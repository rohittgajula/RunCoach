"""Heart rate, split by what you were doing.

Rohit: "add a HeartRate section in health with multiple hr filters like while
sleeping, running, walking, normal day time ... basically i wanna see how my
hr is changing".

A day contains four quite different hearts, and a daily average buries the one
that tells you most — sleeping heart rate — under sixteen waking hours.
"""

from __future__ import annotations

import datetime as dt

import pytest

from analysis import hr_contexts as hc

DAY = dt.date(2026, 11, 25)


def hr(*pairs):
    return [[m, bpm] for m, bpm in pairs]


def minutes(start: int, end: int, bpm: int, step: int = 2):
    return [[m, bpm] for m in range(start, end, step)]


# --- which bucket a reading lands in ------------------------------------------


def test_the_four_contexts_do_not_overlap():
    """Awake is a remainder, never a window of its own, so nothing is counted
    twice and nothing falls through."""
    windows = hc.windows_for([(400, 430)], [(430, 450)], (0, 390))
    assert hc.classify(410, windows) == "run"
    assert hc.classify(440, windows) == "walk"
    assert hc.classify(200, windows) == "sleep"
    assert hc.classify(700, windows) == "awake"


def test_running_beats_the_watch_thinking_you_were_asleep():
    """Priority runs downhill from the most specific. A segment that says you
    were running is better evidence than a sleep window that overlaps it."""
    windows = hc.windows_for([(300, 330)], [], (0, 400))
    assert hc.classify(310, windows) == "run"


def test_a_sample_outside_everything_is_awake():
    assert hc.classify(800, hc.windows_for([], [], None)) == "awake"


# --- the day ------------------------------------------------------------------


def test_a_day_is_split_four_ways():
    series = (
        minutes(0, 400, 52)        # asleep
        + minutes(400, 440, 150)   # running
        + minutes(440, 480, 105)   # walking
        + minutes(480, 1400, 70)   # awake
    )
    windows = hc.windows_for([(400, 440)], [(440, 480)], (0, 400))
    day = hc.bucket_day(DAY, series, windows)

    assert day.means["sleep"] == 52
    assert day.means["run"] == 150
    assert day.means["walk"] == 105
    assert day.means["awake"] == 70


def test_a_bucket_with_barely_any_readings_is_left_out():
    """A mean of three samples and a mean of four hundred are different claims
    and should not look the same on a chart."""
    series = minutes(0, 400, 52) + hr((500, 160), (502, 162))
    day = hc.bucket_day(DAY, series, hc.windows_for([(500, 504)], [], (0, 400)))
    assert "sleep" in day.means
    assert "run" not in day.means
    # Still counted, so the UI can say why it is missing.
    assert day.counts["run"] == 2


def test_a_zero_reading_is_skipped_rather_than_averaged_in():
    """A zero would drag a mean down and look like a resting heart rate nobody
    has."""
    series = minutes(0, 400, 50) + [[m, 0] for m in range(400, 500, 2)]
    day = hc.bucket_day(DAY, series, hc.windows_for([], [], (0, 400)))
    assert day.means["sleep"] == 50
    assert "awake" not in day.means


def test_malformed_rows_do_not_bring_the_day_down():
    series = minutes(0, 400, 50) + [["x", "y"], [], [1]]
    assert hc.bucket_day(DAY, series, hc.windows_for([], [], (0, 400))).means["sleep"] == 50


# --- across days --------------------------------------------------------------


def days_of(values: list[float | None], context: str = "sleep") -> list[hc.DayHR]:
    out = []
    for i, v in enumerate(values):
        means = {context: v} if v is not None else {}
        out.append(hc.DayHR(day=DAY - dt.timedelta(days=len(values) - 1 - i),
                            means=means, counts={context: 100} if v else {}))
    return out


def test_a_day_without_enough_data_is_a_gap_not_a_zero():
    """A flat line through a week the watch was off the wrist is a lie the
    chart would tell convincingly."""
    points = hc.series(days_of([50, None, 52, None, 51]), "sleep")
    assert [p["bpm"] for p in points] == [50, 52, 51]


def test_the_series_runs_oldest_first():
    points = hc.series(days_of([50, 51, 52]), "sleep")
    assert points[0]["day"] < points[-1]["day"]


def test_weeks_average_the_days_inside_them():
    rows = days_of([50, 50, 50, 50, 50, 50, 50, 56, 56, 56, 56, 56, 56, 56])
    weeks = hc.weekly(rows, "sleep")
    assert len(weeks) >= 2
    assert weeks[0]["bpm"] != weeks[-1]["bpm"]


# --- the trend ----------------------------------------------------------------


def test_down_is_the_good_direction_and_is_named_not_signed():
    """"-3" reads as worse to most people, and this is the one metric where
    down is the win."""
    trend = hc.direction(hc.series(days_of([58, 58, 57, 57, 55, 54, 53, 52, 52]), "sleep"))
    assert trend["enough"] is True
    assert trend["better"] is True
    assert trend["change"] < 0


def test_a_rising_heart_rate_is_not_called_better():
    trend = hc.direction(hc.series(days_of([50, 50, 51, 52, 54, 55, 56, 57, 58]), "sleep"))
    assert trend["better"] is False


def test_a_flat_line_is_called_flat_rather_than_a_direction():
    trend = hc.direction(hc.series(days_of([52, 52, 52.2, 51.9, 52, 52.1, 52, 52]), "sleep"))
    assert trend["flat"] is True


def test_too_few_days_gets_no_trend_rather_than_a_guess():
    """Two single days are two coin flips and a line between them is noise."""
    assert hc.direction(hc.series(days_of([50, 54]), "sleep"))["enough"] is False


def test_every_context_has_a_label_and_a_reason():
    for key in hc.CONTEXTS:
        assert hc.LABEL[key] and hc.WHY[key]
