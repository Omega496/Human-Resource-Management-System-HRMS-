from src.worker import app

def test_celery_app_initialized():
    assert app is not None
    assert "run_automation_job" in app.tasks
