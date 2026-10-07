"""Habits maths (R8 §B): series, streaks, quit savings, milestones and the impact of a
habit on the next morning's numbers. Pure — dates and numbers in, dicts out.

Impact is association, never causation: "on nights after drinking your HRV was X lower
on average (n=…)". A comparison is only `enough_data` with >= 5 nights in each group,
and only a difference past a meaningful threshold gets a direction.
"""

from __future__ import annotations

import datetime as dt
import statistics

MIN_N = 5
# metric -> (label, unit, threshold, threshold is relative?, higher is better?)
METRICS = {
    "hrv": ("Overnight HRV", "ms", 0.05, True, True),
    "rhr": ("Resting HR", "bpm", 2.0, False, False),
    "sleep_score": ("Sleep score", "", 3.0, False, True),
    "body_battery": ("Body Battery high", "", 5.0, False, True),
    "stress": ("Average stress", "", 3.0, False, False),
    "sleep_respiration": ("Sleep breathing rate", "brpm", 0.5, False, False),
    # Runs on the day after: lower HR at easy pace / higher efficiency / lower drift = better.
    "easy_hr": ("HR on easy runs", "bpm", 2.0, False, False),
    "efficiency": ("Efficiency (speed ÷ HR)", "m/min/bpm", 0.03, True, True),
    "hr_drift": ("HR drift", "%", 1.0, False, False),
}
HABIT_WORDS = {"smoke": "smoking", "alcohol": "drinking", "sugar": "sugary food",
               "private": "a Private day"}

# General public-health timeline after the last cigarette, shown as "typically".
MILESTONES = [
    (dt.timedelta(minutes=20), "20 minutes: heart rate and blood pressure typically start "
                               "to come down"),
    (dt.timedelta(hours=12), "12 hours: carbon monoxide in the blood typically falls to "
                             "normal"),
    (dt.timedelta(hours=24), "24 hours: nicotine is typically mostly out of the blood"),
    (dt.timedelta(hours=48), "48 hours: taste and smell typically start to improve"),
    (dt.timedelta(weeks=2), "2 weeks: circulation and lung function typically begin to "
                            "improve"),
    (dt.timedelta(days=30), "1 month: coughing and shortness of breath typically ease"),
    (dt.timedelta(days=90), "3 months: lung function typically keeps improving — "
                            "running feels easier"),
    (dt.timedelta(days=365), "1 year: the extra risk of heart disease is typically about "
                             "half a smoker's"),
]


def daily_totals(logs: list[tuple[dt.date, float]]) -> dict[dt.date, float]:
    out: dict[dt.date, float] = {}
    for day, qty in logs:
        out[day] = out.get(day, 0.0) + float(qty or 0)
    return out


def series(totals: dict[dt.date, float], start: dt.date, end: dt.date) -> list[dict]:
    days = (end - start).days + 1
    return [{"date": (start + dt.timedelta(days=i)).isoformat(),
             "count": round(totals.get(start + dt.timedelta(days=i), 0.0), 2)}
            for i in range(max(days, 0))]


def trend_per_week(points: list[dict]) -> float | None:
    """Least-squares slope of the daily count, per week (negative = cutting down)."""
    if len(points) < 3:
        return None
    xs = list(range(len(points)))
    ys = [p["count"] for p in points]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    var = sum((x - mx) ** 2 for x in xs)
    if not var:
        return None
    return round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var * 7, 2)


def streak(totals: dict[dt.date, float], today: dt.date, tracking_start: dt.date | None) -> dict:
    """Smoke-free days. Counted only from when tracking began (quit date or first log):
    a day before anyone was logging is not a smoke-free day. Today counts while it is
    still clean."""
    if tracking_start is None or tracking_start > today:
        return {"current_days": 0, "best_days": 0}
    best = run = 0
    day = tracking_start
    while day <= today:
        run = run + 1 if totals.get(day, 0) <= 0 else 0
        best = max(best, run)
        day += dt.timedelta(days=1)
    return {"current_days": run, "best_days": best}


def since_quit(quit_date: dt.date | None, today: dt.date, baseline_per_day: float | None,
               price: float | None, smoked_since: float) -> dict | None:
    if quit_date is None:
        return None
    days = max((today - quit_date).days, 0)
    avoided = None
    if baseline_per_day:
        avoided = round(max(baseline_per_day * days - smoked_since, 0.0), 1)
    money = round(avoided * price, 2) if avoided is not None and price else None
    return {"days": days, "cigarettes_avoided": avoided, "money_saved": money}


def milestones(quit_at: dt.datetime | None, now: dt.datetime) -> list[dict]:
    if quit_at is None:
        return []
    return [{"label": label, "reached": now >= quit_at + offset,
             "at": (quit_at + offset).isoformat()} for offset, label in MILESTONES]


def compare(habit: str, metric: str, with_values: list[float], without_values: list[float],
            dose: str | None = None) -> dict:
    """One impact row: with vs without, n each, direction past the metric's threshold."""
    label_name, unit, threshold, relative, higher_better = METRICS[metric]
    n_with, n_without = len(with_values), len(without_values)
    with_avg = round(statistics.mean(with_values), 1) if with_values else None
    without_avg = round(statistics.mean(without_values), 1) if without_values else None
    diff = diff_pct = None
    if with_avg is not None and without_avg is not None:
        diff = round(with_avg - without_avg, 2)
        diff_pct = round(diff / without_avg * 100, 1) if without_avg else None
    enough = n_with >= MIN_N and n_without >= MIN_N
    direction = "no_clear_difference"
    if enough and diff is not None:
        size = abs(diff / without_avg) if relative and without_avg else abs(diff)
        if size >= threshold:
            better = (diff > 0) == higher_better
            direction = "better" if better else "worse"
    return {"habit": habit, "metric": metric, "dose": dose,
            "label": _label(habit, metric, label_name, unit, diff, n_with, n_without, dose),
            "with_avg": with_avg, "without_avg": without_avg, "diff": diff,
            "diff_pct": diff_pct, "n_with": n_with, "n_without": n_without,
            "direction": direction, "enough_data": enough}


def _label(habit, metric, name, unit, diff, n_with, n_without, dose) -> str:
    after = "the day after" if metric in ("easy_hr", "efficiency", "hr_drift") else \
        "the morning after"
    words = HABIT_WORDS.get(habit, habit)
    if dose:
        words = f"{dose} drinks"
    if diff is None:
        return f"{name}: not enough data yet {after} {words}."
    amount = f"{abs(diff):g}{(' ' + unit) if unit else ''}"
    side = "higher" if diff > 0 else "lower" if diff < 0 else "no different"
    if side == "no different":
        return (f"{name} {after} {words} was about the same as on other days "
                f"(n={n_with} vs {n_without}).")
    return (f"{name} {after} {words} was {amount} {side} on average "
            f"(n={n_with} vs {n_without}).")


def impact(habit: str, totals: dict[dt.date, float], days: list[dt.date],
           mornings: dict[dt.date, dict], runs: dict[dt.date, dict]) -> list[dict]:
    """Exposure day D (>= 1 log) vs clean day D (none): metrics dated D+1 (the morning
    after) and runs on D+1. `days` are the days to consider (tracking window)."""
    rows = []
    for metric in METRICS:
        source = runs if metric in ("easy_hr", "efficiency", "hr_drift") else mornings
        with_v, without_v = [], []
        for day in days:
            value = (source.get(day + dt.timedelta(days=1)) or {}).get(metric)
            if value is None:
                continue
            (with_v if totals.get(day, 0) > 0 else without_v).append(float(value))
        rows.append(compare(habit, metric, with_v, without_v))
    if habit == "alcohol":
        rows += _dose_rows(totals, days, mornings)
    return rows


def _dose_rows(totals, days, mornings) -> list[dict]:
    """1-2 vs 3+ drinks, HRV only, when both dose groups have at least 3 nights."""
    clean, low, high = [], [], []
    for day in days:
        value = (mornings.get(day + dt.timedelta(days=1)) or {}).get("hrv")
        if value is None:
            continue
        qty = totals.get(day, 0)
        (clean if qty <= 0 else low if qty < 3 else high).append(float(value))
    if len(low) < 3 or len(high) < 3:
        return []
    return [compare("alcohol", "hrv", low, clean, dose="1-2"),
            compare("alcohol", "hrv", high, clean, dose="3+")]


def weekly(start: dt.date, end: dt.date, habit_totals: dict[str, dict[dt.date, float]],
           mornings: dict[dt.date, dict], runs: dict[dt.date, dict]) -> list[dict]:
    """Monday weeks: habit sums and the mean HRV / RHR / sleep score / easy pace /
    efficiency for that week."""
    monday = start - dt.timedelta(days=start.weekday())
    out = []
    while monday <= end:
        week = [monday + dt.timedelta(days=i) for i in range(7)]

        def total(kind):
            return round(sum(habit_totals.get(kind, {}).get(d, 0) for d in week), 1)

        def avg(source, key, digits=1):
            vals = [source[d][key] for d in week if d in source and source[d].get(key) is not None]
            return round(statistics.mean(vals), digits) if vals else None

        out.append({"week_start": monday.isoformat(), "cigarettes": total("smoke"),
                    "drinks": total("alcohol"), "sugar": total("sugar"),
                    "hrv_avg": avg(mornings, "hrv"), "rhr_avg": avg(mornings, "rhr"),
                    "sleep_score_avg": avg(mornings, "sleep_score"),
                    "easy_pace_s_per_km": avg(runs, "easy_pace", 0),
                    "efficiency": avg(runs, "efficiency", 3)})
        monday += dt.timedelta(days=7)
    return out


# --- R9 §C: the habit health report ----------------------------------------------
# "Has it improved or hurt me?" Every sentence below describes an association in the
# athlete's own numbers ("on mornings after …, your HRV averaged …", "weeks with more …
# tended to have …") — never a cause. Each finding appears only past its data
# threshold; what is still missing is listed in one neutral "keep logging" finding.

STEADY_PCT = 10.0
MIN_TREND_DAYS = 7
MIN_DOSE_N = 3
MIN_TIMING_N = 4
MIN_WEEKS = 6
MIN_RHO = 0.4
MIN_WEEK_VALUES = 3
MIN_QUIT_DAYS = 7
QUIT_BEFORE_DAYS = 14
MIN_QUIT_N = 5
MIN_RUN_N = 3
MIN_GARMIN_N = 3
LATE_HOUR = 21

MORNING_KEYS = ("hrv", "rhr", "sleep_score", "body_battery", "stress", "sleep_respiration")
RUN_KEYS = ("easy_hr", "efficiency")
SHORT = {"hrv": "HRV", "rhr": "resting HR", "sleep_score": "sleep score",
         "body_battery": "Body Battery high", "stress": "stress",
         "sleep_respiration": "sleep breathing rate", "easy_hr": "easy-pace HR",
         "efficiency": "efficiency", "hr_drift": "HR drift"}
HABIT_NAMES = {"smoke": "Cigarettes", "alcohol": "Drinks", "sugar": "Sugar",
               "private": "Private"}
WEEK_NOUNS = {"smoke": "cigarettes", "alcohol": "drinks", "sugar": "sugar servings",
              "private": "Private logs"}
AFTER_WORDS = {"smoke": "smoking", "alcohol": "drinking", "sugar": "sugary food",
               "private": "a Private day"}
LATE_WORDS = {"alcohol": ("drinking after 21:00", "earlier drinking"),
              "sugar": ("sugary food after 21:00", "earlier sugary food"),
              "private": ("a Private log after 21:00", "earlier Private logs")}
TIMING_HABITS = ("alcohol", "sugar", "private")
# report key -> (source, source key, label, unit, METRICS key for the threshold)
GARMIN = [
    ("hrv", "mornings", "hrv", "Overnight HRV", "ms", "hrv"),
    ("rhr", "mornings", "rhr", "Resting HR", "bpm", "rhr"),
    ("sleep_score", "mornings", "sleep_score", "Sleep score", "", "sleep_score"),
    ("stress", "mornings", "stress", "Average stress", "", "stress"),
    ("body_battery_high", "mornings", "body_battery", "Body Battery high", "", "body_battery"),
    ("respiration", "mornings", "sleep_respiration", "Sleep breathing rate", "brpm",
     "sleep_respiration"),
    ("easy_pace_hr", "runs", "easy_hr", "HR on easy runs", "bpm", "easy_hr"),
    ("efficiency", "runs", "efficiency", "Efficiency (speed ÷ HR)", "m/min/bpm", "efficiency"),
]


def _days(first: dt.date | None, last: dt.date) -> list[dt.date]:
    if first is None or first > last:
        return []
    return [first + dt.timedelta(days=i) for i in range((last - first).days + 1)]


def _mean(values) -> float | None:
    values = [float(v) for v in values if v is not None]
    return statistics.mean(values) if values else None


def _digits(metric: str) -> int:
    return 3 if metric == "efficiency" else 1


def _better(metric: str, diff: float | None, base: float | None) -> bool | None:
    """True / False past the metric's threshold (METRICS), else None."""
    if diff is None or base is None:
        return None
    _, _, threshold, relative, higher_better = METRICS[metric]
    if relative:
        if not base:
            return None
        size = abs(diff / base)
    else:
        size = abs(diff)
    if size < threshold:
        return None
    return (diff > 0) == higher_better


def _amount_text(metric: str, diff: float) -> str:
    unit = METRICS[metric][1]
    value = f"{abs(round(diff, _digits(metric))):g}"
    return f"{value} {unit}".strip() if unit else value


def _minus(text: str) -> str:
    return text.replace("-", "−")


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Spearman's rank correlation (average ranks for ties). None when either side is
    constant or there are fewer than 3 pairs."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None

    def ranks(values):
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            for k in range(i, j + 1):
                out[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return out

    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if not sxx or not syy:
        return None
    return sxy / (sxx * syy) ** 0.5


def garmin_compare(mornings: dict[dt.date, dict], runs: dict[dt.date, dict],
                   start: dt.date, end: dt.date, prev_start: dt.date,
                   prev_end: dt.date) -> list[dict]:
    """The range against the same-length range before it, one row per metric. A side
    needs >= 3 days with a value, else it is null."""
    sources = {"mornings": mornings, "runs": runs}
    rows = []
    for key, source, field, label, unit, threshold_key in GARMIN:
        data = sources[source]

        def side(first, last):
            values = [v[field] for d, v in data.items()
                      if first <= d <= last and v.get(field) is not None]
            return _mean(values) if len(values) >= MIN_GARMIN_N else None

        now, before = side(start, end), side(prev_start, prev_end)
        digits = _digits(field)
        delta = round(now - before, digits) if now is not None and before is not None else None
        rows.append({"metric": key, "label": label, "unit": unit,
                     "now": round(now, digits) if now is not None else None,
                     "before": round(before, digits) if before is not None else None,
                     "delta": delta, "better": _better(threshold_key, delta, before)})
    return rows


def amount_trend(totals: dict[dt.date, float], start: dt.date, end: dt.date,
                 prev_start: dt.date, prev_end: dt.date, tracking: dt.date | None) -> dict:
    """Per-day amount now vs the previous range, over the tracked days of each. A trend
    needs >= 7 tracked days on both sides; ±10 % is steady."""
    cur = _days(max(start, tracking) if tracking else None, end)
    prev = _days(max(prev_start, tracking) if tracking else None, prev_end)
    now = sum(totals.get(d, 0) for d in cur) / len(cur) if cur else None
    before = sum(totals.get(d, 0) for d in prev) / len(prev) if prev else None
    change = None
    if now is not None and before is not None:
        change = round((now - before) / before * 100, 1) if before else (0.0 if not now else None)
    direction = None
    if len(cur) >= MIN_TREND_DAYS and len(prev) >= MIN_TREND_DAYS:
        if not before:
            direction = "steady" if not now else "up"
        elif change <= -STEADY_PCT:
            direction = "down"
        elif change >= STEADY_PCT:
            direction = "up"
        else:
            direction = "steady"
    return {"now_per_day": round(now, 2) if now is not None else None,
            "before_per_day": round(before, 2) if before is not None else None,
            "change_pct": change,
            "now_per_week": round(now * 7, 1) if now is not None else None,
            "before_per_week": round(before * 7, 1) if before is not None else None,
            "direction": direction, "days_now": len(cur), "days_before": len(prev)}


def _finding(tone: str, text: str, kind: str, **internal) -> dict:
    return {"tone": tone, "text": text, "kind": kind, **internal}


def _amount_finding(habit: str, amount: dict, previous_label: str) -> dict:
    weekly = habit == "alcohol"
    now = amount["now_per_week" if weekly else "now_per_day"]
    before = amount["before_per_week" if weekly else "before_per_day"]
    per = "a week" if weekly else "a day"
    pct = amount["change_pct"]
    change = f" ({_minus(f'{pct:+.0f}')}%)" if pct is not None else ""
    tone = {"down": "good", "up": "bad"}.get(amount["direction"], "neutral")
    return _finding(tone, f"{HABIT_NAMES[habit]}: {before:g} → {now:g} {per}{change} vs "
                          f"{previous_label}.", "amount")


def _next_morning(habit: str, rows: list[dict], missing: list[str]) -> list[dict]:
    after = AFTER_WORDS[habit]
    mine = [r for r in rows if r["habit"] == habit and r["metric"] in MORNING_KEYS
            and not r.get("dose")]
    enough = [r for r in mine if r["enough_data"]]
    if not enough:
        hrv = next((r for r in mine if r["metric"] == "hrv"), None)
        have = f"; you have {hrv['n_with']} and {hrv['n_without']}" if hrv else ""
        missing.append(f"next-morning effect (needs {MIN_N} mornings after {after} and "
                       f"{MIN_N} without{have})")
        return []
    out = []
    for r in enough:
        if r["direction"] == "no_clear_difference":
            continue
        side = "lower" if r["diff"] < 0 else "higher"
        out.append(_finding(
            "good" if r["direction"] == "better" else "bad",
            f"On mornings after {after}, your {SHORT[r['metric']]} averaged "
            f"{_amount_text(r['metric'], r['diff'])} {side} (n={r['n_with']} vs "
            f"{r['n_without']}).", "next_morning", _metric=r["metric"]))
    if not out:
        r = enough[0]
        out.append(_finding("neutral", f"Your morning numbers after {after} were about the "
                                       f"same as on other days (n={r['n_with']} vs "
                                       f"{r['n_without']}).", "next_morning"))
    return out


def _next_values(days, source, metric):
    return {d: (source.get(d + dt.timedelta(days=1)) or {}).get(metric) for d in days}


def _group_compare(metric, group_a, group_b):
    """(diff a − b, better, n_a, n_b) over the non-null values."""
    a = [v for v in group_a if v is not None]
    b = [v for v in group_b if v is not None]
    ma, mb = _mean(a), _mean(b)
    diff = round(ma - mb, _digits(metric)) if ma is not None and mb is not None else None
    return diff, _better(metric, diff, mb), len(a), len(b)


def _dose(totals, days, mornings, missing) -> list[dict]:
    out, counts = [], None
    for metric in ("hrv", "sleep_score"):
        values = _next_values(days, mornings, metric)
        low = [v for d, v in values.items() if 0 < totals.get(d, 0) < 3]
        high = [v for d, v in values.items() if totals.get(d, 0) >= 3]
        diff, better, n_high, n_low = _group_compare(metric, high, low)
        if metric == "hrv":
            counts = (n_low, n_high)
        if n_high < MIN_DOSE_N or n_low < MIN_DOSE_N:
            continue
        if better is None:
            text = (f"Your {SHORT[metric]} the morning after 3+ drinks was about the same as "
                    f"after 1–2 (n={n_high} vs {n_low}).")
            tone = "neutral"
        else:
            side = "lower" if diff < 0 else "higher"
            text = (f"After 3+ drinks, your {SHORT[metric]} the next morning averaged "
                    f"{_amount_text(metric, diff)} {side} than after 1–2 drinks "
                    f"(n={n_high} vs {n_low}).")
            tone = "bad" if better is False else "neutral"
        out.append(_finding(tone, text, "dose"))
    if not out:
        low, high = counts or (0, 0)
        missing.append(f"dose comparison (needs {MIN_DOSE_N} nights each of 1–2 and 3+ "
                       f"drinks; you have {low} and {high})")
    return out


def _timing(habit, totals, days, late_days, mornings, missing) -> list[dict]:
    late_word, early_word = LATE_WORDS[habit]
    exposed = [d for d in days if totals.get(d, 0) > 0]
    out, counts = [], (0, 0)
    for metric in ("sleep_score", "hrv"):
        values = _next_values(exposed, mornings, metric)
        late = [v for d, v in values.items() if d in late_days]
        early = [v for d, v in values.items() if d not in late_days]
        diff, better, n_late, n_early = _group_compare(metric, late, early)
        counts = max(counts, (n_late, n_early))
        if n_late < MIN_TIMING_N or n_early < MIN_TIMING_N:
            continue
        if better is None:
            text = (f"Your {SHORT[metric]} after {late_word} was about the same as after "
                    f"{early_word} (n={n_late} vs {n_early}).")
            tone = "neutral"
        else:
            side = "lower" if diff < 0 else "higher"
            text = (f"On mornings after {late_word}, your {SHORT[metric]} averaged "
                    f"{_amount_text(metric, diff)} {side} than after {early_word} "
                    f"(n={n_late} vs {n_early}).")
            tone = "bad" if better is False else "neutral"
        out.append(_finding(tone, text, "timing"))
    if not out:
        missing.append(f"timing (needs {MIN_TIMING_N} nights each with {late_word} and "
                       f"{early_word}; you have {counts[0]} and {counts[1]})")
    return out


def weekly_blocks(totals, mornings, start: dt.date, end: dt.date,
                  tracking: dt.date | None) -> list[dict]:
    """Full 7-day blocks ending on `end`, back to the range start and never before
    tracking began: the amount and the mean HRV / RHR / sleep score (>= 3 mornings)."""
    first = max(start, tracking) if tracking else None
    out = []
    block_end = end
    while first is not None and block_end - dt.timedelta(days=6) >= first:
        days = [block_end - dt.timedelta(days=i) for i in range(7)]
        row = {"start": days[-1], "amount": sum(totals.get(d, 0) for d in days)}
        for metric in ("hrv", "rhr", "sleep_score"):
            values = [mornings[d][metric] for d in days
                      if d in mornings and mornings[d].get(metric) is not None]
            row[metric] = _mean(values) if len(values) >= MIN_WEEK_VALUES else None
        out.append(row)
        block_end -= dt.timedelta(days=7)
    return list(reversed(out))


def _weekly_link(habit, totals, mornings, start, end, tracking, missing) -> list[dict]:
    blocks = weekly_blocks(totals, mornings, start, end, tracking)
    noun = WEEK_NOUNS[habit]
    out, best_n = [], 0
    for metric in ("hrv", "rhr", "sleep_score"):
        pairs = [(b["amount"], b[metric]) for b in blocks if b[metric] is not None]
        best_n = max(best_n, len(pairs))
        if len(pairs) < MIN_WEEKS:
            continue
        rho = spearman([p[0] for p in pairs], [p[1] for p in pairs])
        if rho is None or abs(rho) < MIN_RHO:
            continue
        side = "higher" if rho > 0 else "lower"
        worse = (rho > 0) != METRICS[metric][4]
        out.append(_finding("bad" if worse else "neutral",
                            f"Weeks with more {noun} tended to have {side} "
                            f"{SHORT[metric]} (ρ={_minus(f'{rho:.2f}')}, {len(pairs)} weeks).",
                            "weekly_link"))
    if not out and best_n >= MIN_WEEKS:
        out.append(_finding("neutral", f"No clear weekly link between {noun} and HRV, resting "
                                       f"HR or sleep score ({best_n} weeks).", "weekly_link"))
    elif not out and (end - start).days + 1 >= MIN_WEEKS * 7:
        missing.append(f"weekly link (needs {MIN_WEEKS} tracked weeks with morning data; "
                       f"you have {best_n})")
    return out


def _since_quit(quit_date, end, mornings, runs, missing) -> list[dict]:
    if quit_date is None:
        return []
    if (end - quit_date).days < MIN_QUIT_DAYS:
        missing.append(f"since-quit comparison (starts {MIN_QUIT_DAYS} days after your "
                       "quit date)")
        return []
    before = _days(quit_date - dt.timedelta(days=QUIT_BEFORE_DAYS),
                   quit_date - dt.timedelta(days=1))
    after = _days(quit_date, end)
    out = []
    for metric in ("hrv", "rhr", "sleep_score", "easy_hr"):
        source = runs if metric == "easy_hr" else mornings
        diff, better, n_after, n_before = _group_compare(
            metric, [(source.get(d) or {}).get(metric) for d in after],
            [(source.get(d) or {}).get(metric) for d in before])
        if n_after < MIN_QUIT_N or n_before < MIN_QUIT_N:
            continue
        if better is None:
            text = (f"Since you quit, your {SHORT[metric]} has been about the same as in the "
                    f"{QUIT_BEFORE_DAYS} days before (n={n_after} vs {n_before}).")
            tone = "neutral"
        else:
            side = "lower" if diff < 0 else "higher"
            text = (f"Since you quit, your {SHORT[metric]} averaged "
                    f"{_amount_text(metric, diff)} {side} than in the {QUIT_BEFORE_DAYS} "
                    f"days before (n={n_after} vs {n_before}).")
            tone = "good" if better else "bad"
        out.append(_finding(tone, text, "since_quit"))
    if not out:
        missing.append(f"since-quit comparison (needs {MIN_QUIT_N} days of data on each "
                       "side of your quit date)")
    return out


def _next_day_run(habit, totals, days, runs, missing) -> list[dict]:
    after = AFTER_WORDS[habit]
    out, counts = [], (0, 0)
    for metric in RUN_KEYS:
        values = _next_values(days, runs, metric)
        diff, better, n_with, n_without = _group_compare(
            metric, [v for d, v in values.items() if totals.get(d, 0) > 0],
            [v for d, v in values.items() if totals.get(d, 0) <= 0])
        counts = max(counts, (n_with, n_without))
        if n_with < MIN_RUN_N or n_without < MIN_RUN_N or better is None:
            continue
        side = "lower" if diff < 0 else "higher"
        out.append(_finding("good" if better else "bad",
                            f"On runs the day after {after}, your {SHORT[metric]} averaged "
                            f"{_amount_text(metric, diff)} {side} (n={n_with} vs "
                            f"{n_without}).", "next_day_run"))
    if not out and min(counts) >= MIN_RUN_N:
        out.append(_finding("neutral", f"Runs the day after {after} looked about the same as "
                                       f"other runs (n={counts[0]} vs {counts[1]}).",
                            "next_day_run"))
    elif not out:
        missing.append(f"next-day runs (needs {MIN_RUN_N} runs the day after {after} and "
                       f"{MIN_RUN_N} after other days; you have {counts[0]} and {counts[1]})")
    return out


def habit_report(habit: str, *, totals: dict[dt.date, float], start: dt.date, end: dt.date,
                 prev_start: dt.date, prev_end: dt.date, tracking: dt.date | None,
                 impact_rows: list[dict], prev_impact_rows: list[dict],
                 mornings: dict[dt.date, dict], runs: dict[dt.date, dict],
                 late_days: set[dt.date] | None = None, quit_date: dt.date | None = None,
                 previous_label: str = "the previous period") -> dict:
    """One habit's card: amount trend, status, headline and findings."""
    amount = amount_trend(totals, start, end, prev_start, prev_end, tracking)
    days = [d for d in _days(max(start, tracking) if tracking else None, end) if d < end]
    missing: list[str] = []
    findings = []
    if amount["direction"] is None:
        missing.append(f"amount trend (needs a week of tracking in this period and "
                       f"{previous_label})")
    else:
        findings.append(_amount_finding(habit, amount, previous_label))
    findings += _next_morning(habit, impact_rows, missing)
    if habit == "alcohol":
        findings += _dose(totals, days, mornings, missing)
    if habit in TIMING_HABITS:
        findings += _timing(habit, totals, days, late_days or set(), mornings, missing)
    findings += _weekly_link(habit, totals, mornings, start, end, tracking, missing)
    if habit == "smoke":
        findings += _since_quit(quit_date, end, mornings, runs, missing)
    findings += _next_day_run(habit, totals, days, runs, missing)
    if missing:
        findings.append(_finding("neutral", "Keep logging — still needed: "
                                 + "; ".join(missing) + ".", "keep_logging"))

    # A "new" bad finding: a next-morning metric that was not already worse in the
    # previous range, or a worse number since quitting.
    before_bad = {r["metric"] for r in prev_impact_rows if r["habit"] == habit
                  and r["enough_data"] and r["direction"] == "worse" and not r.get("dose")}
    new_bad = any(f["tone"] == "bad" and (
        (f["kind"] == "next_morning" and f.get("_metric") not in before_bad)
        or f["kind"] == "since_quit") for f in findings)
    direction = amount["direction"]
    if direction is None:
        status = "not_enough_data"
    elif direction == "down" and not new_bad:
        status = "improving"
    elif direction == "up":
        status = "worsening"
    else:
        status = "steady"
    return {"habit": habit, "status": status,
            "headline": _habit_headline(amount, previous_label),
            "amount": {k: amount[k] for k in ("now_per_day", "before_per_day", "change_pct",
                                              "now_per_week", "before_per_week")},
            "findings": [{k: f[k] for k in ("tone", "text", "kind")} for f in findings]}


def _habit_headline(amount: dict, previous_label: str) -> str:
    direction, pct = amount["direction"], amount["change_pct"]
    if direction is None:
        return "Keep logging to see a trend"
    if direction == "down":
        return f"Down {abs(pct):.0f}% vs {previous_label}"
    if direction == "up":
        return (f"Up {pct:.0f}% vs {previous_label}" if pct is not None
                else f"Up from none in {previous_label}")
    if not amount["now_per_day"] and not amount["before_per_day"]:
        return f"None logged here or in {previous_label}"
    return f"About the same as {previous_label}"


def _vitals_clause(garmin: list[dict]) -> str:
    parts = []
    for row in garmin:
        if row["metric"] in ("hrv", "rhr") and row["now"] is not None \
                and row["before"] is not None:
            name = "HRV" if row["metric"] == "hrv" else "resting HR"
            parts.append(f"{name} {row['before']:g} → {row['now']:g} {row['unit']}")
    return ("; " + ", ".join(parts)) if parts else ""


def overall(habits: list[dict], garmin: list[dict], previous_label: str) -> dict:
    """improving: most logged habits improving and HRV / resting HR not worse;
    worsening: most logged habits worsening; else steady."""
    logged = [h for h in habits if h["status"] != "not_enough_data"]
    if not logged:
        return {"status": "not_enough_data",
                "headline": f"Keep logging — the report compares this period with "
                            f"{previous_label}."}
    vitals_worse = any(r["better"] is False for r in garmin if r["metric"] in ("hrv", "rhr"))
    improving = sum(1 for h in logged if h["status"] == "improving")
    worsening = sum(1 for h in logged if h["status"] == "worsening")
    n, clause = len(logged), _vitals_clause(garmin)
    noun = "habit" if n == 1 else "habits"
    if improving * 2 > n and not vitals_worse:
        return {"status": "improving",
                "headline": f"{improving} of {n} {noun} improving vs {previous_label}{clause}"}
    if worsening * 2 > n:
        return {"status": "worsening",
                "headline": f"{worsening} of {n} {noun} up vs {previous_label}{clause}"}
    return {"status": "steady", "headline": f"Mostly steady vs {previous_label}{clause}"}


def report(habits: list[dict], garmin: list[dict], previous_label: str) -> dict:
    return {"overall": overall(habits, garmin, previous_label), "garmin": garmin,
            "habits": habits}
