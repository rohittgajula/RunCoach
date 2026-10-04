"""Fitness / Fatigue / Form and the training-status bands."""

import datetime as dt

import pytest

from analysis.fitness import daily_loads, history_days, series, status

D0 = dt.date(2026, 1, 1)


def test_daily_loads_sums_per_day_and_treats_missing_as_zero():
    loads = daily_loads([(D0, 50), (D0, 30), (D0 + dt.timedelta(days=1), None)])
    assert loads == {D0: 80.0, D0 + dt.timedelta(days=1): 0.0}


def test_constant_load_converges_and_fatigue_reacts_faster():
    loads = {D0 + dt.timedelta(days=i): 60.0 for i in range(200)}
    points = series(loads, D0, D0 + dt.timedelta(days=199))
    assert len(points) == 200
    assert points[6].fatigue > points[6].fitness       # 7-day reacts faster
    assert points[-1].fitness == pytest.approx(60, abs=1)
    assert points[-1].form == pytest.approx(0, abs=1)


def test_rest_after_training_makes_form_positive():
    loads = {D0 + dt.timedelta(days=i): 80.0 for i in range(60)}
    points = series(loads, D0, D0 + dt.timedelta(days=74))
    assert points[59].form < 0
    assert points[-1].form > 0
    assert points[-1].fitness < points[59].fitness       # fitness decays on rest


def test_window_is_warmed_up_from_history():
    loads = {D0 + dt.timedelta(days=i): 50.0 for i in range(100)}
    late = series(loads, D0 + dt.timedelta(days=90), D0 + dt.timedelta(days=99))
    assert late[0].fitness > 40


@pytest.mark.parametrize("form,expected", [
    (25, "detraining"), (20.1, "detraining"), (20, "fresh"), (5.1, "fresh"),
    (5, "maintaining"), (0, "maintaining"), (-10, "maintaining"),
    (-10.1, "gaining"), (-30, "gaining"), (-30.1, "overtraining"),
])
def test_status_bands(form, expected):
    assert status(form, history_days=30) == expected


def test_insufficient_history_is_not_labelled():
    assert status(25, history_days=13) == "insufficient_data"
    assert status(25, history_days=14) == "detraining"


def test_history_days():
    assert history_days({}, D0) == 0
    assert history_days({D0: 1.0}, D0 + dt.timedelta(days=13)) == 14
