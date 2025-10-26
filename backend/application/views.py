from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Customer, Loan
from .serializers import CustomerSerializer, LoanSerializer
from django.shortcuts import get_object_or_404
from django.db.models import Sum
from .tasks import ingest_excel_files
import math
from datetime import date
import math

def calculate_emi(P, annual_rate, n_months):
    if n_months == 0:
        return 0
    r = annual_rate / 12.0 / 100.0
    if r == 0:
        return P / n_months
    emi = P * r * (1 + r)**n_months / ((1 + r)**n_months - 1)
    return emi

def compute_credit_score(customer: Customer):
    active_loans = customer.loans.filter(is_active=True)
    sum_active_amount = active_loans.aggregate(total=Sum('loan_amount'))['total'] or 0
    if sum_active_amount > customer.approved_limit:
        return 0
    total_emis = customer.loans.aggregate(total=Sum('tenure'))['total'] or 0
    on_time = customer.loans.aggregate(total=Sum('emis_paid_on_time'))['total'] or 0
    past_ratio = (on_time / total_emis) if total_emis > 0 else 1
    num_loans = customer.loans.count()
    this_year = date.today().year
    loan_activity = customer.loans.filter(start_date__year=this_year).count()
    total_past_amount = customer.loans.aggregate(total=Sum('loan_amount'))['total'] or 0
    volume_ratio = min(total_past_amount / (customer.approved_limit or 1), 1)
    score = 0
    score += 40 * past_ratio
    score += 25 * (1 - volume_ratio)
    score += 15 * (1 / (1 + num_loans))
    score += 20 * (1 / (1 + loan_activity))
    score = max(0, min(100, score))
    return round(score, 2)

class RegisterView(APIView):
    def get(self, request):
        return Response({
            "message": "Please send a POST request with the following data",
            "required_fields": {
                "first_name": "string",
                "last_name": "string",
                "age": "integer",
                "monthly_income": "number",
                "phone_number": "string"
            }
        })

    def post(self, request):
        try:
            data = request.data
            # Validate required fields
            required_fields = ['first_name', 'last_name', 'age', 'monthly_income', 'phone_number']
            for field in required_fields:
                if field not in data:
                    return Response(
                        {"error": f"Missing required field: {field}"},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            # Validate data types
            try:
                age = int(data['age'])
                monthly_income = float(data['monthly_income'])
            except (ValueError, TypeError):
                return Response(
                    {"error": "Invalid data types. Age must be an integer and monthly_income must be a number."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Validate age
            if age < 18:
                return Response(
                    {"error": "Customer must be at least 18 years old"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Create customer
            customer = Customer.objects.create(
                first_name=data['first_name'],
                last_name=data['last_name'],
                age=age,
                monthly_salary=monthly_income,
                phone_number=data['phone_number']
            )
            
            serializer = CustomerSerializer(customer)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class CheckEligibilityView(APIView):
    def get(self, request):
        return Response({
            "message": "Please send a POST request with the following data",
            "required_fields": {
                "customer_id": "integer",
                "loan_amount": "number",
                "interest_rate": "number",
                "tenure": "integer"
            }
        })

    def post(self, request):
        customer_id = request.data.get('customer_id')
        loan_amount = float(request.data.get('loan_amount', 0))
        interest_rate = float(request.data.get('interest_rate', 0))
        tenure = int(request.data.get('tenure', 0))
        customer = get_object_or_404(Customer, customer_id=customer_id)
        credit_score = compute_credit_score(customer)
        corrected_interest = interest_rate
        approved = False
        message = ""
        sum_current_emis = customer.loans.filter(is_active=True).aggregate(total=Sum('monthly_repayment'))['total'] or 0
        new_emi = calculate_emi(loan_amount, interest_rate, tenure)
        if (sum_current_emis + new_emi) > 0.5 * customer.monthly_salary:
            approved = False
            message = "Total EMIs would exceed 50% of monthly salary. Not approved."
            return Response({
                "customer_id": customer.customer_id,
                "approval": False,
                "interest_rate": interest_rate,
                "corrected_interest_rate": None,
                "tenure": tenure,
                "monthly_installment": round(new_emi,2),
                "credit_score": credit_score,
                "message": message
            }, status=status.HTTP_200_OK)
        if credit_score == 0:
            approved = False
            message = "Sum of current loans exceeds approved limit. Not eligible."
            return Response({
                "customer_id": customer.customer_id,
                "approval": False,
                "interest_rate": interest_rate,
                "corrected_interest_rate": None,
                "tenure": tenure,
                "monthly_installment": round(new_emi,2),
                "credit_score": credit_score,
                "message": message
            }, status=status.HTTP_200_OK)
        if credit_score > 50:
            approved = True
            corrected_interest = interest_rate
        elif 30 < credit_score <= 50:
            min_rate = 12.0
            if interest_rate <= min_rate:
                corrected_interest = min_rate
            if interest_rate >= min_rate:
                approved = True
        elif 10 < credit_score <= 30:
            min_rate = 16.0
            if interest_rate <= min_rate:
                corrected_interest = min_rate
            if interest_rate >= min_rate:
                approved = True
        else:
            approved = False
        monthly_installment = calculate_emi(loan_amount, corrected_interest, tenure)
        return Response({
            "customer_id": customer.customer_id,
            "approval": bool(approved),
            "interest_rate": interest_rate,
            "corrected_interest_rate": round(corrected_interest,2),
            "tenure": tenure,
            "monthly_installment": round(monthly_installment,2),
            "credit_score": credit_score
        }, status=status.HTTP_200_OK)

class CreateLoanView(APIView):
    def get(self, request):
        return Response({
            "message": "Please send a POST request with the following data",
            "required_fields": {
                "customer_id": "integer",
                "loan_amount": "number",
                "interest_rate": "number",
                "tenure": "integer"
            }
        })

    def post(self, request):
        customer_id = request.data.get('customer_id')
        loan_amount = float(request.data.get('loan_amount', 0))
        interest_rate = float(request.data.get('interest_rate', 0))
        tenure = int(request.data.get('tenure', 0))
        elig_view = CheckEligibilityView()
        class Dummy:
            data = request.data
        res = elig_view.post(Dummy())
        resp_data = res.data
        if not resp_data.get('approval'):
            return Response({
                "loan_id": None,
                "customer_id": customer_id,
                "loan_approved": False,
                "message": resp_data.get('message', 'Loan not approved'),
                "monthly_installment": resp_data.get('monthly_installment')
            }, status=status.HTTP_200_OK)
        customer = get_object_or_404(Customer, customer_id=customer_id)
        corrected_interest = resp_data.get('corrected_interest_rate') or interest_rate
        monthly_installment = resp_data.get('monthly_installment')
        loan = Loan.objects.create(
            customer=customer,
            loan_amount=loan_amount,
            tenure=tenure,
            interest_rate=corrected_interest,
            monthly_repayment=monthly_installment,
            is_active=True
        )
        customer.current_debt = (customer.current_debt or 0) + loan_amount
        customer.save()
        return Response({
            "loan_id": loan.loan_id,
            "customer_id": customer.customer_id,
            "loan_approved": True,
            "message": "Loan approved and created",
            "monthly_installment": round(monthly_installment,2)
        }, status=status.HTTP_201_CREATED)

class ViewLoanView(APIView):
    def get(self, request, loan_id):
        loan = get_object_or_404(Loan, loan_id=loan_id)
        data = {
            "loan_id": loan.loan_id,
            "customer": {
                "id": loan.customer.customer_id,
                "first_name": loan.customer.first_name,
                "last_name": loan.customer.last_name,
                "phone_number": loan.customer.phone_number,
                "age": loan.customer.age,
            },
            "loan_amount": loan.loan_amount,
            "interest_rate": loan.interest_rate,
            "monthly_installment": loan.monthly_repayment,
            "tenure": loan.tenure
        }
        return Response(data, status=status.HTTP_200_OK)

class ViewLoansByCustomer(APIView):
    def get(self, request, customer_id):
        customer = get_object_or_404(Customer, customer_id=customer_id)
        loans = customer.loans.filter(is_active=True)
        items = []
        for loan in loans:
            repayments_left = max(0, loan.tenure - loan.emis_paid_on_time)
            items.append({
                "loan_id": loan.loan_id,
                "loan_amount": loan.loan_amount,
                "interest_rate": loan.interest_rate,
                "monthly_installment": loan.monthly_repayment,
                "repayments_left": repayments_left
            })
        return Response(items, status=status.HTTP_200_OK)
