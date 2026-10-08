"""R18: memory facts → profile parameters (apps.athletes.profile_params)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def fact_saved(sender, instance, raw=False, **kwargs):
    if raw or instance.text == instance.params_text:
        return
    from apps.athletes.profile_params import reparse

    try:
        reparse(instance)
    except Exception:  # noqa: BLE001 — a parse must never lose the fact
        logger.exception("parsing memory fact %s failed", instance.pk)


def fact_deleted(sender, instance, **kwargs):
    from apps.athletes.models import Athlete
    from apps.athletes.profile_params import sync_plan_fields

    athlete = Athlete.objects.filter(pk=instance.athlete_id).first()
    if athlete is None:              # account deletion cascade
        return
    try:
        sync_plan_fields(athlete)    # its parameters are gone: fall back
    except Exception:  # noqa: BLE001
        logger.exception("profile fallback after deleting fact %s failed", instance.pk)
