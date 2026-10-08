from django.apps import AppConfig


class AthletesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.athletes'

    def ready(self):
        # R18 §B: every write to an athlete's data bumps their data version.
        from django.db.models.signals import post_delete, post_save

        from .versioning import on_write

        post_save.connect(on_write, dispatch_uid="r18-data-version-save")
        post_delete.connect(on_write, dispatch_uid="r18-data-version-delete")
