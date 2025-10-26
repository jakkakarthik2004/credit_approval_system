FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONBUFFERED 1

WORKDIR /application

COPY requirements.txt /application/
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

COPY . /application/

EXPOSE 8000
