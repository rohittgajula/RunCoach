"""Users and invite codes for the admin page (R14 §14)."""

from __future__ import annotations

import datetime as dt

from django.contrib.auth.models import User
from django.db.models import Count, Max, Q, Sum
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from apps.athletes.models import InviteCode


def month_start() -> dt.datetime:
    now = timezone.now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _ai_month() -> dict[int, dict]:
    from apps.coaching.models import AIRequestLog

    rows = (AIRequestLog.objects.filter(created_at__gte=month_start(), athlete__isnull=False)
            .values("athlete_id")
            .annotate(calls=Count("id", filter=Q(status__in=["ok", "invalid"])),
                      cost=Sum("estimated_cost_usd")))
    return {r["athlete_id"]: r for r in rows}


def _last_active(user_ids) -> dict[int, dt.datetime]:
    """Newest of last login and the newest refresh-token rotation (every 15-minute
    access refresh issues one), so an app left signed in still counts as active."""
    from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

    rows = (OutstandingToken.objects.filter(user_id__in=list(user_ids))
            .values("user_id").annotate(last=Max("created_at")))
    return {r["user_id"]: r["last"] for r in rows}


def user_json(user: User, ai: dict | None = None, last_token: dt.datetime | None = None) -> dict:
    from apps.coaching.services import MONTHLY_CALL_BUDGET
    from apps.planning.models import TrainingPlan

    athlete = getattr(user, "athlete", None)
    if ai is None:
        ai = _ai_month().get(getattr(athlete, "pk", None), {}) if athlete else {}
    if last_token is None:
        last_token = _last_active([user.pk]).get(user.pk)
    plan = None
    if athlete is not None:
        row = (TrainingPlan.objects.filter(athlete=athlete, status="active")
               .select_related("race").first())
        if row is not None:
            plan = {"id": row.pk, "name": row.name,
                    "race_date": row.race.date if row.race else None}
    custom = athlete.ai_call_budget if athlete is not None else None
    candidates = [d for d in (user.last_login, last_token) if d]
    return {
        "id": user.pk, "username": user.username,
        "display_name": athlete.display_name if athlete else user.username,
        "email": user.email, "joined": user.date_joined,
        "last_active": max(candidates) if candidates else None,
        "is_active": user.is_active, "is_staff": user.is_staff,
        "garmin_connected": bool(athlete and athlete.garmin_connected),
        "garmin_last_sync": athlete.garmin_last_sync if athlete else None,
        "plan": plan,
        "ai": {"calls_month": int(ai.get("calls") or 0),
               "cost_month_usd": round(float(ai.get("cost") or 0.0), 4),
               "budget": MONTHLY_CALL_BUDGET if custom is None else custom,
               "budget_source": "default" if custom is None else "custom"},
    }


@api_view(["GET"])
@permission_classes([IsAdminUser])
def users(request):
    from apps.athletes.invites import registration_mode
    from apps.coaching.services import MONTHLY_CALL_BUDGET

    rows = list(User.objects.select_related("athlete").order_by("-date_joined", "-id"))
    ai = _ai_month()
    last = _last_active(u.pk for u in rows)
    out = []
    for user in rows:
        athlete = getattr(user, "athlete", None)
        out.append(user_json(user, ai.get(athlete.pk, {}) if athlete else {},
                             last.get(user.pk)))
    return Response({"registration_mode": registration_mode(),
                     "default_budget": MONTHLY_CALL_BUDGET, "users": out})


@api_view(["PATCH"])
@permission_classes([IsAdminUser])
def user_detail(request, pk: int):
    user = User.objects.select_related("athlete").filter(pk=pk).first()
    if user is None:
        return Response({"detail": "Not found."}, status=404)
    data = request.data
    if "is_active" in data:
        value = data["is_active"]
        if not isinstance(value, bool):
            return Response({"detail": "is_active must be true or false."}, status=400)
        if user.pk == request.user.pk and not value:
            return Response({"detail": "You can't disable your own account."}, status=400)
    if "ai_budget" in data:
        budget = data["ai_budget"]
        if budget is not None and (not isinstance(budget, int) or isinstance(budget, bool)
                                   or not 0 <= budget <= 100000):
            return Response({"detail": "ai_budget must be a whole number 0–100000 or null."},
                            status=400)
        athlete = getattr(user, "athlete", None)
        if athlete is None:
            return Response({"detail": "This user has no athlete profile."}, status=400)
        athlete.ai_call_budget = budget
        athlete.save(update_fields=["ai_call_budget", "updated_at"])
    if "is_active" in data and data["is_active"] != user.is_active:
        user.is_active = data["is_active"]
        user.save(update_fields=["is_active"])
        if not user.is_active:
            from apps.athletes.deletion import revoke_refresh_tokens

            revoke_refresh_tokens(user)
    return Response(user_json(user))


# --- invites ---------------------------------------------------------------------------

def invite_json(invite: InviteCode) -> dict:
    return {"id": invite.pk, "code": invite.code, "note": invite.note,
            "max_uses": invite.max_uses, "uses": invite.uses, "expires_at": invite.expires_at,
            "created_at": invite.created_at, "usable": invite.is_usable, "revoked": invite.revoked_at is not None}


@api_view(["GET", "POST"])
@permission_classes([IsAdminUser])
def invites(request):
    if request.method == "GET":
        return Response([invite_json(i) for i in InviteCode.objects.all()[:200]])
    data = request.data
    note = data.get("note") or ""
    if not isinstance(note, str) or len(note) > 200:
        return Response({"detail": "note must be text of at most 200 characters."}, status=400)
    max_uses = data.get("max_uses", 1)
    if not isinstance(max_uses, int) or isinstance(max_uses, bool) or not 1 <= max_uses <= 100:
        return Response({"detail": "max_uses must be 1–100."}, status=400)
    days = data.get("expires_in_days")
    if days is not None and (not isinstance(days, int) or isinstance(days, bool)
                             or not 1 <= days <= 365):
        return Response({"detail": "expires_in_days must be 1–365 or null."}, status=400)
    invite = InviteCode.objects.create(
        note=note.strip(), max_uses=max_uses,
        expires_at=timezone.now() + dt.timedelta(days=days) if days else None)
    return Response(invite_json(invite), status=201)


@api_view(["POST"])
@permission_classes([IsAdminUser])
def invite_revoke(request, pk: int):
    invite = InviteCode.objects.filter(pk=pk).first()
    if invite is None:
        return Response({"detail": "Not found."}, status=404)
    if invite.revoked_at is None:
        invite.revoked_at = timezone.now()
        invite.save(update_fields=["revoked_at"])
    return Response(invite_json(invite))
