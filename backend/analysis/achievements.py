"""Achievements and streaks (R10 §C13). Deterministic badges with the date each was
first reached, and progress towards the ones not reached yet. Pure."""

from __future__ import annotations

import datetime as dt

MIN_WEEK_RUNS = 2
FIVE_K_M = 5000
SLEEP_GOOD_S = 7 * 3600

# group -> (unit, [(target, label, description)])
CATALOGUE: dict[str, tuple[str, list[tuple[int, str, str]]]] = {
    "smoke_free": ("days", [
        (1, "First smoke-free day", "A whole day without a cigarette."),
        (3, "3 days smoke-free", "Three days in a row without a cigarette."),
        (7, "One week smoke-free", "Seven days in a row without a cigarette."),
        (14, "Two weeks smoke-free", "Fourteen days in a row without a cigarette."),
        (30, "30 days smoke-free", "A month in a row without a cigarette."),
        (90, "90 days smoke-free", "Three months in a row without a cigarette."),
    ]),
    "consistency": ("weeks", [
        (2, "2 steady weeks", "Two weeks in a row with at least 2 runs."),
        (4, "4 steady weeks", "Four weeks in a row with at least 2 runs."),
        (8, "8 steady weeks", "Eight weeks in a row with at least 2 runs."),
        (12, "12 steady weeks", "Twelve weeks in a row with at least 2 runs."),
    ]),
    "distance": ("runs", [
        (1, "First 5K", "A run of 5 km or more."),
    ]),
    "records": ("records", [
        (1, "First personal record", "Set a personal record."),
        (5, "5 personal records", "Set five personal records."),
        (10, "10 personal records", "Set ten personal records."),
    ]),
    "run_streak": ("days", [
        (3, "3-day run streak", "Runs on three days in a row."),
        (5, "5-day run streak", "Runs on five days in a row."),
        (7, "7-day run streak", "Runs on seven days in a row."),
    ]),
    "sleep": ("nights", [
        (3, "3 good nights", "Three nights in a row with 7 hours of sleep or more."),
        (7, "A week of good sleep", "Seven nights in a row with 7 hours or more."),
        (14, "Two weeks of good sleep", "Fourteen nights in a row with 7 hours or more."),
        (30, "A month of good sleep", "Thirty nights in a row with 7 hours or more."),
    ]),
    # R13 §8: cravings ridden out without smoking (only when cravings are logged).
    "cravings": ("cravings", [
        (1, "First craving beaten", "Didn't smoke through a craving."),
        (10, "10 cravings beaten", "Rode out ten cravings without smoking."),
        (50, "50 cravings beaten", "Fifty cravings resisted."),
        (100, "100 cravings beaten", "A hundred cravings resisted."),
    ]),
}
KEY_PREFIX = {"smoke_free": "smoke_free_", "consistency": "consistent_weeks_",
              "distance": "first_5k", "records": "prs_", "run_streak": "run_streak_",
              "sleep": "sleep_7h_", "cravings": "cravings_resisted_"}


def badge_key(group: str, target: int) -> str:
    prefix = KEY_PREFIX[group]
    return prefix if group == "distance" else f"{prefix}{target}"


def streak_reached(days: list[dt.date], good: set[dt.date], targets: list[int],
                   ) -> tuple[dict[int, dt.date], int, int]:
    """Walk consecutive `days`; return ({target: first date reached}, current run,
    best run). A day missing from `good` breaks the run."""
    reached: dict[int, dt.date] = {}
    run = best = 0
    for day in days:
        run = run + 1 if day in good else 0
        best = max(best, run)
        for target in targets:
            if run >= target and target not in reached:
                reached[target] = day
    return reached, run, best


def day_range(start: dt.date | None, end: dt.date) -> list[dt.date]:
    if start is None or start > end:
        return []
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def smoke_free(smoke_totals: dict[dt.date, float], tracking_start: dt.date | None,
               today: dt.date) -> tuple[dict[int, dt.date], int]:
    """Days without a cigarette from when tracking began. Today counts only once it is
    over — a badge is never given for a day that can still be lost."""
    targets = [t for t, _, _ in CATALOGUE["smoke_free"][1]]
    days = day_range(tracking_start, today - dt.timedelta(days=1))
    good = {d for d in days if smoke_totals.get(d, 0) <= 0}
    reached, current, _ = streak_reached(days, good, targets)
    return reached, current


def consistent_weeks(run_dates: list[dt.date], today: dt.date
                     ) -> tuple[dict[int, dt.date], int]:
    """Consecutive Monday–Sunday weeks with ≥ 2 runs. Earned on the day of the run that
    made the Nth week count. Progress counts the current week once it qualifies."""
    targets = [t for t, _, _ in CATALOGUE["consistency"][1]]
    if not run_dates:
        return {}, 0
    by_week: dict[dt.date, list[dt.date]] = {}
    for day in sorted(run_dates):
        by_week.setdefault(day - dt.timedelta(days=day.weekday()), []).append(day)
    first = min(by_week)
    this_week = today - dt.timedelta(days=today.weekday())
    reached: dict[int, dt.date] = {}
    run = 0
    week = first
    current = 0
    while week <= this_week:
        days = by_week.get(week, [])
        if len(days) >= MIN_WEEK_RUNS:
            run += 1
            for target in targets:
                if run >= target and target not in reached:
                    reached[target] = days[MIN_WEEK_RUNS - 1]
        elif week != this_week:
            run = 0
        current = run
        week += dt.timedelta(days=7)
    return reached, current


def run_streak(run_dates: list[dt.date], today: dt.date) -> tuple[dict[int, dt.date], int]:
    targets = [t for t, _, _ in CATALOGUE["run_streak"][1]]
    if not run_dates:
        return {}, 0
    days = day_range(min(run_dates), today)
    good = set(run_dates)
    reached, current, _ = streak_reached(days, good, targets)
    if today not in good and current == 0 and (today - dt.timedelta(days=1)) in good:
        # Today has no run yet: the streak is still alive.
        _, current, _ = streak_reached(days[:-1], good, targets)
    return reached, current


def sleep_streak(nights: dict[dt.date, int | None]) -> tuple[dict[int, dt.date], int]:
    targets = [t for t, _, _ in CATALOGUE["sleep"][1]]
    if not nights:
        return {}, 0
    days = day_range(min(nights), max(nights))
    good = {d for d, s in nights.items() if s is not None and s >= SLEEP_GOOD_S}
    reached, current, _ = streak_reached(days, good, targets)
    return reached, current


def first_5k(runs: list[tuple[dt.date, float]]) -> tuple[dict[int, dt.date], int]:
    for day, metres in sorted(runs):
        if metres >= FIVE_K_M:
            return {1: day}, 1
    return {}, 0


def records(pr_dates: list[dt.date]) -> tuple[dict[int, dt.date], int]:
    targets = [t for t, _, _ in CATALOGUE["records"][1]]
    reached = {}
    ordered = sorted(pr_dates)
    for target in targets:
        if len(ordered) >= target:
            reached[target] = ordered[target - 1]
    return reached, len(ordered)


def badges(results: dict[str, tuple[dict[int, dt.date], int]]) -> list[dict]:
    """results: group -> (reached dates, current progress). Groups missing from
    `results` are left out (e.g. smoke-free when smoking is not tracked)."""
    out = []
    for group, (unit, levels) in CATALOGUE.items():
        if group not in results:
            continue
        reached, current = results[group]
        for target, label, description in levels:
            earned_on = reached.get(target)
            out.append({"key": badge_key(group, target), "group": group, "label": label,
                        "description": description, "target": target, "unit": unit,
                        "earned_on": earned_on,
                        "progress": {"current": min(current, target) if earned_on is None
                                     else target, "target": target}})
    return out
