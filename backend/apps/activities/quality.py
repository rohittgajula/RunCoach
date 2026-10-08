"""R17 §2: the bad-data filter, Django side.

analysis/data_quality.py does the maths. This module stores the verdict
(ActivityQuality), and gives every consumer of per-second data ONE loader —
`series(activity, fields)` — that returns the raw records or the cleaned copy,
whichever the run's `use` says. The records themselves are never written.

Nothing is ever left out of trends unless the athlete chose `decision = "exclude"`.
"""

from __future__ import annotations

from django.utils import timezone

from analysis import data_quality as dq
from analysis.segmentation import FOOT_SPORTS

from .models import Activity, ActivityQuality

QSAMPLE_FIELDS = ("offset_s", "distance_m", "speed_mps", "cadence_spm", "heart_rate",
                  "latitude", "longitude")
CLEANED_FIELDS = {"heart_rate", "distance_m", "speed_mps", "latitude", "longitude"}
CHART_POINTS = 320


def is_foot(activity: Activity) -> bool:
    sport = (activity.sport or "").lower()
    return sport in FOOT_SPORTS or "run" in sport or "walk" in sport or "hik" in sport


def _rows(activity: Activity, extra: tuple[str, ...] = ()) -> list[dict]:
    fields = tuple(dict.fromkeys(QSAMPLE_FIELDS + tuple(extra)))
    return list(activity.records.order_by("offset_s").values(*fields))


def _qsamples(rows: list[dict]) -> list[dq.QSample]:
    return [dq.QSample(**{k: r.get(k) for k in QSAMPLE_FIELDS}) for r in rows]


def params_for(activity: Activity) -> dict:
    return {"max_hr": activity.athlete.max_hr, "foot": is_foot(activity)}


def run_filter(rows: list[dict], params: dict) -> dq.Result:
    return dq.analyse(_qsamples(rows), max_hr=params.get("max_hr"),
                      foot=params.get("foot", True))


def assess(activity: Activity) -> ActivityQuality | None:
    """Analyse and store. The athlete's decision / use choice are kept."""
    rows = _rows(activity)
    if not rows:
        ActivityQuality.objects.filter(activity=activity).delete()
        return None
    params = params_for(activity)
    result = run_filter(rows, params)
    row, _ = ActivityQuality.objects.update_or_create(
        activity=activity,
        defaults={"version": dq.VERSION, "score": result.score,
                  "summary": result.summary_dict(), "params": params})
    return row


def quality_row(activity: Activity) -> ActivityQuality | None:
    try:
        return activity.quality
    except ActivityQuality.DoesNotExist:
        return None


def effective_use(activity: Activity) -> str:
    row = quality_row(activity)
    return row.use if row is not None else "raw"


def series(activity: Activity, fields: tuple[str, ...], *, use: str | None = None
           ) -> list[dict]:
    """Per-second rows (ordered) with `offset_s` + `fields`, cleaned when the run's
    `use` is "cleaned". Unknown/unstored quality → raw (exactly the pre-R17 rows)."""
    use = use or effective_use(activity)
    if use != "cleaned" or not (set(fields) & CLEANED_FIELDS):
        wanted = tuple(dict.fromkeys(("offset_s",) + tuple(fields)))
        return list(activity.records.order_by("offset_s").values(*wanted))
    rows = _rows(activity, tuple(fields))
    row = quality_row(activity)
    result = run_filter(rows, row.params if row and row.params else params_for(activity))
    c = result.cleaned
    by_field = {"heart_rate": c.heart_rate, "distance_m": c.distance_m,
                "speed_mps": c.speed_mps, "latitude": c.latitude, "longitude": c.longitude}
    out = []
    for i, r in enumerate(rows):
        item = {"offset_s": r["offset_s"]}
        for f in fields:
            if f in by_field:
                v = by_field[f][i]
                if f == "heart_rate" and v is not None:
                    v = int(round(v))
                item[f] = v
            else:
                item[f] = r.get(f)
        out.append(item)
    return out


def quality_json(activity: Activity) -> dict | None:
    row = quality_row(activity)
    if row is None:
        return None
    s = row.summary or {}
    view = dq.status_and_chip(s, decision=row.decision or None,
                              use_choice=row.use_choice or None)
    return {
        "version": row.version, "score": row.score, "status": view["status"],
        "chip": view["chip"], "summary": s.get("summary", ""),
        "flags": s.get("flags", []), "counts": s.get("counts", {}),
        "hr_fixed_s": s.get("hr_fixed_s", 0), "gps_fixed_s": s.get("gps_fixed_s", 0),
        "hr_fixed_pct": s.get("hr_fixed_pct", 0), "gps_fixed_pct": s.get("gps_fixed_pct", 0),
        "affected": s.get("affected", []),
        "suggestion": s.get("suggestion"), "suggestion_reason": s.get("suggestion_reason"),
        "decision": row.decision or None,
        "excluded_from_trends": view["excluded_from_trends"],
        "use": view["use"], "use_default": s.get("use_default", "raw"),
        "use_choice": row.use_choice or None, "use_suggestion": s.get("use_suggestion"),
        "pending_review": view["pending_review"], "info": dq.INFO,
    }


def hr_chart(activity: Activity) -> list[dict]:
    rows = _rows(activity)
    if not rows:
        return []
    row = quality_row(activity)
    result = run_filter(rows, row.params if row and row.params else params_for(activity))
    clean, fixed = result.cleaned.heart_rate, result.cleaned.hr_fixed
    step = max(1, len(rows) // CHART_POINTS)
    out = []
    for start in range(0, len(rows), step):
        idx = range(start, min(len(rows), start + step))
        raw = [rows[i]["heart_rate"] for i in idx if rows[i]["heart_rate"]]
        cl = [clean[i] for i in idx if clean[i] is not None]
        out.append({"t": round(rows[start]["offset_s"]),
                    "hr_raw": round(sum(raw) / len(raw), 1) if raw else None,
                    "hr_clean": round(sum(cl) / len(cl), 1) if cl else None,
                    "fixed": any(fixed[i] for i in idx)})
    return out


DECISIONS = ("include", "exclude")
USES = ("cleaned", "raw")


class BadChoice(ValueError):
    pass


def set_choices(activity: Activity, *, decision=..., use=...) -> ActivityQuality:
    """`...` = leave as is; None = reset. Changing `use` re-derives the run."""
    row = quality_row(activity) or assess(activity)
    if row is None:
        raise BadChoice("This activity has no recorded data to check.")
    fields = []
    if decision is not ...:
        if decision is not None and decision not in DECISIONS:
            raise BadChoice("decision must be include, exclude or null.")
        row.decision = decision or ""
        fields.append("decision")
    use_changed = False
    if use is not ...:
        if use is not None and use not in USES:
            raise BadChoice("use must be cleaned, raw or null.")
        before = row.use
        row.use_choice = use or ""
        fields.append("use_choice")
        use_changed = row.use != before
    if fields:
        row.decided_at = timezone.now()
        row.save(update_fields=fields + ["decided_at", "updated_at"])
    if use_changed:
        from .services import derive

        activity.quality = row
        derive(activity, reassess=False)
    return row


def excluded_ids(athlete) -> set[int]:
    """Activities the athlete explicitly left out of trends."""
    return set(ActivityQuality.objects.filter(activity__athlete=athlete, decision="exclude")
               .values_list("activity_id", flat=True))
