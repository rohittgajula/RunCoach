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
