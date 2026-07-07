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

    class Meta:
        ordering = ["date", "developer_id"]

    def __str__(self):
        return f"D{self.day_num} {self.developer} — {self.title}"


class Update(models.Model):
    """Announcements the admin posts to the project team (also emailed)."""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="updates")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


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
