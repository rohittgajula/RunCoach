"""R13 §2: GET /races/{id}/plan/ — the race-day planner (maths in planning/race_day.py)."""

from __future__ import annotations

import datetime as dt

from planning import race_day as maths

from .models import Race
from .serializers import RaceSerializer

GARMIN_KM = {5.0: "race_pred_5k_s", 10.0: "race_pred_10k_s", 21.1: "race_pred_half_s",
             42.2: "race_pred_marathon_s"}
RIEGEL = 1.06
FORECAST_DAYS = 7



def _race_sweat_rate(athlete, hour: dict | None) -> float | None:
    """His measured sweat rate for the weather forecast at the start, when he has
    done a sweat test. Decides how much he carries and how often he stops, so the
    band average is the one number here most worth replacing with a real one."""
    try:
        from analysis.weather_advice import _base, heat_band
        from apps.health.sweat_service import measured_rate

        band = _base(heat_band((hour or {}).get("feels_like"), (hour or {}).get("dew_point")))
        return measured_rate(athlete, band)
    except Exception:  # noqa: BLE001
        return None

def garmin_prediction(athlete, distance_km: float) -> float | None:
    """Garmin's own race prediction for this distance (Riegel from the nearest one)."""
    from apps.ingest.models import DailyMetrics

    row = (DailyMetrics.objects.filter(athlete=athlete).exclude(race_pred_10k_s__isnull=True)
           .order_by("-metric_date").first())
    if row is None:
        return None
    known = [(km, getattr(row, field)) for km, field in GARMIN_KM.items() if getattr(row, field)]
    if not known:
        return None
    km, seconds = min(known, key=lambda k: abs(k[0] - distance_km))
    if abs(km - distance_km) < 0.15:
        return float(seconds)
    return seconds * (distance_km / km) ** RIEGEL


def _own_prediction(athlete, race) -> float | None:
    from .services import prediction_for

    try:
        prediction = prediction_for(athlete, race)
    except Exception:  # noqa: BLE001 — a prediction failure must not break the plan
        return None
    return prediction.likely_finish_s


def _forecast_hour(athlete, race: Race, start_min: int, today: dt.date) -> dict | None:
    if not 0 <= (race.date - today).days <= FORECAST_DAYS:
        return None
    from apps.ingest import weather
    from apps.ingest.weather_services import refresh_location

    refresh_location(athlete)
    if athlete.location_lat is None or athlete.location_lon is None:
        return None
    fc = weather.forecast_week(athlete.location_lat, athlete.location_lon,
                               athlete.timezone or "UTC")
    return weather.hour_at(fc, race.date, start_min // 60)


def _sleep_avg(athlete, today: dt.date) -> float | None:
    from apps.ingest.models import DailyMetrics

    values = [r for r in DailyMetrics.objects.filter(
        athlete=athlete, metric_date__gt=today - dt.timedelta(days=7), metric_date__lte=today,
        sleep_seconds__isnull=False).values_list("sleep_seconds", flat=True)]
    return round(sum(values) / len(values) / 3600, 1) if values else None


def race_plan(athlete, race: Race, strategy: str) -> dict:
    from apps.health.injury import current_shoe

    today = athlete.local_today
    start_min = (race.start_time.hour * 60 + race.start_time.minute if race.start_time
                 else maths.DEFAULT_START_MIN)
    hour = _forecast_hour(athlete, race, start_min, today)
    weather = maths.weather_block(hour, race.date, maths.clock(start_min // 60 * 60))
    slowdown = weather["pace_slowdown_pct"] if weather else 0
    target = maths.target(race.distance_km, race.goal_time_s, _own_prediction(athlete, race),
                          garmin_prediction(athlete, race.distance_km), slowdown)
    splits = maths.splits(race.distance_km, target["time_s"], strategy) if target else []
    duration = target["time_s"] if target else None
    fueling = maths.fueling(duration, target["pace_s_per_km"] if target else None,
                            hour.get("feels_like") if hour else None,
                            hour.get("dew_point") if hour else None, race.distance_km,
                            _race_sweat_rate(athlete, hour))
    return {
        "race": RaceSerializer(race).data, "strategy": strategy,
        "available": target is not None, "reason": None if target else "no_target",
        "start_time": maths.clock(start_min),
        "start_time_source": "race" if race.start_time else "default",
        "days_to_race": (race.date - today).days,
        "target": target, "splits": splits, "fueling": fueling, "weather": weather,
        "warmup": maths.warmup(race.distance_km),
        "taper": maths.taper(race.date, today, race.distance_km, _sleep_avg(athlete, today),
                             current_shoe(athlete)),
        "morning": maths.morning(start_min, race.distance_km),
    }
