"""Energy balance vs weight trend.

Seven-day rolling intake minus target, turned into a predicted weekly weight change,
set beside the weight actually measured. Shown only with >= 5 logged days out of the
last 7: an average over two logged days mostly measures which days got logged.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

KCAL_PER_KG = 7700
WINDOW_DAYS = 7
MIN_LOGGED_DAYS = 5


@dataclass(frozen=True)
class Balance:
    avg_balance_kcal: int | None
    predicted_kg_per_week: float | None
    actual_kg_per_week: float | None
    logged_days_last_7: int
    message: str


def slope_per_day(points: list[tuple[dt.date, float]]) -> float | None:
    """Least-squares slope in units per day. None with fewer than two distinct days."""
    if len({d for d, _ in points}) < 2:
        return None
    origin = min(d for d, _ in points)
    xs = [(d - origin).days for d, _ in points]
    ys = [v for _, v in points]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator


def summarise(
    intake: dict[dt.date, float],
    targets: dict[dt.date, float],
    weights: list[tuple[dt.date, float]],
    end: dt.date,
) -> Balance:
    """`intake` holds only days with something logged; `targets` every day."""
    window = [end - dt.timedelta(days=offset) for offset in range(WINDOW_DAYS)]
    logged = [d for d in window if intake.get(d)]

    if len(logged) < MIN_LOGGED_DAYS:
        return Balance(None, None, None, len(logged), "Log more days to see this.")

    balances = [intake[d] - targets[d] for d in logged if d in targets]
    if not balances:
        return Balance(None, None, None, len(logged), "Log more days to see this.")
    average = sum(balances) / len(balances)
    predicted = average * 7 / KCAL_PER_KG

    start = window[-1]
    in_window = [(d, w) for d, w in weights if start <= d <= end]
    slope = slope_per_day(in_window)
    actual = round(slope * 7, 2) if slope is not None else None

    message = (
        f"Avg {round(average):+d} kcal/day ≈ {predicted:+.1f} kg/week predicted"
        + (f", {actual:+.1f} kg/week actual" if actual is not None else "")
    )
    return Balance(
        avg_balance_kcal=round(average),
        predicted_kg_per_week=round(predicted, 2),
        actual_kg_per_week=actual,
        logged_days_last_7=len(logged),
        message=message,
    )
