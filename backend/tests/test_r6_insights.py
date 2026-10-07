"""R6 §5: Insights focus rules (pure) and the endpoint shapes."""

import datetime as dt

import pytest

from analysis.insights import FocusInputs, computed_readiness, focus, pace_cv, slope_per_week
from apps.ingest.models import DailyMetrics
from tests.r6_helpers import make_activity

TOP_KEYS = {"range", "today", "readiness", "hrv", "sleep", "resting_hr", "body_battery",
            "stress", "respiration", "vo2max", "race_predictions", "running", "load",
            "focus", "summary",
            "start", "end", "period"}      # R12 §A


def keys(items):
    return [i["key"] for i in items]


def test_each_focus_rule_fires():
    assert keys(focus(FocusInputs(avg_cadence=150))) == ["cadence"]
    assert keys(focus(FocusInputs(easy_above_z2_share=0.45))) == ["easy_pace"]
    assert keys(focus(FocusInputs(runs=4, run_fraction_slope=0.01,
                                  avg_run_fraction=0.6))) == ["run_blocks"]
    assert keys(focus(FocusInputs(hrv_last_days=[40, 41, 39],
                                  hrv_baseline_low=44))) == ["recovery"]
    assert keys(focus(FocusInputs(avg_sleep_h=6.2))) == ["sleep"]
    assert keys(focus(FocusInputs(gap_days=12))) == ["consistency"]
    assert keys(focus(FocusInputs(respiration_recent=[16.5, 16.8, 16.2],
                                  respiration_baseline=15.0))) == ["breathing"]


def test_focus_rules_do_not_fire_on_good_numbers():
    good = FocusInputs(avg_cadence=165, easy_above_z2_share=0.1, runs=5,
                       run_fraction_slope=0.05, avg_run_fraction=0.7,
                       hrv_last_days=[50, 39, 51], hrv_baseline_low=44, avg_sleep_h=7.5,
                       gap_days=2, respiration_recent=[15.2, 15.1], respiration_baseline=15.0)
    assert focus(good) == []


def test_focus_is_capped_at_three_most_urgent_first():
    items = focus(FocusInputs(avg_cadence=150, easy_above_z2_share=0.5, avg_sleep_h=6,
                              gap_days=10, hrv_last_days=[30, 30, 30], hrv_baseline_low=44))
    assert keys(items) == ["recovery", "sleep", "consistency"]
    assert all(set(i) == {"key", "title", "why", "how"} for i in items)


def test_helpers():
    day = dt.date(2026, 9, 1)
    points = [(day + dt.timedelta(days=7 * i), 150 + i) for i in range(4)]
    assert slope_per_week(points) == pytest.approx(1.0)
    assert slope_per_week(points[:2]) is None
    assert pace_cv([(400, 100), (400, 100)]) == 0
    assert computed_readiness(sleep_h=None, hrv=None, hrv_baseline=(None, None),
                              resting_hr=None, resting_baseline=None, form=None) == (None, [])
    score, drivers = computed_readiness(sleep_h=5.5, hrv=40, hrv_baseline=(44, 60),
                                        resting_hr=None, resting_baseline=None, form=None)
    assert score == 40 and len(drivers) == 2


def test_insights_endpoint_shape(api, athlete):
    today = athlete.local_today
    for i in range(10):
        DailyMetrics.objects.create(
            athlete=athlete, metric_date=today - dt.timedelta(days=i), sleep_seconds=23000,
            sleep_score=70, hrv_overnight_avg=40, hrv_baseline_low=44, hrv_baseline_high=60,
            hrv_status="UNBALANCED", resting_hr=55, respiration_avg=15.0,
            respiration_sleep_avg=14.0, stress_avg=30, body_battery_high=80,
            body_battery_low=20, training_readiness=55 if i == 0 else None,
            training_readiness_level="MODERATE", vo2max=42.0,
            race_pred_5k_s=1800 if i == 0 else None, race_pred_10k_s=3800 if i == 0 else None)
    for i in (12, 9, 5):
        make_activity(athlete, today - dt.timedelta(days=i), cadence=148,
                      zones={"Z1": 100, "Z2": 200, "Z3": 400},
                      blocks=[{"duration_s": 300, "hr_avg": 140, "hr_max": 150, "pace": 420}])

    r = api.get("/api/insights/", {"range": "4w"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == TOP_KEYS
    assert set(body["readiness"]) == {"score", "label", "drivers", "source"}
    assert body["readiness"]["source"] == "garmin" and body["readiness"]["score"] == 55
    assert set(body["hrv"]) == {"last_night_ms", "weekly_avg_ms", "baseline_low",
                                "baseline_high", "status", "series"}
    assert body["hrv"]["status"] == "unbalanced"
    assert set(body["hrv"]["series"][0]) == {"date", "ms"}
    assert set(body["sleep"]) == {"avg_s", "avg_score", "series"}
    assert set(body["sleep"]["series"][0]) == {"date", "s", "score"}
    assert set(body["resting_hr"]) == {"current", "trend_bpm_per_week", "series"}
    assert set(body["body_battery"]) == {"avg", "series"} == set(body["stress"])
    assert set(body["respiration"]) == {"avg_rpm", "sleep_avg_rpm", "series"}
    assert body["vo2max"]["value"] == 42.0
    assert set(body["race_predictions"]) >= {"5k_s", "10k_s", "half_s"}
    running = body["running"]
    assert set(running) == {"runs", "run_km", "run_fraction_trend", "longest_run_trend",
                            "easy_pace_trend", "cadence", "hr_drift_avg", "pace_cv_avg", "form"}
    assert running["runs"] == 3
    assert set(running["cadence"]) == {"avg", "trend", "target", "note"}
    assert set(body["load"]) == {"fitness", "fatigue", "form", "status", "acwr"}
    assert 1 <= len(body["focus"]) <= 3
    focus_keys = keys(body["focus"])
    assert focus_keys[0] == "recovery"                      # HRV under baseline 3+ days
    assert "sleep" in focus_keys                            # ~6.4 h
    assert body["summary"]["status"] == "none"


def test_insights_bad_range(api):
    assert api.get("/api/insights/", {"range": "2y"}).status_code == 400


def test_empty_account_still_renders(api):
    body = api.get("/api/insights/", {"range": "6m"}).json()
    assert body["vo2max"] is None and body["race_predictions"] is None
    assert body["readiness"]["score"] is None and body["running"]["runs"] == 0


def test_summary_generated_cached_per_day(api, athlete, monkeypatch):
    from apps.coaching import services
    from apps.coaching.models import AIRequestLog
    from apps.coaching.schemas import InsightsSummary

    calls = []

    def fake_complete(*, operation, schema, **kwargs):
        calls.append(operation)
        return InsightsSummary(markdown="Steady progress."), {
            "model": "test-model", "input_tokens": 1, "output_tokens": 1, "latency_ms": 1,
            "retry_count": 0, "estimated_cost_usd": 0.0}

    monkeypatch.setattr(services, "complete", fake_complete)
    monkeypatch.setattr(services, "model_for", lambda op: "test-model")
    r = api.post("/api/insights/summary/")
    assert r.status_code == 200
    assert r.json()["status"] == "ready" and r.json()["markdown"] == "Steady progress."
    api.post("/api/insights/summary/")
    assert calls == ["insights_summary"]
    assert AIRequestLog.objects.filter(athlete=athlete, operation="insights_summary").count() == 1
    assert api.get("/api/insights/").json()["summary"]["status"] == "ready"


def test_summary_503(api, monkeypatch):
    from apps.coaching import services
    from apps.coaching.client import AIUnavailable

    def boom(**kwargs):
        raise AIUnavailable("down")

    monkeypatch.setattr(services, "complete", boom)
    monkeypatch.setattr(services, "model_for", lambda op: "test-model")
    r = api.post("/api/insights/summary/")
    assert r.status_code == 503 and r.json()["detail"]
