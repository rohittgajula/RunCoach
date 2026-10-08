"""The tenancy root and everything hanging off it.

`Athlete` is the tenant. Every piece of data in this system belongs to exactly one,
from the first model onwards — retrofitting multi-tenancy is a bad week, and on a
publicly hosted app a missed filter is a breach rather than a bug.
"""

from django.contrib.auth.models import User
from django.db import models


def default_available_days() -> dict:
    """Which weekdays this athlete can train. Keys are "0" (Monday) .. "6" (Sunday).

    Availability only — deliberately NOT what each day is for. The plan generator
    decides that from the phase, the runway and last week's data. If the profile also
    declared "Tuesday is intervals" the two would disagree and one would silently win.

    Monday rest by default: new runners are injured by frequency far more often than
    by distance.
    """
    return {"0": False, "1": True, "2": False, "3": True,
            "4": False, "5": True, "6": True}


class Athlete(models.Model):
    """Tenancy root. Every piece of data in the system hangs off an Athlete."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="athlete")
    display_name = models.CharField(max_length=120)
    timezone = models.CharField(max_length=64, default="UTC")

    date_of_birth = models.DateField(null=True, blank=True)
    weight_kg = models.FloatField(
        null=True, blank=True, help_text="Scales hydration and fuelling figures later."
    )
    resting_hr = models.PositiveSmallIntegerField(null=True, blank=True)
    max_hr = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Observed max, not a 220-age formula estimate."
    )

    # Standing defaults, in seconds per km. NOT what today's session prescribes:
    # anything describing today reads from the session object, which is what these
    # became after the plan, the day type and the readiness adjustment. Reading the
    # profile instead skips all three.
    easy_pace_min = models.PositiveSmallIntegerField(
        default=600, help_text="Fast edge of the easy band, sec/km. 600 = 10:00/km."
    )
    easy_pace_max = models.PositiveSmallIntegerField(
        default=645, help_text="Slow edge of the easy band, sec/km. 645 = 10:45/km."
    )
    hr_easy_min = models.PositiveSmallIntegerField(default=130)
    hr_easy_max = models.PositiveSmallIntegerField(default=145)
    hr_ceiling = models.PositiveSmallIntegerField(
        default=155, help_text="Cross this during a run block and the athlete should walk."
    )

    run_cadence_threshold = models.PositiveSmallIntegerField(
        default=140, help_text="Cadence at or above this counts as running, not walking."
    )

    # --- Body and diet (RunCoach). Used by nutrition/targets.py; every one is
    # optional, and what is missing is reported to the UI rather than guessed.
    class Sex(models.TextChoices):
        MALE = "male", "Male"
        FEMALE = "female", "Female"

    class DietGoal(models.TextChoices):
        MAINTAIN = "maintain", "Maintain"
        LOSE = "lose", "Lose"
        GAIN = "gain", "Gain"

    sex = models.CharField(max_length=6, choices=Sex.choices, null=True, blank=True)
    height_cm = models.FloatField(null=True, blank=True)
    diet_goal = models.CharField(
        max_length=8, choices=DietGoal.choices, default=DietGoal.MAINTAIN
    )
    diet_rate_kg_per_week = models.FloatField(
        default=0.25, help_text="Clamped to 0-0.75. Faster loss costs training quality."
    )
    # Mirrored from the latest MetricEntry(kind=threshold_pace) so the profile card
    # does not need a query per metric. MetricEntry is the source of truth.
    threshold_pace_s = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Threshold pace, sec/km."
    )

    available_days = models.JSONField(default=default_available_days)
    long_run_day = models.PositiveSmallIntegerField(
        default=6, help_text="0 = Monday. The one day with time for a long session."
    )

    # R8 §A: how many days a week to run (2-6). None = the coach default
    # (planning.generator.run_day_limit). Same weekly volume, split differently.
    runs_per_week = models.PositiveSmallIntegerField(null=True, blank=True)

    # R8 §B: habits. Logged in apps.habits; these are the goals and the quit maths.
    class SmokeGoal(models.TextChoices):
        QUIT = "quit", "Quit"
        REDUCE = "reduce", "Reduce"
        NONE = "none", "None"

    class ReduceGoal(models.TextChoices):
        REDUCE = "reduce", "Reduce"
        NONE = "none", "None"

    smoke_goal = models.CharField(max_length=6, choices=SmokeGoal.choices,
                                  default=SmokeGoal.NONE)
    smoke_quit_date = models.DateField(null=True, blank=True)
    smoke_baseline_per_day = models.FloatField(null=True, blank=True)
    cigarette_price = models.FloatField(null=True, blank=True, help_text="Rupees per cigarette.")
    alcohol_goal = models.CharField(max_length=6, choices=ReduceGoal.choices,
                                    default=ReduceGoal.NONE)
    sugar_goal = models.CharField(max_length=6, choices=ReduceGoal.choices,
                                  default=ReduceGoal.NONE)
    daily_limits = models.JSONField(default=dict, blank=True)
    # R9 §B: the "Private" habit. Labelled only "Private" anywhere it is shown, and it
    # never reaches the AI (chat, chat tools, AI summaries or check-in signals).
    private_habit_enabled = models.BooleanField(default=False)
    private_on_today = models.BooleanField(default=False)
    private_goal = models.CharField(max_length=6, choices=ReduceGoal.choices,
                                    default=ReduceGoal.NONE)

    # R10 §B3: Garmin's lactate threshold. Zones switch to it only when present, and
    # the easy zones can never get harder (analysis.zones.from_lactate_threshold).
    class ZonesSource(models.TextChoices):
        RESERVE = "heart_rate_reserve", "Heart-rate reserve"
        LT = "lactate_threshold", "Lactate threshold"

    lt_hr = models.PositiveSmallIntegerField(null=True, blank=True)
    lt_pace_s = models.PositiveSmallIntegerField(null=True, blank=True,
                                                 help_text="Threshold pace, sec/km.")
    lt_date = models.DateField(null=True, blank=True)
    zones_source = models.CharField(max_length=20, choices=ZonesSource.choices,
                                    default=ZonesSource.RESERVE)
    zones_updated_at = models.DateTimeField(null=True, blank=True)

    # R8 §D: where the athlete runs, rounded to 2 decimals (~1 km) — never finer.
    class LocationSource(models.TextChoices):
        RUNS = "runs", "From runs"
        CITY = "city", "City"
        NONE = "none", "None"

    location_lat = models.FloatField(null=True, blank=True)
    location_lon = models.FloatField(null=True, blank=True)
    location_name = models.CharField(max_length=120, blank=True, default="")
    location_city = models.CharField(max_length=120, blank=True, default="",
                                     help_text="What the athlete typed; overrides runs.")
    location_source = models.CharField(max_length=4, choices=LocationSource.choices,
                                       default=LocationSource.NONE)

    # R11 §E: run maps trim the first and last 200 m so home/work never shows.
    map_hide_endpoints = models.BooleanField(default=True)

    # R13: auto-adjust after each run (§1), strength sessions (§4), caffeine tile (§9),
    # daily "Anything hurting?" (§3) and the quit-smoking savings goal (§8).
    auto_adjust_plan = models.BooleanField(default=True)
    strength_per_week = models.PositiveSmallIntegerField(default=0)
    caffeine_on_today = models.BooleanField(default=False)
    pain_daily_check = models.BooleanField(default=False)
    savings_goal_name = models.CharField(max_length=60, blank=True, default="")
    savings_goal_amount = models.FloatField(null=True, blank=True)

    # R14 §1: the optional Today cards that are on, in order (null = the app default).
    # The frontend owns the card catalogue; the backend only checks the shape.
    today_layout = models.JSONField(null=True, blank=True)
    # R14 §3: apply weather swaps without asking (default: suggest only).
    weather_auto_apply = models.BooleanField(default=False)
    # R14 §14: per-athlete monthly AI call budget set by an admin (null = the default,
    # AI_MONTHLY_CALL_BUDGET). Never writable through the athlete API.
    ai_call_budget = models.PositiveIntegerField(null=True, blank=True)

    # R18 §B: profile = the single source of truth. Read through apps.athletes.effective.
    sleep_need_minutes = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Override of Garmin's sleep need (null = Garmin's).")
    usual_run_time = models.TimeField(null=True, blank=True)
    loop_distance_km = models.FloatField(null=True, blank=True,
                                         help_text="One lap of the athlete's usual loop.")
    injury_note = models.CharField(max_length=200, blank=True, default="")
    # {field: {"value": ..., "at": iso|null}} — the explicit setting and when it changed
    # (apps.athletes.profile_params). For available_days / long_run_day / runs_per_week the
    # columns hold the effective value, so the explicit one is kept here.
    profile_settings = models.JSONField(default=dict, blank=True)

    # Whether the athlete has been through onboarding. Needed as an explicit flag
    # rather than inferred: the router has to decide where a freshly-registered
    # athlete lands, and racing a redirect against a state update silently skipped
    # onboarding entirely.
    onboarding_complete = models.BooleanField(default=False)

    # System-managed. Never writable through the API — a client that could set
    # garmin_connected=True could make the UI lie about whether sync works.
    garmin_connected = models.BooleanField(default=False)
    garmin_last_sync = models.DateTimeField(null=True, blank=True)
    # Set once the 12-month history backfill has finished. Until then each sync pages
    # deeper (R6 §1); after it, a sync only fetches until it meets a known activity.
    garmin_backfilled = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.display_name or self.user.username

    @property
    def local_now(self):
        """Now, in the athlete's own timezone.

        Django's TIME_ZONE is UTC, so timezone.localdate() answers a question nobody
        asked: at 00:48 in Kolkata it is still yesterday in UTC, and the whole app
        would show yesterday's session. Every 'today' must come from here.
        """
        from zoneinfo import ZoneInfo

        from django.utils import timezone

        try:
            zone = ZoneInfo(self.timezone or "UTC")
        except Exception:  # noqa: BLE001 — a bad zone must not break every page
            zone = ZoneInfo("UTC")
        return timezone.now().astimezone(zone)

    @property
    def local_today(self):
        return self.local_now.date()

    @property
    def age(self) -> int | None:
        if not self.date_of_birth:
            return None
        today = self.local_today
        born = self.date_of_birth
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))

    @property
    def training_days_per_week(self) -> int:
        return sum(1 for v in (self.available_days or {}).values() if v)

    def is_available(self, weekday: int) -> bool:
        """weekday: 0 = Monday."""
        return bool((self.available_days or {}).get(str(weekday), False))

    def zones(self):
        """Heart-rate zones, or None when the data cannot support them.

        Resting HR comes from Garmin's nightly measurement in preference to the
        profile field, because it is measured rather than remembered. Max HR falls
        back to the highest value ever *observed* in this athlete's own activities —
        a real measurement, and a conservative one: a true maximum is likely higher,
        which makes the derived zones slightly easier rather than harder.

        There is deliberately no 220-age fallback. That formula has a ±10-12 bpm
        spread, wide enough to put someone a full zone out, and a wrong zone is worse
        than no zone.
        """
        from django.db.models import Max

        from analysis.zones import build

        from apps.activities.models import Activity
        from apps.ingest.models import DailyMetrics

        resting = self.resting_hr
        source = "profile"
        if not resting:
            recent = [
                row.resting_hr
                for row in DailyMetrics.objects.filter(athlete=self).order_by("-metric_date")[:28]
                if row.resting_hr
            ]
            resting = sorted(recent)[len(recent) // 2] if recent else None

        maximum = self.max_hr
        if not maximum:
            maximum = Activity.objects.filter(athlete=self).aggregate(
                peak=Max("max_hr")
            )["peak"]
            source = "observed"

        reserve = build(resting, maximum, max_source=source) if resting and maximum else None
        if self.zones_source == self.ZonesSource.LT and self.lt_hr:
            from analysis.zones import from_lactate_threshold

            lt = from_lactate_threshold(self.lt_hr, max_hr=maximum, resting_hr=resting,
                                        reserve=reserve, hr_ceiling=self.hr_ceiling)
            if lt is not None:
                return lt
        return reserve

    @property
    def token_dir(self) -> str:
        """Per-athlete Garmin token directory. Never shared between athletes."""
        from django.conf import settings

        return f"{settings.GARMIN_TOKEN_DIR}/athlete_{self.pk}"


class OwnedByAthlete(models.Model):
    """Base for every tenant-scoped model."""

    athlete = models.ForeignKey(
        Athlete, on_delete=models.CASCADE, related_name="%(class)ss"
    )

    class Meta:
        abstract = True


class MetricEntry(OwnedByAthlete):
    """One measurement of a slowly-changing number: weight, threshold pace, HR.

    A history rather than a single profile field, because the trend is the point — a
    weight that "is" 72 kg says nothing about whether the diet is working. "Current"
    is the latest by `recorded_at`, and writing a weight or threshold-pace entry
    re-mirrors that value onto the Athlete so hot paths read one row.
    """

    class Kind(models.TextChoices):
        WEIGHT = "weight", "Weight (kg)"
        THRESHOLD_PACE = "threshold_pace", "Threshold pace (s/km)"
        RESTING_HR = "resting_hr", "Resting HR (bpm)"
        MAX_HR = "max_hr", "Max HR (bpm)"

    class Source(models.TextChoices):
        MANUAL = "manual", "Manual input"
        GARMIN = "garmin", "Garmin"
        ESTIMATED = "estimated", "Estimated"

    # Which Athlete field each kind mirrors to. Only these two, per the spec: resting
    # and max HR feed zone maths that already prefers measured Garmin values, and a
    # stray manual entry silently overriding those would move every zone.
    MIRRORED = {"weight": "weight_kg", "threshold_pace": "threshold_pace_s"}

    kind = models.CharField(max_length=16, choices=Kind.choices, db_index=True)
    value = models.FloatField()
    recorded_at = models.DateTimeField(db_index=True)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-recorded_at", "-id"]
        verbose_name_plural = "metric entries"

    def __str__(self):
        return f"{self.kind}={self.value} @ {self.recorded_at:%Y-%m-%d}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        mirror(self.athlete, self.kind)

    def delete(self, *args, **kwargs):
        athlete, kind = self.athlete, self.kind
        result = super().delete(*args, **kwargs)
        mirror(athlete, kind)
        return result


def mirror(athlete: Athlete, kind: str) -> None:
    """Copy the current (latest) entry of `kind` onto the Athlete field it mirrors.

    Recomputed from the table rather than from the entry just written: back-filling an
    old weight must not overwrite today's.
    """
    field = MetricEntry.MIRRORED.get(kind)
    if not field:
        return
    latest = (
        MetricEntry.objects.filter(athlete=athlete, kind=kind)
        .order_by("-recorded_at", "-id").first()
    )
    if latest is None:
        return  # deleting the last entry leaves the profile value as it was
    value = round(latest.value) if field == "threshold_pace_s" else latest.value
    if getattr(athlete, field) != value:
        setattr(athlete, field, value)
        athlete.save(update_fields=[field, "updated_at"])


def generate_invite_code() -> str:
    """12 characters from an alphabet without look-alikes (no 0/O, 1/I/L)."""
    import secrets

    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(12))


class InviteCode(models.Model):
    """Registration ticket for REGISTRATION_MODE=invite (docs/DEPLOY.md §2.2).

    Not tenant data: it belongs to the operator, and survives the athlete who used it.
    Consumption is a single conditional UPDATE (see apps/athletes/invites.py), so two
    people racing for the last use cannot both win.
    """

    code = models.CharField(max_length=32, unique=True, default=generate_invite_code)
    note = models.CharField(max_length=200, blank=True, help_text="Who it is for.")
    max_uses = models.PositiveIntegerField(default=1)
    uses = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(null=True, blank=True)
    # R14 §14: revoked from the admin page (kept for the record, never usable again).
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} ({self.uses}/{self.max_uses})"

    def save(self, *args, **kwargs):
        # Stored upper-case so matching is exact; people type codes in any case.
        self.code = (self.code or "").strip().upper()
        super().save(*args, **kwargs)

    @property
    def is_usable(self) -> bool:
        from django.utils import timezone

        return self.revoked_at is None and self.uses < self.max_uses and (
            self.expires_at is None or self.expires_at > timezone.now()
        )


class DataExport(OwnedByAthlete):
    """R13 §15: one "Export my data" ZIP. Built by a Celery task into the media volume
    (never under a public URL), downloadable once by its owner with a one-time token,
    and deleted after the download or 24 h."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"
        EXPIRED = "expired", "Expired"
        DOWNLOADED = "downloaded", "Downloaded"

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    file_name = models.CharField(max_length=200, blank=True, default="")
    size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    # The one-time download token is an HMAC of (id, created_at) with SECRET_KEY —
    # re-derivable, never stored (apps/athletes/export.py).
    error = models.CharField(max_length=300, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    downloaded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
