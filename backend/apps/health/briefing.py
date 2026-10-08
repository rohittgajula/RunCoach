"""R13 §6: the daily "Good morning" briefing.

Gathered from what already exists — readiness, the morning check-in verdict, today's
session (and any auto-adjust), the weather window + hydration, the diet targets, the
injury watch and habits — with the focus and notes decided in analysis/briefing.py.
Built at the athlete's wake time by a 15-minute beat (or on first read after 04:00),
stored once a day (dismissal, the optional AI phrasing), refreshed on read.
"""

from __future__ import annotations

import datetime as dt
import json
import logging

from django.db import IntegrityError
from django.utils import timezone
from rest_framework import status as http
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis import briefing as maths
from apps.coaching.throttles import ChatThrottle

from .models import MorningBriefing

logger = logging.getLogger(__name__)

READY_HOUR = 4
LATEST_WAKE_HOUR = 11


def _minutes(clock: str | None) -> int | None:
    if not clock:
        return None
    hours, minutes = clock.split(":")
    return int(hours) * 60 + int(minutes)


def wake_minute(athlete) -> int | None:
    """Today's wake time from the wake planner, when it is a morning time."""
    from .wake_views import wake_plan

    try:
        minute = _minutes(wake_plan(athlete, athlete.local_today).get("wake_time"))
    except Exception:  # noqa: BLE001 — the planner must not break the briefing
        return None
    if minute is None or not READY_HOUR * 60 <= minute < LATEST_WAKE_HOUR * 60:
        return None
    return minute


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:  # noqa: BLE001 — one missing piece must not lose the briefing
        logger.exception("briefing part failed")
        return default


def compute(athlete) -> dict:
    from apps.activities.reviews import recent
    from apps.habits.models import HabitLog
    from apps.ingest.models import DailyMetrics
    from apps.planning.auto_adjust import current_for
    from apps.planning.checkin_services import compute as checkin
    from apps.planning.strength_service import sessions_between

    from .injury import injury_payload
    from .models import MoodLog

    today = athlete.local_today
    metrics = DailyMetrics.objects.filter(athlete=athlete, metric_date=today).first()
    verdict, workout = checkin(athlete)
    strength = next((s for s in sessions_between(athlete, today, today)
                     if s.status == "planned"), None)
    injury = _safe(lambda: injury_payload(athlete), {"risk": "low", "flags": []})
    injury_text = injury["flags"][0]["text"] if injury["flags"] else None
    sleep_h = (metrics.sleep_seconds / 3600) if metrics and metrics.sleep_seconds else None
    need_h = (metrics.sleep_need_seconds / 3600) if metrics and metrics.sleep_need_seconds \
        else None
    drinks = sum(HabitLog.objects.filter(athlete=athlete, kind="alcohol",
                                         local_date=today - dt.timedelta(days=1))
                 .values_list("quantity", flat=True)) or None
    smoke_free = None
    if athlete.smoke_goal == "quit" or athlete.smoke_quit_date:
        from apps.habits.services import smoke_streak

        smoke_free = _safe(lambda: smoke_streak(athlete)["current_days"])
    mood = MoodLog.objects.filter(athlete=athlete, date=today).first()
    adjustment = current_for(workout) if workout is not None else None
    return {
        "date": today.isoformat(), "greeting": maths.greeting(athlete.display_name),
        "readiness": {"score": metrics.training_readiness if metrics else None,
                      "label": (metrics.training_readiness_level or None) if metrics else None,
                      "source": "garmin" if metrics and metrics.training_readiness is not None
                      else None,
                      "date": today.isoformat() if metrics and metrics.training_readiness
                      is not None else None},
        "checkin": {"verdict": verdict.verdict, "headline": verdict.headline},
        "session": {
            "workout": {"id": workout.pk, "title": workout.title, "kind": workout.kind,
                        "duration_s": workout.duration_s} if workout else None,
            "adjustment": adjustment,
            "strength": {"id": strength.pk, "title": strength.title} if strength else None},
        "weather": _safe(lambda: _weather(athlete)),
        "fuel": _safe(lambda: _fuel(athlete, today)),
        "focus": maths.focus(verdict=verdict.verdict, headline=verdict.headline,
                             workout_kind=workout.kind if workout else None,
                             injury_risk=injury["risk"], injury_text=injury_text,
                             sleep_h=sleep_h, has_strength=strength is not None),
        "notes": maths.notes(injury_risk=injury["risk"], injury_text=injury_text,
                             drinks=drinks, smoke_free_days=smoke_free, sleep_h=sleep_h,
                             need_h=need_h, mood=mood.mood if mood else None,
                             reviewed=_safe(lambda: recent(athlete)) is not None),
        "injury_risk": injury["risk"],
    }


def _weather(athlete) -> dict | None:
    from apps.ingest.weather_services import weather_today

    body = weather_today(athlete)
    if not body.get("available"):
        return None
    return {"best_window": body.get("best_window"),
            "feels_like_max": (body.get("daily") or {}).get("feels_like_max"),
            "heat": body.get("heat"), "hydration": body.get("hydration")}


def _fuel(athlete, today) -> dict:
    from apps.diet.services import targets_for

    t = targets_for(athlete, today)
    return {"kcal": t.kcal, "carbs_g": t.carbs_g, "protein_g": t.protein_g,
            "water_ml": t.water_ml}


def build(athlete) -> MorningBriefing:
    """Today's row, created or refreshed."""
    payload = json.loads(json.dumps(compute(athlete), default=str))
    today = athlete.local_today
    row = MorningBriefing.objects.filter(athlete=athlete, date=today).first()
    if row is None:
        try:
            row = MorningBriefing.objects.create(athlete=athlete, date=today, payload=payload)
        except IntegrityError:
            row = MorningBriefing.objects.get(athlete=athlete, date=today)
    else:
        row.payload = payload
        row.save(update_fields=["payload"])
    return row


def ready(athlete) -> bool:
    return athlete.local_now.hour >= READY_HOUR


def briefing_json(athlete, row: MorningBriefing | None) -> dict:
    today = athlete.local_today
    wake = wake_minute(athlete)
    empty = {"date": today, "ready": False, "built_at": None, "dismissed": False,
             "wake_time": f"{wake // 60:02d}:{wake % 60:02d}" if wake is not None else None,
             "greeting": maths.greeting(athlete.display_name), "readiness": None,
             "checkin": None, "session": None, "weather": None, "fuel": None, "focus": None,
             "notes": [], "ai": {"status": "none", "text": "", "generated_at": None}}
    if row is None:
        return empty
    p = row.payload
    return {**empty, "ready": True, "built_at": row.created_at, "dismissed": row.dismissed,
            "greeting": p.get("greeting"), "readiness": p.get("readiness"),
            "checkin": p.get("checkin"), "session": p.get("session"),
            "weather": p.get("weather"), "fuel": p.get("fuel"), "focus": p.get("focus"),
            "notes": p.get("notes", []),
            "ai": ({"status": "ready", "text": row.ai_text, "generated_at": row.ai_generated_at}
                   if row.ai_text else empty["ai"])}


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def today(request):
    from .freshness import freshness_json

    athlete = request.user.athlete
    row = build(athlete) if ready(athlete) else None
    fresh = freshness_json(athlete)
    return Response({**briefing_json(athlete, row), "as_of": fresh["as_of"], "freshness": fresh})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def dismiss(request):
    athlete = request.user.athlete
    row = MorningBriefing.objects.filter(athlete=athlete, date=athlete.local_today).first()
    if row is None and ready(athlete):
        row = build(athlete)
    if row is not None and not row.dismissed:
        row.dismissed = True
        row.save(update_fields=["dismissed"])
    return Response({"dismissed": True})


BRIEFING_USER = """These are an athlete's morning facts for {date}, calculated in Python: \
readiness, the check-in verdict, today's session, the weather window, today's food and \
water targets, the one focus and the notes.

{payload}

Write one or two friendly sentences (at most 45 words) of markdown that greet the athlete \
and say what today is about, built on the focus. Use only numbers above. Never diagnose, \
never suggest training harder than the plan."""


def ai_payload(row: MorningBriefing) -> dict:
    """Aggregates only: no pain locations (injury as a level), no mood, nothing private."""
    p = row.payload
    session = p.get("session") or {}
    workout = session.get("workout") or {}
    notes = [n for n in p.get("notes", []) if n["kind"] in ("habit", "sleep")]
    return {"date": p.get("date"), "readiness": (p.get("readiness") or {}).get("score"),
            "verdict": (p.get("checkin") or {}).get("verdict"),
            "session": {"title": workout.get("title"), "kind": workout.get("kind"),
                        "minutes": round(workout["duration_s"] / 60)
                        if workout.get("duration_s") else None,
                        "adjusted": bool(session.get("adjustment")),
                        "strength": bool(session.get("strength"))},
            "weather": {"heat": (p.get("weather") or {}).get("heat"),
                        "best_window": (p.get("weather") or {}).get("best_window")},
            "fuel": p.get("fuel"), "focus": (p.get("focus") or {}).get("text"),
            "injury_watch": p.get("injury_risk", "low"),
            "notes": [n["text"] for n in notes]}


def generate_ai(athlete, refresh: bool = False) -> dict:
    from apps.coaching.models import AIAnalysis
    from apps.coaching.schemas import ShortParagraph
    from apps.coaching.services import _run

    row = build(athlete)
    if row.ai_text and not refresh:
        return {"status": "ready", "text": row.ai_text, "generated_at": row.ai_generated_at}
    payload = ai_payload(row)
    if refresh:
        from apps.coaching.client import canonical_hash, model_for
        from apps.coaching.prompts import PROMPT_VERSION

        digest = canonical_hash(payload, PROMPT_VERSION, model_for("morning_briefing"))
        AIAnalysis.objects.filter(athlete=athlete, kind=AIAnalysis.Kind.BRIEFING,
                                  input_hash=digest).delete()
    result, _ = _run(athlete, kind=AIAnalysis.Kind.BRIEFING, operation="morning_briefing",
                     payload=payload,
                     user_prompt=BRIEFING_USER.format(date=payload["date"],
                                                      payload=json.dumps(payload, indent=2)),
                     schema=ShortParagraph)
    row.ai_text = result.markdown
    row.ai_generated_at = timezone.now()
    row.save(update_fields=["ai_text", "ai_generated_at"])
    return {"status": "ready", "text": row.ai_text, "generated_at": row.ai_generated_at}


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ChatThrottle])
def briefing_ai(request):
    from apps.coaching.client import AIUnavailable

    athlete = request.user.athlete
    if not ready(athlete):
        return Response({"detail": "The briefing is ready from 04:00."},
                        status=http.HTTP_409_CONFLICT)
    try:
        return Response(generate_ai(athlete, refresh=request.query_params.get("refresh") == "1"))
    except AIUnavailable as exc:
        return Response({"detail": str(exc) or "The coach is unavailable right now."},
                        status=http.HTTP_503_SERVICE_UNAVAILABLE)


def due_now(athlete) -> bool:
    """Built by the beat once the athlete's local time passes today's wake time (the wake
    planner's, else 06:30), until 11:00."""
    now = athlete.local_now
    minute = now.hour * 60 + now.minute
    wake = wake_minute(athlete)
    start = wake if wake is not None else 6 * 60 + 30
    return start <= minute < LATEST_WAKE_HOUR * 60
