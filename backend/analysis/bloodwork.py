"""Reading a blood panel, for a runner. Pure — no Django, no clock, no I/O.

Rohit is booking a full-body home test — bloods and urine — and wanted the app
to read the report. This does the half an app can honestly do: it puts his
numbers next to the range they were measured against, says which ones matter
for somebody who runs, and shows them moving over time.

It does not diagnose, and that is not a disclaimer bolted on the end — it is
why the module is shaped this way. A marker outside a range is a question, not
an answer: ferritin of 18 means something different in a man with heavy
training load than in a woman who has just given blood, and neither of those
is a thing this code knows. So every out-of-range value produces a sentence
pointing at a conversation, never a conclusion.

**The lab's own range wins.** Reference intervals differ between labs, between
assays and between populations, and a value flagged "low" against the wrong
range is worse than no flag at all. `FALLBACK` here is used only when the
report did not print one, and the result says which was used.

**What a runner should actually look at**, and why these five lead:

* ferritin — iron stores. Far and away the commonest reason a runner feels
  flat, and the one most often missed because haemoglobin can still be normal
  while stores are empty. Endurance training lowers it through foot-strike
  haemolysis, sweat and gut losses.
* haemoglobin — oxygen carriage. The thing ferritin eventually costs you.
* vitamin D — bone and muscle. Low in most people who train indoors or live
  far from the equator, and implicated in stress fractures.
* B12 — oxygen carriage and nerve function; low in diets light on animal food.
* TSH — thyroid. Unexplained fatigue and a heart rate that will not behave.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Direction that is a concern. Some markers only matter when low, some only
#: when high, and flagging both ways on all of them is how an app cries wolf.
LOW, HIGH, BOTH = "low", "high", "both"


@dataclass(frozen=True)
class Marker:
    key: str
    label: str
    unit: str
    #: Used only when the report prints no range of its own.
    fallback: tuple[float, float] | None
    watch: str
    #: Why a runner cares. Shown with the number, because a number with no
    #: reason attached is one nobody acts on.
    matters: str
    #: Shown when it falls outside the range. A question, never a conclusion.
    outside: str
    runner_key: bool = False


MARKERS: tuple[Marker, ...] = (
    Marker("ferritin", "Ferritin", "ng/mL", (30.0, 300.0), LOW,
           "Your iron stores — the tank behind your haemoglobin.",
           "Low ferritin is the commonest reason a runner feels flat, and it shows up "
           "here before haemoglobin drops. Worth asking your doctor about iron, and "
           "worth re-testing rather than supplementing on one number.",
           runner_key=True),
    Marker("hemoglobin", "Haemoglobin", "g/dL", (13.0, 17.0), LOW,
           "How much oxygen your blood can carry.",
           "Below range is worth a conversation, especially alongside low ferritin. "
           "Endurance athletes can also read slightly low from plasma volume alone, "
           "which is not the same thing as being anaemic.",
           runner_key=True),
    Marker("vitamin_d", "Vitamin D", "ng/mL", (30.0, 100.0), LOW,
           "Bone and muscle function.",
           "Low vitamin D is very common and is associated with stress fractures. "
           "Easy to correct, and worth raising with your doctor.",
           runner_key=True),
    Marker("vitamin_b12", "Vitamin B12", "pg/mL", (200.0, 900.0), LOW,
           "Oxygen carriage and nerve function.",
           "Low B12 causes fatigue that training will not explain. Ask your doctor, "
           "particularly if you eat little animal food.",
           runner_key=True),
    Marker("tsh", "TSH (thyroid)", "mIU/L", (0.4, 4.0), BOTH,
           "Thyroid signalling — energy, weight and resting heart rate.",
           "Out of range here explains a lot of unexplained tiredness and a heart "
           "rate that will not settle. One for your doctor, not for a training app.",
           runner_key=True),
    Marker("vitamin_b9", "Folate", "ng/mL", (3.0, 20.0), LOW,
           "Works with B12 on red blood cells.", "Worth mentioning to your doctor."),
    Marker("hba1c", "HbA1c", "%", (4.0, 5.7), HIGH,
           "Average blood sugar over about three months.",
           "Above range is a conversation with your doctor about diet and risk."),
    Marker("creatinine", "Creatinine", "mg/dL", (0.7, 1.3), BOTH,
           "Kidney filtering.",
           "Runners often read a little high from muscle turnover alone; it is the "
           "trend and the context that matter. Ask your doctor."),
    Marker("alt", "ALT", "U/L", (7.0, 56.0), HIGH,
           "Liver enzyme.",
           "Can rise for a few days after hard training. Ask your doctor, and "
           "mention when you last ran hard."),
    Marker("cholesterol_total", "Total cholesterol", "mg/dL", (0.0, 200.0), HIGH,
           "Cardiovascular risk marker.", "One to discuss with your doctor."),
    Marker("hdl", "HDL", "mg/dL", (40.0, 100.0), LOW,
           "The protective cholesterol.", "One to discuss with your doctor."),
    Marker("ldl", "LDL", "mg/dL", (0.0, 100.0), HIGH,
           "The one linked to cardiovascular risk.",
           "One to discuss with your doctor."),
    Marker("vitamin_b6", "Vitamin B6", "ng/mL", (5.0, 50.0), BOTH,
           "Energy metabolism.", "Worth mentioning to your doctor."),
    Marker("calcium", "Calcium", "mg/dL", (8.5, 10.5), BOTH,
           "Bone and muscle contraction.", "Worth mentioning to your doctor."),
    Marker("magnesium", "Magnesium", "mg/dL", (1.7, 2.4), LOW,
           "Muscle function and sleep.", "Worth mentioning to your doctor."),
)

BY_KEY: dict[str, Marker] = {m.key: m for m in MARKERS}
RUNNER_KEYS: tuple[str, ...] = tuple(m.key for m in MARKERS if m.runner_key)

#: What a value is, relative to its range.
IN, BELOW, ABOVE, UNKNOWN = "in_range", "below", "above", "unknown"


@dataclass(frozen=True)
class Reading:
    key: str
    label: str
    unit: str
    value: float
    low: float | None
    high: float | None
    #: "lab" when the report printed its own range, "fallback" when we supplied
    #: one, "none" when there is nothing to compare against. Shown, always: a
    #: flag against the wrong range is worse than no flag.
    range_source: str
    status: str
    flagged: bool
    matters: str
    note: str
    runner_key: bool


def assess(key: str, value: float,
           low: float | None = None, high: float | None = None) -> Reading | None:
    """One marker, against the lab's range if it gave one.

    `flagged` means "worth asking about", not "abnormal": a marker that only
    matters when low is not flagged for being high, because an app that flags
    everything gets scrolled past.
    """
    marker = BY_KEY.get(key)
    if marker is None or value is None:
        return None

    if low is not None or high is not None:
        source = "lab"
    elif marker.fallback:
        low, high = marker.fallback
        source = "fallback"
    else:
        source = "none"

    if low is None and high is None:
        status = UNKNOWN
    elif low is not None and value < low:
        status = BELOW
    elif high is not None and value > high:
        status = ABOVE
    else:
        status = IN

    flagged = (
        (status == BELOW and marker.watch in (LOW, BOTH))
        or (status == ABOVE and marker.watch in (HIGH, BOTH))
    )
    return Reading(
        key=key, label=marker.label, unit=marker.unit, value=float(value),
        low=low, high=high, range_source=source, status=status, flagged=flagged,
        matters=marker.matters, note=marker.outside if flagged else "",
        runner_key=marker.runner_key,
    )


def summarise(readings: list[Reading]) -> dict:
    """The one paragraph at the top. Deliberately bland when nothing is flagged.

    No reassurance is offered, because this is a handful of markers from one
    morning and "everything looks fine" is not a thing a training app is
    entitled to say about a person's health.
    """
    flagged = [r for r in readings if r.flagged]
    missing = [k for k in RUNNER_KEYS if k not in {r.key for r in readings}]
    fallbacks = [r.label for r in readings if r.range_source == "fallback"]

    if flagged:
        names = ", ".join(r.label for r in flagged[:4])
        headline = (
            f"{len(flagged)} marker{'s' if len(flagged) != 1 else ''} to ask about: "
            f"{names}."
        )
    else:
        headline = "Nothing here is outside its range."

    return {
        "headline": headline,
        "flagged": [r.key for r in flagged],
        "missing_runner_markers": missing,
        "used_fallback_ranges": fallbacks,
        # Said every time, on every panel, flagged or not.
        "standing_note": (
            "This lines your numbers up against the ranges they were measured "
            "against and points out the ones runners care about. It is not a "
            "diagnosis and cannot be one — take the report itself to your doctor."
        ),
    }
