"""R25: what the lab-report extractor refuses to pass through.

The point of these is the rejections. Anyone can test that a clean report comes
back as rows; the reason `labs.py` refused to read a report for a release and a
half is the bad row that looks fine, and that is what is asserted here.
"""

from __future__ import annotations

import datetime as dt

import pytest

from apps.health import lab_extract as L

TODAY = dt.date(2026, 11, 28)


def row(key="ferritin", *, value=22.0, unit="ng/mL", printed="Ferritin",
        as_printed=None, low=None, high=None):
    return L.ExtractedReading(
        printed_name=printed, key=key, value=value, unit=unit,
        as_printed=as_printed if as_printed is not None else f"{value:g}",
        ref_low=low, ref_high=high,
    )


def panel(rows, *, taken_on="2026-11-20", lab="Redcliffe", unreadable=None):
    return L.ExtractedPanel(taken_on=taken_on, lab=lab, readings=rows,
                            unreadable=unreadable or [])


def run(rows, **kw):
    return L._validate(panel(rows, **kw), today=TODAY, source_note="test")


# --- units: the hazard that is not OCR ---------------------------------------

@pytest.mark.parametrize(
    ("key", "value", "unit", "expected", "canonical"),
    [
        # Vitamin D in SI units is the classic: 75 nmol/L is a fine result, and
        # read as 75 ng/mL it is also a fine result — of a different person.
        # Expected values are post-rounding: a conversion is held to the figures its
        # source had (test_a_converted_number_does_not_invent_precision).
        ("vitamin_d", 75.0, "nmol/L", 30.0, "ng/mL"),
        ("vitamin_d", 30.0, "ng/mL", 30.0, "ng/mL"),
        ("vitamin_b12", 300.0, "pmol/L", 406.0, "pg/mL"),
        ("hemoglobin", 140.0, "g/L", 14.0, "g/dL"),
        ("ferritin", 22.0, "µg/L", 22.0, "ng/mL"),   # MICRO SIGN
        ("ferritin", 22.0, "μg/L", 22.0, "ng/mL"),   # Greek mu, what some labs emit
        ("creatinine", 88.4, "umol/L", 1.0, "mg/dL"),
        ("tsh", 2.5, "µIU/mL", 2.5, "mIU/L"),
        ("ldl", 2.6, "mmol/L", 101.0, "mg/dL"),
    ],
)
def test_units_are_converted_in_python(key, value, unit, expected, canonical):
    out = run([row(key, value=value, unit=unit)])
    assert not out["rejected"], out["rejected"]
    (reading,) = out["readings"]
    assert reading["unit"] == canonical
    assert reading["value"] == pytest.approx(expected, abs=0.05)


def test_a_conversion_says_so_and_a_pass_through_does_not():
    converted = run([row("vitamin_d", value=75, unit="nmol/L")])["readings"][0]
    assert "converted from 75 nmol/L" in converted["unit_note"]
    plain = run([row("vitamin_d", value=30, unit="ng/mL")])["readings"][0]
    assert plain["unit_note"] is None


def test_an_unknown_unit_is_rejected_not_assumed():
    out = run([row("ferritin", unit="mg/dL")])
    assert out["readings"] == []
    assert "not one I know" in out["rejected"][0]["reason"]


def test_a_missing_unit_is_kept_but_flagged():
    out = run([row("ferritin", value=22, unit="")])
    assert out["readings"][0]["value"] == 22
    assert "printed no unit" in out["readings"][0]["unit_note"]


# --- the misplaced decimal point ---------------------------------------------

@pytest.mark.parametrize(
    ("key", "value", "unit"),
    [
        ("ferritin", 124_000.0, "ng/mL"),  # a comma read as nothing
        ("hemoglobin", 140.0, "g/dL"),     # g/L value with g/dL printed
        ("hba1c", 55.0, "%"),              # mmol/mol value under a % heading
        ("vitamin_d", 0.0, "ng/mL"),
        ("tsh", 2500.0, "mIU/L"),
    ],
)
def test_impossible_values_are_rejected(key, value, unit):
    out = run([row(key, value=value, unit=unit, printed=key)])
    assert out["readings"] == [], f"{key} {value} {unit} should not have passed"
    assert "misread decimal point" in out["rejected"][0]["reason"]


def test_a_high_but_real_result_still_passes():
    """Ferritin of 1,240 is a real and alarming result. Rejecting it would hide
    the one number on the page that most needs the conversation."""
    out = run([row("ferritin", value=1240.0)])
    assert out["readings"][0]["value"] == 1240.0
    assert not out["rejected"]


# --- nothing disappears quietly ----------------------------------------------

def test_an_untracked_marker_is_named_not_dropped():
    out = run([row("other", printed="Serum Uric Acid", value=5.2, unit="mg/dL"),
               row("ferritin")])
    assert out["not_tracked"] == ["Serum Uric Acid"]
    assert [r["key"] for r in out["readings"]] == ["ferritin"]


def test_a_duplicate_marker_is_reported():
    out = run([row("ferritin", value=22), row("ferritin", value=31)])
    assert [r["value"] for r in out["readings"]] == [22]
    assert "twice" in out["rejected"][0]["reason"]


def test_missing_runner_markers_are_listed():
    out = run([row("ferritin")])
    assert "Vitamin D" in out["missing_runner_markers"]
    assert "Ferritin" not in out["missing_runner_markers"]


def test_unreadable_rows_are_passed_through():
    out = run([row("ferritin")], unreadable=["Vitamin B12 (smudged)"])
    assert out["unreadable"] == ["Vitamin B12 (smudged)"]


def test_as_printed_is_preserved_verbatim():
    """The whole review screen rests on this field matching the paper."""
    out = run([row("ferritin", value=5.0, as_printed="<5.0")])
    assert out["readings"][0]["as_printed"] == "<5.0"
    assert out["readings"][0]["value"] == 5.0


# --- the lab's own range -----------------------------------------------------

@pytest.mark.parametrize(
    ("key", "value", "unit", "low", "high", "want_low", "want_high"),
    [
        # Redcliffe prints vitamin D in nmol/L with a 75-250 nmol/L range. Left
        # unconverted that becomes 17 ng/mL against "75-250 ng/mL" — a row that
        # compares two different scales and looks precise doing it.
        ("vitamin_d", 42.5, "nmol/L", 75.0, 250.0, 30.0, 100.0),
        ("vitamin_b12", 148.0, "pmol/L", 145.0, 569.0, 196.0, 771.0),
        ("hemoglobin", 143.0, "g/L", 130.0, 170.0, 13.0, 17.0),
        ("creatinine", 88.4, "umol/L", 62.0, 106.0, 0.701, 1.2),
    ],
)
def test_the_printed_range_converts_with_the_value(
    key, value, unit, low, high, want_low, want_high
):
    out = run([row(key, value=value, unit=unit, low=low, high=high)])
    (reading,) = out["readings"]
    assert reading["ref_low"] == pytest.approx(want_low, abs=0.05)
    assert reading["ref_high"] == pytest.approx(want_high, abs=0.05)
    # And the value still sits inside its own converted range where it did before.
    assert (reading["value"] < reading["ref_low"]) == (value < low)


def test_a_converted_number_does_not_invent_precision():
    """42.5 nmol/L is three figures. 17.027 ng/mL would be three of vitamin D and
    two of arithmetic, and the extra decimals read as confidence nobody measured."""
    out = run([row("vitamin_d", value=42.5, unit="nmol/L", low=75.0, high=250.0)])
    reading = out["readings"][0]
    assert reading["value"] == 17.0
    assert reading["ref_low"] == 30.0


def test_an_unconverted_number_is_left_exactly_as_the_report_had_it():
    """Rounding a number nobody converted would mean showing him something his
    report does not say."""
    out = run([row("ferritin", value=18.47, unit="ng/mL", low=21.83, high=274.65)])
    reading = out["readings"][0]
    assert reading["value"] == 18.47
    assert (reading["ref_low"], reading["ref_high"]) == (21.83, 274.65)


def test_a_small_converted_number_keeps_its_figures():
    out = run([row("creatinine", value=106.0, unit="umol/L")])
    assert out["readings"][0]["value"] == pytest.approx(1.2, abs=0.001)


def test_a_converted_range_survives_the_plausibility_check():
    """Haemoglobin's range in g/L (130-170) is far outside anything plausible in
    g/dL, so validating before converting silently threw the lab's range away."""
    out = run([row("hemoglobin", value=143.0, unit="g/L", low=130.0, high=170.0)])
    reading = out["readings"][0]
    assert reading["ref_low"] is not None and reading["ref_high"] is not None


def test_a_printed_range_is_kept():
    out = run([row("ferritin", low=20.0, high=250.0)])
    assert (out["readings"][0]["ref_low"], out["readings"][0]["ref_high"]) == (20.0, 250.0)


@pytest.mark.parametrize(("low", "high"), [(250.0, 20.0), (0.0, 999_999.0), (-5.0, 100.0)])
def test_a_nonsense_range_is_dropped_so_the_app_falls_back(low, high):
    """A range read off the neighbouring row is worse than no range: it flags a
    normal value or silences an abnormal one, and `range_source` would still
    say "lab"."""
    out = run([row("ferritin", low=low, high=high)])
    reading = out["readings"][0]
    assert reading["ref_low"] is None or reading["ref_high"] is None


def test_one_sided_range_survives():
    out = run([row("ldl", value=90.0, unit="mg/dL", high=100.0)])
    assert out["readings"][0]["ref_high"] == 100.0
    assert out["readings"][0]["ref_low"] is None


# --- the date ----------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "note"),
    [(None, "did not print"), ("", "did not print"), ("tomorrow", "could not read"),
     ("2027-01-01", "in the future"), ("1998-04-04", "over 20 years ago")],
)
def test_a_date_that_cannot_be_trusted_is_left_for_him(raw, note):
    out = run([row("ferritin")], taken_on=raw)
    assert out["taken_on"] is None
    assert note in out["date_note"]


def test_a_good_date_is_kept():
    out = run([row("ferritin")], taken_on="2026-11-20")
    assert out["taken_on"] == dt.date(2026, 11, 20)
    assert out["date_note"] is None


# --- ordering and the standing note ------------------------------------------

def test_runner_markers_come_first():
    out = run([row("calcium", value=9.2, unit="mg/dL"),
               row("ferritin"),
               row("alt", value=30.0, unit="U/L"),
               row("vitamin_d", value=28.0, unit="ng/mL")])
    keys = [r["key"] for r in out["readings"]]
    assert keys[:2] == ["ferritin", "vitamin_d"]
    assert set(keys[2:]) == {"alt", "calcium"}


def test_the_response_says_it_was_not_kept():
    out = run([row("ferritin")])
    assert "not kept" in out["standing_note"]


def test_every_marker_has_a_plausible_range_and_a_unit_table():
    """A marker added to bloodwork with no entry here would be extracted with no
    sanity check at all, which is the failure this module exists to prevent."""
    for key in L.KEYS:
        assert key in L.PLAUSIBLE, f"{key} has no plausible range"
        assert key in L.UNITS and L.UNITS[key], f"{key} has no unit table"
        canonical = L.CANONICAL[key]
        assert any(
            target == canonical and factor == 1.0
            for target, factor in L.UNITS[key].values()
        ), f"{key} cannot be expressed in its own canonical unit {canonical}"
