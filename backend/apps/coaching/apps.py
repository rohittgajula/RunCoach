from django.apps import AppConfig


class CoachingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.coaching"

    def ready(self):
        # R18: a memory fact's parameters follow its text, whatever path saved it.
        from django.db.models.signals import post_delete, post_save

        from .models import MemoryFact
        from .signals import fact_deleted, fact_saved

        post_save.connect(fact_saved, sender=MemoryFact, dispatch_uid="r18-fact-saved")
        post_delete.connect(fact_deleted, sender=MemoryFact, dispatch_uid="r18-fact-deleted")
