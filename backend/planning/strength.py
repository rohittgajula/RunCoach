"""Strength sessions in the calendar (R13 §4). Pure — no Django.

`place()` decides which days get a 20-minute strength session; `session()` decides
what is in it. Rules:

* a non-run day first (a rest day or an optional walk day);
* only when there are not enough of those, after an easy run (EASY / RUN_WALK);
* never the day before a long run, a hard session (intervals, tempo) or the race, never
  on the race day or in the last 5 days before it, never on a long/hard day itself;
* never two days in a row, spread across the week;
* nothing in the past (today counts only when `include_today`).

The session itself is a **beginner gym programme**, not the prehab circuit it used
to be. Rohit is going to a gym for the first time and cannot do a single push-up,
and a circuit of calf raises and clamshells does not answer that: it has no push,
no pull, no squat worth the name, and nothing to add weight to.

Six movement patterns, five rungs each, and **each pattern climbs its own ladder**.
A single programme level forces one movement to be wrong — almost everybody can
squat long before they can press, and starting both at the same rung means one of
them is either pointless or impossible. Rung 1 is deliberately easy enough to be
boring: a wall push-up, a squat down onto a chair, a bridge on the floor. Failing
in week one is the most reliable way to stop going, so week one is built to be
passed.

What the old circuit got right is kept, inside the session rather than instead of
it: the calf work, the glute bridge and the single-leg squat are the three things
in here that most protect a beginner's running, which is why calf sits first.

On fat loss, the other stated goal: nothing in this file burns it in a way worth
planning around. Energy balance does that. What lifting does is hold onto muscle
while the deficit runs, so what is lost is fat rather than the legs needed to run.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

#: Five minutes of warm-up plus the lifting. Declared here with the other
#: constants; WARMUP_S is defined with the warm-up itself further down.
WARMUP_S = 5 * 60
DURATION_S = WARMUP_S + 35 * 60
MAX_PER_WEEK = 3
SUGGESTED_PER_WEEK = 2
LEVEL_EVERY_WEEKS = 2
# Five rungs, not six. The sixth existed to keep adding reps to a bodyweight
# circuit; a ladder tops out at a movement you keep and load instead.
MAX_LEVEL = 5
RACE_BUFFER_DAYS = 5

# Below this many weeks of training, sets stay at two and nothing goes near
# failure: connective tissue adapts to repetition long before it adapts to load,
# and it is tendons, not muscles, that end a beginner's build.
SETS_UPGRADE_LEVEL = 3

RUN_KINDS = frozenset({"EASY", "RUN_WALK", "LONG", "INTERVALS", "TEMPO", "RACE"})
DEMANDING = frozenset({"LONG", "INTERVALS", "TEMPO", "RACE"})
AFTER_RUN_OK = frozenset({"EASY", "RUN_WALK"})

# Six patterns, five rungs each. Order is the order they are done in: calf first
# because it is the tissue most likely to end the build and the one people skip
# when they run out of time, then the two big lower-body patterns while fresh,
# then push and pull, then core last because a tired trunk makes everything above
# it sloppy.
#
# Each rung: (name, reps | None, seconds | None, per_side, load, cue, graduate_when)
# Rungs are ordered by the demand they actually place. An incline push-up on a
# counter is roughly 40% of bodyweight and a knee push-up roughly 60%, which is
# the opposite of how the two are usually taught.
LADDERS: list[tuple[str, str, str, list[tuple]]] = [
    ("calf", "Calf", "Takes about eight times bodyweight per stride and strengthens slowly — "
     "it is what usually ends a beginner's build, not the lungs.", [
        ("Calf raise", 12, None, False, "Bodyweight, flat floor",
         "All the way up, two seconds down. The slow lowering is the part that works.",
         "25 reps without the heels stopping short."),
        ("Calf raise off a step", 12, None, False, "Bodyweight, heels hanging",
         "Heel below the step at the bottom, as high as it goes at the top.",
         "20 reps through the full range."),
        ("Single-leg calf raise", 10, None, True, "Bodyweight",
         "One leg at a time. Most people find a clear strong and weak side here.",
         "15 reps a side on the floor."),
        ("Single-leg calf raise off a step", 10, None, True, "Bodyweight, heel hanging",
         "Three seconds down on every rep.",
         "12 reps a side, full range, three-second lower."),
        ("Loaded single-leg calf raise", 10, None, True, "Holding a dumbbell",
         "Add weight slowly. This tissue adapts over months, not weeks.", "Stay here."),
    ]),
    ("squat", "Squat", "Quads and glutes absorb every landing. When they quit late in a run "
     "the knee takes what they stopped taking.", [
        ("Box squat", 10, None, False, "Bodyweight, onto a chair",
         "Sit back until you touch the chair, then stand. Chest up, knees over the toes.",
         "15 reps without pushing off your hands."),
        ("Bodyweight squat", 12, None, False, "Bodyweight",
         "No chair. As low as you can keep a flat back.",
         "15 reps with thighs reaching parallel."),
        ("Goblet squat", 10, None, False, "One dumbbell at the chest",
         "The weight at your chest is a counterweight — it lets you sit deeper, not shallower.",
         "12 reps with 12 kg, still controlled."),
        ("Split squat", 8, None, True, "Bodyweight, then dumbbells",
         "Back knee towards the floor, front shin near vertical.",
         "10 reps a side with 2x8 kg."),
        ("Bulgarian split squat", 8, None, True, "Dumbbells, rear foot on a bench",
         "The hardest single-leg movement here. Slow down, especially on the way down.",
         "Stay here and add weight."),
    ]),
    ("hinge", "Hinge", "Glutes and hamstrings drive you forward. Without them you run on "
     "quads alone, which is slower and harder on the knee.", [
        ("Glute bridge", 12, None, False, "Bodyweight, on the floor",
         "Drive through the heels, squeeze at the top, do not arch the lower back.",
         "20 reps felt in the glutes, not the lower back."),
        ("Hip hinge with a broomstick", 10, None, False, "Bodyweight",
         "Stick touching head, upper back and tailbone. Push the hips back, keep all three touching.",
         "15 clean reps with nothing losing contact."),
        ("Romanian deadlift", 10, None, False, "Light dumbbells",
         "Hips back, weights brushing the legs, stop when the hamstrings tighten. Not a squat.",
         "12 reps with 2x8 kg, back flat."),
        ("Single-leg Romanian deadlift", 8, None, True, "One light dumbbell",
         "Running is a single-leg sport, and this is where the balance for it comes from.",
         "10 reps a side without putting the free foot down."),
        ("Trap-bar deadlift", 8, None, False, "Barbell",
         "Have someone watch the first session. Everything else here is safe to learn alone.",
         "Stay here and progress by load."),
    ]),
    ("push", "Push", "Will not make you faster, but it holds your posture together in the "
     "last kilometre. When the trunk folds, breathing gets worse.", [
        ("Wall push-up", 12, None, False, "Hands on a wall",
         "Stand a long arm's length back. One line from head to heels — no sagging hips.",
         "20 easy reps with the body straight throughout."),
        ("Incline push-up on a counter", 10, None, False, "About 40% of bodyweight",
         "The lower the surface the harder it gets. This is the rung most people skip.",
         "15 reps with the chest touching."),
        ("Incline push-up on a bench", 10, None, False, "About 55% of bodyweight",
         "Elbows at about 45 degrees to the body, not flared out to the sides.",
         "12 reps, chest to the bench, no sagging."),
        ("Knee push-up", 10, None, False, "About 60% of bodyweight",
         "Knees, hips and shoulders in one line. Hips drifting back teaches nothing.",
         "12 reps with the chest within a fist of the floor."),
        ("Full push-up", 8, None, False, "Bodyweight",
         "From a standing start this usually takes two to four months. You will get here.",
         "Stay here and add reps."),
    ]),
    ("pull", "Pull", "Balances the pushing and stops the shoulders rolling forward — the "
     "posture that makes late-run breathing worse.", [
        ("Table row", 10, None, False, "Lying under a sturdy table",
         "Heels down, body straight, pull the chest to the edge. Walk the feet in to make it easier.",
         "12 reps with the chest reaching the table."),
        ("Seated cable row", 12, None, False, "Light",
         "Pull with the elbows, not the hands. Shoulder blades together at the end.",
         "15 reps without the torso rocking."),
        ("One-arm dumbbell row", 10, None, True, "One dumbbell, hand on a bench",
         "Shoulders square to the floor. Rotating turns it into a different exercise.",
         "12 reps a side with 10 kg."),
        ("Lat pulldown", 10, None, False, "Machine",
         "Bar to the collarbone, chest proud. Leaning a long way back makes it a row.",
         "10 reps at half bodyweight."),
        ("Assisted pull-up", 6, None, False, "Machine or band",
         "The long-term goal. Take the assistance off a little at a time.",
         "Stay here and reduce the assistance."),
    ]),
    ("core", "Core", "Not for the look of it. A trunk that cannot stay stiff lets the pelvis "
     "drop every stride, and that energy goes into wobbling instead of forward.", [
        ("Dead bug", 8, None, True, "Bodyweight",
         "Lower back pressed into the floor throughout. If it lifts, shorten the range.",
         "10 slow reps a side with the back staying down."),
        ("Front plank", None, 20, False, "Bodyweight",
         "Squeeze the glutes. A sagging plank is just hanging off the spine.",
         "A 45-second hold that is hard but not shaking."),
        ("Side plank", None, 20, True, "Bodyweight",
         "Hips stacked and lifted. This trains the muscle that stops the pelvis dropping.",
         "30 seconds a side."),
        ("Pallof press", 10, None, True, "Cable or band at chest height",
         "Press straight out and resist the twist. The point is the rotation that does not happen.",
         "12 reps a side with the hips square."),
        ("Hanging knee raise", 8, None, False, "Hanging from a bar",
         "Curl the pelvis up rather than just lifting the legs.", "Stay here."),
    ]),
]


# --- the warm-up --------------------------------------------------------------
#
# These are the drills the old circuit was made of — A-skips, leg swings, the
# clamshell, the hip-flexor stretch. Replacing that circuit with a strength
# programme left them out, and that was a loss: they were never much of a
# strength session, and they are a genuinely good warm-up. They come back here,
# doing the job they were always suited to.
#
# A warm-up before lifting is not optional for somebody whose tendons have never
# been loaded. It is also the part people skip, so it is short, it is specific,
# and nothing in it needs equipment or floor space.
#
# Ordered deliberately: pulse first so the rest happens warm, then the joints
# that are about to be asked for range, then one drill that rehearses the
# pattern of the session itself.

WARMUP: tuple[tuple[str, str, int | None, int | None, bool, str], ...] = (
    # key, name, reps | None, seconds | None, per_side, cue
    ("march", "March on the spot", None, 60, False,
     "Knees to hip height, arms swinging. Just get warm — this is not training."),
    ("legswing", "Leg swings", 10, None, True,
     "Forwards and back, then side to side. Hold a wall. Loose, not forced."),
    ("anklerock", "Ankle rocks", 10, None, True,
     "Knee forward over the toes, heel down. The joint that limits a squat most."),
    ("clam", "Clamshell", 12, None, True,
     "Heels together, open the top knee, don't roll back. Wakes the glute up."),
    ("hipflexor", "Hip-flexor stretch", None, 20, True,
     "Tuck the pelvis, then push the hips forward. Sitting all day shortens these."),
    ("askip", "A-skip", None, 20, False,
     "Knee to hip height, land under you, quick and light. Rehearses the stride."),
)


def warmup_block() -> list[dict]:
    """The warm-up, as the same shape the session's exercises use.

    Same shape on purpose: the screen renders one list, and a warm-up that
    needed its own renderer would be the first thing to fall out of step with
    the rest of the session.
    """
    return [
        {
            "key": key, "pattern": "Warm-up", "name": name,
            "sets": 1, "reps": reps, "seconds": seconds, "per_side": per_side,
            "rest_s": 0, "load": "Bodyweight", "cue": cue,
            "why": "Warm tissue tolerates load; cold tissue tears. Five minutes.",
            "level": 1, "max_level": 1, "ceiling": 1, "at_ceiling": False,
            "graduate_when": "", "is_warmup": True,
        }
        for key, name, reps, seconds, per_side, cue in WARMUP
    ]


PATTERNS: tuple[str, ...] = tuple(key for key, _, _, _ in LADDERS)

# How far up each ladder you can climb with what you actually have.
#
# This is why the ladders are the right shape: "bodyweight only" is not a
# separate programme or a mode to maintain, it is a ceiling on an existing one.
# Every rung 1 is bodyweight, so a beginner with nothing starts in exactly the
# same place as one with a full gym — they just stop climbing sooner.
#
# The consequence that matters: nothing can prescribe a goblet squat before the
# athlete has said they have a dumbbell. The alternative, prescribing it and
# hoping they improvise, is how a plan loses someone in week five.
EQUIPMENT: tuple[str, ...] = ("bodyweight", "dumbbells", "gym")

EQUIPMENT_CEILING: dict[str, dict[str, int]] = {
    # A table, a wall and a chair. Pull is the limited one — there is no way to
    # train a horizontal pull without something to hang under, and a table row
    # is genuinely the whole answer until there is.
    "bodyweight": {"calf": 4, "squat": 2, "hinge": 2, "push": 5, "pull": 1, "core": 3},
    # A pair of dumbbells covers most of it. Barbell deadlifts and the machines
    # stay out of reach, which is correct: both want a gym and one wants a coach.
    "dumbbells": {"calf": 5, "squat": 5, "hinge": 4, "push": 5, "pull": 3, "core": 3},
    # Everything.
    "gym": {},
}


def ceiling_for(equipment: str, pattern: str) -> int:
    return EQUIPMENT_CEILING.get(equipment, {}).get(pattern, MAX_LEVEL)


def cap_levels(levels: dict[str, int], equipment: str) -> dict[str, int]:
    """Hold each pattern at what the available equipment can actually do.

    Capped rather than refused: somebody who reaches the top of what a table and
    a chair allow should keep training there, not be told to stop. The cap is
    also the natural prompt to change the setting — "you are at the top of this
    one" is a better nudge than a toggle buried in settings.
    """
    return {
        key: max(1, min(int(levels.get(key, 1)), ceiling_for(equipment, key)))
        for key in PATTERNS
    }

REST_S = 30


@dataclass(frozen=True)
class Day:
    date: dt.date
    kinds: tuple[str, ...] = ()      # planned kinds that day (not skipped)


def level_for(start: dt.date, day: dt.date) -> int:
    weeks = max((day - start).days, 0) // 7
    return min(1 + weeks // LEVEL_EVERY_WEEKS, MAX_LEVEL)


def exercises(level: int, levels: dict[str, int] | None = None,
              equipment: str = "gym") -> list[dict]:
    """The session, one entry per movement pattern.

    `level` is the programme's own clock — how long this athlete has been
    training. `levels` overrides it per pattern, which is the point of the
    ladders: somebody doing bodyweight squats comfortably may still be on wall
    push-ups, and one number cannot say both.
    """
    level = max(1, min(level, MAX_LEVEL))
    sets = 2 if level < SETS_UPGRADE_LEVEL else 3
    levels = levels or {}
    out: list[dict] = []

    for key, label, why, rungs in LADDERS:
        rung = max(1, min(int(levels.get(key, level)), MAX_LEVEL))
        # What you have beats where the programme thinks you are.
        rung = min(rung, ceiling_for(equipment, key))
        name, reps, seconds, per_side, load, cue, graduate = rungs[rung - 1]
        out.append({
            "key": key,
            "pattern": label,
            "name": name,
            "sets": sets,
            "reps": reps,
            "seconds": seconds,
            "per_side": per_side,
            "rest_s": REST_S,
            "load": load,
            "cue": cue,
            "why": why,
            "level": rung,
            "max_level": MAX_LEVEL,
            "ceiling": ceiling_for(equipment, key),
            "at_ceiling": rung >= ceiling_for(equipment, key) < MAX_LEVEL,
            "graduate_when": graduate,
        })
    # The warm-up leads the list. It is the part people skip, and burying it
    # under six lifts is how it gets skipped.
    return warmup_block() + out


def ladders() -> list[dict]:
    """Every rung of every pattern, for the screen that shows where you stand."""
    return [
        {
            "key": key, "pattern": label, "why": why, "max_level": MAX_LEVEL,
            "steps": [
                {"name": r[0], "load": r[4], "graduate_when": r[6]} for r in rungs
            ],
        }
        for key, label, why, rungs in LADDERS
    ]


def rung_name(pattern: str, level: int) -> str:
    """The movement one rung of one pattern prescribes.

    LADDERS is a list of tuples here, so a caller that wants "what is squat at
    rung 3" has to walk it. Doing that at the call site is how a `[pattern]`
    lookup written from memory ends up shipping against the wrong shape.
    """
    level = max(1, min(int(level), MAX_LEVEL))
    for key, _label, _why, rungs in LADDERS:
        if key == pattern:
            return rungs[level - 1][0]
    return pattern


def graduate(levels: dict[str, int], pattern: str, direction: int = 1) -> dict[str, int]:
    """Move one pattern up or down its ladder. Returns a new dict."""
    out = dict(levels)
    current = max(1, min(int(out.get(pattern, 1)), MAX_LEVEL))
    out[pattern] = max(1, min(current + direction, MAX_LEVEL))
    return out


def default_levels() -> dict[str, int]:
    return {key: 1 for key in PATTERNS}


def title_for(level: int) -> str:
    return "Gym — full body" if level < SETS_UPGRADE_LEVEL else f"Gym — full body · level {level}"


def _blocked(days: dict[dt.date, Day], day: dt.date, race_date: dt.date | None) -> bool:
    kinds = set(days.get(day, Day(day)).kinds)
    tomorrow = set(days.get(day + dt.timedelta(days=1), Day(day)).kinds)
    if kinds & DEMANDING or tomorrow & DEMANDING:
        return True
    if race_date is not None and race_date - dt.timedelta(days=RACE_BUFFER_DAYS) <= day:
        return True
    return False


def _spread(candidates: list[dt.date], n: int, taken: list[dt.date]) -> list[dt.date]:
    """Pick up to n dates, never adjacent to each other or to `taken`, spread out:
    greedily take the candidate farthest from everything already chosen."""
    chosen = list(taken)
    picked: list[dt.date] = []
    pool = sorted(candidates)
    while len(picked) < n:
        options = [d for d in pool if all(abs((d - c).days) > 1 for c in chosen)]
        if not options:
            break
        if not chosen:
            best = options[0]
        else:
            best = max(options, key=lambda d: (min(abs((d - c).days) for c in chosen), -d.toordinal()))
        picked.append(best)
        chosen.append(best)
        pool.remove(best)
    return sorted(picked)


def place(days: list[Day], per_week: int, first_day: dt.date, last_day: dt.date,
          race_date: dt.date | None = None,
          gym_days: set[int] | None = None) -> list[tuple[dt.date, bool]]:
    """[(date, after_run)] for every ISO week touching first_day..last_day.

    `gym_days` is a set of weekday numbers (0 = Monday). When given, only those
    days are considered: an athlete who says Tuesday and Friday has a gym with
    opening hours and a commute, and the best-spaced day in the week is no use
    if they cannot get there. When empty the old behaviour stands and the
    spacing rules pick.

    The safety rules are not relaxed for a chosen day. A gym day the evening
    before the long run still gets skipped rather than wrecking tomorrow's legs
    — `_blocked` runs either way — which is the one case where the athlete's
    preference loses, and it loses to their own next run.
    """
    per_week = max(0, min(per_week, MAX_PER_WEEK))
    if per_week == 0 or last_day < first_day:
        return []
    by_date = {d.date: d for d in days}
    out: list[tuple[dt.date, bool]] = []
    week = first_day - dt.timedelta(days=first_day.weekday())
    while week <= last_day:
        dates = [week + dt.timedelta(days=i) for i in range(7)]
        dates = [d for d in dates if first_day <= d <= last_day]
        if gym_days:
            dates = [d for d in dates if d.weekday() in gym_days]
        free, after = [], []
        for day in dates:
            if _blocked(by_date, day, race_date):
                continue
            kinds = set(by_date.get(day, Day(day)).kinds)
            if not kinds & RUN_KINDS:
                free.append(day)
            elif kinds & RUN_KINDS <= AFTER_RUN_OK:
                after.append(day)
        picked = _spread(free, per_week, [])
        after_picked = _spread(after, per_week - len(picked), picked) \
            if len(picked) < per_week else []
        out += [(d, False) for d in picked] + [(d, True) for d in after_picked]
        week += dt.timedelta(days=7)
    return sorted(out)
