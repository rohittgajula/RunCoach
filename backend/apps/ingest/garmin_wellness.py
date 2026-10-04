"""Pull daily wellness metrics from Garmin Connect.

Written defensively on purpose. Garmin's unofficial endpoints return different shapes
depending on device, subscription tier and whether the watch was worn overnight, and
several return `None` or an empty dict rather than erroring. Every read goes through
`_dig`, and one endpoint failing never aborts the day or the run — a partial row is
far more useful than no row.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from apps.athletes.models import Athlete

from .models import DailyMetrics

logger = logging.getLogger(__name__)


def _dig(payload: Any, *path, default=None):
    """Walk nested dict/list keys, returning default at the first miss."""
    current = payload
    for key in path:
        if current is None:
            return default
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, list):
            if not current:
                return default
            current = current[key] if isinstance(key, int) else None
        else:
            return default
    return default if current is None else current


def _int(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _float(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _humanise(phrase: str) -> str:
    """'RECOVERY_1' -> 'Recovery'. Garmin suffixes a variant number per phrase."""
    if not phrase:
        return ""
    tail = phrase.rsplit("_", 1)[-1]
    base = phrase.rsplit("_", 1)[0] if tail.isdigit() else phrase
    return base.replace("_", " ").title()[:40]


def _local_dt(value) -> dt.datetime | None:
    """Garmin's *TimestampLocal fields are epoch-ms ALREADY shifted to local wall
    time, so reading them as UTC gives the clock reading the athlete saw. Applying a
    timezone on top double-counts the offset — which turned a 02:06 bedtime into
    07:36 and made last night's sleep look like a morning nap."""
    try:
        return dt.datetime.utcfromtimestamp(int(value) / 1000)
    except (TypeError, ValueError, OSError):
        return None


# (raw key, label, client call). Each is one request, wrapped on its own: one endpoint
# failing — or not existing on this account — never loses the rest of the day.
DAILY_ENDPOINTS = (
    ("sleep", "sleep", lambda c, iso: c.get_sleep_data(iso)),
    ("training_readiness", "training readiness", lambda c, iso: c.get_training_readiness(iso)),
    ("training_status", "training status", lambda c, iso: c.get_training_status(iso)),
    ("hrv", "hrv", lambda c, iso: c.get_hrv_data(iso)),
    ("rhr", "resting hr", lambda c, iso: c.get_rhr_day(iso)),
    ("stats", "daily stats", lambda c, iso: c.get_stats(iso)),
    ("max_metrics", "vo2max", lambda c, iso: c.get_max_metrics(iso)),
    ("respiration", "respiration", lambda c, iso: c.get_respiration_data(iso)),
)


class RateLimited(Exception):
    """A 429 inside one endpoint. Stops the whole wellness run (the limit is per IP)."""


def _attempt(label: str, iso: str, fn):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — a missing metric is not a sync failure
        if "429" in str(exc) or "TooManyRequests" in str(exc):
            raise RateLimited(str(exc)) from exc
        logger.debug("garmin %s unavailable for %s: %s", label, iso, exc)
        return None


def fetch_day(client, day: dt.date) -> dict:
    """Collect one day's metrics. Each endpoint is isolated so one failure is partial."""
    iso = day.isoformat()
    raw: dict = {}
    for key, label, call in DAILY_ENDPOINTS:
        payload = _attempt(label, iso, lambda: call(client, iso))
        if payload:
            raw[key] = payload
    return fields_from_raw(raw)


def fields_from_raw(raw: dict) -> dict:
    """Map stored payloads to columns. Also used to backfill new columns from `raw`
    without asking Garmin again."""
    out: dict = {}

    sleep = raw.get("sleep")
    if sleep:
        daily = _dig(sleep, "dailySleepDTO", default={}) or {}
        out.update(
            sleep_seconds=_int(daily.get("sleepTimeSeconds")),
            sleep_need_seconds=(
                _int(_dig(daily, "sleepNeed", "actual"))
                or _int(daily.get("sleepNeedSeconds"))
                or _int(_dig(daily, "sleepScores", "totalDuration", "optimalStart"))
            ),
            sleep_score=_int(_dig(daily, "sleepScores", "overall", "value")),
            deep_sleep_seconds=_int(daily.get("deepSleepSeconds")),
            light_sleep_seconds=_int(daily.get("lightSleepSeconds")),
            rem_sleep_seconds=_int(daily.get("remSleepSeconds")),
            awake_seconds=_int(daily.get("awakeSleepSeconds")),
            sleep_start_local=_local_dt(daily.get("sleepStartTimestampLocal")),
            sleep_end_local=_local_dt(daily.get("sleepEndTimestampLocal")),
            hrv_overnight_avg=_int(_dig(sleep, "avgOvernightHrv")),
            respiration_sleep_avg=_float(daily.get("averageRespirationValue")),
        )

    readiness = raw.get("training_readiness")
    if readiness:
        first = readiness[0] if isinstance(readiness, list) and readiness else readiness
        out.update(
            training_readiness=_int(_dig(first, "score")),
            training_readiness_level=str(_dig(first, "level", default="") or "")[:32],
        )

    status = raw.get("training_status")
    if status:
        recent = _dig(status, "mostRecentTrainingStatus", "latestTrainingStatusData",
                      default={}) or {}
        device = next(iter(recent.values()), {}) if isinstance(recent, dict) else {}

        # `trainingStatus` is an opaque numeric code; the feedback phrase is the
        # label Garmin itself shows.
        out["training_status"] = _humanise(
            str(device.get("trainingStatusFeedbackPhrase") or "")
        ) or str(device.get("trainingStatus") or "")[:40]

        acwr = _dig(device, "acuteTrainingLoadDTO", default={}) or {}
        acute = _float(acwr.get("dailyTrainingLoadAcute"))
        chronic = _float(acwr.get("dailyTrainingLoadChronic"))
        if acute is not None:
            out["acute_load"] = acute
        if chronic is not None:
            out["chronic_load"] = chronic
        # Deliberately NOT derived from acwrPercent when Garmin omits chronic: on this
        # account it was the acute value with the decimal point moved, every day.

    hrv = raw.get("hrv")
    if hrv:
        summary = _dig(hrv, "hrvSummary", default={}) or {}
        out["hrv_status"] = str(summary.get("status") or "")[:24]
        out["hrv_overnight_avg"] = out.get("hrv_overnight_avg") or _int(summary.get("lastNightAvg"))
        out["hrv_weekly_avg"] = _int(summary.get("weeklyAvg"))
        out["hrv_baseline_low"] = _int(_dig(summary, "baseline", "balancedLow"))
        out["hrv_baseline_high"] = _int(_dig(summary, "baseline", "balancedUpper"))

    rhr = raw.get("rhr")
    if rhr:
        values = _dig(rhr, "allMetrics", "metricsMap",
                      "WELLNESS_RESTING_HEART_RATE", default=[]) or []
        if values:
            out["resting_hr"] = _int(_dig(values, 0, "value"))

    stats = raw.get("stats")
    if stats:
        moderate = _int(stats.get("moderateIntensityMinutes"))
        vigorous = _int(stats.get("vigorousIntensityMinutes"))
        out.update(
            steps=_int(stats.get("totalSteps")),
            stress_avg=_int(stats.get("averageStressLevel")),
            body_battery_high=_int(stats.get("bodyBatteryHighestValue")),
            body_battery_low=_int(stats.get("bodyBatteryLowestValue")),
            floors_climbed=_int(stats.get("floorsAscended")),
            # Garmin's own convention: a vigorous minute counts double.
            intensity_minutes=(
                (moderate or 0) + 2 * (vigorous or 0)
                if moderate is not None or vigorous is not None else None
            ),
            spo2_avg=_int(stats.get("averageSpo2")),
            respiration_avg=_float(stats.get("avgWakingRespirationValue")),
        )
        out["resting_hr"] = out.get("resting_hr") or _int(stats.get("restingHeartRate"))

    respiration = raw.get("respiration")
    if respiration:
        out["respiration_avg"] = out.get("respiration_avg") or _float(
            respiration.get("avgWakingRespirationValue"))
        out["respiration_sleep_avg"] = out.get("respiration_sleep_avg") or _float(
            respiration.get("avgSleepRespirationValue"))

    vo2 = raw.get("max_metrics")
    if vo2:
        first = vo2[0] if isinstance(vo2, list) and vo2 else vo2
        out["vo2max"] = (
            _float(_dig(first, "generic", "vo2MaxPreciseValue"))
            or _float(_dig(first, "generic", "vo2MaxValue"))
        )

    predictions = raw.get("race_predictions")
    if predictions:
        first = predictions[0] if isinstance(predictions, list) and predictions else predictions
        out.update(
            race_pred_5k_s=_int(_dig(first, "time5K")),
            race_pred_10k_s=_int(_dig(first, "time10K")),
            race_pred_half_s=_int(_dig(first, "timeHalfMarathon")),
            race_pred_marathon_s=_int(_dig(first, "timeMarathon")),
        )

    # Drop empties so an existing row is never overwritten with None by a day where
    # one endpoint happened to fail.
    cleaned = {k: v for k, v in out.items() if v not in (None, "")}
    if raw:
        cleaned["raw"] = raw
    return cleaned


FIRST_SYNC_DAYS = 28


def days_to_fetch(athlete: Athlete) -> int:
    """28 days on the first sync; afterwards from the last stored day (re-fetched,
    because last night's sleep and today's totals keep changing) up to today."""
    last = (
        DailyMetrics.objects.filter(athlete=athlete)
        .order_by("-metric_date").values_list("metric_date", flat=True).first()
    )
    if last is None:
        return FIRST_SYNC_DAYS
    return max(2, min(FIRST_SYNC_DAYS, (athlete.local_today - last).days + 1))


def _upsert(athlete: Athlete, day: dt.date, payload: dict) -> None:
    """Merge into the day's row: new raw payloads join the stored ones rather than
    replacing them, so a partial day never erases what an earlier sync captured."""
    existing = DailyMetrics.objects.filter(athlete=athlete, metric_date=day).first()
    if existing is not None and payload.get("raw"):
        payload = {**payload, "raw": {**(existing.raw or {}), **payload["raw"]}}
    DailyMetrics.objects.update_or_create(athlete=athlete, metric_date=day, defaults=payload)


def sync_wellness(athlete: Athlete, client, days: int | None = None) -> dict:
    """Upsert wellness metrics for the last `days` days (default: see days_to_fetch)."""
    # athlete.local_today, never timezone.localdate() — at 00:48 in Kolkata the
    # latter still says yesterday and the newest day is silently skipped.
    today = athlete.local_today
    days = days or days_to_fetch(athlete)
    written = empty = 0
    rate_limited = False

    for offset in range(days):
        day = today - dt.timedelta(days=offset)
        try:
            payload = fetch_day(client, day)
        except RateLimited:
            logger.warning("rate limited during wellness sync, stopping at %s", day)
            rate_limited = True
            break
        except Exception:  # noqa: BLE001
            logger.exception("wellness fetch failed for %s", day)
            continue

        if not payload:
            empty += 1
            continue

        _upsert(athlete, day, payload)
        written += 1

    # Race predictions are "as of now", so one request per sync, stored on today.
    if not rate_limited:
        try:
            predictions = _attempt("race predictions", today.isoformat(),
                                   lambda: client.get_race_predictions())
        except RateLimited:
            predictions, rate_limited = None, True
        if predictions:
            fields = fields_from_raw({"race_predictions": predictions})
            if len(fields) > 1:
                _upsert(athlete, today, fields)

    return {"days_written": written, "days_empty": empty, "rate_limited": rate_limited}


def backfill_from_raw(athlete: Athlete | None = None) -> int:
    """Re-map every stored day from its raw payloads (new columns, no Garmin calls)."""
    rows = DailyMetrics.objects.all()
    if athlete is not None:
        rows = rows.filter(athlete=athlete)
    updated = 0
    for row in rows:
        fields = fields_from_raw(row.raw or {})
        fields.pop("raw", None)
        changed = [k for k, v in fields.items() if getattr(row, k) != v]
        if changed:
            for key in changed:
                setattr(row, key, fields[key])
            row.save(update_fields=changed + ["updated_at"])
            updated += 1
    return updated
