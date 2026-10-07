"""System health for the admin page (R14 §14): Garmin breaker + sync status, Celery
queue lengths, backups, nodes/pods via the read-only ServiceAccount, app version, GCP
trial. Every part degrades on its own — one unreachable piece never fails the page."""

from __future__ import annotations

import datetime as dt
import logging
import os

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from . import k8s

logger = logging.getLogger(__name__)

QUEUES = ("celery", "garmin", "metrics", "ai", "planning")


def garmin_status() -> dict:
    from apps.athletes.models import Athlete
    from apps.ingest.tasks import BREAKER_KEY

    reason, ttl = None, None
    try:
        reason = cache.get(BREAKER_KEY)
        if reason is not None and hasattr(cache, "ttl"):
            ttl = cache.ttl(BREAKER_KEY)
    except Exception:  # noqa: BLE001
        reason = None
    if ttl is None and reason is not None:
        try:
            client = cache._cache.get_client(BREAKER_KEY)          # Django RedisCache
            ttl = client.ttl(cache.make_and_validate_key(BREAKER_KEY))
        except Exception:  # noqa: BLE001
            ttl = None
    now = timezone.now()
    users = []
    for a in Athlete.objects.filter(garmin_connected=True).order_by("display_name"):
        last = a.garmin_last_sync
        users.append({"athlete_id": a.pk, "name": a.display_name, "connected": True,
                      "last_sync": last,
                      "hours_since_sync": round((now - last).total_seconds() / 3600, 1)
                      if last else None,
                      "backfilled": a.garmin_backfilled})
    return {"breaker_open": reason is not None, "reason": str(reason)[:200] if reason else None,
            "retry_after_s": int(ttl) if isinstance(ttl, (int, float)) and ttl > 0 else None,
            "users": users}


def celery_status() -> dict:
    try:
        import redis

        client = redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_timeout=2,
                                      socket_connect_timeout=2)
        return {"available": True,
                "queues": [{"name": q, "length": int(client.llen(q))} for q in QUEUES]}
    except Exception as exc:  # noqa: BLE001
        logger.info("admin: celery queues unavailable: %s", exc)
        return {"available": False, "queues": []}


def version_info() -> dict:
    sha = os.environ.get("GIT_SHA") or os.environ.get("APP_VERSION") or None
    if sha:
        return {"git_sha": sha, "image": None, "source": "env"}
    try:
        image = k8s.own_image()
    except k8s.K8sUnavailable:
        image = None
    if image:
        tag = image.rsplit(":", 1)[-1] if ":" in image.rsplit("/", 1)[-1] else None
        return {"git_sha": tag, "image": image, "source": "kubernetes"}
    return {"git_sha": None, "image": None, "source": None}


def backups() -> dict:
    r2 = os.environ.get("R2_BUCKET")
    r2_block = {"configured": True if r2 else None,
                "note": ("Uploaded by the backup job when the runcoach-r2 Secret exists; "
                         "the backend can't see the bucket." if not r2 else
                         "R2 bucket configured.")}
    try:
        status = k8s.backup_status()
    except k8s.K8sUnavailable as exc:
        return {"available": False, "reason": exc.reason, "schedule": None,
                "last_success_at": None, "last_schedule_at": None, "jobs": [], "r2": r2_block}
    return {"available": True, "reason": None, **status, "r2": r2_block}


def kubernetes() -> dict:
    try:
        nodes = k8s.nodes()
        pods = k8s.pods()
    except k8s.K8sUnavailable as exc:
        return {"available": False, "reason": exc.reason, "nodes": [], "pods": []}
    return {"available": True, "reason": None, "nodes": nodes, "pods": pods}


def gcp(today: dt.date | None = None) -> dict:
    today = today or timezone.now().date()
    raw_end = getattr(settings, "GCP_TRIAL_END", "") or ""
    raw_credit = getattr(settings, "GCP_CREDIT_INR", "") or ""
    try:
        end = dt.date.fromisoformat(raw_end) if raw_end else None
    except ValueError:
        end = None
    try:
        credit = float(raw_credit) if raw_credit != "" else None
    except ValueError:
        credit = None
    return {"configured": end is not None or credit is not None, "trial_end": end,
            "days_left": max((end - today).days, 0) if end else None, "credit_inr": credit}


@api_view(["GET"])
@permission_classes([IsAdminUser])
def system(request):
    return Response({"version": version_info(), "garmin": garmin_status(),
                     "celery": celery_status(), "backups": backups(),
                     "kubernetes": kubernetes(), "gcp": gcp(), "checked_at": timezone.now()})
