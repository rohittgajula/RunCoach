"""R11 §A: Garmin's intraday series — all-day heart rate, stress + Body Battery and
15-minute steps — stored compactly per athlete-day (IntradayDay).

Real garminconnect 0.3.10 methods (read from the installed package):
* ``get_heart_rates(date)`` → ``{startTimestampGMT, startTimestampLocal, restingHeartRate,
  heartRateValues: [[epoch_ms, bpm|None], …]}`` (2-minute samples)
* ``get_stress_data(date)`` (same URL as ``get_all_day_stress``) →
  ``{stressValuesArray: [[epoch_ms, level], …], bodyBatteryValuesArray:
  [[epoch_ms, "MEASURED"|"MODELED", level, version], …]}`` (3-minute samples; level −1 =
  off wrist, −2 = activity) — so Body Battery needs no call of its own
* ``get_steps_data(date)`` → ``[{startGMT, endGMT, steps, primaryActivityLevel}, …]``
  (96 buckets of 15 min; level sleeping|sedentary|active|highlyActive|generic|none)
Daily totals (step goal, sedentary/active seconds, Body Battery charged/drained) are in
``get_user_summary`` = ``get_stats``, which the wellness sync already stores in
``DailyMetrics.raw["stats"]`` — no extra request.

Three requests per day, made on the garmin queue with the R10 runner: the breaker is
checked before each one, they are GARMIN_SLOW_PAUSE_S apart and the first 429 stops the
run (and trips the breaker in the task).
"""

from __future__ import annotations

import datetime as dt
import logging
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.athletes.models import Athlete

from .garmin_wellness import RateLimited, _int
from .models import IntradayDay

logger = logging.getLogger(__name__)

BACKFILL_DAYS = 30
LEVELS = {"sleeping": "sleeping", "sedentary": "sedentary", "active": "active",
          "highlyActive": "highly_active"}


# --- parsing (pure functions of the payloads) ----------------------------------------

def _parse_ts(value) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value).split(".")[0])
    except ValueError:
        return None


def payload_offset_min(payload) -> int | None:
    """Garmin's own local-minus-GMT offset for that day (minutes)."""
    if not isinstance(payload, dict):
        return None
    gmt = _parse_ts(payload.get("startTimestampGMT"))
    local = _parse_ts(payload.get("startTimestampLocal"))
    if gmt is None or local is None:
        return None
    return round((local - gmt).total_seconds() / 60)


def zone_offset_min(zone_name: str, day: dt.date) -> int:
    try:
        zone = ZoneInfo(zone_name or "UTC")
    except Exception:  # noqa: BLE001
        zone = ZoneInfo("UTC")
    noon = dt.datetime.combine(day, dt.time(12, 0), tzinfo=zone)
    return round(noon.utcoffset().total_seconds() / 60)


def minute_of(epoch_ms, offset_min: int, day: dt.date) -> int | None:
    try:
        local = dt.datetime(1970, 1, 1) + dt.timedelta(milliseconds=int(epoch_ms),
                                                       minutes=offset_min)
    except (TypeError, ValueError, OverflowError):
        return None
    if local.date() != day:
        return None
    return local.hour * 60 + local.minute


def _dedupe(points: list[list[int]]) -> list[list[int]]:
    """One value per minute, ordered."""
    by_min: dict[int, int] = {}
    for m, v in points:
        by_min[m] = v
    return [[m, by_min[m]] for m in sorted(by_min)]


def parse_heart_rates(payload, day: dt.date, offset: int) -> tuple[list, int | None]:
    values = payload.get("heartRateValues") if isinstance(payload, dict) else None
    out = []
    for item in values or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        bpm = _int(item[1])
        m = minute_of(item[0], offset, day)
        if m is not None and bpm and 25 <= bpm <= 240:
            out.append([m, bpm])
    resting = _int(payload.get("restingHeartRate")) if isinstance(payload, dict) else None
    return _dedupe(out), resting


def parse_stress(payload, day: dt.date, offset: int) -> tuple[list, list]:
    """(stress [[min, 0-100]], body battery [[min, level]] — change points + last)."""
    if not isinstance(payload, dict):
        return [], []
    stress = []
    for item in payload.get("stressValuesArray") or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        level = _int(item[1])
        m = minute_of(item[0], offset, day)
        if m is not None and level is not None and 0 <= level <= 100:
            stress.append([m, level])
    battery = []
    for item in payload.get("bodyBatteryValuesArray") or []:
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            continue
        level = _int(item[2])
        m = minute_of(item[0], offset, day)
        if m is not None and level is not None and 0 <= level <= 100:
            battery.append([m, level])
    battery = _dedupe(battery)
    compact = [p for i, p in enumerate(battery)
               if i == 0 or i == len(battery) - 1 or p[1] != battery[i - 1][1]]
    return _dedupe(stress), compact


def parse_steps(payload, day: dt.date, offset: int) -> list:
    out = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict):
            continue
        start = _parse_ts(item.get("startGMT"))
        if start is None:
            continue
        local = start + dt.timedelta(minutes=offset)
        if local.date() != day:
            continue
        steps = _int(item.get("steps")) or 0
        level = LEVELS.get(str(item.get("primaryActivityLevel") or ""))
        out.append([local.hour * 60 + local.minute, max(0, steps), level])
    out.sort(key=lambda r: r[0])
    return out


# --- storing --------------------------------------------------------------------------

def store_day(athlete: Athlete, day: dt.date, *, heart_rates=None, stress=None,
              steps=None, complete: bool | None = None) -> IntradayDay | None:
    """Merge whatever payloads arrived into the day's row (a missing one keeps what an
    earlier fetch stored) and recompute the aggregates."""
    offset = (payload_offset_min(heart_rates) or payload_offset_min(stress)
              or zone_offset_min(athlete.timezone, day))
    fields: dict = {"utc_offset_min": offset}
    if heart_rates:
        hr, resting = parse_heart_rates(heart_rates, day, offset)
        if hr:
            fields["hr"] = hr
        if resting:
            fields["resting_hr"] = resting
    if stress:
        s, bb = parse_stress(stress, day, offset)
        if s:
            fields["stress"] = s
        if bb:
            fields["body_battery"] = bb
    if steps:
        rows = parse_steps(steps, day, offset)
        if rows:
            fields["steps"] = rows
    if len(fields) == 1:
        return IntradayDay.objects.filter(athlete=athlete, day=day).first()
    fields["fetched_at"] = timezone.now()
    if complete is not None:
        fields["complete"] = complete
    row, _ = IntradayDay.objects.update_or_create(athlete=athlete, day=day, defaults=fields)
    refresh_aggregates(row)
    return row


def refresh_aggregates(row: IntradayDay) -> IntradayDay:
    from analysis.day import aggregates
    from apps.health.day_service import day_input

    values = aggregates(day_input(row.athlete, row.day, row=row, history=False))
    changed = [k for k, v in values.items() if getattr(row, k) != v]
    for key in changed:
        setattr(row, key, values[key])
    if changed:
        row.save(update_fields=changed + ["updated_at"])
    return row


# --- fetching -------------------------------------------------------------------------

def fetch_day(athlete: Athlete, client, day: dt.date, call, *, minimal: bool = False):
    """Three requests (two with `minimal`: steps + stress, what the nudges need)."""
    iso = day.isoformat()
    hr = None if minimal else call("heart rates", lambda: client.get_heart_rates(iso))
    stress = call("stress", lambda: client.get_stress_data(iso))
    steps = call("steps", lambda: client.get_steps_data(iso))
    return store_day(athlete, day, heart_rates=hr, stress=stress, steps=steps,
                     complete=day < athlete.local_today)


def sync_intraday(athlete: Athlete, client, days: list[dt.date] | None = None, *,
                  minimal: bool = False) -> dict:
    """Default: today and yesterday (yesterday finalises)."""
    from .garmin_slow import _Runner

    today = athlete.local_today
    days = days or [today, today - dt.timedelta(days=1)]
    call = _Runner(client)
    stored = 0
    try:
        for day in days:
            if fetch_day(athlete, client, day, call, minimal=minimal) is not None:
                stored += 1
    except RateLimited as exc:
        logger.warning("garmin intraday rate limited for %s: %s", athlete.pk, exc)
        return {"days": stored, "rate_limited": True, "calls": call.calls}
    return {"days": stored, "rate_limited": False, "calls": call.calls, "missing": call.errors}


def backfill_days(athlete: Athlete, days: int = BACKFILL_DAYS, force: bool = False) -> list[dt.date]:
    """Days still to fetch, newest first (complete days are skipped unless forced)."""
    today = athlete.local_today
    wanted = [today - dt.timedelta(days=i) for i in range(1, days + 1)]
    if force:
        return wanted
    done = set(IntradayDay.objects.filter(athlete=athlete, complete=True, day__in=wanted)
               .values_list("day", flat=True))
    return [d for d in wanted if d not in done]
