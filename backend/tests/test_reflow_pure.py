"""planning.reflow: move a stored plan's future workouts onto new training days."""

import datetime as dt

import pytest

from planning.generator import Baseline, PlanConfig, generate_plan, run_day_limit
from planning.reflow import Item, reflow

MON = dt.date(2026, 10, 5)            # a Monday
SUN_BEFORE = MON - dt.timedelta(days=1)


def day(offset: int) -> dt.date:
    return MON + dt.timedelta(days=offset)


def item(pk, offset, kind="EASY", duration=1800, status="planned"):
    return Item(id=pk, date=day(offset), kind=kind, duration_s=duration, status=status)


def run(items, available, long_day=6, limit=5, today=SUN_BEFORE, last_date=None):
    return reflow(items, available=available, long_day=long_day, limit=limit, today=today,
                  last_date=last_date)


def applied(items, result):
    """The items after the result: dropped removed, moved re-dated."""
    return [Item(i.id, result.moves.get(i.id, i.date), i.kind, i.duration_s, i.status)
            for i in items if i.id not in result.drops]


def week_4():
    # Mon easy (short), Wed intervals, Fri easy, Sun long — a typical generated week.
    return [item(1, 0, "EASY", 1800), item(2, 2, "INTERVALS", 2400),
            item(3, 4, "EASY", 2000), item(4, 6, "LONG", 4000)]


def test_fewer_days_drops_the_shortest_easy_and_keeps_long_on_long_day():
    result = run(week_4(), available=[1, 3, 6])
    assert result.drops == [1]                       # the 30-min easy, not the 33-min one
    assert result.moves == {2: day(1), 3: day(3)}    # intervals Tue, easy Thu, long stays Sun


def test_nothing_is_lengthened_or_added():
    items = week_4()
    result = run(items, available=[1, 3, 6])
    after = applied(items, result)
    assert len(after) == len(items) - 1
    before = {i.id: i for i in items}
    assert all(i.duration_s == before[i.id].duration_s and i.kind == before[i.id].kind
               for i in after)


def test_long_hard_and_race_are_never_dropped():
    items = [item(1, 0, "EASY", 1500), item(2, 1, "TEMPO"), item(3, 3, "INTERVALS"),
             item(4, 4, "EASY", 1200), item(5, 6, "LONG", 4000)]
    result = run(items, available=[2, 6])
    assert sorted(result.drops) == [1, 4]
    after = {i.id: i.date for i in applied(items, result)}
    assert after[5] == day(6)                        # long on the long-run day
    assert {2, 3} <= set(after)                      # both hard sessions kept
    assert len(set(after.values())) == len(after)    # one run per day


def test_hard_sessions_are_not_put_next_to_each_other():
    # Order alone would give easy Mon, intervals Tue, tempo Wed.
    items = [item(1, 0, "EASY"), item(2, 2, "INTERVALS"), item(3, 3, "TEMPO"),
             item(4, 6, "LONG", 4000)]
    result = run(items, available=[0, 1, 2, 6])
    after = {i.id: i.date for i in applied(items, result)}
    assert abs((after[2] - after[3]).days) > 1
    assert after == {1: day(1), 2: day(0), 3: day(2), 4: day(6)}


def test_hard_session_avoids_the_day_before_the_long_run():
    items = [item(1, 0, "EASY"), item(2, 1, "TEMPO"), item(3, 6, "LONG", 4000)]
    result = run(items, available=[2, 5, 6])
    after = {i.id: i.date for i in applied(items, result)}
    assert after[3] == day(6) and after[2] == day(2) and after[1] == day(5)


def test_race_is_fixed_and_nothing_lands_on_or_after_it():
    race_day = day(5)
    items = [item(1, 0, "EASY"), item(2, 2, "EASY"), item(3, 5, "RACE", 3600)]
    result = run(items, available=[1, 3, 5, 6], last_date=race_day - dt.timedelta(days=1))
    assert 3 not in result.moves and 3 not in result.drops
    assert all(d < race_day for d in result.moves.values())
    assert result.moves == {1: day(1), 2: day(3)}


def test_today_past_and_completed_are_untouched():
    today = day(2)                                    # Wednesday
    items = [item(1, 0, "EASY", status="completed"), item(2, 1, "EASY"),  # Tue missed
             item(3, 2, "EASY"), item(4, 4, "TEMPO"), item(5, 6, "LONG", 4000)]
    result = run(items, available=[3, 5, 6], limit=4, today=today)
    assert set(result.moves) <= {4, 5} and not result.drops
    assert all(d > today for d in result.moves.values())
    assert result.moves == {4: day(3)}               # tempo Fri -> Thu; long stays Sun


def test_current_week_uses_only_future_days_and_fixed_runs_count_towards_the_limit():
    today = day(3)                                    # Thursday
    items = [item(1, 0, "EASY", status="completed"), item(2, 2, "EASY", status="completed"),
             item(3, 3, "EASY"),                      # today
             item(4, 4, "EASY", 1500), item(5, 6, "LONG", 4000),
             item(6, 7, "EASY"), item(7, 9, "TEMPO"), item(8, 13, "LONG", 4200)]
    result = run(items, available=[0, 2, 5, 6], limit=4, today=today)
    # This week: 3 runs already used, one slot left (Sun) -> the long run stays, Fri easy
    # is dropped rather than squeezed onto Saturday next to it.
    assert result.drops == [4]
    assert 5 not in result.moves
    assert all(d > today for d in result.moves.values())
    # Next week (Mon, Wed, Sun) already fits the new days.
    assert not set(result.moves) & {6, 7, 8}


def test_same_days_is_a_noop_and_reflow_is_idempotent():
    items = week_4()
    assert run(items, available=[0, 2, 4, 6]).moves == {}
    result = run(items, available=[1, 3, 6])
    again = run(applied(items, result), available=[1, 3, 6])
    assert again.moves == {} and again.drops == []


@pytest.mark.parametrize("days,long_day", [([0, 2, 4, 6], 6), ([1, 3, 5], 5),
                                           ([0, 1, 2, 3, 4, 5, 6], 5)])
def test_a_generated_plan_with_its_own_days_does_not_move(days, long_day):
    available = {str(d): d in days for d in range(7)}
    baseline = Baseline(run_km_per_week=20, longest_run_s=3600, run_pace_s_per_km=360,
                        walk_pace_s_per_km=600, available_days=available, long_run_day=long_day)
    start = dt.date(2026, 10, 8)                     # a Thursday: weeks are not ISO weeks
    plan = generate_plan(start, start + dt.timedelta(weeks=12), 10.0, baseline, PlanConfig())
    items, pk = [], 0
    for week in plan.weeks:
        for s in week.sessions:
            if not s.optional:
                pk += 1
                items.append(Item(pk, s.date, s.kind, int(s.run_minutes * 60)))
    limit = run_day_limit(20, PlanConfig())
    result = reflow(items, available=days, long_day=long_day, limit=limit,
                    today=start - dt.timedelta(days=1),
                    last_date=start + dt.timedelta(weeks=12) - dt.timedelta(days=1))
    assert result.moves == {} and result.drops == []


def test_adding_a_day_moves_nothing():
    assert run(week_4(), available=[0, 1, 2, 3, 4, 6]).moves == {}


def test_more_days_than_runs_spreads_without_adding():
    items = week_4()
    result = run(items, available=[1, 2, 3, 4, 5, 6])     # Monday removed
    after = applied(items, result)
    assert not result.drops and len(after) == 4
    dates = [i.date for i in after]
    assert len(set(dates)) == 4 and all(d.weekday() in {1, 2, 3, 4, 5, 6} for d in dates)
    assert {i.id: i.date for i in after}[4] == day(6)


def test_long_day_changed_only():
    items = week_4()
    result = run(items, available=[0, 2, 4, 6], long_day=4)
    assert not result.drops
    after = {i.id: i.date for i in applied(items, result)}
    assert after[4] == day(4)                             # long run now Friday
    assert sorted(after.values()) == [day(0), day(2), day(4), day(6)]


def test_walks_make_way_for_runs_and_are_dropped_when_no_day_is_free():
    items = [item(1, 0, "EASY"), item(2, 1, "WALK", 1500), item(3, 6, "LONG", 4000)]
    result = run(items, available=[1, 6])
    after = {i.id: i.date for i in applied(items, result)}
    assert after[1] == day(1) and after[3] == day(6)
    assert after[2] not in (day(1), day(6))              # walk moved off the run day
    full = [item(10 + d, d, "EASY") for d in range(6)] + [item(20, 6, "WALK")]
    result = run(full, available=[0, 1, 2, 3, 4, 5], long_day=5, limit=6)
    assert result.moves == {} and result.drops == []


def test_no_available_future_day_keeps_undroppable_sessions_in_place():
    today = day(4)                                        # Friday
    items = [item(1, 5, "TEMPO"), item(2, 6, "LONG", 4000)]
    result = run(items, available=[0, 2], long_day=2, today=today)
    assert not result.drops and result.moves == {}
