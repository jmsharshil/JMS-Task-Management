from django.utils import timezone
from django.template.loader import render_to_string
from django.http import HttpResponse
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from accounts.models import User
from accounts.permissions import IsAdmin
from ai import planner
from .models import Client, Project, Task, Update
from .serializers import ClientSerializer, ProjectSerializer, TaskSerializer, UpdateSerializer
from .services import build_plan_rows, weekly_report_text, summary_stats_text,build_gantt_pdf_context
from notifications import tasks as notify
from django.utils.text import slugify

from logging import getLogger
logger = getLogger(__name__)

class ClientViewSet(viewsets.ModelViewSet):
    queryset = Client.objects.all().order_by("name")
    serializer_class = ClientSerializer
    permission_classes = [IsAdmin]


class ProjectViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        qs = Project.objects.all().order_by("-created_at")
        if not self.request.user.is_admin:
            qs = qs.filter(team=self.request.user)
        return qs

    def get_permissions(self):
        if self.action in ("list", "retrieve", "report", "gantt", "gantt_pdf"):
            return super().get_permissions()
        return [IsAdmin()]

    # ---- Plan generation (create flow) -------------------------------------
    @action(detail=False, methods=["post"], url_path="generate-plan")
    def generate_plan(self, request):
        """
        Multipart or JSON. Fields: name, start_date, weeks, team (ids, comma or list),
        doc_text (optional), sow_pdf (optional file). Returns a DRAFT plan + brief —
        nothing is saved until POST /projects/ with the confirmed rows.
        """
        name = request.data.get("name", "Project")
        weeks = int(request.data.get("weeks", 8))
        team_ids = request.data.get("team")
        if isinstance(team_ids, str):
            team_ids = [int(x) for x in team_ids.split(",") if x.strip()]
        devs = list(User.objects.filter(id__in=team_ids or []))
        if not devs:
            return Response({"detail": "Select at least one developer."}, status=400)

        pdf = request.FILES.get("sow_pdf")
        doc_text = request.data.get("doc_text", "")
        if not pdf and not doc_text.strip():
            return Response({"detail": "Upload the SOW/FDD PDF or paste its scope text."}, status=400)

        from datetime import date
        start = date.fromisoformat(request.data.get("start_date"))
        tmp = Project(name=name, start_date=start, weeks=weeks)
        days = tmp.working_days()

        try:
            brief = planner.extract_brief(file_bytes=pdf.read() if pdf else None, filename=pdf.name if pdf else "", doc_text=doc_text)
            rows = build_plan_rows(name, weeks, devs, days, brief)
        except Exception as e:  # surface AI/parse errors cleanly
            return Response({"detail": f"Plan generation failed: {e}"}, status=502)

        return Response({"brief": brief, "rows": rows})

    def create(self, request, *args, **kwargs):
        """Save a confirmed project + its (possibly edited) draft rows, then notify team."""
        data = request.data
        project = Project.objects.create(
            name=data["name"], client_id=data.get("client") or None,
            ref=data.get("ref", ""), start_date=data["start_date"],
            weeks=int(data.get("weeks", 8)),
            brief_summary=(data.get("brief") or {}).get("summary", ""),
            brief_modules=(data.get("brief") or {}).get("modules", []),
        )
        project.team.set(data.get("team", []))
        Task.objects.bulk_create([
            Task(project=project, day_num=r["day_num"], date=r["date"], week=r["week"],
                 developer_id=r["developer_id"], module=r["module"], title=r["title"])
            for r in data.get("rows", [])
        ])
        Update.objects.create(project=project, author=request.user,
                              text=f"Project kicked off — plan published. "
                                   f"{project.tasks.count()} tasks across {project.weeks} weeks.")
        notify.send_plan_published(project.id)
        return Response(ProjectSerializer(project).data, status=status.HTTP_201_CREATED)

    # ---- Adjust plan mid-project (FDD change) ------------------------------
    @action(detail=True, methods=["post"], url_path="adjust")
    def adjust(self, request, pk=None):
        """
        Body: change_note, optional sow_pdf, apply (bool).
        Completed tasks are preserved; pending tasks from the current week onward
        are re-planned. apply=false returns a preview; apply=true commits + notifies.
        """
        project = self.get_object()
        note = request.data.get("change_note", "")
        pdf = request.FILES.get("sow_pdf")
        apply_now = str(request.data.get("apply", "false")).lower() == "true"

        today = timezone.localdate()
        days = project.working_days()
        week_from = next(((i // 5) + 1 for i, d in enumerate(days) if d >= today), project.weeks + 1)
        if week_from > project.weeks:
            return Response({"detail": "Timeline already ended — extend the project instead."}, status=400)

        brief = {"summary": project.brief_summary, "modules": project.brief_modules}
        try:
            if pdf:
                brief = planner.extract_brief(file_bytes=pdf.read(), filename=pdf.name)
            done_titles = list(project.tasks.filter(status="DONE").values_list("title", flat=True))
            devs = list(project.team.all())
            rows = build_plan_rows(project.name, project.weeks, devs, days, brief,
                                   week_from=week_from, change_note=note, done_titles=done_titles)
        except Exception as e:
            return Response({"detail": f"Re-planning failed: {e}"}, status=502)

        # Skip slots already occupied by DONE tasks in the re-planned range
        done_keys = set(project.tasks.filter(status="DONE", week__gte=week_from)
                        .values_list("day_num", "developer_id"))
        rows = [r for r in rows if (r["day_num"], r["developer_id"]) not in done_keys]

        if not apply_now:
            return Response({"week_from": week_from, "rows": rows, "brief": brief})

        project.tasks.filter(week__gte=week_from).exclude(status="DONE").delete()
        Task.objects.bulk_create([
            Task(project=project, day_num=r["day_num"], date=r["date"], week=r["week"],
                 developer_id=r["developer_id"], module=r["module"], title=r["title"])
            for r in rows
        ])
        project.brief_summary = brief.get("summary", project.brief_summary)
        project.brief_modules = brief.get("modules", project.brief_modules)
        project.save()
        Update.objects.create(project=project, author=request.user,
                              text=f"Plan adjusted from W{week_from} onwards"
                                   + (f" — {note}" if note else " (revised FDD)")
                                   + ". Check your upcoming tasks.")
        notify.send_plan_adjusted(project.id, week_from)
        return Response(ProjectSerializer(project).data)

    # ---- Reports / summary / gantt / updates --------------------------------
    @action(detail=True, methods=["get"])
    def report(self, request, pk=None):
        week = int(request.query_params.get("week", 1))
        return Response({"week": week, "text": weekly_report_text(self.get_object(), week)})

    @action(detail=True, methods=["post"], url_path="report/email", permission_classes=[IsAdmin])
    def email_report(self, request, pk=None):
        week = int(request.data.get("week", 1))
        notify.email_weekly_report(self.get_object().id, week)
        return Response({"detail": "Report is on its way to your inbox."})

    @action(detail=True, methods=["get"], permission_classes=[IsAdmin])
    def summary(self, request, pk=None):
        try:
            text = planner.executive_summary(summary_stats_text(self.get_object()))
        except Exception as e:
            return Response({"detail": f"Summary failed: {e}"}, status=502)
        return Response({"text": text})

    @action(detail=True, methods=["get"])
    def gantt(self, request, pk=None):
        """Per-developer module segments for the Gantt view."""
        project = self.get_object()
        n_days = project.weeks * 5
        out = []
        for dev in project.team.all():
            by_day = {t.day_num: t for t in project.tasks.filter(developer=dev)}
            segs, cur = [], None
            for d in range(1, n_days + 1):
                t = by_day.get(d)
                mod = t.module if t else None
                if cur and cur["module"] == mod:
                    cur["len"] += 1
                    cur["done"] += 1 if t and t.status == "DONE" else 0
                else:
                    if cur and cur["module"]:
                        segs.append(cur)
                    cur = {"start": d, "len": 1, "module": mod,
                           "done": 1 if t and t.status == "DONE" else 0} if mod else None
            if cur and cur["module"]:
                segs.append(cur)
            out.append({"developer": dev.get_full_name() or dev.email,
                        "designation": dev.designation, "segments": segs})
        return Response({"n_days": n_days, "rows": out})

    def _build_gantt_rows(self, project):
        """Shared by gantt() and gantt_pdf() so we only compute this once."""
        n_days = project.weeks * 5
        out = []
        for dev in project.team.all():
            by_day = {t.day_num: t for t in project.tasks.filter(developer=dev)}
            segs, cur = [], None
            for d in range(1, n_days + 1):
                t = by_day.get(d)
                mod = t.module if t else None
                if cur and cur["module"] == mod:
                    cur["len"] += 1
                    cur["done"] += 1 if t and t.status == "DONE" else 0
                else:
                    if cur and cur["module"]:
                        segs.append(cur)
                    cur = {"start": d, "len": 1, "module": mod,
                        "done": 1 if t and t.status == "DONE" else 0} if mod else None
            if cur and cur["module"]:
                segs.append(cur)
            out.append({"developer": dev.get_full_name() or dev.email,
                        "designation": dev.designation, "segments": segs})
        return {"n_days": n_days, "rows": out}

    @action(detail=True, methods=["get"])
    def gantt(self, request, pk=None):
        return Response(self._build_gantt_rows(self.get_object()))

    @action(detail=True, methods=["get"], url_path="gantt-pdf")
    def gantt_pdf(self, request, pk=None):
        """Generate a professional PDF of the Gantt chart (backend rendered)."""
        try:
            from weasyprint import HTML
        except OSError as e:
            # Missing GTK/Pango runtime — common on Windows dev machines.
            err = (
                "WeasyPrint dependencies not found (GTK runtime).\n\n"
                "1. Download GTK3 Runtime: https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases\n"
                "2. Run the .exe installer and add bin/ to PATH.\n"
                "3. Restart terminal + venv.\n\n"
                "Backup: Use the 'Export (browser)' button in the Gantt tab (html2canvas + jsPDF fallback).\n\n"
                f"Original error: {e}"
            )
            return HttpResponse(err, status=500, content_type="text/plain")

        project = self.get_object()

        try:
            gantt_data = self._build_gantt_rows(project)
            context = build_gantt_pdf_context(project, gantt_data, request)
            html_string = render_to_string("gantt_pdf.html", context)
            pdf_bytes = HTML(string=html_string, base_url=request.build_absolute_uri("/")).write_pdf()
        except Exception:
            # Never leak a stack trace to the client; log it for ops instead.
            logger.exception("Gantt PDF generation failed for project %s", project.id)
            return Response(
                {"detail": "Couldn't generate the PDF right now. Try again, or use the browser export as a fallback."},
                status=502,
            )

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        safe_name = slugify(project.name) or f"project-{project.id}"
        disposition = "inline" if request.query_params.get("preview") else "attachment"
        response["Content-Disposition"] = f'{disposition}; filename="{safe_name}_gantt_chart.pdf"'
        response["Cache-Control"] = "no-store"
        return response

    @action(detail=True, methods=["get", "post"], url_path="updates")
    def project_updates(self, request, pk=None):
        project = self.get_object()
        if request.method == "POST":
            if not request.user.is_admin:
                return Response(status=403)
            u = Update.objects.create(project=project, author=request.user,
                                      text=request.data.get("text", ""))
            notify.send_project_update(u.id)
            return Response(UpdateSerializer(u).data, status=201)
        return Response(UpdateSerializer(project.updates.all(), many=True).data)


class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    http_method_names = ["get", "patch"]

    def get_queryset(self):
        qs = Task.objects.select_related("developer", "project")
        u = self.request.user
        if not u.is_admin:
            qs = qs.filter(developer=u)
        pid = self.request.query_params.get("project")
        if pid:
            qs = qs.filter(project_id=pid)
        mine = self.request.query_params.get("mine")
        if mine:
            qs = qs.filter(developer=u)
        return qs

    def partial_update(self, request, *args, **kwargs):
        task = self.get_object()
        u = request.user
        # Developers may toggle their own status; only admins may reassign
        if "developer" in request.data and not u.is_admin:
            return Response(status=403)
        if "status" in request.data:
            new = request.data["status"]
            task.status = new
            task.done_at = timezone.now() if new == "DONE" else None
        if "developer" in request.data and u.is_admin:
            task.developer_id = request.data["developer"]
        task.save()
        return Response(TaskSerializer(task).data)


@api_view(["GET"])
def dashboard(request):
    """Founder dashboard: totals + per-project + per-developer rollups."""
    today = timezone.localdate()
    u = request.user
    projects = Project.objects.all() if u.is_admin else Project.objects.filter(team=u)
    proj_rows, dev_map = [], {}
    totals = {"done": 0, "pending": 0, "overdue": 0}
    for p in projects.prefetch_related("tasks__developer"):
        done = pend = over = 0
        for t in p.tasks.all():
            n = t.developer.get_full_name() or t.developer.email
            s = dev_map.setdefault(n, {"name": n, "done": 0, "pending": 0, "overdue": 0})
            if t.status == "DONE":
                done += 1; s["done"] += 1; totals["done"] += 1
            elif t.date < today:
                over += 1; s["overdue"] += 1; totals["overdue"] += 1
            else:
                pend += 1; s["pending"] += 1; totals["pending"] += 1
        total = done + pend + over
        proj_rows.append({"id": p.id, "name": p.name, "done": done, "pending": pend + over,
                          "total": total, "pct": round(done / total * 100) if total else 0})
    return Response({"totals": totals, "projects": proj_rows, "developers": list(dev_map.values())})
