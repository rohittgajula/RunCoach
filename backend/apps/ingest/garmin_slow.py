"""R10 §B: the slow-changing Garmin data — endurance score, fitness age, lactate
threshold, personal records, body composition and gear.

Fetched at most once a day per athlete, on the garmin queue (concurrency 1), with a
pause between calls and the shared circuit breaker honoured before every one: a 429
stops the run at once (the limit is per IP, so pressing on lengthens the block for
everyone). Every endpoint is isolated — one that fails or does not exist on this
account leaves the rest of the fetch intact, and anything absent is stored as null.

Real method names on garminconnect 0.3.10 (checked against the installed package):
get_endurance_score, get_fitnessage_data, get_lactate_threshold, get_personal_record,
get_body_composition, get_user_profile, get_gear, get_gear_stats; R12 adds get_devices and
get_device_settings (read-only, for the watch alarms). Training status /
load focus and sleep details come from get_training_status / get_sleep_data, which the
daily wellness sync already stores verbatim (see garmin_wellness.fields_from_raw).
"""

from __future__ import annotations

import datetime as dt
import logging
import time

from django.conf import settings
from django.utils import timezone

from apps.athletes.models import Athlete, MetricEntry

from .garmin_wellness import RateLimited, _attempt, _dig, _float, _int, _upsert, fields_from_raw
from .models import BodyComposition, DailyMetrics, GarminProfile, LactateThreshold, PersonalRecord

logger = logging.getLogger(__name__)

BODY_DAYS = 30
BACKFILL_DAYS = 180
DELETION_PAGE = 100                 # R17: one listing call for the deletion check
FITNESS_AGE_EVERY_DAYS = 7          # backfill samples fitness age weekly, not daily
MAX_GEAR_STATS = 10


class _Runner:
    """Calls Garmin one endpoint at a time: breaker check, pause, 429 → stop."""

    def __init__(self, client):
        self.client = client
        self.calls = 0
        self.errors: list[str] = []

    def __call__(self, label: str, fn):
        from .tasks import garmin_blocked

        if garmin_blocked():
            raise RateLimited("circuit breaker open")
        if self.calls:
            pause = getattr(settings, "GARMIN_SLOW_PAUSE_S", 1.5)
            if pause:
                time.sleep(pause)
        self.calls += 1
        result = _attempt(label, "slow", fn)
        if result is None:
            self.errors.append(label)
        return result


def profile_for(athlete: Athlete) -> GarminProfile:
    profile, _ = GarminProfile.objects.get_or_create(athlete=athlete)
    return profile


def _user_profile_pk(athlete: Athlete, profile: GarminProfile, call) -> int | None:
    """Garmin's numeric profile id (needed for gear). From a stored sleep payload when
    possible, else one profile request."""
    if profile.user_profile_pk:
        return profile.user_profile_pk
    for raw in (DailyMetrics.objects.filter(athlete=athlete).exclude(raw={})
                .order_by("-metric_date").values_list("raw", flat=True)[:7]):
        pk = _int(_dig(raw, "sleep", "dailySleepDTO", "userProfilePK"))
        if pk:
            break
    else:
        payload = call("user profile", lambda: call.client.get_user_profile())
        pk = _int(_dig(payload, "id")) if isinstance(payload, dict) else None
    if pk:
        profile.user_profile_pk = pk
        profile.save(update_fields=["user_profile_pk", "updated_at"])
    return pk


# --- endurance score and fitness age ------------------------------------------------

def _store_day(athlete: Athlete, day: dt.date, raw: dict) -> bool:
    fields = fields_from_raw(raw)
    if len(fields) <= 1:            # only `raw`: nothing usable
        return False
    _upsert(athlete, day, fields)
    return True


def store_endurance_day(athlete: Athlete, day: dt.date, payload) -> bool:
    if not isinstance(payload, dict) or not payload.get("overallScore"):
        return False
    return _store_day(athlete, day, {"endurance_score": payload})


def store_endurance_range(athlete: Athlete, payload) -> int:
    """The range call aggregates weekly: each week's average lands on its first day."""
    written = 0
    groups = _dig(payload, "groupMap", default={}) or {}
    for key, group in groups.items() if isinstance(groups, dict) else []:
        score = _int(_dig(group, "groupAverage"))
        try:
            day = dt.date.fromisoformat(str(key)[:10])
        except ValueError:
            continue
        if score:
            _upsert(athlete, day, {"endurance_score": score})
            written += 1
    return written


def store_fitness_age(athlete: Athlete, profile: GarminProfile, day: dt.date, payload) -> bool:
    if not isinstance(payload, dict) or not payload.get("fitnessAge"):
        return False
    changed = []
    chrono = _int(payload.get("chronologicalAge"))
    achievable = _float(payload.get("achievableFitnessAge"))
    if chrono is not None and chrono != profile.chronological_age:
        profile.chronological_age = chrono
        changed.append("chronological_age")
    if achievable is not None and achievable != profile.achievable_fitness_age:
        profile.achievable_fitness_age = achievable
        changed.append("achievable_fitness_age")
    if changed:
        profile.save(update_fields=changed + ["updated_at"])
    return _store_day(athlete, day, {"fitness_age": payload})


# --- lactate threshold ----------------------------------------------------------------

def lt_speed_mps(value) -> float | None:
    """Garmin reports LT speed in tenths of m/s on some accounts (0.3138 for 3.138 m/s,
    a 5:19 /km pace). No runner's threshold is under 1 m/s (16:40 /km), so a value
    below 1 is read as tenths."""
    speed = _float(value)
    if not speed or speed <= 0:
        return None
    return speed * 10 if speed < 1.0 else speed


def _pace(speed: float | None) -> int | None:
    return round(1000 / speed) if speed else None


def _day(value) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def store_lactate(athlete: Athlete, day: dt.date | None, hr, speed, raw: dict) -> LactateThreshold | None:
    hr = _int(hr)
    speed = lt_speed_mps(speed)
    if day is None or (not hr and not speed):
        return None
    row, _ = LactateThreshold.objects.update_or_create(
        athlete=athlete, measured_on=day,
        defaults={"heart_rate": hr or None, "speed_mps": round(speed, 3) if speed else None,
                  "pace_s_per_km": _pace(speed), "raw": raw})
    return row


def store_lactate_latest(athlete: Athlete, payload) -> LactateThreshold | None:
    data = _dig(payload, "speed_and_heart_rate", default={}) or {}
    return store_lactate(athlete, _day(data.get("calendarDate")), data.get("heartRate"),
                         data.get("speed"), payload if isinstance(payload, dict) else {})


def store_lactate_range(athlete: Athlete, payload) -> int:
    """{"speed": [{from, value}], "heart_rate": [{from, value}]} merged by date."""
    by_day: dict[dt.date, dict] = {}
    for key in ("speed", "heart_rate"):
        for entry in _dig(payload, key, default=[]) or []:
            day = _day(entry.get("from") or entry.get("calendarDate")) if isinstance(entry, dict) else None
            if day is not None:
                by_day.setdefault(day, {})[key] = entry.get("value")
    written = 0
    for day, values in sorted(by_day.items()):
        if store_lactate(athlete, day, values.get("heart_rate"), values.get("speed"),
                         {"range": values}):
            written += 1
    return written


def apply_lactate_threshold(athlete: Athlete) -> bool:
    """Point the athlete's zones at the newest LT with a heart rate. Only when present
    and plausible; only rewrites when the value changed. Returns whether it changed.
    The easy-zone safety cap is applied when zones are built (analysis.zones)."""
    from analysis.zones import lt_plausible

    latest = (LactateThreshold.objects.filter(athlete=athlete, heart_rate__isnull=False)
              .order_by("-measured_on").first())
    pace_row = (LactateThreshold.objects.filter(athlete=athlete, pace_s_per_km__isnull=False)
                .order_by("-measured_on").first())
    if latest is None or not lt_plausible(latest.heart_rate, athlete.max_hr):
        return False
    if athlete.lt_date and latest.measured_on < athlete.lt_date:
        return False
    pace = pace_row.pace_s_per_km if pace_row else None
    unchanged = (athlete.lt_hr == latest.heart_rate and athlete.lt_pace_s == pace
                 and athlete.zones_source in (Athlete.ZonesSource.LT,
                                              Athlete.ZonesSource.PERCENT_MAX))
    if unchanged:
        if athlete.lt_date != latest.measured_on:
            athlete.lt_date = latest.measured_on
            athlete.save(update_fields=["lt_date", "updated_at"])
        return False
    athlete.lt_hr = latest.heart_rate
    athlete.lt_pace_s = pace
    athlete.lt_date = latest.measured_on
    # The athlete picked "same as Garmin": keep it, store the LT for reference only.
    if athlete.zones_source != Athlete.ZonesSource.PERCENT_MAX:
        athlete.zones_source = Athlete.ZonesSource.LT
    athlete.zones_updated_at = timezone.now()
    athlete.save(update_fields=["lt_hr", "lt_pace_s", "lt_date", "zones_source",
                                "zones_updated_at", "updated_at"])
    return True


# --- personal records ---------------------------------------------------------------

def store_records(athlete: Athlete, payload) -> int:
    from analysis.records import GARMIN_TYPES, parse_garmin

    raw_by_key = {GARMIN_TYPES[e["typeId"]][0]: e for e in payload
                  if isinstance(e, dict) and e.get("typeId") in GARMIN_TYPES} \
        if isinstance(payload, list) else {}
    entries = parse_garmin(payload)
    for entry in entries:
        PersonalRecord.objects.update_or_create(
            athlete=athlete, key=entry["key"],
            defaults={"value": entry["value"], "achieved_on": entry["date"],
                      "garmin_activity_id": entry["garmin_activity_id"],
                      "raw": raw_by_key.get(entry["key"], {})})
    return len(entries)


# --- body composition ---------------------------------------------------------------

def _kg(grams) -> float | None:
    value = _float(grams)
    return round(value / 1000, 2) if value else None


def store_body(athlete: Athlete, payload) -> int:
    """Garmin weights are grams. Several weigh-ins in a day: the latest wins."""
    entries = _dig(payload, "dateWeightList", default=[]) or []
    by_day: dict[dt.date, dict] = {}
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        day = _day(entry.get("calendarDate"))
        if day is None or not entry.get("weight"):
            continue
        current = by_day.get(day)
        if current is None or (entry.get("timestampGMT") or 0) >= (current.get("timestampGMT") or 0):
            by_day[day] = entry
    for day, entry in by_day.items():
        BodyComposition.objects.update_or_create(
            athlete=athlete, measured_on=day,
            defaults={"weight_kg": _kg(entry.get("weight")),
                      "body_fat_pct": _float(entry.get("bodyFat")),
                      "bmi": _float(entry.get("bmi")),
                      "muscle_mass_kg": _kg(entry.get("muscleMass")),
                      "raw": entry})
    mirror_latest_weight(athlete)
    return len(by_day)


def mirror_latest_weight(athlete: Athlete) -> bool:
    """A Garmin weigh-in newer than every weight entry becomes one (source garmin), so
    the profile weight — and Diet's targets — follow the scale."""
    latest = (BodyComposition.objects.filter(athlete=athlete, weight_kg__isnull=False)
              .order_by("-measured_on").first())
    if latest is None:
        return False
    stamp = _int((latest.raw or {}).get("timestampGMT"))
    recorded = (dt.datetime.fromtimestamp(stamp / 1000, tz=dt.timezone.utc) if stamp else
                dt.datetime.combine(latest.measured_on, dt.time(12, 0), tzinfo=dt.timezone.utc))
    newest = (MetricEntry.objects.filter(athlete=athlete, kind="weight")
              .order_by("-recorded_at").first())
    if newest is not None and newest.recorded_at >= recorded:
        return False
    MetricEntry.objects.create(athlete=athlete, kind="weight", value=latest.weight_kg,
                               recorded_at=recorded, source=MetricEntry.Source.GARMIN)
    return True


# --- gear -----------------------------------------------------------------------------

def store_gear(athlete: Athlete, gear_list, call=None) -> int:
    """Garmin's shoes -> Shoe rows (source garmin), plus distance from gear stats for
    the active ones. The athlete's own retire_km / default choice are kept."""
    from apps.gear.models import Shoe

    stored = 0
    stats_calls = 0
    for item in gear_list if isinstance(gear_list, list) else []:
        if not isinstance(item, dict) or not item.get("uuid"):
            continue
        if str(item.get("gearTypeName") or "").lower() != "shoes":
            continue
        make = str(item.get("gearMakeName") or "")
        model = str(item.get("gearModelName") or "")
        name = (item.get("displayName") or item.get("customMakeModel")
                or " ".join(p for p in (make, model) if p and p != "Other") or "Shoes")
        retired = str(item.get("gearStatusName") or "").lower() == "retired"
        max_m = _float(item.get("maximumMeters"))
        shoe, created = Shoe.objects.get_or_create(
            athlete=athlete, garmin_uuid=item["uuid"],
            defaults={"name": str(name)[:80], "source": Shoe.Source.GARMIN})
        shoe.name = str(name)[:80]
        shoe.brand = "" if make in ("", "Other") else make[:60]
        shoe.retired = retired
        shoe.garmin_max_km = round(max_m / 1000, 1) if max_m else None
        shoe.in_use_since = _day(item.get("dateBegin")) or shoe.in_use_since
        shoe.raw = item
        needs_stats = not retired or shoe.garmin_distance_m is None
        if call is not None and needs_stats and stats_calls < MAX_GEAR_STATS:
            stats_calls += 1
            stats = call("gear stats", lambda uuid=item["uuid"]: call.client.get_gear_stats(uuid))
            if isinstance(stats, dict) and stats:
                shoe.garmin_distance_m = _float(stats.get("totalDistance"))
                shoe.garmin_activities = _int(stats.get("totalActivities"))
        shoe.save()
        stored += 1
    return stored


# --- R12 §B4: watch alarms (read-only) --------------------------------------------------

MAX_DEVICES = 3


def store_watch_alarms(athlete: Athlete, profile: GarminProfile, call) -> int | None:
    """Read the alarms configured on the athlete's devices: get_devices(), then
    get_device_settings(deviceId) per device (each through the spaced runner). Only
    the `alarms` key is read; nothing is ever written to the device. Returns how many
    alarms were found, or None when the check is unavailable."""
    from analysis.wake import parse_alarm

    devices = call("devices", lambda: call.client.get_devices())
    alarms: list[dict] = []
    read_any = False
    for device in (devices if isinstance(devices, list) else [])[:MAX_DEVICES]:
        if not isinstance(device, dict) or not device.get("deviceId"):
            continue
        device_id = device["deviceId"]
        settings_payload = call("device settings",
                                lambda d=device_id: call.client.get_device_settings(d))
        if not isinstance(settings_payload, dict):
            continue
        read_any = True
        name = (device.get("productDisplayName") or device.get("displayName")
                or device.get("deviceTypeName") or None)
        for raw in settings_payload.get("alarms") or []:
            parsed = parse_alarm(raw, str(name)[:60] if name else None)
            if parsed:
                alarms.append(parsed)
    profile.watch_alarms = alarms if read_any else []
    profile.watch_alarms_available = read_any
    profile.watch_alarms_checked_on = athlete.local_today
    profile.save(update_fields=["watch_alarms", "watch_alarms_available",
                                "watch_alarms_checked_on", "updated_at"])
    return len(alarms) if read_any else None


# --- the daily run --------------------------------------------------------------------

def sync_slow(athlete: Athlete, client, *, force: bool = False) -> dict:
    """Once a day per athlete (force=True ignores the daily guard)."""
    profile = profile_for(athlete)
    today = athlete.local_today
    if profile.slow_synced_on == today and not force:
        return {"skipped": "already_today"}
    call = _Runner(client)
    done: dict = {}
    iso = today.isoformat()
    try:
        done["endurance"] = store_endurance_day(
            athlete, today, call("endurance score", lambda: client.get_endurance_score(iso)))
        done["fitness_age"] = store_fitness_age(
            athlete, profile, today, call("fitness age", lambda: client.get_fitnessage_data(iso)))
        store_lactate_latest(athlete, call("lactate threshold",
                                           lambda: client.get_lactate_threshold(latest=True)))
        done["zones_updated"] = apply_lactate_threshold(athlete)
        records = call("personal records", lambda: client.get_personal_record())
        done["records"] = store_records(athlete, records) if records else 0
        start = (today - dt.timedelta(days=BODY_DAYS)).isoformat()
        body = call("body composition", lambda: client.get_body_composition(start, iso))
        done["body"] = store_body(athlete, body) if body else 0
        pk = _user_profile_pk(athlete, profile, call)
        if pk:
            gear = call("gear", lambda: client.get_gear(str(pk)))
            done["shoes"] = store_gear(athlete, gear, call) if gear else 0
        done["watch_alarms"] = store_watch_alarms(athlete, profile, call)
        # R17: one listing call — activities RunCoach holds that Garmin no longer lists
        # become review questions (never deleted automatically).
        listing = call("activity list", lambda: client.get_activities(0, DELETION_PAGE))
        if isinstance(listing, list):
            from apps.activities.deletion import check_listing

            done["deleted_in_garmin"] = len(check_listing(
                athlete, listing, page_full=len(listing) >= DELETION_PAGE))
    except RateLimited as exc:
        logger.warning("garmin slow sync rate limited for %s: %s", athlete.pk, exc)
        return {**done, "rate_limited": True, "calls": call.calls}
    profile.slow_synced_on = today
    profile.save(update_fields=["slow_synced_on", "updated_at"])
    return {**done, "rate_limited": False, "calls": call.calls, "missing": call.errors}


def backfill(athlete: Athlete, client, days: int = BACKFILL_DAYS) -> dict:
    """The last `days` days of what the API offers as history: LT (range), endurance
    score (weekly range), body composition (range), fitness age (sampled weekly — it
    has no range call), plus PRs and gear. Stored sleep/training-status payloads are
    re-read for the new columns without any request."""
    from .garmin_wellness import backfill_from_raw

    profile = profile_for(athlete)
    today = athlete.local_today
    start = today - dt.timedelta(days=days)
    call = _Runner(client)
    done: dict = {"remapped_days": backfill_from_raw(athlete)}
    try:
        lt = call("lactate threshold range", lambda: client.get_lactate_threshold(
            latest=False, start_date=start.isoformat(), end_date=today.isoformat()))
        done["lactate"] = store_lactate_range(athlete, lt) if lt else 0
        store_lactate_latest(athlete, call("lactate threshold",
                                           lambda: client.get_lactate_threshold(latest=True)))
        done["zones_updated"] = apply_lactate_threshold(athlete)
        endurance = call("endurance range", lambda: client.get_endurance_score(
            start.isoformat(), today.isoformat()))
        done["endurance_weeks"] = store_endurance_range(athlete, endurance) if endurance else 0
        body = call("body composition", lambda: client.get_body_composition(
            start.isoformat(), today.isoformat()))
        done["body"] = store_body(athlete, body) if body else 0
        ages = 0
        for offset in range(0, days + 1, FITNESS_AGE_EVERY_DAYS):
            day = today - dt.timedelta(days=offset)
            iso = day.isoformat()
            payload = call("fitness age", lambda iso=iso: client.get_fitnessage_data(iso))
            ages += store_fitness_age(athlete, profile, day, payload)
        done["fitness_age_days"] = ages
        records = call("personal records", lambda: client.get_personal_record())
        done["records"] = store_records(athlete, records) if records else 0
        pk = _user_profile_pk(athlete, profile, call)
        if pk:
            gear = call("gear", lambda: client.get_gear(str(pk)))
            done["shoes"] = store_gear(athlete, gear, call) if gear else 0
    except RateLimited as exc:
        logger.warning("garmin backfill rate limited for %s: %s", athlete.pk, exc)
        return {**done, "rate_limited": True, "calls": call.calls}
    profile.backfilled_on = today
    profile.slow_synced_on = today
    profile.save(update_fields=["backfilled_on", "slow_synced_on", "updated_at"])
    return {**done, "rate_limited": False, "calls": call.calls, "missing": call.errors}
