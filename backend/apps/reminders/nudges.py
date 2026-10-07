"""R11 §C: nudges — move, breathing break, drink water.

Move and breathing read the latest intraday data (Garmin syncs are not real time, so
"latest" means the newest sample, and a nudge is only considered while that sample is
≤ 60 minutes old). Every nudge is off by default and respects quiet hours, its own
hours, a per-day cap, a minimum gap, one nudge per stretch, and never fires during a
run or within an hour after one. Payloads carry no numbers.
"""

from __future__ import annotations

import datetime as dt

from analysis import day as day_maths

NUDGES = {
    "move": ("Move reminder", "A nudge to get up after a long sitting spell."),
    "breathing": ("Breathing break", "When stress has stayed high for 30+ minutes, a short "
                                      "breathing exercise."),
    "water": ("Drink water", "Every few hours, until today's water target is reached."),
}
# key -> {field: (min, max)} beyond the common enabled/start/end/max_per_day
EXTRA = {"move": {"after_min": (60, 90)}, "breathing": {"threshold": (51, 90)},
         "water": {"every_h": (1, 4)}}
MAX_PER_DAY = (1, 8)
MIN_GAP = dt.timedelta(minutes=60)
FRESH_MIN = 60
AFTER_RUN = dt.timedelta(minutes=60)
BREATHING_MIN = 30

MESSAGES = {
    "move": {"title": "Time to move", "body": "You've been still for a while — stand up and "
             "walk for a few minutes.", "url": "/health/day", "tag": "move"},
    "breathing": {"title": "Breathing break", "body": "Stress has been up for a while. Two "
                  "minutes of slow breathing can help.", "url": "/health/guides?g=breathing",
                  "tag": "breathing"},
    "water": {"title": "Drink some water", "body": "A glass of water now keeps you on track "
              "for today.", "url": "/diet", "tag": "water"},
}


def _t(value: dt.time) -> str:
    return value.strftime("%H:%M")


def nudges_json(row) -> list[dict]:
    out = []
    for key, (label, description) in NUDGES.items():
        out.append({
            "key": key, "label": label, "description": description,
            "enabled": getattr(row, key), "start": _t(getattr(row, f"{key}_start")),
            "end": _t(getattr(row, f"{key}_end")),
            "max_per_day": getattr(row, f"{key}_max_per_day"),
            "after_min": row.move_after_min if key == "move" else None,
            "threshold": row.breathing_threshold if key == "breathing" else None,
            "every_h": row.water_every_h if key == "water" else None,
        })
    return out


def quiet_json(row) -> dict:
    return {"start": _t(row.quiet_start), "end": _t(row.quiet_end)}


def in_window(now: dt.time, start: dt.time, end: dt.time) -> bool:
    """[start, end); wraps past midnight when end ≤ start."""
    if start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end


def _parse_time(value) -> dt.time:
    return dt.datetime.strptime(str(value), "%H:%M").time()


def validate_patch(key: str, change) -> dict:
    """Field updates for one nudge, or raises ValueError with a message."""
    if not isinstance(change, dict):
        raise ValueError(f"{key} takes an object.")
    allowed = {"enabled", "start", "end", "max_per_day", *EXTRA[key]}
    unknown = set(change) - allowed
    if unknown:
        raise ValueError(f"{key} does not take {', '.join(sorted(unknown))}.")
    updates: dict = {}
    if "enabled" in change:
        if not isinstance(change["enabled"], bool):
            raise ValueError(f"{key}.enabled must be true or false.")
        updates[key] = change["enabled"]
    for name in ("start", "end"):
        if name in change:
            try:
                updates[f"{key}_{name}"] = _parse_time(change[name])
            except ValueError as exc:
                raise ValueError(f"{key}.{name} must be HH:MM (24 h).") from exc
    bounds = {"max_per_day": MAX_PER_DAY, **EXTRA[key]}
    for name, (low, high) in bounds.items():
        if name in change:
            value = change[name]
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ValueError(f"{key}.{name} must be a whole number from {low} to {high}.")
            updates[f"{key}_{name}"] = value
    return updates


def validate_quiet(change) -> dict:
    if not isinstance(change, dict) or not set(change) <= {"start", "end"}:
        raise ValueError("quiet_hours takes {start?, end?}.")
    updates = {}
    for name in ("start", "end"):
        if name in change:
            try:
                updates[f"quiet_{name}"] = _parse_time(change[name])
            except ValueError as exc:
                raise ValueError(f"quiet_hours.{name} must be HH:MM (24 h).") from exc
    return updates


# --- evaluation ----------------------------------------------------------------------

def _state(row, key: str, today: dt.date) -> dict:
    state = dict((row.nudge_state or {}).get(key) or {})
    if state.get("date") != today.isoformat():
        state = {"date": today.isoformat(), "count": 0}
    return state


def _after_run(athlete, now: dt.datetime, steps: list, now_min: int) -> bool:
    from apps.activities.models import Activity

    recent = Activity.objects.filter(athlete=athlete, started_at__gte=now - dt.timedelta(hours=8),
                                     started_at__lte=now)
    for a in recent:
        end = a.started_at + dt.timedelta(seconds=a.total_elapsed_s or a.total_timer_s or 0)
        if now <= end + AFTER_RUN:
            return True
    if steps:
        last = steps[-1]
        if day_maths.bucket_kind(last) == "intense" or (len(last) > 2 and last[2] == "highly_active"):
            if now_min - (last[0] + day_maths.BUCKET_MIN) <= AFTER_RUN.total_seconds() / 60:
                return True
    return False


def _water_done(athlete, today: dt.date, local_now: dt.datetime, every_h: int) -> bool:
    from apps.diet.models import WaterLog
    from apps.diet.water import water_target

    since = local_now - dt.timedelta(hours=every_h)
    if WaterLog.objects.filter(athlete=athlete, at__gte=since).exists():
        return True
    target, _ = water_target(athlete, today)
    drunk = sum(WaterLog.objects.filter(athlete=athlete, local_date=today)
                .values_list("ml", flat=True))
    return bool(target) and drunk >= target


def check(athlete, row, key: str, local_now: dt.datetime, intraday=None) -> tuple[dict | None, dict]:
    """(push message or None, the nudge's updated state — saved only when sent)."""
    today = local_now.date()
    state = _state(row, key, today)
    if not getattr(row, key):
        return None, state
    if in_window(local_now.time(), row.quiet_start, row.quiet_end):
        return None, state
    if not in_window(local_now.time(), getattr(row, f"{key}_start"), getattr(row, f"{key}_end")):
        return None, state
    if state["count"] >= getattr(row, f"{key}_max_per_day"):
        return None, state
    gap = dt.timedelta(hours=row.water_every_h) if key == "water" else MIN_GAP
    if state.get("last_at"):
        last = dt.datetime.fromisoformat(state["last_at"])
        if local_now - last < gap:
            return None, state

    now_min = local_now.hour * 60 + local_now.minute
    stretch = None
    if key in ("move", "breathing"):
        if intraday is None or intraday.day != today:
            return None, state
        if _after_run(athlete, local_now, intraday.steps or [], now_min):
            return None, state
        if key == "move":
            steps = intraday.steps or []
            if not steps or now_min - (steps[-1][0] + day_maths.BUCKET_MIN) > FRESH_MIN:
                return None, state
            trailing = day_maths.trailing_sedentary(steps)
            if trailing is None or trailing[1] < row.move_after_min:
                return None, state
            stretch = trailing[0]
        else:
            stress = intraday.stress or []
            if not stress or now_min - stress[-1][0] > FRESH_MIN:
                return None, state
            trailing = day_maths.trailing_stress(stress, row.breathing_threshold)
            if trailing is None or trailing[1] < BREATHING_MIN:
                return None, state
            stretch = trailing[0]
        if state.get("stretch") == stretch:
            return None, state                # already nudged for this stretch
    elif _water_done(athlete, today, local_now, row.water_every_h):
        return None, state

    state = {**state, "count": state["count"] + 1, "last_at": local_now.isoformat(),
             "stretch": stretch}
    return dict(MESSAGES[key]), state


def run_for(athlete, row, local_now: dt.datetime, send) -> int:
    """Evaluate every enabled nudge for one athlete; `send(message) -> bool`."""
    from apps.ingest.models import IntradayDay

    keys = [k for k in NUDGES if getattr(row, k)]
    if not keys:
        return 0
    intraday = None
    if any(k in ("move", "breathing") for k in keys):
        intraday = (IntradayDay.objects.filter(athlete=athlete, day=local_now.date())
                    .only("day", "steps", "stress").first())
    sent = 0
    changed = False
    states = dict(row.nudge_state or {})
    for key in keys:
        message, state = check(athlete, row, key, local_now, intraday)
        if message is None:
            continue
        states[key] = state
        changed = True
        if send(message):
            sent += 1
    if changed:
        row.nudge_state = states
        row.save(update_fields=["nudge_state", "updated_at"])
    return sent
