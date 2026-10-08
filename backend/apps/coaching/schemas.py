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
