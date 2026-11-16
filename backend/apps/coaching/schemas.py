"""Pydantic models that ARE the API schema.

One definition, three jobs: it generates the schema sent to OpenAI, validates what
comes back, and types the rest of the code.

Written for OpenAI's strict Structured Outputs, which requires every field to be
`required` and every object to set `additionalProperties: false`. Optionality is
therefore expressed as a union with `None`, never as a field with a default — a
default would be silently dropped from the schema and the model would be free to
omit the field entirely.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Observation(BaseModel):
    """One thing the data shows, and what it means for the athlete.

    Split deliberately into three parts. `finding` must be traceable to a number the
    system actually holds; `meaning` is interpretation; `action` is what to do. Fusing
    them is how a plausible-sounding sentence smuggles in an invented figure.
    """

    model_config = {"extra": "forbid"}

    topic: str = Field(description="Short label, e.g. 'Longest continuous run'.")
    finding: str = Field(description="What the data shows. Cite the number given to you.")
    meaning: str = Field(description="What it means for this athlete's goal.")
    action: str | None = Field(description="What to do about it, or null if nothing.")


class Guidance(BaseModel):
    """The coaching read on where the athlete stands."""

    model_config = {"extra": "forbid"}

    headline: str = Field(description="One sentence. The single most important thing right now.")
    doing_well: list[Observation]
    to_improve: list[Observation]
    stamina: str = Field(
        description="Concretely how to build endurance from where this athlete actually is."
    )
    cautions: list[str] = Field(
        description="Risks in the data. Empty list if none — do not invent one."
    )
    confidence: float = Field(ge=0.0, le=1.0)


class RecoveryAdvice(BaseModel):
    model_config = {"extra": "forbid"}

    level: Literal["LOW", "MODERATE", "HIGH"]
    reason: str


class RunAnalysis(BaseModel):
    """One run, interpreted."""

    model_config = {"extra": "forbid"}

    summary: str = Field(description="Two or three sentences on what happened.")
    what_went_well: list[str]
    observations: list[str]
    possible_explanations: list[str] = Field(
        description="Why the numbers may look as they do — heat, terrain, sleep, "
        "sensor error. Not conclusions."
    )
    concerns: list[str] = Field(description="Empty list if none.")
    recovery: RecoveryAdvice
    next_focus: str = Field(description="What to concentrate on in the next session.")
    confidence: float = Field(ge=0.0, le=1.0)


class WeeklyReview(BaseModel):
    model_config = {"extra": "forbid"}

    status: Literal["ON_TRACK", "UNDER_LOADED", "OVER_LOADED", "FATIGUED", "RECOVERING", "ANOMALOUS"]
    summary: str
    progress: list[Observation]
    risks: list[str]
    next_week_focus: str
    confidence: float = Field(ge=0.0, le=1.0)


class JournalFacts(BaseModel):
    """Structured facts extracted from a free-text log entry."""

    model_config = {"extra": "forbid"}

    rpe: int | None = Field(description="Perceived effort 1-10, or null if not mentioned.")
    energy: int | None = Field(description="1-10, or null.")
    leg_fatigue: int | None = Field(description="1-10, or null.")
    sleep_quality: int | None = Field(description="1-10, or null.")
    pain_reported: bool
    pain_location: str | None
    pain_severity: int | None = Field(description="1-5, or null.")
    illness_reported: bool
    notes_summary: str
    confidence: float = Field(ge=0.0, le=1.0)


class WorkoutReview(BaseModel):
    """R6 §3: one completed session, interpreted. Every number must come from the input."""

    summary_md: str = Field(description="2-4 short sentences of markdown: what happened.")
    went_well: list[str] = Field(description="1-3 specific things that went well.")
    to_improve: list[str] = Field(description="1-3 specific things to do differently next time.")


class InsightsSummary(BaseModel):
    """R6 §5: the "Are you running well?" overview of the Insights payload."""

    markdown: str = Field(description="A short markdown overview, 80-160 words.")


class CheckinExplanation(BaseModel):
    """R7 §1: the one-line "why" under the morning check-in verdict."""

    text: str = Field(description="One sentence, at most 30 words.")


class HabitsSummary(BaseModel):
    """R8 §B: the habits explanation, from aggregates only."""

    markdown: str = Field(description="A short markdown summary, 80-160 words.")


class ProgressReview(BaseModel):
    """R8 §C: the progress review of the last N runs against the N before."""

    went_well: list[str] = Field(description="1-3 short points that improved.")
    improve: list[str] = Field(description="1-3 short points to work on.")
    check: list[str] = Field(description="0-2 things worth checking (heat, sleep, kit).")
    markdown: str = Field(description="A short markdown review, 60-140 words.")


class RunComparison(BaseModel):
    """Two to four runs read against each other, after Python has done the maths."""

    headline: str = Field(
        description="One sentence naming the single most important difference, in "
        "the athlete's own units. Not a summary of everything that changed."
    )
    improving: list[str] = Field(
        description="0-3 short points that genuinely got better. Empty is a valid "
        "answer and better than inventing one."
    )
    watch: list[str] = Field(
        description="0-3 short points going the wrong way, or worth keeping an eye on."
    )
    do_next: list[str] = Field(
        description="1-3 concrete things to do in the next run or two. Specific to "
        "these numbers — not general running advice."
    )
    markdown: str = Field(description="A short markdown read, 60-140 words.")


class WeeklyReportSummary(BaseModel):
    """R10 §C10: the optional paragraph on the weekly report card."""

    markdown: str = Field(description="One short markdown paragraph, 60-120 words.")


class ShortParagraph(BaseModel):
    """R13: the optional AI paragraph on the run review, the monthly report and the
    morning briefing."""

    markdown: str = Field(description="One short markdown paragraph, as long as asked.")


class FactParamItem(BaseModel):
    """R18: one profile parameter stated in a memory fact."""

    model_config = {"extra": "forbid"}

    key: Literal["sleep_need_minutes", "usual_run_time", "loop_distance_km",
                 "available_days", "long_run_day", "runs_per_week"]
    number: float | None = Field(description="sleep_need_minutes (minutes), loop_distance_km "
                                             "(km), long_run_day (0=Monday), runs_per_week; "
                                             "else null.")
    time: str | None = Field(description="usual_run_time as 24-hour HH:MM, else null.")
    days: list[int] | None = Field(description="available_days as weekdays 0=Monday..6, "
                                               "else null.")
    confidence: float = Field(ge=0.0, le=1.0, description="How clearly the fact states a "
                                                           "lasting setting (not a one-off).")


class FactParams(BaseModel):
    model_config = {"extra": "forbid"}

    parameters: list[FactParamItem]


class DescribedStep(BaseModel):
    """One step of a session the athlete described in a sentence.

    Deliberately the SAME shape `planning.edit.stored_step` already accepts, so
    what the model returns goes straight through the validator the manual
    editor uses. A second shape would need a second validator, and the one that
    got less attention would be the one the model talks to.
    """

    model_config = {"extra": "forbid"}

    kind: Literal["warmup", "run", "walk", "recovery", "cooldown", "strides", "other"]
    duration_s: int = Field(description="Seconds, 10 to 5400.")
    intensity: Literal["walk", "easy", "moderate", "hard"]
    hr_low: int | None = Field(description="Heart rate floor, or null to leave it to the app.")
    hr_high: int | None = Field(description="Heart rate ceiling, or null.")
    note: str | None = Field(description="At most a few words, or null.")


class DescribedBlock(BaseModel):
    """A repeated block: "4 × (4 min run, 2 min walk)"."""

    model_config = {"extra": "forbid"}

    repeat: int = Field(description="2 to 30. Use 1 step lists only inside a repeat.")
    steps: list[DescribedStep]


class ProposedChange(BaseModel):
    """A change to a DIFFERENT day that the new session would make necessary.

    Rohit: "if you wanna change future runs ask for a updated on specific day i
    will give you a go or no go."

    So this is a question, never an instruction. Each one names a single date
    and gets its own yes or no — a list the athlete accepts wholesale is not
    consent to the item buried in the middle of it. The server resolves every
    one to a real workout before showing it, and applies only the ones that
    come back approved.

    Only ever gentler. A day the athlete did not ask about may be made easier,
    moved or dropped; it may never be made longer or harder. Reading a clash is
    the job; re-planning the week is not.
    """

    model_config = {"extra": "forbid"}

    date: str = Field(description="YYYY-MM-DD. A day other than the one being planned.")
    action: Literal["easier", "move", "skip"]
    minutes: int | None = Field(
        description="For 'easier': the new total, lower than the current one. Else null."
    )
    move_to: str | None = Field(description="For 'move': YYYY-MM-DD. Else null.")
    why: str = Field(description="One short sentence the athlete can judge. Name the clash.")


class DescribedSession(BaseModel):
    """A run written from the athlete's own description of it.

    The model's job here is reading, not prescribing: turning "easy run in zone
    2 for 30 min, run/walk strategy" into steps. Every limit — step length,
    total length, heart-rate bands against this athlete's own floor and
    ceiling — is enforced afterwards by `planning.edit.expand`, because a model
    asked to respect a numeric limit will mostly respect it, and mostly is not
    a safety rule.
    """

    model_config = {"extra": "forbid"}

    title: str = Field(description="Short, e.g. '30m easy run/walk'. No date in it.")
    kind: Literal["RUN_WALK", "EASY", "LONG", "INTERVALS", "TEMPO"]
    description: str = Field(description="1-2 sentences on how to run it.")
    target_zone: str | None = Field(description="'Z2' etc. if the athlete named one, else null.")
    understood: str = Field(
        description="One line, addressed to the athlete, naming what you took from "
                    "their words, and how the days around it shaped the session. "
                    "Say plainly if you had to assume something."
    )
    steps: list[DescribedStep | DescribedBlock]
    changes: list[ProposedChange] = Field(
        description="Changes to OTHER days that this session would need, or an empty "
                    "list. Each is a proposal the athlete answers yes or no to on its "
                    "own; you are not making them."
    )
