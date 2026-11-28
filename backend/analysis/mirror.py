"""The weekly mirror: what he said he would do, against what he did. Pure.

Every number here already exists somewhere in the app. Runs have a compliance
score, food has targets and a log, sleep has a target and a measurement, water has
both. What has never existed is one screen that puts the gaps side by side, so a
week where the running held together and the eating fell apart reads as exactly
that instead of as two unrelated screens that each look fine.

Three rules, which are the whole design:

* **A missing log is not a zero.** Not logging dinner is not eating nothing, and a
  mirror that scores it as nothing is lying in the direction that makes him feel
  worse. Every row carries how many days it actually has, and a row without enough
  of them says so instead of showing a number.
* **No coaching.** No encouragement, no "great work", no goal for next week. Those
  exist already in the weekly report. A mirror that editorialises stops being a
  mirror, and the discomfort of an unadorned gap is the feature.
* **Over is not automatically worse than under.** Eating over target on a week with
  a long run in it is fine; sleeping over target is just sleep. Which direction is
  bad is per-row, and some rows have no bad direction at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Status = Literal["hit", "under", "over", "not_enough_data", "nothing_planned",
                 "no_target"]
Bad = Literal["under", "over", "both", "neither"]

#: Within this fraction of the target counts as hitting it. Deliberately wide: a
#: mirror that calls 2380 against 2400 a miss trains him to ignore it.
HIT_WITHIN = 0.10
#: A row needs this many days of data out of seven before it shows a number at all.
MIN_DAYS = 4
#: Rows are ordered by how much they are his to control, not by importance.
ORDER = ("runs", "run_time", "strength", "kcal", "protein", "sleep", "water")


@dataclass
class Row:
    key: str
    label: str
    planned: float | None
    done: float | None
    unit: str
    #: Which way is actually a problem. Sleep over target is not a problem.
    bad: Bad = "under"
    #: Days of data behind `done`, and days there could have been. Only meaningful
    #: for rows built from a log — see `needs_days`.
    days: int = 0
    of_days: int = 7
    #: True for rows read from a log (food, sleep, water), where a handful of days
    #: is not a week and the row should stay quiet. False for rows read from the
    #: plan (runs, strength): the plan knows what it asked for whatever day it is,
    #: and gating those on MIN_DAYS would blank the Runs row every Monday and
    #: Tuesday. It also governs whether "(n of 7 days logged)" is shown at all,
    #: which on a Runs row was simply untrue.
    needs_days: bool = True
    #: Why there is no target, when there is a reason better than "nothing planned"
    #: — a calorie target needs his weight, and "nothing planned" would blame him
    #: for an empty profile field instead of telling him which one to fill.
    missing_reason: str = ""
    #: Set by `assess`; never passed in.
    status: Status = "not_enough_data"
    gap: float | None = None
    pct: int | None = None
    note: str = ""


def _pct(done: float, planned: float) -> int:
    return int(round(done / planned * 100)) if planned else 0


def assess(row: Row) -> Row:
    """Fill in status, gap, pct and the one-line note. Pure, and the only place a
    row is judged — so every domain is judged the same way."""
    if row.planned is None or row.planned == 0:
        row.status = "no_target" if row.missing_reason else "nothing_planned"
        row.note = row.missing_reason or "Nothing planned."
        return row
    if row.done is None or (row.needs_days and row.days < MIN_DAYS):
        row.status = "not_enough_data"
        row.note = (f"Only {row.days} of {row.of_days} days logged — not enough to say."
                    if row.days else "Nothing logged.")
        return row

    row.gap = round(row.done - row.planned, 1)
    row.pct = _pct(row.done, row.planned)
    within = abs(row.done - row.planned) <= row.planned * HIT_WITHIN
    if within:
        row.status = "hit"
    else:
        row.status = "over" if row.done > row.planned else "under"

    # A direction that is not a problem is reported without being called a miss.
    if row.status == "hit":
        row.note = "On it."
    elif row.bad == "neither" or (row.bad == "under" and row.status == "over") or (
            row.bad == "over" and row.status == "under"):
        row.note = f"{abs(row.gap):g} {row.unit} {'over' if row.gap > 0 else 'under'}, which is fine."
        row.status = "hit"
    else:
        row.note = f"{abs(row.gap):g} {row.unit} {'over' if row.gap > 0 else 'short'}."
    return row


@dataclass
class Mirror:
    rows: list[Row] = field(default_factory=list)
    #: The count that matters: rows he actually missed, out of rows that could be judged.
    missed: int = 0
    judged: int = 0
    #: The single row furthest from its target, which is where to look first.
    worst: str | None = None
    headline: str = ""


def build(rows: list[Row]) -> Mirror:
    """Assess every row, order them, and say in one line how the week went.

    The headline counts rather than praises: "3 of 5 on target" is a fact he can
    argue with, where "good week!" is not.
    """
    done = [assess(r) for r in rows]
    by_key = {r.key: r for r in done}
    ordered = [by_key[k] for k in ORDER if k in by_key]
    ordered += [r for r in done if r.key not in ORDER]

    judged = [r for r in ordered if r.status in ("hit", "under", "over")]
    missed = [r for r in judged if r.status != "hit"]

    worst = None
    if missed:
        worst = max(missed, key=lambda r: abs((r.pct or 100) - 100)).key

    out = Mirror(rows=ordered, missed=len(missed), judged=len(judged), worst=worst)
    if not judged:
        out.headline = "Not enough logged this week to compare anything."
    elif not missed:
        out.headline = f"All {len(judged)} on target."
    else:
        out.headline = f"{len(judged) - len(missed)} of {len(judged)} on target."
    return out
