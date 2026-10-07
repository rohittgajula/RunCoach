"""Web push (R10 §C12) with VAPID. With any of VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY /
VAPID_SUBJECT missing the feature is off: nothing is sent and pywebpush is never
imported. Payloads carry no habit counts or health numbers — only a title, a short
body, a URL to open and a tag."""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.utils import timezone

from .models import PushSubscription

logger = logging.getLogger(__name__)

GONE = {404, 410}
MAX_FAILURES = 10
TTL_S = 6 * 3600


def available() -> bool:
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY
                and settings.VAPID_SUBJECT)


def _subject() -> str:
    subject = settings.VAPID_SUBJECT
    if subject.startswith(("mailto:", "https://")):
        return subject
    return f"mailto:{subject}"


def send_one(sub: PushSubscription, message: dict) -> bool:
    """True when the push service accepted it. Expired subscriptions are deleted."""
    if not available():
        return False
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info={"endpoint": sub.endpoint,
                               "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
            data=json.dumps(message),
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": _subject()},
            ttl=TTL_S, timeout=10,
        )
    except WebPushException as exc:
        code = getattr(getattr(exc, "response", None), "status_code", None)
        if code in GONE:
            sub.delete()
            return False
        logger.warning("web push failed (%s) for subscription %s", code, sub.pk)
        _failed(sub)
        return False
    except Exception:  # noqa: BLE001 — network trouble must not break the beat task
        logger.exception("web push error for subscription %s", sub.pk)
        _failed(sub)
        return False
    sub.failures = 0
    sub.last_success_at = timezone.now()
    sub.save(update_fields=["failures", "last_success_at"])
    return True


def _failed(sub: PushSubscription) -> None:
    sub.failures += 1
    if sub.failures >= MAX_FAILURES:
        sub.delete()
    else:
        sub.save(update_fields=["failures"])


def send_to_athlete(athlete, message: dict) -> tuple[int, int]:
    sent = failed = 0
    for sub in list(PushSubscription.objects.filter(athlete=athlete)):
        if send_one(sub, message):
            sent += 1
        else:
            failed += 1
    return sent, failed
