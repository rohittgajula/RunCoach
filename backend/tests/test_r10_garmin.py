"""R10 §B ingest: new wellness columns from stored payloads, the once-a-day slow fetch
(endurance, fitness age, LT → zones, PRs, body composition, gear), the circuit breaker,
the 180-day backfill and its management command. Garmin is never called: a fake client
returns payloads shaped like garminconnect 0.3.10's (synthetic values)."""

import datetime as dt

import pytest
from django.core.cache.backends.locmem import LocMemCache
from django.core.management import call_command

from apps.athletes.models import MetricEntry
from apps.gear.models import Shoe
from apps.ingest import garmin_slow, tasks
from apps.ingest.garmin_wellness import fields_from_raw
from apps.ingest.models import (
    BodyComposition, DailyMetrics, GarminProfile, LactateThreshold, PersonalRecord,
)

UUID = "ef3f7e55c7f24ec4958601e437f7ba6b"


@pytest.fixture(autouse=True)
def private_breaker(monkeypatch, settings):
    """The breaker lives in a per-test memory cache, never the shared Redis (tripping
    that would stop the dev stack's real Garmin worker for 45 minutes)."""
    cache = LocMemCache("r10-breaker", {})
    cache.clear()
    monkeypatch.setattr(tasks, "cache", cache)
    settings.GARMIN_SLOW_PAUSE_S = 0
    return cache


class FakeClient:
    def __init__(self, today, fail=None, missing=()):
        self.today = today
        self.calls = []
        self.fail = fail            # method name that answers 429
        self.missing = set(missing)

    def _hit(self, name):
        self.calls.append(name)
        if name == self.fail:
            raise Exception("429 Client Error: Too Many Requests")
        if name in self.missing:
            raise Exception("404 Not Found")

    def get_activities(self, start=0, limit=20):     # R17: the deletion check
        self._hit("get_activities")
        return []

    def get_endurance_score(self, start, end=None):
        self._hit("get_endurance_score")
        if end:
            return {"groupMap": {"2026-09-24": {"groupAverage": 4100},
                                 "2026-10-01": {"groupAverage": 4120},
                                 "2026-09-17": {"groupAverage": None}}}
        return {"overallScore": 4120, "classification": 2, "calendarDate": start}

    def get_fitnessage_data(self, cdate):
        self._hit("get_fitnessage_data")
        return {"chronologicalAge": 31, "fitnessAge": 29.4321, "achievableFitnessAge": 27.0}

    def get_lactate_threshold(self, *, latest=True, start_date=None, end_date=None, **kw):
        self._hit("get_lactate_threshold")
        if latest:
            return {"speed_and_heart_rate": {"calendarDate": "2026-10-01T07:00:00.0",
                                             "speed": 0.2739726, "heartRate": 171},
                    "power": {}}
        return {"speed": [{"from": "2026-08-01", "value": 0.26}],
                "heart_rate": [{"from": "2026-08-01", "value": 168},
                               {"from": "2026-10-01", "value": 171}],
                "power": []}

    def get_personal_record(self):
        self._hit("get_personal_record")
        return [{"typeId": 3, "value": 1635.0, "activityId": 111,
                 "activityStartDateTimeLocalFormatted": "2026-09-30T06:10:00.0"},
                {"typeId": 7, "value": 8200.0, "activityId": 111,
                 "activityStartDateTimeLocalFormatted": "2026-09-30T06:10:00.0"},
                {"typeId": 12, "value": 28000.0}]

    def get_body_composition(self, start, end=None):
        self._hit("get_body_composition")
        return {"dateWeightList": [
            {"calendarDate": "2026-09-20", "weight": 76200.0, "bodyFat": 21.5,
             "timestampGMT": 1789900000000},
            {"calendarDate": "2026-10-05", "weight": 75400.0, "bodyFat": None,
             "muscleMass": 33000.0, "timestampGMT": 1791200000000},
            {"calendarDate": "2026-10-05", "weight": 75600.0, "timestampGMT": 1791100000000},
        ]}

    def get_user_profile(self):
        self._hit("get_user_profile")
        return {"id": 147}

    def get_gear(self, pk):
        self._hit("get_gear")
        assert pk == "147"
        return [{"uuid": UUID, "gearTypeName": "Shoes", "gearMakeName": "Other",
                 "gearModelName": "Unknown Shoes", "customMakeModel": "Nike Revolution",
                 "gearStatusName": "active", "maximumMeters": 650000.0,
                 "dateBegin": "2026-08-09T00:00:00.0"},
                {"uuid": "b" * 32, "gearTypeName": "Bike", "displayName": "Bike"}]

    def get_gear_stats(self, uuid):
        self._hit("get_gear_stats")
        return {"totalDistance": 10668.3, "totalActivities": 6}

    # R12 §B4: read-only watch alarms.
    def get_devices(self):
        self._hit("get_devices")
        return [{"deviceId": 3442975544, "productDisplayName": "Forerunner 265"}]

    def get_device_settings(self, device_id):
        self._hit("get_device_settings")
        return {"alarms": [{"alarmMode": "ON", "alarmTime": 360,
                            "alarmDays": ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"],
                            "alarmId": 1}]}


# --- fields from stored payloads ------------------------------------------------------

def test_new_columns_from_raw_payloads():
    raw = {
        "sleep": {"restlessMomentsCount": 54, "dailySleepDTO": {
            "sleepTimeSeconds": 24780, "averageSpO2Value": 95.0, "lowestSpO2Value": 88.0}},
        "training_status": {"mostRecentTrainingLoadBalance": {"metricsTrainingLoadBalanceDTOMap": {
            "1": {"primaryTrainingDevice": False, "monthlyLoadAerobicLow": 1.0},
            "2": {"primaryTrainingDevice": True, "monthlyLoadAerobicLow": 410.0,
                  "monthlyLoadAerobicLowTargetMin": 95, "monthlyLoadAerobicLowTargetMax": 260,
                  "trainingBalanceFeedbackPhrase": "AEROBIC_LOW_SHORTAGE"}}}},
        "endurance_score": {"overallScore": 4120, "classification": 2},
        "fitness_age": {"fitnessAge": 29.43},
    }
    out = fields_from_raw(raw)
    assert out["restless_moments"] == 54 and out["sleep_spo2_avg"] == 95.0
    assert out["sleep_spo2_low"] == 88.0
    assert out["load_focus"]["items"][0]["value"] == 410.0
    assert out["load_focus"]["items"][0]["state"] == "above"
    assert out["endurance_score"] == 4120 and out["endurance_level"] == "Intermediate"
    assert out["fitness_age"] == 29.4


def test_absent_values_stay_null():
    out = fields_from_raw({"sleep": {"dailySleepDTO": {"sleepTimeSeconds": 100}},
                           "endurance_score": {}, "fitness_age": {"fitnessAge": None}})
    for key in ("restless_moments", "sleep_spo2_avg", "endurance_score", "fitness_age",
                "load_focus"):
        assert key not in out


# --- the daily slow fetch ------------------------------------------------------------------

@pytest.mark.django_db
def test_slow_sync_stores_everything_and_updates_zones(athlete):
    athlete.max_hr, athlete.resting_hr, athlete.hr_ceiling = 190, 60, 155
    athlete.save()
    client = FakeClient(athlete.local_today)
    result = garmin_slow.sync_slow(athlete, client)
    assert result["rate_limited"] is False and result["zones_updated"] is True

    today = DailyMetrics.objects.get(athlete=athlete, metric_date=athlete.local_today)
    assert today.endurance_score == 4120 and today.fitness_age == 29.4
    assert "endurance_score" in today.raw and "fitness_age" in today.raw
    profile = GarminProfile.objects.get(athlete=athlete)
    assert profile.chronological_age == 31 and profile.slow_synced_on == athlete.local_today
    assert profile.user_profile_pk == 147

    lt = LactateThreshold.objects.get(athlete=athlete)
    assert lt.heart_rate == 171 and lt.measured_on == dt.date(2026, 10, 1)
    assert lt.speed_mps == pytest.approx(2.74, abs=0.01) and lt.pace_s_per_km == 365
    athlete.refresh_from_db()
    assert athlete.zones_source == "lactate_threshold" and athlete.lt_hr == 171
    assert athlete.lt_pace_s == 365 and athlete.zones_updated_at is not None
    zones = athlete.zones()
    assert zones.source == "lactate_threshold"
    assert zones.band("Z2").high <= 155                 # never above the HR ceiling

    assert set(PersonalRecord.objects.filter(athlete=athlete).values_list("key", flat=True)) \
        == {"5k", "longest_run"}
    body = {b.measured_on: b for b in BodyComposition.objects.filter(athlete=athlete)}
    assert body[dt.date(2026, 10, 5)].weight_kg == 75.4      # latest of the day wins
    assert body[dt.date(2026, 10, 5)].muscle_mass_kg == 33.0
    assert body[dt.date(2026, 9, 20)].body_fat_pct == 21.5
    entry = MetricEntry.objects.get(athlete=athlete, kind="weight")
    assert entry.source == "garmin" and entry.value == 75.4 and athlete.weight_kg == 75.4

    shoe = Shoe.objects.get(athlete=athlete)
    assert shoe.source == "garmin" and shoe.name == "Nike Revolution" and shoe.brand == ""
    assert shoe.garmin_max_km == 650.0 and shoe.garmin_distance_m == 10668.3
    assert shoe.in_use_since == dt.date(2026, 8, 9)

    # At most once a day: a second run asks Garmin nothing.
    again = FakeClient(athlete.local_today)
    assert garmin_slow.sync_slow(athlete, again) == {"skipped": "already_today"}
    assert again.calls == []


@pytest.mark.django_db
def test_slow_sync_pauses_between_calls(athlete, settings, monkeypatch):
    settings.GARMIN_SLOW_PAUSE_S = 1.5
    pauses = []
    monkeypatch.setattr(garmin_slow.time, "sleep", pauses.append)
    client = FakeClient(athlete.local_today)
    result = garmin_slow.sync_slow(athlete, client)
    assert pauses == [1.5] * (result["calls"] - 1) and result["calls"] == len(client.calls)


@pytest.mark.django_db
def test_slow_sync_missing_endpoint_is_null_not_failure(athlete):
    client = FakeClient(athlete.local_today, missing={"get_endurance_score",
                                                      "get_lactate_threshold"})
    result = garmin_slow.sync_slow(athlete, client)
    assert result["rate_limited"] is False and "endurance score" in result["missing"]
    assert DailyMetrics.objects.get(athlete=athlete).endurance_score is None
    athlete.refresh_from_db()
    assert athlete.zones_source == "heart_rate_reserve" and athlete.lt_hr is None
    assert GarminProfile.objects.get(athlete=athlete).slow_synced_on == athlete.local_today


@pytest.mark.django_db
def test_slow_sync_stops_at_the_first_429(athlete, monkeypatch, private_breaker):
    client = FakeClient(athlete.local_today, fail="get_personal_record")
    athlete.garmin_connected = True
    athlete.save()
    monkeypatch.setattr("apps.ingest.garmin._client", lambda a: client)
    result = tasks.sync_slow_one(athlete.pk)
    assert result["rate_limited"] is True
    assert "get_gear" not in client.calls and "get_body_composition" not in client.calls
    assert tasks.garmin_blocked()                        # breaker tripped
    assert GarminProfile.objects.get(athlete=athlete).slow_synced_on is None
    # While the breaker is open nothing is asked at all.
    other = FakeClient(athlete.local_today)
    monkeypatch.setattr("apps.ingest.garmin._client", lambda a: other)
    assert tasks.sync_slow_one(athlete.pk) == {"skipped": "rate_limited"}
    assert other.calls == []


@pytest.mark.django_db
def test_breaker_opening_mid_run_stops_the_run(athlete, private_breaker):
    class Tripping(FakeClient):
        def get_fitnessage_data(self, cdate):
            tasks.trip_breaker("another worker hit 429")
            return super().get_fitnessage_data(cdate)

    client = Tripping(athlete.local_today)
    result = garmin_slow.sync_slow(athlete, client)
    assert result["rate_limited"] is True
    assert client.calls == ["get_endurance_score", "get_fitnessage_data"]


@pytest.mark.django_db
def test_task_skips_unconnected_athlete(athlete):
    assert tasks.sync_slow_one(athlete.pk) == {"skipped": "not_connected"}


@pytest.mark.django_db
def test_lt_without_heart_rate_leaves_zones_alone(athlete):
    garmin_slow.store_lactate(athlete, dt.date(2026, 9, 1), None, 3.0, {})
    assert garmin_slow.apply_lactate_threshold(athlete) is False
    athlete.refresh_from_db()
    assert athlete.zones_source == "heart_rate_reserve"


@pytest.mark.django_db
def test_lt_unchanged_keeps_update_time_and_older_lt_is_ignored(athlete):
    garmin_slow.store_lactate(athlete, dt.date(2026, 9, 1), 170, 3.0, {})
    assert garmin_slow.apply_lactate_threshold(athlete) is True
    athlete.refresh_from_db()
    first = athlete.zones_updated_at
    assert garmin_slow.apply_lactate_threshold(athlete) is False
    athlete.refresh_from_db()
    assert athlete.zones_updated_at == first
    LactateThreshold.objects.all().delete()
    garmin_slow.store_lactate(athlete, dt.date(2026, 8, 1), 160, None, {})
    assert garmin_slow.apply_lactate_threshold(athlete) is False
    athlete.refresh_from_db()
    assert athlete.lt_hr == 170


@pytest.mark.django_db
def test_implausible_lt_is_not_applied(athlete):
    athlete.max_hr = 165
    athlete.save()
    garmin_slow.store_lactate(athlete, dt.date(2026, 9, 1), 170, None, {})
    assert garmin_slow.apply_lactate_threshold(athlete) is False


def test_lt_speed_units():
    assert garmin_slow.lt_speed_mps(0.3138) == pytest.approx(3.138)
    assert garmin_slow.lt_speed_mps(3.2) == 3.2
    assert garmin_slow.lt_speed_mps(None) is None and garmin_slow.lt_speed_mps(0) is None


@pytest.mark.django_db
def test_manual_weight_newer_than_garmin_is_kept(athlete):
    from django.utils import timezone

    MetricEntry.objects.create(athlete=athlete, kind="weight", value=74.0,
                               recorded_at=timezone.now())
    garmin_slow.store_body(athlete, {"dateWeightList": [
        {"calendarDate": "2026-09-01", "weight": 80000.0, "timestampGMT": 1788000000000}]})
    athlete.refresh_from_db()
    assert athlete.weight_kg == 74.0
    assert MetricEntry.objects.filter(athlete=athlete, source="garmin").count() == 0


@pytest.mark.django_db
def test_gear_keeps_athlete_choices(athlete):
    garmin_slow.store_gear(athlete, FakeClient(athlete.local_today).get_gear("147"))
    shoe = Shoe.objects.get(athlete=athlete)
    shoe.retire_km, shoe.is_default = 500, True
    shoe.save()
    garmin_slow.store_gear(athlete, FakeClient(athlete.local_today).get_gear("147"))
    shoe.refresh_from_db()
    assert shoe.retire_km == 500 and shoe.is_default is True
    assert Shoe.objects.filter(athlete=athlete).count() == 1


@pytest.mark.django_db
def test_profile_pk_from_stored_sleep_payload(athlete):
    DailyMetrics.objects.create(athlete=athlete, metric_date=athlete.local_today,
                                raw={"sleep": {"dailySleepDTO": {"userProfilePK": 999}}})
    client = FakeClient(athlete.local_today)
    profile = garmin_slow.profile_for(athlete)
    runner = garmin_slow._Runner(client)
    assert garmin_slow._user_profile_pk(athlete, profile, runner) == 999
    assert "get_user_profile" not in client.calls


# --- backfill ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_backfill_reads_history_and_remaps_stored_payloads(athlete):
    DailyMetrics.objects.create(athlete=athlete, metric_date=athlete.local_today
                                - dt.timedelta(days=3),
                                raw={"sleep": {"restlessMomentsCount": 12, "dailySleepDTO": {}}})
    client = FakeClient(athlete.local_today)
    result = garmin_slow.backfill(athlete, client, days=28)
    assert result["rate_limited"] is False and result["remapped_days"] == 1
    assert DailyMetrics.objects.get(athlete=athlete, metric_date=athlete.local_today
                                    - dt.timedelta(days=3)).restless_moments == 12
    assert client.calls.count("get_fitnessage_data") == 5        # weekly samples over 28 d
    assert result["fitness_age_days"] == 5
    assert result["endurance_weeks"] == 2
    assert DailyMetrics.objects.get(athlete=athlete,
                                    metric_date=dt.date(2026, 10, 1)).endurance_score == 4120
    assert set(LactateThreshold.objects.filter(athlete=athlete)
               .values_list("measured_on", "heart_rate")) == {
        (dt.date(2026, 8, 1), 168), (dt.date(2026, 10, 1), 171)}
    assert GarminProfile.objects.get(athlete=athlete).backfilled_on == athlete.local_today


@pytest.mark.django_db
def test_backfill_command_runs_now_and_requires_target(athlete, monkeypatch):
    athlete.garmin_connected = True
    athlete.save()
    client = FakeClient(athlete.local_today)
    monkeypatch.setattr("apps.ingest.garmin._client", lambda a: client)
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("garmin_backfill_r10")
    call_command("garmin_backfill_r10", "--athlete", str(athlete.pk), "--now", "--days", "14")
    assert "get_lactate_threshold" in client.calls
    assert GarminProfile.objects.get(athlete=athlete).backfilled_on is not None


@pytest.mark.django_db
def test_backfill_command_refuses_while_breaker_open(athlete):
    tasks.trip_breaker("429")
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("garmin_backfill_r10", "--all")


# --- queueing ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_queue_slow_once_a_day(athlete, monkeypatch):
    queued = []
    monkeypatch.setattr(tasks.sync_slow_one, "apply_async",
                        lambda args, countdown=0: queued.append(args))
    assert tasks.queue_slow(athlete) is True and queued == [(athlete.pk,)]
    GarminProfile.objects.create(athlete=athlete, slow_synced_on=athlete.local_today)
    assert tasks.queue_slow(athlete) is False


@pytest.mark.django_db
def test_sync_one_queues_the_slow_fetch(athlete, monkeypatch):
    from apps.ingest.garmin import SyncResult

    athlete.garmin_connected = True
    athlete.save()
    monkeypatch.setattr(tasks, "sync_athlete", lambda a: SyncResult())
    queued = []
    monkeypatch.setattr(tasks, "queue_slow", lambda a: queued.append(a.pk))
    monkeypatch.setattr("apps.planning.tasks.adapt_week_task.delay", lambda *a: None)
    tasks.sync_one(athlete.pk)
    assert queued == [athlete.pk]
