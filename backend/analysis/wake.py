"""R12 §B: the wake planner and the watch-alarm check. Pure: no Django.

A web app cannot set the phone's alarm or write one to a Garmin watch, so this only
suggests times, reads the watch's own alarms (read-only) and flags mismatches with the
plan. Clock times are minutes after midnight.
"""

from __future__ import annotations

import datetime as dt
from statistics import median

PREP_MIN = 45              # wake this long before a planned run
ALARM_SLACK_MIN = 15       # an alarm later than run − 15 min is too late to run on time
FALL_ASLEEP_MIN = 15
DEFAULT_WAKE = 7 * 60
DEFAULT_NEED_S = 8 * 3600
MORNING_END = 12 * 60
RECENT_RUNS = 10
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
DAY_NAMES = {
    "MONDAY": 0, "MON": 0, "M": 0, "TUESDAY": 1, "TUE": 1, "TU": 1, "WEDNESDAY": 2, "WED": 2,
    "W": 2, "THURSDAY": 3, "THU": 3, "TH": 3, "FRIDAY": 4, "FRI": 4, "F": 4, "SATURDAY": 5,
    "SAT": 5, "SA": 5, "SUNDAY": 6, "SUN": 6, "SU": 6,
}
EVERY_DAY = {"DAILY", "EVERYDAY", "EVERY_DAY", "ALL"}
ONCE = {"ONCE", "ONE_TIME", "NONE"}


def clock(minute: float | None) -> str | None:
    if minute is None:
        return None
    m = int(round(minute)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def minutes(value: str | dt.time | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, dt.time):
        return value.hour * 60 + value.minute
    try:
        h, m = str(value).split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, TypeError):
        return None


def typical_run_time(starts: list[int]) -> int | None:
    """Median start of the recent morning runs (minutes), else None."""
    morning = [s for s in starts[-RECENT_RUNS:] if s < MORNING_END]
    return round(median(morning)) if morning else None


def plan(*, run_planned: bool, run_time: int | None, habit_wake: int | None,
         need_s: int | None, lead_min: int) -> dict:
    """Suggested wake (minutes), its source, bedtime and the reminder time."""
    need = need_s or DEFAULT_NEED_S
    if run_planned and run_time is not None:
        wake, source = run_time - PREP_MIN, "run"
    elif habit_wake is not None:
        wake, source = habit_wake, "habit"
    else:
        wake, source = DEFAULT_WAKE, "default"
    bedtime = wake - need / 60 - FALL_ASLEEP_MIN
    return {"wake": wake % 1440, "wake_source": source, "bedtime": bedtime % 1440,
            "reminder": (bedtime - lead_min) % 1440, "need_s": need,
            "need_source": "garmin" if need_s else "default"}


# --- watch alarms ----------------------------------------------------------------------

def parse_alarm(raw: dict, device: str | None = None) -> dict | None:
    """One Garmin device alarm -> {time, days, once, enabled, label, device}."""
    if not isinstance(raw, dict):
        return None
    value = raw.get("alarmTime")
    if value is None:
        value = raw.get("time")
    t = None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        t = int(value)
        if t >= 1440 and t % 60 == 0 and t // 60 < 1440:
            t //= 60          # seconds after midnight on some firmware
    elif isinstance(value, str):
        t = minutes(value)
    if t is None or not 0 <= t < 1440:
        return None
    days_raw = raw.get("alarmDays") or raw.get("days") or []
    if isinstance(days_raw, str):
        days_raw = [days_raw]
    days: set[int] = set()
    once = False
    for item in days_raw:
        name = str(item).upper().strip()
        if name in EVERY_DAY:
            days |= set(range(7))
        elif name in ONCE:
            once = True
        elif name in DAY_NAMES:
            days.add(DAY_NAMES[name])
    if not days and not once:
        once = True
    mode = str(raw.get("alarmMode") or "").upper()
    enabled = raw.get("enabled")
    if enabled is None:
        enabled = mode != "OFF"
    label = raw.get("alarmLabel") or raw.get("alarmMessage") or None
    return {"time": clock(t), "days": sorted(days), "once": once, "enabled": bool(enabled),
            "label": str(label)[:60] if label else None, "device": device}


def _days_text(days: list[int]) -> str:
    if len(days) == 7:
        return "every day"
    if days == [0, 1, 2, 3, 4]:
        return "Mon–Fri"
    if days == [5, 6]:
        return "Sat–Sun"
    runs, start = [], None
    for i, d in enumerate(days):
        if start is None:
            start = d
        if i + 1 == len(days) or days[i + 1] != d + 1:
            runs.append(WEEKDAYS[start] if start == d else
                        f"{WEEKDAYS[start]}–{WEEKDAYS[d]}" if d - start > 1 else
                        f"{WEEKDAYS[start]}, {WEEKDAYS[d]}")
            start = None
    return ", ".join(runs)


def summary(alarms: list[dict]) -> str | None:
    """'06:00 Mon–Fri · 08:00 Sat' — enabled alarms only."""
    parts = []
    for a in sorted((a for a in alarms if a["enabled"]), key=lambda a: a["time"]):
        parts.append(f"{a['time']} {'once' if a['once'] and not a['days'] else _days_text(a['days'])}")
    return " · ".join(parts) or None


def alarms_on(alarms: list[dict], weekday: int, *, include_once: bool = True) -> list[int]:
    """Minutes of the enabled alarms that ring on `weekday` (a one-off counts)."""
    out = []
    for a in alarms:
        if not a.get("enabled"):
            continue
        if weekday in a.get("days", []) or (include_once and a.get("once") and not a.get("days")):
            m = minutes(a["time"])
            if m is not None:
                out.append(m)
    return sorted(out)


def flags(*, run_planned: bool, run_time: int | None, watch_available: bool,
          watch_times: list[int], my_alarm: int | None) -> list[dict]:
    """Mismatches between the alarms and the run (only on run days with a run time)."""
    if not run_planned or run_time is None:
        return []
    latest_ok = run_time - ALARM_SLACK_MIN
    out = []
    run = clock(run_time)
    if my_alarm is None and not watch_times:
        return [{"kind": "no_alarm_for_run", "text": f"No alarm set for tomorrow's run at {run}."}]
    if watch_times:
        earliest = min(watch_times)
        if earliest > latest_ok:
            out.append({"kind": "watch_alarm_after_run",
                        "text": f"Your run is at {run} but your watch alarm is {clock(earliest)}."})
    elif watch_available:
        out.append({"kind": "no_watch_alarm_for_run",
                    "text": f"No watch alarm is set for the run at {run}."})
    if my_alarm is not None and my_alarm > latest_ok:
        out.append({"kind": "my_alarm_after_run",
                    "text": f"Your run is at {run} but your RunCoach alarm is {clock(my_alarm)}."})
    return out


def android_intent(minute: int, message: str = "RunCoach") -> str:
    h, m = divmod(int(minute) % 1440, 60)
    return ("intent:#Intent;action=android.intent.action.SET_ALARM;"
            f"i.android.intent.extra.alarm.HOUR={h};i.android.intent.extra.alarm.MINUTES={m};"
            f"S.android.intent.extra.alarm.MESSAGE={message};end")


def sentence(wake_source: str, wake: int, bedtime: int, run_time: int | None) -> str:
    if wake_source == "run":
        return (f"Up at {clock(wake)} for your {clock(run_time)} run — in bed by "
                f"{clock(bedtime)} to get your sleep.")
    if wake_source == "habit":
        return (f"You usually wake around {clock(wake)}; bed by {clock(bedtime)} covers "
                "your sleep need.")
    return f"Aim for bed by {clock(bedtime)} to wake rested at {clock(wake)}."
