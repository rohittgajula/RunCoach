"""Post-run coach review (R13 §7). Pure — no Django.

A run is compared with similar past runs — the same kind of session in the same
distance bucket (R8 buckets: < 2, 2–5, 5–8, 8+ km), the 10 most recent in the 90 days
before it — on pace, HR at that pace, HR drift, cadence and time spent running. The
bullets are deterministic; an optional AI paragraph may phrase them.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass

SIMILAR_MAX = 10
SIMILAR_DAYS = 90
PACE_BAND_S = 20
PACE_BETTER_PCT = 2.0
HR_BETTER_BPM = 2
DRIFT_BETTER_PT = 1.0
DRIFT_HIGH = 8.0
DRIFT_GOOD = 5.0
CADENCE_TARGET = 168
CADENCE_BETTER = 2
CADENCE_LOW = 160
FRACTION_BETTER_PT = 3.0
MAX_BULLETS = 3

BUCKET_LABELS = {"lt2": "under 2 km", "2to5": "2–5 km", "5to8": "5–8 km", "8plus": "8 km+"}
KIND_WORDS = {"EASY": "easy run", "RUN_WALK": "run/walk", "LONG": "long run",
              "INTERVALS": "interval session", "TEMPO": "tempo run", "RACE": "race"}


@dataclass(frozen=True)
class RunPoint:
    activity_id: int
    date: dt.date
    kind: str                       # planned kind, else EASY
    km: float                       # total distance
    pace: float | None = None       # run pace s/km
    hr: float | None = None         # avg HR on run blocks
    drift: float | None = None
    cadence: float | None = None
    run_fraction: float | None = None   # 0–1


def bucket(km: float) -> str:
    if km < 2:
        return "lt2"
    if km < 5:
        return "2to5"
    if km < 8:
        return "5to8"
    return "8plus"


def similar(run: RunPoint, history: list[RunPoint]) -> list[RunPoint]:
    since = run.date - dt.timedelta(days=SIMILAR_DAYS)
    rows = [h for h in history
            if h.activity_id != run.activity_id and since <= h.date <= run.date
            and h.kind == run.kind and bucket(h.km) == bucket(run.km)
            and (h.date < run.date or h.activity_id < run.activity_id)]
    rows.sort(key=lambda h: (h.date, h.activity_id))
    return rows[-SIMILAR_MAX:]


def _mean(values):
    values = [v for v in values if v is not None]
    return statistics.mean(values) if values else None


def _clock(seconds: float | None) -> str:
    if seconds is None:
        return "–"
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def metrics(run: RunPoint, past: list[RunPoint]) -> list[dict]:
    typical_pace = _mean([p.pace for p in past])
    at_pace = [p.hr for p in past if p.pace and run.pace and abs(p.pace - run.pace) <= PACE_BAND_S]
    typical_hr = _mean(at_pace)
    typical_drift = _mean([p.drift for p in past])
    typical_cadence = _mean([p.cadence for p in past])
    typical_fraction = _mean([p.run_fraction * 100 if p.run_fraction is not None else None
                              for p in past])
    this_fraction = run.run_fraction * 100 if run.run_fraction is not None else None

    def row(key, label, unit, now, typical, digits, better_fn):
        delta = better = None
        if now is not None and typical is not None:
            delta = round(now - typical, digits) if digits else round(now - typical)
            better = better_fn(now, typical)
        return {"key": key, "label": label, "unit": unit,
                "this_run": None if now is None else (round(now, digits) if digits else round(now)),
                "typical": None if typical is None else (round(typical, digits) if digits
                                                         else round(typical)),
                "delta": delta, "better": better}

    def pace_better(now, typ):
        pct = (typ - now) / typ * 100
        return None if abs(pct) < PACE_BETTER_PCT else pct > 0

    def hr_better(now, typ):
        return None if abs(now - typ) < HR_BETTER_BPM else now < typ

    def drift_better(now, typ):
        return None if abs(now - typ) < DRIFT_BETTER_PT else now < typ

    def cadence_better(now, typ):
        gain = abs(typ - CADENCE_TARGET) - abs(now - CADENCE_TARGET)
        return None if abs(gain) < CADENCE_BETTER else gain > 0

    def fraction_better(now, typ):
        return None if abs(now - typ) < FRACTION_BETTER_PT else now > typ

    return [
        row("pace", "Run pace", "s/km", run.pace, typical_pace, 0, pace_better),
        row("hr_at_pace", "HR at this pace", "bpm", run.hr if at_pace else run.hr,
            typical_hr, 0, hr_better),
        row("hr_drift", "HR drift", "%", run.drift, typical_drift, 1, drift_better),
        row("cadence", "Cadence", "spm", run.cadence, typical_cadence, 0, cadence_better),
        row("run_fraction", "Time running", "%", this_fraction, typical_fraction, 0,
            fraction_better),
    ]


def bullets(run: RunPoint, rows: list[dict], compared_with: int, *,
            zone_top: int | None = None, completion: float | None = None,
            rpe: int | None = None) -> tuple[list[str], list[str], list[str]]:
    good: list[str] = []
    bad: list[str] = []
    nxt: list[str] = []
    by = {r["key"]: r for r in rows}
    group = f"{BUCKET_LABELS[bucket(run.km)]} {KIND_WORDS.get(run.kind, 'run')}s"
    pace = by["pace"]
    if pace["better"] is not None:
        diff = abs(pace["delta"])
        text = (f"Run pace {_clock(pace['this_run'])}/km — {diff} s "
                f"{'faster' if pace['delta'] < 0 else 'slower'} than your typical {group}")
        # Faster is only "good" on a planned hard session or when HR did not rise with it.
        hr = by["hr_at_pace"]
        if pace["better"] and (run.kind in ("INTERVALS", "TEMPO", "RACE") or hr["better"] is not False):
            good.append(text)
        elif not pace["better"] and run.kind in ("EASY", "RUN_WALK", "LONG"):
            pass  # slower on an easy day is fine; not a "to improve"
        else:
            bad.append(text)
    hr = by["hr_at_pace"]
    if hr["better"] is not None:
        text = (f"HR at this pace {hr['this_run']} bpm vs your usual {hr['typical']} — "
                f"{'lower' if hr['better'] else 'higher'}")
        (good if hr["better"] else bad).append(text)
    drift = by["hr_drift"]
    if drift["this_run"] is not None:
        if drift["this_run"] > DRIFT_HIGH:
            bad.append(f"HR drifted {drift['this_run']:.1f}% — you were working harder by the end")
            nxt.append("Start the first 10 minutes slower and sip water if it's warm.")
        elif drift["better"] or drift["this_run"] <= DRIFT_GOOD:
            good.append(f"Steady effort: HR drift {drift['this_run']:.1f}%")
    cad = by["cadence"]
    if cad["better"] is not None:
        text = f"Cadence {cad['this_run']} spm vs your usual {cad['typical']}"
        (good if cad["better"] else bad).append(text)
    if cad["this_run"] is not None and cad["this_run"] < CADENCE_LOW:
        nxt.append("Try slightly quicker, shorter steps — a metronome at "
                   f"{min(200, max(140, round(cad['this_run'] * 1.05)))} spm helps.")
    frac = by["run_fraction"]
    if frac["better"] is not None:
        text = f"Running {frac['this_run']}% of the time vs your usual {frac['typical']}%"
        (good if frac["better"] else bad).append(text)
    if run.kind in ("EASY", "RUN_WALK", "LONG") and run.hr and zone_top and run.hr > zone_top + 4:
        bad.append(f"Average HR {round(run.hr)} bpm — above the easy cap of {zone_top}")
        nxt.append(f"Walk whenever your HR passes {zone_top} bpm — easy days build the base.")
    if completion is not None:
        if completion >= 0.9:
            good.append("You did the whole planned session")
        elif completion < 0.7:
            bad.append(f"You ran {round(completion * 100)}% of the planned time")
            nxt.append("If the planned time felt too long, the plan will ease off — "
                       "do what you can at an easy effort.")
    if rpe is not None and rpe >= 8 and run.kind in ("EASY", "RUN_WALK", "LONG"):
        bad.append(f"It felt hard ({rpe}/10) for an easy session")
        nxt.append("Slow down until you can talk in full sentences.")
    if not compared_with:
        nxt.append("Keep logging similar runs — comparisons start after the next one.")
    if not nxt:
        nxt.append("Keep the same easy effort next time — consistency is what builds fitness.")
    return good[:MAX_BULLETS], bad[:MAX_BULLETS], nxt[:MAX_BULLETS]


def review(run: RunPoint, history: list[RunPoint], **kwargs) -> dict:
    past = similar(run, history)
    rows = metrics(run, past)
    good, bad, nxt = bullets(run, rows, len(past), **kwargs)
    return {"kind": run.kind, "bucket": bucket(run.km), "compared_with": len(past),
            "metrics": rows, "went_well": good, "to_improve": bad, "next_time": nxt}
