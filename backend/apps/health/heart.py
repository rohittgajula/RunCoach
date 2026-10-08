"""R14 §9: `GET /health/heart/` — heart adaptation run by run.

The maths is analysis/heart_adaptation.py (pure). Here: load each run's records and
run/walk blocks, cache the per-run numbers (RunHeartStats — they read every record),
attach the weather at the run's start (ActivityWeather, filled by a task from
Open-Meteo's archive) and put the response together.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis import heart_adaptation as maths

from .common import BadRequest
from .models import ActivityWeather, RunHeartStats
from .period import parse_period

logger = logging.getLogger(__name__)

VERSION = "h1"
EDGE_RUNS = 6            # first/last runs of all history, for "since day 1"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
ARCHIVE_LAG_DAYS = 6
WEATHER_GIVE_UP_DAYS = 10
WEATHER_BATCH = 60


def references(request, athlete) -> tuple[int, int]:
    def number(name, lo, hi, default):
        raw = request.query_params.get(name)
        if raw in (None, ""):
            return default
        try:
            value = int(raw)
        except ValueError as exc:
            raise BadRequest(f"{name} must be a whole number {lo}–{hi}.") from exc
        if not lo <= value <= hi:
            raise BadRequest(f"{name} must be a whole number {lo}–{hi}.")
        return value

    default_hr = max(100, min(190, (athlete.hr_ceiling or 155) - 5))
    default_pace = int(round(((athlete.easy_pace_min or 600) + (athlete.easy_pace_max or 645)) / 2))
    return number("ref_hr", 100, 200, default_hr), number("ref_pace", 180, 1200, default_pace)


def _runs(athlete):
    from apps.activities.models import Activity

    return (Activity.objects.filter(athlete=athlete, sport__icontains="run",
                                    segmentation_version__isnull=False)
            .exclude(quality__decision="exclude")         # R17: explicit choice only
            .order_by("started_at", "id"))


def run_stats(activity, *, ref_hr: int, ref_pace: int) -> dict:
    from apps.activities.models import Segment

    try:
        weather = activity.weather
    except ActivityWeather.DoesNotExist:
        weather = None
    feels = weather.feels_like_c if weather is not None else None
    from apps.activities.quality import effective_use, series

    use = effective_use(activity)
    key = f"{VERSION}:{activity.segmentation_version}:{ref_hr}:{ref_pace}:{feels}:{use[0]}"
    cached = RunHeartStats.objects.filter(activity=activity).first()
    if cached is not None and cached.key == key:
        return cached.payload
    points = [maths.Point(r["offset_s"], r["heart_rate"], r["speed_mps"], r["altitude_m"])
              for r in series(activity, ("heart_rate", "speed_mps", "altitude_m"), use=use)]
    blocks = [maths.Block(kind, start, duration) for kind, start, duration in
              Segment.objects.filter(activity=activity).order_by("index")
              .values_list("kind", "start_offset_s", "duration_s")]
    payload = maths.analyse_run(points, blocks, ref_hr=ref_hr, ref_pace=ref_pace,
                                feels_like=feels)
    RunHeartStats.objects.update_or_create(activity=activity,
                                           defaults={"key": key, "payload": payload})
    return payload


def _row(activity, stats: dict) -> dict:
    return {"activity_id": activity.pk, "date": activity.local_date,
            "started_at": activity.started_at, **stats}


def payload(athlete, period, ref_hr: int, ref_pace: int) -> dict:
    runs_qs = _runs(athlete).select_related("weather")
    in_range = list(runs_qs.filter(local_date__gte=period.start, local_date__lte=period.end))
    first = list(runs_qs[:EDGE_RUNS])
    last = list(runs_qs.order_by("-started_at", "-id")[:EDGE_RUNS])
    computed = {}
    for activity in {a.pk: a for a in first + in_range + last}.values():
        computed[activity.pk] = _row(activity, run_stats(activity, ref_hr=ref_hr,
                                                         ref_pace=ref_pace))
    rows = [computed[a.pk] for a in in_range]
    edges = sorted({**{a.pk: computed[a.pk] for a in first},
                    **{a.pk: computed[a.pk] for a in last}}.values(),
                   key=lambda r: (r["started_at"], r["activity_id"]))
    total = runs_qs.count()
    # The snapshot uses the first and last runs of ALL history (the edges); with few runs
    # the two overlap, which since_day1 handles by halving.
    day1 = maths.since_day1(edges if total > 2 * EDGE_RUNS else
                            [computed[a.pk] for a in runs_qs], ref_hr=ref_hr, ref_pace=ref_pace)
    trend = maths.rolling_trend(rows)
    trend_cool = maths.rolling_trend([r for r in rows if r.get("hot") is not True])
    missing = [a.pk for a in in_range if not _has_weather(a)]
    if missing:
        try:
            from .tasks import heart_weather_task

            heart_weather_task.delay(athlete.pk)
        except Exception:  # noqa: BLE001 — no broker: the numbers are still right
            logger.debug("could not queue heart weather for %s", athlete.pk)
    sentences = list(day1["sentences"]) if day1 else []
    heat = maths.heat_view(rows)
    if heat["sentence"]:
        sentences.append(heat["sentence"])
    return {"range": period.range_key, "start": period.start, "end": period.end,
            "ref_hr": ref_hr, "ref_hr_band": maths.REF_HR_BAND, "ref_pace_s_per_km": ref_pace,
            "ref_pace_band_s": maths.REF_PACE_BAND_S, "hot_threshold_c": maths.HOT_FEELS_C,
            "runs": rows, "trend": trend, "trend_cool": trend_cool,
            "since_day1": day1, "heat": heat,
            "headline": maths.headline(day1, rows, ref_hr), "sentences": sentences,
            "key_numbers": maths.key_numbers(trend, day1["first"] if day1 else None, ref_hr),
            "weather_pending": bool(missing), "caveat": maths.CAVEAT}


def _has_weather(activity) -> bool:
    try:
        return activity.weather is not None
    except ActivityWeather.DoesNotExist:
        return False


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def heart(request):
    athlete = request.user.athlete
    period = parse_period(request, athlete, "3m", extra={"all": 730})
    ref_hr, ref_pace = references(request, athlete)
    return Response(payload(athlete, period, ref_hr, ref_pace))


# --- weather at run time -------------------------------------------------------------------

def _start_place(activity, athlete) -> tuple[float, float] | None:
    from apps.activities.models import ActivityRecord
    from apps.ingest.weather import round_coord

    row = (ActivityRecord.objects.filter(activity=activity, latitude__isnull=False,
                                         longitude__isnull=False)
           .order_by("offset_s").values_list("latitude", "longitude").first())
    if row:
        return round_coord(row[0]), round_coord(row[1])
    if athlete.location_lat is not None and athlete.location_lon is not None:
        return athlete.location_lat, athlete.location_lon
    return None


def fill_weather(athlete) -> int:
    """Store the weather at the start of runs that have none yet. Returns rows stored."""
    from apps.ingest import weather as wx

    today = timezone.now().date()
    todo = [a for a in _runs(athlete).filter(weather__isnull=True)[:WEATHER_BATCH]]
    groups: dict[tuple, list] = {}
    for activity in todo:
        place = _start_place(activity, athlete)
        if place is None:
            # No GPS and no location on the profile: nothing to look up, ever.
            ActivityWeather.objects.update_or_create(activity=activity,
                                                     defaults={"source": "none"})
            continue
        groups.setdefault(place, []).append(activity)
    stored = 0
    for (lat, lon), acts in groups.items():
        hours: dict[str, dict] = {}
        old = [a for a in acts if (today - a.started_at.date()).days > ARCHIVE_LAG_DAYS]
        new = [a for a in acts if a not in old]
        hourly = "temperature_2m,apparent_temperature,dew_point_2m,relative_humidity_2m"
        try:
            if old:
                data = wx._get_json(ARCHIVE_URL, {
                    "latitude": lat, "longitude": lon, "hourly": hourly, "timezone": "UTC",
                    "start_date": min(a.started_at.date() for a in old).isoformat(),
                    "end_date": max(a.started_at.date() for a in old).isoformat()})
                hours.update(_index(data))
            if new:
                data = wx._get_json(wx.FORECAST_URL, {
                    "latitude": lat, "longitude": lon, "hourly": hourly, "timezone": "UTC",
                    "past_days": 7, "forecast_days": 1})
                hours.update(_index(data))
        except wx.WeatherUnavailable as exc:
            logger.info("heart weather unavailable for %s: %s", athlete.pk, exc)
            continue
        for activity in acts:
            at = activity.started_at.astimezone(dt.timezone.utc)
            key = at.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:00")
            row = hours.get(key)
            if row and row.get("apparent_temperature") is not None:
                ActivityWeather.objects.update_or_create(activity=activity, defaults={
                    "temp_c": row.get("temperature_2m"),
                    "feels_like_c": row.get("apparent_temperature"),
                    "dew_point_c": row.get("dew_point_2m"),
                    "humidity": row.get("relative_humidity_2m"), "source": "archive"})
                stored += 1
            elif (today - at.date()).days > WEATHER_GIVE_UP_DAYS:
                ActivityWeather.objects.update_or_create(activity=activity,
                                                         defaults={"source": "none"})
    return stored


def _index(data: dict) -> dict[str, dict]:
    hourly = (data or {}).get("hourly") or {}
    out = {}
    for i, time in enumerate(hourly.get("time") or []):
        out[time[:16]] = {k: (hourly.get(k) or [None] * (i + 1))[i]
                          if i < len(hourly.get(k) or []) else None
                          for k in ("temperature_2m", "apparent_temperature", "dew_point_2m",
                                    "relative_humidity_2m")}
    return out
