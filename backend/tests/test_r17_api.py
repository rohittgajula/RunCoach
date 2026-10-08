"""R17 API: delete activities + Garmin-side deletions, data review (nothing excluded
without a decision), illness mode, experiments ×3, coach memory, recovery routine,
isolation and account deletion. Dates are relative to the athlete's local today."""

import datetime as dt

import pytest
from django.utils import timezone

from apps.activities.models import (
    Activity, ActivityQuality, ActivityRecord, ActivityTombstone, GarminDeletionCheck,
    RecoveryLog,
)
from apps.activities.services import derive
from apps.coaching.models import MemoryFact
from apps.health.models import Achievement, DayDataDecision, Illness
from apps.journal.models import JournalEntry
from apps.planning.models import PlannedWorkout, StrengthSession

from .r7_helpers import active_plan, make_workout, wellness
from .r17_streams import run_stream

pytestmark = pytest.mark.django_db


def recorded_run(athlete, day, *, stream=None, garmin_id=None, started_at=None):
    stream = stream or run_stream()
    started = started_at or timezone.make_aware(dt.datetime.combine(day, dt.time(7, 0)))
    activity = Activity.objects.create(
        athlete=athlete, source="garmin_sync", sport="running", garmin_activity_id=garmin_id,
        started_at=started, local_date=day, total_timer_s=len(stream),
        total_elapsed_s=len(stream), total_distance_m=stream[-1].distance_m, avg_hr=140,
        max_hr=160)
    ActivityRecord.objects.bulk_create([
        ActivityRecord(activity=activity, offset_s=s.offset_s, distance_m=s.distance_m,
                       speed_mps=s.speed_mps, cadence_spm=s.cadence_spm,
                       heart_rate=s.heart_rate, latitude=s.latitude, longitude=s.longitude)
        for s in stream])
    derive(activity)
    return Activity.objects.select_related("metrics").get(pk=activity.pk)


def locked_stream():
    s = run_stream()
    for i in range(0, 1100):
        s[i].heart_rate = int(s[i].cadence_spm) + (i % 3 - 1)
    return s


@pytest.fixture
def queued(monkeypatch):
    """Every Garmin job the app would queue (watch removals), recorded instead."""
    calls = []
    monkeypatch.setattr("apps.planning.garmin_sync._queue",
                        lambda task, *args: calls.append((task.name, args)))
    return calls


# --- (1) delete activity, tombstones, Garmin-side deletions ----------------------------

def test_delete_activity_reopens_workout_and_tombstones(api, other_api, athlete,
                                                        monkeypatch):
    day = athlete.local_today - dt.timedelta(days=1)
    run = recorded_run(athlete, day, garmin_id=77)
    workout = make_workout(athlete, day, status="completed")
    workout.completed_activity = run
    workout.save()
    JournalEntry.objects.create(athlete=athlete, text="Post-run check-in: RPE 5/10",
                                written_on=day, applies_to_date=day, activity=run,
                                extracted={"checkin": True, "rpe": 5})
    Achievement.objects.create(athlete=athlete, key=f"pr:computed:fastest_1k:{day}",
                               kind="pr", label="New PR", earned_on=day)

    assert other_api.delete(f"/api/activities/{run.pk}/").status_code == 404
    r = api.delete(f"/api/activities/{run.pk}/")
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["deleted"] == run.pk and body["workouts_reopened"] == [workout.pk]
    assert body["records_removed"] == [f"pr:computed:fastest_1k:{day}"]
    assert not Activity.objects.filter(pk=run.pk).exists()
    assert not ActivityRecord.objects.filter(activity_id=run.pk).exists()
    workout.refresh_from_db()
    assert workout.status == "planned" and workout.completed_activity is None
    assert not JournalEntry.objects.filter(athlete=athlete).exists()

    listed = api.get("/api/activities/deleted/").json()
    assert [t["garmin_activity_id"] for t in listed] == [77]
    assert listed[0]["reason"] == "user" and listed[0]["can_reimport"] is True
    assert other_api.get("/api/activities/deleted/").json() == []

    # A later sync never brings it back (no download is attempted).
    from apps.ingest import garmin

    monkeypatch.setattr(garmin, "_client", lambda a: object())
    monkeypatch.setattr(garmin, "list_new_activities",
                        lambda client, known, *, backfill, cutoff: (
                            [{"activityId": 77, "startTimeLocal": f"{day} 07:00:00"}], True))
    monkeypatch.setattr("apps.ingest.garmin_wellness.sync_wellness",
                        lambda a, c: {"days_written": 0, "rate_limited": False})
    result = garmin.sync_athlete(athlete)
    assert result.skipped == 1 and result.failed == 0 and result.imported == 0


def test_reimport_removes_tombstone(api, other_api, athlete, monkeypatch):
    tomb = ActivityTombstone.objects.create(athlete=athlete, garmin_activity_id=55,
                                            local_date=athlete.local_today)
    upload = ActivityTombstone.objects.create(athlete=athlete, sha256="ab" * 32)
    athlete.garmin_connected = True
    athlete.save(update_fields=["garmin_connected"])
    monkeypatch.setattr("apps.ingest.tasks.run_reimport", lambda a, g: {
        "activity_id": None, "detail": "Garmin no longer has this activity."})
    assert other_api.post(f"/api/activities/deleted/{tomb.pk}/reimport/").status_code == 404
    r = api.post(f"/api/activities/deleted/{tomb.pk}/reimport/")
    assert r.status_code == 200 and r.json()["reimported"] is False
    assert not ActivityTombstone.objects.filter(pk=tomb.pk).exists()
    r = api.post(f"/api/activities/deleted/{upload.pk}/reimport/")
    assert r.json()["detail"].startswith("Upload the file again")


def test_garmin_side_deletion_is_only_ever_a_question(api, athlete):
    from apps.activities.deletion import check_listing

    day = athlete.local_today - dt.timedelta(days=3)
    gone = recorded_run(athlete, day, garmin_id=1)
    kept = recorded_run(athlete, day, garmin_id=2)
    other = recorded_run(athlete, day - dt.timedelta(days=1), garmin_id=3)
    listing = [{"activityId": 2, "startTimeLocal": f"{day} 07:00:00"}]
    # A full page that only reaches back to `day`: older activities are not provable.
    assert check_listing(athlete, listing, page_full=True) == []
    flagged = check_listing(athlete, listing, page_full=False)
    assert sorted(flagged) == sorted([gone.pk, other.pk])
    assert Activity.objects.filter(pk=gone.pk).exists()          # never removed by itself

    items = {i["id"]: i for i in api.get("/api/data-review/").json()["items"]
             if i["kind"] == "deleted_in_garmin"}
    assert items[gone.pk]["pending"] and kept.pk not in items

    r = api.post("/api/data-review/decide/", {"items": [
        {"kind": "deleted_in_garmin", "id": other.pk, "decision": "keep"},
        {"kind": "deleted_in_garmin", "id": gone.pk, "decision": "remove"}]}, format="json")
    assert r.status_code == 200, r.json()
    assert Activity.objects.filter(pk=other.pk).exists()
    assert not Activity.objects.filter(pk=gone.pk).exists()
    assert ActivityTombstone.objects.get(garmin_activity_id=1).reason == "deleted_in_garmin"
    assert check_listing(athlete, listing, page_full=False) == []   # "keep" is remembered
    assert GarminDeletionCheck.objects.get(activity=other).decision == "keep"


# --- (2) data review: nothing excluded without a decision; reversible --------------------

def test_low_quality_run_stays_in_trends_until_excluded(api, other_api, athlete):
    from apps.activities.progress import run_dicts

    run = recorded_run(athlete, athlete.local_today - dt.timedelta(days=2),
                       stream=locked_stream())
    q = api.get(f"/api/activities/{run.pk}/").json()["quality"]
    assert q["suggestion"] == "exclude" and q["decision"] is None
    assert q["excluded_from_trends"] is False and q["use"] == "raw"
    assert q["use_suggestion"] == "cleaned" and q["status"] == "review"
    assert run.pk in [r["id"] for r in run_dicts(athlete)]      # still counted

    review = api.get("/api/data-review/").json()
    assert review["pending"] == 1 and review["items"][0]["kind"] == "run"

    assert other_api.post("/api/data-review/decide/", {"items": [
        {"kind": "run", "id": run.pk, "decision": "exclude"}]},
        format="json").status_code == 400
    r = api.post("/api/data-review/decide/", {"items": [
        {"kind": "run", "id": run.pk, "decision": "exclude"}]}, format="json")
    assert r.status_code == 200 and r.json()["updated"] == 1
    assert run.pk not in [r["id"] for r in run_dicts(athlete)]
    assert api.get(f"/api/activities/{run.pk}/route/").json()["quality"][
        "excluded_from_trends"] is True

    # Reversal.
    api.post("/api/data-review/decide/", {"items": [
        {"kind": "run", "id": run.pk, "decision": None}]}, format="json")
    assert run.pk in [r["id"] for r in run_dicts(athlete)]
    assert ActivityQuality.objects.get(activity=run).decision == ""


def test_use_cleaned_rederives_and_series_shows_fixes(api, athlete):
    run = recorded_run(athlete, athlete.local_today - dt.timedelta(days=1),
                       stream=locked_stream())
    raw_hr = run.metrics.avg_run_hr
    r = api.patch(f"/api/activities/{run.pk}/quality/", {"use": "cleaned"}, format="json")
    assert r.status_code == 200 and r.json()["quality"]["use"] == "cleaned"
    run.metrics.refresh_from_db()
    assert run.metrics.avg_run_hr != raw_hr          # the lock no longer counts
    assert ActivityRecord.objects.filter(activity=run, heart_rate=165).exists()  # raw kept
    body = api.get(f"/api/activities/{run.pk}/quality/").json()
    assert any(p["fixed"] for p in body["series"])
    series = api.get(f"/api/activities/{run.pk}/series/").json()["points"]
    assert any(p["hr_fixed"] for p in series)
    assert api.patch(f"/api/activities/{run.pk}/quality/", {"use": "bogus"},
                     format="json").status_code == 400


def test_illness_days_flagged_kept_until_excluded(api, athlete):
    from apps.health.compare_views import series_for

    today = athlete.local_today
    for i in range(1, 11):
        wellness(athlete, today - dt.timedelta(days=i), resting_hr=70 if 4 <= i <= 6 else 55)
    ill = Illness.objects.create(athlete=athlete, type="flu", fever=True,
                                 start_date=today - dt.timedelta(days=6),
                                 recovered_on=today - dt.timedelta(days=4),
                                 status="recovered")
    start = today - dt.timedelta(days=10)
    assert len(series_for(athlete, "rhr", start, today)) == 10        # nothing dropped
    flag = api.get(f"/api/health/day/?date={today - dt.timedelta(days=5)}").json()["flagged"]
    assert flag["reason"] == "illness" and flag["decision"] is None

    items = [i for i in api.get("/api/data-review/").json()["items"] if i["kind"] == "illness"]
    assert items[0]["id"] == ill.pk and len(items[0]["days"]) == 3 and items[0]["pending"]

    r = api.post("/api/data-review/decide/", {"items": [
        {"kind": "illness", "id": ill.pk, "decision": "exclude"}]}, format="json")
    assert r.status_code == 200 and r.json()["items"][0]["decision"] == "exclude"
    assert len(series_for(athlete, "rhr", start, today)) == 7
    trends = api.get("/api/health/day/trends/?range=4w").json()
    assert sum(1 for d in trends["flagged_days"] if d["excluded"]) == 3

    api.post("/api/data-review/decide/", {"items": [
        {"kind": "day", "date": str(today - dt.timedelta(days=5)), "decision": None}]},
        format="json")
    assert len(series_for(athlete, "rhr", start, today)) == 8
    assert DayDataDecision.objects.filter(athlete=athlete).count() == 2

    bad = api.post("/api/data-review/decide/", {"items": [
        {"kind": "illness", "id": ill.pk, "decision": None},
        {"kind": "nope"}]}, format="json")
    assert bad.status_code == 400
    assert DayDataDecision.objects.filter(athlete=athlete).count() == 2   # all-or-nothing


# --- (3) illness mode ------------------------------------------------------------------

def _plan_week(athlete):
    today = athlete.local_today
    plan = active_plan(athlete)
    rows = [make_workout(athlete, today + dt.timedelta(days=i), kind="EASY")
            for i in range(0, 9)]
    edited = rows[8]
    edited.steps = [{"kind": "run", "duration_s": 600, "intensity": "easy", "label": "Mine",
                     "hr_min": 120, "hr_max": 140}]
    edited.edited_by = "user"
    edited.save()
    on_watch = rows[1]
    on_watch.garmin_workout_id = 999
    on_watch.save()
    race = PlannedWorkout.objects.create(
        athlete=athlete, plan=plan, date=today + dt.timedelta(days=10), title="Race day",
        kind="RACE", duration_s=3600, load=90, steps=[], status="planned")
    strength = StrengthSession.objects.create(athlete=athlete, plan=plan,
                                              date=today + dt.timedelta(days=2), title="S1",
                                              garmin_workout_id=555)
    return rows, edited, on_watch, race, strength


def test_illness_pauses_plan_and_rest_messaging(api, other_api, athlete, queued):
    rows, edited, on_watch, race, strength = _plan_week(athlete)
    r = api.post("/api/illness/", {"type": "cold"}, format="json")
    assert r.status_code == 201, r.json()
    ill = r.json()
    assert ill["status"] == "active" and ill["paused_workouts"] == 9
    assert ill["symptoms"] == "above_neck" and ill["advice"] and ill["see_doctor"]
    statuses = dict(PlannedWorkout.objects.values_list("pk", "status"))
    assert all(statuses[w.pk] == "paused" for w in rows)
    assert statuses[race.pk] == "planned"                        # races are never paused
    edited.refresh_from_db()
    assert edited.steps[0]["label"] == "Mine"                    # content kept
    strength.refresh_from_db()
    assert strength.status == "paused"
    names = {name for name, _ in queued}
    assert "planning.garmin_push" in names and "planning.garmin_strength_push" in names
    push = next(args for name, args in queued if name == "planning.garmin_push")
    assert push == (athlete.pk, [on_watch.pk], "delete")

    today = api.get("/api/today/").json()
    assert today["verdict"] == "rest" and today["workout"] is None
    assert today["illness"]["id"] == ill["id"]
    assert api.post("/api/illness/", {"type": "flu"}, format="json").status_code == 409
    assert api.patch(f"/api/workouts/{rows[2].pk}/", {"status": "paused"},
                     format="json").status_code == 400
    assert other_api.post(f"/api/illness/{ill['id']}/recover/").status_code == 404
    assert api.get("/api/illness/").json()["active"]["id"] == ill["id"]


def test_recovery_block_is_easier_than_the_plan(api, athlete, queued):
    rows, edited, on_watch, race, strength = _plan_week(athlete)
    from apps.planning.models import Race

    city = Race.objects.create(athlete=athlete, name="City 10K", distance_km=10,
                               date=athlete.local_today + dt.timedelta(days=10))
    ill = api.post("/api/illness/", {"type": "cold", "start_date":
                                     str(athlete.local_today - dt.timedelta(days=2))},
                   format="json").json()
    preview = api.post(f"/api/illness/{ill['id']}/recover/", {"dry_run": True},
                       format="json").json()
    assert preview["return_block"]["rule"] == "short"
    assert Illness.objects.get(pk=ill["id"]).status == "active"   # dry run saved nothing

    body = api.post(f"/api/illness/{ill['id']}/recover/", format="json").json()
    block = body["return_block"]
    assert body["status"] == "recovered" and len(block["sessions"]) == 3
    planned = {w.date: w for w in rows}
    for s in block["sessions"]:
        day = dt.date.fromisoformat(s["date"])
        assert s["duration_s"] <= planned[day].duration_s     # never longer than the plan
        assert s["hr_cap"] <= 145
        made = PlannedWorkout.objects.get(pk=s["workout_id"])
        assert made.illness_return == ill["id"] and made.status == "planned"
    resumes = dt.date.fromisoformat(block["resumes_on"])
    edited.refresh_from_db()
    assert edited.date >= resumes and edited.status == "planned"
    assert edited.steps[0]["label"] == "Mine" and edited.edited_by == "user"
    early = PlannedWorkout.objects.get(pk=rows[1].pk)
    assert early.status == "paused"                              # history stays paused
    assert body["race_warning"]["race_id"] == city.pk
    assert body["race_warning"]["days_after_block"] <= 14
    assert api.post(f"/api/illness/{ill['id']}/recover/").status_code == 409
    history = api.get("/api/illness/history/").json()
    assert history[0]["id"] == ill["id"] and history[0]["days_off"] == 2


def test_cancelled_illness_unpauses(api, athlete, queued):
    rows, *_ = _plan_week(athlete)
    ill = api.post("/api/illness/", {"type": "stomach"}, format="json").json()
    assert api.delete(f"/api/illness/{ill['id']}/").status_code == 204
    assert set(PlannedWorkout.objects.filter(pk__in=[w.pk for w in rows])
               .values_list("status", flat=True)) == {"planned"}


def test_chat_tools_set_and_recover_illness(athlete, queued):
    from apps.coaching.tools import ToolRunner

    make_workout(athlete, athlete.local_today + dt.timedelta(days=1), kind="EASY")
    runner = ToolRunner(athlete)
    started = runner("set_illness", {"type": "cold"})
    assert started["status"] == "started" and started["paused"] == 1
    assert runner.plan_changed
    assert runner("set_illness", {"type": "cold"})["error"]
    done = runner("recover_illness", {})
    assert done["status"] == "recovered"


# --- (4) experiments ×3 ---------------------------------------------------------------

def test_three_experiments_overlap_notes(api):
    ids = []
    for kind in ("no_alcohol", "no_sugar", "steps"):
        r = api.post("/api/experiments/", {"kind": kind}, format="json")
        assert r.status_code == 201, r.json()
        ids.append(r.json()["id"])
    assert api.post("/api/experiments/", {"kind": "bed_by"}, format="json").status_code == 409
    body = api.get("/api/experiments/active/").json()
    assert body["max_active"] == 3 and len(body["active_list"]) == 3
    assert body["experiment"]["id"] == ids[0]
    detail = api.get(f"/api/experiments/{ids[0]}/").json()
    assert {o["id"] for o in detail["overlapping"]} == set(ids[1:])
    assert detail["overlapping"][0]["days"] >= 1
    assert detail["result"]["overlap_note"].startswith("Another experiment ran")


# --- (5) coach memory -----------------------------------------------------------------

def test_memory_crud_groups_pins_and_private_filter(api, other_api, athlete):
    r = api.post("/api/memory/", {"text": "Left knee hurts on long downhills"}, format="json")
    assert r.status_code == 201 and r.json()["category"] == "health"
    fact = r.json()
    assert fact["source"] == "app"
    api.post("/api/memory/", {"text": "Runs before work on weekdays"}, format="json")
    r = api.patch(f"/api/memory/{fact['id']}/", {"pinned": True, "text": "Left knee sore"},
                  format="json")
    assert r.status_code == 200 and r.json()["pinned"] and r.json()["edited"]
    grouped = api.get("/api/memory/?grouped=1").json()
    assert [g["key"] for g in grouped["groups"]] == ["health", "schedule", "goals", "other"]
    assert grouped["count"] == 2 and grouped["pinned"] == 1
    assert api.patch(f"/api/memory/{fact['id']}/", {"text": "Runs before work on weekdays"},
                     format="json").status_code == 400            # duplicate
    assert other_api.patch(f"/api/memory/{fact['id']}/", {"pinned": False},
                           format="json").status_code == 404

    # The private habit is never stored, whatever the route.
    assert api.post("/api/memory/", {"text": "Logs his private habit daily"},
                    format="json").status_code == 400
    assert api.patch(f"/api/memory/{fact['id']}/", {"text": "Doing nofap"},
                     format="json").status_code == 400
    from apps.coaching.tools import ToolRunner, add_fact

    assert ToolRunner(athlete)("add_memory", {"text": "Quit porn last month"}) == {"saved": False}
    assert add_fact(athlete, "private habit count is 3", "checkin") is None
    assert not MemoryFact.objects.filter(text__icontains="private").exists()

    from apps.coaching.chat import system_prompt

    assert "Left knee sore" in system_prompt(athlete)
    assert api.delete(f"/api/memory/{fact['id']}/").status_code == 204


# --- (7) recovery routine -------------------------------------------------------------

def test_recovery_routine_done_and_streak_badge(api, other_api, athlete):
    runs = [recorded_run(athlete, athlete.local_today - dt.timedelta(days=d))
            for d in (3, 2, 1)]
    body = api.get(f"/api/activities/{runs[0].pk}/recovery/").json()
    assert body["available"] and 5 <= body["minutes"] <= 8 and body["steps"]
    assert other_api.get(f"/api/activities/{runs[0].pk}/recovery/").status_code == 404
    first = api.post(f"/api/activities/{runs[0].pk}/recovery/done/", format="json").json()
    again = api.post(f"/api/activities/{runs[0].pk}/recovery/done/", format="json").json()
    # Runs after it have no routine yet, so the current streak is 0 (best 1).
    assert first["done_at"] == again["done_at"] and first["streak"] == {"current": 0, "best": 1}
    api.post(f"/api/activities/{runs[1].pk}/recovery/done/", format="json")
    third = api.post(f"/api/activities/{runs[2].pk}/recovery/done/", format="json").json()
    assert third["streak"] == {"current": 3, "best": 3}
    assert [b["key"] for b in third["new_badges"]] == ["recovery_streak_3"]

    walk = Activity.objects.create(athlete=athlete, source="fit_upload", sport="walking",
                                   started_at=timezone.now(), local_date=athlete.local_today)
    assert api.get(f"/api/activities/{walk.pk}/recovery/").json()["available"] is False
    assert api.post(f"/api/activities/{walk.pk}/recovery/done/").status_code == 409


def test_recovery_today_card(api, athlete):
    run = recorded_run(athlete, athlete.local_today,
                       started_at=timezone.now() - dt.timedelta(hours=1))
    card = api.get("/api/recovery/today/").json()["routine"]
    assert card["activity_id"] == run.pk and card["title"].startswith("Recovery · ")
    RecoveryLog.objects.create(athlete=athlete, activity=run, done_at=timezone.now())
    assert api.get("/api/recovery/today/").json()["routine"] is None


# --- account deletion -----------------------------------------------------------------

def test_account_deletion_removes_r17_rows(api, athlete):
    run = recorded_run(athlete, athlete.local_today - dt.timedelta(days=1), garmin_id=9)
    RecoveryLog.objects.create(athlete=athlete, activity=run, done_at=timezone.now())
    GarminDeletionCheck.objects.create(athlete=athlete, activity=run)
    ActivityTombstone.objects.create(athlete=athlete, garmin_activity_id=10)
    Illness.objects.create(athlete=athlete, type="cold", start_date=athlete.local_today)
    DayDataDecision.objects.create(athlete=athlete, date=athlete.local_today,
                                   decision="exclude")
    assert api.delete("/api/auth/me/", {"password": "correct-horse-battery-1"},
                      format="json").status_code == 204
    for model in (ActivityQuality, RecoveryLog, GarminDeletionCheck, ActivityTombstone,
                  Illness, DayDataDecision):
        assert not model.objects.exists(), model.__name__


def test_r17_isolation(api, other_api, athlete):
    run = recorded_run(athlete, athlete.local_today - dt.timedelta(days=1))
    ill = Illness.objects.create(athlete=athlete, type="cold", start_date=athlete.local_today)
    assert other_api.get(f"/api/activities/{run.pk}/quality/").status_code == 404
    assert other_api.patch(f"/api/activities/{run.pk}/quality/", {"decision": "exclude"},
                           format="json").status_code == 404
    assert other_api.post(f"/api/activities/{run.pk}/recovery/done/").status_code == 404
    assert other_api.patch(f"/api/illness/{ill.pk}/", {"note": "x"},
                           format="json").status_code == 404
    assert other_api.delete(f"/api/illness/{ill.pk}/").status_code == 404
    assert other_api.get("/api/illness/").json() == {"active": None, "history": []}
    assert other_api.get("/api/data-review/").json() == {"pending": 0, "items": []}
    assert other_api.post("/api/data-review/decide/", {"items": [
        {"kind": "illness", "id": ill.pk, "decision": "exclude"}]},
        format="json").status_code == 400
