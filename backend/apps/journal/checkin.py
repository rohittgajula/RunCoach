"""R7 §2: the post-run check-in. Structured, ~10 seconds, no model call.

A check-in is a JournalEntry(source=run_log) tied to the activity, with the RPE and a
pain flag written straight onto the columns readiness and compliance read. The free
note, when there is one, is read by the existing extractor later, on the `ai` queue;
it can only ADD a pain/illness flag, never clear the structured one.
"""

from __future__ import annotations

import datetime as dt

from django.db import transaction

from apps.activities.models import Activity

from .models import JournalEntry

LEGS = ("fresh", "ok", "heavy", "sore")
BREATHING = ("easy", "ok", "hard")
PENDING_DAYS = 7
MAX_NOTE = 2000


class CheckinInvalid(ValueError):
    pass


def _int_in(value, low, high, name):
    if isinstance(value, bool):
        raise CheckinInvalid(f"{name} must be a whole number {low}–{high}.")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise CheckinInvalid(f"{name} must be a whole number {low}–{high}.") from None
    if number != value and str(number) != str(value):
        raise CheckinInvalid(f"{name} must be a whole number {low}–{high}.")
    if not low <= number <= high:
        raise CheckinInvalid(f"{name} must be {low}–{high}.")
    return number


def validate(data: dict) -> dict:
    """The structured fields, cleaned. Raises CheckinInvalid with a readable message."""
    rpe = _int_in(data.get("rpe"), 1, 10, "rpe")
    legs = data.get("legs")
    if legs is not None and legs not in LEGS:
        raise CheckinInvalid(f"legs must be one of {', '.join(LEGS)}.")
    breathing = data.get("breathing")
    if breathing is not None and breathing not in BREATHING:
        raise CheckinInvalid(f"breathing must be one of {', '.join(BREATHING)}.")
    pain = data.get("pain")
    if pain is not None:
        if not isinstance(pain, dict):
            raise CheckinInvalid("pain must be {where, level} or null.")
        where = str(pain.get("where") or "").strip()[:40]
        if not where:
            raise CheckinInvalid("pain.where is required.")
        pain = {"where": where, "level": _int_in(pain.get("level"), 1, 10, "pain.level")}
    note = str(data.get("note") or "").strip()
    if len(note) > MAX_NOTE:
        raise CheckinInvalid(f"note must be under {MAX_NOTE} characters.")
    return {"rpe": rpe, "legs": legs, "breathing": breathing, "pain": pain, "note": note}


def _summary_text(fields: dict) -> str:
    parts = [f"RPE {fields['rpe']}/10"]
    if fields["legs"]:
        parts.append(f"legs {fields['legs']}")
    if fields["breathing"]:
        parts.append(f"breathing {fields['breathing']}")
    if fields["pain"]:
        parts.append(f"pain: {fields['pain']['where']} {fields['pain']['level']}/10")
    text = "Post-run check-in: " + " · ".join(parts)
    return f"{text}\n\n{fields['note']}" if fields["note"] else text


def existing(activity: Activity) -> JournalEntry | None:
    return (JournalEntry.objects.filter(athlete_id=activity.athlete_id, activity=activity,
                                        source=JournalEntry.Source.RUN_LOG)
            .order_by("-created_at").first())


def record(athlete, activity: Activity, fields: dict) -> tuple[JournalEntry, bool]:
    """Create (or replace) the activity's check-in. Returns (entry, created)."""
    with transaction.atomic():
        entry = existing(activity)
        created = entry is None
        if created:
            entry = JournalEntry(athlete=athlete, activity=activity,
                                 source=JournalEntry.Source.RUN_LOG)
        entry.text = _summary_text(fields)
        entry.written_on = athlete.local_today
        entry.applies_to_date = activity.local_date
        entry.rpe = fields["rpe"]
        entry.pain_reported = bool(fields["pain"])
        entry.illness_reported = False
        entry.extraction_failed = False
        entry.extracted = {"checkin": True, "skipped": False, **fields}
        entry.save()
    if fields["note"]:
        transaction.on_commit(lambda: _queue_note(entry.pk))
    transaction.on_commit(lambda: _queue_after_checkin(activity.pk))
    return entry, created


def _queue_after_checkin(activity_id: int) -> None:
    """R13: the RPE can only make the plan easier (auto-adjust) and refreshes the review."""
    try:
        from apps.planning.tasks import after_checkin_task

        after_checkin_task.delay(activity_id)
    except Exception:  # noqa: BLE001 — no broker in a one-off script
        pass


def _queue_note(entry_id: int) -> None:
    try:
        from apps.coaching.tasks import extract_checkin_note

        extract_checkin_note.delay(entry_id)
    except Exception:  # noqa: BLE001 — no broker in a one-off script
        pass


def skip(athlete, activity: Activity, reason: str) -> tuple[JournalEntry, bool]:
    """Mark the activity as checked in without answers, so it stops being pending."""
    entry = existing(activity)
    if entry is not None:
        return entry, False
    reason = (reason or "").strip()[:300]
    entry = JournalEntry.objects.create(
        athlete=athlete, activity=activity, source=JournalEntry.Source.RUN_LOG,
        text=f"Check-in skipped: {reason}" if reason else "Check-in skipped",
        written_on=athlete.local_today, applies_to_date=activity.local_date,
        extracted={"checkin": False, "skipped": True, "reason": reason},
    )
    return entry, True


def is_checkin_sport(sport: str | None) -> bool:
    sport = (sport or "").lower()
    return "run" in sport or "walk" in sport


def pending(athlete) -> list[Activity]:
    """Runs and walks of the last 7 days that nothing in the journal covers yet.

    Same rule as ActivityCard.journalled: an entry tied to the activity, or an entry
    for that date that is not tied to any activity (a chat note about the day). A
    check-in for one run does not cover a second run the same day.
    """
    since = athlete.local_today - dt.timedelta(days=PENDING_DAYS - 1)
    activities = [a for a in Activity.objects.filter(athlete=athlete, local_date__gte=since)
                  .select_related("metrics").prefetch_related("segments")
                  .order_by("-started_at") if is_checkin_sport(a.sport)]
    if not activities:
        return []
    ids = {a.pk for a in activities}
    dates = {a.local_date for a in activities}
    covered_ids = set(JournalEntry.objects.filter(athlete=athlete, activity_id__in=ids)
                      .values_list("activity_id", flat=True))
    covered_dates = set(JournalEntry.objects.filter(athlete=athlete, applies_to_date__in=dates,
                                                    activity__isnull=True)
                        .values_list("applies_to_date", flat=True))
    return [a for a in activities
            if a.pk not in covered_ids and a.local_date not in covered_dates]
