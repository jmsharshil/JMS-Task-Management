from rest_framework import serializers
from .models import Client, Project, Task, Update
from accounts.serializers import UserSerializer


class ClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = ["id", "name", "contact"]


class TaskSerializer(serializers.ModelSerializer):
    developer_name = serializers.CharField(source="developer.get_full_name", read_only=True)
    project_name = serializers.CharField(source="project.name", read_only=True)

    class Meta:
        model = Task
        fields = ["id", "project", "project_name", "day_num", "date", "week",
                  "developer", "developer_name", "module", "title", "status", "done_at"]
        read_only_fields = ["project", "day_num", "date", "week"]


class UpdateSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.get_full_name", read_only=True)

    class Meta:
        model = Update
        fields = ["id", "text", "author_name", "created_at"]


class ProjectSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source="client.name", read_only=True)
    team_detail = UserSerializer(source="team", many=True, read_only=True)
    stats = serializers.SerializerMethodField()
    latest_update = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = ["id", "name", "client", "client_name", "ref", "start_date", "weeks",
                  "team", "team_detail", "brief_summary", "brief_modules", "stats",
                  "latest_update", "created_at"]

    def get_stats(self, obj):
        total = obj.tasks.count()
        done = obj.tasks.filter(status="DONE").count()
        return {"total": total, "done": done, "pct": round(done / total * 100) if total else 0}

    def get_latest_update(self, obj):
        u = obj.updates.first()
        return UpdateSerializer(u).data if u else None
