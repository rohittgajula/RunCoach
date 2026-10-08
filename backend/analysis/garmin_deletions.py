"""Activities RunCoach holds that Garmin no longer lists (R17). Pure.

Garmin's listing is paged, so "not returned" only means "deleted" inside the window the
listing fully covered. With a full page the oldest listed day may be cut part-way, so the
covered window starts the day after it; with a short page (Garmin ran out) everything
back to the look-back horizon was covered.
"""

from __future__ import annotations

import datetime as dt

LOOKBACK_DAYS = 60
MIN_AGE = dt.timedelta(hours=2)


def covered_from(listed_dates: list[dt.date], page_full: bool, today: dt.date,
                 lookback_days: int = LOOKBACK_DAYS) -> dt.date:
    horizon = today - dt.timedelta(days=lookback_days)
    if page_full:
        if not listed_dates:
            return today + dt.timedelta(days=1)      # nothing provable
        return max(horizon, min(listed_dates) + dt.timedelta(days=1))
    return horizon


def missing(ours: list[tuple[int, int, dt.date, dt.datetime]], listed_ids: set[int],
            window_start: dt.date, now: dt.datetime) -> list[int]:
    """ours = [(activity pk, garmin id, local date, started_at)] → pks Garmin no longer
    lists. Only dates inside the covered window, and only activities older than 2 h."""
    out = []
    for pk, garmin_id, day, started in ours:
        if garmin_id is None or day < window_start:
            continue
        if started is not None and now - started < MIN_AGE:
            continue
        if garmin_id not in listed_ids:
            out.append(pk)
    return out
