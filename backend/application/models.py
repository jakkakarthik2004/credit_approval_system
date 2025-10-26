from django.db import models
from django.utils import timezone
import math

class Customer(models.Model):
    customer_id = models.AutoField(primary_key=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    age = models.IntegerField(null=True, blank=True)
    phone_number = models.CharField(max_length=20)
    monthly_salary = models.FloatField(default=0)
    approved_limit = models.FloatField(default=0)
    current_debt = models.FloatField(default=0)

    def save(self, *args, **kwargs):
        if not self.approved_limit:
            val = 36 * self.monthly_salary
            self.approved_limit = round(val / 100000) * 100000
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.customer_id} - {self.first_name} {self.last_name}"

class Loan(models.Model):
    loan_id = models.AutoField(primary_key=True)
    customer = models.ForeignKey(Customer, related_name='loans', on_delete=models.CASCADE)
    loan_amount = models.FloatField()
    tenure = models.IntegerField()
    interest_rate = models.FloatField()
    monthly_repayment = models.FloatField()
    emis_paid_on_time = models.IntegerField(default=0)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)  

    def __str__(self):
        return f"Loan {self.loan_id} for Customer {self.customer_id}"
