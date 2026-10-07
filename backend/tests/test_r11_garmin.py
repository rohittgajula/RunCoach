"""R11 §A ingest: intraday payload parsing, the compact IntradayDay row, the fetch after
each sync (today + yesterday), spacing, the breaker, the 30-day backfill command and
the nudge refresh. Garmin is never called: a fake client returns payloads shaped like
garminconnect 0.3.10's (synthetic values; shapes checked against one real response)."""

import datetime as dt

import pytest
from django.core.cache.backends.locmem import LocMemCache
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.ingest import garmin_intraday as gi
from apps.ingest import garmin_slow, tasks
from apps.ingest.models import DailyMetrics, IntradayDay
from apps.reminders.models import PushSubscription, ReminderSettings

OFFSET = 330   # Asia/Kolkata


@pytest.fixture(autouse=True)
def private_breaker(monkeypatch, settings):
    cache = LocMemCache("r11-breaker", {})
    cache.clear()
    monkeypatch.setattr(tasks, "cache", cache)
    settings.GARMIN_SLOW_PAUSE_S = 0
    return cache


def epoch_ms(day: dt.date, minute: int) -> int:
    local = dt.datetime.combine(day, dt.time()) + dt.timedelta(minutes=minute - OFFSET)
    return int(local.replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def gmt(day: dt.date, minute: int) -> str:
    local = dt.datetime.combine(day, dt.time()) + dt.timedelta(minutes=minute - OFFSET)
    return local.strftime("%Y-%m-%dT%H:%M:%S.0")


def bounds(day):
    return {"startTimestampGMT": gmt(day, 0), "startTimestampLocal": f"{day}T00:00:00.0",
            "calendarDate": day.isoformat()}


def hr_payload(day, bpm=70):
    values = [[epoch_ms(day, m), bpm] for m in range(0, 1440, 2)]
    values[3][1] = None                      # Garmin leaves gaps as null
    values.append([epoch_ms(day, 1440), 99])  # a sample belonging to the next day
    return {**bounds(day), "restingHeartRate": 55, "heartRateValues": values}


def stress_payload(day, level=30):
    stress = [[epoch_ms(day, m), level] for m in range(0, 1440, 3)]
    stress[10][1] = -1                       # off wrist
    stress[11][1] = -2                       # activity
    battery = [[epoch_ms(day, m), "MEASURED", 50 if m < 720 else 40, 2.0]
               for m in range(0, 1440, 3)]
    return {**bounds(day), "stressValuesArray": stress, "bodyBatteryValuesArray": battery}


def steps_payload(day, steps=100):
    return [{"startGMT": gmt(day, m), "endGMT": gmt(day, m + 15), "steps": steps,
             "primaryActivityLevel": "sleeping" if m < 420 else
             ("highlyActive" if m == 600 else "sedentary"), "activityLevelConstant": True}
            for m in range(0, 1440, 15)]


class FakeClient:
    def __init__(self, fail=None, missing=()):
        self.calls = []
        self.fail = fail
        self.missing = set(missing)

    def _hit(self, name, cdate):
        self.calls.append((name, cdate))
        if name == self.fail:
            raise Exception("429 Client Error: Too Many Requests")
        if name in self.missing:
            raise Exception("404 Not Found")

    def get_heart_rates(self, cdate):
        self._hit("get_heart_rates", cdate)
        return hr_payload(dt.date.fromisoformat(cdate))

    def get_stress_data(self, cdate):
        self._hit("get_stress_data", cdate)
        return stress_payload(dt.date.fromisoformat(cdate))

    def get_steps_data(self, cdate):
        self._hit("get_steps_data", cdate)
        return steps_payload(dt.date.fromisoformat(cdate))


# --- parsing ---------------------------------------------------------------------------

def test_offset_from_payload_and_zone():
    day = dt.date(2026, 10, 6)
    assert gi.payload_offset_min(bounds(day)) == 330
    assert gi.payload_offset_min({}) is None
    assert gi.zone_offset_min("Asia/Kolkata", day) == 330
    assert gi.zone_offset_min("Not/AZone", day) == 0


def test_parse_heart_rates_drops_nulls_and_other_days():
    day = dt.date(2026, 10, 6)
    hr, resting = gi.parse_heart_rates(hr_payload(day), day, OFFSET)
    assert resting == 55 and len(hr) == 719 and hr[0] == [0, 70] and hr[-1] == [1438, 70]
    assert all(v == 70 for _, v in hr)


def test_parse_stress_drops_negatives_and_compacts_battery():
    day = dt.date(2026, 10, 6)
    stress, battery = gi.parse_stress(stress_payload(day), day, OFFSET)
    assert len(stress) == 478 and all(0 <= v <= 100 for _, v in stress)
    assert battery == [[0, 50], [720, 40], [1437, 40]]       # change points + last


def test_parse_steps_levels():
    day = dt.date(2026, 10, 6)
    rows = gi.parse_steps(steps_payload(day), day, OFFSET)
    assert len(rows) == 96 and rows[0] == [0, 100, "sleeping"]
    assert rows[40] == [600, 100, "highly_active"] and rows[-1][2] == "sedentary"
    assert gi.parse_steps({"not": "a list"}, day, OFFSET) == []


# --- storing ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_store_day_merges_and_computes_aggregates(athlete):
    day = athlete.local_today - dt.timedelta(days=1)
    DailyMetrics.objects.create(athlete=athlete, metric_date=day, raw={"stats": {
        "dailyStepGoal": 7000, "totalSteps": 9600, "sedentarySeconds": 36000,
        "activeSeconds": 3600, "highlyActiveSeconds": 900, "bodyBatteryChargedValue": 50}})
    row = gi.store_day(athlete, day, heart_rates=hr_payload(day), complete=True)
    assert row.hr and row.stress == [] and row.complete and row.resting_hr == 55
    row = gi.store_day(athlete, day, stress=stress_payload(day), steps=steps_payload(day))
    row.refresh_from_db()
    assert row.hr and row.stress and row.steps and row.body_battery     # earlier arrays kept
    assert row.utc_offset_min == 330
    assert row.steps_total == 9600 and row.step_goal == 7000
    assert (row.sedentary_min, row.active_min, row.intense_min) == (600, 60, 15)
    assert row.stress_avg == 30 and row.stress_high_min == 0
    assert row.awake_hr_avg == 70 and row.bb_charged == 50
    assert IntradayDay.objects.count() == 1


@pytest.mark.django_db
def test_store_day_with_nothing_usable(athlete):
    assert gi.store_day(athlete, athlete.local_today, heart_rates={}) is None
    assert not IntradayDay.objects.exists()


# --- fetching --------------------------------------------------------------------------

@pytest.mark.django_db
def test_sync_intraday_today_and_yesterday(athlete, monkeypatch):
    pauses = []
    monkeypatch.setattr(garmin_slow.time, "sleep", pauses.append)
    from django.conf import settings
    settings.GARMIN_SLOW_PAUSE_S = 1.5
    client = FakeClient()
    result = gi.sync_intraday(athlete, client)
    today = athlete.local_today
    assert result["days"] == 2 and result["calls"] == 6 and result["rate_limited"] is False
    assert [c[1] for c in client.calls[:3]] == [today.isoformat()] * 3
    assert {c[0] for c in client.calls} == {"get_heart_rates", "get_stress_data", "get_steps_data"}
    assert pauses == [1.5] * 5                            # spaced
    rows = {r.day: r for r in IntradayDay.objects.all()}
    assert rows[today].complete is False and rows[today - dt.timedelta(days=1)].complete is True


@pytest.mark.django_db
def test_sync_intraday_minimal_skips_heart_rate(athlete):
    client = FakeClient()
    gi.sync_intraday(athlete, client, [athlete.local_today], minimal=True)
    assert [c[0] for c in client.calls] == ["get_stress_data", "get_steps_data"]


@pytest.mark.django_db
def test_missing_endpoint_is_skipped(athlete):
    client = FakeClient(missing={"get_heart_rates"})
    result = gi.sync_intraday(athlete, client, [athlete.local_today])
    assert result["missing"] == ["heart rates"]
    row = IntradayDay.objects.get()
    assert row.hr == [] and row.stress


@pytest.mark.django_db
def test_429_stops_and_trips_breaker(athlete, monkeypatch):
    athlete.garmin_connected = True
    athlete.save()
    client = FakeClient(fail="get_stress_data")
    monkeypatch.setattr("apps.ingest.garmin._client", lambda a: client)
    result = tasks.sync_intraday_one(athlete.pk)
    assert result == {"skipped": "rate_limited"} or result.get("rate_limited")
    assert tasks.garmin_blocked()
    assert len(client.calls) == 2                         # hr, then the 429 — nothing more
    other = FakeClient()
    monkeypatch.setattr("apps.ingest.garmin._client", lambda a: other)
    assert tasks.sync_intraday_one(athlete.pk) == {"skipped": "rate_limited"}
    assert other.calls == []


@pytest.mark.django_db
def test_breaker_opening_mid_run_stops(athlete):
    class Tripping(FakeClient):
        def get_stress_data(self, cdate):
            tasks.trip_breaker("another worker hit 429")
            return super().get_stress_data(cdate)

    client = Tripping()
    result = gi.sync_intraday(athlete, client)
    assert result["rate_limited"] is True and len(client.calls) == 2


@pytest.mark.django_db
def test_sync_one_queues_the_intraday_fetch(athlete, monkeypatch, no_real_garmin_queue):
    from apps.ingest.garmin import SyncResult

    athlete.garmin_connected = True
    athlete.save()
    monkeypatch.setattr(tasks, "sync_athlete", lambda a: SyncResult())
    monkeypatch.setattr("apps.planning.tasks.adapt_week_task.delay", lambda *a: None)
    tasks.sync_one(athlete.pk)
    names = [q[0] for q in no_real_garmin_queue]
    assert "sync_intraday_one" in names and "sync_slow_one" in names
    intraday = next(q for q in no_real_garmin_queue if q[0] == "sync_intraday_one")
    assert intraday[1] == (athlete.pk,) and intraday[3] == tasks.INTRADAY_DELAY_S


@pytest.mark.django_db
def test_no_intraday_queued_after_a_rate_limited_sync(athlete, monkeypatch, no_real_garmin_queue):
    from apps.ingest.garmin import SyncResult

    athlete.garmin_connected = True
    athlete.save()
    monkeypatch.setattr(tasks, "sync_athlete",
                        lambda a: SyncResult(errors=["Garmin rate-limited the download"]))
    monkeypatch.setattr("apps.planning.tasks.adapt_week_task.delay", lambda *a: None)
    tasks.sync_one(athlete.pk)
    assert no_real_garmin_queue == []
    assert tasks.queue_intraday(athlete) is False          # breaker now open


# --- backfill command ------------------------------------------------------------------

@pytest.mark.django_db
def test_backfill_command_queues_spaced_chunks(athlete, no_real_garmin_queue):
    athlete.garmin_connected = True
    athlete.save()
    IntradayDay.objects.create(athlete=athlete, day=athlete.local_today - dt.timedelta(days=1),
                               complete=True)
    call_command("garmin_backfill_intraday", "--athlete", str(athlete.pk), "--days", "30")
    chunks = [q for q in no_real_garmin_queue if q[0] == "backfill_intraday"]
    days = [d for q in chunks for d in q[1][1]]
    assert len(days) == 29 and len(set(days)) == 29          # the complete day skipped
    assert [len(q[1][1]) for q in chunks] == [7, 7, 7, 7, 1]
    assert [q[3] for q in chunks] == [0, 300, 600, 900, 1200]


@pytest.mark.django_db
def test_backfill_command_now_and_force(athlete, monkeypatch):
    athlete.garmin_connected = True
    athlete.save()
    client = FakeClient()
    monkeypatch.setattr("apps.ingest.garmin._client", lambda a: client)
    call_command("garmin_backfill_intraday", "--athlete", str(athlete.pk), "--days", "3", "--now")
    assert IntradayDay.objects.filter(complete=True).count() == 3 and len(client.calls) == 9
    call_command("garmin_backfill_intraday", "--athlete", str(athlete.pk), "--days", "3", "--now")
    assert len(client.calls) == 9                            # nothing left to fetch
    call_command("garmin_backfill_intraday", "--athlete", str(athlete.pk), "--days", "3", "--now",
                 "--force")
    assert len(client.calls) == 18


@pytest.mark.django_db
def test_backfill_command_refuses_while_breaker_open_or_without_target(athlete):
    with pytest.raises(CommandError):
        call_command("garmin_backfill_intraday")
    tasks.trip_breaker("429")
    with pytest.raises(CommandError):
        call_command("garmin_backfill_intraday", "--all")


@pytest.mark.django_db
def test_backfill_now_stops_on_429(athlete, monkeypatch):
    athlete.garmin_connected = True
    athlete.save()
    client = FakeClient(fail="get_heart_rates")
    monkeypatch.setattr("apps.ingest.garmin._client", lambda a: client)
    call_command("garmin_backfill_intraday", "--athlete", str(athlete.pk), "--days", "20", "--now")
    assert len(client.calls) == 1 and tasks.garmin_blocked()


# --- nudge refresh ---------------------------------------------------------------------

@pytest.mark.django_db
def test_intraday_refresh_only_for_nudge_users_in_hours(athlete, other_athlete, settings,
                                                         no_real_garmin_queue):
    settings.INTRADAY_REFRESH_MIN = 60
    for a in (athlete, other_athlete):
        a.garmin_connected = True
        a.save()
        PushSubscription.objects.create(athlete=a, endpoint=f"https://p.example.com/{a.pk}",
                                        p256dh="k", auth="a")
    every_hour = dict(move=True, move_start=dt.time(0, 0), move_end=dt.time(23, 59),
                      quiet_start=dt.time(0, 0), quiet_end=dt.time(0, 0))
    ReminderSettings.objects.create(athlete=athlete, **every_hour)
    ReminderSettings.objects.create(athlete=other_athlete)         # nudges off
    assert tasks.intraday_refresh() == {"queued": 1}
    q = no_real_garmin_queue[0]
    assert q[0] == "sync_intraday_one" and q[1] == (athlete.pk,)
    assert q[2] == {"today_only": True, "minimal": True}
    # Fresh data: nothing queued.
    IntradayDay.objects.create(athlete=athlete, day=athlete.local_today, fetched_at=timezone.now())
    assert tasks.intraday_refresh() == {"queued": 0}
    settings.INTRADAY_REFRESH_MIN = 0
    assert tasks.intraday_refresh() == {"skipped": "off"}
