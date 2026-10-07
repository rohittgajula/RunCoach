"""R12 §A: the one parser for `range` | `start`+`end`, and `freq`, used by every Health
endpoint. 400 {detail} with a plain message on anything off."""

from __future__ import annotations

import datetime as dt

from analysis.buckets import FREQS, MAX_DAYS, Period, default_freq

from .common import RANGES, BadRequest

LEGACY = {"12w": 84}     # insights and habits summary keep their old preset


def parse_period(request, athlete, default: str, *, extra: dict | None = None) -> Period:
    params = request.query_params
    presets = {**RANGES, **(extra or {})}
    raw_range, raw_start, raw_end = params.get("range"), params.get("start"), params.get("end")
    today = athlete.local_today
    if raw_range and (raw_start or raw_end):
        raise BadRequest("Use either range or start/end dates, not both.")
    if raw_start or raw_end:
        if not (raw_start and raw_end):
            raise BadRequest("start and end are both required for a custom range.")
        try:
            start, end = dt.date.fromisoformat(raw_start), dt.date.fromisoformat(raw_end)
        except ValueError as exc:
            raise BadRequest("start and end must be dates (YYYY-MM-DD).") from exc
        if start > end:
            raise BadRequest("start must be on or before end.")
        if end > today:
            raise BadRequest("end can't be in the future.")
        if (end - start).days + 1 > MAX_DAYS:
            raise BadRequest(f"A custom range can be at most {MAX_DAYS} days.")
        key = "custom"
    else:
        key = raw_range or default
        if key not in presets:
            names = ", ".join(presets)
            raise BadRequest(f"range must be one of {names} (or give start and end).")
        end = today
        start = end - dt.timedelta(days=presets[key] - 1)
    freq = params.get("freq") or default_freq((end - start).days + 1)
    if freq not in FREQS:
        raise BadRequest("freq must be day, week or month.")
    return Period(key, start, end, freq)


def as_period(athlete, value, extra: dict | None = None) -> Period:
    """A Period, or a preset key (the pre-R12 call style) turned into one."""
    if isinstance(value, Period):
        return value
    presets = {**RANGES, **(extra or {})}
    end = athlete.local_today
    start = end - dt.timedelta(days=presets[value] - 1)
    return Period(value, start, end, default_freq(presets[value]))
