"""
All outbound notifications. Everything runs on Celery so API responses stay fast,
and the two scheduled jobs (beat) automate what the founder asked for:

  * 08:30 Mon-Fri  -> each developer gets an email (+WhatsApp if configured)
                      with exactly today's tasks per project.
  * 18:00 Friday   -> the founder gets one weekly report email per active project.
"""
from core.background import background_task
from django.conf import settings
from django.utils import timezone
from django.template.loader import render_to_string

from .senders import email, whatsapp


@background_task
def send_welcome_email(user_id, password):
    from accounts.models import User
    u = User.objects.get(id=user_id)
    body = (f"Hi {u.first_name},\n\nYou've been added to JMS Delivery Hub.\n"
            f"Login: {u.email}\nTemporary password: {password}\n\n"
            "Open the hub, sign in, and you'll see your daily tasks.\n\n— JMS Tech")
    html_message = render_to_string("notifications/emails/welcome.html", {
        "first_name": u.first_name, "email": u.email, "password": password
    })
    email(u.email, "Your JMS Delivery Hub account", body, html_message=html_message)


@background_task
def send_plan_published(project_id):
    from core.models import Project
    p = Project.objects.get(id=project_id)
    for u in p.team.all():
        n = p.tasks.filter(developer=u).count()
        body = (f"Hi {u.first_name},\n\nA new project has been planned: {p.name}.\n"
                f"You have {n} tasks scheduled between {p.start_date:%d %b} and "
                f"{p.working_days()[-1]:%d %b}.\n\nOpen the hub to see your day-wise plan.\n\n— JMS Delivery Hub")
        html_message = render_to_string("notifications/emails/plan_published.html", {
            "first_name": u.first_name, "project_name": p.name, "task_count": n,
            "start_date": p.start_date.strftime("%d %b"), "end_date": p.working_days()[-1].strftime("%d %b")
        })
        email(u.email, f"New project plan: {p.name}", body, html_message=html_message)
        # whatsapp(u.phone, f"JMS Hub: new project '{p.name}' — {n} tasks assigned to you. Check your daily plan.")


@background_task
def send_plan_adjusted(project_id, week_from):
    from core.models import Project
    p = Project.objects.get(id=project_id)
    for u in p.team.all():
        body = (f"Hi {u.first_name},\n\nThe plan for {p.name} was adjusted from W{week_from} onwards "
                "(scope/FDD change). Completed work is untouched — please review your upcoming tasks.\n\n— JMS Delivery Hub")
        html_message = render_to_string("notifications/emails/plan_adjusted.html", {
            "first_name": u.first_name, "project_name": p.name, "week_from": week_from
        })
        email(u.email, f"Plan updated: {p.name}", body, html_message=html_message)
        # whatsapp(u.phone, f"JMS Hub: plan for '{p.name}' adjusted from W{week_from}. Review your upcoming tasks.")


@background_task
def send_project_update(update_id):
    from core.models import Update
    u = Update.objects.select_related("project").get(id=update_id)
    for member in u.project.team.all():
        body = f"{u.text}\n\n— JMS Delivery Hub"
        html_message = render_to_string("notifications/emails/project_update.html", {
            "first_name": member.first_name, "project_name": u.project.name, "update_text": u.text
        })
        email(member.email, f"Update — {u.project.name}", body, html_message=html_message)
        # whatsapp(member.phone, f"JMS Hub · {u.project.name}: {u.text}")


@background_task
def send_daily_digests():
    """08:30 Mon-Fri: each developer's tasks for today, across all projects."""
    from core.models import Task
    today = timezone.localdate()
    tasks = Task.objects.filter(date=today).select_related("developer", "project")
    by_dev = {}
    for t in tasks:
        by_dev.setdefault(t.developer, []).append(t)
    for dev, items in by_dev.items():
        lines = [f"  D{t.day_num} · {t.project.name} · {t.module}: {t.title}" for t in items]
        body = (f"Good morning {dev.first_name},\n\nYour tasks for {today:%A, %d %b}:\n\n"
                + "\n".join(lines)
                + "\n\nTick them off in the hub as you finish. Have a productive day!\n\n— JMS Delivery Hub")
        ctx_tasks = [{"day_num": t.day_num, "project_name": t.project.name, "module": t.module or "General", "title": t.title} for t in items]
        html_message = render_to_string("notifications/emails/daily_digest.html", {
            "first_name": dev.first_name, "today": today.strftime("%A, %d %b"), "task_count": len(items), "tasks": ctx_tasks
        })
        email(dev.email, f"Today's tasks ({len(items)}) — {today:%d %b}", body, html_message=html_message)
        # whatsapp(dev.phone, f"JMS Hub — today's {len(items)} task(s):\n" + "\n".join(lines[:5]))


@background_task
def send_weekly_reports():
    """Friday 18:00: one report per project that has tasks this week, emailed to the founder."""
    from core.models import Project
    today = timezone.localdate()
    for p in Project.objects.all():
        weeks_active = p.tasks.filter(date__lte=today).values_list("week", flat=True)
        if not weeks_active:
            continue
        email_weekly_report(p.id, max(weeks_active))


@background_task
def email_weekly_report(project_id, week):
    from core.models import Project
    from core.services import weekly_report_text, weekly_report_context
    p = Project.objects.get(id=project_id)
    text_body = weekly_report_text(p, week)
    context = weekly_report_context(p, week)
    html_message = render_to_string("notifications/emails/weekly_report.html", context)
    email(settings.ADMIN_REPORT_EMAIL, f"Weekly Report — {p.name} — W{week}", text_body, html_message=html_message)
