import os
from django.core.management.base import BaseCommand
from accounts.models import User


class Command(BaseCommand):
    help = "Create the first admin account from ADMIN_EMAIL / ADMIN_PASSWORD env vars (idempotent)."

    def handle(self, *args, **kwargs):
        email = os.getenv("ADMIN_EMAIL")
        password = os.getenv("ADMIN_PASSWORD")
        name = os.getenv("ADMIN_NAME", "Admin")
        if not email or not password:
            self.stdout.write("ADMIN_EMAIL/ADMIN_PASSWORD not set; skipping.")
            return
        if User.objects.filter(email=email).exists():
            self.stdout.write(f"Admin {email} already exists; skipping.")
            return
        parts = name.split(" ", 1)
        user = User(email=email, username=email, first_name=parts[0],
                    last_name=parts[1] if len(parts) > 1 else "",
                    role=User.Role.ADMIN, is_staff=True, is_superuser=True,
                    designation="Founder")
        user.set_password(password)
        user.save()
        self.stdout.write(self.style.SUCCESS(f"Admin {email} created."))
