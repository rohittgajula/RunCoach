"""R13 §8 cravings + savings, §9 caffeine, §15 data export, and account deletion /
tenant isolation for every new R13 model."""

import datetime as dt
import io
import zipfile

import pytest
from django.utils import timezone

from apps.athletes.models import DataExport
from apps.habits.models import CravingLog, HabitLog


def at(athlete, days_ago=0, hour=12):
    local = dt.datetime.combine(athlete.local_today - dt.timedelta(days=days_ago),
                                dt.time(hour), tzinfo=athlete.local_now.tzinfo)
    return local.astimezone(dt.timezone.utc)


# --- §8 -----------------------------------------------------------------------------

def test_craving_crud_cigarette_link_and_isolation(api, other_api, athlete):
    r = api.post("/api/habits/cravings/", {"intensity": 4, "trigger": "coffee", "place": "Office",
                                           "mood": 2, "at": at(athlete, 1, 9).isoformat()},
                 format="json")
    assert r.status_code == 201, r.json()
    body = r.json()
    assert set(body) == {"id", "at", "local_date", "intensity", "trigger", "place", "mood",
                         "smoked", "cigarette_log_id", "note", "created_at"}
    assert body["smoked"] is False and body["cigarette_log_id"] is None
    smoked = api.post("/api/habits/cravings/", {"intensity": 5, "trigger": "alcohol",
                                                "smoked": True}, format="json").json()
    log = HabitLog.objects.get(pk=smoked["cigarette_log_id"])
    assert log.kind == "smoke" and log.quantity == 1
    # Un-smoking the craving removes the cigarette; smoking again re-creates it.
    r = api.patch(f"/api/habits/cravings/{smoked['id']}/", {"smoked": False}, format="json")
    assert r.json()["cigarette_log_id"] is None and not HabitLog.objects.filter(pk=log.pk).exists()
    r = api.patch(f"/api/habits/cravings/{body['id']}/", {"smoked": True}, format="json")
    assert r.json()["cigarette_log_id"]
    for bad in ({"intensity": 6, "trigger": "coffee"}, {"intensity": 3, "trigger": "tv"},
                {"intensity": 3, "trigger": "other", "mood": 0},
                {"intensity": 3, "trigger": "other", "at": "2999-01-01T00:00:00Z"}):
        assert api.post("/api/habits/cravings/", bad, format="json").status_code == 400, bad
    assert len(api.get("/api/habits/cravings/").json()) == 2
    assert other_api.get("/api/habits/cravings/").json() == []
    assert other_api.patch(f"/api/habits/cravings/{body['id']}/", {"smoked": False},
                           format="json").status_code == 404
    assert other_api.delete(f"/api/habits/cravings/{body['id']}/").status_code == 404
    assert api.delete(f"/api/habits/cravings/{body['id']}/").status_code == 204
    assert api.get("/api/habits/cravings/?days=0").status_code == 400


def test_craving_summary_and_savings(api, athlete):
    athlete.smoke_quit_date = athlete.local_today - dt.timedelta(days=10)
    athlete.smoke_baseline_per_day = 10
    athlete.cigarette_price = 15
    athlete.save()
    r = api.patch("/api/athlete/", {"savings_goal_name": "New shoes",
                                    "savings_goal_amount": 6000}, format="json")
    assert r.status_code == 200
    athlete.refresh_from_db()
    for hour, trigger, smoked in ((9, "coffee", False), (9, "coffee", True), (21, "stress", False)):
        CravingLog.objects.create(athlete=athlete, at=at(athlete, 1, hour), intensity=3,
                                  trigger=trigger, place="Home", smoked=smoked)
    body = api.get("/api/habits/cravings/summary/").json()
    assert body["total"] == 3 and body["resisted"] == 2 and body["resisted_pct"] == 67
    assert body["by_trigger"][0]["trigger"] == "coffee"
    assert body["peak_hours"][0] == {"hour": 9, "count": 2}
    assert body["range"] == "4w" and "period" in body
    savings = body["savings"]
    assert savings["name"] == "New shoes" and savings["amount"] == 6000
    assert savings["saved"] == 1500.0 and savings["pct"] == 25 and savings["eta"]
    assert api.get("/api/habits/cravings/summary/?range=9d").status_code == 400


def test_cravings_badge(api, athlete):
    CravingLog.objects.create(athlete=athlete, at=timezone.now(), intensity=3, trigger="other")
    badges = {b["key"]: b for b in api.get("/api/achievements/").json()["badges"]}
    assert badges["cravings_resisted_1"]["earned"] is True
    assert badges["cravings_resisted_10"]["progress"] == {"current": 1, "target": 10}


def test_no_cravings_no_badge_group(api):
    keys = {b["key"] for b in api.get("/api/achievements/").json()["badges"]}
    assert not any(k.startswith("cravings_") for k in keys)


# --- §9 -----------------------------------------------------------------------------

def test_caffeine_logging_today_and_report(api, other_api, athlete):
    r = api.post("/api/habits/logs/", {"kind": "caffeine", "quantity": 2, "subtype": "tea",
                                       "at": at(athlete, 1, 15).isoformat()}, format="json")
    assert r.status_code == 201 and r.json()["subtype"] == "tea"
    r = api.post("/api/habits/logs/", {"kind": "caffeine"}, format="json")
    assert r.json()["subtype"] == "coffee"
    assert api.post("/api/habits/logs/", {"kind": "smoke", "subtype": "tea"},
                    format="json").status_code == 400
    assert api.post("/api/habits/logs/", {"kind": "caffeine", "subtype": "beer"},
                    format="json").status_code == 400
    today = api.get("/api/habits/today/").json()
    assert "caffeine" not in today["counts"]
    assert today["caffeine"]["count"] == 1 and today["caffeine"]["on_today"] is False
    body = api.get("/api/habits/caffeine/?range=7d").json()
    assert body["total"] == 3 and body["late_days"] == 1 and body["late_cutoff"] == "14:00"
    assert body["by_type"]["tea"] == 2 and len(body["impact"]) == 3
    assert {"range", "start", "end", "period", "series", "caveat"} <= set(body)
    # Not part of the smoke/alcohol/sugar summary.
    assert "caffeine" not in api.get("/api/habits/summary/").json()
    assert other_api.get("/api/habits/caffeine/").json()["total"] == 0
    r = api.delete("/api/habits/logs/?kind=caffeine")
    assert r.json() == {"deleted": 2}


def test_caffeine_compare_series(api, athlete):
    HabitLog.objects.create(athlete=athlete, kind="caffeine", at=at(athlete, 2), subtype="coffee")
    r = api.get("/api/health/compare/?x=caffeine&y=sleep_h&range=7d")
    assert r.status_code == 200


# --- §15 ----------------------------------------------------------------------------

@pytest.fixture
def media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


def test_export_flow(api, other_api, athlete, media, no_real_r13_queue,
                     django_capture_on_commit_callbacks):
    from apps.athletes.export import run_build
    from tests.r10_helpers import run

    run(athlete, athlete.local_today)
    HabitLog.objects.create(athlete=athlete, kind="private", at=timezone.now())
    with django_capture_on_commit_callbacks(execute=True):
        r = api.post("/api/export/")
    assert r.status_code == 202 and r.json()["status"] == "pending"
    export_id = r.json()["id"]
    assert ("build_export", (export_id,), {}) in no_real_r13_queue
    second = api.post("/api/export/")
    assert second.status_code == 429 and second.json()["retry_after_s"] > 0
    assert api.get("/api/export/latest/").json()["export"]["download_url"] is None

    assert run_build(export_id)["size"] > 0
    latest = api.get("/api/export/latest/").json()["export"]
    assert latest["status"] == "ready" and latest["expires_at"]
    url = latest["download_url"]
    assert url.startswith(f"/api/export/{export_id}/download/?token=")
    # Owner + token only.
    assert other_api.get(url).status_code == 404
    assert api.get(f"/api/export/{export_id}/download/?token=wrong").status_code == 404
    assert api.get(f"/api/export/{export_id}/download/").status_code == 404
    from rest_framework.test import APIClient

    assert APIClient().get(url).status_code == 401
    response = api.get(url)
    assert response.status_code == 200 and response["Content-Type"] == "application/zip"
    assert "attachment" in response["Content-Disposition"]
    data = b"".join(response.streaming_content)
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    for name in ("README.txt", "athlete.json", "activities.csv", "laps.csv",
                 "daily_wellness.csv", "intraday_daily.csv", "habits.csv", "cravings.csv",
                 "mood.csv", "water.csv", "meals.csv", "weights.csv", "plans.csv",
                 "workouts.csv", "strength.csv", "pain.csv", "reports_weekly.csv",
                 "reports_monthly.csv"):
        assert name in names
    habits_csv = zipfile.ZipFile(io.BytesIO(data)).read("habits.csv").decode()
    assert "private" in habits_csv          # the athlete's own data, all of it
    # One-time: gone afterwards, file deleted.
    assert api.get(url).status_code == 410
    assert api.get("/api/export/latest/").json()["export"]["status"] == "downloaded"
    assert not list((media / "exports").rglob("*.zip"))


def test_export_expiry_and_cleanup(api, athlete, media):
    from apps.athletes.export import cleanup, file_path, run_build, token_for

    export = DataExport.objects.create(athlete=athlete)
    run_build(export.pk)
    export.refresh_from_db()
    path = file_path(export)
    assert path.exists()
    DataExport.objects.filter(pk=export.pk).update(expires_at=timezone.now() - dt.timedelta(1))
    export.refresh_from_db()
    url = f"/api/export/{export.pk}/download/?token={token_for(export)}"
    assert api.get(url).status_code == 410
    assert api.get("/api/export/latest/").json()["export"]["status"] == "expired"
    assert cleanup() == 1 and not path.exists()


def test_exports_never_served_by_media_route(rf, media):
    from django.http import Http404

    from config.urls import media as media_view

    (media / "exports" / "athlete_1").mkdir(parents=True)
    (media / "exports" / "athlete_1" / "x.zip").write_bytes(b"zip")
    (media / "ok.txt").write_text("fine")
    for path in ("exports/athlete_1/x.zip", "foo/../exports/athlete_1/x.zip", "exports",
                 "/exports/athlete_1/x.zip"):
        with pytest.raises(Http404):
            media_view(rf.get("/"), path)
    assert media_view(rf.get("/"), "ok.txt").status_code == 200


# --- deletion + isolation for every new model ------------------------------------------

def test_account_deletion_removes_every_r13_row_and_exports(athlete, media):
    from apps.activities.models import RunReview
    from apps.activities.reviews import build_review
    from apps.athletes.deletion import delete_account
    from apps.athletes.export import run_build
    from apps.health.models import MonthlyReport, MoodLog, MorningBriefing, PainReport
    from apps.planning.models import StrengthSession, WorkoutAdjustment
    from tests.r10_helpers import run
    from tests.r7_helpers import make_workout

    activity = run(athlete, athlete.local_today)
    build_review(activity)
    workout = make_workout(athlete, athlete.local_today + dt.timedelta(days=1))
    WorkoutAdjustment.objects.create(athlete=athlete, plan=workout.plan, workout=workout,
                                     trigger="run", action="shorten", reason="r", chip="c",
                                     before={}, after={})
    StrengthSession.objects.create(athlete=athlete, date=athlete.local_today, title="S")
    PainReport.objects.create(athlete=athlete, date=athlete.local_today, location="knee",
                              side="left", severity=1)
    MoodLog.objects.create(athlete=athlete, date=athlete.local_today, mood=3, energy=3)
    MonthlyReport.objects.create(athlete=athlete, month=athlete.local_today.replace(day=1))
    MorningBriefing.objects.create(athlete=athlete, date=athlete.local_today)
    CravingLog.objects.create(athlete=athlete, at=timezone.now(), intensity=2, trigger="other")
    export = DataExport.objects.create(athlete=athlete)
    run_build(export.pk)
    assert list((media / "exports").rglob("*.zip"))

    delete_account(athlete.user)
    for model in (RunReview, WorkoutAdjustment, StrengthSession, PainReport, MoodLog,
                  MonthlyReport, MorningBriefing, CravingLog, DataExport):
        assert not model.objects.exists(), model.__name__
    assert not (media / "exports" / f"athlete_{athlete.pk}").exists()
