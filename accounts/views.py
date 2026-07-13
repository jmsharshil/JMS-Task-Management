from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from .models import User
from .serializers import UserSerializer, CreateUserSerializer
from .permissions import IsAdmin


@api_view(["GET"])
def me(request):
    return Response(UserSerializer(request.user).data)


class UserViewSet(viewsets.ModelViewSet):
    """Admin-only team management: add developers with designations, reset passwords."""
    queryset = User.objects.all().order_by("first_name")
    permission_classes = [IsAdmin]

    def get_serializer_class(self):
        return CreateUserSerializer if self.action == "create" else UserSerializer

    def create(self, request, *args, **kwargs):
        ser = CreateUserSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = ser.save()
        # Welcome email with credentials happens async
        from notifications.tasks import send_welcome_email
        send_welcome_email(user.id, request.data.get("password", ""))
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        """Admin resets a user's password. Sends a notification email."""
        user = self.get_object()
        new_password = request.data.get("password", "").strip()
        if len(new_password) < 6:
            return Response({"detail": "Password must be at least 6 characters."}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(new_password)
        user.save()
        from notifications.tasks import send_password_reset_email
        send_password_reset_email(user.id, new_password)
        return Response({"detail": f"Password reset for {user.get_full_name() or user.email}."})


@api_view(["POST"])
def change_password(request):
    """Any authenticated user can change their own password."""
    old_password = request.data.get("old_password", "")
    new_password = request.data.get("new_password", "").strip()
    if not request.user.check_password(old_password):
        return Response({"detail": "Current password is incorrect."}, status=status.HTTP_400_BAD_REQUEST)
    if len(new_password) < 6:
        return Response({"detail": "New password must be at least 6 characters."}, status=status.HTTP_400_BAD_REQUEST)
    request.user.set_password(new_password)
    request.user.save()
    return Response({"detail": "Password changed successfully."})
