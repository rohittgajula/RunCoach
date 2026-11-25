"""HR drift belongs to the running, not to the session.

Rohit: "today i noticed one more thing hr drift showed 18% the reason was i
was walking in run session for some time to cover that i was running in walk
session, so it counted run in walk session as walk only and calculated. only
count actual run & walk sessions not the planned one."

He was right, and the diagnosis was better than the one in the code. Drift was
computed across every sample in the activity, walk breaks included. For a
run/walk athlete who walks early and runs late, the first half of the session
is mostly walking and the second mostly running, so the number measures the
mix and not the heart.

The rest of this codebase is built on exactly that distinction — "distance
means distance run", everything from segments and never from raw samples. Heart
rate was the one place it had been missed.
"""

from __future__ import annotations

import pytest

from analysis import heart_rate
from analysis.segmentation import Sample, Segment


def block(kind: str, start: int, seconds: int, hr: int) -> Segment:
    """One segment at a steady heart rate, one sample a second."""
    return Segment(
        index=0, kind=kind, start_offset_s=start, duration_s=seconds,
        distance_m=seconds * (2.5 if kind == "run" else 1.4),
        samples=[Sample(offset_s=start + i, heart_rate=hr) for i in range(seconds)],
    )


def test_the_session_rohit_actually_ran():
    """Walked through the first half, ran through the second, steady heart rate
    inside each. The old figure read as 18 % of drift. Nothing drifted."""
    walk = block("walk", 0, 900, 110)
    run = block("run", 900, 900, 150)
    segments = [walk, run]
    everything = [*walk.samples, *run.samples]

    whole_session = heart_rate.hr_drift_percent(everything)
    assert whole_session is not None and whole_session > 15, whole_session

    running_only = heart_rate.hr_drift_percent(everything, segments)
    assert running_only == 0.0, running_only


def test_real_drift_inside_the_running_is_still_caught():
    """The fix must not make the metric blind — a heart rate that climbs while
    the pace holds is the thing this measures and it has to survive."""
    segments = [
        block("run", 0, 600, 140),
        block("walk", 600, 120, 110),
        block("run", 720, 600, 154),
    ]
    samples = [s for seg in segments for s in seg.samples]
    drift = heart_rate.hr_drift_percent(samples, segments)
    assert drift is not None and 9 < drift < 11, drift


def test_the_split_ignores_the_walk_in_the_middle():
    """Splitting on the clock would put the midpoint inside a walk break and
    compare a run block against itself."""
    segments = [
        block("run", 0, 600, 140),
        block("walk", 600, 1800, 100),   # a very long break
        block("run", 2400, 600, 140),
    ]
    samples = [s for seg in segments for s in seg.samples]
    assert heart_rate.hr_drift_percent(samples, segments) == 0.0


def test_too_little_running_gets_no_number_rather_than_a_guess():
    """A two-minute jog has a first and a second half, and the difference
    between them is noise."""
    segments = [block("run", 0, 120, 150), block("walk", 120, 900, 110)]
    samples = [s for seg in segments for s in seg.samples]
    assert heart_rate.hr_drift_percent(samples, segments) is None


def test_a_session_with_no_running_has_no_drift():
    segments = [block("walk", 0, 1800, 110)]
    samples = [s for seg in segments for s in seg.samples]
    assert heart_rate.hr_drift_percent(samples, segments) is None


def test_without_segments_it_behaves_as_it_always_did():
    """A continuous run with no walking in it needs no split, and callers that
    have not been given segments must not silently start returning None."""
    run = block("run", 0, 1200, 140)
    assert heart_rate.hr_drift_percent(run.samples) == 0.0


def test_missing_heart_rate_still_refuses_to_invent_a_number():
    segments = [
        Segment(index=0, kind="run", start_offset_s=0, duration_s=600, distance_m=1500,
                samples=[Sample(offset_s=i) for i in range(600)]),
    ]
    samples = list(segments[0].samples)
    assert heart_rate.hr_drift_percent(samples, segments) is None
