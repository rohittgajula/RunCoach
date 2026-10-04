"""A synced activity on a planned day completes that day's workout.

A signal rather than a call inside ingest, so every path that creates an activity —
Garmin sync, a manual FIT upload, a re-ingest command — links the same way.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.activities.models import Activity


@receiver(post_save, sender=Activity, dispatch_uid="planning.link_activity")
def link_new_activity(sender, instance, created, **kwargs):
    if not created:
        return
    from .plan_store import link_activity

    link_activity(instance)
