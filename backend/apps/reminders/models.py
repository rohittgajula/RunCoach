"""R10 §C12: web-push subscriptions and the athlete's reminder choices."""

import datetime as dt

from django.db import models

from apps.athletes.models import OwnedByAthlete


class PushSubscription(OwnedByAthlete):
    """One browser/device. The endpoint is a capability URL issued by the browser's
    push service; the keys encrypt the payload end to end."""

    endpoint = models.URLField(max_length=1000, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    user_agent = models.CharField(max_length=300, blank=True, default="")
    failures = models.PositiveSmallIntegerField(default=0)
    last_success_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ReminderSettings(OwnedByAthlete):
    """Per-reminder toggle and local time. All off until the athlete turns one on."""

    morning_checkin = models.BooleanField(default=False)
    morning_checkin_time = models.TimeField(default=dt.time(7, 0))
    habit_log = models.BooleanField(default=False)
    habit_log_time = models.TimeField(default=dt.time(21, 0))
    best_run_time = models.BooleanField(default=False)
    best_run_time_time = models.TimeField(default=dt.time(6, 0))
    weekly_report = models.BooleanField(default=False)
    weekly_report_time = models.TimeField(default=dt.time(7, 0))
    # R13: the "Good morning" briefing (at the wake time, else this time).
    morning_briefing = models.BooleanField(default=False)
    morning_briefing_time = models.TimeField(default=dt.time(6, 30))
    # R15 §C: the watch-sized run summary (event: when a post-run review is built; no
    # time). Replaces R13's "Run reviewed". On by default — it only reaches athletes who
    # subscribed a device to push.
    run_summary = models.BooleanField(default=True)
    # R17 §1: "Recovery routine ready" after a run (event; off by default).
    recovery_ready = models.BooleanField(default=False)
    # R11 §C: nudges driven by the intraday data (and water by the clock). All off.
    move = models.BooleanField(default=False)
    move_start = models.TimeField(default=dt.time(9, 0))
    move_end = models.TimeField(default=dt.time(19, 0))
    move_max_per_day = models.PositiveSmallIntegerField(default=4)
    move_after_min = models.PositiveSmallIntegerField(default=60)
    breathing = models.BooleanField(default=False)
    breathing_start = models.TimeField(default=dt.time(9, 0))
    breathing_end = models.TimeField(default=dt.time(21, 0))
    breathing_max_per_day = models.PositiveSmallIntegerField(default=3)
    breathing_threshold = models.PositiveSmallIntegerField(default=51)
    water = models.BooleanField(default=False)
    water_start = models.TimeField(default=dt.time(9, 0))
    water_end = models.TimeField(default=dt.time(21, 0))
    water_max_per_day = models.PositiveSmallIntegerField(default=6)
    water_every_h = models.PositiveSmallIntegerField(default=2)
    quiet_start = models.TimeField(default=dt.time(22, 0))
    quiet_end = models.TimeField(default=dt.time(7, 0))
    # {nudge key: {"date": local date, "count": n, "last_at": iso, "stretch": minute}}
    nudge_state = models.JSONField(default=dict, blank=True)

    # {reminder key: "YYYY-MM-DD" last sent, local date} — once a day each.
    last_sent = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "reminder settings"
        constraints = [models.UniqueConstraint(fields=["athlete"],
                                               name="uniq_reminder_settings_athlete")]


def all_days() -> list[int]:
    return [0, 1, 2, 3, 4, 5, 6]


class Alarm(OwnedByAthlete):
    """R12 §B: "My alarm" and the wake planner's inputs. Not a phone alarm — a web app
    cannot set one — but it can push a notification at that time."""

    time = models.TimeField(null=True, blank=True)
    days = models.JSONField(default=all_days)
    enabled = models.BooleanField(default=False)
    push = models.BooleanField(default=False)
    run_time = models.TimeField(null=True, blank=True)
    bedtime_reminder = models.BooleanField(default=False)
    bedtime_lead_min = models.PositiveSmallIntegerField(default=30)
    # {"alarm": "YYYY-MM-DD", "bedtime": "YYYY-MM-DD"} — once a local day each.
    last_sent = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["athlete"], name="uniq_alarm_athlete")]
