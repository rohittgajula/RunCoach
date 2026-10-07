"""Weather report ratings and weather-smart rescheduling (R14 §3). Pure — no Django.

Hourly entries are the `/weather/today/` shape (local "YYYY-MM-DDTHH:MM" times, feels_like,
precip_prob, weather_code, aqi, …; any value may be None).

Rescheduling only ever MOVES a session (or swaps it with an optional walk): its content
never changes, so a move can't make training harder. It respects the plan's spacing —
a long or hard session never lands next to another long/hard/race day, nothing lands on
the day before a race — and never touches today, the past, completed sessions or races.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .weather_advice import THUNDER_CODES, WINDOW_HOURS

BAD_FEELS_C = 34.0
BAD_RAIN_PCT = 70
BAD_AQI = 150
POOR_FEELS_C, POOR_RAIN_PCT, POOR_AQI = 30.0, 40, 100
OK_FEELS_C, OK_AQI = 26.0, 50
LOOKAHEAD_DAYS = 3

RUN_KINDS = frozenset({"EASY", "RUN_WALK", "LONG", "TEMPO", "INTERVALS"})
DEMANDING = frozenset({"LONG", "TEMPO", "INTERVALS", "RACE"})
OCCUPYING = RUN_KINDS | {"RACE"}
RATING_RANK = {"good": 0, "ok": 1, "poor": 2, "bad": 3}
VERDICT_RANK = {"good": 0, "caution": 1, "bad": 2}
WEEKDAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
KIND_WORD = {"LONG": "long run", "TEMPO": "tempo run", "INTERVALS": "intervals",
             "EASY": "run", "RUN_WALK": "run/walk"}

AQI_LEVELS = [  # (upper bound, level, meaning)
    (50, "good", "Good — fine for any run."),
    (100, "moderate", "Moderate — fine for most; sensitive people keep it easy."),
    (150, "sensitive", "Unhealthy for sensitive groups — keep runs easy and shorter."),
    (200, "unhealthy", "Unhealthy — shorten the run or move it indoors."),
    (300, "very_unhealthy", "Very unhealthy — run indoors or rest."),
    (10**6, "hazardous", "Hazardous — don't exercise outside."),
]


def aqi_level(aqi) -> tuple[str | None, str | None]:
    if aqi is None:
        return None, None
    for bound, level, meaning in AQI_LEVELS:
        if aqi <= bound:
            return level, meaning
    return None, None  # pragma: no cover


def uv_level(uv) -> str | None:
    if uv is None:
        return None
    if uv < 3:
        return "low"
    if uv < 6:
        return "moderate"
    if uv < 8:
        return "high"
    if uv < 11:
        return "very_high"
    return "extreme"


def _feels(h: dict):
    value = h.get("feels_like")
    return h.get("temp") if value is None else value


def hour_problems(h: dict) -> list[str]:
    """Why this hour is unrunnable: heat | storm | rain | air (empty = runnable)."""
    out = []
    feels = _feels(h)
    if feels is not None and feels >= BAD_FEELS_C:
        out.append("heat")
    if h.get("weather_code") in THUNDER_CODES:
        out.append("storm")
    elif (h.get("precip_prob") or 0) >= BAD_RAIN_PCT:
        out.append("rain")
    if h.get("aqi") is not None and h["aqi"] > BAD_AQI:
        out.append("air")
    return out


def hour_rating(h: dict) -> str | None:
    feels = _feels(h)
    if feels is None and h.get("precip_prob") is None and h.get("aqi") is None:
        return None
    if hour_problems(h):
        return "bad"
    aqi, rain = h.get("aqi"), h.get("precip_prob") or 0
    if (feels is not None and feels >= POOR_FEELS_C) or rain >= POOR_RAIN_PCT or (
            aqi is not None and aqi > POOR_AQI):
        return "poor"
    if (feels is not None and feels >= OK_FEELS_C) or (aqi is not None and aqi > OK_AQI):
        return "ok"
    return "good"


def _hour(h: dict) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(h["time"])
    except (KeyError, TypeError, ValueError):
        return None


def candidates(hourly: list[dict], day: dt.date) -> list[dict]:
    """The hours a run could start on `day` (05–08 and 17–19 local)."""
    out = []
    for h in hourly:
        at = _hour(h)
        if at is not None and at.date() == day and at.hour in WINDOW_HOURS:
            out.append(h)
    return out


def _score(h: dict) -> float:
    feels = _feels(h)
    aqi = h.get("aqi")
    rain = h.get("precip_prob") or 0
    return ((feels if feels is not None else 25.0) + (max(aqi - 50, 0) / 10 if aqi else 0)
            + rain / 20)


REASON_TEXT = {
    "heat": "feels like {feels:.0f} °C even at its coolest ({time})",
    "storm": "thunderstorms forecast",
    "rain": "heavy rain likely ({rain}%)",
    "air": "unhealthy air (AQI {aqi:.0f})",
}


@dataclass
class DayCheck:
    date: dt.date
    verdict: str | None                  # good | caution | bad | None (no data)
    best: dict | None = None             # the best candidate hour
    reasons: list[dict] = field(default_factory=list)   # [{key, text}] when bad
    score: float | None = None

    def brief(self, hours: list[dict]) -> dict:
        day_hours = [h for h in hours if (_hour(h) or dt.datetime.min).date() == self.date]
        rains = [h.get("precip_prob") for h in day_hours if h.get("precip_prob") is not None]
        aqis = [h.get("aqi") for h in day_hours if h.get("aqi") is not None]
        best = self.best or {}
        return {"date": self.date.isoformat(),
                "best_feels_like": _feels(best) if self.best else None,
                "precip_prob_max": int(max(rains)) if rains else None,
                "aqi_max": max(aqis) if aqis else None,
                "condition": best.get("condition"), "verdict": self.verdict or "good"}


def check_day(hourly: list[dict], day: dt.date) -> DayCheck:
    hours = [h for h in candidates(hourly, day) if hour_rating(h) is not None]
    if not hours:
        return DayCheck(day, None)
    best = min(hours, key=_score)
    if all(hour_problems(h) for h in hours):
        keys: list[str] = []
        for h in hours:
            for key in hour_problems(h):
                if key not in keys:
                    keys.append(key)
        coolest = min(hours, key=lambda h: _feels(h) if _feels(h) is not None else 99)
        reasons = []
        for key in keys:
            if key == "heat":
                text = REASON_TEXT["heat"].format(feels=_feels(coolest),
                                                  time=coolest["time"][11:16])
            elif key == "rain":
                text = REASON_TEXT["rain"].format(rain=int(max(h.get("precip_prob") or 0
                                                               for h in hours)))
            elif key == "air":
                text = REASON_TEXT["air"].format(aqi=min(h["aqi"] for h in hours
                                                         if h.get("aqi") is not None))
            else:
                text = REASON_TEXT[key]
            reasons.append({"key": key, "text": text})
        return DayCheck(day, "bad", best, reasons, _score(best))
    rating = hour_rating(best)
    return DayCheck(day, "caution" if rating == "poor" else "good", best, [], _score(best))


def day_reasons(check: DayCheck) -> list[str]:
    if check.verdict == "bad":
        return [r["text"][0].upper() + r["text"][1:] for r in check.reasons]
    if check.verdict == "caution" and check.best:
        feels = _feels(check.best)
        bits = []
        if feels is not None and feels >= POOR_FEELS_C:
            bits.append(f"Warm even at the best time (feels {feels:.0f} °C) — go by heart rate")
        if (check.best.get("precip_prob") or 0) >= POOR_RAIN_PCT:
            bits.append("Rain likely — watch your footing")
        if check.best.get("aqi") is not None and check.best["aqi"] > POOR_AQI:
            bits.append(f"Poor air (AQI {check.best['aqi']:.0f}) — keep it easy")
        return bits
    return []


def best_windows(hourly: list[dict], now: dt.datetime, hours: int = 48) -> list[dict]:
    """One best start hour per local day in the next `hours`, from now on."""
    now = now.replace(tzinfo=None, minute=0, second=0, microsecond=0)
    by_day: dict[dt.date, dict] = {}
    for h in hourly:
        at = _hour(h)
        if at is None or not now <= at < now + dt.timedelta(hours=hours):
            continue
        if at.hour not in WINDOW_HOURS or hour_rating(h) in (None, "bad"):
            continue
        current = by_day.get(at.date())
        if current is None or _score(h) < _score(current):
            by_day[at.date()] = h
    out = []
    for day in sorted(by_day):
        h = by_day[day]
        start = _hour(h)
        feels = _feels(h)
        reason = f"Coolest slot: feels like {feels:.0f}°C" if feels is not None else "Best slot"
        if h.get("aqi") is not None:
            reason += f", AQI {h['aqi']:.0f}"
        out.append({"date": day.isoformat(), "start": start.isoformat(timespec="minutes"),
                    "end": (start + dt.timedelta(hours=1)).isoformat(timespec="minutes"),
                    "reason": reason, "feels_like": feels, "aqi": h.get("aqi")})
    return out


# --- rescheduling ------------------------------------------------------------------------

@dataclass(frozen=True)
class Session:
    id: int
    date: dt.date
    kind: str
    status: str = "planned"          # planned | completed | skipped


@dataclass(frozen=True)
class Proposal:
    workout_id: int
    from_date: dt.date
    to_date: dt.date
    action: str                      # move | swap
    swap_with: int | None
    reasons: tuple                   # ({key, text}, …)


def _monday(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


def runs_on(sessions: list[Session], day: dt.date, exclude: set[int] = frozenset()) -> list:
    return [s for s in sessions if s.date == day and s.id not in exclude
            and s.status != "skipped" and s.kind in OCCUPYING]


def spacing_ok(session: Session, to_date: dt.date, sessions: list[Session],
               exclude: set[int] = frozenset()) -> bool:
    """Would `session` on `to_date` keep the plan's spacing? `exclude`: ids that move
    away with it (a swap partner)."""
    others = [s for s in sessions if s.id != session.id and s.id not in exclude
              and s.status != "skipped"]
    races = {s.date for s in others if s.kind == "RACE"}
    if to_date + dt.timedelta(days=1) in races or to_date in races:
        return False
    if session.kind in DEMANDING:
        demanding = {s.date for s in others if s.kind in DEMANDING}
        if any(to_date + dt.timedelta(days=d) in demanding for d in (-1, 1)):
            return False
    return True


def target_ok(session: Session, to_date: dt.date, sessions: list[Session], *,
              today: dt.date, available: set[int], last_date: dt.date | None) -> tuple[bool, int | None]:
    """(ok, id of the walk to swap with). Same Mon–Sun week, after today, an available
    training day, no other run there, before the race, spacing kept."""
    if to_date <= today or to_date == session.date or _monday(to_date) != _monday(session.date):
        return False, None
    if last_date is not None and to_date > last_date:
        return False, None
    if to_date.weekday() not in available:
        return False, None
    if runs_on(sessions, to_date, {session.id}):
        return False, None
    walk = next((s for s in sessions if s.date == to_date and s.kind == "WALK"
                 and s.status == "planned"), None)
    exclude = {walk.id} if walk else set()
    if not spacing_ok(session, to_date, sessions, exclude):
        return False, None
    return True, walk.id if walk else None


def propose(sessions: list[Session], checks: dict[dt.date, DayCheck], *, today: dt.date,
            available: set[int], last_date: dt.date | None = None,
            skip: set[tuple[int, dt.date]] = frozenset()) -> list[Proposal]:
    """Moves for planned runs today+1 … today+3 on a bad-weather day, to a better day in
    the same week. `skip`: (workout id, date) pairs already suggested or dismissed."""
    out: list[Proposal] = []
    taken: set[dt.date] = set()
    working = list(sessions)
    for s in sorted(sessions, key=lambda x: (x.date, x.id)):
        if s.status != "planned" or s.kind not in RUN_KINDS:
            continue
        if not today < s.date <= today + dt.timedelta(days=LOOKAHEAD_DAYS):
            continue
        if (s.id, s.date) in skip:
            continue
        check = checks.get(s.date)
        if check is None or check.verdict != "bad":
            continue
        options = []
        for offset in range(-6, 7):
            day = s.date + dt.timedelta(days=offset)
            if day in taken:
                continue
            target = checks.get(day)
            if target is None or target.verdict in (None, "bad"):
                continue
            ok, walk = target_ok(s, day, working, today=today, available=available,
                                 last_date=last_date)
            if not ok:
                continue
            options.append((VERDICT_RANK[target.verdict], target.score or 0, abs(offset),
                            day, walk))
        if not options:
            continue
        _, _, _, day, walk = min(options)
        taken.add(day)
        out.append(Proposal(s.id, s.date, day, "swap" if walk else "move", walk,
                            tuple(check.reasons)))
        # Later decisions see this one as made.
        working = [Session(x.id, day if x.id == s.id else (s.date if x.id == walk else x.date),
                           x.kind, x.status) for x in working]
    return out


def text_for(kind: str, from_date: dt.date, to_date: dt.date) -> str:
    word = KIND_WORD.get(kind, "run")
    return f"Weather: move {WEEKDAY[from_date.weekday()]} {word} to {WEEKDAY[to_date.weekday()]}?"


def reason_for(from_check: DayCheck, to_check: DayCheck | None, from_date: dt.date,
               to_date: dt.date) -> str:
    first = "; ".join(r["text"] for r in from_check.reasons) or "bad weather"
    text = f"{WEEKDAY[from_date.weekday()]}: {first}."
    if to_check is not None and to_check.best is not None:
        feels = _feels(to_check.best)
        when = to_check.best["time"][11:16]
        if feels is not None:
            text += f" {WEEKDAY[to_date.weekday()]} {when}: feels like {feels:.0f} °C."
    return text
