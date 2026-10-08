"""Post-run recovery routine (R17 §1): a 5–8 minute cool-down walk + stretch set matched
to the run. Pure.

Never stretch into pain: a spot reported at severity 1 gets a softened (shorter, gentler)
stretch; severity 2 or more skips every stretch and roll that loads it. Foam rolling is
always optional and comes last.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MIN_S, MAX_S = 300, 480
LONG_S = 60 * 60
QUAD_FROM_S = 30 * 60
HILLY_M_PER_KM = 15.0
HARD_KINDS = ("INTERVALS", "TEMPO", "RACE")
HARD_SHARE = 0.20
LOW_CADENCE = 160.0
HIGH_GCT_MS = 280.0

# key -> (title, seconds, per_side, cue, figure, area)
CATALOGUE: dict[str, tuple[str, int, bool, str, str, str | None]] = {
    "cooldown_walk": ("Easy cool-down walk", 150, False,
                      "Walk slowly and let your breathing settle.", "walk", None),
    "calf_stretch": ("Calf stretch", 30, True,
                     "Hands on a wall, back leg straight, heel down. Lean in gently.",
                     "calf", "calf"),
    "hamstring_stretch": ("Hamstring stretch", 30, True,
                          "Heel forward on the ground, hinge at the hips, back flat.",
                          "hamstring", "hamstring"),
    "quad_stretch": ("Quad stretch", 30, True,
                     "Hold your ankle behind you, knees together, hips pushed forward.",
                     "quad", "quad"),
    "hip_flexor_stretch": ("Hip flexor stretch", 30, True,
                           "Half-kneel, tuck your tailbone, shift your hips forward.",
                           "hip_flexor", "hip"),
    "glute_stretch": ("Glute / piriformis stretch", 30, True,
                      "Lying down, ankle over the other knee, pull the leg towards you.",
                      "glute", "glute"),
    "it_band_stretch": ("Hip and IT band stretch", 30, True,
                        "Cross one leg behind the other and lean your hips to the side.",
                        "it_band", "hip"),
    "adductor_stretch": ("Inner thigh stretch", 40, False,
                         "Sit, soles of the feet together, let your knees drop.",
                         "adductor", "adductor"),
    "lower_back_stretch": ("Lower back release", 40, False,
                           "On your back, hug both knees to your chest and breathe.",
                           "lower_back", "lower_back"),
    "calf_roll": ("Foam roll: calves", 45, True,
                  "Slow rolls from ankle to knee; pause on tight spots, never on pain.",
                  "calf_roll", "calf"),
    "hamstring_roll": ("Foam roll: hamstrings", 45, True,
                       "Roll from the knee to the sit bone, slowly.", "hamstring_roll",
                       "hamstring"),
    "quad_roll": ("Foam roll: quads", 45, True,
                  "Face down, roll from above the knee to the hip.", "quad_roll", "quad"),
    "it_band_roll": ("Foam roll: outer thigh", 45, True,
                     "On your side, roll the outer thigh gently — ease off if it bites.",
                     "it_band_roll", "hip"),
    "glute_roll": ("Foam roll: glutes", 45, True,
                   "Sit on the roller, ankle over knee, lean into that side.",
                   "glute_roll", "glute"),
}
STRETCH_ORDER = ["calf_stretch", "hamstring_stretch", "quad_stretch", "hip_flexor_stretch",
                 "glute_stretch", "it_band_stretch", "adductor_stretch", "lower_back_stretch"]
ROLL_ORDER = ["calf_roll", "quad_roll", "hamstring_roll", "it_band_roll", "glute_roll"]
# Dropped first when the routine runs long.
DROP_ORDER = ["lower_back_stretch", "adductor_stretch", "it_band_stretch", "glute_stretch",
              "quad_stretch"]
FILL_ORDER = ["quad_stretch", "glute_stretch", "lower_back_stretch", "adductor_stretch"]

# Pain location (R13 §3) -> the stretch areas that load it.
PAIN_AREAS = {
    "foot": {"calf"}, "ankle": {"calf"}, "shin": {"calf"}, "calf": {"calf"},
    "knee": {"quad", "hip"}, "hamstring": {"hamstring"}, "quad": {"quad"},
    "hip": {"hip", "glute", "adductor"}, "lower_back": {"lower_back", "hamstring"},
}
AREA_LABEL = {"calf": "calf", "hamstring": "hamstring", "quad": "quad", "hip": "hip",
              "glute": "glute", "adductor": "inner thigh", "lower_back": "lower back"}
PAIN_LABEL = {"foot": "Foot", "ankle": "Ankle", "shin": "Shin", "calf": "Calf",
              "knee": "Knee", "hamstring": "Hamstring", "quad": "Quad", "hip": "Hip",
              "lower_back": "Lower back"}
NOTE = "Ease into each stretch — mild tension, never pain."


@dataclass
class RoutineInputs:
    duration_s: float                       # moving time
    distance_m: float = 0.0
    kind: str | None = None                 # planned kind, else None
    elevation_gain_m: float | None = None
    hard_share: float | None = None         # share of HR time in Z4–Z5
    cadence_spm: float | None = None
    ground_contact_ms: float | None = None
    pains: list[tuple[str, str, int]] = field(default_factory=list)   # (location, side, severity)
    injury_risk: str = "low"


@dataclass
class Routine:
    minutes: int
    total_s: int
    reason: str
    focus: list[str]
    steps: list[dict]
    avoided: list[dict]
    notes: list[str]


def _step(key: str, seconds: int | None = None, *, softened=False, optional=False) -> dict:
    title, default, per_side, cue, figure, area = CATALOGUE[key]
    s = seconds if seconds is not None else default
    if softened:
        s = max(15, s // 2)
        cue = "Gently — only to light tension. " + cue
    return {"key": key, "title": title, "seconds": int(s), "per_side": per_side,
            "cue": cue, "figure": figure, "optional": optional, "softened": softened,
            "area": area}


def _cost(step: dict) -> int:
    return step["seconds"] * (2 if step["per_side"] else 1)


def build(inp: RoutineInputs) -> Routine:
    minutes_run = inp.duration_s / 60
    km = inp.distance_m / 1000 if inp.distance_m else 0
    hilly = bool(inp.elevation_gain_m and km >= 1
                 and inp.elevation_gain_m / km >= HILLY_M_PER_KM)
    long_run = inp.duration_s >= LONG_S or (inp.kind == "LONG")
    hard = (inp.kind in HARD_KINDS) or bool(inp.hard_share and inp.hard_share >= HARD_SHARE)
    cadence_flag = bool(inp.cadence_spm and inp.cadence_spm < LOW_CADENCE)
    gct_flag = bool(inp.ground_contact_ms and inp.ground_contact_ms > HIGH_GCT_MS)

    focus: list[str] = []
    for flag, name in ((long_run, "long"), (hard, "hard"), (hilly, "hills"),
                       (cadence_flag, "cadence"), (gct_flag, "ground_contact")):
        if flag:
            focus.append(name)

    # Pain: worst severity per stretch area.
    sore: dict[str, int] = {}
    sore_from: dict[str, str] = {}
    for location, side, severity in inp.pains:
        for area in PAIN_AREAS.get(location, set()):
            if severity > sore.get(area, 0):
                sore[area] = severity
                side_txt = f" ({side})" if side and side not in ("center", "both") else ""
                sore_from[area] = f"{PAIN_LABEL.get(location, location.title())}{side_txt}"
    if sore:
        focus.append("pain")
    injury_watch = inp.injury_risk in ("moderate", "high")
    if injury_watch:
        focus.append("injury_watch")

    holds: dict[str, int] = {k: CATALOGUE[k][1] for k in CATALOGUE}
    wanted = ["calf_stretch", "hamstring_stretch", "hip_flexor_stretch"]
    if inp.duration_s >= QUAD_FROM_S or hilly or hard:
        wanted.append("quad_stretch")
    if long_run:
        wanted += ["glute_stretch", "lower_back_stretch"]
    if hard:
        wanted += ["adductor_stretch", "it_band_stretch"]
    if hilly:
        holds["calf_stretch"] += 15
        holds["quad_stretch"] += 15
    if cadence_flag or gct_flag:
        holds["calf_stretch"] += 10
    holds["cooldown_walk"] = 180 if (long_run or hard) else 150

    avoided: list[dict] = []
    soft: set[str] = set()

    def allowed(key: str) -> bool:
        area = CATALOGUE[key][5]
        if area is None:
            return True
        level = sore.get(area, 0)
        if level >= 2:
            return False
        if level == 1 or (injury_watch and area in sore):
            soft.add(key)
        return True

    for key in STRETCH_ORDER:
        if key in wanted and not allowed(key):
            area = CATALOGUE[key][5]
            avoided.append({"area": area, "text": f"{sore_from[area]}: skipped the "
                            f"{CATALOGUE[key][0].lower()} — never stretch into pain."})
    stretches = [k for k in STRETCH_ORDER if k in wanted and k not in
                 {a for a in STRETCH_ORDER if CATALOGUE[a][5] in sore
                  and sore[CATALOGUE[a][5]] >= 2}]

    def steps_for(keys, walk_s):
        out = [_step("cooldown_walk", walk_s)]
        for k in keys:
            out.append(_step(k, holds[k], softened=k in soft))
        return out

    walk_s = holds["cooldown_walk"]
    steps = steps_for(stretches, walk_s)
    total = sum(_cost(s) for s in steps)
    for key in DROP_ORDER:
        if total <= MAX_S:
            break
        if key in stretches:
            stretches.remove(key)
            steps = steps_for(stretches, walk_s)
            total = sum(_cost(s) for s in steps)
    if total > MAX_S:
        walk_s = 120
        steps = steps_for(stretches, walk_s)
        total = sum(_cost(s) for s in steps)
    for key in FILL_ORDER:
        if total >= MIN_S:
            break
        if key not in stretches and allowed(key) and not (
                CATALOGUE[key][5] in sore and sore[CATALOGUE[key][5]] >= 2):
            stretches.append(key)
            stretches.sort(key=STRETCH_ORDER.index)
            steps = steps_for(stretches, walk_s)
            total = sum(_cost(s) for s in steps)
    while total < MIN_S and walk_s < 240:
        walk_s += 30
        steps = steps_for(stretches, walk_s)
        total = sum(_cost(s) for s in steps)

    # Optional foam rolling, never on a sore area.
    rolls = ["calf_roll"]
    if hilly or hard:
        rolls.append("quad_roll")
    if long_run:
        rolls += ["hamstring_roll", "glute_roll"]
    if hard:
        rolls.append("it_band_roll")
    for key in ROLL_ORDER:
        if key in rolls and CATALOGUE[key][5] not in sore:
            steps.append(_step(key, optional=True))

    minutes = max(5, min(8, round(total / 60)))
    return Routine(minutes=minutes, total_s=int(total),
                   reason=_reason(minutes_run, inp.kind, focus, hilly, long_run, hard,
                                  cadence_flag or gct_flag, bool(sore)),
                   focus=focus, steps=steps, avoided=avoided,
                   notes=[NOTE] + (["Pain that changes how you move is a reason to rest "
                                     "and get it checked."] if sore else []))


def _reason(minutes_run, kind, focus, hilly, long_run, hard, form, sore) -> str:
    words = []
    if hilly:
        words.append("Hilly")
    label = {"LONG": "long run", "INTERVALS": "interval session", "TEMPO": "tempo run",
             "RACE": "race", "RUN_WALK": "run/walk", "EASY": "easy run"}.get(kind or "", "run")
    words.append(f"{round(minutes_run)}-min {label}")
    head = " ".join(words)
    head = head[0].upper() + head[1:]
    extras = []
    if hilly:
        extras.append("extra calf and quad time")
    if long_run:
        extras.append("glutes and lower back after the long effort")
    if hard:
        extras.append("hips and inner thighs after the hard work")
    if form:
        extras.append("a longer calf hold")
    if sore:
        extras.append("gentler around the sore spot")
    if not extras:
        extras.append("the basics to loosen up")
    return f"{head} — {', '.join(extras)}."


def recovery_streak(run_done: list[bool]) -> tuple[int, int]:
    """(current, best) runs in a row with the routine done, oldest first. Runs before
    the first routine ever done do not count (the feature did not exist for them)."""
    try:
        start = run_done.index(True)
    except ValueError:
        return 0, 0
    current = best = 0
    for done in run_done[start:]:
        current = current + 1 if done else 0
        best = max(best, current)
    return current, best


def streak_reached(run_done: list[tuple[object, bool]], targets: list[int]) -> dict:
    """{target: the date of the run that reached it} — run_done = [(date, done)]."""
    reached: dict = {}
    started = False
    run = 0
    for day, done in run_done:
        if done:
            started = True
        if not started:
            continue
        run = run + 1 if done else 0
        for t in targets:
            if run >= t and t not in reached:
                reached[t] = day
    return reached
