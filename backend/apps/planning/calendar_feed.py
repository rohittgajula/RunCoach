"""Calendar sync (R14 §5): a private ICS subscription URL.

`/api/cal/<token>.ics` needs no sign-in — calendar apps can't send one — so the token is
the credential: 43 random URL-safe characters (256 bits), regenerated or revoked from
Me → Calendar sync. The feed carries workout titles, durations and steps, strength
sessions and races — no health data (no HR history, weight, sleep, habits, notes).

UIDs are stable per item; SEQUENCE / LAST-MODIFIED move only when an item's date,
title or steps change (CalendarFeedItem remembers the last served content hash).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
from urllib.parse import quote

from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponse, HttpResponseNotModified
from django.utils import timezone
from django.utils.http import http_date, parse_http_date_safe
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from planning import ics

from .models import CalendarFeed, CalendarFeedItem, PlannedWorkout, Race, StrengthSession, TrainingPlan

PAST_DAYS = 30
FUTURE_DAYS = 180
KIND_EMOJI = {"RACE": "🏁", "WALK": "🚶", "REST": "😌"}
KIND_WORD = {"EASY": "Easy run", "LONG": "Long run", "TEMPO": "Tempo run",
             "INTERVALS": "Intervals", "RUN_WALK": "Run/walk", "WALK": "Walk",
             "REST": "Rest", "RACE": "Race"}


def new_token() -> str:
    return secrets.token_urlsafe(32)


def feed_json(request, feed: CalendarFeed | None) -> dict:
    if feed is None:
        return {"enabled": False, "url": None, "webcal_url": None, "google_url": None,
                "path": None, "created_at": None, "last_fetched_at": None}
    path = f"/api/cal/{feed.token}.ics"
    url = request.build_absolute_uri(path)
    webcal = "webcal://" + url.split("://", 1)[1]
    return {"enabled": True, "url": url, "webcal_url": webcal,
            "google_url": "https://calendar.google.com/calendar/r?cid=" + quote(webcal, safe=""),
            "path": path, "created_at": feed.created_at, "last_fetched_at": feed.last_fetched_at}


@api_view(["GET", "POST", "DELETE"])
@permission_classes([IsAuthenticated])
def feed_view(request):
    athlete = request.user.athlete
    feed = CalendarFeed.objects.filter(athlete=athlete).first()
    if request.method == "GET":
        return Response(feed_json(request, feed))
    if request.method == "DELETE":
        CalendarFeed.objects.filter(athlete=athlete).delete()
        CalendarFeedItem.objects.filter(athlete=athlete).delete()
        return Response(status=204)
    with transaction.atomic():
        if feed is None:
            try:
                feed = CalendarFeed.objects.create(athlete=athlete, token=new_token())
            except IntegrityError:
                feed = CalendarFeed.objects.get(athlete=athlete)
        else:
            feed.token = new_token()
            feed.created_at = timezone.now()
            feed.last_fetched_at = None
            feed.save(update_fields=["token", "created_at", "last_fetched_at"])
    return Response(feed_json(request, feed), status=201)


# --- the feed ---------------------------------------------------------------------------

def _workout_event(w: PlannedWorkout) -> ics.Event:
    word = KIND_WORD.get(w.kind, w.kind.title())
    emoji = KIND_EMOJI.get(w.kind, "🏃")
    title = w.title or word
    summary = f"{emoji} {title}"
    if w.kind not in ("REST",) and w.duration_s:
        summary += f" · {ics.minutes(w.duration_s)}"
    if w.status == PlannedWorkout.Status.COMPLETED:
        summary += " ✓"
    parts = []
    steps = ics.steps_text(w.steps)
    if steps:
        parts.append(steps)
    if w.purpose:
        parts.append(w.purpose.strip())
    parts.append("From RunCoach — your plan changes here automatically.")
    return ics.Event(uid=f"workout-{w.pk}@runcoach", summary=summary,
                     description="\n\n".join(parts), day=w.date)


def _strength_event(s: StrengthSession) -> ics.Event:
    lines = []
    for e in s.exercises or []:
        dose = f"{e.get('reps')} reps" if e.get("reps") else f"{e.get('seconds')} s"
        side = " each side" if e.get("per_side") else ""
        lines.append(f"{e.get('name', 'Exercise')}: {e.get('sets', 1)} × {dose}{side}")
    summary = f"💪 {s.title} · {ics.minutes(s.duration_s)}"
    if s.status == StrengthSession.Status.COMPLETED:
        summary += " ✓"
    lines.append("From RunCoach.")
    return ics.Event(uid=f"strength-{s.pk}@runcoach", summary=summary,
                     description="\n".join(lines), day=s.date)


def _race_event(r: Race, zone) -> ics.Event:
    summary = f"🏁 {r.name} · {r.distance_km:g} km"
    description = f"Race: {r.distance_km:g} km.\nFrom RunCoach."
    if r.start_time is not None:
        start = dt.datetime.combine(r.date, r.start_time, tzinfo=zone)
        expected = (r.goal_time_s or int(r.distance_km * 420)) + 1800
        return ics.Event(uid=f"race-{r.pk}@runcoach", summary=summary, description=description,
                         start_utc=start.astimezone(dt.timezone.utc), duration_s=expected)
    return ics.Event(uid=f"race-{r.pk}@runcoach", summary=summary, description=description,
                     day=r.date)


def events_for(athlete) -> list[ics.Event]:
    from apps.health.common import zone_of

    today = athlete.local_today
    start, end = today - dt.timedelta(days=PAST_DAYS), today + dt.timedelta(days=FUTURE_DAYS)
    out = []
    plan = TrainingPlan.objects.filter(athlete=athlete, status=TrainingPlan.Status.ACTIVE).first()
    if plan is not None:
        for w in plan.workouts.filter(date__gte=start, date__lte=end) \
                .exclude(status=PlannedWorkout.Status.SKIPPED).exclude(kind="RACE"):
            out.append(_workout_event(w))
    for s in StrengthSession.objects.filter(athlete=athlete, date__gte=start, date__lte=end) \
            .exclude(status=StrengthSession.Status.SKIPPED):
        out.append(_strength_event(s))
    zone = zone_of(athlete)
    for r in Race.objects.filter(athlete=athlete, date__gte=start, date__lte=end):
        out.append(_race_event(r, zone))
    return sorted(out, key=lambda e: (e.day or e.start_utc.date(), e.uid))


def _versions(athlete, events: list[ics.Event]) -> list[tuple[ics.Event, int, dt.datetime]]:
    """(event, SEQUENCE, LAST-MODIFIED). New UID → 0; changed content → +1."""
    now = timezone.now().replace(microsecond=0)
    known = {i.uid: i for i in CalendarFeedItem.objects.filter(athlete=athlete)}
    out = []
    for event in events:
        digest = event.content_hash()
        item = known.get(event.uid)
        if item is None:
            item = CalendarFeedItem(athlete=athlete, uid=event.uid, content_hash=digest,
                                    sequence=0, updated_at=now)
            try:
                with transaction.atomic():
                    item.save()
            except IntegrityError:          # a concurrent fetch got there first
                item = CalendarFeedItem.objects.get(athlete=athlete, uid=event.uid)
        elif item.content_hash != digest:
            item.content_hash, item.sequence, item.updated_at = digest, item.sequence + 1, now
            item.save(update_fields=["content_hash", "sequence", "updated_at"])
        out.append((event, item.sequence, item.updated_at))
    return out


def feed_ics(request, token: str):
    feed = CalendarFeed.objects.filter(token=token).select_related("athlete").first()
    if feed is None or not token:
        raise Http404
    athlete = feed.athlete
    rows = _versions(athlete, events_for(athlete))
    modified = max((m for _, _, m in rows), default=feed.created_at).replace(microsecond=0)
    # The ETag covers the content and its versions, not the generation time (DTSTAMP).
    tag_src = "|".join(f"{e.uid}:{seq}:{e.content_hash()}" for e, seq, _ in rows)
    etag = '"' + hashlib.sha256(tag_src.encode()).hexdigest()[:32] + '"'
    CalendarFeed.objects.filter(pk=feed.pk).update(last_fetched_at=timezone.now())

    match = request.headers.get("If-None-Match")
    since = parse_http_date_safe(request.headers.get("If-Modified-Since") or "")
    not_modified = (etag in [t.strip() for t in match.split(",")] if match
                    else since is not None and int(modified.timestamp()) <= since)
    if not_modified:
        response = HttpResponseNotModified()
    else:
        body = ics.calendar(rows, name="RunCoach", stamp=modified)
        response = HttpResponse(body, content_type="text/calendar; charset=utf-8")
        response["Content-Disposition"] = 'inline; filename="runcoach.ics"'
    response["ETag"] = etag
    response["Last-Modified"] = http_date(modified.timestamp())
    response["Cache-Control"] = "private, max-age=900"
    response["X-Robots-Tag"] = "noindex"
    return response
