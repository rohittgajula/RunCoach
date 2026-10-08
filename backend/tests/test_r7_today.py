"""R7 §1: GET /today/, POST /today/apply/, POST /today/explain/."""

import datetime as dt

import pytest

from apps.journal.models import JournalEntry
from apps.planning.models import PlannedWorkout
from tests.r7_helpers import make_workout, wellness

TODAY_KEYS = {"date", "verdict", "headline", "reasons", "signals_missing", "note", "workout",
              "adjusted", "applied", "explanation",
              # R13 §3 / §10
              "injury", "mood",
              # R16 §C
              "as_of", "freshness",
              # R17 §10
              "illness"}
HOURS = 3600


def _pain(athlete, days_ago=1):
    JournalEntry.objects.create(
        athlete=athlete, text="knee hurts", written_on=athlete.local_today,
        applies_to_date=athlete.local_today - dt.timedelta(days=days_ago), pain_reported=True,
    )


@pytest.mark.parametrize("setup,verdict,kind", [
    ({"sleep_seconds": 8 * HOURS, "training_readiness": 80}, "go", None),
    ({"sleep_seconds": 5 * HOURS}, "easy", "RUN_WALK"),
    ({"sleep_seconds": 5 * HOURS, "training_readiness": 10, "body_battery_high": 40},
     "swap", "WALK"),
])
def test_today_shape_for_each_verdict(api, athlete, setup, verdict, kind):
    workout = make_workout(athlete)
    wellness(athlete, **setup)
    body = api.get("/api/today/").json()
    assert set(body) == TODAY_KEYS
    assert body["verdict"] == verdict and body["workout"]["id"] == workout.pk
    assert body["applied"] is False
    assert body["explanation"] == {"status": "none", "text": ""}
    assert (body["adjusted"] or {}).get("kind") == kind
    if body["adjusted"]:
        assert set(body["adjusted"]) == {"title", "kind", "duration_s", "load", "steps",
                                         "target_zone", "description"}


def test_today_rest_on_pain(api, athlete):
    make_workout(athlete)
    wellness(athlete, sleep_seconds=8 * HOURS, training_readiness=90)
    _pain(athlete)
    body = api.get("/api/today/").json()
    assert body["verdict"] == "rest" and body["headline"] == "Rest today"
    assert body["adjusted"]["kind"] == "REST"
    assert body["reasons"][0]["signal"] == "pain"


def test_today_no_plan(api, athlete):
    body = api.get("/api/today/").json()
    assert body["verdict"] == "no_plan" and body["workout"] is None and body["adjusted"] is None
    assert "walk" in body["note"]
    assert "sleep" in body["signals_missing"]


def test_skipped_workout_counts_as_no_plan(api, athlete):
    make_workout(athlete, status="skipped")
    assert api.get("/api/today/").json()["verdict"] == "no_plan"


def test_apply_stores_original_and_is_idempotent(api, athlete):
    workout = make_workout(athlete)
    original_steps = list(workout.steps)
    wellness(athlete, sleep_seconds=5 * HOURS)
    first = api.post("/api/today/apply/")
    assert first.status_code == 200 and first.json()["applied"] is True
    workout.refresh_from_db()
    assert workout.adjusted_by == "checkin" and workout.status == "planned"
    assert workout.original_steps == original_steps
    assert workout.original["title"] == "23m run/walk"
    run_caps = [s["hr_max"] for s in workout.steps if s["kind"] == "run"]
    assert run_caps == [140, 140, 140]

    # Again: no second easing (the check-in always judges the original).
    api.post("/api/today/apply/")
    workout.refresh_from_db()
    assert [s["hr_max"] for s in workout.steps if s["kind"] == "run"] == [140, 140, 140]
    assert workout.original_steps == original_steps
    body = api.get("/api/today/").json()
    assert body["applied"] is True and body["verdict"] == "easy"
    assert body["workout"]["adjusted_by"] == "checkin"
    assert body["workout"]["original_steps"] == original_steps

    # Things get worse later in the day: re-applying starts from the original.
    wellness(athlete, sleep_seconds=5 * HOURS, training_readiness=10, body_battery_high=40)
    api.post("/api/today/apply/")
    workout.refresh_from_db()
    assert workout.kind == "WALK" and workout.original_steps == original_steps


def test_apply_with_nothing_to_change_is_409(api, athlete):
    make_workout(athlete)
    wellness(athlete, sleep_seconds=8 * HOURS)
    assert api.post("/api/today/apply/").status_code == 409
    PlannedWorkout.objects.all().delete()
    assert api.post("/api/today/apply/").status_code == 409


def _fake_ai(monkeypatch, calls):
    from apps.coaching import services
    from apps.coaching.schemas import CheckinExplanation

    def fake_complete(*, operation, schema, **kwargs):
        calls.append(operation)
        return CheckinExplanation(text="Short sleep, so keep it easy."), {
            "model": "test-model", "input_tokens": 1, "output_tokens": 1, "latency_ms": 1,
            "retry_count": 0, "estimated_cost_usd": 0.0}

    monkeypatch.setattr(services, "complete", fake_complete)
    monkeypatch.setattr(services, "model_for", lambda op: "test-model")


def test_explain_is_cached_per_day(api, athlete, monkeypatch):
    make_workout(athlete)
    wellness(athlete, sleep_seconds=5 * HOURS)
    calls = []
    _fake_ai(monkeypatch, calls)
    r = api.post("/api/today/explain/")
    assert r.status_code == 200
    assert r.json()["explanation"] == {"status": "ready", "text": "Short sleep, so keep it easy."}
    api.post("/api/today/explain/")
    assert calls == ["checkin_explain"]
    assert api.get("/api/today/").json()["explanation"]["status"] == "ready"
    # Applying the change does not invalidate today's explanation.
    api.post("/api/today/apply/")
    assert api.get("/api/today/").json()["explanation"]["status"] == "ready"


def test_explain_503_when_ai_unavailable(api, athlete, monkeypatch):
    from apps.coaching import services
    from apps.coaching.client import AIUnavailable

    def boom(**kwargs):
        raise AIUnavailable("down")

    monkeypatch.setattr(services, "complete", boom)
    monkeypatch.setattr(services, "model_for", lambda op: "test-model")
    r = api.post("/api/today/explain/")
    assert r.status_code == 503 and r.json()["detail"]


def test_explain_respects_budget(api, athlete, monkeypatch):
    from apps.coaching import services
    from apps.coaching.models import AIRequestLog

    calls = []
    _fake_ai(monkeypatch, calls)
    monkeypatch.setattr(services, "MONTHLY_CALL_BUDGET", 0)
    r = api.post("/api/today/explain/")
    assert r.status_code == 503 and calls == []
    assert AIRequestLog.objects.filter(athlete=athlete, status="refused").exists()


def test_today_is_tenant_isolated(api, other_api, athlete, other_athlete):
    workout = make_workout(athlete)
    wellness(athlete, sleep_seconds=5 * HOURS)
    _pain(athlete)
    assert other_api.get("/api/today/").json()["verdict"] == "no_plan"
    assert other_api.post("/api/today/apply/").status_code == 409
    workout.refresh_from_db()
    assert workout.adjusted_by == ""
    assert api.get("/api/today/").json()["verdict"] == "rest"


def test_rpe_yesterday_feeds_the_checkin(api, athlete):
    make_workout(athlete)
    wellness(athlete, sleep_seconds=6.5 * HOURS)          # one watch
    JournalEntry.objects.create(
        athlete=athlete, text="hard", written_on=athlete.local_today, source="run_log",
        applies_to_date=athlete.local_today - dt.timedelta(days=1), rpe=9,
    )
    body = api.get("/api/today/").json()
    assert any(r["signal"] == "rpe" and r["status"] == "watch" for r in body["reasons"])
    assert body["verdict"] == "easy"


def test_today_requires_auth(client, db):
    assert client.get("/api/today/").status_code == 401


def test_morning_task_queues_wellness_then_checkin_and_never_applies(athlete, monkeypatch):
    from apps.ingest import tasks as ingest_tasks
    from apps.planning import tasks

    workout = make_workout(athlete)
    wellness(athlete, sleep_seconds=5 * HOURS)
    queued = []
    monkeypatch.setattr(tasks, "MORNING_HOUR", athlete.local_now.hour)
    monkeypatch.setattr(tasks.compute_checkin, "delay", lambda pk: queued.append(("compute", pk)))
    monkeypatch.setattr(ingest_tasks.sync_wellness_one, "apply_async",
                        lambda args, link=None: queued.append(("wellness", args[0])))
    assert tasks.morning_checkins() == {"queued": 1}
    assert queued == [("compute", athlete.pk)]           # not Garmin-connected
    athlete.garmin_connected = True
    athlete.save()
    tasks.morning_checkins()
    assert queued[-1] == ("wellness", athlete.pk)

    result = tasks.compute_checkin.run(athlete.pk)
    assert result["verdict"] == "easy" and result["workout_id"] == workout.pk
    workout.refresh_from_db()
    assert workout.adjusted_by == ""


def test_morning_wellness_respects_the_breaker(athlete, monkeypatch):
    from apps.ingest import tasks as ingest_tasks

    athlete.garmin_connected = True
    athlete.save()
    monkeypatch.setattr(ingest_tasks, "garmin_blocked", lambda: True)
    assert ingest_tasks.sync_wellness_one.run(athlete.pk) == {"skipped": "rate_limited"}


def test_daytime_signals_fall_back_one_day_but_sleep_and_hrv_do_not(athlete):
    """In the morning today's Garmin row is often only partly filled. Resting HR and
    body battery from yesterday still describe today; a night without the watch must
    stay missing rather than borrow older sleep/HRV."""
    from apps.planning.plan_services import snapshot_for

    today = athlete.local_today
    wellness(athlete, today - dt.timedelta(days=2), sleep_seconds=7 * 3600, hrv_overnight_avg=50,
             resting_hr=55, body_battery_high=80)
    wellness(athlete, today - dt.timedelta(days=1), resting_hr=58, body_battery_high=70)
    wellness(athlete, today, training_readiness=60)

    snap = snapshot_for(athlete, today)
    assert snap.resting_hr == 58 and snap.body_battery_high == 70
    assert snap.sleep_hours is None and snap.hrv is None
    assert snap.readiness == 60
