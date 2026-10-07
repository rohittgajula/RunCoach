"""R10 §C: weekly report cards and achievements."""

from django.db import models

from apps.athletes.models import OwnedByAthlete


class WeeklyReport(OwnedByAthlete):
    """Last week's report card (Monday–Sunday), built once — Monday 06:00 local or on
    first read. `payload` is the deterministic report; the AI paragraph is optional."""

    week_start = models.DateField()
    payload = models.JSONField(default=dict)
    ai_markdown = models.TextField(blank=True, default="")
    ai_generated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-week_start"]
        constraints = [models.UniqueConstraint(fields=["athlete", "week_start"],
                                               name="uniq_athlete_report_week")]


class Achievement(OwnedByAthlete):
    """An earned badge or a personal-record event. Stored once, with the day it was
    reached; awarding again is a no-op."""

    class Kind(models.TextChoices):
        BADGE = "badge", "Badge"
        PR = "pr", "Personal record"

    key = models.CharField(max_length=80)
    kind = models.CharField(max_length=5, choices=Kind.choices, default=Kind.BADGE)
    label = models.CharField(max_length=120)
    earned_on = models.DateField()
    seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-earned_on", "-id"]
        constraints = [models.UniqueConstraint(fields=["athlete", "key"],
                                               name="uniq_athlete_achievement")]


class PainReport(OwnedByAthlete):
    """R13 §3 "Anything hurting?": one spot, one side, one day. Severity 1–3. Never a
    diagnosis; two days ≥ 2 on the same spot only ever makes the plan easier."""

    date = models.DateField(db_index=True)
    location = models.CharField(max_length=12)
    side = models.CharField(max_length=6)
    severity = models.PositiveSmallIntegerField()
    activity = models.ForeignKey("activities.Activity", on_delete=models.SET_NULL, null=True,
                                 blank=True, related_name="pain_reports")
    note = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
        constraints = [models.UniqueConstraint(fields=["athlete", "date", "location", "side"],
                                               name="uniq_athlete_pain_spot_day")]


class MoodLog(OwnedByAthlete):
    """R13 §10: mood and energy, 1–5 each, one per local day. Never sent to the AI
    except as averages."""

    date = models.DateField()
    mood = models.PositiveSmallIntegerField()
    energy = models.PositiveSmallIntegerField()
    note = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date"]
        constraints = [models.UniqueConstraint(fields=["athlete", "date"],
                                               name="uniq_athlete_mood_day")]


class MonthlyReport(OwnedByAthlete):
    """R13 §11: last month's report, built once (1st of the month 06:00 local or on
    first read). `payload` is deterministic; the AI paragraph is optional."""

    month = models.DateField(help_text="The 1st of the month.")
    payload = models.JSONField(default=dict)
    ai_markdown = models.TextField(blank=True, default="")
    ai_generated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-month"]
        constraints = [models.UniqueConstraint(fields=["athlete", "month"],
                                               name="uniq_athlete_report_month")]


class MorningBriefing(OwnedByAthlete):
    """R13 §6: today's "Good morning" card, stored once a day (dismissal, push sent,
    optional AI phrasing)."""

    date = models.DateField()
    payload = models.JSONField(default=dict)
    dismissed = models.BooleanField(default=False)
    ai_text = models.TextField(blank=True, default="")
    ai_generated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]
        constraints = [models.UniqueConstraint(fields=["athlete", "date"],
                                               name="uniq_athlete_briefing_day")]


class Experiment(OwnedByAthlete):
    """R14 §7: a self-experiment — one rule kept for 7–42 days, judged from the logs."""

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        STOPPED = "stopped", "Stopped"

    kind = models.CharField(max_length=20)
    title = models.CharField(max_length=80)
    start = models.DateField()
    end = models.DateField()
    rule = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    decision = models.CharField(max_length=4, blank=True, default="")      # keep | stop
    created_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-start", "-id"]


class Goal(OwnedByAthlete):
    """R14 §8: a long-term goal with progress from the athlete's own data."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ACHIEVED = "achieved", "Achieved"
        ABANDONED = "abandoned", "Abandoned"

    kind = models.CharField(max_length=16)
    title = models.CharField(max_length=80)
    unit = models.CharField(max_length=12, blank=True, default="")
    target = models.FloatField()
    target_date = models.DateField(null=True, blank=True)
    start_value = models.FloatField(null=True, blank=True)
    start_date = models.DateField()
    distance_km = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    achieved_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class GoalEntry(models.Model):
    """A value posted by hand for a custom goal."""

    goal = models.ForeignKey(Goal, on_delete=models.CASCADE, related_name="entries")
    date = models.DateField()
    value = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "id"]


class ActivityWeather(models.Model):
    """R14 §9: the weather at a run's start (Open-Meteo archive), for heat flags."""

    activity = models.OneToOneField("activities.Activity", on_delete=models.CASCADE,
                                    related_name="weather")
    temp_c = models.FloatField(null=True, blank=True)
    feels_like_c = models.FloatField(null=True, blank=True)
    dew_point_c = models.FloatField(null=True, blank=True)
    humidity = models.FloatField(null=True, blank=True)
    source = models.CharField(max_length=10, default="archive")     # archive | none
    fetched_at = models.DateTimeField(auto_now=True)


class RunHeartStats(models.Model):
    """R14 §9: one run's heart-adaptation numbers, cached (they read every record)."""

    activity = models.OneToOneField("activities.Activity", on_delete=models.CASCADE,
                                    related_name="heart_stats")
    key = models.CharField(max_length=80)       # algorithm + segmentation + reference values
    payload = models.JSONField(default=dict)
    computed_at = models.DateTimeField(auto_now=True)
