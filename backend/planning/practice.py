"""Training with no race on the calendar. Pure — no Django.

Every plan this app has ever made counts down to a date. That is the right
shape when there is a date, and the wrong shape for what Rohit actually asked
for: *"completely forget about race day, i am not participating in any race
now, i need practice only, i want to see improvement on myself."*

The app's answer to that was to keep his October race plan running — a taper
and a race week on 11 January for an event he had deleted — and his own coach
told him so in the UI: "The current planner cannot create a formal no-race
plan." This is that plan.

**A race gives four things, and only one of them needs a date.** It gives an
end, a target distance, a reason the volume stops rising, and something to aim
at. Only the first needs a calendar. The other three are replaced here by a
*milestone*: the next unbroken block worth reaching.

**The milestone ladder is time, not distance.** Fifteen minutes of continuous
running is the same training stimulus whether you cover 2 km or 3, and a
beginner who chases distance at a fixed pace is chasing two things at once.
Distance is shown alongside, computed at the athlete's own pace, because that
is what they will tell people — but the target is the minutes.

**Nothing here can be failed.** A milestone is passed when it is passed. There
is no date attached to it, because the honest answer to "when will I run for
thirty minutes" is a projection, and a projection presented as a deadline is
just a race with extra steps.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace

from .generator import (
    PHASE_SHAPE, Baseline, Plan, PlanConfig, Week, _continuous_curve,
    _lay_out_week, _round_down, _volume_curve,
)

#: How far ahead a practice plan is written. Long enough to show a direction,
#: short enough that it is rewritten from real data before the far end matters.
#: An open-ended plan that projects a year out is a year of fiction.
HORIZON_WEEKS = 12

#: The ladder. Each rung is a longest unbroken block worth reaching, and the
#: gaps widen because the early ones arrive in days and the later ones in months.
#:
#: Stops at an hour. Past that the useful question stops being "can you keep
#: running" and starts being "how fast", which is a different plan.
MILESTONES_S: tuple[int, ...] = (
    5 * 60, 10 * 60, 15 * 60, 20 * 60, 30 * 60, 45 * 60, 60 * 60,
)

#: Weekly running volume a practice plan will build toward, as a multiple of the
#: current milestone's duration. Three sessions a week around the milestone,
#: roughly — enough to support it without the volume becoming the goal.
VOLUME_MULTIPLE = 3.2

#: The block shape a practice plan repeats: three loading weeks, one cutback.
#: Not a ramp toward anything, because there is nothing to ramp toward.
BLOCK_WEEKS = 4


@dataclass(frozen=True)
class Milestone:
    seconds: int
    index: int
    total: int
    #: What that block covers at this athlete's pace, which is what they will
    #: say out loud even though the target is the minutes.
    distance_m: float
    reached: bool

    @property
    def label(self) -> str:
        minutes = self.seconds // 60
        return f"{minutes} minutes unbroken"


def milestone_for(longest_run_s: float, run_pace_s_per_km: float) -> Milestone:
    """The next rung above what the athlete has already held.

    Strictly above: a milestone you have already passed is not a target, and
    showing one is how an app ends up congratulating somebody for standing
    still.
    """
    for index, seconds in enumerate(MILESTONES_S):
        if longest_run_s < seconds:
            return Milestone(
                seconds=seconds, index=index, total=len(MILESTONES_S),
                distance_m=(seconds / run_pace_s_per_km) * 1000 if run_pace_s_per_km else 0.0,
                reached=False,
            )
    top = MILESTONES_S[-1]
    return Milestone(
        seconds=top, index=len(MILESTONES_S) - 1, total=len(MILESTONES_S),
        distance_m=(top / run_pace_s_per_km) * 1000 if run_pace_s_per_km else 0.0,
        reached=True,
    )


def passed(longest_run_s: float) -> list[int]:
    return [s for s in MILESTONES_S if longest_run_s >= s]


def _phases(weeks: int) -> list[str]:
    """A repeating block, with no taper and no race week.

    The first block is FOUNDATION because somebody with no race is usually
    either starting or coming back, and both want the same first month. After
    that it is AEROBIC indefinitely: the phase that builds the thing the
    milestone measures.
    """
    out: list[str] = []
    for index in range(weeks):
        out.append("FOUNDATION" if index < BLOCK_WEEKS else "AEROBIC")
    return out


def generate_practice(
    plan_start: dt.date,
    baseline: Baseline,
    config: PlanConfig | None = None,
    weeks: int = HORIZON_WEEKS,
) -> Plan:
    """A plan that builds toward the next milestone and then keeps going.

    Reuses the generator's own curves and week layout, so the safety rules are
    the same ones a race plan obeys: the weekly increase cap, the cutback every
    fourth week, hard sessions never back to back, the long run on the day the
    athlete said they have time for it, and the regain rate for ground already
    held.
    """
    config = config or PlanConfig()
    weeks = max(1, int(weeks))
    phases = _phases(weeks)

    milestone = milestone_for(baseline.longest_run_s, baseline.run_pace_s_per_km)

    # Continuous capacity is computed FIRST, and the volume ceiling derives from
    # where it ends up.
    #
    # The obvious order — ceiling from today's milestone, then volume — pinned the
    # whole twelve weeks to the rung the athlete happens to be on now. Rohit is on
    # the 10-minute rung and will pass three more inside this horizon, so it
    # capped him at 2.8 km a week when he ran 5.3 in August. The ceiling exists to
    # stop the 10% rule compounding into a number nobody asked for, not to hold
    # the plan at today's ability, so it is set from where the block is going.
    continuous, peak_continuous = _continuous_curve(
        phases, baseline.longest_run_s, config,
        baseline.demonstrated_longest_s or baseline.longest_run_s,
    )
    ideal_peak_km = _round_down(
        (peak_continuous * VOLUME_MULTIPLE / baseline.run_pace_s_per_km)
        if baseline.run_pace_s_per_km else 10.0
    )
    ideal_peak_km = max(ideal_peak_km, _round_down(baseline.run_km_per_week * 1.1))

    volumes, achieved_peak, reached = _volume_curve(
        phases, baseline.run_km_per_week, ideal_peak_km, config,
    )

    warnings: list[str] = []
    if peak_continuous < milestone.seconds:
        warnings.append(
            f"This block gets your longest unbroken run to about "
            f"{peak_continuous / 60:.0f} minutes, against the "
            f"{milestone.seconds // 60} you are working toward. That is normal — "
            "the plan is rewritten from what you actually do, so the milestone "
            "arrives in a later block rather than being missed in this one."
        )
    else:
        warnings.append(
            f"On this block you should pass {milestone.seconds // 60} minutes "
            "unbroken. Nothing here has a deadline on it: when you pass it, the "
            "next one appears."
        )

    built: list[Week] = []
    for index, (phase, volume) in enumerate(zip(phases, volumes)):
        start = plan_start + dt.timedelta(days=index * 7)
        week = Week(
            index=index,
            # Counts up, not down. There is nothing to count down to, and a
            # weeks_out of 0 would make every mode resolver think it is race week.
            weeks_out=weeks - index - 1,
            phase=phase,
            start_date=start,
            planned_run_km=volume,
            continuous_target_s=continuous[index],
            is_cutback=index > 0 and volume < volumes[index - 1],
        )
        week.sessions = _lay_out_week(week, baseline, config)
        built.append(week)

    return Plan(
        runway="STANDARD",
        weeks_available=weeks,
        peak_run_km=achieved_peak,
        ideal_peak_run_km=ideal_peak_km,
        reached_ideal_peak=reached,
        peak_continuous_s=round(peak_continuous),
        # There is no race, so the thing the continuous curve is measured
        # against is the milestone.
        race_needs_continuous_s=milestone.seconds,
        warnings=warnings,
        weeks=built,
    )


# --- a distance by a date, with no race attached ------------------------------
#
# Rohit: "if its not compulsary that i dont have an end date, you can choose
# accordingly — like within this many days i wanna finish 5k."
#
# A milestone with no date is right for somebody who wants to train; a date is
# right for somebody who wants a deadline. Neither needs an entry fee, a start
# line or a taper, and the app only ever offered the version that came with all
# three.
#
# The one thing this mode must do that a race plan does not: refuse. A race date
# is a fact, so a plan to it is built and warned about. A self-set date is a
# wish, and the useful answer to an impossible wish is the possible one beside
# it — not a plan that spends four months arriving somewhere short.


@dataclass(frozen=True)
class Feasibility:
    """Whether a distance can be run continuously by a date, and when it can."""

    target_distance_km: float
    target_date: dt.date
    #: When the ramp starts. Needed so the earliest achievable date is an
    #: absolute answer rather than one derived from the date being asked about —
    #: the first version drifted by days depending on what was requested, which
    #: makes "the honest date" look like a guess.
    plan_start: dt.date
    #: Continuous running the target needs, at this athlete's current pace.
    needs_s: int
    #: What the ramp reaches by the target date.
    reaches_s: int
    weeks_available: int
    #: The first week the ramp reaches the target, however far out.
    weeks_needed: int | None
    achievable: bool

    @property
    def earliest_date(self) -> dt.date | None:
        """The first date this is realistic, whatever date was asked about."""
        if self.weeks_needed is None:
            return None
        return self.plan_start + dt.timedelta(weeks=self.weeks_needed)


def assess_goal(
    plan_start: dt.date,
    target_date: dt.date,
    target_distance_km: float,
    baseline: Baseline,
    config: PlanConfig | None = None,
    search_weeks: int = 104,
) -> Feasibility:
    """Can this distance be run without stopping by this date, and if not, when.

    Projected with the same continuous curve a plan is built from, including the
    regain rate — so an athlete returning to ground they have held is told the
    truth about how fast it comes back, rather than being quoted the beginner's
    timeline for it.
    """
    config = config or PlanConfig()
    weeks_available = max((target_date - plan_start).days // 7, 0)
    needs_s = round(target_distance_km * baseline.run_pace_s_per_km)

    curve, _ = _continuous_curve(
        ["AEROBIC"] * max(search_weeks, weeks_available + 1),
        baseline.longest_run_s, config,
        baseline.demonstrated_longest_s or baseline.longest_run_s,
    )
    weeks_needed = next((i for i, value in enumerate(curve) if value >= needs_s), None)
    reaches_s = round(curve[min(weeks_available, len(curve) - 1)]) if curve else 0

    return Feasibility(
        target_distance_km=target_distance_km,
        target_date=target_date,
        plan_start=plan_start,
        needs_s=needs_s,
        reaches_s=reaches_s,
        weeks_available=weeks_available,
        weeks_needed=weeks_needed,
        achievable=weeks_needed is not None and weeks_needed <= weeks_available,
    )


def generate_goal(
    plan_start: dt.date,
    target_date: dt.date,
    target_distance_km: float,
    baseline: Baseline,
    config: PlanConfig | None = None,
) -> tuple[Plan, Feasibility]:
    """A dated plan toward running a distance, with no race ceremony.

    The plan is built for the weeks available either way. When the date is not
    achievable the plan is still returned — the training is the same training —
    but the warning says so plainly and names the date that would work, because
    an athlete who is told "no" and nothing else just picks another number.
    """
    config = config or PlanConfig()
    verdict = assess_goal(plan_start, target_date, target_distance_km, baseline, config)
    weeks = max(verdict.weeks_available, 4)

    plan = generate_practice(plan_start, baseline, config, weeks=weeks)

    target_label = f"{target_distance_km:g} km without stopping"
    if verdict.achievable:
        warning = (
            f"{target_label} by {target_date:%-d %B} is realistic: the ramp "
            f"reaches {verdict.reaches_s / 60:.0f} minutes of continuous running "
            f"against the {verdict.needs_s / 60:.0f} it needs at your pace."
        )
    elif verdict.earliest_date:
        warning = (
            f"{target_label} by {target_date:%-d %B} is not realistic from where "
            f"you are. It needs {verdict.needs_s / 60:.0f} minutes of continuous "
            f"running and the ramp reaches {verdict.reaches_s / 60:.0f} by then. "
            f"{verdict.earliest_date:%-d %B %Y} is the honest date — this plan "
            "builds toward it, and the date can move once you are further along."
        )
    else:
        warning = (
            f"{target_label} is a long way from a {baseline.longest_run_s / 60:.0f}"
            "-minute unbroken run. The plan below builds the block that gets you "
            "there; the distance is worth revisiting once it is bigger."
        )

    plan = replace(plan, warnings=[warning, *plan.warnings[1:]],
                   race_needs_continuous_s=verdict.needs_s)
    return plan, verdict
