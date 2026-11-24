"""Reading a blood panel, for a runner.

Rohit is booking a full-body home test and asked the app to read the report.
It does the half an app can honestly do — numbers against the range they were
measured against, and which ones runners care about. It does not diagnose, and
every test here is about keeping it that way.
"""

from __future__ import annotations

import pytest

from analysis import bloodwork


# --- the ranges ---------------------------------------------------------------


def test_the_labs_own_range_wins():
    """Reference intervals differ between labs and assays. A value flagged
    against the wrong range is worse than no flag at all."""
    reading = bloodwork.assess("tsh", 5.0, low=0.5, high=5.5)
    assert reading.status == bloodwork.IN
    assert reading.range_source == "lab"
    assert (reading.low, reading.high) == (0.5, 5.5)


def test_our_range_is_used_only_when_the_report_printed_none_and_says_so():
    reading = bloodwork.assess("tsh", 5.0)
    assert reading.status == bloodwork.ABOVE
    assert reading.range_source == "fallback"


def test_the_same_number_can_be_fine_or_flagged_depending_whose_range():
    """Which is the whole reason the source is shown on every row."""
    ours = bloodwork.assess("tsh", 5.0)
    theirs = bloodwork.assess("tsh", 5.0, low=0.5, high=5.5)
    assert ours.flagged is True
    assert theirs.flagged is False


# --- what gets flagged --------------------------------------------------------


def test_a_marker_that_only_matters_when_low_is_not_flagged_for_being_high():
    """An app that flags everything gets scrolled past."""
    high = bloodwork.assess("ferritin", 400)
    assert high.status == bloodwork.ABOVE
    assert high.flagged is False

    low = bloodwork.assess("ferritin", 18)
    assert low.flagged is True


def test_a_marker_that_matters_both_ways_is_flagged_both_ways():
    assert bloodwork.assess("tsh", 0.1).flagged is True
    assert bloodwork.assess("tsh", 9.0).flagged is True


def test_a_flag_is_a_question_not_a_conclusion():
    """Ferritin of 18 means something different in a man training hard and in
    somebody who has just given blood, and this code knows neither."""
    note = bloodwork.assess("ferritin", 18).note.lower()
    assert "doctor" in note
    for word in ("you have", "diagnos", "anaemia", "deficient"):
        assert word not in note, note


def test_an_in_range_value_carries_no_note_but_still_says_why_it_matters():
    reading = bloodwork.assess("hemoglobin", 15.0)
    assert reading.note == ""
    assert reading.matters


def test_an_unknown_marker_is_ignored_rather_than_guessed():
    assert bloodwork.assess("unobtainium", 42) is None


# --- the summary --------------------------------------------------------------


def test_nothing_flagged_is_never_reported_as_all_clear():
    """A handful of markers from one morning is not a statement about anyone's
    health, and a training app is not entitled to make one."""
    readings = [bloodwork.assess("hemoglobin", 15.0), bloodwork.assess("tsh", 2.0)]
    summary = bloodwork.summarise(readings)
    assert "outside its range" in summary["headline"]
    for word in ("healthy", "fine", "all clear", "no concerns"):
        assert word not in summary["headline"].lower()


def test_the_standing_note_is_on_every_panel_flagged_or_not():
    for readings in ([], [bloodwork.assess("ferritin", 18)]):
        note = bloodwork.summarise(readings)["standing_note"].lower()
        assert "not a diagnosis" in note
        assert "doctor" in note


def test_it_names_the_runner_markers_that_were_not_tested():
    """Worth asking for next time — ferritin above all, which is the commonest
    thing a runner is low on and the one most often left off a panel."""
    summary = bloodwork.summarise([bloodwork.assess("hemoglobin", 15.0)])
    assert "ferritin" in summary["missing_runner_markers"]
    assert "vitamin_d" in summary["missing_runner_markers"]


def test_it_says_which_values_were_judged_against_a_borrowed_range():
    summary = bloodwork.summarise([
        bloodwork.assess("ferritin", 50),
        bloodwork.assess("tsh", 2.0, low=0.5, high=5.5),
    ])
    assert summary["used_fallback_ranges"] == ["Ferritin"]


def test_the_markers_a_runner_needs_are_the_ones_marked_so():
    assert set(bloodwork.RUNNER_KEYS) == {
        "ferritin", "hemoglobin", "vitamin_d", "vitamin_b12", "tsh",
    }
