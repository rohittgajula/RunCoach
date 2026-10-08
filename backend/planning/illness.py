"""Illness mode (R17 §10): advice and the return-to-run block. Pure.

Safety only ever makes training easier: a return session sits only on a day the paused
plan already had a run, is never longer than that day's planned session, and carries a
lower heart-rate cap than the plan's easy band. Wording is plain and non-medical.

Return rules (days_off = recovery date − start date):
* short   — off ≤ 3 days, no fever, symptoms above the neck: 2 sessions (≤ 1 day off) or
            3, at 50 / 60 / 70 % of the usual duration.
* week    — 4–7 days, no fever, above the neck: one easy week, 50 / 60 / 70 / 80 %.
* rebuild — > 7 days, or fever, or below the neck: 7 days (14 when > 14 days off, or
            fever with > 7 days off). Week one run/walk (2 min run / 1 min walk) at
            40 / 50 / 60 %; week two easy at 60 / 70 / 80 %.
Injury: the same rules by days, the first two sessions run/walk.
The block starts the day after recovery — two days after with fever or below-the-neck
symptoms (symptom-free for 24–48 h first).
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass, field

from analysis.load import session_load

TYPES = {"cold": "Cold", "flu": "Fever / flu", "stomach": "Stomach bug",
         "injury": "Injury", "other": "Other"}
SYMPTOMS = ("above_neck", "below_neck")
DEFAULT_USUAL_S = 30 * 60
MIN_SESSION_S = 10 * 60
RACE_WARN_DAYS = 14
SHORT_SEARCH_DAYS = 10
CAP_FIRST = 10
CAP_LATER = 5
WARM_S = 180
COOL_S = 180
RW_RUN_S, RW_WALK_S = 120, 60


@dataclass
class PlanDay:
    """A paused run workout of the plan (the slot a return session may use)."""
    date: dt.date
    duration_s: int
    workout_id: int | None = None
    hr_cap: int | None = None          # the plan's own cap that day (top of its HR band)


@dataclass
class Session:
    date: dt.date
    kind: str                           # EASY | RUN_WALK
    duration_s: int
    pct_of_usual: int
    hr_cap: int | None
    replaces: int | None                # the paused workout id on that date
    title: str = ""
    steps: list[dict] = field(default_factory=list)
    load: float = 0.0
    description: str = ""


@dataclass
class Block:
    rule: str
    label: str
    start: dt.date
    end: dt.date
    resumes_on: dt.date
    sessions: list[Session]
    usual_duration_s: int
    note: str


def label_for(kind: str) -> str:
    return TYPES.get(kind, "Other")


def severe(kind: str, symptoms: str, fever: bool) -> bool:
    return fever or symptoms == "below_neck" or kind == "flu"


def advice(kind: str, symptoms: str, fever: bool) -> tuple[list[str], list[str]]:
    """(advice, see_doctor) — general wellbeing guidance, never a diagnosis."""
    tips: list[str] = []
    if kind == "injury":
        tips.append("Rest the sore area; no running while it hurts to walk or changes how "
                    "you move.")
        tips.append("Gentle movement that doesn't hurt is fine.")
        doctor = ["See a doctor or physio if the pain is sharp, swollen, getting worse, or "
                  "not easing after a few days."]
        return tips, doctor
    if severe(kind, symptoms, fever):
        tips.append("No running for now. Wait until you've been symptom-free for 24–48 "
                    "hours (no fever without medicine) before your first easy session.")
    else:
        tips.append("Rest is the quickest way back. When you start again, keep it short "
                    "and easy.")
    if kind == "stomach":
        tips.append("Sip fluids often and add electrolytes; eat plain food as you can.")
    else:
        tips.append("Sleep, fluids and easy days help most.")
    tips.append("Your plan is paused — no workouts on your watch until you're better.")
    doctor = ["See a doctor if you have a high or lasting fever, chest pain, trouble "
              "breathing, a racing heart at rest, or you're not improving after a week."]
    if kind == "stomach":
        doctor.append("See a doctor if you can't keep fluids down or feel dizzy when "
                      "standing.")
    return tips, doctor


def usual_duration(recent_runs_s: list[float], paused_runs_s: list[float]) -> int:
    """Median of the runs in the 28 days before the illness (≥ 2), else of the paused
    run workouts, else 30 min."""
    runs = [r for r in recent_runs_s if r and r > 0]
    if len(runs) >= 2:
        return int(statistics.median(runs))
    paused = [r for r in paused_runs_s if r and r > 0]
    if paused:
        return int(statistics.median(paused))
    return DEFAULT_USUAL_S


def choose_rule(kind: str, symptoms: str, fever: bool, days_off: int) -> tuple[str, int]:
    """(rule, block days; 0 = by session count)."""
    if days_off > 7 or severe(kind, symptoms, fever):
        long_block = days_off > 14 or ((fever or kind == "flu") and days_off > 7)
        return "rebuild", 14 if long_block else 7
    if days_off >= 4:
        return "week", 7
    return "short", 0


def _round_min(seconds: float) -> int:
    return int(round(seconds / 60)) * 60


def _steps(kind: str, duration_s: int, easy_low: int | None, cap: int | None,
           easy_pace: tuple[int, int] | None) -> list[dict]:
    def step(k, s, intensity, label):
        run = intensity != "walk"
        return {"kind": k, "duration_s": int(s), "intensity": intensity, "label": label,
                "pace_min_s": easy_pace[0] if run and easy_pace else None,
                "pace_max_s": easy_pace[1] if run and easy_pace else None,
                "hr_min": (min(easy_low, cap - 10) if easy_low and cap else easy_low)
                if run else None,
                "hr_max": cap if run else None}

    warm = WARM_S if duration_s >= 15 * 60 else 120
    cool = COOL_S if duration_s >= 15 * 60 else 120
    middle = max(60, duration_s - warm - cool)
    out = [step("warmup", warm, "walk", "Walk warm-up")]
    if kind == "RUN_WALK":
        left = middle
        while left > 0:
            run = min(RW_RUN_S, left)
            out.append(step("run", run, "easy", f"Run {run // 60}:{run % 60:02d}"))
            left -= run
            if left > 0:
                walk = min(RW_WALK_S, left)
                out.append(step("walk", walk, "walk", f"Walk {walk // 60}:{walk % 60:02d}"))
                left -= walk
    else:
        out.append(step("run", middle, "easy", f"Easy run {middle // 60}:{middle % 60:02d}"))
    out.append(step("cooldown", cool, "walk", "Walk cool-down"))
    return out


def return_block(*, kind: str, symptoms: str, fever: bool, start_date: dt.date,
                 recovered_on: dt.date, usual_s: int, plan_days: list[PlanDay] | None,
                 free_dates: list[dt.date] | None = None, easy_low: int | None = None,
                 easy_top: int | None = None,
                 easy_pace: tuple[int, int] | None = None) -> Block:
    """plan_days: the paused plan's run workouts from the day after recovery (None = no
    active plan; then `free_dates` — the athlete's available days — are used)."""
    days_off = max(0, (recovered_on - start_date).days)
    rule, block_days = choose_rule(kind, symptoms, fever, days_off)
    gap = 2 if severe(kind, symptoms, fever) else 1
    start = recovered_on + dt.timedelta(days=gap)

    if plan_days is not None:
        slots = sorted((d for d in plan_days if d.date >= start), key=lambda d: d.date)
    else:
        slots = [PlanDay(date=d, duration_s=10 ** 6) for d in sorted(free_dates or [])
                 if d >= start]

    if rule == "short":
        count = 2 if days_off <= 1 else 3
        horizon = start + dt.timedelta(days=SHORT_SEARCH_DAYS - 1)
        chosen = [s for s in slots if s.date <= horizon][:count]
        pcts = [50, 60, 70][:count]
        end = chosen[-1].date if chosen else start
        label = f"{count} easy sessions"
    else:
        end = start + dt.timedelta(days=block_days - 1)
        chosen = [s for s in slots if s.date <= end]
        if plan_days is None:
            # Without a plan: at most 4 sessions a week, never two days running.
            picked, last = [], None
            for s in chosen:
                week = (s.date - start).days // 7
                if sum(1 for p in picked if (p.date - start).days // 7 == week) >= 4:
                    continue
                if last is not None and (s.date - last).days < 2:
                    continue
                picked.append(s)
                last = s.date
            chosen = picked
        if rule == "week":
            pcts = [min(80, 50 + 10 * i) for i in range(len(chosen))]
            label = "One easy week"
        else:
            pcts = []
            for s in chosen:
                week = (s.date - start).days // 7
                index = sum(1 for c in chosen if c.date < s.date
                            and (c.date - start).days // 7 == week)
                base = [40, 50, 60] if week == 0 else [60, 70, 80]
                pcts.append(base[min(index, 2)])
            label = "2-week rebuild" if block_days == 14 else "1-week rebuild"

    sessions: list[Session] = []
    for i, (slot, pct) in enumerate(zip(chosen, pcts)):
        if rule == "rebuild":
            week = (slot.date - start).days // 7
            s_kind = "RUN_WALK" if week == 0 else "EASY"
        else:
            s_kind = "EASY"
        if kind == "injury" and i < 2:
            s_kind = "RUN_WALK"
        duration = _round_min(min(pct / 100 * usual_s, slot.duration_s))
        duration = max(MIN_SESSION_S, duration)
        duration = min(duration, max(MIN_SESSION_S, _round_min(slot.duration_s)))
        caps = [c for c in (easy_top - (CAP_FIRST if i < 2 else CAP_LATER)
                            if easy_top else None, slot.hr_cap) if c]
        cap = min(caps) if caps else None
        steps = _steps(s_kind, duration, easy_low, cap, easy_pace)
        run_min = sum(st["duration_s"] for st in steps if st["intensity"] != "walk") / 60
        walk_min = sum(st["duration_s"] for st in steps if st["intensity"] == "walk") / 60
        minutes = duration // 60
        title = (f"Return: {minutes}m run/walk" if s_kind == "RUN_WALK"
                 else f"Return: {minutes}m easy run")
        cap_txt = f" Keep your heart rate under {cap} bpm." if cap else ""
        sessions.append(Session(
            date=slot.date, kind=s_kind, duration_s=sum(st["duration_s"] for st in steps),
            pct_of_usual=pct, hr_cap=cap, replaces=slot.workout_id, title=title,
            steps=steps, load=session_load(run_min, walk_min),
            description=(f"Back after being unwell: {pct}% of your usual session, all "
                         f"easy.{cap_txt} Stop and walk if anything feels off."
                         + (" Stop if it hurts." if kind == "injury" else ""))))

    if rule == "short":
        end = sessions[-1].date if sessions else start
    resumes = end + dt.timedelta(days=1)
    note = ("Short and easy first — the plan picks up again on "
            f"{resumes.strftime('%a %-d %b')}.")
    if severe(kind, symptoms, fever):
        note = ("Wait until you've been symptom-free for 24–48 hours. " + note)
    return Block(rule=rule, label=label, start=start, end=end, resumes_on=resumes,
                 sessions=sessions, usual_duration_s=int(usual_s), note=note)


def race_warning(races: list[tuple[int, str, dt.date]], block: Block) -> dict | None:
    """The nearest race inside the block or ≤ 14 days after it resumes."""
    for race_id, name, day in sorted(races, key=lambda r: r[2]):
        if day < block.start:
            continue
        if day < block.resumes_on:
            return {"race_id": race_id, "name": name, "date": day, "days_after_block": 0,
                    "text": f"{name} falls inside your return block. Consider moving it, "
                            f"or run it very easy (or not at all)."}
        after = (day - block.resumes_on).days
        if after <= RACE_WARN_DAYS:
            return {"race_id": race_id, "name": name, "date": day,
                    "days_after_block": after,
                    "text": f"{name} is {after} days after your return block ends — "
                            f"little time to rebuild. Consider shifting it or running it "
                            f"easy."}
    return None


def block_dict(block: Block, statuses: dict[int, str] | None = None,
               ids: dict[dt.date, int] | None = None) -> dict:
    return {"rule": block.rule, "label": block.label, "start": block.start,
            "end": block.end, "resumes_on": block.resumes_on,
            "sessions": [{"workout_id": (ids or {}).get(s.date), "date": s.date,
                          "title": s.title, "kind": s.kind, "duration_s": s.duration_s,
                          "hr_cap": s.hr_cap, "pct_of_usual": s.pct_of_usual,
                          "status": (statuses or {}).get((ids or {}).get(s.date))}
                         for s in block.sessions],
            "usual_duration_s": block.usual_duration_s, "note": block.note}


def neutral_days(periods: list[tuple[dt.date, dt.date]]) -> set[dt.date]:
    """Every date inside the given (start, end) illness periods."""
    out: set[dt.date] = set()
    for start, end in periods:
        day = start
        while day <= end:
            out.add(day)
            day += dt.timedelta(days=1)
    return out
