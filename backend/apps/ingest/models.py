"""Raw activity files, kept permanently.

Two reasons this is non-negotiable, both learned rather than assumed:

1. Garmin has no personal API. The unofficial sync can break at any time, and manual
   export becomes the fallback — but only for activities you still hold.
2. The segmentation algorithm *will* change. When it does, every past activity needs
   reprocessing from source. A lossy summary cannot be re-derived; the original bytes can.
"""

import hashlib

from django.db import models

from apps.athletes.models import OwnedByAthlete


def fit_upload_path(instance, filename: str) -> str:
    return f"fit/athlete_{instance.athlete_id}/{filename}"


class RawFitFile(OwnedByAthlete):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PARSED = "parsed", "Parsed"
        FAILED = "failed", "Failed"

    file = models.FileField(upload_to=fit_upload_path)
    original_name = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64, db_index=True)
    size_bytes = models.PositiveIntegerField()

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    error = models.TextField(blank=True)

    uploaded_at = models.DateTimeField(auto_now_add=True)
    parsed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-uploaded_at"]
        constraints = [
            # One of the two independent idempotency layers. The other is the Garmin
            # activity id on Activity. Two layers means re-syncing is safe even if
            # Garmin renumbers something, or the same run arrives by manual upload.
            models.UniqueConstraint(
                fields=["athlete", "sha256"], name="uniq_athlete_fit_hash"
            )
        ]

    def __str__(self):
        return f"{self.original_name} ({self.status})"

    @staticmethod
    def hash_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()


class DailyMetrics(OwnedByAthlete):
    """One day of Garmin wellness data.

    Every field is nullable. Garmin's unofficial endpoints return different shapes by
    device, subscription tier, and whether the watch was worn overnight — a partial
    row is far more useful than no row, and a missing metric must stay distinguishable
    from a measured zero.
    """

    metric_date = models.DateField(db_index=True)

    # Sleep. Garmin dates a night by the MORNING IT ENDS, so this row's sleep is the
    # sleep *before* that day's session. Written notes are the opposite — they come
    # from the evening before. Getting this backwards misattributes both.
    sleep_seconds = models.IntegerField(null=True, blank=True)
    sleep_need_seconds = models.IntegerField(null=True, blank=True)
    sleep_score = models.IntegerField(null=True, blank=True)
    deep_sleep_seconds = models.IntegerField(null=True, blank=True)
    light_sleep_seconds = models.IntegerField(null=True, blank=True)
    rem_sleep_seconds = models.IntegerField(null=True, blank=True)
    awake_seconds = models.IntegerField(null=True, blank=True)
    sleep_start_local = models.DateTimeField(null=True, blank=True)
    sleep_end_local = models.DateTimeField(null=True, blank=True)

    # Recovery and load
    hrv_overnight_avg = models.IntegerField(null=True, blank=True)
    hrv_status = models.CharField(max_length=24, blank=True)
    hrv_weekly_avg = models.IntegerField(null=True, blank=True)
    hrv_baseline_low = models.IntegerField(null=True, blank=True)
    hrv_baseline_high = models.IntegerField(null=True, blank=True)
    training_readiness = models.IntegerField(null=True, blank=True)
    training_readiness_level = models.CharField(max_length=32, blank=True)
    training_status = models.CharField(max_length=40, blank=True)
    acute_load = models.FloatField(null=True, blank=True)
    chronic_load = models.FloatField(null=True, blank=True)

    # Daily totals
    resting_hr = models.IntegerField(null=True, blank=True)
    steps = models.IntegerField(null=True, blank=True)
    stress_avg = models.IntegerField(null=True, blank=True)
    body_battery_high = models.IntegerField(null=True, blank=True)
    body_battery_low = models.IntegerField(null=True, blank=True)
    floors_climbed = models.IntegerField(null=True, blank=True)
    intensity_minutes = models.IntegerField(null=True, blank=True)
    spo2_avg = models.IntegerField(null=True, blank=True)
    respiration_avg = models.FloatField(null=True, blank=True)
    respiration_sleep_avg = models.FloatField(null=True, blank=True)
    # Garmin's "generic" VO2max, which is the running one (cycling is separate).
    vo2max = models.FloatField(null=True, blank=True)

    # Garmin's race predictor, seconds. Fetched once per sync, stored on that day.
    race_pred_5k_s = models.IntegerField(null=True, blank=True)
    race_pred_10k_s = models.IntegerField(null=True, blank=True)
    race_pred_half_s = models.IntegerField(null=True, blank=True)
    race_pred_marathon_s = models.IntegerField(null=True, blank=True)

    # R10 §B: sleep details, fitness trend and load focus. Null when the watch or the
    # account does not provide them.
    restless_moments = models.IntegerField(null=True, blank=True)
    sleep_spo2_avg = models.FloatField(null=True, blank=True)
    sleep_spo2_low = models.FloatField(null=True, blank=True)
    endurance_score = models.IntegerField(null=True, blank=True)
    endurance_level = models.CharField(max_length=20, blank=True)
    fitness_age = models.FloatField(null=True, blank=True)
    # {feedback, items: [{key, label, value, target_min, target_max, state}]}
    load_focus = models.JSONField(null=True, blank=True)

    # Verbatim payloads, so a field nobody thought to map can be backfilled from
    # history later without re-fetching from Garmin.
    raw = models.JSONField(default=dict, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-metric_date"]
        verbose_name_plural = "daily metrics"
        constraints = [
            models.UniqueConstraint(
                fields=["athlete", "metric_date"], name="uniq_athlete_metric_date"
            )
        ]

    def __str__(self):
        return f"{self.metric_date} · sleep {self.sleep_score} · HRV {self.hrv_overnight_avg}"

    @property
    def acwr(self) -> float | None:
        """Acute:chronic workload ratio. Above ~1.5 is the classic spike warning."""
        if self.acute_load and self.chronic_load:
            return round(self.acute_load / self.chronic_load, 2)
        return None


class GarminProfile(OwnedByAthlete):
    """R10 §B: the slow-changing Garmin data, fetched at most once a day per athlete.

    The verbatim payloads are kept (like DailyMetrics.raw) so a field nobody mapped can
    be re-read later without asking Garmin again.
    """

    slow_synced_on = models.DateField(null=True, blank=True)
    backfilled_on = models.DateField(null=True, blank=True)
    user_profile_pk = models.BigIntegerField(null=True, blank=True)
    chronological_age = models.IntegerField(null=True, blank=True)
    achievable_fitness_age = models.FloatField(null=True, blank=True)
    raw = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["athlete"],
                                               name="uniq_garmin_profile_athlete")]


class PersonalRecord(OwnedByAthlete):
    """R10 §B6: Garmin's own personal records (1 km … marathon, longest run)."""

    key = models.CharField(max_length=20)
    value = models.FloatField(help_text="Seconds, or metres for longest_run.")
    achieved_on = models.DateField(null=True, blank=True)
    garmin_activity_id = models.BigIntegerField(null=True, blank=True)
    raw = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]
        constraints = [models.UniqueConstraint(fields=["athlete", "key"],
                                               name="uniq_athlete_pr_key")]


class BodyComposition(OwnedByAthlete):
    """R10 §B7: one weigh-in day from Garmin (scale or manual entry in Connect)."""

    measured_on = models.DateField(db_index=True)
    weight_kg = models.FloatField(null=True, blank=True)
    body_fat_pct = models.FloatField(null=True, blank=True)
    bmi = models.FloatField(null=True, blank=True)
    muscle_mass_kg = models.FloatField(null=True, blank=True)
    raw = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["measured_on"]
        constraints = [models.UniqueConstraint(fields=["athlete", "measured_on"],
                                               name="uniq_athlete_body_day")]


class LactateThreshold(OwnedByAthlete):
    """R10 §B3: Garmin's running lactate threshold, one row per date it changed."""

    measured_on = models.DateField(db_index=True)
    heart_rate = models.PositiveSmallIntegerField(null=True, blank=True)
    speed_mps = models.FloatField(null=True, blank=True)
    pace_s_per_km = models.PositiveSmallIntegerField(null=True, blank=True)
    raw = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["measured_on"]
        constraints = [models.UniqueConstraint(fields=["athlete", "measured_on"],
                                               name="uniq_athlete_lt_day")]


class IntradayDay(OwnedByAthlete):
    """R11 §A: one athlete-day of Garmin's intraday series, compact.

    Arrays are `[minute_of_day, value]` in the athlete's local time (steps buckets add
    Garmin's activity level as a third item). Only what the Day screen needs is kept —
    no raw payloads — so a year is a few MB. The aggregate columns feed trends and
    Compare; they are recomputed whenever the day is stored again.
    """

    day = models.DateField(db_index=True)
    utc_offset_min = models.SmallIntegerField(null=True, blank=True)
    hr = models.JSONField(default=list, blank=True)              # [[min, bpm]] every 2 min
    stress = models.JSONField(default=list, blank=True)          # [[min, 0-100]] every 3 min
    body_battery = models.JSONField(default=list, blank=True)    # [[min, 0-100]] on change
    steps = models.JSONField(default=list, blank=True)           # [[min, steps, level]] / 15 min

    # Garmin's daily summary bits the arrays cannot give (from DailyMetrics.raw["stats"]).
    step_goal = models.IntegerField(null=True, blank=True)
    resting_hr = models.IntegerField(null=True, blank=True)

    # Derived aggregates (analysis.day.aggregates).
    steps_total = models.IntegerField(null=True, blank=True)
    sedentary_min = models.IntegerField(null=True, blank=True)
    active_min = models.IntegerField(null=True, blank=True)
    intense_min = models.IntegerField(null=True, blank=True)
    stress_avg = models.IntegerField(null=True, blank=True)
    stress_high_min = models.IntegerField(null=True, blank=True)
    stressful_min = models.IntegerField(null=True, blank=True)
    awake_hr_avg = models.IntegerField(null=True, blank=True)
    bb_charged = models.IntegerField(null=True, blank=True)
    bb_drained = models.IntegerField(null=True, blank=True)
    bb_at_wake = models.IntegerField(null=True, blank=True)
    bb_at_bedtime = models.IntegerField(null=True, blank=True)

    complete = models.BooleanField(default=False, help_text="Fetched after the day ended.")
    fetched_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-day"]
        constraints = [models.UniqueConstraint(fields=["athlete", "day"],
                                               name="uniq_athlete_intraday_day")]

    def __str__(self):
        return f"{self.day} intraday ({len(self.hr)} hr, {len(self.stress)} stress)"
