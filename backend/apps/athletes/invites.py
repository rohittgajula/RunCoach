"""Registration gating: open · invite · closed (docs/DEPLOY.md §2.2)."""

from django.conf import settings
from django.db.models import F, Q
from django.utils import timezone

from .models import InviteCode


def registration_mode() -> str:
    return settings.REGISTRATION_MODE


def consume_invite(code: str) -> bool:
    """Use one slot of `code`. True when a slot was taken, False otherwise.

    One conditional UPDATE: the row lock it takes means a concurrent second caller
    re-checks `uses < max_uses` after the first commits, so the last slot goes to
    exactly one of them. Call inside the registration transaction so a failed
    registration gives the slot back.
    """
    code = (code or "").strip().upper()
    if not code:
        return False
    return bool(
        InviteCode.objects.filter(code=code, uses__lt=F("max_uses"), revoked_at__isnull=True)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
        .update(uses=F("uses") + 1)
    )
