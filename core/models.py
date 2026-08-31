from django.db import models
from django.conf import settings


class Client(models.Model):
    name = models.CharField(max_length=120)
    contact = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Project(models.Model):
    name = models.CharField(max_length=160)
    client = models.ForeignKey(Client, null=True, blank=True, on_delete=models.SET_NULL, related_name="projects")
    ref = models.CharField(max_length=60, blank=True)  # e.g. JMS-AGR-2026-032
    start_date = models.DateField()
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
        from datetime import timedelta
        days, d = [], self.start_date
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
    status = models.CharField(max_length=6, choices=Status.choices, default=Status.TODO)
    done_at = models.DateTimeField(null=True, blank=True)
    comment = models.TextField(blank=True)

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
