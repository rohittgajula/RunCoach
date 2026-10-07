"""Habit logs (R8 §B): cigarettes, standard drinks, sugar servings.

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

    kind = models.CharField(max_length=8, choices=Kind.choices)
    at = models.DateTimeField()
    # The athlete's own calendar day, fixed at save time (like Meal.local_date).
    local_date = models.DateField()
    quantity = models.FloatField(default=1.0)
    note = models.CharField(max_length=200, blank=True, default="")
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
