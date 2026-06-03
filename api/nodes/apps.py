import os
from django.apps import AppConfig


class NodesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "nodes"

    def ready(self):
        if os.environ.get("RUN_MAIN") == "true":
            from .scheduler import start_command_scheduler
            start_command_scheduler()

