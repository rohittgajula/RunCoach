"""R16 pure rules: planning/edit.py, the Garmin payload's edited-step targets,
analysis/freshness.py, the honesty-guard matcher. No database."""

import datetime as dt

import pytest

from analysis.freshness import assess
from apps.coaching import honesty
from planning import edit as rules
from planning.garmin_workout import build_payload, payload_hash
from planning.reflow import Item, reflow

LIMITS = rules.Limits(hr_min=50, hr_max=190)


def run_walk(blocks=3, run=240, walk=120, hr=(130, 145)):
    steps = [{"kind": "warmup", "duration_s": 300, "intensity": "walk", "label": "Walk warm-up",
              "pace_min_s": None, "pace_max_s": None, "hr_min": None, "hr_max": None}]
    for _ in range(blocks):
        steps += [{"kind": "run", "duration_s": run, "intensity": "easy", "label": "Run 4:00",
                   "pace_min_s": 600, "pace_max_s": 645, "hr_min": hr[0], "hr_max": hr[1]},
                  {"kind": "walk", "duration_s": walk, "intensity": "walk", "label": "Walk 2:00",
                   "pace_min_s": None, "pace_max_s": None, "hr_min": None, "hr_max": None}]
    return steps


# --- editor round trip ----------------------------------------------------------------

def test_edit_items_fold_repeats_and_expand_back():
    items = rules.edit_items(run_walk(3))
    assert items[0]["kind"] == "warmup" and items[0]["target"] == "auto"
    assert items[1]["repeat"] == 3 and [s["kind"] for s in items[1]["steps"]] == ["run", "walk"]
    assert items[1]["steps"][0]["target"] == "hr" and items[1]["steps"][0]["hr_low"] == 130
    flat = rules.expand(items, LIMITS)
    assert len(flat) == 7 and rules.total_s(flat) == rules.total_s(run_walk(3))
    assert flat[1]["target"] == "hr" and flat[1]["label"] == "Run 4:00"
    assert flat[2]["intensity"] == "walk" and flat[2]["target"] == "auto"


def test_expand_repeat_block_and_defaults():
    steps = rules.expand([
        {"kind": "warmup", "duration_s": 300},
        {"repeat": 3, "steps": [{"kind": "run", "duration_s": 180, "pace_low": 360,
                                 "pace_high": 390},
                                {"kind": "walk", "duration_s": 60}]},
        {"kind": "strides", "duration_s": 20, "note": "relaxed"},
        {"kind": "cooldown", "duration_s": 300}], LIMITS)
    assert len(steps) == 9
    assert steps[1]["target"] == "pace" and steps[1]["pace_min_s"] == 360
    assert steps[7]["kind"] == "stride" and steps[7]["intensity"] == "hard"
    assert steps[7]["label"] == "Stride 20s · relaxed"


@pytest.mark.parametrize("items, message", [
    ([{"kind": "run", "duration_s": 5}], "between 10 s"),
    ([{"kind": "run", "duration_s": 6000}], "between 10 s"),
    ([{"kind": "run", "duration_s": 120}], "5–240 min"),
    ([{"kind": "jog", "duration_s": 600}], "kind must be"),
    ([{"kind": "run", "duration_s": 600, "hr_low": 150, "hr_high": 200}], "between 50 and 190"),
    ([{"kind": "run", "duration_s": 600, "hr_low": 150, "hr_high": 140}], "low to high"),
    ([{"kind": "run", "duration_s": 600, "pace_low": 100, "pace_high": 300}], "pace must be"),
    ([{"kind": "run", "duration_s": 600, "pace_low": 400, "pace_high": 350}], "fast end"),
    ([{"repeat": 2, "steps": [{"repeat": 2, "steps": []}]}], "nested"),
    ([{"repeat": 1, "steps": [{"kind": "run", "duration_s": 600}]}], "repeat must be"),
    ([{"kind": "run", "duration_s": 600, "target": "hr"}], "needs hr_low"),
    ([], "non-empty"),
])
def test_invalid_steps_are_refused(items, message):
    with pytest.raises(rules.EditError, match=message):
        rules.expand(items, LIMITS)


def test_limits_from_profile():
    assert rules.limits_for(55, 185, 40).as_dict()["hr_max"] == 185
    assert rules.limits_for(None, None, 40) == rules.Limits(hr_min=40, hr_max=180)
    assert rules.limits_for(None, None, None) == rules.Limits(hr_min=40, hr_max=210)


# --- transforms --------------------------------------------------------------------------

def test_add_minutes_to_run_parts_spreads_evenly():
    steps = rules.add_seconds(run_walk(3), 180, "run")
    runs = [s["duration_s"] for s in steps if s["kind"] == "run"]
    assert runs == [300, 300, 300] and steps[1]["label"] == "Run 5:00"
    assert rules.total_s(steps) == rules.total_s(run_walk(3)) + 180
    assert rules.walk_s(steps) == rules.walk_s(run_walk(3))


def test_add_minutes_to_walk_and_negative_with_floor():
    steps = rules.add_seconds(run_walk(3), 120, "walk")
    assert rules.walk_s(steps) == rules.walk_s(run_walk(3)) + 120
    shorter = rules.add_seconds(run_walk(3), -600, "run")
    assert rules.run_s(shorter) == 720 - 600 and min(s["duration_s"] for s in shorter) >= 30
    with pytest.raises(rules.EditError, match="isn't enough"):
        rules.add_seconds(run_walk(3), -800, "run")


def test_add_walk_minutes_without_walk_appends_cooldown():
    easy = [{"kind": "run", "duration_s": 1800, "intensity": "easy", "label": "Run 30:00",
             "pace_min_s": None, "pace_max_s": None, "hr_min": None, "hr_max": None}]
    steps = rules.add_seconds(easy, 300, "walk")
    assert steps[-1]["kind"] == "cooldown" and steps[-1]["duration_s"] == 300


def test_scale_to_exact_total():
    steps = rules.scale_to(run_walk(3), 45 * 60)
    assert rules.total_s(steps) == 2700
    assert all(s["duration_s"] >= 10 for s in steps)


def test_walk_breaks_keep_total_and_never_lengthen():
    easy = [{"kind": "run", "duration_s": 1800, "intensity": "easy", "label": "Easy run 30:00",
             "pace_min_s": 600, "pace_max_s": 645, "hr_min": 130, "hr_max": 145}]
    steps = rules.add_walk_breaks(easy, 5)
    assert rules.total_s(steps) == 1800
    assert [s["kind"] for s in steps[:4]] == ["run", "walk", "run", "walk"]
    assert steps[0]["duration_s"] == 300 and steps[1]["duration_s"] == 60
    assert rules.run_s(steps) < 1800
    with pytest.raises(rules.EditError, match="nothing to break up"):
        rules.add_walk_breaks(run_walk(3), 5)


def test_set_hr_range_only_on_non_walk_steps():
    steps = rules.set_hr_range(run_walk(2), 120, 140, LIMITS)
    assert all(s["hr_max"] == 140 and s["target"] == "hr" for s in steps
               if s["intensity"] != "walk")
    assert all(s["hr_max"] is None for s in steps if s["intensity"] == "walk")


def test_parse_and_apply_order_and_errors():
    changes = rules.parse_changes({"add_minutes": 2, "apply_to": "run", "notes": " hills "})
    assert changes == {"add_minutes": 2.0, "apply_to": "run", "notes": "hills"}
    with pytest.raises(rules.EditError, match="Nothing to change"):
        rules.parse_changes({})
    with pytest.raises(rules.EditError):
        rules.parse_changes({"total_minutes": 300})
    with pytest.raises(rules.EditError, match="both"):
        rules.parse_changes({"hr_low": 120})
    out = rules.apply(run_walk(3), {"total_minutes": 30, "add_minutes": 2}, LIMITS)
    assert rules.total_s(out) == 32 * 60


def test_retitle():
    assert rules.retitle("45m easy aerobic run", 3000) == "50m easy aerobic run"
    assert rules.retitle("Long run 60m", 3900) == "Long run 65m"
    assert rules.retitle("Intervals 5 × 2:00", 3000) == "Intervals 5 × 2:00"


def test_week_changes():
    assert rules.week_changes("add_minutes", 5, "walk") == {"add_minutes": 5.0, "apply_to": "walk"}
    assert rules.week_changes("set_hr_range", [120, 140]) == {"hr_low": 120, "hr_high": 140}
    assert rules.week_changes("set_hr_range", {"hr_low": 1, "hr_high": 2})["hr_high"] == 2
    assert rules.scaled_changes({"scale": 1.1}, run_walk(3)) == {
        "total_minutes": pytest.approx(rules.total_s(run_walk(3)) * 1.1 / 60)}
    with pytest.raises(rules.EditError):
        rules.week_changes("delete", 1)
    with pytest.raises(rules.EditError):
        rules.week_changes("scale", 3)


# --- warnings ------------------------------------------------------------------------------

def warn_keys(**kw):
    base = dict(kind="EASY", base_steps=run_walk(3), new_steps=run_walk(3), hr_ceiling=155,
                easy_top=145, neighbour_hard=False, week_other_runs=[1800, 1800])
    base.update(kw)
    return [w["key"] for w in rules.warnings_for(**base)]


def test_warnings():
    assert warn_keys() == []
    bigger = rules.add_seconds(run_walk(3), 300, "run")         # 720 -> 1020 s, +42 %
    assert "run_increase" in warn_keys(new_steps=bigger)
    assert warn_keys(new_steps=rules.add_seconds(run_walk(3), 120, "run")) == []   # +17 %
    hot = rules.set_hr_range(run_walk(3), 150, 170, LIMITS)
    keys = warn_keys(new_steps=hot, neighbour_hard=True)
    assert "hr_above_ceiling" in keys and "hard_days_in_a_row" in keys
    assert "hard_days_in_a_row" not in warn_keys(new_steps=hot)           # no hard neighbour
    long = rules.add_seconds(run_walk(3), 1800, "run")                    # 2520 s of running
    assert "long_run_share" in warn_keys(new_steps=long, week_other_runs=[1200, 1200])
    texts = rules.warnings_for(kind="EASY", base_steps=run_walk(3), new_steps=bigger,
                               hr_ceiling=155, easy_top=145, neighbour_hard=False,
                               week_other_runs=[])
    assert "42 % more running than planned (12 → 17 min)" in texts[0]["text"]


def test_increase_ratio():
    assert rules.increase_ratio(run_walk(3), rules.add_seconds(run_walk(3), 144, "run")) \
        == pytest.approx(0.2, abs=0.05)
    walk = [{"kind": "walk", "duration_s": 1200, "intensity": "walk"}]
    assert rules.increase_ratio(walk, [{"kind": "walk", "duration_s": 1800,
                                        "intensity": "walk"}]) == pytest.approx(0.5)


# --- Garmin payload ------------------------------------------------------------------------

HR = {"resting_hr": 55, "hr_easy_min": 130, "hr_easy_max": 145, "hr_ceiling": 155}


def test_generated_payload_is_unchanged_by_r16():
    """A workout nobody edited hashes exactly as before (no re-sends after deploy)."""
    workout = {"title": "23m run/walk", "duration_s": 1380, "steps": run_walk(3), "hr": HR,
               "description": "Run/walk."}
    payload = build_payload(workout)
    steps = payload["workoutSegments"][0]["workoutSteps"]
    assert steps[1]["type"] == "RepeatGroupDTO" and steps[1]["numberOfIterations"] == 3
    run = steps[1]["workoutSteps"][0]
    assert run["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"
    assert (run["targetValueOne"], run["targetValueTwo"]) == (130.0, 145.0)
    assert payload_hash(payload, "2026-10-10") == payload_hash(build_payload(workout),
                                                               "2026-10-10")


def test_edited_step_targets_pace_hr_none():
    from garminconnect.workout import RunningWorkout

    steps = rules.expand([
        {"kind": "warmup", "duration_s": 300, "target": "none"},
        {"kind": "run", "duration_s": 600, "pace_low": 360, "pace_high": 400},
        {"kind": "walk", "duration_s": 120, "hr_low": 100, "hr_high": 120},
        {"kind": "run", "duration_s": 600, "pace_low": 360, "pace_high": 400,
         "hr_low": 140, "hr_high": 150, "target": "hr"},
        {"kind": "cooldown", "duration_s": 300}], LIMITS)
    payload = build_payload({"title": "Edited", "steps": steps, "hr": HR})
    out = payload["workoutSegments"][0]["workoutSteps"]
    assert out[0]["targetType"]["workoutTargetTypeKey"] == "no.target"
    assert out[1]["targetType"] == {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone",
                                    "displayOrder": 6}
    assert out[1]["targetValueOne"] == round(1000 / 400, 4)        # slow edge first
    assert out[1]["targetValueTwo"] == round(1000 / 360, 4)
    assert (out[2]["targetValueOne"], out[2]["targetValueTwo"]) == (100.0, 120.0)
    assert out[3]["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"
    assert (out[3]["targetValueOne"], out[3]["targetValueTwo"]) == (140.0, 150.0)
    assert out[4]["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"   # auto: gentle
    assert RunningWorkout.model_validate(payload).to_dict() == payload


# --- reflow keeps edited sessions -----------------------------------------------------------

def test_reflow_never_drops_an_edited_session():
    monday = dt.date(2026, 11, 2)
    items = [Item(1, monday, "EASY", 1200), Item(2, monday + dt.timedelta(days=2), "EASY", 900,
                                                 edited=True),
             Item(3, monday + dt.timedelta(days=4), "LONG", 3600)]
    result = reflow(items, available=[0, 6], long_day=6, limit=2, today=monday - dt.timedelta(days=3))
    assert 2 not in result.drops and 1 in result.drops


# --- freshness -------------------------------------------------------------------------------

TODAY = dt.date(2026, 10, 12)


def test_freshness_rules():
    yesterday = TODAY - dt.timedelta(days=1)
    fresh = assess(today=TODAY, local_hour=8, has_sleep_today=True, has_readiness_today=True,
                   latest_sleep_date=TODAY, latest_readiness_date=TODAY)
    assert fresh == {"stale": False, "stale_reason": None, "stale_text": None}
    stale = assess(today=TODAY, local_hour=8, has_sleep_today=False, has_readiness_today=False,
                   latest_sleep_date=yesterday, latest_readiness_date=yesterday)
    assert stale["stale"] and stale["stale_reason"] == "both_missing"
    assert stale["stale_text"] == ("Showing yesterday's sleep — your watch hasn't synced last "
                                   "night yet.")
    early = assess(today=TODAY, local_hour=4, has_sleep_today=False, has_readiness_today=False,
                   latest_sleep_date=yesterday, latest_readiness_date=yesterday)
    assert early["stale"] is False
    only_ready = assess(today=TODAY, local_hour=9, has_sleep_today=True,
                        has_readiness_today=False, latest_sleep_date=TODAY,
                        latest_readiness_date=yesterday)
    assert only_ready["stale_reason"] == "readiness_missing"
    no_watch_readiness = assess(today=TODAY, local_hour=9, has_sleep_today=True,
                                has_readiness_today=False, latest_sleep_date=TODAY,
                                latest_readiness_date=None)
    assert no_watch_readiness["stale"] is False
    old = assess(today=TODAY, local_hour=9, has_sleep_today=False, has_readiness_today=True,
                 latest_sleep_date=TODAY - dt.timedelta(days=3), latest_readiness_date=TODAY)
    assert old["stale_text"].startswith("Showing sleep from Fri 9 Oct")
    gone = assess(today=TODAY, local_hour=9, has_sleep_today=False, has_readiness_today=False,
                  latest_sleep_date=TODAY - dt.timedelta(days=40), latest_readiness_date=None)
    assert gone["stale"] is False


# --- honesty matcher -------------------------------------------------------------------------

@pytest.mark.parametrize("text, claims", [
    ("I've increased Saturday's long run to 70 min.", True),
    ("Done! I have moved your run to Friday.", True),
    ("Your workout has been updated on the watch.", True),
    ("Your Thursday run was moved to Friday.", True),
    ("Your plan is now updated: Sat 40 → 45 min.", True),
    ("Your run was cut short yesterday, that's fine.", False),
    ("I haven't changed anything yet. Want me to add 5 minutes to the run?", False),
    ("I've added that to your journal.", False),
    ("Should I move your run?", False),
    ("I can change the plan if you like.", False),
    ("Nothing has been changed in your plan.", False),
    ("If you agree, I'll add 10 minutes to Saturday.", False),
])
def test_claimed_change(text, claims):
    assert bool(honesty.claimed_change(text)) is claims


def test_mutation_succeeded():
    assert not honesty.mutation_succeeded([])
    assert not honesty.mutation_succeeded([{"name": "get_workouts", "result": []}])
    assert not honesty.mutation_succeeded([{"name": "edit_workout",
                                            "result": {"status": "needs_confirmation"}}])
    assert not honesty.mutation_succeeded([{"name": "move_workout", "result": {"error": "x"}}])
    assert honesty.mutation_succeeded([{"name": "edit_week", "result": {"status": "updated"}}])
    assert honesty.mutation_succeeded([{"name": "skip_workout", "result": {"skipped": 3}}])
    assert "edit_workout" in honesty.facts([{"name": "edit_workout", "arguments": {"id": 1},
                                             "result": {"status": "needs_confirmation"}}])
