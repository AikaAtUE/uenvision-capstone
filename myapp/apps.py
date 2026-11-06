from django.apps import AppConfig


class MyappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'myapp'

    def ready(self):
        # Rebuilds the subject profiles after every curriculum survey submit / edit / delete.
        from . import subject_profiles  # noqa: F401
