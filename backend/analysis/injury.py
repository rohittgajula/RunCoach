"""Injury watch (R13 §3): daily deterministic risk flags. Pure — no Django.

Flags are early warnings, never a diagnosis. Each one is a rule a coach would use:

* ramp — the last 7 days' running km more than 10 % over the 7 days before, **and** the
  acute:chronic load ratio over 1.3 (high when > 30 % and ACWR > 1.5);
* long_run_share — the longest run is more than 40 % of the last 7 days' km (≥ 2 runs);
* cadence_drop — the last 3 runs' cadence ≥ 5 spm under the 4-week baseline before them;
* gct_balance — ground-contact-time balance more than 2 % off 50/50 (mean of the last 5
  runs that have it; only watches with a running-dynamics sensor record it);
* shoe — the shoe in use is past its replace threshold;
* pain — the same spot ≥ 2/3 on two of the last 3 days (high with a 3).

Risk: high = any high flag or ≥ 3 flags; moderate = 1–2 flags; else low.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass

RAMP_PCT = 10.0
RAMP_HIGH_PCT = 30.0
ACWR_WATCH = 1.3
ACWR_HIGH = 1.5
MIN_PREVIOUS_KM = 3.0
LONG_SHARE = 0.40
CADENCE_DROP = 5.0
CADENCE_RECENT = 3
CADENCE_BASELINE_MIN = 3
GCT_OFF = 2.0
GCT_RUNS = 5
PAIN_MIN = 2
PAIN_WINDOW_DAYS = 3
PAIN_DAYS = 2

LOCATIONS = {"foot": "Foot", "ankle": "Ankle", "shin": "Shin", "calf": "Calf",
             "knee": "Knee", "hamstring": "Hamstring", "quad": "Quad", "hip": "Hip",
             "lower_back": "Lower back"}
SIDES = {"left": "left", "right": "right", "both": "both sides", "center": None}

NOTE = ("Early-warning flags from your own data — not a diagnosis. They only ever make "
        "the plan easier.")
PHYSIO = "If pain lasts more than a few days, gets worse or changes how you run, see a physio."


@dataclass(frozen=True)
class Run:
    date: dt.date
    km: float
    cadence: float | None = None
    gct_balance: float | None = None      # % left


@dataclass(frozen=True)
class Pain:
    date: dt.date
    location: str
    side: str
    severity: int


def spot_label(location: str, side: str) -> str:
    name = LOCATIONS.get(location, location.replace("_", " ").title())
    side_word = SIDES.get(side)
    return f"{name} ({side_word})" if side_word else name


def pain_signal(pains: list[Pain], today: dt.date) -> dict | None:
    """{status: watch|bad, label, location, side, days} for the worst repeated spot."""
    since = today - dt.timedelta(days=PAIN_WINDOW_DAYS - 1)
    spots: dict[tuple[str, str], dict[dt.date, int]] = {}
    for p in pains:
        if since <= p.date <= today and p.severity >= PAIN_MIN:
            days = spots.setdefault((p.location, p.side), {})
            days[p.date] = max(days.get(p.date, 0), p.severity)
    worst = None
    for (location, side), days in spots.items():
        if len(days) < PAIN_DAYS:
            continue
        status = "bad" if max(days.values()) >= 3 else "watch"
        candidate = {"status": status, "location": location, "side": side,
                     "days": len(days),
                     "label": f"{spot_label(location, side)} sore {len(days)} days",
                     "since": min(days)}
        if worst is None or (status == "bad" and worst["status"] != "bad"):
            worst = candidate
    return worst


def _flag(kind, level, text, since=None, value=None) -> dict:
    return {"kind": kind, "level": level, "text": text, "since": since, "value": value}


def ramp_flag(runs: list[Run], acwr: float | None, today: dt.date) -> dict | None:
    week_start = today - dt.timedelta(days=6)
    prev_start = week_start - dt.timedelta(days=7)
    this = sum(r.km for r in runs if week_start <= r.date <= today)
    before = sum(r.km for r in runs if prev_start <= r.date < week_start)
    if before < MIN_PREVIOUS_KM or acwr is None:
        return None
    pct = (this - before) / before * 100
    if pct <= RAMP_PCT or acwr <= ACWR_WATCH:
        return None
    level = "high" if pct > RAMP_HIGH_PCT and acwr > ACWR_HIGH else "watch"
    return _flag("ramp", level, f"Running km up {pct:.0f}% on the week before "
                 f"({before:.1f} → {this:.1f} km) with load ratio {acwr:.2f}.",
                 week_start, round(pct))


def long_run_flag(runs: list[Run], today: dt.date) -> dict | None:
    week = [r for r in runs if today - dt.timedelta(days=6) <= r.date <= today]
    total = sum(r.km for r in week)
    if len(week) < 2 or total <= 0:
        return None
    longest = max(week, key=lambda r: r.km)
    share = longest.km / total
    if share <= LONG_SHARE:
        return None
    return _flag("long_run_share", "watch",
                 f"Your longest run ({longest.km:.1f} km) was {share * 100:.0f}% of this "
                 "week's running — more than 40%.", longest.date, round(share * 100))


def cadence_flag(runs: list[Run], today: dt.date) -> dict | None:
    with_cadence = sorted((r for r in runs if r.cadence), key=lambda r: r.date)
    recent = with_cadence[-CADENCE_RECENT:]
    if len(recent) < CADENCE_RECENT:
        return None
    first_recent = recent[0].date
    base = [r.cadence for r in with_cadence
            if first_recent - dt.timedelta(days=28) <= r.date < first_recent]
    if len(base) < CADENCE_BASELINE_MIN:
        return None
    now, before = statistics.mean(r.cadence for r in recent), statistics.mean(base)
    drop = before - now
    if drop < CADENCE_DROP:
        return None
    return _flag("cadence_drop", "watch",
                 f"Cadence down {drop:.0f} spm on your 4-week average ({before:.0f} → {now:.0f}) "
                 "— often a sign of tired or sore legs.", first_recent, round(drop, 1))


def gct_flag(runs: list[Run]) -> dict | None:
    values = [r for r in sorted(runs, key=lambda r: r.date) if r.gct_balance is not None]
    recent = values[-GCT_RUNS:]
    if len(recent) < 2:
        return None
    mean = statistics.mean(r.gct_balance for r in recent)
    off = abs(mean - 50.0)
    if off <= GCT_OFF:
        return None
    side = "left" if mean > 50 else "right"
    return _flag("gct_balance", "watch",
                 f"Ground-contact balance {mean:.1f}% left — {off:.1f}% towards the {side}, "
                 "more than 2% off even.", recent[0].date, round(mean, 1))


def shoe_flag(shoe: dict | None) -> dict | None:
    if not shoe or not shoe.get("replace_due"):
        return None
    return _flag("shoe", "watch",
                 f"{shoe['name']} has {shoe['distance_km']:.0f} km — past its "
                 f"{shoe['retire_km']:.0f} km replace mark.", None, shoe["distance_km"])


def pain_flag(signal: dict | None) -> dict | None:
    if not signal:
        return None
    return _flag("pain", "high" if signal["status"] == "bad" else "watch",
                 f"{signal['label']} — the plan eases off until it settles.",
                 signal["since"], signal["days"])


def risk(flags: list[dict]) -> str:
    if any(f["level"] == "high" for f in flags) or len(flags) >= 3:
        return "high"
    if flags:
        return "moderate"
    return "low"


def guidance(flags: list[dict]) -> list[str]:
    kinds = {f["kind"] for f in flags}
    out = []
    if "pain" in kinds:
        out.append("Keep runs easy and short, or rest, until it stops hurting.")
        out.append(PHYSIO)
    if "ramp" in kinds:
        out.append("Hold this week's distance instead of adding more.")
    if "long_run_share" in kinds:
        out.append("Spread the week's running more evenly across your runs.")
    if "cadence_drop" in kinds:
        out.append("Take an extra easy day; tired legs shorten your stride rate.")
    if "gct_balance" in kinds:
        out.append("Uneven ground contact can follow a niggle — notice if one side feels "
                   "different. " + (PHYSIO if "pain" not in kinds else ""))
    if "shoe" in kinds:
        out.append("Start rotating in a newer pair of shoes.")
    return [g.strip() for g in out]


def assess(runs: list[Run], acwr: float | None, pains: list[Pain], shoe: dict | None,
           today: dt.date) -> dict:
    signal = pain_signal(pains, today)
    flags = [f for f in (pain_flag(signal), ramp_flag(runs, acwr, today),
                         long_run_flag(runs, today), cadence_flag(runs, today),
                         gct_flag(runs), shoe_flag(shoe)) if f]
    return {"date": today, "risk": risk(flags), "flags": flags, "guidance": guidance(flags),
            "note": NOTE, "pain_signal": signal}
