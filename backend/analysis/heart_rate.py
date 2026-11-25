"""Heart-rate metrics.

Every function returns None rather than a number when the data cannot support one.
Returning 0.0 for missing data is a lie the whole stack then repeats — and heart rate
is the field most often absent, because a strap slips or a wrist sensor drops out.
"""

from __future__ import annotations

import statistics

from .segmentation import Sample

# Below this share of samples carrying HR, any drift figure is an artefact of which
# half happened to have data rather than of the athlete.
MIN_HR_COVERAGE = 0.8

#: Running samples needed before a drift figure means anything. At roughly one
#: sample a second this is about five minutes of actual running — below that
#: the two halves are noise either side of a coin toss.
MIN_RUN_SAMPLES = 300


def hr_coverage(samples: list[Sample]) -> float:
    if not samples:
        return 0.0
    return sum(1 for s in samples if s.heart_rate) / len(samples)


def run_samples(segments) -> list[Sample]:
    """Every sample taken while actually running, in order.

    The segments know which is which; the raw sample list does not. This is the
    same split the rest of the module is built on — "distance means distance
    run" — applied to heart rate, where it had been missed.
    """
    out: list[Sample] = []
    for segment in sorted(segments or [], key=lambda sg: sg.start_offset_s):
        if getattr(segment, "kind", None) == "run":
            out.extend(segment.samples or [])
    return sorted(out, key=lambda s: s.offset_s)


def hr_drift_percent(samples: list[Sample], segments=None) -> float | None:
    """How much heart rate rose across the RUNNING half of a session.

    (2nd-half mean HR − 1st-half mean HR) / 1st-half mean HR × 100, over the
    running only, split at the midpoint of running time rather than of the
    clock.

    **Why the running only.** This used to take every sample in the activity,
    walk breaks included, and for a run/walk athlete that measures the mix
    rather than the heart. Rohit walked through part of a run block and ran
    through part of a walk block; the first half of his session was mostly
    walking and the second mostly running, and the number came out at 18 %.
    Nothing had drifted. He had just run more in the second half.

    Splitting at the midpoint of *running time* matters for the same reason: a
    long walk break in the middle would otherwise push the clock midpoint into
    one of the run blocks and compare a block against itself.

    With no segments it falls back to the whole session, which is the old
    behaviour and is right for a continuous run with no walking in it.

    Interpret carefully and never alone. High drift can come from heat,
    humidity, hills, dehydration, fatigue, a slipping sensor, or genuinely
    insufficient aerobic conditioning. It is a question to ask, not an answer.
    """
    if segments is not None:
        samples = run_samples(segments)
        # Too little running to say anything. A two-minute jog has a first and
        # a second half, and the difference between them is noise.
        if sum(1 for s in samples if s.heart_rate) < MIN_RUN_SAMPLES:
            return None

    if hr_coverage(samples) < MIN_HR_COVERAGE:
        return None

    ordered = sorted(samples, key=lambda s: s.offset_s)
    with_hr = [s for s in ordered if s.heart_rate]
    if len(with_hr) < 2:
        return None

    # Split by position in the running, not by wall-clock offset: the walks
    # between blocks are not part of what is being measured.
    half = len(with_hr) // 2
    first = [s.heart_rate for s in with_hr[:half]]
    second = [s.heart_rate for s in with_hr[half:]]
    if not first or not second:
        return None

    first_mean = statistics.mean(first)
    if first_mean == 0:
        return None
    return round((statistics.mean(second) - first_mean) / first_mean * 100, 1)


def hr_range(samples: list[Sample]) -> tuple[int, int] | None:
    values = [s.heart_rate for s in samples if s.heart_rate]
    return (min(values), max(values)) if values else None
