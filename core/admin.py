from django.contrib import admin
from .models import Client, Project, Task, Update, ProjectArchitecture, ProjectMilestone


@admin.register(ProjectArchitecture)
class ProjectArchitectureAdmin(admin.ModelAdmin):
    list_display = ("title", "project", "status", "version", "generated_at", "approved_by")
    list_filter = ("status", "version")
    search_fields = ("title", "project__name")
    readonly_fields = ("generated_at", "approved_at")


@admin.register(ProjectMilestone)
class ProjectMilestoneAdmin(admin.ModelAdmin):
    list_display = ("title", "project", "status", "owner", "committed_date", "final_completion_date")
    list_filter = ("status", "project")
    search_fields = ("title", "owner", "project__name")


admin.site.register([Client, Project, Task, Update])