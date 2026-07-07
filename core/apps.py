from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        import os,sys
        from django.conf import settings
        # Start only in the main process when using runserver
        ignored_commands = ["test", "makemigrations", "migrate", "showmigrations"]
        if any(cmd in sys.argv for cmd in ignored_commands):
            return
        if os.environ.get("RUN_MAIN", None) == "true" or not settings.DEBUG:
            from core.scheduler import start_scheduler
            start_scheduler()
