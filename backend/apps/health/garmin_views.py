"""R10 §B endpoints: fitness trend, training status, sleep details, running form,
personal records and body composition. Rows in; the maths is in analysis/."""

from __future__ import annotations

import datetime as dt

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis import body as body_maths
from analysis import form as form_maths
from analysis import records as record_maths
from analysis import sleep as sleep_maths
from analysis.training_status import status_key
from apps.activities.models import Activity
from apps.ingest.models import BodyComposition, GarminProfile, LactateThreshold, PersonalRecord

from analysis.buckets import bucket

from .common import first_last_change, metrics_rows
from .period import as_period, parse_period

ZONES_UPDATED_DAYS = 14
STATUS_LOOKBACK_DAYS = 60


def _series(rows, attr, digits=1):
    out = []
    for r in rows:
        value = getattr(r, attr)
        if value is None:
            continue
        out.append({"date": r.metric_date, "value": round(value) if digits == 0
                    else round(value, digits)})
    return out


def _pred(row) -> dict | None:
    if row is None:
        return None
    return {"5k_s": row.race_pred_5k_s, "10k_s": row.race_pred_10k_s,
            "half_s": row.race_pred_half_s, "marathon_s": row.race_pred_marathon_s}


def zones_json(athlete):
    from apps.athletes.serializers import AthleteSerializer

    return AthleteSerializer().get_zones(athlete)


# --- B1/B3 fitness ------------------------------------------------------------------

def fitness_payload(athlete, period) -> dict:
    period = as_period(athlete, period)
    start, end, freq = period.start, period.end, period.freq
    rows = metrics_rows(athlete, start, end)
    profile = GarminProfile.objects.filter(athlete=athlete).first()

    vo2 = _series(rows, "vo2max", 1)
    ages = _series(rows, "fitness_age", 1)
    endurance = _series(rows, "endurance_score", 0)
    level = next((r.endurance_level for r in reversed(rows)
                  if r.endurance_score and r.endurance_level), None)
    preds = [r for r in rows if r.race_pred_5k_s or r.race_pred_10k_s
             or r.race_pred_half_s or r.race_pred_marathon_s]

    lt_rows = list(LactateThreshold.objects.filter(athlete=athlete).order_by("measured_on"))
    latest_lt = lt_rows[-1] if lt_rows else None
    lactate = None
    if latest_lt is not None:
        updated_at = athlete.zones_updated_at if athlete.zones_source == "lactate_threshold" else None
        lactate = {
            "hr": athlete.lt_hr or next((r.heart_rate for r in reversed(lt_rows) if r.heart_rate), None),
            "pace_s_per_km": athlete.lt_pace_s or next(
                (r.pace_s_per_km for r in reversed(lt_rows) if r.pace_s_per_km), None),
            "date": athlete.lt_date or latest_lt.measured_on,
            "source": "garmin",
            "zones_updated": bool(updated_at and (dt.datetime.now(dt.timezone.utc) - updated_at)
                                  < dt.timedelta(days=ZONES_UPDATED_DAYS)),
            "zones_updated_at": updated_at,
            "series": [{"date": r.measured_on, "hr": r.heart_rate,
                        "pace_s_per_km": r.pace_s_per_km}
                       for r in lt_rows if start <= r.measured_on <= end],
        }

    if lactate is not None:
        lactate["series"] = bucket(lactate["series"], freq, "last")
    return {
        **period.ranged(),
        "vo2max": {"current": vo2[-1]["value"] if vo2 else None,
                   "change": first_last_change([p["value"] for p in vo2], 1),
                   "series": bucket(vo2, freq, "last")},
        "fitness_age": {"current": ages[-1]["value"] if ages else None,
                        "chronological_age": profile.chronological_age if profile else None,
                        "achievable": profile.achievable_fitness_age if profile else None,
                        "change": first_last_change([p["value"] for p in ages], 1),
                        "series": bucket(ages, freq, "last")},
        "endurance_score": {"current": endurance[-1]["value"] if endurance else None,
                            "level": level or None,
                            "change": first_last_change([p["value"] for p in endurance], 0),
                            "series": bucket(endurance, freq, "last")},
        "race_predictions": {
            "current": _pred(preds[-1]) if preds else None,
            "previous": _pred(preds[0]) if len(preds) > 1 else None,
            "as_of": preds[-1].metric_date if preds else None,
            "previous_as_of": preds[0].metric_date if len(preds) > 1 else None,
            "series": bucket([{"date": r.metric_date, **_pred(r)} for r in preds], freq, "last"),
        },
        "lactate_threshold": lactate,
        "zones": zones_json(athlete),
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def fitness(request):
    athlete = request.user.athlete
    return Response(fitness_payload(athlete, parse_period(request, athlete, "6m")))


# --- B2 training status -------------------------------------------------------------

def training_status_payload(athlete, period=None) -> dict:
    period = as_period(athlete, period or "4w")
    today = athlete.local_today
    rows = metrics_rows(athlete, today - dt.timedelta(days=STATUS_LOOKBACK_DAYS), today)
    history_rows = metrics_rows(athlete, period.start, period.end)
    status_row = next((r for r in reversed(rows) if r.training_status), None)
    load_row = next((r for r in reversed(rows)
                     if r.acute_load is not None or r.chronic_load is not None), None)
    focus_row = next((r for r in reversed(rows) if r.load_focus), None)
    acute = load_row.acute_load if load_row else None
    chronic = load_row.chronic_load if load_row else None
    history = [{"date": r.metric_date, "status_key": status_key(r.training_status),
                "acute_load": r.acute_load, "chronic_load": r.chronic_load}
               for r in history_rows if r.training_status or r.acute_load is not None]
    return {
        **period.ranged(),
        "date": status_row.metric_date if status_row else None,
        "status": status_row.training_status if status_row else None,
        "status_key": status_key(status_row.training_status) if status_row else None,
        "acute_load": acute, "chronic_load": chronic,
        "acwr": round(acute / chronic, 2) if acute is not None and chronic else None,
        "load_focus": ({"date": focus_row.metric_date, "period_days": 28,
                        "feedback": focus_row.load_focus.get("feedback"),
                        "items": focus_row.load_focus.get("items", [])}
                       if focus_row else None),
        "history": bucket(history, period.freq,
                          {"status_key": "last", "*": "mean"}, digits=1),
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def training_status(request):
    athlete = request.user.athlete
    return Response(training_status_payload(athlete, parse_period(request, athlete, "4w")))


# --- B4 sleep -------------------------------------------------------------------------

def _night(r, need: dict | None = None) -> dict:
    from apps.athletes.effective import night_need_s

    return {"date": r.metric_date, "sleep_s": r.sleep_seconds,
            # R18: the athlete's own need (memory / setting) when set, else Garmin's.
            "need_s": night_need_s(need, r.sleep_need_seconds) if need else r.sleep_need_seconds,
            "garmin_need_s": r.sleep_need_seconds,
            "score": r.sleep_score, "deep_s": r.deep_sleep_seconds,
            "light_s": r.light_sleep_seconds, "rem_s": r.rem_sleep_seconds,
            "awake_s": r.awake_seconds,
            "bedtime": r.sleep_start_local.strftime("%Y-%m-%dT%H:%M") if r.sleep_start_local else None,
            "wake_time": r.sleep_end_local.strftime("%Y-%m-%dT%H:%M") if r.sleep_end_local else None,
            "restless_moments": r.restless_moments, "spo2_avg": r.sleep_spo2_avg,
            "spo2_low": r.sleep_spo2_low, "breathing_rate": r.respiration_sleep_avg,
            # internal, for averages (never serialised)
            "bedtime_dt": r.sleep_start_local, "wake_dt": r.sleep_end_local}


def _has_sleep(r) -> bool:
    return bool(r.sleep_seconds or r.sleep_score or r.sleep_start_local)


def _public(night: dict) -> dict:
    return {k: v for k, v in night.items() if not k.endswith("_dt")}


def _clock_h(value: dt.datetime | None, bedtime: bool) -> float | None:
    if value is None:
        return None
    hours = value.hour + value.minute / 60
    if bedtime and hours < 12:
        hours += 24          # after midnight counts as 24:xx
    return round(hours, 2)


def _sleep_point(n: dict) -> dict:
    return {"date": n["date"], "sleep_s": n["sleep_s"], "need_s": n["need_s"],
            "score": n["score"], "deep_s": n["deep_s"], "light_s": n["light_s"],
            "rem_s": n["rem_s"], "awake_s": n["awake_s"],
            "restless_moments": n["restless_moments"], "spo2_avg": n["spo2_avg"],
            "breathing_rate": n["breathing_rate"],
            "bedtime_h": _clock_h(n["bedtime_dt"], True),
            "wake_h": _clock_h(n["wake_dt"], False)}


def sleep_payload(athlete, period) -> dict:
    from apps.habits.services import _runs

    period = as_period(athlete, period)
    start, end = period.start, period.end
    prev_start, prev_end = period.compare_start, period.compare_end
    from apps.athletes.effective import sleep_need

    need_info = sleep_need(athlete)
    nights = [_night(r, need_info) for r in metrics_rows(athlete, start, end) if _has_sleep(r)]
    previous = [_night(r, need_info) for r in metrics_rows(athlete, prev_start, prev_end)
                if _has_sleep(r)]
    recent = [_night(r, need_info) for r in metrics_rows(athlete, end - dt.timedelta(days=6), end)
              if _has_sleep(r)]

    debt = sleep_maths.debt([(n["sleep_s"], n["need_s"]) for n in recent])
    hours = {n["date"]: n["sleep_s"] / 3600 for n in nights if n["sleep_s"]}
    runs = _runs(athlete, start, end)
    pairs = [(hours.get(day), values.get("easy_hr")) for day, values in runs.items()]
    need = (need_info["seconds"] if need_info["source"] in ("memory", "user")
            else debt["need_s"] or sleep_maths.median([n["need_s"] for n in recent])
            or need_info["seconds"])
    digits = {"*": 0, "breathing_rate": 1, "spo2_avg": 1, "bedtime_h": 2, "wake_h": 2}
    return {
        **period.ranged(),
        "nights": [_public(n) for n in nights],
        "series": bucket([_sleep_point(n) for n in nights], period.freq, "mean", digits=digits),
        "averages": sleep_maths.averages(nights),
        "previous": sleep_maths.averages(previous),
        "regularity": sleep_maths.regularity([n["bedtime_dt"] for n in nights],
                                             [n["bedtime_dt"] for n in previous]),
        "debt": debt,
        "sleep_vs_runs": sleep_maths.sleep_vs_runs(pairs),
        "tonight": sleep_maths.tonight([n["wake_dt"] for n in recent],
                                       round(need) if need else None),
        "need": need_info,                                   # R18
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sleep(request):
    from django.utils import timezone

    athlete = request.user.athlete
    body = sleep_payload(athlete, parse_period(request, athlete, "4w"))
    nights = body.get("nights") or []
    # R16 §C: when the newest night is not last night, the UI says so.
    return Response({**body, "as_of": timezone.now(),
                     "last_night_date": nights[-1]["date"] if nights else None})


# --- B5 running form --------------------------------------------------------------------

def form_payload(athlete, period) -> dict:
    period = as_period(athlete, period)
    start, end = period.start, period.end
    runs = []
    for a in (Activity.objects.filter(athlete=athlete, sport__icontains="run",
                                      local_date__gte=start, local_date__lte=end)
              .exclude(quality__decision="exclude")
              .select_related("metrics").order_by("started_at")):
        m = getattr(a, "metrics", None)
        if m is None or m.run_block_count <= 0:
            continue
        runs.append({
            "activity_id": a.pk, "date": a.local_date.isoformat(),
            "cadence_spm": round(m.avg_run_cadence_spm, 1) if m.avg_run_cadence_spm else None,
            "ground_contact_ms": round(m.avg_ground_contact_ms) if m.avg_ground_contact_ms else None,
            "vertical_oscillation_cm": (round(m.avg_vertical_oscillation_cm, 1)
                                        if m.avg_vertical_oscillation_cm else None),
            "stride_length_m": round(m.avg_stride_length_m, 2) if m.avg_stride_length_m else None,
            "run_km": round(m.run_distance_m / 1000, 2),
            "run_pace_s_per_km": round(m.run_pace_s_per_km) if m.run_pace_s_per_km else None,
        })
    series = [{"date": dt.date.fromisoformat(r["date"]),
               **{k: r[k] for k in ("cadence_spm", "ground_contact_ms", "vertical_oscillation_cm",
                                    "stride_length_m", "run_pace_s_per_km", "run_km")}}
              for r in runs]
    series = bucket(series, period.freq, {"run_km": "sum", "*": "mean"},
                    digits={"stride_length_m": 2, "run_km": 2, "ground_contact_ms": 0,
                            "run_pace_s_per_km": 0, "*": 1})
    return {**period.ranged(), "has_dynamics": form_maths.has_dynamics(runs),
            "runs": runs, "series": series, "metrics": form_maths.metric_rows(runs)}


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def form(request):
    athlete = request.user.athlete
    return Response(form_payload(athlete, parse_period(request, athlete, "3m")))


# --- B6 personal records --------------------------------------------------------------

def records_list(athlete) -> list[dict]:
    """Garmin's PRs then our computed bests, each with display text and is_new."""
    from apps.activities.progress import run_dicts

    today = athlete.local_today
    garmin = {r.key: r for r in PersonalRecord.objects.filter(athlete=athlete)}
    ids = {g.garmin_activity_id for g in garmin.values() if g.garmin_activity_id}
    ours = dict(Activity.objects.filter(athlete=athlete, garmin_activity_id__in=ids)
                .values_list("garmin_activity_id", "pk")) if ids else {}
    out = []
    for type_id, (key, label, unit) in record_maths.GARMIN_TYPES.items():
        row = garmin.get(key)
        if row is None:
            continue
        out.append({"key": key, "label": label, "source": "garmin", "unit": unit,
                    "value": row.value, "display": record_maths.display(row.value, unit),
                    "date": row.achieved_on,
                    "activity_id": ours.get(row.garmin_activity_id),
                    "garmin_activity_id": row.garmin_activity_id,
                    "is_new": record_maths.is_new(row.achieved_on, today)})
    for entry in record_maths.computed(run_dicts(athlete)):
        out.append({"key": entry["key"], "label": entry["label"], "source": "computed",
                    "unit": entry["unit"], "value": entry["value"],
                    "display": record_maths.display(entry["value"], entry["unit"]),
                    "date": entry["date"], "activity_id": entry["activity_id"],
                    "garmin_activity_id": None,
                    "is_new": record_maths.is_new(entry["date"], today)})
    return out


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def records(request):
    athlete = request.user.athlete
    rows = records_list(athlete)
    profile = GarminProfile.objects.filter(athlete=athlete).first()
    return Response({"records": rows, "new_count": sum(1 for r in rows if r["is_new"]),
                     "synced_on": profile.slow_synced_on if profile else None})


# --- B7 body composition ----------------------------------------------------------------

def body_payload(athlete, period) -> dict:
    from apps.athletes.models import MetricEntry
    from .common import zone_of

    period = as_period(athlete, period)
    start, end = period.start, period.end
    garmin = [{"date": b.measured_on, "weight_kg": b.weight_kg, "body_fat_pct": b.body_fat_pct,
               "bmi": b.bmi, "muscle_mass_kg": b.muscle_mass_kg}
              for b in BodyComposition.objects.filter(athlete=athlete, measured_on__gte=start,
                                                      measured_on__lte=end)]
    zone = zone_of(athlete)
    manual: dict[dt.date, dict] = {}
    for entry in (MetricEntry.objects.filter(athlete=athlete, kind="weight")
                  .exclude(source=MetricEntry.Source.GARMIN).order_by("recorded_at")):
        day = entry.recorded_at.astimezone(zone).date()
        if start <= day <= end:
            manual[day] = {"date": day, "weight_kg": round(entry.value, 2)}
    merged = body_maths.merge(garmin, list(manual.values()))
    latest = merged[-1] if merged else None
    return {
        **period.ranged(),
        "profile_weight_kg": athlete.weight_kg,
        "latest": ({"date": latest["date"], "weight_kg": latest.get("weight_kg"),
                    "body_fat_pct": latest.get("body_fat_pct"), "bmi": latest.get("bmi"),
                    "muscle_mass_kg": latest.get("muscle_mass_kg"), "source": latest["source"]}
                   if latest else None),
        "change": {"weight_kg": body_maths.change(merged, "weight_kg"),
                   "body_fat_pct": body_maths.change(merged, "body_fat_pct")},
        "trend_kg_per_week": body_maths.trend(merged),
        "series": bucket([{"date": p["date"], "weight_kg": p.get("weight_kg"),
                           "body_fat_pct": p.get("body_fat_pct"), "source": p["source"]}
                          for p in merged], period.freq, "last"),
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def body(request):
    athlete = request.user.athlete
    return Response(body_payload(athlete, parse_period(request, athlete, "6m")))

