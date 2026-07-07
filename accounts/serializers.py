from rest_framework import serializers
from .models import User


class UserSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "name", "first_name", "last_name", "role", "designation", "phone"]

    def get_name(self, obj):
        return obj.get_full_name() or obj.email


class CreateUserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)
    name = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ["email", "name", "password", "role", "designation", "phone"]

    def create(self, validated):
        name = validated.pop("name", "")
        parts = name.split(" ", 1)
        user = User(
            email=validated["email"], username=validated["email"],
            first_name=parts[0], last_name=parts[1] if len(parts) > 1 else "",
            role=validated.get("role", User.Role.DEVELOPER),
            designation=validated.get("designation", ""),
            phone=validated.get("phone", ""),
        )
        user.set_password(validated["password"])
        user.save()
        return user
