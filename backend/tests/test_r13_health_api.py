"""R13 §3 injury watch + pain, §6 briefing, §7 run review, §10 mood, §11 monthly report,
compare catalogue and reminders — API shapes, validation and tenant isolation."""

import datetime as dt

import pytest

from apps.activities.models import RunReview
from apps.health.models import MonthlyReport, MoodLog, MorningBriefing, PainReport
from tests.r10_helpers import night, run


def day(athlete, offset):
    return athlete.local_today + dt.timedelta(days=offset)


@pytest.fixture
def no_ai(monkeypatch):
    from apps.coaching import client

    def unavailable(**kwargs):
        raise client.AIUnavailable("No model in tests.")

    monkeypatch.setattr("apps.coaching.services.complete", unavailable)


@pytest.fixture
def fake_ai(monkeypatch):
    from apps.coaching.schemas import ShortParagraph

    calls = []

    def complete(*, operation, system, user, schema):
        calls.append((operation, user))
        return ShortParagraph(markdown="A short paragraph."), {
            "model": "test-model", "input_tokens": 1, "output_tokens": 1, "latency_ms": 1,
            "estimated_cost_usd": 0.0, "retry_count": 0}

    monkeypatch.setattr("apps.coaching.services.complete", complete)
    return calls


# --- §3 -----------------------------------------------------------------------------

def test_pain_crud_validation_and_isolation(api, other_api, athlete, other_athlete):
    r = api.post("/api/health/pain/", {"location": "knee", "side": "left", "severity": 2},
                 format="json")
    assert r.status_code == 201
    body = r.json()
    assert set(body) == {"id", "date", "location", "side", "severity", "activity_id", "note",
                         "created_at"}
    again = api.post("/api/health/pain/", {"location": "knee", "side": "left", "severity": 3},
                     format="json")
    assert again.status_code == 200 and again.json()["id"] == body["id"]
    for bad in ({"location": "elbow", "side": "left", "severity": 2},
                {"location": "knee", "side": "up", "severity": 2},
                {"location": "knee", "side": "left", "severity": 4},
                {"location": "knee", "side": "left", "severity": "2.5"},
                {"location": "knee", "side": "left", "severity": 1, "date": "2020-01-01"},
                {"location": "knee", "side": "left", "severity": 1, "activity_id": 999999}):
        assert api.post("/api/health/pain/", bad, format="json").status_code == 400, bad
    other_activity = run(other_athlete, day(athlete, 0))
    assert api.post("/api/health/pain/", {"location": "hip", "side": "left", "severity": 1,
                                          "activity_id": other_activity.pk},
                    format="json").status_code == 400
    assert [p["id"] for p in api.get("/api/health/pain/").json()] == [body["id"]]
    assert other_api.get("/api/health/pain/").json() == []
    assert other_api.delete(f"/api/health/pain/{body['id']}/").status_code == 404
    assert api.delete(f"/api/health/pain/{body['id']}/").status_code == 204
    assert api.get("/api/health/pain/?days=0").status_code == 400


def test_pain_report_queues_auto_adjust(api, athlete, no_real_r13_queue,
                                        django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        api.post("/api/health/pain/", {"location": "calf", "side": "right", "severity": 2},
                 format="json")
    assert ("after_pain_task", (athlete.pk,), {}) in no_real_r13_queue


def test_injury_endpoint(api, other_api, athlete):
    body = api.get("/api/health/injury/").json()
    assert body["risk"] == "low" and body["flags"] == [] and body["pains"] == []
    assert set(body) == {"date", "risk", "flags", "pains", "guidance", "note"}
    for offset in (0, -1):
        PainReport.objects.create(athlete=athlete, date=day(athlete, offset), location="hip",
                                  side="left", severity=3)
    body = api.get("/api/health/injury/").json()
    assert body["risk"] == "high" and body["flags"][0]["kind"] == "pain"
    assert set(body["flags"][0]) == {"kind", "level", "text", "since", "value"}
    assert any("physio" in g for g in body["guidance"])
    assert other_api.get("/api/health/injury/").json()["risk"] == "low"


def test_injury_shoe_and_cadence_flags(api, athlete):
    from apps.gear.models import Shoe

    Shoe.objects.create(athlete=athlete, name="Old pair", source="local", is_default=True,
                        start_km=750, retire_km=700)
    for offset in (-26, -22, -18, -14):
        run(athlete, day(athlete, offset), cadence=168)
    for offset in (-5, -3, -1):
        run(athlete, day(athlete, offset), cadence=158)
    kinds = {f["kind"] for f in api.get("/api/health/injury/").json()["flags"]}
    assert {"shoe", "cadence_drop"} <= kinds


# --- §6 -----------------------------------------------------------------------------

def test_briefing_builds_after_4am(api, other_api, athlete, monkeypatch):
    monkeypatch.setattr("apps.health.briefing.ready", lambda a: False)
    body = api.get("/api/briefing/today/").json()
    assert body["ready"] is False and body["session"] is None
    monkeypatch.setattr("apps.health.briefing.ready", lambda a: True)
    night(athlete, athlete.local_today, hours=5.0, need_h=8.0, training_readiness=40)
    body = api.get("/api/briefing/today/").json()
    assert set(body) == {"date", "ready", "built_at", "dismissed", "wake_time", "greeting",
                         "readiness", "checkin", "session", "weather", "fuel", "focus",
                         "notes", "ai"}
    assert body["ready"] and body["greeting"] == "Good morning, Tester"
    assert body["readiness"]["score"] == 40 and body["focus"]["key"] == "sleep"
    assert any(n["kind"] == "sleep" for n in body["notes"])
    assert body["fuel"]["kcal"] > 0 and body["weather"] is None
    assert api.post("/api/briefing/today/dismiss/").json() == {"dismissed": True}
    assert api.get("/api/briefing/today/").json()["dismissed"] is True
    assert MorningBriefing.objects.filter(athlete=athlete).count() == 1
    assert other_api.get("/api/briefing/today/").json()["dismissed"] is False


def test_briefing_ai_aggregates_only(api, athlete, monkeypatch, fake_ai):
    from apps.health.models import PainReport

    monkeypatch.setattr("apps.health.briefing.ready", lambda a: True)
    for offset in (0, -1):
        PainReport.objects.create(athlete=athlete, date=day(athlete, offset), location="knee",
                                  side="left", severity=2)
    MoodLog.objects.create(athlete=athlete, date=athlete.local_today, mood=1, energy=1,
                           note="secret note")
    r = api.post("/api/briefing/today/ai/")
    assert r.status_code == 200 and r.json()["status"] == "ready"
    _, prompt = fake_ai[0]
    assert "knee" not in prompt.lower() and "secret" not in prompt and "mood" not in prompt
    assert api.get("/api/briefing/today/").json()["ai"]["text"] == "A short paragraph."


def test_briefing_ai_503_without_model(api, athlete, monkeypatch, no_ai):
    monkeypatch.setattr("apps.health.briefing.ready", lambda a: True)
    assert api.post("/api/briefing/today/ai/").status_code == 503


def test_briefing_beat_and_push(athlete, monkeypatch, settings):
    from apps.health import tasks
    from apps.reminders.service import due, message, settings_for

    monkeypatch.setattr("apps.health.briefing.due_now", lambda a: True)
    assert tasks.morning_briefings.run()["built"] == 1
    assert tasks.morning_briefings.run()["built"] == 0          # once a day
    row = settings_for(athlete)
    row.morning_briefing = True
    row.save()
    body = message(athlete, "morning_briefing")
    assert body == {"title": "Good morning", "body": "Your morning briefing is ready.",
                    "url": "/", "tag": "briefing"}
    assert due(row, "run_summary", athlete.local_now) is False


# --- §7 -----------------------------------------------------------------------------

def test_review_endpoint_and_recent(api, other_api, athlete):
    from apps.activities.reviews import build_review

    for offset in (-20, -10, -5):
        run(athlete, day(athlete, offset), pace=420, hr=145)
    activity = run(athlete, day(athlete, 0), pace=400, hr=141)
    body = api.get(f"/api/activities/{activity.pk}/review/").json()
    assert body["available"] is True and body["compared_with"] == 3
    assert body["created_at"] is None and body["ai"]["status"] == "none"
    assert set(body) == {"activity_id", "date", "available", "reason", "kind", "bucket",
                         "compared_with", "metrics", "went_well", "to_improve", "next_time",
                         "ai", "created_at"}
    assert {m["key"] for m in body["metrics"]} == {"pace", "hr_at_pace", "hr_drift", "cadence",
                                                   "run_fraction"}
    assert api.get("/api/reviews/recent/").json() == {"review": None}
    build_review(activity)
    recent = api.get("/api/reviews/recent/").json()["review"]
    assert recent["activity_id"] == activity.pk
    assert other_api.get(f"/api/activities/{activity.pk}/review/").status_code == 404
    assert other_api.get("/api/reviews/recent/").json() == {"review": None}
    # POST on the same path still opens a chat thread (R6).
    assert api.post(f"/api/activities/{activity.pk}/review/").status_code == 201


def test_review_not_a_run_and_ai(api, athlete, fake_ai):
    activity = run(athlete, day(athlete, 0))
    activity.sport = "strength_training"
    activity.save()
    assert api.get(f"/api/activities/{activity.pk}/review/").json()["reason"] == "not_a_run"
    assert api.post(f"/api/activities/{activity.pk}/review/ai/").status_code == 503
    runner = run(athlete, day(athlete, 0))
    r = api.post(f"/api/activities/{runner.pk}/review/ai/")
    assert r.status_code == 200 and r.json()["markdown"] == "A short paragraph."
    assert RunReview.objects.get(activity=runner).ai_markdown == "A short paragraph."
    assert fake_ai[0][0] == "run_review"


def test_review_push_only_when_enabled(athlete, monkeypatch, settings):
    """R15: the R13 "Run reviewed" push is now the run summary (on by default)."""
    from apps.activities import reviews
    from apps.reminders.service import settings_for

    sent = []
    monkeypatch.setattr("apps.reminders.push.available", lambda: True)
    monkeypatch.setattr("apps.reminders.push.send_to_athlete",
                        lambda a, body: (sent.append(body) or 1, 0))
    monkeypatch.setattr("apps.activities.run_summary.quiet_until", lambda row, now: None)
    row = settings_for(athlete)
    row.run_summary = False
    row.save()
    reviews.build_review(run(athlete, day(athlete, 0)), push=True)
    assert sent == []
    row.run_summary = True
    row.save()
    from django.utils import timezone

    activity = run(athlete, day(athlete, 0))
    activity.started_at = timezone.now() - dt.timedelta(hours=1)
    activity.save(update_fields=["started_at"])
    reviews.build_review(activity, push=True)
    assert len(sent) == 1 and sent[0]["tag"] == f"run_summary-{activity.pk}"
    assert sent[0]["url"] == f"/activities/{activity.pk}"


# --- §10 ----------------------------------------------------------------------------

def test_mood_upsert_list_delete_and_isolation(api, other_api, athlete):
    r = api.post("/api/mood/", {"mood": 4, "energy": 3, "note": "fine"}, format="json")
    assert r.status_code == 201 and set(r.json()) == {"date", "mood", "energy", "note",
                                                      "updated_at"}
    r = api.post("/api/mood/", {"mood": 2, "energy": 2}, format="json")
    assert r.status_code == 200 and MoodLog.objects.filter(athlete=athlete).count() == 1
    for bad in ({"mood": 0, "energy": 3}, {"mood": 3, "energy": 6}, {"mood": "x", "energy": 3},
                {"mood": True, "energy": 3}, {"mood": 3, "energy": 3, "date": "2020-01-01"},
                {"mood": 3.5, "energy": 3}):
        assert api.post("/api/mood/", bad, format="json").status_code == 400, bad
    assert api.get("/api/mood/today/").json()["entry"]["mood"] == 2
    assert len(api.get("/api/mood/").json()) == 1
    assert other_api.get("/api/mood/").json() == []
    assert other_api.get("/api/mood/today/").json()["entry"] is None
    today = athlete.local_today.isoformat()
    assert other_api.delete(f"/api/mood/{today}/").status_code == 404
    assert api.delete(f"/api/mood/{today}/").status_code == 204
    assert api.get("/api/mood/?start=2026-01-02&end=2026-01-01").status_code == 400


def test_mood_in_weekly_report_and_compare(api, athlete):
    from apps.health.reports import last_complete_week

    start = last_complete_week(athlete)
    for i, (m, e) in enumerate([(4, 3), (2, 5)]):
        MoodLog.objects.create(athlete=athlete, date=start + dt.timedelta(days=i), mood=m,
                               energy=e)
    body = api.get("/api/reports/weekly/").json()
    assert body["mood"] == {"mood_avg": 3.0, "energy_avg": 4.0, "days": 2,
                            "previous_mood_avg": None, "previous_energy_avg": None}
    keys = {m["key"]: m for m in api.get("/api/health/compare/metrics/").json()["metrics"]}
    assert keys["mood"]["group"] == "wellness" and keys["caffeine"]["group"] == "habits"
    r = api.get("/api/health/compare/?x=mood&y=energy&range=4w")
    assert r.status_code == 200 and r.json()["n"] == 2


# --- §11 ----------------------------------------------------------------------------

def test_monthly_report_build_list_and_errors(api, other_api, athlete):
    from apps.health.monthly import last_complete_month, month_end

    first = last_complete_month(athlete)
    run(athlete, first + dt.timedelta(days=3), km=5)
    run(athlete, first + dt.timedelta(days=10), km=8)
    MoodLog.objects.create(athlete=athlete, date=first + dt.timedelta(days=2), mood=4, energy=4)
    PainReport.objects.create(athlete=athlete, date=first + dt.timedelta(days=4),
                              location="knee", side="left", severity=2)
    body = api.get("/api/reports/monthly/").json()
    assert body["month"] == first.strftime("%Y-%m") and body["end"] == month_end(first).isoformat()
    assert body["runs"]["count"] == 2 and body["runs"]["longest_km"] == 8.0
    assert body["mood"]["mood_avg"] == 4.0 and body["injury"] == {"flags": 0, "pain_days": 1}
    assert body["ai"]["status"] == "none" and isinstance(body["goal"], str)
    assert set(body) == {"id", "month", "start", "end", "generated_at", "runs", "prs", "fitness",
                         "wellness", "habits", "smoke_free_days", "mood", "weight", "injury",
                         "went_well", "to_improve", "goal", "ai"}
    this_month = athlete.local_today.strftime("%Y-%m")
    assert api.get(f"/api/reports/monthly/?month={this_month}").status_code == 400
    assert api.get("/api/reports/monthly/?month=bad").status_code == 400
    listed = api.get("/api/reports/monthly/list/").json()
    assert listed[0]["runs_done"] == 2 and listed[0]["month"] == body["month"]
    assert other_api.get("/api/reports/monthly/list/").json() == []
    assert other_api.get("/api/reports/monthly/").json()["runs"]["count"] == 0
    assert MonthlyReport.objects.filter(athlete=athlete).count() == 1


def test_monthly_ai_excludes_private_and_notes(api, athlete, fake_ai):
    from apps.habits.models import HabitLog
    from apps.health.monthly import last_complete_month

    athlete.private_habit_enabled = True
    athlete.save()
    first = last_complete_month(athlete)
    moment = dt.datetime.combine(first + dt.timedelta(days=2), dt.time(12),
                                 tzinfo=dt.timezone.utc)
    HabitLog.objects.create(athlete=athlete, kind="private", at=moment)
    HabitLog.objects.create(athlete=athlete, kind="caffeine", at=moment, subtype="tea")
    MoodLog.objects.create(athlete=athlete, date=first + dt.timedelta(days=2), mood=3, energy=3,
                           note="very secret")
    body = api.get("/api/reports/monthly/").json()
    assert {h["habit"] for h in body["habits"]} >= {"private", "caffeine"}
    r = api.post("/api/reports/monthly/ai/")
    assert r.status_code == 200 and r.json()["status"] == "ready"
    _, prompt = fake_ai[0]
    assert "private" not in prompt.lower() and "secret" not in prompt
    assert "caffeine" in prompt


def test_monthly_beat(athlete, monkeypatch):
    from apps.health import tasks

    queued = []
    monkeypatch.setattr(tasks.build_monthly_report, "delay", lambda pk: queued.append(pk))
    tasks.monthly_reports.run()
    now = athlete.local_now
    assert queued == ([athlete.pk] if now.day == 1 and now.hour == 6 else [])
    assert tasks.build_monthly_report.run(athlete.pk)["month"]


# --- reminders ------------------------------------------------------------------------

def test_new_reminders_keys(api):
    body = api.get("/api/reminders/").json()
    by_key = {r["key"]: r for r in body["reminders"]}
    assert by_key["morning_briefing"]["time"] == "06:30"
    assert by_key["run_summary"]["time"] is None and "run_reviewed" not in by_key
    assert api.patch("/api/reminders/", {"run_summary": {"time": "07:00"}},
                     format="json").status_code == 400
    # R15: run_reviewed is still accepted as an alias of run_summary.
    r = api.patch("/api/reminders/", {"run_reviewed": {"enabled": False},
                                      "morning_briefing": {"time": "05:45"}}, format="json")
    assert r.status_code == 200
    by_key = {r["key"]: r for r in r.json()["reminders"]}
    assert by_key["run_summary"]["enabled"] is False
    assert by_key["morning_briefing"]["time"] == "05:45"
