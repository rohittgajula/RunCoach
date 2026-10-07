"""Compare any two (R10 §C11): pair two daily series, Spearman's ρ and a plain
sentence. Association only — the caveat travels with every result. Pure."""

from __future__ import annotations

import datetime as dt

from .habits import spearman

MIN_N = 8
CAVEAT = "This shows a pattern in your own data, not a cause."


def pair(xs: dict[dt.date, float], ys: dict[dt.date, float], lag: int) -> list[dict]:
    """Points where both exist; with lag 1 the y value is the day after x's date."""
    out = []
    for day in sorted(xs):
        y = ys.get(day + dt.timedelta(days=lag))
        if xs[day] is None or y is None:
            continue
        out.append({"date": day, "x": xs[day], "y": y})
    return out


def strength(rho: float | None) -> str | None:
    if rho is None:
        return None
    size = abs(rho)
    if size < 0.2:
        return "none"
    if size < 0.4:
        return "weak"
    if size < 0.6:
        return "moderate"
    return "strong"


def trend(points: list[dict]) -> dict | None:
    """Least-squares line of y on x, for the scatter's trend line."""
    if len(points) < 3:
        return None
    xs = [p["x"] for p in points]
    ys = [p["y"] for p in points]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    var = sum((x - mx) ** 2 for x in xs)
    if not var:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var
    return {"slope": round(slope, 4), "intercept": round(my - slope * mx, 4)}


def _rho_text(rho: float) -> str:
    return f"{rho:.2f}".replace("-", "−")


def sentence(x_noun: str, y_noun: str, lag: int, rho: float | None, n: int) -> str:
    if n < MIN_N:
        return (f"Not enough days with both {x_noun} and {y_noun} yet "
                f"(n = {n}; at least {MIN_N} needed).")
    if rho is None:
        return f"One of these didn't change over the range, so there is no pattern to show (n = {n})."
    stats = f"(ρ = {_rho_text(rho)}, n = {n})"
    if strength(rho) == "none":
        when = " the next day" if lag else ""
        return f"No clear link between {x_noun} and {y_noun}{when} {stats}."
    direction = "higher" if rho > 0 else "lower"
    if lag:
        return (f"Days with more {x_noun} tended to be followed by {direction} {y_noun} "
                f"the next day {stats}.")
    return f"Days with more {x_noun} tended to come with {direction} {y_noun} {stats}."


def compare(xs: dict[dt.date, float], ys: dict[dt.date, float], lag: int,
            x_noun: str, y_noun: str) -> dict:
    points = pair(xs, ys, lag)
    n = len(points)
    rho = spearman([p["x"] for p in points], [p["y"] for p in points]) if n >= 3 else None
    rho = round(rho, 2) if rho is not None else None
    enough = n >= MIN_N and rho is not None
    return {
        "points": [{"date": p["date"], "x": p["x"], "y": p["y"]} for p in points],
        "n": n, "rho": rho if n >= 3 else None,
        "strength": strength(rho) if enough else None,
        "direction": (("positive" if rho > 0 else "negative")
                      if enough and strength(rho) != "none" else None),
        "enough_data": enough,
        "trend": trend(points),
        "sentence": sentence(x_noun, y_noun, lag, rho, n),
        "caveat": CAVEAT,
    }
