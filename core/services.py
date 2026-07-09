"""Plan orchestration + report building (pure functions used by views & celery)."""
from datetime import date as date_cls
from django.utils import timezone
from ai import planner
from .models import Task


def _fmt(d):
    return d.strftime("%d %b")


def build_plan_rows(project_name, weeks, devs, working_days, brief,
                    week_from=1, change_note="", done_titles=None):
    """
    devs: list of user objects. Returns list of dicts:
    {day_num, date, week, developer_id, module, title}
    """
    dev_pairs = [(u.get_full_name() or u.email, u.designation or "Developer") for u in devs]
    by_name = { (u.get_full_name() or u.email).lower(): u for u in devs }
    weekly = planner.weekly_plan(project_name, weeks, dev_pairs, brief,
                                 week_from=week_from, change_note=change_note,
                                 done_titles=done_titles)
    rows = []
    for w in range(week_from, weeks + 1):
        wk = next((x for x in weekly if x.get("week") == w), {"focus": "", "modules": []})
        labels = [f"D{(w-1)*5 + i + 1} ({_fmt(working_days[(w-1)*5 + i])})" for i in range(5)
                  if (w-1)*5 + i < len(working_days)]
        out = planner.daily_tasks(project_name, weeks, w, wk.get("focus", ""),
                                  wk.get("modules", []), dev_pairs, labels, change_note)
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
    }


def weekly_report_text(project, week):
    """Plain-text weekly report — same layout as the JMS sheet reports."""
    tasks = list(project.tasks.filter(week=week).select_related("developer"))
    all_tasks = project.tasks.all()
    total, done_all = all_tasks.count(), all_tasks.filter(status="DONE").count()
    done_wk = [t for t in tasks if t.status == "DONE"]
    pend_wk = [t for t in tasks if t.status != "DONE"]

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
