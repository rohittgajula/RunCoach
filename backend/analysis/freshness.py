"""R16 §C: is today's sleep / readiness in yet? Pure — no Django.

The watch syncs last night's sleep and this morning's readiness some time after the
athlete wakes. Until it does, screens fall back to older values; this says so once
("Showing yesterday's sleep — your watch hasn't synced last night yet.") instead of
dating every tile.

Not stale: before 05:00 local (nothing is expected yet), or when the athlete has no
recent data of that kind at all (no watch, or a watch that never reports readiness —
otherwise the banner would nag forever).
"""

from __future__ import annotations

import datetime as dt

STALE_FROM_HOUR = 5
RECENT_DAYS = 14


def _recent(latest: dt.date | None, today: dt.date) -> bool:
    return latest is not None and (today - latest).days <= RECENT_DAYS


def assess(*, today: dt.date, local_hour: int, has_sleep_today: bool,
           has_readiness_today: bool, latest_sleep_date: dt.date | None,
           latest_readiness_date: dt.date | None) -> dict:
    """{stale, stale_reason, stale_text}."""
    sleep_missing = (not has_sleep_today) and _recent(latest_sleep_date, today)
    ready_missing = (not has_readiness_today) and _recent(latest_readiness_date, today)
    if local_hour < STALE_FROM_HOUR or not (sleep_missing or ready_missing):
        return {"stale": False, "stale_reason": None, "stale_text": None}
    if sleep_missing and ready_missing:
        reason = "both_missing"
    else:
        reason = "sleep_missing" if sleep_missing else "readiness_missing"
    if sleep_missing:
        if latest_sleep_date == today - dt.timedelta(days=1):
            shown = "yesterday's sleep"
        else:
            shown = f"sleep from {latest_sleep_date:%a} {latest_sleep_date.day} " \
                    f"{latest_sleep_date:%b}"
        text = f"Showing {shown} — your watch hasn't synced last night yet."
    else:
        text = "Today's readiness isn't in yet — your watch hasn't synced this morning."
    return {"stale": True, "stale_reason": reason, "stale_text": text}
