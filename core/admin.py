from django.contrib import admin
from .models import Client, Project, Task, Update, ProjectArchitecture


@admin.register(ProjectArchitecture)
class ProjectArchitectureAdmin(admin.ModelAdmin):
    list_display = ("title", "project", "status", "version", "generated_at", "approved_by")
    list_filter = ("status", "version")
    search_fields = ("title", "project__name")
    readonly_fields = ("generated_at", "approved_at")


admin.site.register([Client, Project, Task, Update])