"""Shoes (R10 §B8). Garmin's gear list when the athlete keeps one there, and local
shoes otherwise — runs are then auto-assigned to the default local shoe."""

from django.db import models

from apps.athletes.models import OwnedByAthlete


class Shoe(OwnedByAthlete):
    class Source(models.TextChoices):
        GARMIN = "garmin", "Garmin"
        LOCAL = "local", "Added here"

    name = models.CharField(max_length=80)
    brand = models.CharField(max_length=60, blank=True, default="")
    source = models.CharField(max_length=6, choices=Source.choices, default=Source.LOCAL)
    garmin_uuid = models.CharField(max_length=64, null=True, blank=True)
    is_default = models.BooleanField(default=False)
    retired = models.BooleanField(default=False)
    # The athlete's own replace-at distance. Null = Garmin's max distance, else 700 km.
    retire_km = models.FloatField(null=True, blank=True)
    garmin_max_km = models.FloatField(null=True, blank=True)
    start_km = models.FloatField(default=0.0, help_text="Distance already on the shoe.")
    in_use_since = models.DateField(null=True, blank=True)
    garmin_distance_m = models.FloatField(null=True, blank=True)
    garmin_activities = models.IntegerField(null=True, blank=True)
    raw = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["retired", "-is_default", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["athlete", "garmin_uuid"],
                                    condition=models.Q(garmin_uuid__isnull=False),
                                    name="uniq_athlete_garmin_shoe"),
        ]

    def __str__(self):
        return self.name


class ShoeAssignment(models.Model):
    """Which local shoe a run was done in (one shoe per activity)."""

    shoe = models.ForeignKey(Shoe, on_delete=models.CASCADE, related_name="assignments")
    activity = models.OneToOneField("activities.Activity", on_delete=models.CASCADE,
                                    related_name="shoe_assignment")
    created_at = models.DateTimeField(auto_now_add=True)
