from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        DEVELOPER = "DEVELOPER", "Developer"

    role = models.CharField(max_length=12, choices=Role.choices, default=Role.DEVELOPER)
    designation = models.CharField(max_length=80, blank=True)  # e.g. "Backend Lead"
    phone = models.CharField(max_length=20, blank=True)        # for WhatsApp notifications
    email = models.EmailField(unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN

    def __str__(self):
        return f"{self.get_full_name() or self.email} ({self.designation or self.role})"
