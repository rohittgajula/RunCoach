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
import math
from dataclasses import dataclass, replace
from typing import Literal

from .generator import (
    CONTINUOUS_CEILING_MIN, PHASE_SHAPE, Baseline, Plan, PlanConfig, Week,
    _continuous_curve, _lay_out_week, _round_down, _volume_curve,
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
    min_peak_run_km: float | None = None,
) -> Plan:
    """A plan that builds toward the next milestone and then keeps going.

    Reuses the generator's own curves and week layout, so the safety rules are
    the same ones a race plan obeys: the weekly increase cap, the cutback every
    fourth week, hard sessions never back to back, the long run on the day the
    athlete said they have time for it, and the regain rate for ground already
    held.

    `min_peak_run_km` raises the volume ceiling the ramp is allowed to climb
    toward. It exists for the run-walk goal mode, where the governing quantity
    is how far the long run *covers* rather than how long its unbroken block
    is, and the milestone-derived ceiling would otherwise stop the ramp short
    of a distance the athlete explicitly asked for. It moves the ceiling only:
    the weekly increase cap still decides how fast the ramp gets there, which
    is the part that keeps people uninjured.
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
    if min_peak_run_km:
        ideal_peak_km = max(ideal_peak_km, _round_down(float(min_peak_run_km)))

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


#: The two honest readings of "I want to do 5 km by March".
#:
#: They are different questions with different answers, and the app used to
#: answer only the first while accepting the words of the second. Rohit asked
#: for "5k between march and april with breaks" and would have been told his
#: date was impossible — true of running it without stopping, and false of what
#: he actually asked for.
GoalStyle = Literal["nonstop", "run_walk"]

#: A run-walk attempt is governed by the long run's TOTAL covered distance; a
#: non-stop one by its longest unbroken block. Mixing the two is the whole bug
#: this mode exists to avoid, so the quantity is named everywhere it is carried.
GOVERNS: dict[GoalStyle, str] = {
    "nonstop": "longest unbroken block",
    "run_walk": "distance covered in one session",
}

#: Past this, a run-walk "session" has stopped being a training session and
#: become a day out. Not a refusal — the plan is still built — but the athlete
#: is told, because four hours of run-walking is a different undertaking from
#: the one most people picture when they say "5k".
LONG_SESSION_WARN_S = 3 * 3600


def coverage_factor(
    run_walk_ratio: float, run_pace_s_per_km: float, walk_pace_s_per_km: float,
) -> float:
    """How far a run-walk session covers, per metre of RUNNING inside it.

    `run_walk_ratio` is the fraction of the session's TIME spent running, which
    is what `PHASE_SHAPE` holds and what `_session` lays a week out with. The
    walking that rides along covers ground too, and for a beginner it covers a
    lot of it: at Rohit's 10:04/km run and 11:40/km walk, a FOUNDATION session
    covers 2.3 metres for every metre he runs.

    Ignoring that is how the app concluded 5 km was two years away. It is also
    why this cannot be folded into the continuous curve: walking adds distance
    without adding a second to the unbroken block.
    """
    if run_walk_ratio <= 0:
        return 0.0
    if run_walk_ratio >= 1 or walk_pace_s_per_km <= 0:
        return 1.0
    walk_time_per_run_time = (1 - run_walk_ratio) / run_walk_ratio
    return 1 + walk_time_per_run_time * (run_pace_s_per_km / walk_pace_s_per_km)


def blended_pace_s_per_km(
    run_walk_ratio: float, run_pace_s_per_km: float, walk_pace_s_per_km: float,
) -> float:
    """Seconds per kilometre of the whole session, running and walking.

    What the athlete will actually see on the watch, and the number that turns
    "5 km with breaks" into "about an hour on your feet" — which is the fact
    that decides whether they want it.
    """
    factor = coverage_factor(run_walk_ratio, run_pace_s_per_km, walk_pace_s_per_km)
    if factor <= 0 or run_walk_ratio <= 0:
        return run_pace_s_per_km
    return run_pace_s_per_km / (run_walk_ratio * factor)


def _long_run_shape(phase: str, config: PlanConfig) -> tuple[float, float]:
    """(share of the week the long run takes, fraction of its time running).

    Read from the same `PHASE_SHAPE` and the same `max_long_run_pct_of_week`
    that `_lay_out_week` uses, including the min() between them — a projection
    that disagrees with what the generator then prescribes is worse than no
    projection.
    """
    shape = PHASE_SHAPE[phase]
    share = min(shape["long_share"], config.max_long_run_pct_of_week / 100)
    return share, shape["run_walk_ratio"]


def covered_by_long_run_m(
    week_run_km: float, phase: str, baseline: Baseline, config: PlanConfig,
) -> float:
    """Total ground the long run covers in a week of this volume and phase."""
    share, ratio = _long_run_shape(phase, config)
    long_run_km = week_run_km * share
    return long_run_km * 1000 * coverage_factor(
        ratio, baseline.run_pace_s_per_km, baseline.walk_pace_s_per_km,
    )


def weekly_volume_for_coverage(
    target_distance_km: float, phase: str, baseline: Baseline, config: PlanConfig,
) -> float:
    """The weekly running volume whose long run covers the target. Inverse of
    `covered_by_long_run_m`, and what the goal plan's volume ceiling is set to.

    Rounded UP to the 0.1 km the volume curve works in, which is the opposite
    of what that curve does to every other figure and is correct here. Every
    weekly volume on the way up rounds down, because rounding up would let a
    10 % cap print an 11 % step. A ceiling is not a step: truncating it leaves
    the ramp stopping just below the distance the athlete asked for. At 5 km
    the exact figure is 7.711 km a week, and 7.7 covers 4.99 — a plan that
    arrives 7 metres short of the whole point of itself.
    """
    share, ratio = _long_run_shape(phase, config)
    factor = coverage_factor(ratio, baseline.run_pace_s_per_km, baseline.walk_pace_s_per_km)
    if share <= 0 or factor <= 0:
        return 0.0
    return math.ceil(target_distance_km / (share * factor) * 10) / 10


@dataclass(frozen=True)
class Feasibility:
    """Whether a distance can be covered by a date, and when it can.

    Carries both readings of the question without mixing them. `needs_s` and
    `reaches_s` are seconds of CONTINUOUS running and mean something only under
    `style="nonstop"`; `needs_m` and `reaches_m` are metres COVERED in one
    session and mean something only under `style="run_walk"`. The fields for
    the other style are left at zero rather than filled with a plausible
    number, because a plausible number in the wrong unit is how this goes
    wrong quietly.
    """

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

    style: GoalStyle = "nonstop"
    #: run_walk: the distance itself, in metres. Here so the two styles read
    #: the same way at the call site.
    needs_m: float = 0.0
    #: run_walk: the furthest the long run covers on or before the target date.
    #: A running maximum, like the continuous curve's capability — a cutback
    #: week prescribes less without unlearning anything, and an athlete who
    #: covered 5 km in week 9 has covered 5 km.
    reaches_m: float = 0.0
    #: run_walk: how long the attempt takes, running and walking together.
    session_s: int = 0
    #: run_walk: seconds per km of the whole session. What the watch will show.
    blended_pace_s_per_km: float = 0.0
    #: run_walk: the weekly running volume the ramp has to reach for the long
    #: run to cover the target. The goal plan's volume ceiling is set to it.
    peak_run_km_needed: float = 0.0

    @property
    def governs(self) -> str:
        """The quantity this verdict is about, named."""
        return GOVERNS[self.style]

    @property
    def earliest_date(self) -> dt.date | None:
        """The first date this is realistic, whatever date was asked about."""
        if self.weeks_needed is None:
            return None
        return self.plan_start + dt.timedelta(weeks=self.weeks_needed)

    @property
    def label(self) -> str:
        """How the goal reads to a human. The one place the words are decided."""
        if self.style == "run_walk":
            return f"{self.target_distance_km:g} km with walk breaks"
        return f"{self.target_distance_km:g} km without stopping"


def assess_goal(
    plan_start: dt.date,
    target_date: dt.date,
    target_distance_km: float,
    baseline: Baseline,
    config: PlanConfig | None = None,
    search_weeks: int = 104,
    style: GoalStyle = "nonstop",
) -> Feasibility:
    """Can this distance be covered by this date, and if not, when.

    Two different questions behind one sentence, and the answers are years
    apart. `style="nonstop"` projects the continuous curve: can the unbroken
    block reach the time the distance takes. `style="run_walk"` projects the
    volume curve: does the long run, walking breaks included, cover the ground.

    Both run on the generator's own curves, so both inherit the weekly increase
    cap, the cutback every fourth week and — for nonstop — the regain rate, and
    neither can quote a date the plan would not actually prescribe.
    """
    config = config or PlanConfig()
    if style == "run_walk":
        return _assess_run_walk(
            plan_start, target_date, target_distance_km, baseline, config, search_weeks,
        )
    return _assess_nonstop(
        plan_start, target_date, target_distance_km, baseline, config, search_weeks,
    )


def _assess_nonstop(
    plan_start, target_date, target_distance_km, baseline, config, search_weeks,
) -> Feasibility:
    """Projected with the same continuous curve a plan is built from, including
    the regain rate — so an athlete returning to ground they have held is told
    the truth about how fast it comes back, rather than being quoted the
    beginner's timeline for it."""
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
        style="nonstop",
        target_distance_km=target_distance_km,
        target_date=target_date,
        plan_start=plan_start,
        needs_s=needs_s,
        reaches_s=reaches_s,
        weeks_available=weeks_available,
        weeks_needed=weeks_needed,
        achievable=weeks_needed is not None and weeks_needed <= weeks_available,
    )


def _assess_run_walk(
    plan_start, target_date, target_distance_km, baseline, config, search_weeks,
) -> Feasibility:
    """Projected with the VOLUME curve, because that is what the long run rides.

    The continuous ceiling does not apply here and must not be borrowed: it
    caps the unbroken block at 75 minutes, which is why 10 km non-stop has no
    honest date at a beginner's pace. Walking is not capped at 75 minutes, and
    a 10 km run-walk is a perfectly ordinary thing to build toward.

    Coverage is tracked as a running maximum. A cutback week covers less
    without unlearning anything, exactly as the continuous curve holds
    capability through one, and "the week you could first cover 5 km" should
    not be withdrawn by the down week after it.
    """
    weeks_available = max((target_date - plan_start).days // 7, 0)
    needs_m = target_distance_km * 1000
    horizon = max(search_weeks, weeks_available + 1)
    phases = _phases(horizon)

    # The search climbs to the SAME ceiling the plan will be built with — the
    # weekly volume whose long run covers the target — and no further.
    #
    # Searching with an unbounded ceiling was wrong in a way that read as
    # confidence: for a 5 km goal nineteen weeks out it projected the long run
    # covering 11.6 km, because nothing stopped the ramp once it passed the
    # target. A projection that overshoots the plan it belongs to is the same
    # failure as one that undershoots it, and it is the more persuasive one.
    peak_needed = weekly_volume_for_coverage(
        target_distance_km, "AEROBIC", baseline, config,
    )
    # Floored at the athlete's own volume the same way `generate_practice`
    # floors it, or the search and the plan disagree for anybody already
    # running more than the goal needs: the curve would step their week DOWN
    # to the ceiling while the plan they are given steps it up.
    search_ceiling = max(peak_needed, _round_down(baseline.run_km_per_week * 1.1))
    volumes, _, _ = _volume_curve(
        phases, baseline.run_km_per_week, search_ceiling, config,
    )

    # Seeded with what the athlete has ALREADY covered in one session. Without
    # this the mode quotes a date to somebody who did the distance in August —
    # the volume curve starts from a weekly figure and divides it across the
    # week, so it can place the long run below a session that actually
    # happened. A record of what happened outranks a projection of it.
    weeks_needed: int | None = None
    best_m = float(baseline.demonstrated_covered_m or 0.0)
    reaches_m = best_m
    achieved_phase = phases[0]
    for index, (phase, volume) in enumerate(zip(phases, volumes)):
        covered = covered_by_long_run_m(volume, phase, baseline, config)
        if covered > best_m:
            best_m = covered
            achieved_phase = phase
        if weeks_needed is None and best_m >= needs_m:
            weeks_needed = index
            achieved_phase = phase
        if index <= weeks_available:
            reaches_m = best_m

    # Quoted from the phase that actually gets there, not from a nominal one.
    # The phases walk different amounts — FOUNDATION walks 60 % of the session
    # and AEROBIC 45 % — so the same distance is a different length of day
    # depending on which week you do it in, and quoting the wrong one makes the
    # app's own estimate disagree with the session it prescribes.
    ratio = PHASE_SHAPE[achieved_phase]["run_walk_ratio"]
    pace = blended_pace_s_per_km(
        ratio, baseline.run_pace_s_per_km, baseline.walk_pace_s_per_km,
    )

    return Feasibility(
        style="run_walk",
        target_distance_km=target_distance_km,
        target_date=target_date,
        plan_start=plan_start,
        needs_s=0,
        reaches_s=0,
        needs_m=needs_m,
        reaches_m=reaches_m,
        session_s=round(target_distance_km * pace),
        blended_pace_s_per_km=pace,
        # The ceiling is quoted from AEROBIC, where a goal plan spends every
        # week after its first block, so the ramp is heading somewhere that
        # supports the distance once the walking share comes down.
        peak_run_km_needed=peak_needed,
        weeks_available=weeks_available,
        weeks_needed=weeks_needed,
        achievable=weeks_needed is not None and weeks_needed <= weeks_available,
    )


def _mmss(seconds: float) -> str:
    seconds = round(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _goal_warning(verdict: Feasibility, baseline: Baseline) -> str:
    """The one sentence the athlete reads. Style-aware, because the honest
    answer to the same date is different for the two questions."""
    label = verdict.label
    when = f"{verdict.target_date:%-d %B}"

    if verdict.style == "run_walk":
        pace = _mmss(verdict.blended_pace_s_per_km)
        takes = (
            f"about {verdict.session_s / 60:.0f} minutes on your feet at "
            f"{pace}/km including the walk breaks"
        )
        if verdict.achievable:
            return (
                f"{label} by {when} is realistic. It is {takes}, and the ramp has "
                f"your long run covering {verdict.reaches_m / 1000:.1f} km by then "
                f"against the {verdict.target_distance_km:g} it needs."
            )
        if verdict.earliest_date:
            return (
                f"{label} by {when} is not realistic from where you are. It is "
                f"{takes}, and by that date the ramp has your long run covering "
                f"{verdict.reaches_m / 1000:.1f} km. "
                f"{verdict.earliest_date:%-d %B %Y} is the honest date — this plan "
                "builds toward it, and the date can move once you are further along."
            )
        return (
            f"{label} is a long way from {baseline.run_km_per_week:g} km a week. "
            "The plan below builds the volume that gets you there; the date is "
            "worth setting once it is bigger."
        )

    if verdict.achievable:
        return (
            f"{label} by {when} is realistic: the ramp reaches "
            f"{verdict.reaches_s / 60:.0f} minutes of continuous running against "
            f"the {verdict.needs_s / 60:.0f} it needs at your pace."
        )
    if verdict.earliest_date:
        return (
            f"{label} by {when} is not realistic from where you are. It needs "
            f"{verdict.needs_s / 60:.0f} minutes of continuous running and the ramp "
            f"reaches {verdict.reaches_s / 60:.0f} by then. "
            f"{verdict.earliest_date:%-d %B %Y} is the honest date — this plan "
            "builds toward it, and the date can move once you are further along."
        )
    return (
        f"{label} is a long way from a {baseline.longest_run_s / 60:.0f}"
        "-minute unbroken run, and the long run stops progressing at "
        f"{CONTINUOUS_CEILING_MIN:.0f} minutes, so there is no date to give you. "
        "Walk breaks would make it reachable — ask for the same distance with "
        "breaks and you will get a date."
    )


def generate_goal(
    plan_start: dt.date,
    target_date: dt.date,
    target_distance_km: float,
    baseline: Baseline,
    config: PlanConfig | None = None,
    style: GoalStyle = "nonstop",
) -> tuple[Plan, Feasibility]:
    """A dated plan toward covering a distance, with no race ceremony.

    The plan is built for the weeks available either way. When the date is not
    achievable the plan is still returned — the training is the same training —
    but the warning says so plainly and names the date that would work, because
    an athlete who is told "no" and nothing else just picks another number.

    The two styles differ in the plan as well as the verdict. A run-walk goal
    raises the volume ceiling to the weekly running the long run needs, because
    the milestone ladder would otherwise stop the ramp short of a distance the
    athlete asked for in as many words.
    """
    config = config or PlanConfig()
    verdict = assess_goal(
        plan_start, target_date, target_distance_km, baseline, config, style=style,
    )
    weeks = max(verdict.weeks_available, 4)

    plan = generate_practice(
        plan_start, baseline, config, weeks=weeks,
        min_peak_run_km=verdict.peak_run_km_needed or None,
    )

    warnings = [_goal_warning(verdict, baseline), *plan.warnings[1:]]
    if verdict.style == "run_walk" and verdict.session_s >= LONG_SESSION_WARN_S:
        warnings.insert(1, (
            f"Worth knowing: at your pace that is {verdict.session_s / 3600:.1f} "
            "hours of run-walking in one go. That is a day out rather than a "
            "training session — covering the distance faster, by running more of "
            "it, is usually the better goal."
        ))

    plan = replace(
        plan,
        warnings=warnings,
        # Only meaningful for a non-stop goal: it is the continuous curve's
        # yardstick. A run-walk goal leaves the milestone ladder in place,
        # because the unbroken block still progresses underneath it.
        race_needs_continuous_s=(
            verdict.needs_s if verdict.style == "nonstop" else plan.race_needs_continuous_s
        ),
    )
    return plan, verdict
