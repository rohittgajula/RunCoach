"""R10 §C endpoints and §B8 gear: lung recovery, weekly report (+ AI without the private
habit), compare any two, reminders / web push, achievements, the readiness forecast and
shoes — plus tenant isolation and account deletion for every new model."""

import datetime as dt
import json

import pytest
from django.utils import timezone

from apps.coaching import services as coaching
from apps.gear.models import Shoe, ShoeAssignment
from apps.habits.models import HabitLog
from apps.health.models import Achievement, WeeklyReport
from apps.reminders.models import PushSubscription, ReminderSettings
from tests.r10_helpers import metric, night, run

PASSWORD = "correct-horse-battery-1"


def ago(athlete, n):
    return athlete.local_today - dt.timedelta(days=n)


def log(athlete, kind, qty=1, days_ago=0, hour=12):
    local = athlete.local_now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return HabitLog.objects.create(athlete=athlete, kind=kind, quantity=qty,
                                   at=local - dt.timedelta(days=days_ago))


def fake_ai(monkeypatch, seen):
    def fake_complete(*, operation, schema, user, **kw):
        seen.append((operation, user))
        return schema(markdown="A steady week."), {
            "model": "m", "input_tokens": 1, "output_tokens": 1, "latency_ms": 1,
            "retry_count": 0, "estimated_cost_usd": 0}
    monkeypatch.setattr(coaching, "complete", fake_complete)


def last_monday(athlete):
    today = athlete.local_today
    return today - dt.timedelta(days=today.weekday()) - dt.timedelta(days=7)


# --- C9 lung recovery ---------------------------------------------------------------

def test_lung_recovery_hidden_without_quit_date(api):
    body = api.get("/api/habits/lung-recovery/").json()
    assert body["available"] is False and body["reason"] == "no_quit_date"
    assert body["metrics"] == [] and body["milestones"] == []


def test_lung_recovery_future_quit_date(api, athlete):
    athlete.smoke_quit_date = ago(athlete, -3)
    athlete.save()
    assert api.get("/api/habits/lung-recovery/").json()["reason"] == "quit_date_in_future"


def test_lung_recovery_compares_before_and_since(api, athlete):
    quit_date = ago(athlete, 30)
    athlete.smoke_quit_date = quit_date
    athlete.save()
    for i in range(1, 15):
        metric(athlete, quit_date - dt.timedelta(days=i), respiration_sleep_avg=16.0,
               resting_hr=62, sleep_spo2_avg=94.0)
    for i in range(14):
        metric(athlete, ago(athlete, i), respiration_sleep_avg=15.0, resting_hr=59,
               sleep_spo2_avg=94.5)
    body = api.get("/api/habits/lung-recovery/").json()
    assert body["available"] is True and body["days_since_quit"] == 30
    rows = {m["key"]: m for m in body["metrics"]}
    assert list(rows) == ["sleep_breathing_rate", "spo2", "resting_hr", "easy_hr"]
    assert rows["sleep_breathing_rate"]["better"] is True
    assert rows["resting_hr"]["change"] == -3.0 and rows["resting_hr"]["better"] is True
    assert rows["spo2"]["better"] is None              # +0.5 is below the 1-point threshold
    assert rows["easy_hr"]["enough_data"] is False
    assert len(rows["resting_hr"]["series"]) == 28
    assert len(body["milestones"]) == 8 and body["milestones"][0]["reached"] is True
    assert "cause" in body["note"]


# --- C10 weekly report -----------------------------------------------------------------

def test_weekly_report_built_on_read_and_stored(api, athlete):
    monday = last_monday(athlete)
    run(athlete, monday, km=5.2, zones={"Z1": 600, "Z2": 1200, "Z3": 100, "below": 50})
    run(athlete, monday + dt.timedelta(days=3), km=4.0)
    run(athlete, monday - dt.timedelta(days=4), km=3.0)
    for i in range(7):
        metric(athlete, monday + dt.timedelta(days=i), hrv_overnight_avg=50, resting_hr=56,
               sleep_seconds=7 * 3600)
        metric(athlete, monday - dt.timedelta(days=i + 1), hrv_overnight_avg=44,
               resting_hr=59, sleep_seconds=6 * 3600)
    log(athlete, "alcohol", 4, days_ago=(athlete.local_today - monday).days - 1)
    body = api.get("/api/reports/weekly/").json()
    assert body["week_start"] == str(monday) and body["week_end"] == str(monday + dt.timedelta(days=6))
    assert body["runs"]["done"] == 2 and body["runs"]["km"] == 9.2
    assert body["runs"]["previous_done"] == 1 and body["runs"]["previous_km"] == 3.0
    assert body["zones"]["Z2"] == 1200 and body["zones_total_s"] == 1900
    wellness = {w["metric"]: w for w in body["wellness"]}
    assert wellness["hrv"]["better"] is True and wellness["sleep"]["this_week"] == 7.0
    habits = {h["habit"]: h for h in body["habits"]}
    assert habits["alcohol"]["this_week"] == 4 and habits["alcohol"]["better"] is False
    assert body["went_well"] and body["goal"] and body["ai"]["status"] == "none"
    assert WeeklyReport.objects.filter(athlete=athlete).count() == 1
    api.get("/api/reports/weekly/", {"week": str(monday + dt.timedelta(days=2))})
    assert WeeklyReport.objects.filter(athlete=athlete).count() == 1
    listing = api.get("/api/reports/weekly/list/").json()
    assert listing[0]["week_start"] == str(monday) and listing[0]["runs_done"] == 2


def test_weekly_report_rejects_current_week_and_bad_dates(api, athlete):
    assert api.get("/api/reports/weekly/", {"week": str(athlete.local_today)}).status_code == 400
    assert api.get("/api/reports/weekly/", {"week": "nope"}).status_code == 400


def test_weekly_report_private_habit_shown_but_never_sent_to_ai(api, athlete, monkeypatch):
    athlete.private_habit_enabled = True
    athlete.save()
    monday = last_monday(athlete)
    days = (athlete.local_today - monday).days
    log(athlete, "private", 3, days_ago=days - 1)
    log(athlete, "alcohol", 2, days_ago=days - 1)
    run(athlete, monday)
    body = api.get("/api/reports/weekly/").json()
    assert any(h["habit"] == "private" for h in body["habits"])
    seen = []
    fake_ai(monkeypatch, seen)
    r = api.post("/api/reports/weekly/ai/")
    assert r.status_code == 200 and r.json()["status"] == "ready"
    assert r.json()["markdown"] == "A steady week."
    operation, prompt = seen[0]
    assert operation == "weekly_report"
    assert "private" not in prompt.lower()
    # Cached: a second tap costs nothing.
    api.post("/api/reports/weekly/ai/")
    assert len(seen) == 1
    assert api.get("/api/reports/weekly/").json()["ai"]["status"] == "ready"
    api.post("/api/reports/weekly/ai/?refresh=1")
    assert len(seen) == 2
    # Turning the habit off hides its row (and its bullet lines) from the stored report.
    athlete.private_habit_enabled = False
    athlete.save()
    body = api.get("/api/reports/weekly/").json()
    assert all(h["habit"] != "private" for h in body["habits"])
    assert "Private" not in json.dumps(body["went_well"] + body["to_improve"] + [body["goal"]])


def test_weekly_report_ai_unavailable(api, athlete, monkeypatch):
    from apps.coaching.client import AIUnavailable

    def boom(**kw):
        raise AIUnavailable("no key")
    monkeypatch.setattr(coaching, "complete", boom)
    r = api.post("/api/reports/weekly/ai/")
    assert r.status_code == 503 and r.json()["detail"] == "no key"


def test_weekly_report_beat_only_at_monday_six_local(athlete, monkeypatch):
    from apps.health import tasks

    queued = []
    monkeypatch.setattr(tasks.build_weekly_report, "delay", lambda pk: queued.append(pk))
    monday_six = dt.datetime(2026, 10, 5, 6, 10, tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30)))
    monkeypatch.setattr(type(athlete), "local_now", property(lambda self: monday_six))
    assert tasks.weekly_reports()["queued"] == 1 and queued == [athlete.pk]
    tuesday = monday_six + dt.timedelta(days=1)
    monkeypatch.setattr(type(athlete), "local_now", property(lambda self: tuesday))
    assert tasks.weekly_reports()["queued"] == 0
    result = tasks.build_weekly_report(athlete.pk)
    assert result["week_start"] == "2026-09-28"
    assert tasks.build_weekly_report(athlete.pk)["id"] == result["id"]       # idempotent


# --- C11 compare -------------------------------------------------------------------------

def test_compare_catalogue_hides_private_until_enabled(api, athlete):
    keys = [m["key"] for m in api.get("/api/health/compare/metrics/").json()["metrics"]]
    assert "private" not in keys and {"sleep_h", "easy_hr", "alcohol", "bedtime_h"} <= set(keys)
    assert api.get("/api/health/compare/", {"x": "private", "y": "hrv"}).status_code == 400
    athlete.private_habit_enabled = True
    athlete.save()
    keys = [m["key"] for m in api.get("/api/health/compare/metrics/").json()["metrics"]]
    assert "private" in keys


def test_compare_sleep_vs_next_day_hrv(api, athlete):
    for i in range(1, 13):
        metric(athlete, ago(athlete, i), sleep_seconds=(5 + (i % 4)) * 3600,
               hrv_overnight_avg=40 + 2 * ((i + 1) % 4))   # tracks the night before
    r = api.get("/api/health/compare/", {"x": "sleep_h", "y": "hrv", "lag": "1"})
    body = r.json()
    assert r.status_code == 200 and body["lag"] == 1 and body["n"] == 11
    assert body["x"] == {"key": "sleep_h", "label": "Sleep", "unit": "h"}
    assert body["rho"] == 1.0 and body["direction"] == "positive"
    assert "followed by higher HRV the next day" in body["sentence"]
    assert body["caveat"] and body["trend"]["slope"] > 0
    assert set(body["points"][0]) == {"date", "x", "y"}


def test_compare_habit_counts_zero_on_clean_days(api, athlete):
    log(athlete, "alcohol", 3, days_ago=10)
    for i in range(0, 11):
        metric(athlete, ago(athlete, i), hrv_overnight_avg=45 + i)
    body = api.get("/api/health/compare/", {"x": "alcohol", "y": "hrv"}).json()
    assert body["n"] == 11 and sum(p["x"] for p in body["points"]) == 3


def test_compare_runs_by_run_date(api, athlete):
    for i in range(1, 10):
        night(athlete, ago(athlete, i), hours=5 + i % 3)
        run(athlete, ago(athlete, i), hr=150 - i % 3, easy=True)
    body = api.get("/api/health/compare/", {"x": "sleep_h", "y": "easy_hr"}).json()
    assert body["n"] == 9 and body["rho"] == -1.0
    assert "lower HR at easy pace" in body["sentence"]


@pytest.mark.parametrize("params", [{"x": "hrv"}, {"x": "hrv", "y": "hrv"},
                                    {"x": "nope", "y": "hrv"},
                                    {"x": "hrv", "y": "rhr", "lag": "2"},
                                    {"x": "hrv", "y": "rhr", "range": "2y"}])
def test_compare_validation(api, params):
    r = api.get("/api/health/compare/", params)
    assert r.status_code == 400 and isinstance(r.json()["detail"], str)


# --- C12 reminders ----------------------------------------------------------------------

SUB = {"endpoint": "https://push.example.com/send/abc", "keys": {"p256dh": "BKey", "auth": "auth"}}


@pytest.fixture
def vapid(settings):
    settings.VAPID_PUBLIC_KEY = "BPublicKey"
    settings.VAPID_PRIVATE_KEY = "private"
    settings.VAPID_SUBJECT = "mailto:ops@example.com"


def test_reminders_hidden_without_vapid(api, settings):
    settings.VAPID_PUBLIC_KEY = settings.VAPID_PRIVATE_KEY = settings.VAPID_SUBJECT = ""
    body = api.get("/api/reminders/").json()
    assert body["available"] is False and body["public_key"] is None
    assert [r["key"] for r in body["reminders"]] == ["morning_checkin", "habit_log",
                                                     "best_run_time", "weekly_report"]
    assert all(r["enabled"] is False for r in body["reminders"]) and "Home Screen" in body["ios_note"]
    assert api.post("/api/reminders/subscribe/", SUB, format="json").status_code == 503
    assert api.post("/api/reminders/test/").status_code == 503
    from apps.reminders.tasks import send_due

    assert send_due() == {"skipped": "not_configured"}


def test_reminder_settings_patch(api):
    r = api.patch("/api/reminders/", {"habit_log": {"enabled": True, "time": "21:30"}},
                  format="json")
    assert r.status_code == 200
    row = {x["key"]: x for x in r.json()["reminders"]}["habit_log"]
    assert row == {**row, "enabled": True, "time": "21:30"}
    for bad in ({"nope": {"enabled": True}}, {"habit_log": {"time": "25:00"}},
                {"habit_log": {"enabled": "yes"}}, {"habit_log": {"colour": 1}}):
        assert api.patch("/api/reminders/", bad, format="json").status_code == 400


def test_subscribe_unsubscribe_and_move_between_accounts(api, other_api, athlete, other_athlete,
                                                         vapid):
    r = api.post("/api/reminders/subscribe/", SUB, format="json")
    assert r.status_code == 201 and r.json()["created"] is True
    again = api.post("/api/reminders/subscribe/", SUB, format="json")
    assert again.status_code == 200 and again.json()["created"] is False
    assert api.get("/api/reminders/").json()["subscriptions"] == 1
    assert api.get("/api/reminders/").json()["public_key"] == "BPublicKey"
    # Another account signs in on the same browser: the subscription follows it.
    other_api.post("/api/reminders/subscribe/", SUB, format="json")
    assert PushSubscription.objects.get().athlete_id == other_athlete.pk
    # Unsubscribe only ever touches the requester's rows.
    assert api.post("/api/reminders/unsubscribe/", {"endpoint": SUB["endpoint"]},
                    format="json").json() == {"deleted": 0}
    assert other_api.post("/api/reminders/unsubscribe/", {"endpoint": SUB["endpoint"]},
                          format="json").json() == {"deleted": 1}
    bad = {"endpoint": "http://insecure", "keys": SUB["keys"]}
    assert api.post("/api/reminders/subscribe/", bad, format="json").status_code == 400
    assert api.post("/api/reminders/subscribe/", {"endpoint": SUB["endpoint"]},
                    format="json").status_code == 400


def test_push_send_and_expired_subscription(api, athlete, vapid, monkeypatch):
    import pywebpush

    sent = []

    def fake_webpush(subscription_info, data, vapid_private_key, vapid_claims, **kw):
        sent.append((subscription_info["endpoint"], json.loads(data), vapid_claims))
        if "gone" in subscription_info["endpoint"]:
            class Resp:
                status_code = 410
            raise pywebpush.WebPushException("gone", response=Resp())
    monkeypatch.setattr(pywebpush, "webpush", fake_webpush)
    api.post("/api/reminders/subscribe/", SUB, format="json")
    api.post("/api/reminders/subscribe/", {**SUB, "endpoint": "https://push.example.com/gone"},
             format="json")
    r = api.post("/api/reminders/test/").json()
    assert r == {"sent": 1, "failed": 1}
    assert PushSubscription.objects.count() == 1          # the expired one is deleted
    assert sent[0][2] == {"sub": "mailto:ops@example.com"}
    assert set(sent[0][1]) == {"title", "body", "url", "tag"}


def test_beat_sends_each_due_reminder_once_a_day(athlete, vapid, monkeypatch):
    from apps.reminders import tasks as reminder_tasks
    import pywebpush

    sent = []
    monkeypatch.setattr(pywebpush, "webpush", lambda **kw: sent.append(json.loads(kw["data"])))
    PushSubscription.objects.create(athlete=athlete, endpoint=SUB["endpoint"], p256dh="k", auth="a")
    now = athlete.local_now
    ReminderSettings.objects.create(
        athlete=athlete, habit_log=True,
        habit_log_time=(now - dt.timedelta(minutes=10)).time().replace(second=0, microsecond=0),
        morning_checkin=True,
        morning_checkin_time=(now + dt.timedelta(minutes=30)).time().replace(second=0,
                                                                            microsecond=0))
    if (now - dt.timedelta(minutes=10)).date() != now.date() or \
            (now + dt.timedelta(minutes=30)).date() != now.date():
        pytest.skip("too close to local midnight for this test")
    assert reminder_tasks.send_due() == {"sent": 1}
    assert [m["tag"] for m in sent] == ["habit_log"]
    assert reminder_tasks.send_due() == {"sent": 0}       # once a day
    row = ReminderSettings.objects.get(athlete=athlete)
    assert row.last_sent["habit_log"] == now.date().isoformat()


def test_reminder_due_window():
    from apps.reminders.service import due

    row = ReminderSettings(habit_log=True, habit_log_time=dt.time(21, 0), last_sent={})
    tz = dt.timezone.utc
    assert due(row, "habit_log", dt.datetime(2026, 10, 7, 21, 5, tzinfo=tz))
    assert not due(row, "habit_log", dt.datetime(2026, 10, 7, 20, 55, tzinfo=tz))
    assert not due(row, "habit_log", dt.datetime(2026, 10, 7, 23, 5, tzinfo=tz))
    row.last_sent = {"habit_log": "2026-10-07"}
    assert not due(row, "habit_log", dt.datetime(2026, 10, 7, 21, 5, tzinfo=tz))
    assert not due(row, "morning_checkin", dt.datetime(2026, 10, 7, 7, 5, tzinfo=tz))


def test_best_run_time_message_needs_weather(athlete):
    from apps.reminders.service import message

    assert message(athlete, "best_run_time") is None     # weather is offline in tests
    assert message(athlete, "habit_log")["tag"] == "habit_log"


# --- C13 achievements ---------------------------------------------------------------------

def test_achievements_award_store_and_seen(api, athlete):
    athlete.smoke_quit_date = ago(athlete, 10)
    athlete.save()
    run(athlete, ago(athlete, 3), km=5.2)
    run(athlete, ago(athlete, 2))
    run(athlete, ago(athlete, 1))
    for i in range(1, 4):
        night(athlete, ago(athlete, i), hours=7.5)
    body = api.get("/api/achievements/").json()
    badges = {b["key"]: b for b in body["badges"]}
    assert badges["smoke_free_7"]["earned"] is True
    assert badges["smoke_free_7"]["earned_on"] == str(ago(athlete, 4))
    assert badges["smoke_free_14"]["earned"] is False
    assert badges["smoke_free_14"]["progress"] == {"current": 10, "target": 14}
    assert badges["first_5k"]["earned_on"] == str(ago(athlete, 3))
    assert badges["run_streak_3"]["earned"] and badges["sleep_7h_3"]["earned"]
    assert badges["prs_1"]["earned"] is True            # computed bests count as PRs
    assert set(badges["first_5k"]) == {"key", "group", "label", "description", "target", "unit",
                                       "earned", "earned_on", "progress", "new"}
    assert badges["first_5k"]["new"] is True and body["unseen"] > 0
    assert any(r["kind"] == "pr" for r in body["recent"])
    count = Achievement.objects.filter(athlete=athlete).count()
    api.get("/api/achievements/")                        # idempotent
    assert Achievement.objects.filter(athlete=athlete).count() == count
    assert api.post("/api/achievements/seen/").json()["updated"] == body["unseen"]
    assert api.get("/api/achievements/").json()["unseen"] == 0


def test_achievements_old_history_is_not_new_and_smoke_hidden(api, athlete):
    run(athlete, ago(athlete, 60), km=6)
    body = api.get("/api/achievements/").json()
    badges = {b["key"]: b for b in body["badges"]}
    assert "smoke_free_1" not in badges
    assert badges["first_5k"]["earned"] is True and badges["first_5k"]["new"] is False


def test_earned_badge_is_kept_when_the_data_changes(api, athlete):
    athlete.smoke_quit_date = ago(athlete, 5)
    athlete.save()
    api.get("/api/achievements/")
    log(athlete, "smoke", 1, days_ago=0)
    log(athlete, "smoke", 1, days_ago=2)
    badges = {b["key"]: b for b in api.get("/api/achievements/").json()["badges"]}
    assert badges["smoke_free_3"]["earned"] is True


def test_award_task(athlete):
    from apps.health.tasks import award_one

    run(athlete, ago(athlete, 1), km=5.5)
    assert award_one(athlete.pk)["earned"] >= 1
    assert award_one(999_999) == {"skipped": "gone"}


# --- C14 forecast -----------------------------------------------------------------------

def test_forecast_endpoint(api, athlete):
    for i in range(0, 7):
        metric(athlete, ago(athlete, i), training_readiness=70, hrv_overnight_avg=40,
               hrv_baseline_low=45, hrv_baseline_high=60, sleep_seconds=6 * 3600,
               sleep_need_seconds=8 * 3600,
               sleep_start_local=dt.datetime.combine(ago(athlete, i + 1), dt.time(23, 30),
                                                     tzinfo=dt.timezone.utc),
               sleep_end_local=dt.datetime.combine(ago(athlete, i), dt.time(6, 30),
                                                   tzinfo=dt.timezone.utc))
    log(athlete, "alcohol", 2)
    log(athlete, "private", 5) if athlete.private_habit_enabled else None
    body = api.get("/api/health/readiness-forecast/").json()
    assert body["date"] == str(ago(athlete, -1)) and body["is_estimate"] is True
    assert body["today"] == {"score": 70, "source": "garmin"}
    keys = [f["key"] for f in body["factors"]]
    assert "sleep_debt" in keys and "alcohol" in keys and "hrv_trend" in keys
    assert [l["key"] for l in body["levers"]] == ["bedtime", "no_alcohol"]
    assert body["best_case"] > body["estimate"] and "could make it" in body["sentence"]
    assert body["low"] <= body["estimate"] <= body["high"]


def test_forecast_without_data(api):
    body = api.get("/api/health/readiness-forecast/").json()
    assert body["estimate"] is None and body["today"] == {"score": None, "source": None}


def test_forecast_ignores_private_habit(api, athlete):
    athlete.private_habit_enabled = True
    athlete.save()
    metric(athlete, athlete.local_today, training_readiness=60)
    before = api.get("/api/health/readiness-forecast/").json()
    log(athlete, "private", 9)
    after = api.get("/api/health/readiness-forecast/").json()
    assert before == after


# --- B8 gear -------------------------------------------------------------------------------

def test_local_shoes_auto_assign_and_flags(api, athlete):
    run(athlete, ago(athlete, 20), km=6)                # before the shoe: not assigned
    r = api.post("/api/gear/", {"name": "Pegasus", "brand": "Nike", "start_km": 620,
                                "is_default": True, "in_use_since": str(ago(athlete, 10))},
                 format="json")
    assert r.status_code == 201 and r.json()["source"] == "local"
    shoe_id = r.json()["id"]
    run(athlete, ago(athlete, 5), km=50)
    run(athlete, ago(athlete, 2), km=40)
    body = api.get("/api/gear/").json()
    shoe = body["shoes"][0]
    assert shoe["distance_km"] == 710.0 and shoe["activities"] == 2
    assert shoe["replace_due"] is True and shoe["replace_soon"] is True
    assert shoe["remaining_km"] == 0 and shoe["last_used"] == str(ago(athlete, 2))
    assert body["default_retire_km"] == 700
    r = api.patch(f"/api/gear/{shoe_id}/", {"retire_km": 900}, format="json")
    assert r.json()["replace_due"] is False and r.json()["remaining_km"] == 190
    assert api.post("/api/gear/", {"name": ""}, format="json").status_code == 400
    assert api.post("/api/gear/", {"name": "X", "retire_km": 50}, format="json").status_code == 400
    second = api.post("/api/gear/", {"name": "Novablast", "is_default": True}, format="json").json()
    assert Shoe.objects.get(pk=shoe_id).is_default is False and second["is_default"] is True
    assert api.delete(f"/api/gear/{shoe_id}/").status_code == 204
    assert ShoeAssignment.objects.count() == 0


def test_garmin_shoe_limits(api, athlete):
    shoe = Shoe.objects.create(athlete=athlete, name="Revolution", source="garmin",
                               garmin_uuid="u1", garmin_distance_m=10668.3, garmin_activities=6,
                               garmin_max_km=650)
    body = api.get("/api/gear/").json()["shoes"][0]
    assert body["distance_km"] == 10.7 and body["activities"] == 6 and body["retire_km"] == 650
    assert api.patch(f"/api/gear/{shoe.pk}/", {"name": "x"}, format="json").status_code == 400
    assert api.patch(f"/api/gear/{shoe.pk}/", {"retired": True},
                     format="json").json()["retired"] is True
    assert api.delete(f"/api/gear/{shoe.pk}/").status_code == 400


# --- tenant isolation & deletion ------------------------------------------------------------

def test_tenant_isolation_for_feature_endpoints(api, other_api, athlete):
    shoe = api.post("/api/gear/", {"name": "Mine"}, format="json").json()
    assert other_api.patch(f"/api/gear/{shoe['id']}/", {"retire_km": 300},
                           format="json").status_code == 404
    assert other_api.delete(f"/api/gear/{shoe['id']}/").status_code == 404
    assert other_api.get("/api/gear/").json()["shoes"] == []
    athlete.smoke_quit_date = ago(athlete, 20)
    athlete.save()
    run(athlete, ago(athlete, 8), km=6)
    api.get("/api/achievements/")
    api.get("/api/reports/weekly/")
    assert other_api.get("/api/habits/lung-recovery/").json()["available"] is False
    other_achievements = other_api.get("/api/achievements/").json()
    assert other_achievements["recent"] == [] and other_achievements["unseen"] == 0
    assert other_api.get("/api/reports/weekly/list/").json() == []
    assert other_api.get("/api/reports/weekly/").json()["runs"]["done"] == 0
    assert other_api.post("/api/achievements/seen/").json()["updated"] == 0
    assert Achievement.objects.filter(athlete=athlete, seen_at__isnull=True).exists()
    log(athlete, "alcohol", 5, days_ago=1)
    for i in range(10):
        metric(athlete, ago(athlete, i), hrv_overnight_avg=40 + i)
    assert other_api.get("/api/health/compare/", {"x": "alcohol", "y": "hrv"}).json()["n"] == 0
    metric(athlete, athlete.local_today, training_readiness=80)
    assert other_api.get("/api/health/readiness-forecast/").json()["estimate"] is None
    other_api.patch("/api/reminders/", {"habit_log": {"enabled": True}}, format="json")
    mine = {r["key"]: r for r in api.get("/api/reminders/").json()["reminders"]}
    assert mine["habit_log"]["enabled"] is False


@pytest.mark.parametrize("url", ["/api/gear/", "/api/habits/lung-recovery/", "/api/reports/weekly/",
                                 "/api/reports/weekly/list/", "/api/achievements/",
                                 "/api/health/compare/metrics/", "/api/health/readiness-forecast/",
                                 "/api/reminders/"])
def test_feature_endpoints_need_auth(client, db, url):
    assert client.get(url).status_code == 401


def test_account_deletion_covers_every_r10_model(api, athlete, other_athlete, settings, tmp_path):
    from apps.ingest.models import (
        BodyComposition, GarminProfile, LactateThreshold, PersonalRecord,
    )

    settings.MEDIA_ROOT = tmp_path / "media"
    settings.GARMIN_TOKEN_DIR = str(tmp_path / "garmin")

    def populate(a):
        act = run(a, ago(a, 1))
        shoe = Shoe.objects.create(athlete=a, name="S")
        ShoeAssignment.objects.create(shoe=shoe, activity=act)
        GarminProfile.objects.create(athlete=a)
        PersonalRecord.objects.create(athlete=a, key="5k", value=1500)
        BodyComposition.objects.create(athlete=a, measured_on=ago(a, 1), weight_kg=70)
        LactateThreshold.objects.create(athlete=a, measured_on=ago(a, 1), heart_rate=170)
        WeeklyReport.objects.create(athlete=a, week_start=last_monday(a), payload={})
        Achievement.objects.create(athlete=a, key="first_5k", label="x", earned_on=ago(a, 1))
        PushSubscription.objects.create(athlete=a, endpoint=f"https://p.example.com/{a.pk}",
                                        p256dh="k", auth="a")
        ReminderSettings.objects.create(athlete=a)

    populate(athlete)
    populate(other_athlete)
    models = [Shoe, ShoeAssignment, GarminProfile, PersonalRecord, BodyComposition,
              LactateThreshold, WeeklyReport, Achievement, PushSubscription, ReminderSettings]
    assert api.delete("/api/auth/me/", {"password": PASSWORD}, format="json").status_code == 204
    for model in models:
        assert model.objects.count() == 1, model.__name__     # only the other athlete's left
    assert ShoeAssignment.objects.get().shoe.athlete_id == other_athlete.pk
    assert timezone.now()
