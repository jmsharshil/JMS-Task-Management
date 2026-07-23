import time
import importlib
import threading
from concurrent.futures import ThreadPoolExecutor
from django.utils import timezone
from django.db import close_old_connections
from core.models import BackgroundJob

def process_queue(executor):
    # Fetch pending jobs
    jobs = BackgroundJob.objects.filter(status=BackgroundJob.Status.PENDING)
    for job in jobs:
        # Mark as running immediately to avoid duplicate processing
        job.status = BackgroundJob.Status.RUNNING
        job.save(update_fields=['status'])
        executor.submit(execute_job, job.id)

def execute_job(job_id):
    close_old_connections()
    job = BackgroundJob.objects.get(id=job_id)
    try:
        module_name, func_name = job.task_name.rsplit('.', 1)
        module = importlib.import_module(module_name)
        func = getattr(module, func_name)
        
        if hasattr(func, 'execute'):
            func.execute(*job.args, **job.kwargs)
        else:
            func(*job.args, **job.kwargs)
            
        job.status = BackgroundJob.Status.DONE
        job.save(update_fields=['status', 'updated_at'])
    except Exception as e:
        job.retry_count += 1
        job.error_log = str(e)
        if job.retry_count >= job.max_retry:
            job.status = BackgroundJob.Status.FAILED
        else:
            job.status = BackgroundJob.Status.PENDING # Retry later
        job.save(update_fields=['status', 'error_log', 'retry_count', 'updated_at'])

def check_scheduled_tasks():
    now = timezone.localtime()

    # 08:30 Mon-Fri - daily digest
    if now.weekday() < 5 and now.hour == 8 and now.minute >= 30:
        ran_today = BackgroundJob.objects.filter(
            task_name="notifications.tasks.send_daily_digests",
            created_at__date=now.date()
        ).exists()
        if not ran_today:
            from notifications.tasks import send_daily_digests
            send_daily_digests() # Enqueues job

    # 18:00 Friday - weekly report
    if now.weekday() == 4 and now.hour >= 18:
        ran_today = BackgroundJob.objects.filter(
            task_name="notifications.tasks.send_weekly_reports",
            created_at__date=now.date()
        ).exists()
        if not ran_today:
            from notifications.tasks import send_weekly_reports
            send_weekly_reports() # Enqueues job

    # 3-hourly task reminders at 12, 15, 18 Mon-Fri
    if now.weekday() < 5 and now.hour in (12, 15, 18):
        key = f"notifications.tasks.send_task_reminders"
        ran_this_hour = BackgroundJob.objects.filter(
            task_name=key,
            created_at__date=now.date(),
            created_at__hour=now.hour
        ).exists()
        if not ran_this_hour:
            from notifications.tasks import send_task_reminders
            send_task_reminders()

    # 18:30 Mon-Fri - archive daily report PDFs
    if now.weekday() < 5 and now.hour >= 18 and now.minute >= 30:
        key = "notifications.tasks.archive_daily_report_pdf"
        ran_today = BackgroundJob.objects.filter(
            task_name=key,
            created_at__date=now.date()
        ).exists()
        if not ran_today:
            from core.models import Project
            from notifications.tasks import archive_daily_report_pdf
            today_str = now.date().isoformat()
            for p in Project.objects.all():
                if p.tasks.filter(date=now.date()).exists():
                    archive_daily_report_pdf(p.id, today_str)

    # 18:30 Friday - archive weekly report PDFs
    if now.weekday() == 4 and now.hour >= 18 and now.minute >= 30:
        key = "notifications.tasks.archive_weekly_report_pdf"
        ran_today = BackgroundJob.objects.filter(
            task_name=key,
            created_at__date=now.date()
        ).exists()
        if not ran_today:
            from core.models import Project
            from notifications.tasks import archive_weekly_report_pdf
            today = now.date()
            for p in Project.objects.all():
                weeks_active = p.tasks.filter(date__lte=today).values_list("week", flat=True)
                if weeks_active:
                    archive_weekly_report_pdf(p.id, max(weeks_active))

    # Cleanup already run tasks (dead threads) to keep DB clean
    BackgroundJob.objects.filter(status=BackgroundJob.Status.DONE).delete()

def run_scheduler_loop():
    executor = ThreadPoolExecutor(max_workers=5)
    while True:
        try:
            close_old_connections()
            check_scheduled_tasks()
            process_queue(executor)
        except Exception as e:
            print(f"Scheduler loop error: {e}")
        time.sleep(10) # Poll every 10 seconds

def start_scheduler():
    # Run the scheduler in a daemon thread so it doesn't block Django
    thread = threading.Thread(target=run_scheduler_loop, daemon=True)
    thread.start()
