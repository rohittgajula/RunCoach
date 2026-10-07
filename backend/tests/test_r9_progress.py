"""R9 §D: progress by custom dates, `period` in both modes and the `highlights` bullets —
pure maths first, then the API (validation, review cache key, tenant isolation)."""

import datetime as dt

import pytest

from analysis import progress as p
from apps.coaching import services as coaching
from apps.coaching.models import AIAnalysis
from tests.r6_helpers import make_activity

PERIOD_KEYS = {"mode", "start", "end", "compare_start", "compare_end", "runs_current",
               "runs_previous"}


def run(i, day, **kw):
    base = {"id": i, "date": day, "run_km": 3.0, "total_km": 4.0, "run_pace": 432.0,
            "avg_hr": 150, "max_hr": 170, "easy_hr": 145.0, "efficiency": 1.0,
            "hr_drift": 4.0, "cadence": 158.0, "run_fraction": 0.6, "longest_run_s": 600.0,
            "z2_pct": 50.0, "fastest_1k_s": 380.0}
    return base | kw


def sept(day):
    return f"2026-09-{day:02d}"


# --- pure ---------------------------------------------------------------------

def test_dates_split_and_period():
    runs = [run(i, sept(i)) for i in range(1, 31)]
    body = p.progress_dates(runs, sept(16), sept(30), sept(1), sept(15))
    assert body["current_n"] == 15 and body["previous_n"] == 15 and body["window"] is None
    assert body["period"] == {"mode": "dates", "start": sept(16), "end": sept(30),
                              "compare_start": sept(1), "compare_end": sept(15),
                              "runs_current": 15, "runs_previous": 15}
    assert len(body["metrics"]) == 12 and len(body["distance_buckets"]) == 4
    assert body["distance_buckets"][1]["current_n"] == 15            # 4 km -> 2to5


def test_dates_bests_use_history_before_the_period():
    runs = [run(1, "2026-06-01", fastest_1k_s=300.0)] + \
        [run(i, sept(i)) for i in range(2, 10)] + [run(10, sept(20), fastest_1k_s=350.0)]
    body = p.progress_dates(runs, sept(15), sept(30), sept(1), sept(14))
    assert body["bests"]["fastest_1k_s"]["value"] == 300.0
    assert body["bests"]["fastest_1k_s"]["new"] is False
    later = p.progress_dates(runs + [run(11, sept(25), fastest_1k_s=290.0)],
                             sept(15), sept(30), sept(1), sept(14))
    assert later["bests"]["fastest_1k_s"]["new"] is True
    assert any(h["text"].startswith("New best: fastest 1 km in 4:50") for h in later["highlights"])


def test_highlight_texts_readable_values():
    old = [run(i, sept(i), run_pace=432.0) for i in range(1, 6)]
    new = [run(i, sept(i), run_pace=418.0, easy_hr=140.0) for i in range(16, 21)]
    body = p.progress_dates(old + new, sept(16), sept(30), sept(1), sept(15))
    texts = [h["text"] for h in body["highlights"]]
    assert "Run pace 7:12 → 6:58 /km — 14 s faster" in texts
    assert "HR at easy pace 145 → 140 bpm — 5 bpm lower" in texts
    assert all(set(h) == {"tone", "text"} for h in body["highlights"])


def test_highlights_good_first_and_max_six():
    old = [run(i, sept(i)) for i in range(1, 3)]
    new = [run(i, sept(i), run_pace=400.0, easy_hr=140.0, efficiency=1.1, run_km=3.5,
               run_fraction=0.7, longest_run_s=700.0, cadence=150.0, hr_drift=6.0,
               z2_pct=60.0) for i in range(16, 26)]
    hl = p.progress_dates(old + new, sept(16), sept(30), sept(1), sept(15))["highlights"]
    assert len(hl) == 6
    tones = [h["tone"] for h in hl]
    assert tones == sorted(tones, key=["good", "bad", "neutral"].index)
    assert tones[0] == "good"


def test_highlights_one_run_and_no_runs():
    one = p.progress_dates([run(1, sept(20))], sept(16), sept(30), sept(1), sept(15))
    texts = [h["text"] for h in one["highlights"]]
    assert "Only one run in this period" in texts
    assert all(h["tone"] == "neutral" for h in one["highlights"])
    none = p.progress_dates([run(1, sept(2))], sept(16), sept(30), sept(1), sept(15))
    assert none["highlights"] == [{"tone": "neutral", "text": "No runs in this period"}]


def test_highlights_consistency_and_bucket():
    old = [run(i, sept(i), total_km=3.0) for i in (1, 8)] + \
        [run(i, sept(i), total_km=6.0) for i in (2, 9)]
    new = [run(i, sept(i), total_km=3.0, run_pace=410.0) for i in (16, 18, 20, 22)] + \
        [run(i, sept(i), total_km=6.0) for i in (17, 23)]
    hl = p.progress_dates(old + new, sept(16), sept(29), sept(2), sept(15))["highlights"]
    texts = [h["text"] for h in hl]
    assert "Consistency 1.5 → 3.0 runs/week" in texts      # day 1 is outside
    assert "2–5 km runs: run pace 7:12 → 6:50 /km — 22 s faster (4 vs 1 runs)" in texts


def test_window_mode_has_period_and_highlights():
    runs = [run(i, sept(i)) for i in range(1, 11)]
    body = p.progress(runs, 5)
    assert set(body["period"]) == PERIOD_KEYS and body["period"]["mode"] == "window"
    assert body["period"]["start"] == sept(6) and body["period"]["end"] == sept(10)
    assert body["period"]["compare_start"] == sept(1) and body["period"]["runs_previous"] == 5
    assert body["highlights"]
    first = p.progress([run(1, sept(1))], 1)
    assert [h["text"] for h in first["highlights"]] == [
        "Only one run in this period", "No earlier runs to compare with yet"]
    assert p.progress([], 5)["highlights"] == [{"tone": "neutral",
                                                "text": "No runs in this period"}]


def test_window_one_does_not_say_only_one_run():
    runs = [run(i, sept(i)) for i in range(1, 7)]
    texts = [h["text"] for h in p.progress(runs, 1)["highlights"]]
    assert "Only one run in this period" not in texts


# --- API ----------------------------------------------------------------------

def make_runs(athlete, days_ago):
    today = athlete.local_today
    return [make_activity(athlete, today - dt.timedelta(days=d), run_s=1200 + 10 * d)
            for d in days_ago]


def test_dates_mode_endpoint(api, athlete):
    make_runs(athlete, [1, 3, 5, 12, 20, 33, 40, 45])
    today = athlete.local_today
    start = (today - dt.timedelta(days=29)).isoformat()
    body = api.get("/api/progress/", {"start": start, "end": today.isoformat()}).json()
    assert body["period"]["mode"] == "dates" and body["window"] is None
    assert body["period"]["start"] == start and body["period"]["end"] == today.isoformat()
    assert body["period"]["compare_end"] == (today - dt.timedelta(days=30)).isoformat()
    assert body["period"]["compare_start"] == (today - dt.timedelta(days=59)).isoformat()
    assert body["current_n"] == 5 and body["previous_n"] == 3
    assert body["period"]["runs_current"] == 5 and body["highlights"]
    assert {"metrics", "distance_buckets", "bests", "series", "focus", "review", "sport",
            "today"} <= set(body)


def test_dates_mode_explicit_compare(api, athlete):
    make_runs(athlete, [1, 3, 100, 101, 102])
    today = athlete.local_today
    body = api.get("/api/progress/", {
        "start": (today - dt.timedelta(days=6)).isoformat(), "end": today.isoformat(),
        "compare_start": (today - dt.timedelta(days=105)).isoformat(),
        "compare_end": (today - dt.timedelta(days=99)).isoformat()}).json()
    assert body["current_n"] == 2 and body["previous_n"] == 3


@pytest.mark.parametrize("params,msg", [
    ({"window": 5, "start": "2026-09-01", "end": "2026-09-30"}, "not both"),
    ({"start": "2026-09-01"}, "both required"),
    ({"start": "2026-09-30", "end": "2026-09-01"}, "on or before"),
    ({"start": "2024-01-01", "end": "2026-09-01"}, "730"),
    ({"start": "2026-09-01", "end": "nope"}, "YYYY-MM-DD"),
    ({"start": "2026-09-01", "end": "2026-09-30", "compare_start": "2026-08-01"}, "together"),
    ({"start": "2026-09-01", "end": "2026-09-30", "compare_start": "2026-08-30",
      "compare_end": "2026-08-01"}, "on or before"),
    ({"window": 3}, "window must be"),
])
def test_dates_validation(api, params, msg):
    r = api.get("/api/progress/", params)
    assert r.status_code == 400 and msg in r.json()["detail"]
    assert api.post("/api/progress/review/?" + "&".join(
        f"{k}={v}" for k, v in params.items())).status_code == 400


def test_max_range_is_inclusive_730_days(api):
    end = dt.date(2026, 9, 30)
    ok = api.get("/api/progress/", {"start": (end - dt.timedelta(days=729)).isoformat(),
                                    "end": end.isoformat()})
    assert ok.status_code == 200
    too_long = api.get("/api/progress/", {"start": (end - dt.timedelta(days=730)).isoformat(),
                                          "end": end.isoformat()})
    assert too_long.status_code == 400


def test_review_cache_key_includes_dates(api, athlete, monkeypatch):
    calls = []

    def fake(*, operation, schema, user, **kw):
        calls.append(user)
        return schema(went_well=["Pace"], improve=["Cadence"], check=[], markdown="Good."), {
            "model": "m", "input_tokens": 1, "output_tokens": 1, "latency_ms": 1,
            "retry_count": 0, "estimated_cost_usd": 0}
    monkeypatch.setattr(coaching, "complete", fake)
    make_runs(athlete, [1, 3, 5, 40, 45])
    today = athlete.local_today
    a = f"start={(today - dt.timedelta(days=29)).isoformat()}&end={today.isoformat()}"
    b = f"start={(today - dt.timedelta(days=9)).isoformat()}&end={today.isoformat()}"
    assert api.post(f"/api/progress/review/?{a}").status_code == 200
    assert "runs from" in calls[0] and '"highlights"' in calls[0]
    api.post(f"/api/progress/review/?{a}")
    assert len(calls) == 1                                   # cached
    api.post(f"/api/progress/review/?{b}")
    assert len(calls) == 2                                   # different dates
    api.post("/api/progress/review/?window=5")
    assert len(calls) == 3                                   # window mode separate
    assert api.get(f"/api/progress/?{a}").json()["review"]["status"] == "ready"
    assert api.get("/api/progress/?start=2020-01-01&end=2020-01-31").json()[
        "review"]["status"] == "none"
    api.post(f"/api/progress/review/?{a}&refresh=1")
    assert len(calls) == 4
    assert AIAnalysis.objects.filter(athlete=athlete, kind=AIAnalysis.Kind.PROGRESS).count() == 3


def test_review_dates_no_runs_409(api):
    assert api.post("/api/progress/review/?start=2020-01-01&end=2020-01-31").status_code == 409


def test_dates_tenant_isolation(other_api, athlete):
    make_runs(athlete, [1, 2, 3, 40])
    today = athlete.local_today
    body = other_api.get("/api/progress/", {"start": (today - dt.timedelta(days=29)).isoformat(),
                                            "end": today.isoformat()}).json()
    assert body["current_n"] == 0 and body["runs"] == 0 and body["series"] == []
    assert body["highlights"] == [{"tone": "neutral", "text": "No runs in this period"}]
