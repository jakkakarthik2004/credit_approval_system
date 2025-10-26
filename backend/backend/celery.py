import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

application = Celery('backend')
application.config_from_object('django.conf:settings', namespace='CELERY')
application.autodiscover_tasks()
