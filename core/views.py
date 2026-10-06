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
from .models import (Client, Project, Task, Update, ProjectDocument,
                     AdHocTask, AdHocTaskAttachment, ProjectArchitecture,
                     MeetingMinutes, ProjectReportTemplate, OrganizationSettings, ProjectMilestone)
from .serializers import (ClientSerializer, ProjectSerializer, TaskSerializer,
                          UpdateSerializer, ProjectDocumentSerializer,
                          AdHocTaskSerializer, AdHocTaskAttachmentSerializer,
                          ProjectArchitectureSerializer, MeetingMinutesSerializer,
                          ReportFormatTemplateSerializer, OrganizationSettingsSerializer,
                          ProjectMilestoneSerializer)
from .services import (build_plan_rows, weekly_report_text, weekly_report_context,
                       summary_stats_text, build_gantt_pdf_context,
                       daily_report_context, daily_report_text, render_report_pdf,
                       custom_range_report_context, custom_range_report_text,
                       mom_pdf_sections)
from notifications import tasks as notify
from django.utils.text import slugify

from logging import getLogger
logger = getLogger(__name__)
from .pagination import OptionalPagination

class ClientViewSet(viewsets.ModelViewSet):
    queryset = Client.objects.all().order_by("name")
    serializer_class = ClientSerializer
    permission_classes = [IsAdmin]


class ProjectMilestoneViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectMilestoneSerializer

    def get_queryset(self):
        qs = ProjectMilestone.objects.all()
        project_id = self.request.query_params.get("project_id")
        if project_id:
            qs = qs.filter(project_id=project_id)
        return qs


class ProjectViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = OptionalPagination

    def get_queryset(self):
        qs = Project.objects.all().order_by("-created_at")
        if not self.request.user.is_admin:
            qs = qs.filter(team=self.request.user)
        return qs

    def get_permissions(self):
        if self.action in ("list", "retrieve", "report", "gantt", "gantt_pdf", "project_updates", "documents"):
            return super().get_permissions()
        return [IsAdmin()]

    # ---- Plan generation (create flow) -------------------------------------
    @action(detail=False, methods=["post"], url_path="generate-plan")
    def generate_plan(self, request):
        """
        Now gated behind approved architecture (two-stage workflow). 
        Requires architecture_id. Returns draft plan enriched with architecture context.
        """
        name = request.data.get("name", "Project")
        weeks = int(request.data.get("weeks", 8))
        architecture_id = request.data.get("architecture_id")
        if not architecture_id:
            return Response({"detail": "architecture_id (from approved architecture) is required."}, status=400)

        team_ids = request.data.get("team")
        if isinstance(team_ids, str):
            team_ids = [int(x) for x in team_ids.split(",") if x.strip()]
        devs = list(User.objects.filter(id__in=team_ids or []))
        if not devs:
            return Response({"detail": "Select at least one developer."}, status=400)

        try:
            arch_obj = ProjectArchitecture.objects.get(id=architecture_id, status="APPROVED")
        except ProjectArchitecture.DoesNotExist:
            return Response({"detail": "Approved architecture not found. Generate and approve one first."}, status=400)

        pdf = request.FILES.get("sow_pdf")
        doc_text = request.data.get("doc_text", "")
        if not pdf and not doc_text.strip():
            return Response({"detail": "Upload the SOW/FDD PDF or paste its scope text."}, status=400)

        pdf_bytes = pdf.read() if pdf else None

        from datetime import date
        start = date.fromisoformat(request.data.get("start_date"))
        tmp = Project(name=name, start_date=start, weeks=weeks)
        days = tmp.working_days()

        try:
            leader_ids = request.data.get("team_leaders")
            leaders = []
            if isinstance(leader_ids, str) and leader_ids.strip():
                leader_ids_list = [int(x) for x in leader_ids.split(",") if x.strip()]
                leaders = list(User.objects.filter(id__in=leader_ids_list))

            brief = planner.extract_brief(file_bytes=pdf_bytes, filename=pdf.name if pdf else "", doc_text=doc_text)
            # Inject architecture into brief so that weekly_plan / daily_tasks can produce better-aligned tasks
            if isinstance(arch_obj.content, dict):
                brief.setdefault("architecture", arch_obj.content)
                brief.setdefault("architecture_id", architecture_id)
            rows = build_plan_rows(name, weeks, devs, days, brief, leaders=leaders)
        except Exception as e:  # surface AI/parse errors cleanly
            return Response({"detail": f"Plan generation failed: {e}"}, status=502)

        return Response({
            "brief": brief,
            "rows": rows,
            "architecture_id": architecture_id,
            "architecture_summary": arch_obj.content.get("overview", "")[:120] if isinstance(arch_obj.content, dict) else ""
        })

    # ---- Architecture generation & approval (NEW gate before plan) -------------
    @action(detail=False, methods=["post"], url_path="generate-architecture")
    def generate_architecture(self, request):
        """
        First step in project creation: Generate high-level architecture doc from SOW.
        Returns draft architecture JSON. Client must approve before generate-plan.
        Supports team_leaders for better prompt guidance on task assignments.
        """
        name = request.data.get("name", "Project")
        team_ids = request.data.get("team")
        if isinstance(team_ids, str):
            team_ids = [int(x) for x in team_ids.split(",") if x.strip()]
        devs = list(User.objects.filter(id__in=team_ids or []))

        leader_ids = request.data.get("team_leaders")
        leaders = []
        if isinstance(leader_ids, str) and leader_ids.strip():
            leader_ids_list = [int(x) for x in leader_ids.split(",") if x.strip()]
            leaders = list(User.objects.filter(id__in=leader_ids_list))

        pdf = request.FILES.get("sow_pdf")
        doc_text = request.data.get("doc_text", "")
        if not pdf and not doc_text.strip():
            return Response({"detail": "Upload the SOW/FDD PDF or paste its scope text."}, status=400)

        pdf_bytes = pdf.read() if pdf else None
        try:
            arch = planner.generate_architecture(
                project_name=name,
                team=devs,
                leaders=leaders,
                file_bytes=pdf_bytes,
                filename=pdf.name if pdf else "",
                doc_text=doc_text
            )
            if "error" in arch:
                return Response({"detail": arch["error"]}, status=502)
            # Also return brief for convenience
            brief = planner.extract_brief(
                file_bytes=pdf_bytes,
                filename=pdf.name if pdf else "",
                doc_text=doc_text
            )
        except Exception as e:
            logger.error(f"Architecture generation failed: {e}")
            return Response({"detail": f"Architecture generation failed: {e}"}, status=502)

        return Response({
            "architecture": arch,
            "brief": brief,
            "message": "Review and approve this architecture before generating the detailed plan."
        })

    @action(detail=False, methods=["post"], url_path="approve-architecture")
    def approve_architecture(self, request):
        """
        Approve (and optionally edit) the architecture document. Returns the saved record ID
        to be passed to generate-plan or project creation.
        """
        arch_data = request.data.get("architecture", {})
        if isinstance(arch_data, str):
            import json
            arch_data = json.loads(arch_data)

        name = request.data.get("name")
        project_id = request.data.get("project")  # if linking to existing draft

        arch = ProjectArchitecture.objects.create(
            title=f"Architecture for {name or 'New Project'}",
            content=arch_data,
            status="APPROVED",
            approved_by=request.user,
            approved_at=timezone.now(),
            notes=request.data.get("notes", "")
        )
        if project_id:
            try:
                proj = Project.objects.get(id=project_id)
                proj.architecture = arch  # since OneToOne, may need to handle if exists
                proj.save()
            except Project.DoesNotExist:
                pass

        return Response({
            "id": arch.id,
            "status": "APPROVED",
            "architecture": ProjectArchitectureSerializer(arch).data,
            "message": "Architecture approved. You may now generate the detailed project plan."
        })

    def create(self, request, *args, **kwargs):
        """Save a confirmed project + its (possibly edited) draft rows, then notify team.
        Now requires approved architecture.
        """
        data = request.data
        import json
        
        # Parse JSON strings if data comes from FormData
        brief_data = data.get("brief")
        if isinstance(brief_data, str):
            brief_data = json.loads(brief_data)
        brief_data = brief_data or {}
            
        rows_data = data.get("rows")
        if isinstance(rows_data, str):
            rows_data = json.loads(rows_data)
        rows_data = rows_data or []
        
        arch_data = data.get("architecture")
        if isinstance(arch_data, str):
            arch_data = json.loads(arch_data)
        arch_id = data.get("architecture_id") or (arch_data.get("id") if isinstance(arch_data, dict) else None)
        
        team_data = data.get("team")
        if isinstance(team_data, str):
            team_data = team_data.split(",") if team_data else []
        elif not team_data:
            team_data = []
            
        # Validate architecture approval
        if not arch_id:
            return Response({"detail": "Approved architecture_id is required."}, status=400)
        try:
            arch = ProjectArchitecture.objects.get(id=arch_id, status="APPROVED")
        except ProjectArchitecture.DoesNotExist:
            return Response({"detail": "Valid approved architecture is required before creating project plan."}, status=400)

        project = Project.objects.create(
            name=data["name"], client_id=data.get("client") or None,
            ref=data.get("ref", ""), start_date=data["start_date"],
            weeks=int(data.get("weeks", 8)),
            brief_summary=brief_data.get("summary", ""),
            brief_modules=brief_data.get("modules", []),
            sow_pdf=request.FILES.get("sow_pdf")
        )
        project.team.set(team_data)
        
        # Set team leaders (subset of team)
        leader_data = data.get("team_leaders")
        if isinstance(leader_data, str):
            leader_data = [int(x) for x in leader_data.split(",") if x.strip()]
        if leader_data:
            # ensure leaders are part of team
            leader_data = [lid for lid in leader_data if int(lid) in [int(t) for t in team_data]]
            project.team_leaders.set(leader_data)
        
        # Link architecture
        arch.project = project
        arch.save(update_fields=['project'])
        
        current_week = int(data.get("current_week", 1))
        Task.objects.bulk_create([
            Task(project=project, day_num=r["day_num"], date=r["date"], week=r["week"],
                 developer_id=r["developer_id"], module=r["module"], title=r["title"],
                 status="DONE" if r["week"] < current_week else "TODO",
                 done_at=timezone.now() if r["week"] < current_week else None)
            for r in rows_data
        ])
        Update.objects.create(project=project, author=request.user,
                              text=f"Architecture approved and project kicked off — plan published. "
                                   f"{project.tasks.count()} tasks across {project.weeks} weeks. "
                                   f"Architecture v{arch.version} approved.")
        notify.send_plan_published(project.id)
        return Response(ProjectSerializer(project).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()

        old_start_date = instance.start_date
        old_weeks = instance.weeks
        old_team_ids = set(instance.team.values_list('id', flat=True))

        data = request.data.copy()
        if "team" in data and isinstance(data["team"], str):
            team_str = data["team"]
            team_list = [int(x) for x in team_str.split(",") if x.strip()]
            if hasattr(data, 'setlist'):
                data.setlist("team", team_list)
            else:
                data["team"] = team_list

        serializer = self.get_serializer(instance, data=data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        instance.refresh_from_db()

        new_team_ids = set(instance.team.values_list('id', flat=True))

        start_date_changed = old_start_date != instance.start_date
        weeks_changed = old_weeks != instance.weeks
        team_changed = old_team_ids != new_team_ids

        if weeks_changed or team_changed or "sow_pdf" in request.FILES:
            done_tasks = instance.tasks.filter(status="DONE")
            done_keys = set(done_tasks.values_list("day_num", "developer_id"))
            done_titles = list(done_tasks.values_list("title", flat=True))

            days = instance.working_days()
            devs = list(instance.team.all())
            brief = {"summary": instance.brief_summary, "modules": instance.brief_modules}
            if instance.architecture and isinstance(instance.architecture.content, dict):
                brief.setdefault("architecture", instance.architecture.content)

            if "sow_pdf" in request.FILES:
                try:
                    pdf = request.FILES["sow_pdf"]
                    brief = planner.extract_brief(file_bytes=pdf.read(), filename=pdf.name)
                    instance.brief_summary = brief.get("summary", instance.brief_summary)
                    instance.brief_modules = brief.get("modules", instance.brief_modules)
                    instance.save(update_fields=['brief_summary', 'brief_modules'])
                    # re-inject architecture
                    if instance.architecture and isinstance(instance.architecture.content, dict):
                        brief.setdefault("architecture", instance.architecture.content)
                except Exception as e:
                    logger.error(f"Failed to extract brief during update: {e}")

            try:
                leaders = list(instance.team_leaders.all())
                rows = build_plan_rows(instance.name, instance.weeks, devs, days, brief,
                                       leaders=leaders, week_from=1, done_titles=done_titles)
                rows = [r for r in rows if (r["day_num"], r["developer_id"]) not in done_keys]
                instance.tasks.exclude(status="DONE").delete()

                Task.objects.bulk_create([
                    Task(project=instance, day_num=r["day_num"], date=r["date"], week=r["week"],
                         developer_id=r["developer_id"], module=r["module"], title=r["title"])
                    for r in rows
                ])
                Update.objects.create(project=instance, author=request.user, text="Project details updated. Plan was automatically recalculated.")
            except Exception as e:
                logger.error(f"Failed to rebuild plan during update: {e}")

        elif start_date_changed:
            days = instance.working_days()
            tasks_to_update = []
            for t in instance.tasks.all():
                if 1 <= t.day_num <= len(days):
                    t.date = days[t.day_num - 1]
                    tasks_to_update.append(t)
            Task.objects.bulk_update(tasks_to_update, ['date'])
            Update.objects.create(project=instance, author=request.user, text="Project start date was adjusted. Task dates have been shifted accordingly.")

        return Response(ProjectSerializer(instance).data)

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
        if project.architecture and isinstance(project.architecture.content, dict):
            brief.setdefault("architecture", project.architecture.content)
        try:
            if pdf:
                brief = planner.extract_brief(file_bytes=pdf.read(), filename=pdf.name)
                # re-inject architecture after possible re-extract
                if project.architecture and isinstance(project.architecture.content, dict):
                    brief.setdefault("architecture", project.architecture.content)
            done_titles = list(project.tasks.filter(status="DONE").values_list("title", flat=True))
            devs = list(project.team.all())
            leaders = list(project.team_leaders.all())
            rows = build_plan_rows(project.name, project.weeks, devs, days, brief,
                                   leaders=leaders, week_from=week_from, change_note=note, done_titles=done_titles)
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

    @action(detail=True, methods=["get", "post"], url_path="share-link")
    def share_link(self, request, pk=None):
        from django.core.files.base import ContentFile
        from django.utils.text import slugify
        from datetime import date as date_cls
        import html as html_lib

        project = self.get_object()
        report_type = request.query_params.get("type")
        if not report_type and isinstance(request.data, dict):
            report_type = request.data.get("type")
        if not report_type:
            report_type = "weekly"
        
        context = None
        html_template = ""
        filename = ""
        title = ""
        html = None
        
        if report_type == "weekly":
            week = int(request.query_params.get("week") or (request.data.get("week") if isinstance(request.data, dict) else 1))
            context = weekly_report_context(project, week)
            html_template = "notifications/emails/weekly_report.html"
            filename = f"{slugify(project.name)}_W{week}_report.pdf"
            title = f"Weekly Report W{week} (Shared)"
        elif report_type == "daily":
            d = request.query_params.get("date") or (request.data.get("date") if isinstance(request.data, dict) else None)
            report_date = date_cls.fromisoformat(d)
            context = daily_report_context(project, report_date)
            html_template = "notifications/emails/daily_report.html"
            filename = f"{slugify(project.name)}_{d}_daily_report.pdf"
            title = f"Daily Report {d} (Shared)"
        elif report_type == "custom":
            df = request.query_params.get("date_from") or (request.data.get("date_from") if isinstance(request.data, dict) else None)
            dt = request.query_params.get("date_to") or (request.data.get("date_to") if isinstance(request.data, dict) else None)
            date_from = date_cls.fromisoformat(df)
            date_to = date_cls.fromisoformat(dt)
            context = custom_range_report_context(project, date_from, date_to)
            html_template = "notifications/emails/custom_range_report.html"
            filename = f"{slugify(project.name)}_{df}_to_{dt}_report.pdf"
            title = f"Custom Report {df} - {dt} (Shared)"
        elif report_type == "milestones":
            filename = f"{slugify(project.name)}_milestones.pdf"
            title = f"{project.name} — Milestone Report (Shared)"
            if isinstance(request.data, dict) and request.data.get("html"):
                html = request.data.get("html")
            else:
                milestones = project.milestones.all()
                rows_html = ""
                for i, m in enumerate(milestones):
                    bg = "#ffffff" if i % 2 == 0 else "#f8fafc"
                    cell = f"padding:8px 10px;border:1px solid #e2e8f0;vertical-align:top;word-break:break-word;white-space:normal;font-size:10.5px;background:{bg};color:#334155"
                    date_cell = f"padding:8px 10px;border:1px solid #e2e8f0;vertical-align:top;font-family:monospace;font-size:10.5px;white-space:nowrap;background:{bg};color:#334155"
                    status_lbl = html_lib.escape(str(m.status or "On Track"))
                    p_name = html_lib.escape(project.name)
                    t_val = html_lib.escape(m.title or "")
                    w_val = html_lib.escape(m.work_completed or "")
                    o_val = html_lib.escape(m.owner or "-")
                    dep_val = html_lib.escape(m.stakeholder_dependency or "-")
                    nxt_val = html_lib.escape(m.next_milestone_desc or "-")
                    c_date = html_lib.escape(str(m.committed_date or "-"))
                    f_date = html_lib.escape(str(m.final_completion_date or "-"))
                    blk = html_lib.escape(m.blocker or "")
                    act = html_lib.escape(m.recovery_action or "")
                    blk_html = f'<b style="color:#dc2626">Blocker:</b> {blk}<br>' if blk else ''
                    act_html = f'<b style="color:#4f46e5">Action:</b> {act}' if act else ''
                    block_act = (blk_html + act_html) if (blk or act) else '-'
                    work_html = f'<br><span style="font-size:9.5px;color:#64748b">{w_val}</span>' if w_val else ''
                    rows_html += f'<tr><td style="{cell}">{p_name}</td><td style="{cell};font-weight:600;color:#0f172a">{t_val}{work_html}</td><td style="{cell}"><span style="display:inline-block;padding:3px 6px;border-radius:3px;font-size:9.5px;font-weight:700;text-transform:uppercase;white-space:nowrap;background:#dcfce7;color:#166534;border:1px solid #bbf7d0">{status_lbl}</span></td><td style="{cell}">{o_val}</td><td style="{cell}">{dep_val}</td><td style="{cell}">{nxt_val}</td><td style="{date_cell}">{c_date}</td><td style="{date_cell}">{f_date}</td><td style="{cell}">{block_act}</td></tr>'
                th = "padding:8px 10px;border:1px solid #cbd5e1;font-weight:700;background:#f1f5f9;color:#1e293b;font-size:10.5px;text-align:left;vertical-align:bottom;word-break:break-word"
                html = f'<!DOCTYPE html><html><head><meta charset="utf-8"><style>@page {{ size: landscape; margin: 10mm; }} body {{ font-family: Arial, Helvetica, sans-serif; font-size: 11px; margin: 10px; color: #1e293b; }} h2 {{ font-size: 16px; margin-bottom: 4px; color: #0f172a; }} p {{ color: #64748b; font-size: 11px; margin: 0 0 14px; }} table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}</style></head><body><h2>{html_lib.escape(project.name)} — Milestone Status Report</h2><p>Milestone Status Summary</p><table><colgroup><col style="width:10%"><col style="width:18%"><col style="width:8%"><col style="width:9%"><col style="width:10%"><col style="width:11%"><col style="width:10%"><col style="width:10%"><col style="width:14%"></colgroup><thead><tr><th style="{th}">Project</th><th style="{th}">Open Item</th><th style="{th}">Status</th><th style="{th}">Owner</th><th style="{th}">Dependency</th><th style="{th}">Next Milestone</th><th style="{th}">Committed Date</th><th style="{th}">Final Closure Date</th><th style="{th}">Risk / Blocker &amp; Action</th></tr></thead><tbody>{rows_html}</tbody></table></body></html>'
        else:
            return Response({"detail": "Invalid type"}, status=400)
            
        if not html and html_template:
            try:
                from .models import OrganizationSettings
                context["org"] = OrganizationSettings.get()
            except Exception:
                pass
            html = render_to_string(html_template, context)
            
        try:
            pdf_bytes = render_report_pdf(html, title=f"{project.name} — Report")
        except RuntimeError as e:
            return Response({"detail": str(e)}, status=502)
            
        doc = ProjectDocument(project=project, title=title)
        doc.file.save(filename, ContentFile(pdf_bytes), save=True)
        
        from django.conf import settings
        if getattr(settings, "USE_AZURE_MEDIA", False):
            account = getattr(settings, "AZURE_ACCOUNT_NAME", "hrmsknowcraftstorage")
            container = getattr(settings, "AZURE_CONTAINER", "media")
            url = f"https://{account}.blob.core.windows.net/{container}/{doc.file.name}"
        else:
            url = request.build_absolute_uri(doc.file.url)
            
        return Response({"link": url})

    @action(detail=True, methods=["get"])
    def report(self, request, pk=None):
        week = int(request.query_params.get("week", 1))
        return Response({"week": week, "text": weekly_report_text(self.get_object(), week)})

    @action(detail=True, methods=["post"], url_path="report/email", permission_classes=[IsAdmin])
    def email_report(self, request, pk=None):
        week = int(request.data.get("week", 1))
        recipients = request.data.get("email", "")
        custom_text = request.data.get("text", None)
        notify.email_weekly_report(
            self.get_object().id, week,
            recipient_email=recipients if recipients and recipients.strip() else None,
            custom_text=custom_text
        )
        return Response({"detail": "Report is on its way."})

    @action(detail=True, methods=["get", "post"], url_path="report-pdf")
    def report_pdf(self, request, pk=None):
        """Download weekly report as PDF. Accepts optional custom text via POST body."""
        project = self.get_object()
        week = int(request.query_params.get("week", 1))
        custom_text = request.data.get("text") if request.method == "POST" else None
        context = weekly_report_context(project, week)
        try:
            from .models import OrganizationSettings
            context["org"] = OrganizationSettings.get()
        except Exception:
            pass

        if custom_text:
            context["custom_text"] = custom_text
        html = render_to_string("notifications/emails/weekly_report.html", context)
        try:
            pdf_bytes = render_report_pdf(html)
        except RuntimeError as e:
            return Response({"detail": str(e)}, status=502)
        resp = HttpResponse(pdf_bytes, content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="{slugify(project.name)}_week{week}_report.pdf"'
        return resp

    @action(detail=True, methods=["get"], url_path="daily-report")
    def daily_report(self, request, pk=None):
        """Get daily report data."""
        from datetime import date as date_cls
        project = self.get_object()
        d = request.query_params.get("date")
        report_date = date_cls.fromisoformat(d) if d else timezone.localdate()
        context = daily_report_context(project, report_date)
        context["text"] = daily_report_text(project, report_date)
        return Response(context)

    @action(detail=True, methods=["get", "post"], url_path="daily-report-pdf")
    def daily_report_pdf(self, request, pk=None):
        """Download daily report as PDF. Accepts optional custom text via POST body."""
        from datetime import date as date_cls
        project = self.get_object()
        d = request.query_params.get("date")
        report_date = date_cls.fromisoformat(d) if d else timezone.localdate()
        custom_text = request.data.get("text") if request.method == "POST" else None
        context = daily_report_context(project, report_date)
        if custom_text:
            context["custom_text"] = custom_text
        html = render_to_string("notifications/emails/daily_report.html", context)
        try:
            pdf_bytes = render_report_pdf(html)
        except RuntimeError as e:
            return Response({"detail": str(e)}, status=502)
        resp = HttpResponse(pdf_bytes, content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="{slugify(project.name)}_{report_date}_daily_report.pdf"'
        return resp

    @action(detail=True, methods=["post"], url_path="daily-report-email", permission_classes=[IsAdmin])
    def email_daily_report(self, request, pk=None):
        """Email a daily report with optional custom text and multiple recipients."""
        from datetime import date as date_cls
        project = self.get_object()
        d = request.data.get("date")
        recipients = request.data.get("email", "")
        custom_text = request.data.get("text", None)
        report_date = date_cls.fromisoformat(d) if d else timezone.localdate()
        notify.email_daily_report(
            project.id, str(report_date),
            recipient_email=recipients if recipients and recipients.strip() else None,
            custom_text=custom_text
        )
        return Response({"detail": "Daily report email queued."})

    @action(detail=True, methods=["get"], url_path="custom-report")
    def custom_report(self, request, pk=None):
        """Get report data for a custom date range."""
        from datetime import date as date_cls
        project = self.get_object()
        df = request.query_params.get("date_from")
        dt = request.query_params.get("date_to")
        if not df or not dt:
            return Response({"detail": "date_from and date_to required (YYYY-MM-DD)."}, status=400)
        date_from = date_cls.fromisoformat(df)
        date_to = date_cls.fromisoformat(dt)
        context = custom_range_report_context(project, date_from, date_to)
        context["text"] = custom_range_report_text(project, date_from, date_to)
        return Response(context)

    @action(detail=True, methods=["post"], url_path="custom-report-email", permission_classes=[IsAdmin])
    def email_custom_report(self, request, pk=None):
        """Email a custom date range report."""
        df = request.data.get("date_from")
        dt = request.data.get("date_to")
        recipient = request.data.get("email", "")
        custom_text = request.data.get("text", None)
        if not df or not dt:
            return Response({"detail": "date_from and date_to required."}, status=400)
        notify.email_custom_range_report(
            self.get_object().id, df, dt,
            recipient_email=recipient if recipient.strip() else None,
            custom_text=custom_text
        )
        return Response({"detail": "Custom range report is on its way."})

    @action(detail=True, methods=["get", "post"], url_path="custom-report-pdf")
    def custom_report_pdf(self, request, pk=None):
        """Download custom date range report as PDF."""
        from datetime import date as date_cls
        project = self.get_object()
        df = request.query_params.get("date_from")
        dt = request.query_params.get("date_to")
        custom_text = request.data.get("text") if request.method == "POST" else None
        if not df or not dt:
            return Response({"detail": "date_from and date_to required."}, status=400)
        date_from = date_cls.fromisoformat(df)
        date_to = date_cls.fromisoformat(dt)
        context = custom_range_report_context(project, date_from, date_to)
        if custom_text:
            context["text"] = custom_text
        html = render_to_string("notifications/emails/custom_range_report.html", context)
        title = project.name + " Report"
        
        # If custom_text is provided, we might want to just render it as a section
        sections = [
            ("Overall Stats", f"{context['done_all']}/{context['total']} tasks done ({context['overall_pct']}%)"),
            ("Period Stats", f"{context['done_range']}/{context['total_range']} tasks done ({context['range_pct']}%)"),
        ]
        if custom_text:
             sections.append(("Report", custom_text))
        else:
             sections.extend([
                 ("Completed", "\\n".join(f"[x] D{t['day_num']} - {t['module']}: {t['title']}" for t in context["completed_tasks"]) or "(none)"),
                 ("Pending", "\\n".join(f"[ ] D{t['day_num']} - {t['module']}: {t['title']}" for t in context["pending_tasks"]) or "(all done)"),
             ])
        try:
            pdf_bytes = render_report_pdf(html, title=title, sections=sections)
        except RuntimeError as e:
            return Response({"detail": str(e)}, status=502)
        resp2 = HttpResponse(pdf_bytes, content_type="application/pdf")
        resp2["Content-Disposition"] = f'attachment; filename="{slugify(project.name)}_{df}_to_{dt}_report.pdf"'
        return resp2

    # ---- MOMs ----

    @action(detail=True, methods=["get", "post"], url_path="moms")
    def moms(self, request, pk=None):
        """List or create MOMs for a project."""
        project = self.get_object()
        if request.method == "POST":
            if not request.user.is_admin:
                return Response(status=403)
            data = request.data.copy()
            data["project"] = project.id
            serializer = MeetingMinutesSerializer(data=data)
            serializer.is_valid(raise_exception=True)
            mom = serializer.save(created_by=request.user)
            return Response(MeetingMinutesSerializer(mom).data, status=201)
        return Response(MeetingMinutesSerializer(project.moms.all(), many=True).data)

    @action(detail=True, methods=["patch", "delete"], url_path=r"moms/(?P<mom_id>\d+)", permission_classes=[IsAdmin])
    def mom_detail(self, request, pk=None, mom_id=None):
        """Update or delete a specific MOM."""
        mom = MeetingMinutes.objects.filter(project=self.get_object(), pk=mom_id).first()
        if not mom:
            return Response(status=404)
        if request.method == "DELETE":
            mom.delete()
            return Response(status=204)
        serializer = MeetingMinutesSerializer(mom, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path=r"moms/(?P<mom_id>\d+)/email", permission_classes=[IsAdmin])
    def email_mom_action(self, request, pk=None, mom_id=None):
        """Email a specific MOM."""
        mom = MeetingMinutes.objects.filter(project=self.get_object(), pk=mom_id).first()
        if not mom:
            return Response(status=404)
        recipient = request.data.get("email", "")
        notify.email_mom(mom.id, recipient_email=recipient if recipient.strip() else None)
        return Response({"detail": "MOM email is on its way."})

    @action(detail=True, methods=["get"], url_path=r"moms/(?P<mom_id>\d+)/pdf", permission_classes=[IsAdmin])
    def mom_pdf(self, request, pk=None, mom_id=None):
        """Download a MOM as PDF."""
        mom = MeetingMinutes.objects.filter(project=self.get_object(), pk=mom_id).first()
        if not mom:
            return Response(status=404)
        title = f"MOM: {mom.title} - {mom.project.name}"
        sections = mom_pdf_sections(mom)
        try:
            pdf_bytes = render_report_pdf("", title=title, sections=sections)
        except RuntimeError as e:
            return Response({"detail": str(e)}, status=502)
        r = HttpResponse(pdf_bytes, content_type="application/pdf")
        r["Content-Disposition"] = f'attachment; filename="{slugify(mom.title)}_mom.pdf"'
        return r

    # ---- Additional project tasks ----

    @action(detail=True, methods=["get", "post"], url_path="extra-tasks")
    def extra_tasks(self, request, pk=None):
        """List or create additional (manually-added) tasks on a project."""
        from django.db.models import Max
        project = self.get_object()
        if request.method == "POST":
            if not request.user.is_admin:
                return Response(status=403)
            dev_id = request.data.get("developer")
            if not dev_id:
                return Response({"detail": "developer is required."}, status=400)
            # Use today as the date for additional tasks
            today = timezone.localdate()
            # Get max day_num + 1 for this project (or use 0)
            existing_max = project.tasks.aggregate(m=Max("day_num"))["m"] or 0
            task = Task.objects.create(
                project=project,
                day_num=existing_max + 1,
                date=today,
                week=project.tasks.filter(date=today).first().week if project.tasks.filter(date=today).exists() else 1,
                developer_id=dev_id,
                module=request.data.get("module", "Additional"),
                title=request.data.get("title", "Untitled task"),
                description=request.data.get("description", ""),
                priority=request.data.get("priority", "MEDIUM"),
                is_additional=True,
            )
            return Response(TaskSerializer(task).data, status=201)
        qs = project.tasks.filter(is_additional=True).select_related("developer")
        return Response(TaskSerializer(qs, many=True).data)

    @action(detail=True, methods=["patch", "delete"], url_path=r"extra-tasks/(?P<etask_id>\d+)")
    def extra_task_detail(self, request, pk=None, etask_id=None):
        """Update or delete an additional project task."""
        task = Task.objects.filter(project=self.get_object(), pk=etask_id, is_additional=True).first()
        if not task:
            return Response(status=404)
        u = request.user
        is_assignee = task.developer_id == u.id
        if not u.is_admin and not is_assignee:
            return Response(status=403)
        if request.method == "DELETE":
            if not u.is_admin:
                return Response(status=403)
            task.delete()
            return Response(status=204)
        if "status" in request.data:
            task.status = request.data["status"]
            if request.data["status"] == "DONE":
                task.done_at = timezone.now()
            else:
                task.done_at = None
        if "comment" in request.data:
            task.comment = request.data["comment"]
        if u.is_admin:
            for field in ["title", "description", "module", "priority"]:
                if field in request.data:
                    setattr(task, field, request.data[field])
            if "developer" in request.data:
                task.developer_id = request.data["developer"]
        task.save()
        return Response(TaskSerializer(task).data)

    @action(detail=True, methods=["get"], permission_classes=[IsAdmin])
    def summary(self, request, pk=None):
        try:
            text = planner.executive_summary(summary_stats_text(self.get_object()))
        except Exception as e:
            return Response({"detail": f"Summary failed: {e}"}, status=502)
        return Response({"text": text})

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

    @action(detail=True, methods=["get", "post"], url_path="documents")
    def documents(self, request, pk=None):
        project = self.get_object()
        if request.method == "POST":
            if not request.user.is_admin:
                return Response(status=403)
            file = request.FILES.get("file")
            title = request.data.get("title", "").strip() or (file.name if file else "Document")
            if not file:
                return Response({"detail": "No file uploaded."}, status=400)
            doc = ProjectDocument.objects.create(
                project=project, title=title, file=file, uploaded_by=request.user
            )
            return Response(
                ProjectDocumentSerializer(doc, context={"request": request}).data,
                status=201,
            )
        docs = project.documents.all()
        return Response(ProjectDocumentSerializer(docs, many=True, context={"request": request}).data)

    @action(detail=True, methods=["delete"], url_path=r"documents/(?P<doc_id>\d+)",
            permission_classes=[IsAdmin])
    def delete_document(self, request, pk=None, doc_id=None):
        doc = ProjectDocument.objects.filter(project=self.get_object(), pk=doc_id).first()
        if not doc:
            return Response(status=404)
        doc.file.delete(save=False)
        doc.delete()
        return Response(status=204)



class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    http_method_names = ["get", "patch", "delete"]
    pagination_class = OptionalPagination

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
        return qs.order_by("date")

    def partial_update(self, request, *args, **kwargs):
        task = self.get_object()
        u = request.user
        # Developers may toggle their own status and edit their own comment; only admins may reassign
        if "developer" in request.data and not u.is_admin:
            return Response(status=403)
        if "status" in request.data:
            new = request.data["status"]
            task.status = new
            task.done_at = timezone.now() if new == "DONE" else None
        if "developer" in request.data and u.is_admin:
            task.developer_id = request.data["developer"]
        if "comment" in request.data:
            # Developer can only edit their own task's comment
            if not u.is_admin and task.developer_id != u.id:
                return Response(status=403)
            task.comment = request.data["comment"]
        if u.is_admin:
            for field in ["title", "description", "module", "priority"]:
                if field in request.data:
                    setattr(task, field, request.data[field])
        task.save()
        return Response(TaskSerializer(task).data)

    def destroy(self, request, *args, **kwargs):
        u = request.user
        if not u.is_admin:
            return Response(status=403)
        task = self.get_object()
        task.delete()
        return Response(status=204)


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


class AdHocTaskViewSet(viewsets.ModelViewSet):
    """CRUD for standalone tasks not tied to projects."""
    serializer_class = AdHocTaskSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = OptionalPagination

    def get_queryset(self):
        u = self.request.user
        qs = AdHocTask.objects.prefetch_related("assignees", "attachments").select_related("created_by")
        if not u.is_admin:
            qs = qs.filter(assignees=u)
        assignee = self.request.query_params.get("assignee")
        if assignee:
            qs = qs.filter(assignees__id=assignee)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        priority = self.request.query_params.get("priority")
        if priority:
            qs = qs.filter(priority=priority)
        return qs.distinct()

    def create(self, request, *args, **kwargs):
        # We need to extract assignees if they come in as multiple form fields
        data = request.data.copy()
        if hasattr(request.data, "getlist") and "assignees" in request.data:
            data.setlist("assignees", request.data.getlist("assignees"))
        
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=201, headers=headers)

    def perform_create(self, serializer):
        task = serializer.save(created_by=self.request.user)
        # Attach files if any
        for f in self.request.FILES.getlist("files"):
            AdHocTaskAttachment.objects.create(task=task, file=f, title=f.name)
        notify.send_adhoc_task_assigned(task.id)

    def partial_update(self, request, *args, **kwargs):
        task = self.get_object()
        u = request.user
        # Non-admin can only update status and comment on their own tasks
        is_assignee = task.assignees.filter(id=u.id).exists()
        if not u.is_admin and not is_assignee:
            return Response(status=403)
        if "status" in request.data:
            task.status = request.data["status"]
            if request.data["status"] == "DONE":
                task.completed_at = timezone.now()
            else:
                task.completed_at = None
        if "comment" in request.data:
            task.comment = request.data["comment"]
        # Admin-only fields
        if u.is_admin:
            for field in ["title", "description", "priority", "due_date", "start_date"]:
                if field in request.data:
                    setattr(task, field, request.data[field])
            
            if "assignees" in request.data:
                assignee_ids = request.data.getlist("assignees") if hasattr(request.data, "getlist") else request.data.get("assignees")
                if assignee_ids is not None:
                    # ensure it's a list
                    if not isinstance(assignee_ids, list):
                        assignee_ids = [assignee_ids]
                    task.assignees.set(assignee_ids)
        task.save()
        return Response(AdHocTaskSerializer(task).data)

    @action(detail=True, methods=["get", "post", "delete"])
    def attachments(self, request, pk=None):
        task = self.get_object()
        if request.method == "GET":
            return Response(AdHocTaskAttachmentSerializer(task.attachments.all(), many=True).data)
        if request.method == "POST":
            f = request.FILES.get("file")
            if not f:
                return Response({"detail": "No file provided."}, status=400)
            att = AdHocTaskAttachment.objects.create(
                task=task, file=f, title=request.data.get("title", f.name)
            )
            return Response(AdHocTaskAttachmentSerializer(att).data, status=201)
        # DELETE — expects attachment_id in query params
        att_id = request.query_params.get("attachment_id")
        if att_id:
            task.attachments.filter(id=att_id).delete()
        return Response(status=204)


@api_view(["GET", "PATCH"])
def report_format_template(request, project_id):
    """GET or PATCH the report format templates for a project."""
    project = Project.objects.get(pk=project_id)
    obj, _ = ProjectReportTemplate.objects.get_or_create(project=project)
    if request.method == "GET":
        return Response(ReportFormatTemplateSerializer(obj).data)
    # PATCH
    for field in ["weekly_format", "daily_format", "custom_format"]:
        if field in request.data:
            setattr(obj, field, request.data[field])
    obj.save()
    return Response(ReportFormatTemplateSerializer(obj).data)


@api_view(["GET", "PATCH"])
def org_settings(request):
    """GET or PATCH the organization-wide settings (singleton)."""
    if not request.user.is_admin:
        return Response(status=403)
    obj = OrganizationSettings.get()
    if request.method == "GET":
        return Response(OrganizationSettingsSerializer(obj).data)
    for field in ["company_name", "company_tagline", "logo_url", "pdf_accent_color",
                  "pdf_header_text", "pdf_footer_text", "email_signature"]:
        if field in request.data:
            setattr(obj, field, request.data[field])
    obj.save()
    return Response(OrganizationSettingsSerializer(obj).data)


from django.core import signing
from rest_framework.decorators import permission_classes
from rest_framework.permissions import AllowAny

@api_view(["GET"])
@permission_classes([AllowAny])
def shared_report_view(request, token):
    """Publicly accessible view for shared reports."""
    try:
        data = signing.loads(token, max_age=86400*30) # 30 days
    except signing.SignatureExpired:
        return HttpResponse("Link expired.", status=403)
    except signing.BadSignature:
        return HttpResponse("Invalid link.", status=403)
        
    project = Project.objects.get(id=data["p"])
    report_type = data["t"]
    
    if report_type == "weekly":
        week = data["w"]
        context = weekly_report_context(project, week)
        template = "notifications/emails/weekly_report.html"
    elif report_type == "daily":
        from datetime import date as date_cls
        report_date = date_cls.fromisoformat(data["d"])
        context = daily_report_context(project, report_date)
        template = "notifications/emails/daily_report.html"
    elif report_type == "custom":
        from datetime import date as date_cls
        date_from = date_cls.fromisoformat(data["df"])
        date_to = date_cls.fromisoformat(data["dt"])
        context = custom_range_report_context(project, date_from, date_to)
        template = "notifications/emails/custom_range_report.html"
    else:
        return HttpResponse("Unknown report type.", status=400)
        
    try:
        from .models import OrganizationSettings
        context["org"] = OrganizationSettings.get()
    except Exception:
        pass
        
    html = render_to_string(template, context)
    return HttpResponse(html)


@api_view(["GET", "POST"])
def milestone_report_pdf(request):
    """Accept an HTML string and return a PDF file download for milestone reports."""
    data = request.data if isinstance(request.data, dict) else {}
    html = data.get("html") or request.query_params.get("html", "")
    project_name = data.get("project_name") or request.query_params.get("project_name", "Milestones")
    if not html:
        return Response({"detail": "html is required."}, status=400)
    try:
        pdf_bytes = render_report_pdf(html, title=f"{project_name} — Milestone Report")
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        safe_name = project_name.replace(" ", "_")
        response["Content-Disposition"] = f'attachment; filename="{safe_name}_milestones.pdf"'
        return response
    except Exception as e:
        logger.error("Milestone PDF error: %s", e)
        return Response({"detail": f"PDF generation failed: {e}"}, status=500)
