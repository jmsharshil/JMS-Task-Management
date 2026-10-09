from django.db import models
from django.conf import settings


class Client(models.Model):
    name = models.CharField(max_length=120)
    contact = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Project(models.Model):
    # Category: which hub section does this project belong to
    class Category(models.TextChoices):
        JMS = "JMS", "JMS Projects"
        NAAVYA = "NAAVYA", "Naavya AI"
        DEMO = "DEMO", "Demo"

    # Project type: specific type within the category
    class ProjectType(models.TextChoices):
        # JMS types
        SOFTWARE = "SOFTWARE", "Custom Software"
        SERVICES = "SERVICES", "Services"
        # Naavya types
        VOICE = "VOICE", "Voice Only"
        VOICE_WHATSAPP = "VOICE_WHATSAPP", "Voice + WhatsApp"
        WHATSAPP = "WHATSAPP", "WhatsApp Only"
        # Demo
        DEMO = "DEMO", "Demo"

    name = models.CharField(max_length=160)
    category = models.CharField(
        max_length=10, choices=Category.choices, default=Category.JMS,
        help_text="Hub section: JMS Projects, Naavya AI, or Demo"
    )
    project_type = models.CharField(
        max_length=20, choices=ProjectType.choices, default=ProjectType.SOFTWARE,
        help_text="Specific project type within the category"
    )
    client = models.ForeignKey(Client, null=True, blank=True, on_delete=models.SET_NULL, related_name="projects")
    ref = models.CharField(max_length=60, blank=True)  # e.g. JMS-AGR-2026-032
    start_date = models.DateField()
    demo_time = models.DateTimeField(null=True, blank=True)
    weeks = models.PositiveSmallIntegerField(default=8)
    team = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="projects")
    team_leaders = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name="led_projects", blank=True
    )
    brief_summary = models.TextField(blank=True)
    brief_modules = models.JSONField(default=list, blank=True)
    sow_pdf = models.FileField(upload_to="sow/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def working_days(self):
        """List of ISO dates, Mon-Fri only, weeks*5 long."""
        from datetime import timedelta, date
        days, d = [], self.start_date
        if isinstance(d, str):
            d = date.fromisoformat(d)
        while len(days) < self.weeks * 5:
            if d.weekday() < 5:
                days.append(d)
            d += timedelta(days=1)
        return days

    def __str__(self):
        return self.name


class Task(models.Model):
    class Status(models.TextChoices):
        TODO = "TODO", "To Do"
        DONE = "DONE", "Done"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    day_num = models.PositiveSmallIntegerField()           # 1..weeks*5  (D1, D2 ...)
    date = models.DateField()
    week = models.PositiveSmallIntegerField()              # 1..weeks    (W1, W2 ...)
    developer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tasks")
    module = models.CharField(max_length=60, default="General")
    title = models.CharField(max_length=240)
    description = models.TextField(blank=True)            # optional detail for additional tasks
    status = models.CharField(max_length=6, choices=Status.choices, default=Status.TODO)
    done_at = models.DateTimeField(null=True, blank=True)
    comment = models.TextField(blank=True)
    # Additional (manually-added) task fields
    is_additional = models.BooleanField(default=False)    # True = manually added by admin
    priority = models.CharField(
        max_length=8,
        choices=[("LOW", "Low"), ("MEDIUM", "Medium"), ("HIGH", "High"), ("URGENT", "Urgent")],
        default="MEDIUM",
    )

    class Meta:
        ordering = ["date", "developer_id"]

    def __str__(self):
        return f"D{self.day_num} {self.developer} — {self.title}"


class ProjectDocument(models.Model):
    """Extra files attached to a project (SOW revisions, specs, design docs, etc.)."""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="documents")
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to="project_docs/")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.project.name} — {self.title}"


class Update(models.Model):
    """Announcements the admin posts to the project team (also emailed)."""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="updates")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class AdHocTask(models.Model):
    """Standalone tasks assigned by admin to team members, not tied to any project."""
    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        URGENT = "URGENT", "Urgent"

    class Status(models.TextChoices):
        TODO = "TODO", "To Do"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        DONE = "DONE", "Done"

    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    assignees = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name="assigned_adhoc_tasks", blank=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="adhoc_tasks_created"
    )
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.TODO)
    start_date = models.DateField(null=True, blank=True)
    due_date = models.DateTimeField()
    comment = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["due_date", "-priority", "created_at"]

    def __str__(self):
        assignees = self.assignees.all()
        assignee_str = assignees[0].get_full_name() or assignees[0].username if assignees else "Unassigned"
        return f"{self.title} → {assignee_str}"


class AdHocTaskAttachment(models.Model):
    """File attachments on ad-hoc tasks."""
    task = models.ForeignKey(AdHocTask, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="adhoc_attachments/")
    title = models.CharField(max_length=200)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.task.title} — {self.title}"


class BackgroundJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RUNNING = "RUNNING", "Running"
        DONE = "DONE", "Done"
        FAILED = "FAILED", "Failed"

    task_name = models.CharField(max_length=255)
    args = models.JSONField(default=list, blank=True)
    kwargs = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    error_log = models.TextField(blank=True)
    retry_count = models.PositiveSmallIntegerField(default=0)
    max_retry = models.PositiveSmallIntegerField(default=3)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]


class ProjectArchitecture(models.Model):
    """High-level architecture document generated by AI and approved before detailed planning."""
    project = models.OneToOneField('Project', on_delete=models.CASCADE, related_name='architecture', null=True, blank=True)
    title = models.CharField(max_length=200, default="System Architecture & Technical Design")
    content = models.JSONField(default=dict)  # structured: {overview, tech_stack, components, data_flow, mermaid_diagrams, risks, etc.}
    status = models.CharField(
        max_length=20,
        choices=[
            ('DRAFT', 'Draft'),
            ('APPROVED', 'Approved'),
            ('REJECTED', 'Rejected'),
        ],
        default='DRAFT'
    )
    version = models.PositiveSmallIntegerField(default=1)
    generated_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='approved_architectures'
    )
    notes = models.TextField(blank=True)  # admin notes on approval/rejection

    class Meta:
        ordering = ['-generated_at']
        verbose_name_plural = "Project Architectures"

    def __str__(self):
        status_str = self.get_status_display()
        proj = self.project.name if self.project else "Pre-Project"
        return f"Arch v{self.version} for {proj} — {status_str}"

    def approve(self, user):
        """Helper to approve."""
        from django.utils import timezone
        self.status = 'APPROVED'
        self.approved_at = timezone.now()
        self.approved_by = user
        self.save()

class MeetingMinutes(models.Model):
    """Minutes of Meeting (MOM) per project — stored and can be exported/emailed."""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="moms")
    title = models.CharField(max_length=300)
    meeting_date = models.DateField()
    meeting_time = models.TimeField(null=True, blank=True)  # time of meeting
    attendees = models.TextField(blank=True)  # comma-separated or free text
    agenda = models.TextField(blank=True)
    discussion = models.TextField(blank=True)
    decisions = models.TextField(blank=True)
    action_items = models.TextField(blank=True)  # free-form action items
    next_meeting_date = models.DateField(null=True, blank=True)
    next_meeting_time = models.TimeField(null=True, blank=True)  # time of next meeting
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-meeting_date", "-created_at"]

    def __str__(self):
        return f"MOM: {self.title} ({self.meeting_date}) — {self.project.name}"

class ProjectReportTemplate(models.Model):
    """
    Stores per-project report format templates.
    These are format strings (not content) that control how each report type is structured.
    Available placeholders vary by report type:
      Weekly:  {project}, {week}, {done}, {total}, {pct}, {completed}, {pending}
      Daily:   {project}, {date}, {done_today}, {total_today}, {overall_pct}, {completed}, {pending}
      Custom:  {project}, {date_from}, {date_to}, {done_range}, {total_range}, {pct}, {completed}, {pending}
    If blank, the auto-generated text is used as-is.
    """
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="report_template")
    weekly_format = models.TextField(blank=True, default="",
        help_text="Format template for weekly report. Leave blank to use auto-generated text.")
    daily_format = models.TextField(blank=True, default="",
        help_text="Format template for daily report. Leave blank to use auto-generated text.")
    custom_format = models.TextField(blank=True, default="",
        help_text="Format template for custom/date-range report. Leave blank to use auto-generated text.")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Report format templates for {self.project.name}"


class OrganizationSettings(models.Model):
    """
    Singleton model for organization-wide settings.
    Controls PDF branding: header logo, company name, colors, footer text.
    Only one record should exist (pk=1).
    """
    company_name = models.CharField(max_length=200, default="JMS Tech")
    company_tagline = models.CharField(max_length=300, blank=True, default="Project Management & Delivery Tracking")
    logo_url = models.URLField(blank=True, default="",
        help_text="URL to the company logo shown in PDF/email headers.")
    pdf_accent_color = models.CharField(max_length=7, default="#2563eb",
        help_text="Hex color for PDF accent elements (e.g. #2563eb)")
    pdf_header_text = models.TextField(blank=True, default="",
        help_text="Additional text shown in PDF headers (e.g. address, website).")
    pdf_footer_text = models.TextField(blank=True, default="Generated by JMS Delivery Hub",
        help_text="Text shown in PDF/email footers.")
    email_signature = models.TextField(blank=True, default="— JMS Delivery Hub",
        help_text="Signature appended to plain-text emails.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Organization Settings"
        verbose_name_plural = "Organization Settings"

    def __str__(self):
        return f"Organization Settings — {self.company_name}"

    @classmethod
    def get(cls):
        """Always returns the singleton settings object, creating it if needed."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class ProjectMilestone(models.Model):
    """
    Tracks clear, specific milestones for a project.
    Includes:
    - exact deliverable / scope remaining
    - current status and work completed to date
    - stakeholder / dependency, if any
    - next milestone and committed date
    - final completion / go-live date
    - blocker, owner and recovery action where a milestone is at risk.
    """
    class Status(models.TextChoices):
        ON_TRACK = "ON_TRACK", "On Track"
        AT_RISK = "AT_RISK", "At Risk"
        DELAYED = "DELAYED", "Delayed"
        COMPLETED = "COMPLETED", "Completed"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="milestones")
    title = models.CharField(max_length=300, help_text="Exact deliverable / scope remaining")
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.ON_TRACK)
    work_completed = models.TextField(blank=True, help_text="Work completed to date")
    
    stakeholder_dependency = models.TextField(blank=True, help_text="Stakeholder / dependency, if any")
    
    next_milestone_desc = models.CharField(max_length=300, blank=True, help_text="Next milestone description")
    committed_date = models.DateField(null=True, blank=True, help_text="Next milestone committed date")
    
    final_completion_date = models.DateField(null=True, blank=True, help_text="Final completion / go-live date")
    
    blocker = models.TextField(blank=True, help_text="Blocker if at risk")
    owner = models.CharField(max_length=200, null=True, blank=True, help_text="Owner name (client-side contact or responsible party)")
    recovery_action = models.TextField(blank=True, help_text="Recovery action if at risk")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["final_completion_date", "created_at"]

    def __str__(self):
        return f"{self.project.name} - {self.title}"

