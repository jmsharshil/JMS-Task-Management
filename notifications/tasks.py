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
def send_password_reset_email(user_id, new_password):
    from accounts.models import User
    u = User.objects.get(id=user_id)
    body = (f"Hi {u.first_name},\n\nYour JMS Delivery Hub password has been reset by an administrator.\n"
            f"Login: {u.email}\nNew password: {new_password}\n\n"
            "Please sign in and change your password.\n\n— JMS Tech")
    html_message = render_to_string("notifications/emails/password_reset.html", {
        "first_name": u.first_name, "email": u.email, "password": new_password
    })
    email(u.email, "Your JMS Delivery Hub password has been reset", body, html_message=html_message)


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
def email_weekly_report(project_id, week, recipient_email=None, custom_text=None):
    from core.models import Project
    from core.services import weekly_report_text, weekly_report_context
    p = Project.objects.get(id=project_id)
    text_body = custom_text if custom_text else weekly_report_text(p, week)
    context = weekly_report_context(p, week)
    if custom_text:
        context["custom_text"] = custom_text
    html_message = render_to_string("notifications/emails/weekly_report.html", context)
    to = [e.strip() for e in recipient_email.split(",")] if recipient_email else [settings.ADMIN_REPORT_EMAIL]
    email(to, f"Weekly Report — {p.name} — W{week}", text_body, html_message=html_message)


@background_task
def email_daily_report(project_id, date_str, recipient_email=None, custom_text=None):
    """Email a daily report with optional custom text and recipients."""
    from datetime import date as date_cls
    from core.models import Project
    from core.services import daily_report_text, daily_report_context
    p = Project.objects.get(id=project_id)
    report_date = date_cls.fromisoformat(date_str)
    text_body = custom_text if custom_text else daily_report_text(p, report_date)
    context = daily_report_context(p, report_date)
    context["text"] = text_body
    html_message = render_to_string("notifications/emails/daily_report.html", context)
    to = [e.strip() for e in recipient_email.split(",")] if recipient_email else [settings.ADMIN_REPORT_EMAIL]
    email(to, f"Daily Report — {p.name} — {report_date.strftime('%d %b %Y')}", text_body, html_message=html_message)


@background_task
def send_task_reminders():
    """3-hourly nudge: email developers who have pending tasks for today."""
    from core.models import Task
    today = timezone.localdate()
    pending = Task.objects.filter(date=today, status="TODO").select_related("developer", "project")
    by_dev = {}
    for t in pending:
        by_dev.setdefault(t.developer, []).append(t)
    for dev, items in by_dev.items():
        ctx_tasks = [{"day_num": t.day_num, "project_name": t.project.name, "module": t.module or "General", "title": t.title} for t in items]
        body = (f"Hi {dev.first_name},\n\nYou still have {len(items)} pending task(s) for today ({today:%d %b}):\n\n"
                + "\n".join(f"  [ ] D{t.day_num} · {t.project.name} · {t.title}" for t in items)
                + "\n\nPlease mark them done in the Hub.\n\n— JMS Delivery Hub")
        html_message = render_to_string("notifications/emails/task_reminder.html", {
            "first_name": dev.first_name, "today": today.strftime("%A, %d %b"),
            "task_count": len(items), "tasks": ctx_tasks
        })
        email(dev.email, f"⏰ {len(items)} pending task(s) — {today:%d %b}", body, html_message=html_message)


@background_task
def archive_weekly_report_pdf(project_id, week):
    """Generate the weekly report PDF and save it as a ProjectDocument."""
    from core.models import Project, ProjectDocument
    from core.services import weekly_report_context, render_report_pdf
    from django.core.files.base import ContentFile
    from django.utils.text import slugify
    p = Project.objects.get(id=project_id)
    context = weekly_report_context(p, week)
    html = render_to_string("notifications/emails/weekly_report.html", context)
    try:
        pdf_bytes = render_report_pdf(html)
    except RuntimeError:
        return  # silently skip if no PDF engine
    filename = f"{slugify(p.name)}_W{week}_report.pdf"
    doc = ProjectDocument(project=p, title=f"Weekly Report W{week} (auto)")
    doc.file.save(filename, ContentFile(pdf_bytes), save=True)


@background_task
def archive_daily_report_pdf(project_id, date_str):
    """Generate the daily report PDF and save it as a ProjectDocument."""
    from datetime import date as date_cls
    from core.models import Project, ProjectDocument
    from core.services import daily_report_context, render_report_pdf
    from django.core.files.base import ContentFile
    from django.utils.text import slugify
    p = Project.objects.get(id=project_id)
    report_date = date_cls.fromisoformat(date_str)
    context = daily_report_context(p, report_date)
    html = render_to_string("notifications/emails/daily_report.html", context)
    try:
        pdf_bytes = render_report_pdf(html)
    except RuntimeError:
        return
    filename = f"{slugify(p.name)}_{date_str}_daily_report.pdf"
    doc = ProjectDocument(project=p, title=f"Daily Report {date_str} (auto)")
    doc.file.save(filename, ContentFile(pdf_bytes), save=True)


@background_task
def send_adhoc_task_assigned(task_id):
    """Email the assignee when an ad-hoc task is assigned to them."""
    from core.models import AdHocTask
    t = AdHocTask.objects.select_related("created_by").prefetch_related("assignees").get(id=task_id)
    assignees = t.assignees.all()
    if not assignees:
        return

    for u in assignees:
        body = (f"Hi {u.first_name},\n\n{t.created_by.get_full_name()} assigned you a new task:\n\n"
                f"  {t.title}\n  Priority: {t.priority}\n  Due: {t.due_date:%d %b %Y}\n\n"
                f"Open the Hub to view details.\n\n— JMS Delivery Hub")
        html_message = render_to_string("notifications/emails/task_assigned.html", {
            "first_name": u.first_name,
            "created_by_name": t.created_by.get_full_name(),
            "task_title": t.title,
            "description": t.description,
            "priority": t.priority,
            "start_date": t.start_date.strftime("%d %b %Y") if t.start_date else None,
            "due_date": t.due_date.strftime("%d %b %Y"),
        })
        email(u.email, f"New task assigned: {t.title}", body, html_message=html_message)


@background_task
def email_custom_range_report(project_id, date_from_str, date_to_str, recipient_email=None, custom_text=None):
    """Email a custom date-range report for a project."""
    from datetime import date as date_cls
    from core.models import Project
    from core.services import custom_range_report_text, custom_range_report_context
    p = Project.objects.get(id=project_id)
    date_from = date_cls.fromisoformat(date_from_str)
    date_to = date_cls.fromisoformat(date_to_str)
    text_body = custom_text if custom_text else custom_range_report_text(p, date_from, date_to)
    context = custom_range_report_context(p, date_from, date_to)
    html_message = render_to_string("notifications/emails/custom_range_report.html", context)
    to = [e.strip() for e in recipient_email.split(',')] if recipient_email else [settings.ADMIN_REPORT_EMAIL]
    email(
        to,
        f"Task Report — {p.name} — {date_from.strftime('%d %b')} to {date_to.strftime('%d %b %Y')}",
        text_body,
        html_message=html_message
    )


@background_task
def email_mom(mom_id, recipient_email=None):
    """Email a Minutes of Meeting document."""
    from core.models import MeetingMinutes
    mom = MeetingMinutes.objects.select_related("project").get(id=mom_id)
    ctx = {
        "project_name": mom.project.name,
        "mom_title": mom.title,
        "meeting_date": mom.meeting_date.strftime("%d %b %Y"),
        "attendees": mom.attendees,
        "agenda": mom.agenda,
        "discussion": mom.discussion,
        "decisions": mom.decisions,
        "action_items": mom.action_items,
        "next_meeting_date": mom.next_meeting_date.strftime("%d %b %Y") if mom.next_meeting_date else None,
    }
    html_message = render_to_string("notifications/emails/mom.html", ctx)
    body = (
        f"MOM: {mom.title}\n"
        f"Project: {mom.project.name}\n"
        f"Date: {mom.meeting_date.strftime('%d %b %Y')}\n\n"
        f"Attendees: {mom.attendees}\n\n"
        f"--- Action Items ---\n{mom.action_items}\n\n"
        f"— JMS Delivery Hub"
    )
    to = [e.strip() for e in recipient_email.split(',')] if recipient_email else [settings.ADMIN_REPORT_EMAIL]
    email(to, f"MOM: {mom.title} — {mom.project.name}", body, html_message=html_message)
