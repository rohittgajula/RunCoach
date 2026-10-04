"""R7 §3: send to Garmin — always against a fake client, never the real one."""

import datetime as dt

import pytest

from apps.planning.models import PlannedWorkout
from tests.r6_helpers import make_activity
from tests.r7_helpers import make_workout, tomorrow


class FakeGarmin:
    def __init__(self, fail_upload=None, rate_limit_after=None):
        self.calls = []
        self.next_id = 1000
        self.fail_upload = fail_upload
        self.rate_limit_after = rate_limit_after
        self.uploads = 0

    def upload_running_workout(self, workout):
        from garminconnect.workout import RunningWorkout

        assert isinstance(workout, RunningWorkout)
        self.uploads += 1
        if self.rate_limit_after is not None and self.uploads > self.rate_limit_after:
            raise Exception("429 Too Many Requests")
        if self.fail_upload:
            raise Exception(self.fail_upload)
        self.next_id += 1
        self.calls.append(("upload", workout.to_dict()))
        return {"workoutId": self.next_id}

    def schedule_workout(self, workout_id, date_str):
        self.calls.append(("schedule", workout_id, date_str))
        return {"workoutScheduleId": workout_id + 50000}

    def unschedule_workout(self, schedule_id):
        self.calls.append(("unschedule", schedule_id))

    def delete_workout(self, workout_id):
        self.calls.append(("delete", workout_id))

    def kinds(self):
        return [c[0] for c in self.calls]


@pytest.fixture
def fake(monkeypatch, settings):
    """Eager queue, a fake client, and a breaker that never touches the shared Redis."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    client = FakeGarmin()
    tripped = []
    monkeypatch.setattr("apps.planning.garmin_push._client", lambda athlete: client)
    monkeypatch.setattr("apps.ingest.tasks.garmin_blocked", lambda: False)
    monkeypatch.setattr("apps.ingest.tasks.trip_breaker", lambda reason: tripped.append(reason))
    client.tripped = tripped
    return client


def test_send_uploads_schedules_and_stores_ids(api, athlete, fake):
    workout = make_workout(athlete, tomorrow(athlete))
    r = api.post(f"/api/workouts/{workout.pk}/garmin/")
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["garmin_result"]["status"] == "uploaded"
    assert body["garmin_workout_id"] == 1001 and body["garmin_synced_at"]
    assert body["garmin_status"] == "synced"
    assert fake.kinds() == ["upload", "schedule"]
    assert fake.calls[1] == ("schedule", 1001, workout.date.isoformat())
    workout.refresh_from_db()
    assert workout.garmin_schedule_id == 51001 and workout.garmin_payload_hash


def test_send_unchanged_is_a_noop(api, athlete, fake):
    workout = make_workout(athlete, tomorrow(athlete))
    api.post(f"/api/workouts/{workout.pk}/garmin/")
    r = api.post(f"/api/workouts/{workout.pk}/garmin/")
    assert r.json()["garmin_result"]["status"] == "unchanged"
    assert fake.kinds() == ["upload", "schedule"]


def test_send_changed_deletes_and_reuploads(api, athlete, fake):
    workout = make_workout(athlete, tomorrow(athlete))
    api.post(f"/api/workouts/{workout.pk}/garmin/")
    steps = workout.steps
    steps[1]["hr_max"] = 140
    PlannedWorkout.objects.filter(pk=workout.pk).update(steps=steps)
    assert api.get(f"/api/workouts/{workout.pk}/").json()["garmin_status"] == "changed"
    r = api.post(f"/api/workouts/{workout.pk}/garmin/")
    assert r.json()["garmin_result"]["status"] == "updated"
    assert fake.kinds() == ["upload", "schedule", "unschedule", "delete", "upload", "schedule"]
    assert fake.calls[3] == ("delete", 1001)
    assert r.json()["garmin_workout_id"] == 1002 and r.json()["garmin_status"] == "synced"


def test_moving_a_workout_counts_as_changed(api, athlete, fake):
    workout = make_workout(athlete, tomorrow(athlete))
    api.post(f"/api/workouts/{workout.pk}/garmin/")
    api.patch(f"/api/workouts/{workout.pk}/", {"date": tomorrow(athlete, 2).isoformat()},
              format="json")
    r = api.post(f"/api/workouts/{workout.pk}/garmin/")
    assert r.json()["garmin_result"]["status"] == "updated"
    assert fake.calls[-1] == ("schedule", 1002, tomorrow(athlete, 2).isoformat())


def test_delete_unschedules_and_deletes(api, athlete, fake):
    workout = make_workout(athlete, tomorrow(athlete))
    api.post(f"/api/workouts/{workout.pk}/garmin/")
    r = api.delete(f"/api/workouts/{workout.pk}/garmin/")
    assert r.status_code == 200 and r.json()["garmin_result"]["status"] == "removed"
    assert r.json()["garmin_workout_id"] is None and r.json()["garmin_status"] == "none"
    assert fake.kinds()[-2:] == ["unschedule", "delete"]


def test_past_or_completed_workouts_are_not_sent(api, athlete, fake):
    past = make_workout(athlete, athlete.local_today - dt.timedelta(days=1))
    r = api.post(f"/api/workouts/{past.pk}/garmin/")
    assert r.status_code == 409 and "past" in r.json()["detail"]
    done = make_workout(athlete, tomorrow(athlete))
    done.status, done.completed_activity = "completed", make_activity(athlete, athlete.local_today)
    done.save()
    assert api.post(f"/api/workouts/{done.pk}/garmin/").status_code == 409
    assert fake.calls == []


def test_garmin_error_is_502_with_detail(api, athlete, fake):
    fake.fail_upload = "500 Server Error"
    workout = make_workout(athlete, tomorrow(athlete))
    r = api.post(f"/api/workouts/{workout.pk}/garmin/")
    assert r.status_code == 502 and "500" in r.json()["detail"]
    workout.refresh_from_db()
    assert workout.garmin_workout_id is None


def test_breaker_open_is_503(api, athlete, fake, monkeypatch):
    monkeypatch.setattr("apps.ingest.tasks.garmin_blocked", lambda: True)
    workout = make_workout(athlete, tomorrow(athlete))
    r = api.post(f"/api/workouts/{workout.pk}/garmin/")
    assert r.status_code == 503 and r.json()["detail"]
    assert fake.calls == []


def test_week_send_returns_per_workout_results(api, athlete, fake):
    first = make_workout(athlete, athlete.local_today)
    second = make_workout(athlete, tomorrow(athlete, 2))
    make_workout(athlete, tomorrow(athlete, 9))                       # outside 7 days
    r = api.post("/api/plans/active/garmin/", {"days": 7}, format="json")
    assert r.status_code == 200
    results = r.json()["results"]
    assert [(x["workout_id"], x["status"]) for x in results] == [
        (first.pk, "uploaded"), (second.pk, "uploaded")]
    again = api.post("/api/plans/active/garmin/", {}, format="json").json()["results"]
    assert {x["status"] for x in again} == {"unchanged"}


def test_week_send_rate_limit_stops_and_reports_each_workout(api, athlete, fake):
    fake.rate_limit_after = 1
    ids = [make_workout(athlete, tomorrow(athlete, d)).pk for d in (1, 2, 3)]
    r = api.post("/api/plans/active/garmin/", {"days": 7}, format="json")
    assert r.status_code == 502
    statuses = [(x["workout_id"], x["status"]) for x in r.json()["results"]]
    assert statuses == [(ids[0], "uploaded"), (ids[1], "error"), (ids[2], "error")]
    assert fake.tripped and fake.uploads == 2


def test_week_send_validation_and_no_plan(api, athlete, fake):
    assert api.post("/api/plans/active/garmin/", {"days": 0}, format="json").status_code == 400
    assert api.post("/api/plans/active/garmin/", {"days": "x"}, format="json").status_code == 400
    assert api.post("/api/plans/active/garmin/", {}, format="json").status_code == 404


def test_garmin_endpoints_are_tenant_isolated(api, other_api, athlete, fake):
    workout = make_workout(athlete, tomorrow(athlete))
    assert other_api.post(f"/api/workouts/{workout.pk}/garmin/").status_code == 404
    assert other_api.delete(f"/api/workouts/{workout.pk}/garmin/").status_code == 404
    assert other_api.post("/api/plans/active/garmin/", {}, format="json").status_code == 404
    assert fake.calls == []


def test_guard_and_time_above_cap_on_workout_json(api, athlete):
    from apps.activities.models import ActivityRecord

    activity = make_activity(athlete, athlete.local_today)
    for second in range(0, 600, 5):
        ActivityRecord.objects.create(activity=activity, offset_s=second,
                                      heart_rate=160 if second < 120 else 140)
    workout = make_workout(athlete)
    workout.status, workout.completed_activity = "completed", activity
    workout.save()
    body = api.get(f"/api/workouts/{workout.pk}/").json()
    assert body["guard"] == {"hr_max": athlete.hr_ceiling, "pace_min_s": 600,
                             "pace_max_s": 645, "cadence_target": 160}
    actual = body["actual"]
    assert actual["hr_cap"] == 155
    assert actual["time_above_cap_s"] == 120 and actual["time_above_cap_pct"] == 20
    intervals = make_workout(athlete, tomorrow(athlete), kind="INTERVALS")
    assert api.get(f"/api/workouts/{intervals.pk}/").json()["guard"] is None


def test_replacing_a_plan_removes_its_workouts_from_garmin(athlete, monkeypatch, django_capture_on_commit_callbacks):
    """Rebuilding used to leave the old plan's uploaded workouts on the watch, so the
    same day showed up three times."""
    from apps.planning import garmin_push
    from apps.planning.models import PlannedWorkout, TrainingPlan
    from apps.planning.plan_store import accept_plan, propose_plan
    import datetime as dt

    race_day = athlete.local_today + dt.timedelta(weeks=10)
    first = accept_plan(propose_plan(athlete, race_name="R", race_date=race_day, distance_km=10))
    sent = PlannedWorkout.objects.filter(plan=first, date__gt=athlete.local_today).first()
    sent.garmin_workout_id, sent.garmin_schedule_id = 111, 222
    sent.save()

    calls = []
    class Fake:
        def unschedule_workout(self, sid): calls.append(("unschedule", sid))
        def delete_workout(self, wid): calls.append(("delete", wid))
    monkeypatch.setattr(garmin_push, "_client", lambda a: Fake())
    from apps.planning import tasks
    monkeypatch.setattr(tasks.garmin_forget_task, "delay",
                        lambda *args: tasks.garmin_forget_task.run(*args))

    with django_capture_on_commit_callbacks(execute=True):
        accept_plan(propose_plan(athlete, race_name="R", race_date=race_day, distance_km=10))

    assert ("unschedule", 222) in calls and ("delete", 111) in calls
    assert not PlannedWorkout.objects.filter(pk=sent.pk).exists()
