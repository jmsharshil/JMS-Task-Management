"""Plan orchestration + report building (pure functions used by views & celery)."""
from datetime import date as date_cls
from django.utils import timezone
from ai import planner
from .models import Task


def _fmt(d):
    return d.strftime("%d %b")


def build_plan_rows(project_name, weeks, devs, working_days, brief,
                    leaders=None, week_from=1, change_note="", done_titles=None):
    """
    devs: list of user objects. leaders: optional list of leader users.
    brief may contain "architecture" from approved ProjectArchitecture.
    Returns list of dicts: {day_num, date, week, developer_id, module, title}
    Passes normalized leaders + full brief (with arch context) to planner.weekly_plan()
    and daily_tasks() for AI alignment and leader bias.
    """
    dev_pairs = [(u.get_full_name() or u.email, u.designation or "Developer") for u in devs]
    by_name = { (u.get_full_name() or u.email).lower(): u for u in devs }
    lead_list = None
    if leaders:
        lead_list = [(u.get_full_name() or u.email, u.designation or "Lead") for u in leaders]

    weekly = planner.weekly_plan(project_name, weeks, dev_pairs, brief, leaders=lead_list,
                                 week_from=week_from, change_note=change_note,
                                 done_titles=done_titles)
    rows = []
    for w in range(week_from, weeks + 1):
        wk = next((x for x in weekly if x.get("week") == w), {"focus": "", "modules": []})
        labels = [f"D{(w-1)*5 + i + 1} ({_fmt(working_days[(w-1)*5 + i])})" for i in range(5)
                  if (w-1)*5 + i < len(working_days)]
        out = planner.daily_tasks(project_name, weeks, w, wk.get("focus", ""),
                                  wk.get("modules", []), dev_pairs, labels, leaders=lead_list,
                                  brief=brief, change_note=change_note)
        for t in out:
            try:
                day_num = int("".join(ch for ch in str(t.get("day", "")) if ch.isdigit()))
            except ValueError:
                continue
            if not (1 <= day_num <= len(working_days)):
                continue
            dev = by_name.get(str(t.get("dev", "")).lower()) or devs[0]
            rows.append({
                "day_num": day_num, "date": working_days[day_num - 1],
                "week": (day_num - 1) // 5 + 1, "developer_id": dev.id,
                "module": (t.get("module") or "General")[:60],
                "title": (t.get("task") or "Task")[:240],
            })
    rows.sort(key=lambda r: (r["date"], r["developer_id"]))
    return rows


def weekly_report_context(project, week):
    tasks = list(project.tasks.filter(week=week).select_related("developer"))
    all_tasks = project.tasks.all()
    total = all_tasks.count()
    done_all = all_tasks.filter(status="DONE").count()
    done_wk = [t for t in tasks if t.status == "DONE"]
    pend_wk = [t for t in tasks if t.status != "DONE"]

    by_dev = {}
    for t in tasks:
        n = t.developer.get_full_name() or t.developer.email
        by_dev.setdefault(n, {"name": n, "done": 0, "total": 0, "pct": 0})
        by_dev[n]["total"] += 1
        if t.status == "DONE":
            by_dev[n]["done"] += 1
            
    devs = []
    for stat in by_dev.values():
        stat["pct"] = round((stat["done"] / stat["total"]) * 100) if stat["total"] else 0
        devs.append(stat)

    dates = sorted(t.date for t in tasks) or [project.start_date]
    
    completed_tasks = [
        {"day_num": t.day_num, "dev_name": t.developer.get_full_name() or t.developer.email, "module": (t.module or "General")[:60], "title": t.title[:240]} 
        for t in done_wk
    ]
    pending_tasks = [
        {"day_num": t.day_num, "dev_name": t.developer.get_full_name() or t.developer.email, "module": (t.module or "General")[:60], "title": t.title[:240]} 
        for t in pend_wk
    ]

    return {
        "project_name": project.name,
        "project_ref": project.ref,
        "client_name": project.client.name if project.client else None,
        "week": week,
        "week_start": _fmt(dates[0]),
        "week_end": _fmt(dates[-1]),
        "generated_date": timezone.localdate().strftime('%a, %d %b %Y'),
        "overall_pct": round(done_all/total*100) if total else 0,
        "done_all": done_all,
        "total": total,
        "week_pct": round(len(done_wk)/len(tasks)*100) if tasks else 0,
        "done_week": len(done_wk),
        "total_week": len(tasks),
        "devs": devs,
        "completed_tasks": completed_tasks,
        "pending_tasks": pending_tasks,
        "milestones": list(project.milestones.select_related("owner").all()),
    }


class SafeDict(dict):
    def __missing__(self, key):
        return '{' + key + '}'

def weekly_report_text(project, week):
    """Plain-text weekly report — uses format template if available."""
    tasks = list(project.tasks.filter(week=week).select_related("developer"))
    all_tasks = project.tasks.all()
    total, done_all = all_tasks.count(), all_tasks.filter(status="DONE").count()
    done_wk = [t for t in tasks if t.status == "DONE"]
    pend_wk = [t for t in tasks if t.status != "DONE"]

    # Check for custom format
    if hasattr(project, "report_template") and project.report_template.weekly_format:
        fmt_str = project.report_template.weekly_format
        completed = "\n".join(f"  [x] D{t.day_num} — {t.module}: {t.title} ({t.developer.get_full_name() or t.developer.email})" for t in done_wk) or "  (none)"
        pending = "\n".join(f"  [ ] D{t.day_num} — {t.module}: {t.title} ({t.developer.get_full_name() or t.developer.email})" for t in pend_wk) or "  (none)"
        try:
            return fmt_str.format_map(SafeDict(
                project=project.name,
                week=week,
                done=len(done_wk),
                total=len(tasks),
                pct=round(len(done_wk)/len(tasks)*100) if tasks else 0,
                completed=completed,
                pending=pending
            ))
        except Exception:
            pass # fallback to default

    dates = sorted(t.date for t in tasks) or [project.start_date]
    lines = [
        "JMS TECH — WEEKLY PROJECT REPORT",
        f"Project: {project.name}" + (f" ({project.ref})" if project.ref else ""),
        f"Client: {project.client.name if project.client else '—'}",
        f"Week: W{week} ({_fmt(dates[0])} – {_fmt(dates[-1])})",
        f"Generated: {timezone.localdate().strftime('%a, %d %b %Y')}",
        "",
        f"OVERALL PROJECT: {done_all}/{total} tasks complete ({round(done_all/total*100) if total else 0}%)",
        f"THIS WEEK: {len(done_wk)}/{len(tasks)} tasks complete ({round(len(done_wk)/len(tasks)*100) if tasks else 0}%)",
        "",
        "COMPLETED THIS WEEK",
        *([f"  [x] D{t.day_num} — {t.module}: {t.title}" for t in done_wk] or ["  (none yet)"]),
        "",
        "PENDING / CARRIED FORWARD",
        *([f"  [ ] D{t.day_num} — {t.module}: {t.title}" for t in pend_wk] or ["  (nothing pending — week fully complete)"]),
        "",
        "— Generated by JMS Delivery Hub",
    ]
    return "\n".join(lines)

    by_dev = {}
    for t in tasks:
        n = t.developer.get_full_name() or t.developer.email
        by_dev.setdefault(n, [0, 0])
        by_dev[n][1] += 1
        if t.status == "DONE":
            by_dev[n][0] += 1

    dates = sorted(t.date for t in tasks) or [project.start_date]
    lines = [
        "JMS TECH — WEEKLY PROJECT REPORT",
        f"Project: {project.name}" + (f" ({project.ref})" if project.ref else ""),
        f"Client: {project.client.name if project.client else '—'}",
        f"Week: W{week} ({_fmt(dates[0])} – {_fmt(dates[-1])})",
        f"Generated: {timezone.localdate().strftime('%a, %d %b %Y')}",
        "",
        f"OVERALL PROJECT: {done_all}/{total} tasks complete ({round(done_all/total*100) if total else 0}%)",
        f"THIS WEEK: {len(done_wk)}/{len(tasks)} tasks complete ({round(len(done_wk)/len(tasks)*100) if tasks else 0}%)",
        "",
        "COMPLETED THIS WEEK",
        *([f"  [x] D{t.day_num} — {t.module}: {t.title}" for t in done_wk] or ["  (none yet)"]),
        "",
        "PENDING / CARRIED FORWARD",
        *([f"  [ ] D{t.day_num} — {t.module}: {t.title}" for t in pend_wk] or ["  (nothing pending — week fully complete)"]),
        "",
        "— Generated by JMS Delivery Hub",
    ]
    return "\n".join(lines)


def summary_stats_text(project):
    today = timezone.localdate()
    tasks = list(project.tasks.select_related("developer"))
    done = [t for t in tasks if t.status == "DONE"]
    overdue = [t for t in tasks if t.status != "DONE" and t.date < today]
    by_dev = {}
    for t in tasks:
        n = t.developer.get_full_name() or t.developer.email
        s = by_dev.setdefault(n, {"d": 0, "t": 0, "o": 0})
        s["t"] += 1
        if t.status == "DONE":
            s["d"] += 1
        elif t.date < today:
            s["o"] += 1
    updates = list(project.updates.all()[:3])
    return (
        f"Project: {project.name}, {project.weeks} weeks, started {project.start_date}, today {today}.\n"
        f"Overall: {len(done)}/{len(tasks)} tasks done. Overdue: {len(overdue)}.\n"
        f"Per developer (done/total, overdue): "
        + "; ".join(f"{n} {s['d']}/{s['t']} ({s['o']} overdue)" for n, s in by_dev.items()) + ".\n"
        f"Overdue items: "
        + ("; ".join(f"{t.developer.get_full_name()}: {t.title}" for t in overdue[:12]) or "none") + ".\n"
        f"Recently completed: " + ("; ".join(t.title for t in done[-10:]) or "none") + ".\n"
        f"Latest team updates: " + (" | ".join(u.text for u in updates) or "none")
    )


# ---------- Daily report ----------

def daily_report_context(project, report_date):
    """Build context for a single-day project report."""
    tasks = list(project.tasks.filter(date=report_date).select_related("developer"))
    all_tasks = project.tasks.all()
    total = all_tasks.count()
    done_all = all_tasks.filter(status="DONE").count()
    done_day = [t for t in tasks if t.status == "DONE"]
    pend_day = [t for t in tasks if t.status != "DONE"]

    by_dev = {}
    for t in tasks:
        n = t.developer.get_full_name() or t.developer.email
        by_dev.setdefault(n, {"name": n, "done": 0, "total": 0, "pct": 0})
        by_dev[n]["total"] += 1
        if t.status == "DONE":
            by_dev[n]["done"] += 1

    devs = []
    for stat in by_dev.values():
        stat["pct"] = round((stat["done"] / stat["total"]) * 100) if stat["total"] else 0
        devs.append(stat)

    completed_tasks = [
        {"day_num": t.day_num, "dev_name": t.developer.get_full_name() or t.developer.email,
         "module": (t.module or "General")[:60], "title": t.title[:240]}
        for t in done_day
    ]
    pending_tasks = [
        {"day_num": t.day_num, "dev_name": t.developer.get_full_name() or t.developer.email,
         "module": (t.module or "General")[:60], "title": t.title[:240]}
        for t in pend_day
    ]

    return {
        "project_name": project.name,
        "project_ref": project.ref,
        "client_name": project.client.name if project.client else None,
        "report_date": report_date.strftime("%A, %d %b %Y"),
        "report_date_short": _fmt(report_date),
        "generated_date": timezone.localdate().strftime('%a, %d %b %Y'),
        "overall_pct": round(done_all / total * 100) if total else 0,
        "done_all": done_all,
        "total": total,
        "day_pct": round(len(done_day) / len(tasks) * 100) if tasks else 0,
        "done_day": len(done_day),
        "total_day": len(tasks),
        "devs": devs,
        "completed_tasks": completed_tasks,
        "pending_tasks": pending_tasks,
        "milestones": list(project.milestones.select_related("owner").all()),
    }


def daily_report_text(project, report_date):
    """Plain-text daily report."""
    tasks = list(project.tasks.filter(date=report_date).select_related("developer"))
    all_tasks = project.tasks.all()
    total, done_all = all_tasks.count(), all_tasks.filter(status="DONE").count()
    done_day = [t for t in tasks if t.status == "DONE"]
    pend_day = [t for t in tasks if t.status != "DONE"]

    # Check for custom format
    if hasattr(project, "report_template") and project.report_template.daily_format:
        fmt_str = project.report_template.daily_format
        completed = "\n".join(f"  [x] D{t.day_num} — {t.module}: {t.title} ({t.developer.get_full_name() or t.developer.email})" for t in done_day) or "  (none)"
        pending = "\n".join(f"  [ ] D{t.day_num} — {t.module}: {t.title} ({t.developer.get_full_name() or t.developer.email})" for t in pend_day) or "  (none)"
        try:
            return fmt_str.format_map(SafeDict(
                project=project.name,
                date=report_date.strftime("%d %b %Y"),
                done_today=len(done_day),
                total_today=len(tasks),
                overall_pct=round(done_all/total*100) if total else 0,
                completed=completed,
                pending=pending
            ))
        except Exception:
            pass

    lines = [
        "JMS TECH — DAILY PROJECT REPORT",
        f"Project: {project.name}" + (f" ({project.ref})" if project.ref else ""),
        f"Client: {project.client.name if project.client else '—'}",
        f"Date: {report_date.strftime('%A, %d %b %Y')}",
        f"Generated: {timezone.localdate().strftime('%a, %d %b %Y')}",
        "",
        f"OVERALL PROJECT: {done_all}/{total} tasks complete ({round(done_all/total*100) if total else 0}%)",
        f"TODAY: {len(done_day)}/{len(tasks)} tasks complete ({round(len(done_day)/len(tasks)*100) if tasks else 0}%)",
        "",
        "COMPLETED TODAY",
        *([f"  [x] D{t.day_num} — {t.module}: {t.title}" for t in done_day] or ["  (none yet)"]),
        "",
        "PENDING / NOT DONE",
        *([f"  [ ] D{t.day_num} — {t.module}: {t.title}" for t in pend_day] or ["  (everything done — great work!)"]),
        "— Generated by JMS Delivery Hub",
    ]

    milestones = list(project.milestones.select_related("owner").all())
    if milestones:
        lines.extend([
            "",
            "PROJECT MILESTONES",
            "--------------------------------------------------------------------------------",
            "| Open Item | Status | Owner | Dependency | Next Milestone | Committed Date | Final Closure | Risk / Blocker & Action |",
            "--------------------------------------------------------------------------------"
        ])
        for m in milestones:
            owner = m.owner.get_full_name() if m.owner else "-"
            lines.append(f"| {m.title} | {m.get_status_display()} | {owner} | {m.stakeholder_dependency or '-'} | {m.next_milestone_desc or '-'} | {m.committed_date or '-'} | {m.final_completion_date or '-'} | {m.blocker or '-'} |")
        lines.append("--------------------------------------------------------------------------------")

    return "\n".join(lines)

    lines = [
        "JMS TECH — DAILY PROJECT REPORT",
        f"Project: {project.name}" + (f" ({project.ref})" if project.ref else ""),
        f"Client: {project.client.name if project.client else '—'}",
        f"Date: {report_date.strftime('%A, %d %b %Y')}",
        f"Generated: {timezone.localdate().strftime('%a, %d %b %Y')}",
        "",
        f"OVERALL PROJECT: {done_all}/{total} tasks complete ({round(done_all/total*100) if total else 0}%)",
        f"TODAY: {len(done_day)}/{len(tasks)} tasks complete ({round(len(done_day)/len(tasks)*100) if tasks else 0}%)",
        "",
        "COMPLETED TODAY",
        *([f"  [x] D{t.day_num} — {t.module}: {t.title}" for t in done_day] or ["  (none yet)"]),
        "",
        "PENDING / NOT DONE",
        *([f"  [ ] D{t.day_num} — {t.module}: {t.title}" for t in pend_day] or ["  (everything done — great work!)"]),
        "",
        "— Generated by JMS Delivery Hub",
    ]
    return "\n".join(lines)


# ---------- Custom date range report ----------

def custom_range_report_context(project, date_from, date_to):
    """Build context for a custom date range project report."""
    tasks = list(project.tasks.filter(date__gte=date_from, date__lte=date_to).select_related("developer"))
    all_tasks = project.tasks.all()
    total = all_tasks.count()
    done_all = all_tasks.filter(status="DONE").count()
    done_range = [t for t in tasks if t.status == "DONE"]
    pend_range = [t for t in tasks if t.status != "DONE"]

    by_dev = {}
    for t in tasks:
        n = t.developer.get_full_name() or t.developer.email
        by_dev.setdefault(n, {"name": n, "done": 0, "total": 0, "pct": 0})
        by_dev[n]["total"] += 1
        if t.status == "DONE":
            by_dev[n]["done"] += 1

    devs = []
    for stat in by_dev.values():
        stat["pct"] = round((stat["done"] / stat["total"]) * 100) if stat["total"] else 0
        devs.append(stat)

    completed_tasks = [
        {"day_num": t.day_num, "dev_name": t.developer.get_full_name() or t.developer.email,
         "module": (t.module or "General")[:60], "title": t.title[:240]}
        for t in done_range
    ]
    pending_tasks = [
        {"day_num": t.day_num, "dev_name": t.developer.get_full_name() or t.developer.email,
         "module": (t.module or "General")[:60], "title": t.title[:240]}
        for t in pend_range
    ]

    return {
        "project_name": project.name,
        "project_ref": project.ref,
        "client_name": project.client.name if project.client else None,
        "date_from": date_from.strftime("%d %b %Y"),
        "date_to": date_to.strftime("%d %b %Y"),
        "report_type": "Custom Range",
        "generated_date": timezone.localdate().strftime('%a, %d %b %Y'),
        "overall_pct": round(done_all / total * 100) if total else 0,
        "done_all": done_all,
        "total": total,
        "range_pct": round(len(done_range) / len(tasks) * 100) if tasks else 0,
        "done_range": len(done_range),
        "total_range": len(tasks),
        "devs": devs,
        "completed_tasks": completed_tasks,
        "pending_tasks": pending_tasks,
    }


def custom_range_report_text(project, date_from, date_to):
    """Plain-text custom date range report."""
    tasks = list(project.tasks.filter(date__gte=date_from, date__lte=date_to).select_related("developer"))
    all_tasks = project.tasks.all()
    total, done_all = all_tasks.count(), all_tasks.filter(status="DONE").count()
    done_range = [t for t in tasks if t.status == "DONE"]
    pend_range = [t for t in tasks if t.status != "DONE"]

    # Check for custom format
    if hasattr(project, "report_template") and project.report_template.custom_format:
        fmt_str = project.report_template.custom_format
        completed = "\n".join(f"  [x] D{t.day_num} — {t.module}: {t.title} ({t.developer.get_full_name() or t.developer.email})" for t in done_range) or "  (none)"
        pending = "\n".join(f"  [ ] D{t.day_num} — {t.module}: {t.title} ({t.developer.get_full_name() or t.developer.email})" for t in pend_range) or "  (none)"
        try:
            return fmt_str.format_map(SafeDict(
                project=project.name,
                date_from=date_from.strftime("%d %b %Y"),
                date_to=date_to.strftime("%d %b %Y"),
                done_range=len(done_range),
                total_range=len(tasks),
                pct=round(len(done_range)/len(tasks)*100) if tasks else 0,
                completed=completed,
                pending=pending
            ))
        except Exception:
            pass

    lines = [
        "JMS TECH — CUSTOM RANGE PROJECT REPORT",
        f"Project: {project.name}" + (f" ({project.ref})" if project.ref else ""),
        f"Client: {project.client.name if project.client else '—'}",
        f"Period: {date_from.strftime('%d %b %Y')} — {date_to.strftime('%d %b %Y')}",
        f"Generated: {timezone.localdate().strftime('%a, %d %b %Y')}",
        "",
        f"OVERALL PROJECT: {done_all}/{total} tasks complete ({round(done_all/total*100) if total else 0}%)",
        f"THIS PERIOD: {len(done_range)}/{len(tasks)} tasks complete ({round(len(done_range)/len(tasks)*100) if tasks else 0}%)",
        "",
        "COMPLETED IN PERIOD",
        *([f"  [x] D{t.day_num} — {t.module}: {t.title}" for t in done_range] or ["  (none yet)"]),
        "",
        "PENDING / NOT DONE",
        *([f"  [ ] D{t.day_num} — {t.module}: {t.title}" for t in pend_range] or ["  (all done!)"]),
        "",
        "— Generated by JMS Delivery Hub",
    ]

    milestones = list(project.milestones.select_related("owner").all())
    if milestones:
        lines.extend([
            "",
            "PROJECT MILESTONES",
            "--------------------------------------------------------------------------------",
            "| Open Item | Status | Owner | Dependency | Next Milestone | Committed Date | Final Closure | Risk / Blocker & Action |",
            "--------------------------------------------------------------------------------"
        ])
        for m in milestones:
            owner = m.owner.get_full_name() if m.owner else "-"
            lines.append(f"| {m.title} | {m.get_status_display()} | {owner} | {m.stakeholder_dependency or '-'} | {m.next_milestone_desc or '-'} | {m.committed_date or '-'} | {m.final_completion_date or '-'} | {m.blocker or '-'} |")
        lines.append("--------------------------------------------------------------------------------")

    return "\n".join(lines)

    lines = [
        "JMS TECH — CUSTOM RANGE PROJECT REPORT",
        f"Project: {project.name}" + (f" ({project.ref})" if project.ref else ""),
        f"Client: {project.client.name if project.client else '—'}",
        f"Period: {date_from.strftime('%d %b %Y')} — {date_to.strftime('%d %b %Y')}",
        f"Generated: {timezone.localdate().strftime('%a, %d %b %Y')}",
        "",
        f"OVERALL PROJECT: {done_all}/{total} tasks complete ({round(done_all/total*100) if total else 0}%)",
        f"THIS PERIOD: {len(done_range)}/{len(tasks)} tasks complete ({round(len(done_range)/len(tasks)*100) if tasks else 0}%)",
        "",
        "COMPLETED IN PERIOD",
        *([f"  [x] D{t.day_num} — {t.module}: {t.title}" for t in done_range] or ["  (none yet)"]),
        "",
        "PENDING / NOT DONE",
        *([f"  [ ] D{t.day_num} — {t.module}: {t.title}" for t in pend_range] or ["  (all done!)"]),
        "",
        "— Generated by JMS Delivery Hub",
    ]
    return "\n".join(lines)


# ---------- MOM PDF ----------

def mom_pdf_sections(mom):
    """Build ReportLab-friendly sections for a MOM PDF."""
    sections = []
    if mom.attendees:
        sections.append(("Attendees", mom.attendees))
    if mom.agenda:
        sections.append(("Agenda", mom.agenda))
    if mom.discussion:
        sections.append(("Discussion", mom.discussion))
    if mom.decisions:
        sections.append(("Decisions", mom.decisions))
    if mom.action_items:
        sections.append(("Action Items", mom.action_items))
    if mom.next_meeting_date:
        sections.append(("Next Meeting", mom.next_meeting_date.strftime("%d %b %Y")))
    return sections


# ---------- PDF rendering ----------

def _embed_external_images(html_string):
    """
    Replace external img src="https://..." with base64 data URIs so PDF
    renderers that cannot make HTTP requests (xhtml2pdf) can display images.
    Also strips width/height attributes that cause xhtml2pdf to missize logos.
    """
    import re, base64
    try:
        from urllib.request import urlopen
        from urllib.error import URLError
    except ImportError:
        return html_string

    def _to_data_uri(match):
        url = match.group(1)
        try:
            with urlopen(url, timeout=6) as resp:
                ct = resp.headers.get_content_type() or "image/png"
                data = base64.b64encode(resp.read()).decode()
                return f'src="data:{ct};base64,{data}"'
        except Exception:
            return match.group(0)   # keep original if fetch fails

    return re.sub(r'src="(https?://[^"]+)"', _to_data_uri, html_string)


def _render_pdf_reportlab(title, sections):
    """
    Professional PDF using ReportLab as a last-resort fallback.
    sections: list of (heading, body_text) tuples.
    Returns bytes or raises ImportError.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER
    import io

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            rightMargin=2*cm, leftMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    try:
        from .models import OrganizationSettings
        org = OrganizationSettings.get()
        brand_color = colors.HexColor(org.pdf_accent_color or "#D6222A")
    except Exception:
        brand_color = colors.HexColor("#D6222A")
        
    dark_color = colors.HexColor("#1A1D23")

    title_style = ParagraphStyle("Title", parent=styles["Title"],
                                 fontSize=20, textColor=brand_color,
                                 spaceAfter=6, fontName="Helvetica-Bold")
    h2_style = ParagraphStyle("H2", parent=styles["Heading2"],
                              fontSize=13, textColor=dark_color,
                              spaceBefore=14, spaceAfter=4, fontName="Helvetica-Bold")
    body_style = ParagraphStyle("Body", parent=styles["Normal"],
                                fontSize=10, leading=15, textColor=colors.HexColor("#374151"))

    story = []
    story.append(Paragraph("JMS Tech — Delivery Hub", ParagraphStyle(
        "Brand", fontSize=9, textColor=colors.gray, spaceAfter=2)))
    story.append(Paragraph(title, title_style))
    story.append(HRFlowable(width="100%", thickness=2, color=brand_color, spaceAfter=12))

    for heading, body in sections:
        if heading:
            story.append(Paragraph(heading, h2_style))
        if body:
            for line in body.split("\n"):
                line = line.strip()
                if line:
                    story.append(Paragraph(line, body_style))
                else:
                    story.append(Spacer(1, 4))
        story.append(Spacer(1, 8))

    doc.build(story)
    return buf.getvalue()


def render_report_pdf(html_string, title="Report", sections=None):
    """
    Render HTML string to PDF bytes.
    Tries: 1) WeasyPrint  2) xhtml2pdf  3) ReportLab (plain but professional).
    If all fail, raises RuntimeError.
    """
    # 1. WeasyPrint
    try:
        from weasyprint import HTML
        return HTML(string=html_string).write_pdf()
    except (ImportError, OSError, Exception) as e:
        _wp_err = str(e)

    # 2. xhtml2pdf
    try:
        import io
        from xhtml2pdf import pisa
        html_string_embedded = _embed_external_images(html_string)
        buf = io.BytesIO()
        pisa_status = pisa.CreatePDF(html_string_embedded, dest=buf)
        if not pisa_status.err:
            return buf.getvalue()
    except (ImportError, Exception):
        pass

    # 3. ReportLab (plain, always works)
    try:
        if sections is None:
            # Extract plain text from html as last-resort sections
            import re
            plain = re.sub(r"<[^>]+>", " ", html_string)
            plain = re.sub(r"\s+", " ", plain).strip()
            sections = [("Report Content", plain)]
        return _render_pdf_reportlab(title, sections)
    except ImportError:
        raise RuntimeError(
            "No PDF library available. Install one of: weasyprint, xhtml2pdf, or reportlab.\n"
            "  pip install weasyprint   (best quality)\n"
            "  pip install xhtml2pdf   (lightweight)\n"
            "  pip install reportlab   (always works)\n"
        )


# --- add to services.py ---

MODULE_COLORS = ["#D6222A", "#1D6FB8", "#178A50", "#B8860B", "#7A3FB8",
                  "#C25A1E", "#0F8A8A", "#8A0F55", "#5A6B1E", "#3F51B5",
                  "#996633", "#607D8B"]


def build_gantt_pdf_context(project, gantt_data, request):
    """Turn raw gantt() data into everything the PDF template needs.
    Pure function — no HTTP/response concerns — so it's easy to unit test."""
    n_days = gantt_data["n_days"] or 1  # guard div-by-zero for freshly-created projects
    rows = gantt_data["rows"]

    modules, color_idx = {}, 0
    for row in rows:
        for seg in row.get("segments", []):
            mod = seg.get("module")
            if not mod:
                continue
            if mod not in modules:
                modules[mod] = MODULE_COLORS[color_idx % len(MODULE_COLORS)]
                color_idx += 1
            seg["color"] = modules[mod]
            seg_len = seg.get("len") or 1
            seg["done_pct"] = round((seg.get("done", 0) / seg_len) * 100)
            seg["left_pct"] = round(((seg.get("start", 1) - 1) / n_days) * 100, 2)
            seg["width_pct"] = round((seg_len / n_days) * 100, 2)

    total_tasks = project.tasks.count()
    done_tasks = project.tasks.filter(status="DONE").count()
    overall_pct = round((done_tasks / total_tasks) * 100) if total_tasks else 0

    return {
        "project": project,
        "n_days": n_days,
        "rows": rows,
        "modules": [{"name": m, "color": c} for m, c in modules.items()],
        "weeks": list(range(1, project.weeks + 1)),
        "week_count": project.weeks or 1,
        "generated_date": timezone.now().strftime("%d %B %Y at %H:%M"),
        "overall_pct": overall_pct,
        "progress_color": (
            "#DC2626" if overall_pct < 30 else
            "#D97706" if overall_pct < 70 else
            "#059669"
        ),
        "client_name": project.client.name if project.client else "",
        "has_data": bool(rows) and any(r.get("segments") for r in rows),
    }