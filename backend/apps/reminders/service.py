"""Reminder settings and what each reminder says (R10 §C12)."""

from __future__ import annotations

import datetime as dt

from .models import ReminderSettings

WINDOW = dt.timedelta(hours=2)
IOS_NOTE = ("On iPhone and iPad, reminders only work after you add RunCoach to your Home "
            "Screen (Share → Add to Home Screen) and open it from there.")

# key -> (label, description)
REMINDERS = {
    "morning_checkin": ("Morning check-in", "Your readiness and today's run, every morning."),
    "habit_log": ("Habit log", "An evening nudge to log today's habits."),
    "best_run_time": ("Best time to run", "Today's best running window from the weather."),
    "weekly_report": ("Weekly report", "Mondays, when last week's report card is ready."),
    # R13
    "morning_briefing": ("Good morning", "Your morning briefing, at your wake time (from "
                         "the wake planner), else at this time."),
    # R15 §C: replaces R13's "run_reviewed" (still accepted in PATCH as an alias).
    "run_summary": ("Run summary", "After each run: distance, time, pace and heart rate. "
                    "Shows on your Garmin watch when Garmin Connect mirrors this app's "
                    "notifications."),
}
# Sent when something happens, not at a time of day: `time` is null and not settable.
EVENT_REMINDERS = {"run_summary"}
ALIASES = {"run_reviewed": "run_summary"}


def settings_for(athlete) -> ReminderSettings:
    row, _ = ReminderSettings.objects.get_or_create(athlete=athlete)
    return row


def reminders_json(row: ReminderSettings) -> list[dict]:
    return [{"key": key, "label": label, "description": description,
             "enabled": getattr(row, key),
             "time": None if key in EVENT_REMINDERS
             else getattr(row, f"{key}_time").strftime("%H:%M")}
            for key, (label, description) in REMINDERS.items()]


def _time_for(row: ReminderSettings, key: str) -> dt.time:
    if key == "morning_briefing":
        from apps.health.briefing import wake_minute

        minute = wake_minute(row.athlete)
        if minute is not None:
            return dt.time(minute // 60, minute % 60)
    return getattr(row, f"{key}_time")


def due(row: ReminderSettings, key: str, local_now: dt.datetime) -> bool:
    if key in EVENT_REMINDERS or not getattr(row, key):
        return False
    if (row.last_sent or {}).get(key) == local_now.date().isoformat():
        return False
    at = dt.datetime.combine(local_now.date(), _time_for(row, key), tzinfo=local_now.tzinfo)
    return at <= local_now < at + WINDOW


def message(athlete, key: str) -> dict | None:
    """The push for one reminder, or None when there is nothing to say today."""
    if key == "morning_checkin":
        return {"title": "Morning check-in", "body": "See how ready you are and what today's "
                "run looks like.", "url": "/", "tag": "morning_checkin"}
    if key == "habit_log":
        return {"title": "Evening log", "body": "Anything to log for today? It takes a second.",
                "url": "/", "tag": "habit_log"}
    if key == "best_run_time":
        from apps.ingest.weather_services import weather_today

        body = weather_today(athlete, include_run=False)
        window = body.get("best_window") if body.get("available") else None
        if not window or not window.get("start"):
            return None
        start = window["start"][11:16]
        end = (window.get("end") or "")[11:16]
        when = f"{start}–{end}" if end else start
        if window["start"][:10] != athlete.local_today.isoformat():
            return None
        return {"title": "Best time to run today", "body": f"Coolest window: {when}.",
                "url": "/", "tag": "best_run_time"}
    if key == "morning_briefing":
        from apps.health.briefing import build

        build(athlete)
        return {"title": "Good morning", "body": "Your morning briefing is ready.",
                "url": "/", "tag": "briefing"}
    if key == "weekly_report":
        if athlete.local_now.weekday() != 0:
            return None
        from apps.health.reports import get_or_build, last_complete_week

        get_or_build(athlete, last_complete_week(athlete))
        return {"title": "Your weekly report", "body": "Last week's report card is ready.",
                "url": "/health", "tag": "weekly_report"}
    return None
