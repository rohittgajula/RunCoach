"""R7 §2: post-run check-in, pending list, skip, and RPE in compliance."""

import datetime as dt

import pytest

from analysis.compliance import evaluate
from apps.journal.models import JournalEntry
from tests.r6_helpers import make_activity
from tests.r7_helpers import make_workout

CHECKIN = {"rpe": 6, "legs": "heavy", "breathing": "ok",
           "pain": {"where": "knee", "level": 3}, "note": ""}


@pytest.fixture
def no_ai(monkeypatch):
    """Any model call fails the test."""
    from apps.coaching import client, services

    def boom(**kwargs):
        raise AssertionError("the structured check-in must not call the model")

    monkeypatch.setattr(services, "complete", boom)
    monkeypatch.setattr(client, "complete", boom)


def test_checkin_creates_entry_without_ai_and_marks_journalled(api, athlete, no_ai):
    activity = make_activity(athlete, athlete.local_today)
    r = api.post(f"/api/activities/{activity.pk}/checkin/", CHECKIN, format="json")
    assert r.status_code == 201
    body = r.json()
    assert body["source"] == "run_log" and body["rpe"] == 6 and body["pain_reported"] is True
    assert body["activity"] == activity.pk
    assert body["extracted"]["legs"] == "heavy" and body["extracted"]["pain"]["where"] == "knee"
    entry = JournalEntry.objects.get(pk=body["id"])
    assert entry.applies_to_date == activity.local_date
    card = api.get(f"/api/activities/{activity.pk}/").json()
    assert card["journalled"] is True and card["checkin"]["id"] == entry.pk


def test_checkin_again_replaces_not_duplicates(api, athlete, no_ai):
    activity = make_activity(athlete, athlete.local_today)
    api.post(f"/api/activities/{activity.pk}/checkin/", CHECKIN, format="json")
    r = api.post(f"/api/activities/{activity.pk}/checkin/",
                 {"rpe": 3, "pain": None}, format="json")
    assert r.status_code == 200 and r.json()["rpe"] == 3 and r.json()["pain_reported"] is False
    assert JournalEntry.objects.filter(athlete=athlete, activity=activity).count() == 1


@pytest.mark.parametrize("payload", [
    {}, {"rpe": 0}, {"rpe": 11}, {"rpe": 5.5}, {"rpe": 5, "legs": "wobbly"},
    {"rpe": 5, "breathing": "gasping"}, {"rpe": 5, "pain": {"level": 3}},
    {"rpe": 5, "pain": {"where": "knee", "level": 12}}, {"rpe": 5, "pain": "knee"},
])
def test_checkin_validation(api, athlete, payload):
    activity = make_activity(athlete, athlete.local_today)
    r = api.post(f"/api/activities/{activity.pk}/checkin/", payload, format="json")
    assert r.status_code == 400 and r.json()["detail"]


def test_note_is_queued_for_extraction_not_called(api, athlete, no_ai, monkeypatch,
                                                  django_capture_on_commit_callbacks):
    from apps.coaching import tasks

    queued = []
    monkeypatch.setattr(tasks.extract_checkin_note, "delay", lambda pk: queued.append(pk))
    activity = make_activity(athlete, athlete.local_today)
    with django_capture_on_commit_callbacks(execute=True):
        r = api.post(f"/api/activities/{activity.pk}/checkin/",
                     {**CHECKIN, "pain": None, "note": "calf felt tight at the end"},
                     format="json")
    assert queued == [r.json()["id"]]


def test_note_extraction_can_add_pain_but_never_clear_rpe(athlete, monkeypatch):
    from apps.coaching import tasks
    from apps.coaching.schemas import JournalFacts

    activity = make_activity(athlete, athlete.local_today)
    entry = JournalEntry.objects.create(
        athlete=athlete, activity=activity, source="run_log", text="x", rpe=4,
        written_on=athlete.local_today, applies_to_date=athlete.local_today,
        extracted={"checkin": True, "rpe": 4, "note": "calf tight"},
    )
    facts = JournalFacts(rpe=8, energy=None, leg_fatigue=None, sleep_quality=None,
                         pain_reported=True, pain_location="calf", pain_severity=2,
                         illness_reported=False, notes_summary="calf", confidence=0.9)
    monkeypatch.setattr("apps.coaching.services.extract_journal",
                        lambda *a, **k: (facts, False))
    tasks.extract_checkin_note.run(entry.pk)
    entry.refresh_from_db()
    assert entry.pain_reported is True and entry.rpe == 4
    assert entry.extracted["note_facts"]["pain_location"] == "calf"


def test_pending_lists_unjournalled_runs_and_walks_of_last_7_days(api, athlete):
    today = athlete.local_today
    run = make_activity(athlete, today)
    walk = make_activity(athlete, today - dt.timedelta(days=1), sport="walking")
    make_activity(athlete, today - dt.timedelta(days=2), sport="cycling")
    make_activity(athlete, today - dt.timedelta(days=8))                 # too old
    done = make_activity(athlete, today - dt.timedelta(days=3))
    JournalEntry.objects.create(athlete=athlete, activity=done, source="run_log", text="x",
                                written_on=today, applies_to_date=done.local_date, rpe=4)
    workout = make_workout(athlete, today)
    workout.status, workout.completed_activity = "completed", run
    workout.save()

    body = api.get("/api/checkins/pending/").json()
    assert [item["activity"]["id"] for item in body] == [run.pk, walk.pk]
    assert body[0]["workout_id"] == workout.pk and body[1]["workout_id"] is None
    assert body[0]["activity"]["journalled"] is False


def test_checkin_for_one_run_does_not_cover_a_second_run_that_day(api, athlete, no_ai):
    first = make_activity(athlete, athlete.local_today)
    second = make_activity(athlete, athlete.local_today)
    api.post(f"/api/activities/{first.pk}/checkin/", {"rpe": 4}, format="json")
    assert [i["activity"]["id"] for i in api.get("/api/checkins/pending/").json()] == [second.pk]


def test_skip_clears_pending_and_is_idempotent(api, athlete):
    activity = make_activity(athlete, athlete.local_today)
    r = api.post(f"/api/activities/{activity.pk}/checkin/skip/", {"reason": "busy"},
                 format="json")
    assert r.status_code == 201 and r.json()["extracted"]["skipped"] is True
    assert r.json()["rpe"] is None and r.json()["pain_reported"] is False
    again = api.post(f"/api/activities/{activity.pk}/checkin/skip/", {}, format="json")
    assert again.status_code == 200 and again.json()["id"] == r.json()["id"]
    assert api.get("/api/checkins/pending/").json() == []


def test_easy_session_that_felt_hard_misses_effort():
    planned = {"kind": "RUN_WALK", "duration_s": 1800, "target_zone": "Z2", "steps": []}
    base = {"duration_s": 1800, "run_duration_s": 0, "longest_run_s": 0,
            "time_in_zone": None, "run_blocks": []}

    def effort(rpe):
        checks = {c["key"]: c for c in evaluate(planned, {**base, "rpe": rpe})["checks"]}
        return checks.get("effort")

    assert effort(7)["status"] == "missed"
    assert effort(7)["note"] == "Felt harder than an easy run should."
    assert effort(6)["status"] == "close" and effort(5)["status"] == "hit"
    assert effort(None) is None
    hard = {**planned, "kind": "INTERVALS"}
    assert "effort" not in {c["key"] for c in evaluate(hard, {**base, "rpe": 9})["checks"]}


def test_checkin_rpe_reaches_workout_compliance(api, athlete, no_ai):
    activity = make_activity(athlete, athlete.local_today)
    workout = make_workout(athlete)
    workout.status, workout.completed_activity = "completed", activity
    workout.save()
    api.post(f"/api/activities/{activity.pk}/checkin/", {"rpe": 8}, format="json")
    checks = {c["key"]: c for c in api.get(f"/api/workouts/{workout.pk}/").json()
              ["compliance"]["checks"]}
    assert checks["effort"]["status"] == "missed"


def test_postrun_endpoints_are_tenant_isolated(api, other_api, athlete):
    activity = make_activity(athlete, athlete.local_today)
    assert other_api.post(f"/api/activities/{activity.pk}/checkin/", {"rpe": 5},
                          format="json").status_code == 404
    assert other_api.post(f"/api/activities/{activity.pk}/checkin/skip/", {},
                          format="json").status_code == 404
    assert other_api.get("/api/checkins/pending/").json() == []
    assert not JournalEntry.objects.exists()
    assert len(api.get("/api/checkins/pending/").json()) == 1
