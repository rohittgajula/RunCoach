"""Diet targets, run fueling and energy balance."""

import datetime as dt

import pytest

from nutrition.balance import summarise
from nutrition.fueling import fueling_for
from nutrition.targets import DayWorkout, Profile, bmr, day_targets, goal_adjustment

ROHIT = Profile(weight_kg=70, height_cm=175, age=30, sex="male")
LOSING = Profile(weight_kg=70, height_cm=175, age=30, sex="male", goal="lose", rate_kg_per_week=0.5)


def easy(minutes):
    return DayWorkout(kind="EASY", duration_s=minutes * 60, run_s=minutes * 60)


# --- BMR -----------------------------------------------------------------------

def test_mifflin_st_jeor():
    assert bmr(70, 175, 30, "male") == pytest.approx(10 * 70 + 6.25 * 175 - 150 + 5)
    assert bmr(70, 175, 30, "female") == pytest.approx(10 * 70 + 6.25 * 175 - 150 - 161)
    assert bmr(70, 175, 30, None) == pytest.approx(10 * 70 + 6.25 * 175 - 150 - 78)


def test_bmr_falls_back_to_22_per_kg():
    assert bmr(70, None, 30, "male") == 22 * 70
    assert bmr(70, 175, None, "male") == 22 * 70


def test_missing_profile_is_reported():
    t = day_targets(Profile(weight_kg=None), [])
    assert set(t.missing) == {"weight_kg", "height_cm", "sex", "date_of_birth"}


# --- carbs -----------------------------------------------------------------------

@pytest.mark.parametrize("workouts,g", [
    ([], 3), ([easy(40)], 4), ([easy(45)], 4), ([easy(50)], 5),
    ([DayWorkout("LONG", 60 * 60, run_s=3600)], 6),
    ([DayWorkout("TEMPO", 40 * 60, run_s=2400)], 6),
    ([DayWorkout("INTERVALS", 40 * 60, run_s=2400)], 6),
    ([DayWorkout("LONG", 95 * 60, run_s=95 * 60)], 7),
    ([DayWorkout("RACE", 60 * 60, run_s=3600)], 8),
])
def test_carb_bands(workouts, g):
    t = day_targets(ROHIT, workouts)
    assert t.carbs_g_per_kg == g
    assert t.carbs_g == round(g * 70)


def test_protein_higher_when_losing():
    assert day_targets(ROHIT, []).protein_g == round(1.6 * 70)
    assert day_targets(LOSING, []).protein_g == round(1.8 * 70)


# --- goal adjustment and the safety rule ------------------------------------------

def test_goal_adjustment_caps():
    assert goal_adjustment("lose", 0.25) == pytest.approx(-275)
    assert goal_adjustment("lose", 0.5) == -500
    assert goal_adjustment("lose", 0.75) == -500
    assert goal_adjustment("gain", 0.75) == 400
    assert goal_adjustment("maintain", 0.75) == 0
    assert goal_adjustment("lose", 5) == -500          # rate clamped too


def test_deficit_applies_on_an_easy_day():
    t = day_targets(LOSING, [easy(30)])
    assert t.goal_adjustment == -500
    assert "weight loss" in t.rationale


@pytest.mark.parametrize("kind", ["LONG", "INTERVALS", "TEMPO", "RACE"])
def test_no_deficit_on_long_or_hard_day(kind):
    t = day_targets(LOSING, [DayWorkout(kind, 50 * 60, run_s=50 * 60)])
    assert t.goal_adjustment == 0
    assert "no deficit" in t.rationale


def test_no_deficit_the_day_after_a_long_run():
    t = day_targets(LOSING, [], day_after_long=True)
    assert t.goal_adjustment == 0
    assert "recovering" in t.rationale


def test_rule_never_touches_a_surplus():
    gaining = Profile(weight_kg=70, height_cm=175, age=30, sex="male", goal="gain", rate_kg_per_week=0.25)
    t = day_targets(gaining, [DayWorkout("LONG", 3600, run_s=3600)], day_after_long=True)
    assert t.goal_adjustment == round(0.25 * 7700 / 7)


def test_fat_floor_raises_total_rather_than_cutting_fat():
    # A small, losing athlete on a race day: carbs 8 g/kg would squeeze fat below floor.
    tiny = Profile(weight_kg=45, height_cm=150, age=60, sex="female", goal="lose", rate_kg_per_week=0.75)
    t = day_targets(tiny, [DayWorkout("RACE", 20 * 60, run_s=1200)])
    assert t.fat_g >= round(0.8 * 45)
    assert t.kcal == pytest.approx(4 * t.carbs_g + 4 * t.protein_g + 9 * t.fat_g, abs=15)
    assert "floor" in t.rationale


def test_exercise_from_garmin_beats_planned():
    t = day_targets(ROHIT, [easy(30)], completed_kcal=412)
    assert t.exercise == 412 and t.exercise_source == "garmin"
    planned = day_targets(ROHIT, [DayWorkout("EASY", 1800, run_s=1800, run_pace_s_per_km=360)])
    assert planned.exercise_source == "planned"
    assert planned.exercise == round(1.0 * 70 * 5)     # 5 km at 6:00/km
    assert day_targets(ROHIT, []).exercise_source == "none"


def test_water():
    assert day_targets(ROHIT, []).water_ml == 2450
    assert day_targets(ROHIT, [easy(60)]).water_ml == 3050


# --- fueling ------------------------------------------------------------------------

def test_short_easy_run_needs_little():
    f = fueling_for("EASY", 30 * 60, 70)
    assert f.before.startswith("Optional")
    assert "Water only" in f.during and f.carbs_g_during_per_h is None
    assert "normal meal" in f.after
    assert "300–500 ml" in f.before


def test_long_run_bands():
    assert fueling_for("LONG", 60 * 60, 70).carbs_g_during_per_h == 30
    assert fueling_for("LONG", 90 * 60, 70).carbs_g_during_per_h == 30
    long = fueling_for("LONG", 100 * 60, 70)
    assert long.carbs_g_during_per_h == 45 and "sodium" in long.during
    assert "70–105 g carbs" in long.before
    assert "20–30 g protein" in long.after and "70 g carbs" in long.after


def test_early_morning_before():
    f = fueling_for("LONG", 70 * 60, 70, start_hour=6)
    assert f.before.startswith("Early start: 30 g carbs")
    assert "2–3 h" not in f.before


def test_hard_short_session_still_gets_full_before_and_recovery():
    f = fueling_for("INTERVALS", 40 * 60, 60)
    assert not f.before.startswith("Optional")
    assert "protein" in f.after


# --- balance ------------------------------------------------------------------------

END = dt.date(2026, 3, 10)


def days_back(n):
    return [END - dt.timedelta(days=i) for i in range(n)]


def test_balance_needs_five_logged_days():
    intake = {d: 2000 for d in days_back(4)}
    targets = {d: 2300 for d in days_back(7)}
    b = summarise(intake, targets, [], END)
    assert b.avg_balance_kcal is None and b.logged_days_last_7 == 4
    assert "Log more days" in b.message


def test_balance_predicted_and_actual():
    intake = {d: 2000 for d in days_back(6)}
    targets = {d: 2300 for d in days_back(7)}
    weights = [(END - dt.timedelta(days=6), 72.0), (END, 71.7)]
    b = summarise(intake, targets, weights, END)
    assert b.avg_balance_kcal == -300
    assert b.predicted_kg_per_week == pytest.approx(-300 * 7 / 7700, abs=0.01)
    assert b.actual_kg_per_week == pytest.approx(-0.35, abs=0.01)


def test_balance_without_weights_has_no_actual():
    intake = {d: 2500 for d in days_back(7)}
    targets = {d: 2300 for d in days_back(7)}
    b = summarise(intake, targets, [(END, 70.0)], END)
    assert b.avg_balance_kcal == 200 and b.actual_kg_per_week is None
