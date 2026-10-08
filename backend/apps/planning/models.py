"""Races. The plan is resolved from these, never from a single stored date."""

from django.db import models

from apps.athletes.models import OwnedByAthlete


class Race(OwnedByAthlete):
    """One race on the calendar.

    `is_target` marks the A race the ramp counts down to. Every other race is
    prescribed at its own distance with its own short taper and recovery window, and
    does not move the plan — which is exactly what a single-date plan gets wrong.
    """

    name = models.CharField(max_length=120)
    date = models.DateField(db_index=True)
    distance_km = models.FloatField()
    is_target = models.BooleanField(
        default=False, help_text="The A race. At most one should be set."
    )
    notes = models.TextField(blank=True)
    # R13 §2: the race-day planner's inputs.
    goal_time_s = models.PositiveIntegerField(null=True, blank=True)
    start_time = models.TimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date"]
        constraints = [
            models.UniqueConstraint(fields=["athlete", "date"], name="uniq_athlete_race_date")
        ]

    def __str__(self):
        return f"{self.name} ({self.date}, {self.distance_km:g} km)"


class TrainingPlan(OwnedByAthlete):
    """A persisted plan: proposed in chat, accepted (or declined) by the athlete.

    MyRunAnalizer regenerated the plan on every read. RunCoach stores it, because a
    plan can now be proposed, accepted, moved and skipped — none of which a projection
    can remember. The numbers inside are still the deterministic generator's; the model
    only names and describes the phases.

    At most one `active` plan per athlete, enforced by a partial unique constraint so
    a race between two accepts fails loudly instead of leaving two calendars.
    """

    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"
        DECLINED = "declined", "Declined"

    race = models.ForeignKey(
        Race, on_delete=models.SET_NULL, null=True, blank=True, related_name="plans"
    )
    name = models.CharField(max_length=160)
    goal = models.TextField(blank=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PROPOSED, db_index=True
    )
    generator_version = models.CharField(max_length=20)
    # Generator facts worth keeping: warnings, peak km, runway, inputs used. Stored so
    # the plan can explain itself later without re-running anything.
    summary = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    chat_message = models.ForeignKey(
        "coaching.ChatMessage", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="proposed_plans",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["athlete"], condition=models.Q(status="active"),
                name="one_active_plan_per_athlete",
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.status})"


class PlanPhase(models.Model):
    """Consecutive generator weeks with the same phase, merged into one block."""

    class Kind(models.TextChoices):
        BASE = "base", "Base"
        BUILD = "build", "Build"
        PEAK = "peak", "Peak"
        TAPER = "taper", "Taper"
        RECOVERY = "recovery", "Recovery"
        RACE = "race", "Race"

    plan = models.ForeignKey(TrainingPlan, on_delete=models.CASCADE, related_name="phases")
    order = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    # The generator's own phase label (FOUNDATION, AEROBIC, ...). Kept because `kind`
    # is a coarser bucket for colour, and merging was done on this, not on `kind`.
    generator_phase = models.CharField(max_length=16, blank=True)
    start = models.DateField()
    end = models.DateField()
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["plan", "order"]
        constraints = [
            models.UniqueConstraint(fields=["plan", "order"], name="uniq_plan_phase_order")
        ]

    def __str__(self):
        return f"{self.name} {self.start}–{self.end}"


class PlannedWorkout(OwnedByAthlete):
    """One prescribed session on one date, with steps the workout bar draws.

    `athlete` is denormalised from the plan on purpose: tenant scoping is a single
    filter on every query, never a join someone can forget.
    """

    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        COMPLETED = "completed", "Completed"
        SKIPPED = "skipped", "Skipped"

    plan = models.ForeignKey(TrainingPlan, on_delete=models.CASCADE, related_name="workouts")
    phase = models.ForeignKey(
        PlanPhase, on_delete=models.SET_NULL, null=True, blank=True, related_name="workouts"
    )
    date = models.DateField(db_index=True)
    title = models.CharField(max_length=120)
    kind = models.CharField(max_length=12)        # generator SessionKind
    duration_s = models.PositiveIntegerField()
    load = models.FloatField()
    steps = models.JSONField(default=list)
    description = models.TextField(blank=True)
    purpose = models.TextField(blank=True)
    target_zone = models.CharField(max_length=4, null=True, blank=True)
    fueling = models.JSONField(default=dict)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PLANNED, db_index=True
    )
    completed_activity = models.ForeignKey(
        "activities.Activity", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="planned_workouts",
    )
    moved_from = models.DateField(null=True, blank=True)
    # R7 §1: the morning check-in applied ("Use this"). The prescription as planned is
    # kept so the change can be shown — and so the check-in always judges the original.
    adjusted_by = models.CharField(max_length=12, blank=True, default="")
    original_steps = models.JSONField(null=True, blank=True)
    # {title, kind, duration_s, load, target_zone, description} as planned.
    original = models.JSONField(null=True, blank=True)
    # R7 §3: what is on the athlete's watch. The hash is of the exact payload + date
    # uploaded; a different hash now means the watch copy is out of date.
    garmin_workout_id = models.BigIntegerField(null=True, blank=True)
    garmin_schedule_id = models.BigIntegerField(null=True, blank=True)
    garmin_synced_at = models.DateTimeField(null=True, blank=True)
    garmin_payload_hash = models.CharField(max_length=64, blank=True, default="")
    # R16 §A: the athlete edited it (app or chat). Auto-adjust, the weekly adaptation,
    # weather swaps and re-layout leave an edited workout's content alone. `pre_edit` is
    # the generated version ({title, kind, duration_s, load, steps, target_zone,
    # description, fueling, notes}) kept for "Undo my edits".
    edited_by = models.CharField(max_length=8, blank=True, default="")
    edited_at = models.DateTimeField(null=True, blank=True)
    edited_via = models.CharField(max_length=8, blank=True, default="")
    pre_edit = models.JSONField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "id"]

    def __str__(self):
        return f"{self.date} {self.title}"

    @property
    def user_edited(self) -> bool:
        return self.edited_by == "user"


class PlanAdjustment(OwnedByAthlete):
    """One weekly adaptation of an active plan (R6 §2), at most one per plan per week.

    `week_start` is the Monday of the week that was adjusted (the week after the one
    reviewed). `factor` is what that week's future workouts were scaled by — 1.0 when
    the plan was followed as written. The row exists either way: it is the record that
    the week was reviewed, which is what makes the task idempotent.
    """

    plan = models.ForeignKey(TrainingPlan, on_delete=models.CASCADE, related_name="adjustments")
    week_start = models.DateField()
    reason = models.TextField()
    factor = models.FloatField(default=1.0)
    planned_run_s = models.PositiveIntegerField(default=0)
    actual_run_s = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-week_start"]
        constraints = [
            models.UniqueConstraint(fields=["plan", "week_start"], name="uniq_plan_week_adjustment")
        ]

    def __str__(self):
        return f"{self.week_start} x{self.factor}"


class WorkoutAdjustment(OwnedByAthlete):
    """R13 §1: one automatic change to one future workout, after a run (or a pain
    report). Keeps the prescription before and after so the athlete can undo it.

    Separate from PlanAdjustment, whose (plan, week_start) row is the weekly adaptation's
    idempotency key; these are per workout and there can be several a week.
    """

    class Status(models.TextChoices):
        APPLIED = "applied", "Applied"
        UNDONE = "undone", "Undone"

    plan = models.ForeignKey(TrainingPlan, on_delete=models.CASCADE,
                             related_name="auto_adjustments")
    workout = models.ForeignKey(PlannedWorkout, on_delete=models.SET_NULL, null=True,
                                blank=True, related_name="auto_adjustments")
    activity = models.ForeignKey("activities.Activity", on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name="auto_adjustments")
    trigger = models.CharField(max_length=10)          # run | checkin | pain
    action = models.CharField(max_length=10)           # shorten | easier | run_walk | rest | swap | extend
    reason = models.TextField()
    chip = models.CharField(max_length=200)
    signals = models.JSONField(default=list)
    # {title, kind, duration_s, load, steps, target_zone, description, fueling, date}
    before = models.JSONField()
    after = models.JSONField()
    group = models.CharField(max_length=40, blank=True, default="")
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.APPLIED)
    created_at = models.DateTimeField(auto_now_add=True)
    undone_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class StrengthSession(OwnedByAthlete):
    """R13 §4: a 20-minute strength & drills session on the calendar."""

    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        COMPLETED = "completed", "Completed"
        SKIPPED = "skipped", "Skipped"

    plan = models.ForeignKey(TrainingPlan, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="strength_sessions")
    date = models.DateField(db_index=True)
    title = models.CharField(max_length=80)
    duration_s = models.PositiveIntegerField(default=1200)
    level = models.PositiveSmallIntegerField(default=1)
    exercises = models.JSONField(default=list)
    after_run = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PLANNED)
    completed_activity = models.ForeignKey(
        "activities.Activity", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="strength_sessions")
    auto_completed = models.BooleanField(default=False)
    garmin_workout_id = models.BigIntegerField(null=True, blank=True)
    garmin_schedule_id = models.BigIntegerField(null=True, blank=True)
    garmin_synced_at = models.DateTimeField(null=True, blank=True)
    garmin_payload_hash = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "id"]


class GarminUpload(OwnedByAthlete):
    """Every Garmin workout RunCoach itself created on the athlete's Garmin calendar.

    The registry is what makes cleanup safe: only ids recorded here are ever deleted by
    the same-day sweep (garmin_registry.sweep), so a workout the athlete made in Garmin
    Connect is never touched. A row is added right after an upload and removed once the
    Garmin copy is deleted. It outlives the PlannedWorkout / StrengthSession it was sent
    for (SET_NULL) — exactly the leftovers (plan rebuilds, re-layouts, a forget that hit
    the rate limit) the sweep exists to remove.
    """

    class Source(models.TextChoices):
        RUN = "run", "Running workout"
        STRENGTH = "strength", "Strength session"

    garmin_workout_id = models.BigIntegerField()
    garmin_schedule_id = models.BigIntegerField(null=True, blank=True)
    date = models.DateField(db_index=True)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.RUN)
    workout = models.ForeignKey(PlannedWorkout, on_delete=models.SET_NULL, null=True,
                                blank=True, related_name="garmin_uploads")
    strength = models.ForeignKey(StrengthSession, on_delete=models.SET_NULL, null=True,
                                 blank=True, related_name="garmin_uploads")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "id"]
        constraints = [
            models.UniqueConstraint(fields=["athlete", "garmin_workout_id"],
                                    name="uniq_athlete_garmin_upload"),
        ]

    def __str__(self):
        return f"{self.date} garmin {self.garmin_workout_id}"


class WeatherSuggestion(OwnedByAthlete):
    """R14 §3: "Weather: move Thu run to Fri?" — a proposed move (or swap with an
    optional walk) of one planned run away from a bad-weather day. Nothing moves until
    the athlete taps Move, unless `weather_auto_apply` is on."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPLIED = "applied", "Applied"
        DISMISSED = "dismissed", "Dismissed"
        EXPIRED = "expired", "Expired"

    workout = models.ForeignKey(PlannedWorkout, on_delete=models.SET_NULL, null=True,
                                blank=True, related_name="weather_suggestions")
    swap_workout = models.ForeignKey(PlannedWorkout, on_delete=models.SET_NULL, null=True,
                                     blank=True, related_name="weather_swaps")
    workout_title = models.CharField(max_length=120)
    workout_kind = models.CharField(max_length=12)
    duration_s = models.PositiveIntegerField(default=0)
    from_date = models.DateField()
    to_date = models.DateField()
    action = models.CharField(max_length=5)                 # move | swap
    text = models.CharField(max_length=120)
    reason = models.CharField(max_length=300)
    reasons = models.JSONField(default=list)
    from_weather = models.JSONField(default=dict)
    to_weather = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING,
                              db_index=True)
    auto_applied = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["workout", "from_date"],
                                               name="uniq_weather_suggestion")]


class CalendarFeed(OwnedByAthlete):
    """R14 §5: the private ICS subscription. The token is the only credential (a
    capability URL): unguessable, regenerated or revoked from Me → Calendar sync."""

    token = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_fetched_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["athlete"], name="one_feed_per_athlete")]


class CalendarFeedItem(OwnedByAthlete):
    """What each calendar event looked like when last served, so its SEQUENCE goes up
    (and LAST-MODIFIED moves) only when the event really changed."""

    uid = models.CharField(max_length=80)
    content_hash = models.CharField(max_length=64)
    sequence = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["athlete", "uid"],
                                               name="uniq_feed_item_uid")]
