"""R17 pure modules: data quality (synthetic streams), recovery routine, illness rules,
memory facts, Garmin deletion window, streak neutral days. No Django, no wall clock."""

import datetime as dt

from analysis import achievements, data_quality as dq, garmin_deletions, memory_facts
from analysis import recovery_routine as rr
from planning import illness as rules

from .r17_streams import M_PER_DEG_LAT, run_stream

D = dt.date(2026, 10, 1)


# --- data quality ---------------------------------------------------------------------

def test_clean_run_has_no_flags_and_uses_cleaned():
    r = dq.analyse(run_stream(), max_hr=190)
    assert r.flags == [] and r.score == 100
    assert r.use_default == "cleaned" and r.use_suggestion is None and r.suggestion is None


def test_cadence_lock_is_masked_and_defaults_to_raw():
    s = run_stream()
    for i in range(300, 420):
        s[i].heart_rate = int(s[i].cadence_spm) + (i % 3 - 1)
    r = dq.analyse(s, max_hr=190)
    assert r.counts == {"hr_cadence_lock": 1}
    assert all(r.cleaned.heart_rate[i] is None for i in range(300, 420))
    assert r.cleaned.heart_rate[200] is not None
    # Not a minor spike fix → the raw stream stays the default, cleaned is suggested.
    assert r.use_default == "raw" and r.use_suggestion == "cleaned"
    assert "avg_hr" in r.affected and r.suggestion is None


def test_long_lock_suggests_exclusion_never_decides():
    s = run_stream()
    for i in range(0, 1100):
        s[i].heart_rate = int(s[i].cadence_spm) + (i % 3 - 1)
    r = dq.analyse(s, max_hr=190)
    assert r.score < 50 and r.suggestion == "exclude"
    assert r.suggestion_reason == "Wrist HR unreliable"
    view = dq.status_and_chip(r.summary_dict(), decision=None, use_choice=None)
    assert view["excluded_from_trends"] is False and view["pending_review"] is True
    assert dq.status_and_chip(r.summary_dict(), decision="exclude",
                              use_choice=None)["excluded_from_trends"] is True


def test_spike_interpolated_and_cleaned_by_default():
    s = run_stream()
    for i in range(500, 503):
        s[i].heart_rate += 40
    r = dq.analyse(s, max_hr=190)
    assert r.counts == {"hr_spike": 1} and r.use_default == "cleaned"
    assert all(abs(r.cleaned.heart_rate[i] - 136) < 3 for i in range(500, 503))
    assert [s[i].heart_rate for i in range(500, 503)] != r.cleaned.heart_rate[500:503]


def test_spike_matched_by_pace_or_lasting_is_real():
    s = run_stream()
    for i in range(500, 503):
        s[i].heart_rate += 40
    for i in range(500, 520):
        s[i].speed_mps = 3.8
    assert "hr_spike" not in dq.analyse(s, max_hr=190).counts
    s = run_stream(seconds=900, hr_end=135)
    for i in range(500, 900):
        s[i].heart_rate += 30
    assert "hr_spike" not in dq.analyse(s, max_hr=190).counts


def test_flatline_and_above_max():
    s = run_stream()
    for i in range(600, 760):
        s[i].heart_rate = 142
    s[1000].heart_rate = 235
    r = dq.analyse(s, max_hr=190)
    assert r.counts == {"hr_flatline": 1, "hr_above_max": 1}
    assert r.cleaned.heart_rate[1000] is None and r.cleaned.heart_rate[650] is None


def test_gps_teleport_corrects_track_and_distance():
    s = run_stream()
    s[900].latitude += 300 / M_PER_DEG_LAT
    for i in range(900, 1800):
        s[i].distance_m += 300
    r = dq.analyse(s, max_hr=190)
    assert r.counts == {"gps_teleport": 1}
    assert r.cleaned.latitude[900] is None and r.cleaned.latitude[901] is not None
    assert abs(r.cleaned.distance_m[-1] - 2.8 * 1799) < 5      # the 300 m jump is gone
    assert s[-1].distance_m > r.cleaned.distance_m[-1] + 290   # raw untouched


def test_gps_speed_for_runners_only():
    s = run_stream()
    for i in range(1000, 1005):
        s[i].speed_mps = 12.0
    assert "gps_speed" in dq.analyse(s, max_hr=190, foot=True).counts
    assert "gps_speed" not in dq.analyse(s, max_hr=190, foot=False).counts


def test_stationary_drift_and_pause_flags():
    s = run_stream()
    for i in range(1000, 1060):
        s[i].cadence_spm = 0
        s[i].speed_mps = 0.2
    r = dq.analyse(s, max_hr=190)
    assert "gps_drift" in r.counts
    assert r.cleaned.distance_m[1059] == r.cleaned.distance_m[1000]
    gap = [x for x in run_stream() if not 1200 < x.offset_s < 1230]
    r = dq.analyse(gap, max_hr=190)
    assert r.counts == {"pause_mismarked": 1} and r.use_default == "cleaned"
    assert r.flags[0].fix == "flagged"


def test_smart_recording_is_time_based():
    s = [x for x in run_stream() if int(x.offset_s) % 4 == 0]    # one sample every 4 s
    assert dq.analyse(s, max_hr=190).flags == []


# --- recovery routine -----------------------------------------------------------------

def _keys(r):
    return [s["key"] for s in r.steps if not s["optional"]]


def test_routine_easy_run_is_5_to_8_minutes():
    r = rr.build(rr.RoutineInputs(duration_s=30 * 60, distance_m=5000, kind="EASY"))
    assert 5 <= r.minutes <= 8 and rr.MIN_S <= r.total_s <= rr.MAX_S
    assert _keys(r)[0] == "cooldown_walk" and "calf_stretch" in _keys(r)
    assert all(s["optional"] for s in r.steps if s["key"].endswith("_roll"))
    assert all(set(s) >= {"key", "title", "seconds", "per_side", "cue", "figure", "optional"}
               for s in r.steps)


def test_routine_hills_long_hard_add_focus():
    r = rr.build(rr.RoutineInputs(duration_s=70 * 60, distance_m=10000, kind="LONG",
                                  elevation_gain_m=250, cadence_spm=150))
    assert {"long", "hills", "cadence"} <= set(r.focus)
    assert r.total_s <= rr.MAX_S and "Hilly" in r.reason


def test_routine_never_stretches_into_pain():
    r = rr.build(rr.RoutineInputs(duration_s=40 * 60, distance_m=6000,
                                  pains=[("knee", "left", 2), ("calf", "right", 1)]))
    keys = _keys(r)
    assert "quad_stretch" not in keys and "quad_roll" not in [s["key"] for s in r.steps]
    calf = next(s for s in r.steps if s["key"] == "calf_stretch")
    assert calf["softened"] and calf["cue"].startswith("Gently")
    assert any("Knee (left)" in a["text"] for a in r.avoided)
    assert all(not s["key"].startswith("calf_roll") for s in r.steps)


def test_recovery_streak_counts_from_first_routine():
    assert rr.recovery_streak([False, False, True, True, False, True]) == (1, 2)
    reached = rr.streak_reached([(D + dt.timedelta(days=i), True) for i in range(3)], [3])
    assert reached == {3: D + dt.timedelta(days=2)}


# --- illness rules -------------------------------------------------------------------

def _days(start, n, minutes=40, cap=150):
    return [rules.PlanDay(date=start + dt.timedelta(days=2 * i), duration_s=minutes * 60,
                          workout_id=i + 1, hr_cap=cap) for i in range(n)]


def test_short_illness_two_or_three_easy_sessions_never_longer_than_plan():
    block = rules.return_block(kind="cold", symptoms="above_neck", fever=False,
                               start_date=D, recovered_on=D + dt.timedelta(days=2),
                               usual_s=60 * 60, plan_days=_days(D + dt.timedelta(days=3), 5, 25),
                               easy_low=120, easy_top=150)
    assert block.rule == "short" and len(block.sessions) == 3
    assert [s.pct_of_usual for s in block.sessions] == [50, 60, 70]
    assert all(s.duration_s <= 25 * 60 for s in block.sessions)       # never above the plan
    assert block.sessions[0].hr_cap == 140 and block.sessions[2].hr_cap == 145
    assert block.resumes_on == block.sessions[-1].date + dt.timedelta(days=1)


def test_week_and_rebuild_rules():
    week = rules.return_block(kind="cold", symptoms="above_neck", fever=False, start_date=D,
                              recovered_on=D + dt.timedelta(days=5), usual_s=40 * 60,
                              plan_days=_days(D + dt.timedelta(days=6), 6), easy_top=150)
    assert week.rule == "week" and (week.end - week.start).days == 6
    flu = rules.return_block(kind="flu", symptoms="below_neck", fever=True, start_date=D,
                             recovered_on=D + dt.timedelta(days=10), usual_s=40 * 60,
                             plan_days=_days(D + dt.timedelta(days=11), 10), easy_top=150)
    assert flu.rule == "rebuild" and (flu.end - flu.start).days == 13
    assert flu.start == D + dt.timedelta(days=12)                        # 48 h symptom-free
    assert flu.sessions[0].kind == "RUN_WALK" and flu.sessions[0].pct_of_usual == 40
    assert flu.sessions[-1].kind == "EASY"


def test_sessions_only_on_plan_run_days_and_race_warning():
    days = _days(D + dt.timedelta(days=4), 3)
    block = rules.return_block(kind="other", symptoms="above_neck", fever=False, start_date=D,
                               recovered_on=D + dt.timedelta(days=1), usual_s=1800,
                               plan_days=days, easy_top=150)
    assert {s.date for s in block.sessions} <= {d.date for d in days}
    warn = rules.race_warning([(1, "City 10K", block.resumes_on + dt.timedelta(days=5))], block)
    assert warn["days_after_block"] == 5
    assert rules.race_warning([(1, "Far", block.resumes_on + dt.timedelta(days=60))],
                              block) is None


def test_injury_starts_with_run_walk_and_advice_is_non_medical():
    block = rules.return_block(kind="injury", symptoms="above_neck", fever=False,
                               start_date=D, recovered_on=D + dt.timedelta(days=2),
                               usual_s=1800, plan_days=_days(D + dt.timedelta(days=3), 4),
                               easy_top=150)
    assert [s.kind for s in block.sessions[:2]] == ["RUN_WALK", "RUN_WALK"]
    tips, doctor = rules.advice("flu", "below_neck", True)
    assert "24–48 hours" in tips[0] and doctor[0].startswith("See a doctor if")


# --- memory facts / Garmin window / streaks ------------------------------------------

def test_private_habit_filter_and_categories():
    assert memory_facts.mentions_private_habit("Tracks his private habit daily")
    assert memory_facts.mentions_private_habit("trying NoFap this month")
    assert not memory_facts.mentions_private_habit("Prefers morning runs")
    assert memory_facts.guess_category("Left knee hurts on hills") == "health"
    assert memory_facts.guess_category("Wants a sub-60 10K") == "goals"
    assert memory_facts.guess_category("Prefers running before work") == "schedule"
    assert memory_facts.guess_category("Has a dog named Max") == "other"
    facts = [("new", False), ("pinned old", True), ("porn free 30 days", False)]
    assert memory_facts.context_facts(facts, limit=2) == ["pinned old", "new"]


def test_garmin_deletion_window():
    today = D
    listed = [D - dt.timedelta(days=i) for i in range(5)]
    assert garmin_deletions.covered_from(listed, True, today) == D - dt.timedelta(days=3)
    assert garmin_deletions.covered_from(listed, False, today) == D - dt.timedelta(days=60)
    now = dt.datetime(2026, 10, 1, 12, tzinfo=dt.timezone.utc)
    ours = [(1, 11, D - dt.timedelta(days=1), now - dt.timedelta(days=1)),     # gone
            (2, 12, D - dt.timedelta(days=1), now - dt.timedelta(days=1)),     # listed
            (3, 13, D - dt.timedelta(days=10), now - dt.timedelta(days=10)),   # outside
            (4, 14, D, now - dt.timedelta(minutes=30))]                       # too fresh
    assert garmin_deletions.missing(ours, {12}, D - dt.timedelta(days=3), now) == [1]


def test_illness_days_never_break_streaks():
    runs = [D, D + dt.timedelta(days=1), D + dt.timedelta(days=5)]
    ill = rules.neutral_days([(D + dt.timedelta(days=2), D + dt.timedelta(days=4))])
    _, with_illness = achievements.run_streak(runs, D + dt.timedelta(days=5), ill)
    _, without = achievements.run_streak(runs, D + dt.timedelta(days=5))
    assert with_illness == 3 and without == 1
    monday = D - dt.timedelta(days=D.weekday())
    weeks = [monday, monday + dt.timedelta(days=1), monday + dt.timedelta(days=14),
             monday + dt.timedelta(days=15)]
    sick = rules.neutral_days([(monday + dt.timedelta(days=8), monday + dt.timedelta(days=9))])
    _, current = achievements.consistent_weeks(weeks, monday + dt.timedelta(days=16), sick)
    assert current == 2
    _, broken = achievements.consistent_weeks(weeks, monday + dt.timedelta(days=16))
    assert broken == 1
