"""R26 §2: the weekly mirror — planned vs done, and what it refuses to claim.

The failure this file guards against is not a wrong number. It is a discouraging
one: a mirror that reads three unlogged days as three days of eating nothing shows
a 40% calorie shortfall that never happened, and the only thing that teaches is to
stop opening the screen.

So the tests that matter here are the ones about absence — no plan, no log, a week
that has not finished yet — and about the rows where going over is not a failure.
"""

from __future__ import annotations

import datetime as dt

import pytest

from analysis import mirror

from .r7_helpers import active_plan, make_workout


def with_body(athlete):
    """A calorie target needs these. Without them the food rows report a missing
    profile instead of a comparison, which is its own test below."""
    athlete.weight_kg = 70.0
    athlete.height_cm = 175
    athlete.sex = "male"
    athlete.date_of_birth = dt.date(1999, 1, 1)
    athlete.save()
    return athlete


def log_food(athlete, monday, days, *, kcal=2000, protein_g=100):
    """One meal per day for `days` days from `monday`.

    Two things about Meal that a test has to respect: `local_date` is recomputed
    from `eaten_at` on every save, and the macros are recomputed from `items` — so
    passing kcal= straight to create() is silently thrown away. Both are right for
    the model and both will quietly void a test that ignores them.
    """
    from zoneinfo import ZoneInfo

    from apps.diet.models import Meal

    zone = ZoneInfo(athlete.timezone or "UTC")
    for i in range(days):
        day = monday + dt.timedelta(days=i)
        Meal.objects.create(
            athlete=athlete,
            eaten_at=dt.datetime.combine(day, dt.time(12, 0), tzinfo=zone),
            meal_type="lunch",
            items=[{"name": "test meal", "quantity": "1", "kcal": kcal,
                    "protein_g": protein_g, "carbs_g": 250, "fat_g": 60}],
        )


def past_monday(athlete, weeks=2):
    return athlete.local_today - dt.timedelta(days=athlete.local_today.weekday() + 7 * weeks)


def row(**kw):
    base = dict(key="kcal", label="Calories", planned=2400, done=2400, unit="kcal", days=7)
    return mirror.Row(**{**base, **kw})


# --- absence is not failure ---------------------------------------------------

def test_nothing_planned_is_not_a_miss():
    out = mirror.assess(row(planned=None, done=None))
    assert out.status == "nothing_planned"
    assert out.note == "Nothing planned."
    assert out.gap is None and out.pct is None


def test_nothing_logged_is_not_a_zero():
    """The whole point. Not logging dinner is not eating nothing."""
    out = mirror.assess(row(done=None, days=0))
    assert out.status == "not_enough_data"
    assert out.note == "Nothing logged."
    assert out.pct is None


def test_too_few_logged_days_shows_no_number_and_says_why():
    out = mirror.assess(row(done=1800, days=2))
    assert out.status == "not_enough_data"
    assert "2 of 7 days logged" in out.note
    assert out.pct is None


def test_enough_days_is_judged():
    out = mirror.assess(row(done=1800, days=mirror.MIN_DAYS))
    assert out.status == "under" and out.pct == 75


def test_an_unjudgeable_row_never_counts_against_him():
    out = mirror.build([row(key="runs", planned=None, done=None),
                        row(key="kcal", done=None, days=0),
                        row(key="protein", planned=120, done=118, days=7)])
    assert out.judged == 1 and out.missed == 0
    assert out.headline == "All 1 on target."


def test_a_week_with_nothing_in_it_says_so_rather_than_scoring_zero():
    out = mirror.build([row(key="runs", planned=None, done=None),
                        row(key="kcal", planned=None, done=None)])
    assert out.judged == 0 and out.missed == 0
    assert "Not enough logged" in out.headline


# --- the band around the target ----------------------------------------------

@pytest.mark.parametrize(
    ("done", "status"),
    [(2400, "hit"), (2300, "hit"), (2500, "hit"), (2100, "under"), (2800, "over")],
)
def test_close_enough_counts_as_hitting_it(done, status):
    """A mirror that calls 2380 against 2400 a miss trains him to ignore it."""
    assert mirror.assess(row(done=done, bad="both")).status == status


def test_the_percentage_is_of_the_target():
    assert mirror.assess(row(done=1200, bad="both")).pct == 50


# --- direction matters per row -----------------------------------------------

def test_sleeping_more_than_needed_is_not_a_miss():
    out = mirror.assess(row(key="sleep", label="Sleep", planned=8.0, done=9.5,
                            unit="h", bad="under"))
    assert out.status == "hit"
    assert "which is fine" in out.note


def test_sleeping_less_than_needed_is():
    out = mirror.assess(row(key="sleep", label="Sleep", planned=8.0, done=6.0,
                            unit="h", bad="under"))
    assert out.status == "under" and "short" in out.note


def test_eating_over_target_is_a_miss_because_calories_cut_both_ways():
    out = mirror.assess(row(done=3200, bad="both"))
    assert out.status == "over" and "over" in out.note


def test_a_row_with_no_bad_direction_is_never_a_miss():
    for done in (1000, 4000):
        assert mirror.assess(row(done=done, bad="neither")).status == "hit"


def test_protein_over_target_is_fine_but_under_is_not():
    over = mirror.assess(row(key="protein", planned=120, done=160, unit="g", bad="under"))
    under = mirror.assess(row(key="protein", planned=120, done=80, unit="g", bad="under"))
    assert over.status == "hit" and under.status == "under"


# --- the summary -------------------------------------------------------------

def test_the_headline_counts_rather_than_praises():
    out = mirror.build([
        row(key="runs", planned=5, done=5, unit="runs"),
        row(key="kcal", done=1500, bad="both"),
        row(key="protein", planned=120, done=60, unit="g"),
    ])
    assert out.headline == "1 of 3 on target."
    assert out.missed == 2


def test_the_worst_row_is_the_one_furthest_from_target():
    out = mirror.build([
        row(key="kcal", done=2000, bad="both"),          # 83%
        row(key="protein", planned=120, done=40, unit="g"),  # 33%
    ])
    assert out.worst == "protein"


def test_a_clean_week_has_no_worst_row():
    out = mirror.build([row(key="kcal", done=2400, bad="both")])
    assert out.worst is None and out.missed == 0


def test_rows_come_back_in_a_fixed_order_whatever_order_they_arrive_in():
    out = mirror.build([row(key="water", planned=3000, done=3000, unit="ml"),
                        row(key="runs", planned=5, done=5, unit="runs"),
                        row(key="sleep", planned=8.0, done=8.0, unit="h")])
    assert [r.key for r in out.rows] == ["runs", "sleep", "water"]


def test_an_unknown_row_is_kept_rather_than_dropped():
    """A domain added later with no entry in ORDER must still appear, or the mirror
    silently stops mirroring it."""
    out = mirror.build([row(key="runs", planned=5, done=5, unit="runs"),
                        row(key="something_new", planned=10, done=10, unit="x")])
    assert "something_new" in [r.key for r in out.rows]


# --- the endpoint ------------------------------------------------------------

MIRROR = "/api/health/mirror/"


def test_an_empty_week_is_honest(api, athlete):
    body = api.get(MIRROR).json()
    assert body["judged"] == 0
    assert "Not enough logged" in body["headline"]
    assert {r["key"] for r in body["rows"]} == {
        "runs", "run_time", "strength", "kcal", "protein", "sleep", "water"}
    assert all(r["planned"] is None for r in body["rows"])


def test_a_bad_week_parameter_is_a_400(api, athlete):
    assert api.get(f"{MIRROR}?week=not-a-date").status_code == 400


def test_the_week_starts_on_monday_whatever_day_is_asked_for(api, athlete):
    body = api.get(f"{MIRROR}?week=2026-11-26").json()   # a Thursday
    assert body["week_start"] == "2026-11-23"
    assert body["week_end"] == "2026-11-29"


def test_planned_runs_not_done_show_up_as_short(api, athlete):
    monday = athlete.local_today - dt.timedelta(days=athlete.local_today.weekday())
    active_plan(athlete)
    for i in range(3):
        make_workout(athlete, day=monday + dt.timedelta(days=i))
    body = api.get(MIRROR).json()
    runs = next(r for r in body["rows"] if r["key"] == "runs")
    assert runs["planned"] == 3
    assert runs["done"] == 0


def test_a_completed_run_counts(api, athlete):
    monday = athlete.local_today - dt.timedelta(days=athlete.local_today.weekday())
    make_workout(athlete, day=monday, status="completed")
    body = api.get(MIRROR).json()
    runs = next(r for r in body["rows"] if r["key"] == "runs")
    assert runs["planned"] == 1 and runs["done"] == 1
    assert runs["status"] == "hit"


def test_a_mid_week_mirror_is_not_marked_down_for_days_that_have_not_happened(api, athlete):
    """Asked on a Wednesday, Friday's planned run is not a missed one."""
    body = api.get(MIRROR).json()
    assert body["in_progress"] is True
    assert body["elapsed_days"] == athlete.local_today.weekday() + 1


def test_a_finished_week_is_not_in_progress(api, athlete):
    old = athlete.local_today - dt.timedelta(days=21)
    body = api.get(f"{MIRROR}?week={old}").json()
    assert body["in_progress"] is False
    assert body["elapsed_days"] == 7


def test_food_is_averaged_over_the_days_he_logged_not_all_seven(api, athlete):
    """Four logged days at target must read as on target, not as 4/7 of it.

    Uses a finished week rather than this one, so the test asserts the same thing
    whatever day it runs on — a current-week version asked on a Monday would have
    one logged day, fall under MIN_DAYS and quietly assert nothing.
    """
    with_body(athlete)
    monday = past_monday(athlete)
    log_food(athlete, monday, 4)
    body = api.get(f"{MIRROR}?week={monday}").json()
    kcal = next(r for r in body["rows"] if r["key"] == "kcal")
    assert kcal["days"] == 4 and kcal["of_days"] == 7
    assert kcal["done"] == 2000      # the average of the logged days, not of seven
    assert kcal["status"] in ("hit", "under", "over")


def test_three_logged_days_is_not_enough_to_judge_food(api, athlete):
    """One below MIN_DAYS: the row goes quiet rather than showing three days as
    though they were the week."""
    with_body(athlete)
    monday = past_monday(athlete)
    log_food(athlete, monday, 3)
    body = api.get(f"{MIRROR}?week={monday}").json()
    kcal = next(r for r in body["rows"] if r["key"] == "kcal")
    assert kcal["status"] == "not_enough_data"
    assert "3 of 7 days logged" in kcal["note"]


def test_an_incomplete_profile_names_the_field_instead_of_blaming_him(api, athlete):
    """Without his weight there is no calorie target. Saying "nothing planned"
    would read as his fault; the row says which Settings field is empty.

    This is not hypothetical — it is the state every account is in before the
    profile is filled, and the one a brand-new user sees first.
    """
    monday = past_monday(athlete)
    log_food(athlete, monday, 5)
    body = api.get(f"{MIRROR}?week={monday}").json()
    kcal = next(r for r in body["rows"] if r["key"] == "kcal")
    assert kcal["status"] == "no_target"
    assert "your weight" in kcal["note"] and "Settings" in kcal["note"]
    # And it must not be counted as a miss against him.
    assert body["missed"] == 0


def test_a_profile_gap_is_not_confused_with_nothing_planned(api, athlete):
    """Two different absences that used to produce the same word."""
    monday = past_monday(athlete)
    log_food(athlete, monday, 5)
    rows = {r["key"]: r for r in api.get(f"{MIRROR}?week={monday}").json()["rows"]}
    assert rows["kcal"]["status"] == "no_target"       # target cannot be computed
    assert rows["runs"]["status"] == "nothing_planned"  # genuinely nothing planned


# --- only the plan he is actually following ----------------------------------

def test_a_proposed_plan_is_not_counted_alongside_the_active_one(api, athlete):
    """Regenerating a plan leaves the old workouts on the same dates, and a pending
    proposal adds a second set. Counting both turned five planned runs into
    thirteen on real data — a number wrong enough to stop anyone trusting it."""
    from apps.planning.models import PlannedWorkout, TrainingPlan

    monday = athlete.local_today - dt.timedelta(days=athlete.local_today.weekday())
    live = active_plan(athlete)
    proposed = TrainingPlan.objects.create(athlete=athlete, name="Proposed",
                                           status="proposed", generator_version="g1")
    archived = TrainingPlan.objects.create(athlete=athlete, name="Old",
                                           status="archived", generator_version="g1")
    for plan in (live, proposed, archived):
        PlannedWorkout.objects.create(
            athlete=athlete, plan=plan, date=monday, title="Easy", kind="EASY",
            duration_s=1800, load=20.0, steps=[], status="planned",
        )
    runs = next(r for r in api.get(MIRROR).json()["rows"] if r["key"] == "runs")
    assert runs["planned"] == 1


def test_a_plan_row_is_judged_from_monday_rather_than_waiting_for_four_days(api, athlete):
    """MIN_DAYS is about days of logging. Applied to the plan it would blank the
    Runs row every Monday and Tuesday, when it is perfectly answerable."""
    monday = athlete.local_today - dt.timedelta(days=athlete.local_today.weekday())
    make_workout(athlete, day=monday, status="completed")
    runs = next(r for r in api.get(MIRROR).json()["rows"] if r["key"] == "runs")
    assert runs["status"] == "hit"
    assert runs["needs_days"] is False


def test_a_logged_row_still_waits_for_enough_days(api, athlete):
    with_body(athlete)
    monday = past_monday(athlete)
    log_food(athlete, monday, 2)
    kcal = next(r for r in api.get(f"{MIRROR}?week={monday}").json()["rows"]
                if r["key"] == "kcal")
    assert kcal["needs_days"] is True and kcal["status"] == "not_enough_data"
