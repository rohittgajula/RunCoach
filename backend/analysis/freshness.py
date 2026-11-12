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


# --- Garmin silence (R19) -----------------------------------------------------
#
# A disconnected watch is the one failure in this app that invalidates everything
# downstream, and until now it failed silently. Rohit's session died on 10 October
# and the only signal was a boolean on a settings page he had no reason to open.
# For five weeks Today showed a plan built on October data, the coach answered
# questions about a stale picture with full confidence, and his 5 km projection
# was computed from a watch that had stopped talking.
#
# Being wrong quietly is worse than being disconnected.

#: Below this, silence is normal — people have rest days, and a watch that has
#: not synced since yesterday evening is not a problem worth a banner.
SYNC_QUIET_HOURS = 48

#: Past this the plan itself is suspect, not just the dashboard: the baseline,
#: the readiness rules and the ramp are all derived from data this old.
SYNC_STALE_DAYS = 7


def sync_verdict(
    *,
    today: dt.date,
    connected: bool,
    last_sync_at: dt.datetime | None,
    last_activity_date: dt.date | None,
    now: dt.datetime | None = None,
) -> dict:
    """How bad the silence is, and what it means for what is on screen.

    Severity is deliberately about CONSEQUENCE rather than duration. A watch
    disconnected for two hours is already "broken" because nothing will arrive
    until somebody acts; a watch that merely has not synced since yesterday is
    fine and needs no banner at all.
    """
    hours = None
    if last_sync_at is not None and now is not None:
        hours = max((now - last_sync_at).total_seconds() / 3600, 0)

    days_since_activity = (
        (today - last_activity_date).days if last_activity_date else None
    )

    if not connected:
        return {
            "level": "broken",
            "connected": False,
            "hours_since_sync": hours,
            "days_since_activity": days_since_activity,
            "last_sync_at": last_sync_at,
            "last_activity_date": last_activity_date,
            "headline": "Garmin is disconnected.",
            "detail": (
                "Nothing has synced"
                + (f" since {last_sync_at:%-d %B}" if last_sync_at else "")
                + ". Everything on this screen — your plan, your readiness, your "
                "projection — is computed from the data that arrived before it "
                "stopped. Reconnect to bring it back up to date."
            ),
            "action": "reconnect",
        }

    if hours is not None and hours > SYNC_STALE_DAYS * 24:
        return {
            "level": "stale",
            "connected": True,
            "hours_since_sync": hours,
            "days_since_activity": days_since_activity,
            "last_sync_at": last_sync_at,
            "last_activity_date": last_activity_date,
            "headline": f"No sync for {round(hours / 24)} days.",
            "detail": (
                "The connection looks alive but nothing is arriving. Your plan and "
                "readiness are being computed from data at least that old."
            ),
            "action": "sync",
        }

    if hours is not None and hours > SYNC_QUIET_HOURS:
        return {
            "level": "quiet",
            "connected": True,
            "hours_since_sync": hours,
            "days_since_activity": days_since_activity,
            "last_sync_at": last_sync_at,
            "last_activity_date": last_activity_date,
            "headline": f"Last sync {round(hours / 24)} days ago.",
            "detail": "Worth a manual sync if you have been out since.",
            "action": "sync",
        }

    return {
        "level": "ok",
        "connected": True,
        "hours_since_sync": hours,
        "days_since_activity": days_since_activity,
        "last_sync_at": last_sync_at,
        "last_activity_date": last_activity_date,
        "headline": "",
        "detail": "",
        "action": "",
    }
