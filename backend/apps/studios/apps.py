from django.apps import AppConfig


class StudiosConfig(AppConfig):
    name = "apps.studios"
    label = "studios"

    def ready(self):
        from . import checks  # noqa: F401 - registers the system checks
