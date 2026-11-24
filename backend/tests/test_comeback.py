"""Meeting the athlete where they are, after they have stopped.

Rohit: ten runs in eleven weeks, a four-week gap through October, then ten days
of nothing. The app noticed none of it — it kept writing sessions, he kept not
doing them, and the only thing that changed was the size of the backlog.
"""

from __future__ import annotations

import datetime as dt

import pytest

from planning import comeback

TODAY = dt.date(2026, 11, 24)


def ago(days: int) -> dt.date:
    return TODAY - dt.timedelta(days=days)


# --- noticing -----------------------------------------------------------------


def test_a_few_days_off_is_a_week_with_something_on():
    """Saying something after two days would make the app a nag, and a nag gets
    silenced rather than answered."""
    assert comeback.gap_for(ago(3), TODAY).noticed is False


def test_a_week_of_silence_gets_one_question():
    gap = comeback.gap_for(ago(10), TODAY)
    assert gap.noticed is True
    assert gap.days == 10
    assert "10 days" in gap.headline


def test_every_answer_does_something():
    """A survey that changes nothing teaches the athlete to ignore the next
    question."""
    gap = comeback.gap_for(ago(10), TODAY)
    assert gap.answers
    for answer in gap.answers:
        assert answer.action in {"illness", "shrink", "nothing", "restart"}
        assert answer.note


def test_a_long_gap_is_a_different_conversation():
    """Three weeks on, the question is not "shall I shrink this" but "shall we
    start again" — a plan built for October is no longer about him."""
    short = comeback.gap_for(ago(10), TODAY)
    long = comeback.gap_for(ago(40), TODAY)
    assert long.long is True and short.long is False
    assert "restart" in {a.key for a in long.answers}
    assert "restart" not in {a.key for a in short.answers}


def test_somebody_who_has_never_run_is_not_asked_why_they_stopped():
    """Asking that of a new athlete is the app talking to itself."""
    assert comeback.gap_for(None, TODAY).noticed is False


# --- the first run back -------------------------------------------------------


def test_the_return_is_half_of_what_he_has_ever_held():
    """Sized from his best block, not from the plan — the plan is the thing he
    did not do."""
    gap = comeback.gap_for(ago(10), TODAY)
    out = comeback.return_session(gap, demonstrated_longest_s=20 * 60)
    assert out.minutes == 10 or out.minutes == comeback.RETURN_MIN_MINUTES


def test_the_return_is_never_punishing_however_fit_he_was():
    """The risk after a lay-off is not that the first run is too easy. It is
    that there is no second one."""
    gap = comeback.gap_for(ago(30), TODAY)
    out = comeback.return_session(gap, demonstrated_longest_s=180 * 60)
    assert out.minutes <= comeback.RETURN_MAX_MINUTES


def test_the_return_is_never_so_small_it_is_not_a_run():
    gap = comeback.gap_for(ago(30), TODAY)
    out = comeback.return_session(gap, demonstrated_longest_s=60)
    assert out.minutes >= comeback.RETURN_MIN_MINUTES


def test_the_return_says_what_the_job_actually_is():
    """"20 minutes, walk whenever" is a different thing from a prescription
    that happens to be short."""
    gap = comeback.gap_for(ago(10), TODAY)
    out = comeback.return_session(gap, demonstrated_longest_s=14 * 60)
    assert out.run_walk is True
    assert "whole job" in out.framing


def test_no_gap_means_no_return_session():
    assert comeback.return_session(comeback.gap_for(ago(2), TODAY), 900) is None


# --- the floor ----------------------------------------------------------------


def test_the_floor_comes_from_what_he_does_not_what_a_plan_wants():
    """Four sessions a week against a man who runs twice is a week he fails by
    arithmetic, every week, for as long as he keeps the app."""
    assert comeback.week_floor([2, 1, 2, 3, 2, 2]) == 2


def test_weeks_he_missed_entirely_count():
    """A man who ran in two of the last six weeks has a floor of one, not of
    whatever he managed in the weeks he showed up."""
    assert comeback.week_floor([0, 0, 3, 0, 0, 2]) == comeback.FLOOR_MIN


def test_the_floor_is_never_zero_and_never_a_plan():
    assert comeback.week_floor([0, 0, 0]) == comeback.FLOOR_MIN
    assert comeback.week_floor([9, 9, 9, 9]) == comeback.FLOOR_MAX


def test_no_history_still_gives_a_floor():
    assert comeback.week_floor([]) == comeback.FLOOR_MIN


def test_a_week_that_clears_the_floor_says_so_plainly():
    assert "good week" in comeback.floor_line(2, 2)
    assert "past a good week" in comeback.floor_line(4, 2)


def test_a_week_under_the_floor_reports_what_is_left_not_what_is_missing():
    """Those are the same number, and only one of them is a thing you can go
    and do."""
    line = comeback.floor_line(0, 2)
    assert "makes this a good week" in line
    assert "missed" not in line.lower() and "behind" not in line.lower()

    assert comeback.floor_line(1, 2) == "1 down, 1 to go for a good week."
