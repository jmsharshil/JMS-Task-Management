from rest_framework import serializers
from .models import Client, Project, Task, Update, ProjectDocument, AdHocTask, AdHocTaskAttachment, ProjectArchitecture

AZURE_BLOB_PREFIX = "https://hrmsknowcraftstorage.blob.core.windows.net"

def _resolve_file_url(file_field):
    """Return an absolute URL for a FileField, routing local /media/ to Azure blob."""
    if not file_field:
        return None
    url = file_field.url
    if url.startswith("/media/"):
        return f"{AZURE_BLOB_PREFIX}{url}"
    return url
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
                  "developer", "developer_name", "module", "title", "status", "done_at", "comment"]
        read_only_fields = ["project", "day_num", "date", "week"]


class ProjectDocumentSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(source="uploaded_by.get_full_name", read_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = ProjectDocument
        fields = ["id", "title", "file_url", "uploaded_by_name", "uploaded_at"]

    def get_file_url(self, obj):
        return _resolve_file_url(obj.file)


class UpdateSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.get_full_name", read_only=True)

    class Meta:
        model = Update
        fields = ["id", "text", "author_name", "created_at"]


class ProjectArchitectureSerializer(serializers.ModelSerializer):
    approved_by_name = serializers.CharField(source="approved_by.get_full_name", read_only=True)
    content_preview = serializers.SerializerMethodField()

    class Meta:
        model = ProjectArchitecture
        fields = ["id", "title", "content", "status", "version", "generated_at",
                  "approved_at", "approved_by", "approved_by_name", "notes", "content_preview"]
        read_only_fields = ["generated_at", "approved_at", "approved_by"]

    def get_content_preview(self, obj):
        """Return short preview for list views."""
        if isinstance(obj.content, dict) and "overview" in obj.content:
            overview = obj.content["overview"]
            return overview[:120] + "..." if len(overview) > 120 else overview
        return str(obj.content)[:120]


class ProjectSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source="client.name", read_only=True)
    team_detail = UserSerializer(source="team", many=True, read_only=True)
    team_leaders_detail = UserSerializer(source="team_leaders", many=True, read_only=True)
    stats = serializers.SerializerMethodField()
    latest_update = serializers.SerializerMethodField()
    sow_pdf = serializers.SerializerMethodField()
    architecture = ProjectArchitectureSerializer(read_only=True)

    class Meta:
        model = Project
        fields = ["id", "name", "client", "client_name", "ref", "start_date", "weeks",
                  "team", "team_leaders", "team_detail", "team_leaders_detail", "brief_summary", "brief_modules", "stats",
                  "latest_update", "created_at", "sow_pdf", "architecture"]

    def get_sow_pdf(self, obj):
        return _resolve_file_url(obj.sow_pdf)

    def get_stats(self, obj):
        total = obj.tasks.count()
        done = obj.tasks.filter(status="DONE").count()
        return {"total": total, "done": done, "pct": round(done / total * 100) if total else 0}

    def get_latest_update(self, obj):
        u = obj.updates.first()
        return UpdateSerializer(u).data if u else None


class AdHocTaskAttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = AdHocTaskAttachment
        fields = ["id", "title", "file_url", "uploaded_at"]

    def get_file_url(self, obj):
        return _resolve_file_url(obj.file)


class AdHocTaskSerializer(serializers.ModelSerializer):
    assignees_detail = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(source="created_by.get_full_name", read_only=True)
    attachments = AdHocTaskAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = AdHocTask
        fields = [
            "id", "title", "description", "assignees", "assignees_detail",
            "created_by", "created_by_name", "priority", "status",
            "start_date", "due_date", "comment", "completed_at",
            "created_at", "updated_at", "attachments",
        ]
        read_only_fields = ["created_by", "completed_at", "created_at", "updated_at"]

    def get_assignees_detail(self, obj):
        return [{"id": u.id, "name": u.get_full_name() or u.username} for u in obj.assignees.all()]
