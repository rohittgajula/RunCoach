"""Habit logs (R8 §B): cigarettes, standard drinks, sugar servings; R9 §B: "Private".

Private health data. It never leaves this database except as the aggregate numbers in
`analysis.habits` (counts, averages, differences) — never as rows — and it goes with
the account on deletion.
"""

from zoneinfo import ZoneInfo

from django.db import models

from apps.athletes.models import OwnedByAthlete


class HabitLog(OwnedByAthlete):
    class Kind(models.TextChoices):
        SMOKE = "smoke", "Cigarettes"
        ALCOHOL = "alcohol", "Standard drinks"
        SUGAR = "sugar", "Sugar servings"
        PRIVATE = "private", "Private"   # R9 §B: never sent to the AI
        CAFFEINE = "caffeine", "Caffeine (cups)"   # R13 §9

    kind = models.CharField(max_length=8, choices=Kind.choices)
    at = models.DateTimeField()
    # The athlete's own calendar day, fixed at save time (like Meal.local_date).
    local_date = models.DateField()
    quantity = models.FloatField(default=1.0)
    note = models.CharField(max_length=200, blank=True, default="")
    # R13 §9: caffeine only — coffee | tea | energy | other.
    subtype = models.CharField(max_length=8, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["at", "id"]
        indexes = [models.Index(fields=["athlete", "kind", "local_date"])]

    def __str__(self):
        return f"{self.local_date} {self.kind} x{self.quantity:g}"

    def save(self, *args, **kwargs):
        try:
            zone = ZoneInfo(self.athlete.timezone or "UTC")
        except Exception:  # noqa: BLE001 — a bad zone must not lose a log
            zone = ZoneInfo("UTC")
        self.local_date = self.at.astimezone(zone).date()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"local_date"}
        super().save(*args, **kwargs)


def _local_date(athlete, at):
    try:
        zone = ZoneInfo(athlete.timezone or "UTC")
    except Exception:  # noqa: BLE001
        zone = ZoneInfo("UTC")
    return at.astimezone(zone)


class CravingLog(OwnedByAthlete):
    """R13 §8: one craving. `smoked` = gave in; a linked smoke HabitLog is the cigarette."""

    class Trigger(models.TextChoices):
        COFFEE = "coffee", "Coffee"
        ALCOHOL = "alcohol", "Alcohol"
        STRESS = "stress", "Stress"
        AFTER_MEAL = "after_meal", "After a meal"
        BOREDOM = "boredom", "Boredom"
        SOCIAL = "social", "Social"
        WORK_BREAK = "work_break", "Work break"
        MORNING = "morning", "Morning"
        OTHER = "other", "Other"

    at = models.DateTimeField()
    local_date = models.DateField()
    local_hour = models.PositiveSmallIntegerField(default=0)
    intensity = models.PositiveSmallIntegerField()
    trigger = models.CharField(max_length=10, choices=Trigger.choices)
    place = models.CharField(max_length=60, blank=True, default="")
    mood = models.PositiveSmallIntegerField(null=True, blank=True)
    smoked = models.BooleanField(default=False)
    cigarette_log = models.ForeignKey(HabitLog, on_delete=models.SET_NULL, null=True,
                                      blank=True, related_name="cravings")
    note = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at", "-id"]

    def save(self, *args, **kwargs):
        local = _local_date(self.athlete, self.at)
        self.local_date, self.local_hour = local.date(), local.hour
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"local_date", "local_hour"}
        super().save(*args, **kwargs)
