from celery import Celery
from src.core.config import settings

celery_app = Celery("hrms", broker=settings.REDIS_URL)
