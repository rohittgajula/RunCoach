""""Am I improving?" report (Health → Reports → Improving)."""

import datetime as dt

import pytest

from analysis import improving as maths
from apps.activities.models import ActivityMetrics
from tests.r6_helpers import make_activity

TODAY = dt.date(2026, 11, 28)


def run(date, *, pace, hr, z45=0, total_min=25, sport="running", max_hr=160):
    zones = {"below": 0, "Z1": 100, "Z2": 600 - z45 * 10, "Z3": 400, "Z4": z45 * 10, "Z5": 0}
    return {"date": date, "sport": sport, "total_s": total_min * 60, "total_m": 2200,
            "run_s": 600, "run_pace_s": pace, "run_hr": hr, "max_hr": max_hr,
            "zones": zones, "longest_run_s": 240}


def test_metres_per_heartbeat_is_speed_over_heart_rate():
    # 10:00/km = 1.667 m/s at 140 bpm (2.333 beats/s) -> 0.71 m per beat
    assert maths.run_row(run("2026-08-01", pace=600, hr=140))["m_per_beat"] == 0.71


def test_control_better_fitness_flat_is_the_rohit_case():
    runs = [run("2026-08-18", pace=590, hr=146, z45=40), run("2026-08-20", pace=600, hr=150, z45=40),
            run("2026-11-25", pace=620, hr=139, z45=5), run("2026-11-28", pace=625, hr=138, z45=0)]
    body = maths.report(runs, [("2026-08-02", 61), ("2026-11-02", 61)], TODAY, (135, 148))
    assert body["status"] == "ok" and body["verdict"]["key"] == "control"
    by = {c["key"]: c["status"] for c in body["changes"]}
    assert by["z45_pct"] == "better" and by["run_hr"] == "better"
    assert by["m_per_beat"] == "flat" and by["rhr"] == "flat"
    assert [m["month"] for m in body["months"]] == ["2026-08", "2026-09", "2026-10", "2026-11"]
    assert body["months"][1]["runs"] == 0
    assert body["gaps"][0]["days"] >= 90


def test_fitness_better_when_same_hr_carries_further():
    runs = [run("2026-08-01", pace=640, hr=140), run("2026-10-01", pace=560, hr=140)]
    body = maths.report(runs, [], TODAY)
    assert {c["key"]: c["status"] for c in body["changes"]}["m_per_beat"] == "better"
    assert body["verdict"]["key"] in ("fitness", "both")


def test_treadmill_left_out_short_run_kept_and_flagged():
    runs = [run("2026-08-09", pace=480, hr=127, total_min=6),
            run("2026-11-20", pace=300, hr=134, sport="treadmill_running"),
            run("2026-11-28", pace=625, hr=138)]
    body = maths.report(runs, [], TODAY)
    assert body["excluded_indoor"] == 1 and len(body["runs"]) == 2
    assert body["runs"][0]["short"] is True


def test_one_month_is_not_enough():
    body = maths.report([run("2026-11-25", pace=600, hr=140)], [], TODAY)
    assert body["status"] == "not_enough" and body["verdict"]["key"] == "early"


def test_no_runs():
    body = maths.report([], [], TODAY)
    assert body["runs"] == [] and body["status"] == "not_enough"


@pytest.mark.django_db
def test_api(api, athlete):
    today = athlete.local_today
    for days, hr in ((100, 150), (98, 148), (2, 138), (1, 137)):
        a = make_activity(athlete, today - dt.timedelta(days=days),
                          zones={"Z2": 600, "Z3": 300, "Z4": 100 if hr > 145 else 0})
        # Later runs are slower at a lower HR: more control, same engine (his case).
        ActivityMetrics.objects.filter(activity=a).update(
            avg_run_hr=hr, run_pace_s_per_km=600 if hr > 145 else 650)
    make_activity(athlete, today - dt.timedelta(days=3), sport="treadmill_running")
    r = api.get("/api/reports/improving/")
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["excluded_indoor"] == 1 and len(body["runs"]) == 4
    assert body["status"] == "ok" and body["verdict"]["key"] == "control"
