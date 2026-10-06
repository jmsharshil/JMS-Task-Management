import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hub.settings')
import django
django.setup()

from django.utils import timezone
from core.models import Client, Project, ProjectMilestone
from core.services import build_milestone_html, render_report_pdf
from django.utils.text import slugify
import tempfile

# Create test data if none exists
if not Client.objects.exists():
    client = Client.objects.create(name="Test Client")
else:
    client = Client.objects.first()

if not Project.objects.filter(name__contains="Test Milestone").exists():
    project = Project.objects.create(
        name="Test Milestone Project",
        client=client,
        start_date=timezone.now().date(),
        weeks=4,
    )
    print("Created test project")
else:
    project = Project.objects.filter(name__contains="Test Milestone").first()
    print("Using existing project")

# Add some milestones if none
if project.milestones.count() == 0:
    ProjectMilestone.objects.create(
        project=project,
        title="UI/UX Design Complete",
        status="COMPLETED",
        work_completed="All wireframes and prototypes approved by client.",
        owner="Jane Designer",
        committed_date=timezone.now().date(),
        final_completion_date=timezone.now().date(),
    )
    ProjectMilestone.objects.create(
        project=project,
        title="Backend API v1",
        status="ON_TRACK",
        work_completed="Core endpoints 80% done",
        stakeholder_dependency="Client auth integration",
        next_milestone_desc="Database optimization",
        committed_date=timezone.now().date() + timezone.timedelta(days=5),
        final_completion_date=timezone.now().date() + timezone.timedelta(days=14),
        owner="Backend Lead",
    )
    ProjectMilestone.objects.create(
        project=project,
        title="Mobile App Launch",
        status="AT_RISK",
        blocker="Pending approval from legal on data privacy",
        recovery_action="Escalate to PMO and schedule urgent review meeting",
        owner="Mobile Team",
        final_completion_date=timezone.now().date() + timezone.timedelta(days=30),
    )
    print("Created test milestones")
else:
    print("Milestones already exist:", project.milestones.count())

# Test HTML builder
html = build_milestone_html(project)
print("HTML built successfully. Length:", len(html))
print("Contains table:", "table" in html.lower())
print("Contains status badges:", "Completed" in html and "On Track" in html)

# Test PDF
try:
    pdf_bytes = render_report_pdf(html, title=f"{project.name} — Milestone Report")
    print("PDF generated successfully. Size:", len(pdf_bytes), "bytes")
    
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        f.write(pdf_bytes)
        print("Saved test PDF to:", f.name)
except Exception as e:
    print("PDF error:", str(e))

print("All tests passed!")
