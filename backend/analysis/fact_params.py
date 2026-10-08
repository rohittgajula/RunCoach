"""R18: structured profile parameters from a memory fact's text. Pure, deterministic.

`parse(text, current_days=None)` → [Param]. A parse the text supports only weakly (a one-off
"slept 6 h last night", "I run at 6" without am/pm) gets confidence < REVIEW_BELOW and is
stored as needs_review — never applied until the athlete confirms it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

REVIEW_BELOW = 0.75

LABELS = {"sleep_need_minutes": "Sleep need", "usual_run_time": "Usual run time",
          "loop_distance_km": "Loop distance", "available_days": "Run days",
          "long_run_day": "Long-run day", "runs_per_week": "Runs per week"}
UNITS = {"sleep_need_minutes": "min", "usual_run_time": "time", "loop_distance_km": "km",
         "available_days": "days", "long_run_day": "weekday", "runs_per_week": "per_week"}
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

_DAY = (r"(mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?|fri(?:day)?|"
        r"sat(?:urday)?|sun(?:day)?)s?")
_DAY_RE = re.compile(rf"\b{_DAY}\b", re.IGNORECASE)
_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
              "eight": 8, "nine": 9, "ten": 10, "once": 1, "twice": 2}


@dataclass
class Param:
    key: str
    value: object
    confidence: float

    @property
    def unit(self) -> str:
        return UNITS[self.key]

    @property
    def needs_review(self) -> bool:
        return self.confidence < REVIEW_BELOW


def _day_index(token: str) -> int:
    return ("mon", "tue", "wed", "thu", "fri", "sat", "sun").index(token.lower()[:3])


def _num(token: str) -> float | None:
    token = token.lower()
    if token in _NUM_WORDS:
        return float(_NUM_WORDS[token])
    try:
        return float(token)
    except ValueError:
        return None


# --- sleep ----------------------------------------------------------------------------

_SLEEP_H = re.compile(
    r"(\d{1,2}(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten)\s*"
    r"(?:-|to)?\s*(?:h|hr|hrs|hours?)\b(?:\s*(?:and\s*)?(\d{1,2})\s*(?:m|min|mins|minutes)\b)?",
    re.IGNORECASE)
# "sleep ≈ 7", "sleep need: 7.5" — a bare number right after "sleep" is hours.
_SLEEP_BARE = re.compile(
    r"\bsleep\w*\b(?:\s+need\w*)?\s*(?:is|of|=|:|≈|~|about|around|roughly|approx\w*|\s)*"
    r"(\d{1,2}(?:\.\d+)?)\b(?!\s*(?:am|pm|:|km|min|%))()", re.IGNORECASE)
_SLEEP_HM = re.compile(r"\b(\d{1,2})h(\d{2})\b", re.IGNORECASE)
_SLEEP_FIRM = re.compile(r"\b(need|needs|require|target|enough|usually|normally|typically|"
                         r"works? (?:best|well|for me)|is fine|ideal|should get|aim|prefer|"
                         r"function|feel (?:best|good|fine)|optimal|at least)\b", re.IGNORECASE)
_SLEEP_ONEOFF = re.compile(r"\b(last night|yesterday|tonight|only slept|slept|this week|"
                           r"lately|recently)\b", re.IGNORECASE)


def _sleep(text: str) -> Param | None:
    if not re.search(r"\bsleep|\bslept|\bbed\b|\bnight", text, re.IGNORECASE):
        return None
    hm = _SLEEP_HM.search(text)
    if hm:
        minutes = int(hm.group(1)) * 60 + int(hm.group(2))
    else:
        m = _SLEEP_H.search(text) or _SLEEP_BARE.search(text)
        if not m:
            return None
        hours = _num(m.group(1))
        if m.re is _SLEEP_BARE and not (4 <= (hours or 0) <= 12):
            return None
        if hours is None:
            return None
        minutes = round(hours * 60) + (int(m.group(2)) if m.group(2) else 0)
    if not 240 <= minutes <= 720:
        return None
    firm = bool(_SLEEP_FIRM.search(text))
    oneoff = bool(_SLEEP_ONEOFF.search(text))
    confidence = 0.95 if firm and not oneoff else 0.6 if oneoff else 0.8
    return Param("sleep_need_minutes", int(minutes), confidence)


# --- usual run time ---------------------------------------------------------------------

_RUN_TIME = re.compile(
    r"\b(?:run|runs|running|jog|jogs|jogging|train|training)\b[^.?!]{0,40}?"
    r"\b(?:at|around|by|from|before|after)\s*(?:about\s*|~\s*)?"
    r"(\d{1,2})(?:[:.](\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?(?![\d.]*\s*(?:km|k\b|m\b|mi))",
    re.IGNORECASE)
_RUN_TIME_PRE = re.compile(
    r"\b(\d{1,2})(?:[:.](\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\s*(?:runs?|jogs?|training)\b",
    re.IGNORECASE)
_HABITUAL = re.compile(r"\b(usually|normally|always|every|typically|prefer|tend to|mostly|"
                       r"generally|my runs|i run)\b", re.IGNORECASE)


def _run_time(text: str) -> Param | None:
    m = _RUN_TIME.search(text) or _RUN_TIME_PRE.search(text)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    ampm = (m.group(3) or "").lower().replace(".", "")
    if hour > 23 or minute > 59:
        return None
    lower = text.lower()
    confidence = 0.95 if _HABITUAL.search(text) else 0.8
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    elif not ampm and hour <= 12:
        if re.search(r"evening|after work|night|afternoon", lower):
            hour = hour + 12 if hour < 12 else hour
        elif re.search(r"morning|before work|early|dawn|sunrise", lower):
            pass
        else:
            confidence = min(confidence, 0.6)        # "run at 6" — am or pm?
            if hour < 5:
                hour += 12
    return Param("usual_run_time", f"{hour:02d}:{minute:02d}", confidence)


# --- loop distance ---------------------------------------------------------------------

_DIST = r"(\d+(?:\.\d+)?)\s*(km|k|kms|kilomet(?:er|re)s?|m|meters?|metres?|mi|miles?)\b"
_LOOP_AFTER = re.compile(rf"\b(?:loop|lap|route|circuit|park|track|block)\b[^.?!]{{0,30}}?{_DIST}",
                         re.IGNORECASE)
_LOOP_BEFORE = re.compile(rf"{_DIST}[\s-]*(?:long\s+)?(?:loop|lap|route|circuit|track)\b",
                          re.IGNORECASE)


def _loop(text: str) -> Param | None:
    m = _LOOP_BEFORE.search(text) or _LOOP_AFTER.search(text)
    if not m:
        return None
    value, unit = float(m.group(1)), m.group(2).lower()
    if unit.startswith("mi"):
        km = value * 1.609
    elif unit in ("m", "meter", "meters", "metre", "metres"):
        km = value / 1000
    else:
        km = value
    if not 0.1 <= km <= 50:
        return None
    confidence = 0.9 if re.search(r"\bloop|\blap|\bcircuit", text, re.IGNORECASE) else 0.7
    return Param("loop_distance_km", round(km, 2), confidence)


# --- runs per week --------------------------------------------------------------------

_PER_WEEK = re.compile(
    r"\b(\d|one|two|three|four|five|six|seven|once|twice)\s*(?:runs?|times|days|sessions)?\s*"
    r"(?:a|per|each|every)\s*week\b", re.IGNORECASE)


def _runs_per_week(text: str) -> Param | None:
    if not re.search(r"\brun|\bjog|\btrain", text, re.IGNORECASE):
        return None
    m = _PER_WEEK.search(text)
    if not m:
        return None
    n = _num(m.group(1))
    if n is None or not 2 <= n <= 6:
        return None
    return Param("runs_per_week", int(n), 0.9)


# --- long-run day / available days -----------------------------------------------------

_LONG_RUN = re.compile(rf"\blong[\s-]?runs?\b[^.?!]{{0,25}}?\b(?:on\s+)?{_DAY}\b|"
                       rf"\b{_DAY}\b[^.?!]{{0,20}}?\blong[\s-]?runs?\b", re.IGNORECASE)


def _long_run_day(text: str) -> Param | None:
    m = _LONG_RUN.search(text)
    if not m:
        return None
    token = m.group(1) or m.group(2)
    return Param("long_run_day", _day_index(token), 0.9)


_NEG = re.compile(r"\b(can't|cannot|can not|won't|don't|do not|never|no|not)\b|n't\b",
                  re.IGNORECASE)


def _available(text: str, current_days: dict | None) -> Param | None:
    lower = text.lower()
    if not re.search(r"\b(run|runs|running|train|training|jog|available|free)\b", lower):
        return None
    if _LONG_RUN.search(text) and not re.search(r"\bonly\b|\bavailable\b|\bcan run\b", lower):
        return None                         # "long run on Sunday" is the long-run day, not days
    days = {_day_index(m.group(1)) for m in _DAY_RE.finditer(text)}
    if "weekend" in lower:
        days |= {5, 6}
    if "weekday" in lower:
        days |= {0, 1, 2, 3, 4}
    if not days:
        return None
    if _NEG.search(text):
        base = {int(k) for k, v in (current_days or {}).items() if v} or set(range(7))
        chosen = base - days
        confidence = 0.8
    else:
        chosen = days
        confidence = 0.9 if re.search(r"\bonly\b|\bavailable\b|\bcan (?:only )?run\b|\bfree\b|"
                                      r"\bi run\b|\brun on\b", lower) else 0.65
    if not chosen:
        return None
    return Param("available_days", {str(d): d in chosen for d in range(7)}, confidence)


def parse(text: str, current_days: dict | None = None) -> list[Param]:
    text = " ".join((text or "").split())
    if not text:
        return []
    out = [p for p in (_sleep(text), _run_time(text), _loop(text), _runs_per_week(text),
                       _long_run_day(text), _available(text, current_days)) if p]
    return out


_PARAM_LIKE = re.compile(
    r"\d|\b(one|two|three|four|five|six|seven|eight|nine|ten|twice|once)\b", re.IGNORECASE)
_TOPIC = re.compile(r"\bsleep|\bslept|\brun|\bjog|\bloop|\blap|\broute|\bkm\b|\bweek|"
                    r"\bmorning|\bevening|\blong run|" + _DAY, re.IGNORECASE)


def looks_parameter_like(text: str) -> bool:
    """Worth the AI fallback when the parser found nothing."""
    return bool(_TOPIC.search(text or "")) and bool(
        _PARAM_LIKE.search(text or "") or _DAY_RE.search(text or ""))


def display(key: str, value) -> str:
    if value is None:
        return "—"
    if key == "sleep_need_minutes":
        h, m = divmod(int(value), 60)
        return f"{h} h" if not m else f"{h} h {m:02d} min"
    if key == "usual_run_time":
        return str(value)
    if key == "loop_distance_km":
        return f"{float(value):g} km"
    if key == "runs_per_week":
        return f"{int(value)} a week"
    if key == "long_run_day":
        return DAY_NAMES[int(value)]
    if key == "available_days":
        chosen = [DAY_NAMES[int(k)][:3] for k, v in sorted(value.items()) if v]
        return ", ".join(chosen) or "none"
    return str(value)


def valid(key: str, value) -> bool:
    try:
        if key == "sleep_need_minutes":
            return 240 <= int(value) <= 720
        if key == "usual_run_time":
            return bool(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(value)))
        if key == "loop_distance_km":
            return 0.1 <= float(value) <= 50
        if key == "runs_per_week":
            return 2 <= int(value) <= 6
        if key == "long_run_day":
            return 0 <= int(value) <= 6
        if key == "available_days":
            return (isinstance(value, dict) and set(value) == {str(d) for d in range(7)}
                    and all(isinstance(v, bool) for v in value.values()) and any(value.values()))
    except (TypeError, ValueError):
        return False
    return False
