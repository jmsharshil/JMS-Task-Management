from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes
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
