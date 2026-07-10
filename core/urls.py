from rest_framework.routers import DefaultRouter
from django.urls import path
from . import views

router = DefaultRouter()
router.register("clients", views.ClientViewSet, basename="clients")
router.register("projects", views.ProjectViewSet, basename="projects")
router.register("tasks", views.TaskViewSet, basename="tasks")
router.register("adhoc-tasks", views.AdHocTaskViewSet, basename="adhoc-tasks")

urlpatterns = [path("dashboard/", views.dashboard)] + router.urls
