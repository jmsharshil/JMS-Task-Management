from rest_framework.routers import DefaultRouter
from django.urls import path
from . import views

router = DefaultRouter()
router.register("clients", views.ClientViewSet, basename="clients")
router.register("projects", views.ProjectViewSet, basename="projects")
router.register("tasks", views.TaskViewSet, basename="tasks")
router.register("adhoc-tasks", views.AdHocTaskViewSet, basename="adhoc-tasks")
router.register("milestones", views.ProjectMilestoneViewSet, basename="milestones")

urlpatterns = [
    path("dashboard/", views.dashboard),
    path("projects/<int:project_id>/report-format/", views.report_format_template),
    path("org-settings/", views.org_settings),
    path("shared/report/<str:token>/", views.shared_report_view),
    path("milestone-report-pdf/", views.milestone_report_pdf),
] + router.urls

