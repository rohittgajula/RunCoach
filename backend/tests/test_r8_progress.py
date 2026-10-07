"""R8 §C: progress comparison — pure maths, then the API."""

import datetime as dt

import pytest

from analysis import progress as p
from apps.activities.models import ActivityRecord
from apps.coaching import services as coaching
from apps.coaching.client import AIUnavailable
from tests.r6_helpers import make_activity


def run(i, **kw):
    base = {"id": i, "date": f"2026-09-{i:02d}", "run_km": 3.0, "total_km": 4.0,
            "run_pace": 420.0, "avg_hr": 150, "max_hr": 170, "easy_hr": 145.0,
            "efficiency": 1.0, "hr_drift": 4.0, "cadence": 158.0, "run_fraction": 0.6,
            "longest_run_s": 600.0, "z2_pct": 50.0, "fastest_1k_s": 380.0}
    return base | kw


def by_key(rows):
    return {r["key"]: r for r in rows}


@pytest.mark.parametrize("window,cur,prev", [(1, 1, 5), (5, 5, 5), (10, 10, 10),
                                             (20, 10, 0)])
def test_windows(window, cur, prev):
    runs = [run(i) for i in range(1, 21)] if window != 20 else [run(i) for i in range(1, 11)]
    current, previous = p.split(runs, window)
    assert len(current) == cur and len(previous) == prev
    if window == 1:
        assert current[0]["id"] == runs[-1]["id"] and previous[-1]["id"] == runs[-2]["id"]


def test_direction_aware_deltas():
    old = [run(i) for i in range(1, 6)]
    new = [run(i, run_pace=400.0, easy_hr=140.0, avg_hr=155, hr_drift=6.0, cadence=162.0,
               efficiency=1.1, run_fraction=0.605) for i in range(6, 11)]
    rows = by_key(p.compare(new, old))
    assert rows["run_pace"]["delta"] == -20 and rows["run_pace"]["better"] is True
    assert rows["easy_hr"]["better"] is True
    assert rows["avg_hr"]["better"] is None                    # no direction on its own
    assert rows["hr_drift"]["better"] is False
    assert rows["cadence"]["better"] is True                   # closer to the target
    assert rows["efficiency"]["better"] is True and rows["efficiency"]["delta_pct"] == 10.0
    assert rows["run_fraction"]["current"] == 60.5 and rows["run_fraction"]["better"] is None
    assert rows["run_km"]["better"] is None                    # no change
    assert set(rows["run_pace"]) == {"key", "label", "current", "previous", "delta",
                                     "delta_pct", "better", "unit"}


def test_missing_previous_gives_null_deltas():
    rows = by_key(p.compare([run(1)], []))
    assert rows["run_pace"]["current"] == 420 and rows["run_pace"]["previous"] is None
    assert rows["run_pace"]["delta"] is None and rows["run_pace"]["better"] is None


def test_distance_buckets_compare_like_with_like():
    runs = [run(i, total_km=1.5) for i in range(1, 4)] + [run(i, total_km=6.0, run_pace=380.0)
                                                          for i in range(4, 8)]
    assert p.bucket_of(1.99) == "lt2" and p.bucket_of(2) == "2to5" and p.bucket_of(8) == "8plus"
    buckets = {b["bucket"]: b for b in p.distance_buckets(runs, 1)}
    assert buckets["lt2"]["runs"] == 3 and buckets["5to8"]["runs"] == 4
    assert buckets["2to5"]["metrics"] == [] and buckets["8plus"]["runs"] == 0
    assert by_key(buckets["5to8"]["metrics"])["run_pace"]["current"] == 380


def test_bests_flag_new_ones():
    runs = [run(i) for i in range(1, 8)] + [run(8, fastest_1k_s=350.0, total_km=9.0)]
    current, _ = p.split(runs, 1)
    bests = p.bests(runs, current)
    assert bests["fastest_1k_s"] == {"value": 350.0, "date": "2026-09-08", "activity_id": 8,
                                     "new": True}
    assert bests["longest_run_km"]["value"] == 9.0 and bests["longest_run_km"]["new"]
    assert bests["lowest_easy_hr"]["new"] is False


def test_focus_rules():
    old = [run(i) for i in range(1, 6)]
    new = [run(i, hr_drift=7.0, easy_hr=150.0, cadence=158.5, run_fraction=0.61)
           for i in range(6, 11)]
    keys = [f["key"] for f in p.focus(p.compare(new, old))]
    assert keys[:4] == ["hr_drift", "easy_hr", "cadence", "run_blocks"]
    good = [run(i, cadence=170.0, run_fraction=0.95, hr_drift=2.0) for i in range(6, 11)]
    assert p.focus(p.compare(good, [run(i, cadence=170.0, run_fraction=0.95, hr_drift=2.0)
                                    for i in range(1, 6)])) == []


# --- API ----------------------------------------------------------------------

def make_runs(athlete, n=8):
    today = athlete.local_today
    acts = []
    for i in range(n):
        a = make_activity(athlete, today - dt.timedelta(days=2 * (n - i)), run_s=1200 + 60 * i)
        acts.append(a)
    return acts


def test_progress_endpoint_shape(api, athlete):
    acts = make_runs(athlete)
    ActivityRecord.objects.bulk_create([
        ActivityRecord(activity=acts[-1], offset_s=t, distance_m=t * 3.0) for t in range(0, 700, 5)])
    body = api.get("/api/progress/", {"window": 5}).json()
    assert {"window", "runs", "current_n", "previous_n", "metrics", "distance_buckets",
            "bests", "series", "focus", "sport", "today", "review"} <= set(body)
    assert body["current_n"] == 5 and body["previous_n"] == 3 and len(body["metrics"]) == 12
    assert len(body["distance_buckets"]) == 4 and body["series"][0]["bucket"] == "2to5"
    assert body["bests"]["fastest_1k_s"]["value"] == pytest.approx(333.3, abs=5)
    assert body["bests"]["fastest_1k_s"]["new"] is True
    assert body["review"]["status"] == "none"
    assert api.get("/api/progress/", {"window": 3}).status_code == 400


def test_progress_tenant_isolation(other_api, athlete):
    make_runs(athlete)
    body = other_api.get("/api/progress/", {"window": 1}).json()
    assert body["runs"] == 0 and body["metrics"] == []


def test_review_is_cached_per_window(api, athlete, monkeypatch):
    calls = []

    def fake(*, operation, schema, **kw):
        calls.append(operation)
        return schema(went_well=["Pace"], improve=["Cadence"], check=[], markdown="Good."), {
            "model": "m", "input_tokens": 1, "output_tokens": 1, "latency_ms": 1,
            "retry_count": 0, "estimated_cost_usd": 0}
    monkeypatch.setattr(coaching, "complete", fake)
    make_runs(athlete)
    r = api.post("/api/progress/review/?window=5")
    assert r.status_code == 200 and r.json()["status"] == "ready"
    assert r.json()["went_well"] == ["Pace"] and calls == ["progress_review"]
    api.post("/api/progress/review/?window=5")
    assert len(calls) == 1
    api.post("/api/progress/review/?window=1")
    assert len(calls) == 2
    assert api.get("/api/progress/", {"window": 5}).json()["review"]["markdown"] == "Good."


def test_review_errors(api, athlete, monkeypatch):
    assert api.post("/api/progress/review/?window=5").status_code == 409     # no runs
    make_runs(athlete)

    def boom(**kw):
        raise AIUnavailable("down")
    monkeypatch.setattr(coaching, "complete", boom)
    assert api.post("/api/progress/review/?window=5").status_code == 503
