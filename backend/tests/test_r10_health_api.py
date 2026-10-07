"""R10 §B endpoints: /health/fitness|training-status|sleep|form|records|body/ — shapes,
ranges, nulls when Garmin has nothing, and tenant isolation."""

import datetime as dt

import pytest
from django.utils import timezone

from apps.athletes.models import MetricEntry
from apps.ingest.models import BodyComposition, GarminProfile, LactateThreshold, PersonalRecord
from tests.r10_helpers import metric, night, run

ENDPOINTS = ["/api/health/fitness/", "/api/health/training-status/", "/api/health/sleep/",
             "/api/health/form/", "/api/health/records/", "/api/health/body/"]
RANGED = ["/api/health/fitness/", "/api/health/sleep/", "/api/health/form/",
          "/api/health/body/"]


def ago(athlete, n):
    return athlete.local_today - dt.timedelta(days=n)


@pytest.mark.parametrize("url", ENDPOINTS)
def test_empty_account_gets_nulls_not_errors(api, url):
    r = api.get(url)
    assert r.status_code == 200, r.json()


@pytest.mark.parametrize("url", RANGED)
def test_range_validation(api, url):
    for key in ("7d", "4w", "3m", "6m", "1y"):
        body = api.get(url, {"range": key}).json()
        assert body["range"] == key
        assert dt.date.fromisoformat(body["end"]) - dt.date.fromisoformat(body["start"]) == \
            dt.timedelta(days={"7d": 6, "4w": 27, "3m": 90, "6m": 181, "1y": 364}[key])
    r = api.get(url, {"range": "2w"})
    assert r.status_code == 400 and "range" in r.json()["detail"]


@pytest.mark.parametrize("url", ENDPOINTS)
def test_unauthenticated_is_refused(client, db, url):
    assert client.get(url).status_code == 401


def test_fitness_payload(api, athlete):
    athlete.max_hr, athlete.resting_hr = 190, 60
    athlete.save()
    metric(athlete, ago(athlete, 60), vo2max=39.0, fitness_age=31.0, endurance_score=3900,
           endurance_level="Recreational", race_pred_5k_s=1800, race_pred_10k_s=3800)
    metric(athlete, ago(athlete, 1), vo2max=41.0, fitness_age=29.4, endurance_score=4120,
           endurance_level="Intermediate", race_pred_5k_s=1780)
    GarminProfile.objects.create(athlete=athlete, chronological_age=31, achievable_fitness_age=27)
    LactateThreshold.objects.create(athlete=athlete, measured_on=ago(athlete, 5), heart_rate=171,
                                    pace_s_per_km=365)
    athlete.lt_hr, athlete.lt_pace_s, athlete.lt_date = 171, 365, ago(athlete, 5)
    athlete.zones_source, athlete.zones_updated_at = "lactate_threshold", timezone.now()
    athlete.save()
    # R12: 6m defaults to weekly buckets; the daily series is freq=day.
    body = api.get("/api/health/fitness/", {"freq": "day"}).json()
    assert body["vo2max"] == {"current": 41.0, "change": 2.0, "series": [
        {"date": str(ago(athlete, 60)), "value": 39.0}, {"date": str(ago(athlete, 1)), "value": 41.0}]}
    assert body["fitness_age"]["current"] == 29.4 and body["fitness_age"]["chronological_age"] == 31
    assert body["fitness_age"]["change"] == -1.6 and body["fitness_age"]["achievable"] == 27
    assert body["endurance_score"]["current"] == 4120 and body["endurance_score"]["change"] == 220
    assert body["endurance_score"]["level"] == "Intermediate"
    preds = body["race_predictions"]
    assert preds["current"]["5k_s"] == 1780 and preds["previous"]["5k_s"] == 1800
    assert preds["current"]["10k_s"] is None and len(preds["series"]) == 2
    lt = body["lactate_threshold"]
    assert lt["hr"] == 171 and lt["pace_s_per_km"] == 365 and lt["zones_updated"] is True
    assert lt["source"] == "garmin" and len(lt["series"]) == 1
    zones = body["zones"]
    assert zones["source"] == "lactate_threshold" and zones["lt_hr"] == 171
    assert zones["lt_date"] == str(ago(athlete, 5)) and zones["updated_at"]
    # The same keys appear on the athlete.
    assert api.get("/api/athlete/").json()["zones"]["source"] == "lactate_threshold"


def test_fitness_without_garmin_data(api, athlete):
    body = api.get("/api/health/fitness/").json()
    assert body["vo2max"] == {"current": None, "change": None, "series": []}
    assert body["lactate_threshold"] is None and body["zones"] is None
    assert body["race_predictions"]["current"] is None
    assert body["endurance_score"]["level"] is None


def test_athlete_zones_reserve_source(api, athlete):
    athlete.max_hr, athlete.resting_hr = 190, 60
    athlete.save()
    zones = api.get("/api/athlete/").json()["zones"]
    assert zones["source"] == "heart_rate_reserve" and zones["lt_hr"] is None
    assert zones["capped"] is False and zones["updated_at"] is None


def test_training_status(api, athlete):
    focus = {"feedback": "Below targets", "items": [
        {"key": "low_aerobic", "label": "Low aerobic", "value": 410.0, "target_min": 95.0,
         "target_max": 260.0, "state": "above"}]}
    metric(athlete, ago(athlete, 2), training_status="Productive", acute_load=300,
           chronic_load=250, load_focus=focus)
    metric(athlete, ago(athlete, 1), training_status="", acute_load=None)
    body = api.get("/api/health/training-status/").json()
    assert body["status"] == "Productive" and body["status_key"] == "productive"
    assert body["acwr"] == 1.2 and body["date"] == str(ago(athlete, 2))
    assert body["load_focus"]["items"][0]["state"] == "above"
    assert body["load_focus"]["period_days"] == 28
    assert [h["status_key"] for h in body["history"]] == ["productive"]


def test_training_status_empty(api):
    body = api.get("/api/health/training-status/").json()
    assert body["status"] is None and body["load_focus"] is None and body["history"] == []


def test_sleep_payload(api, athlete):
    for i in range(1, 8):
        night(athlete, ago(athlete, i), hours=6.5 if i % 2 else 7.5, need_h=8,
              bed=(23, 0) if i % 2 else (0, 30), restless_moments=40 + i, sleep_spo2_avg=95.0,
              respiration_sleep_avg=14.0, sleep_score=70)
    body = api.get("/api/health/sleep/", {"range": "7d"}).json()
    assert len(body["nights"]) == 6           # today has no night; 7d = today-6..today
    first = body["nights"][0]
    assert set(first) == {"date", "sleep_s", "need_s", "score", "deep_s", "light_s", "rem_s",
                          "awake_s", "bedtime", "wake_time", "restless_moments", "spo2_avg",
                          "spo2_low", "breathing_rate"}
    assert first["bedtime"].endswith(("23:00", "00:30")) and first["spo2_avg"] == 95.0
    assert body["averages"]["spo2_avg"] == 95.0 and body["averages"]["bedtime"] is not None
    assert body["regularity"]["bedtime_sd_min"] == 45 and body["regularity"]["n"] == 6
    debt = body["debt"]
    assert debt["nights"] == 6 and debt["need_s"] == 28800 and debt["short_nights"] == 6
    assert body["tonight"]["need_s"] == 28800 and body["tonight"]["bedtime"]
    assert body["sleep_vs_runs"]["enough_data"] is False


def test_sleep_vs_runs_through_the_endpoint(api, athlete):
    for i in range(1, 7):
        day = ago(athlete, i)
        night(athlete, day, hours=5.5 if i <= 3 else 7.5)
        run(athlete, day, hr=152 if i <= 3 else 145, pace=athlete.easy_pace_min + 10)
    body = api.get("/api/health/sleep/").json()["sleep_vs_runs"]
    assert body["enough_data"] and body["diff_bpm"] == 7.0 and "7 bpm lower" in body["sentence"]


def test_form_payload(api, athlete):
    for i in range(10):
        run(athlete, ago(athlete, 30 - 3 * i), cadence=150 + i, gct=300 - i, vo=9.0, stride=0.9)
    body = api.get("/api/health/form/").json()
    assert body["has_dynamics"] is True and len(body["runs"]) == 10
    run0 = body["runs"][0]
    assert set(run0) == {"activity_id", "date", "cadence_spm", "ground_contact_ms",
                         "vertical_oscillation_cm", "stride_length_m", "run_km",
                         "run_pace_s_per_km"}
    rows = {r["key"]: r for r in body["metrics"]}
    assert rows["cadence"]["current"] == 157 and rows["cadence"]["better"] is True
    assert rows["vertical_oscillation"]["better"] is None and rows["stride_length"]["n"] == 10


def test_records_payload(api, athlete):
    act = run(athlete, ago(athlete, 3), km=8.2, garmin_id=111, longest_s=1500)
    PersonalRecord.objects.create(athlete=athlete, key="5k", value=1635, achieved_on=ago(athlete, 3),
                                  garmin_activity_id=111)
    PersonalRecord.objects.create(athlete=athlete, key="longest_run", value=8200,
                                  achieved_on=ago(athlete, 40))
    body = api.get("/api/health/records/").json()
    by_key = {r["key"]: r for r in body["records"]}
    assert by_key["5k"]["display"] == "27:15" and by_key["5k"]["is_new"] is True
    assert by_key["5k"]["activity_id"] == act.pk and by_key["5k"]["source"] == "garmin"
    assert by_key["longest_run"]["display"] == "8.2 km" and by_key["longest_run"]["is_new"] is False
    assert by_key["longest_distance"]["source"] == "computed"
    assert by_key["longest_continuous"]["value"] == 1500
    assert [r["key"] for r in body["records"]][:2] == ["5k", "longest_run"]
    assert body["new_count"] >= 1 and body["synced_on"] is None


def test_body_payload_merges_garmin_and_manual(api, athlete):
    BodyComposition.objects.create(athlete=athlete, measured_on=ago(athlete, 20), weight_kg=76.0,
                                   body_fat_pct=21.0)
    MetricEntry.objects.create(athlete=athlete, kind="weight", value=75.0,
                               recorded_at=timezone.now() - dt.timedelta(days=2))
    MetricEntry.objects.create(athlete=athlete, kind="weight", value=99.0, source="garmin",
                               recorded_at=timezone.now() - dt.timedelta(days=20))
    body = api.get("/api/health/body/").json()
    assert [p["source"] for p in body["series"]] == ["garmin", "manual"]
    assert body["latest"]["weight_kg"] == 75.0 and body["latest"]["source"] == "manual"
    assert body["change"] == {"weight_kg": -1.0, "body_fat_pct": None}
    assert body["profile_weight_kg"] == 75.0


def test_body_empty(api):
    body = api.get("/api/health/body/").json()
    assert body["latest"] is None and body["series"] == [] and body["trend_kg_per_week"] is None


def test_tenant_isolation(other_api, athlete):
    metric(athlete, ago(athlete, 1), vo2max=45.0, training_status="Productive",
           sleep_seconds=25000)
    night(athlete, ago(athlete, 2))
    run(athlete, ago(athlete, 2), gct=250)
    PersonalRecord.objects.create(athlete=athlete, key="5k", value=1500, achieved_on=ago(athlete, 2))
    BodyComposition.objects.create(athlete=athlete, measured_on=ago(athlete, 2), weight_kg=70)
    LactateThreshold.objects.create(athlete=athlete, measured_on=ago(athlete, 2), heart_rate=170)
    assert other_api.get("/api/health/fitness/").json()["vo2max"]["series"] == []
    assert other_api.get("/api/health/fitness/").json()["lactate_threshold"] is None
    assert other_api.get("/api/health/training-status/").json()["status"] is None
    assert other_api.get("/api/health/sleep/").json()["nights"] == []
    assert other_api.get("/api/health/form/").json()["runs"] == []
    assert other_api.get("/api/health/records/").json()["records"] == []
    assert other_api.get("/api/health/body/").json()["series"] == []
