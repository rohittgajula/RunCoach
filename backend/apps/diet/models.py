"""What the athlete ate.

The one place the model produces numbers: estimating a plate from a photo or a
sentence. Those numbers are always shown as an editable estimate, stored with where
they came from (`source`) and how sure the model was (`ai_confidence`), and the totals
are recomputed from the items on every save — so an edited item can never leave a
stale total behind.
"""

import uuid

from django.db import models

from apps.athletes.models import OwnedByAthlete

MACROS = ("kcal", "carbs_g", "protein_g", "fat_g")


def meal_photo_path(instance, filename: str) -> str:
    # Random, not the original filename: these are served without auth in development
    # and a guessable path would be a list of everyone's lunches.
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "jpg").lower()[:5]
    return f"meals/{instance.athlete_id}/{uuid.uuid4().hex}.{ext}"


class Meal(OwnedByAthlete):
    class MealType(models.TextChoices):
        BREAKFAST = "breakfast", "Breakfast"
        LUNCH = "lunch", "Lunch"
        DINNER = "dinner", "Dinner"
        SNACK = "snack", "Snack"

    class Source(models.TextChoices):
        AI_PHOTO = "ai_photo", "AI estimate from photo"
        AI_TEXT = "ai_text", "AI estimate from text"
        MANUAL = "manual", "Manual"

    class Confidence(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    eaten_at = models.DateTimeField()
    # Denormalised in the athlete's timezone at save time, like Activity.local_date.
    # Never timezone.localdate(): at 00:48 in Kolkata that is still yesterday.
    local_date = models.DateField(db_index=True)
    meal_type = models.CharField(max_length=10, choices=MealType.choices)
    description = models.CharField(max_length=300, blank=True)
    photo = models.ImageField(upload_to=meal_photo_path, null=True, blank=True)
    items = models.JSONField(default=list, blank=True)

    kcal = models.FloatField(default=0)
    carbs_g = models.FloatField(default=0)
    protein_g = models.FloatField(default=0)
    fat_g = models.FloatField(default=0)

    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    ai_confidence = models.CharField(
        max_length=6, choices=Confidence.choices, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["eaten_at", "id"]

    def __str__(self):
        return f"{self.local_date} {self.meal_type}: {self.description[:40]}"

    def recompute_totals(self) -> None:
        for key in MACROS:
            total = sum(float(item.get(key) or 0) for item in (self.items or []))
            setattr(self, key, round(total, 1))

    def save(self, *args, **kwargs):
        self.recompute_totals()
        if self.eaten_at is not None:
            from zoneinfo import ZoneInfo

            try:
                zone = ZoneInfo(self.athlete.timezone or "UTC")
            except Exception:  # noqa: BLE001 — a bad zone must not lose a meal
                zone = ZoneInfo("UTC")
            self.local_date = self.eaten_at.astimezone(zone).date()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | set(MACROS) | {"local_date"}
        super().save(*args, **kwargs)


class WaterLog(OwnedByAthlete):
    """R11 §D: one drink of water. `local_date` is fixed at save time in the athlete's
    timezone (like Meal.local_date)."""

    at = models.DateTimeField()
    local_date = models.DateField(db_index=True)
    ml = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["at", "id"]
        indexes = [models.Index(fields=["athlete", "local_date"])]

    def __str__(self):
        return f"{self.local_date} {self.ml} ml"
