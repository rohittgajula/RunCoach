"""Daily morning briefing (R13 §6): the one focus for today and the short notes. Pure.

The rest of the briefing (readiness, session, weather, fuel) is gathered by the Django
side from the existing endpoints; this decides what to say about it, in this order:
injury → the check-in verdict → a short night → the session itself → a rest day.
"""

from __future__ import annotations

SHORT_NIGHT_H = 6.0
DRINKS_NOTE = 3
HARD = {"INTERVALS", "TEMPO"}
EASY = {"EASY", "RUN_WALK"}


def greeting(name: str | None) -> str:
    name = (name or "").strip().split(" ")[0]
    return f"Good morning, {name}" if name else "Good morning"


def focus(*, verdict: str | None, headline: str | None, workout_kind: str | None,
          injury_risk: str, injury_text: str | None, sleep_h: float | None,
          has_strength: bool = False) -> dict:
    if injury_risk == "high":
        return {"key": "injury", "text": f"Listen to your body: {injury_text or 'injury watch is high'}. "
                "Easy or rest today."}
    if verdict == "rest":
        return {"key": "rest", "text": "Rest and recover today — that is training too."}
    if verdict in ("swap", "easy"):
        return {"key": "easy", "text": f"{headline or 'Keep it easy today'} — "
                "the plan has your back."}
    if sleep_h is not None and sleep_h < SHORT_NIGHT_H:
        return {"key": "sleep", "text": "Short night: keep today's effort gentle and get to "
                "bed a little earlier."}
    if workout_kind == "LONG":
        return {"key": "long", "text": "Long run today: start slower than feels necessary "
                "and fuel if it's over an hour."}
    if workout_kind in HARD:
        return {"key": "quality", "text": "Quality session: warm up well, then hit the "
                "targets — not faster."}
    if workout_kind in EASY:
        return {"key": "easy_run", "text": "Easy means easy: walk whenever your HR passes "
                "the cap."}
    if workout_kind == "RACE":
        return {"key": "race", "text": "Race day: run your plan, not the crowd."}
    if has_strength:
        return {"key": "strength", "text": "Strength day: 20 minutes, stop a set when form "
                "slips."}
    return {"key": "rest_day", "text": "No run today — an easy walk keeps you moving."}


def notes(*, injury_risk: str, injury_text: str | None, drinks: float | None,
          smoke_free_days: int | None, sleep_h: float | None, need_h: float | None,
          mood: int | None, reviewed: bool) -> list[dict]:
    out = []
    if injury_risk in ("moderate", "high") and injury_text:
        out.append({"kind": "injury", "text": injury_text})
    if drinks is not None and drinks >= DRINKS_NOTE:
        out.append({"kind": "habit", "text": f"{drinks:g} drinks last night — drink extra "
                    "water and keep the effort easy."})
    if smoke_free_days:
        out.append({"kind": "habit", "text": f"{smoke_free_days} smoke-free day"
                    f"{'s' if smoke_free_days != 1 else ''} — keep going."})
    if sleep_h is not None and need_h and sleep_h < need_h - 1:
        out.append({"kind": "sleep", "text": f"Slept {sleep_h:.1f} h of the {need_h:.1f} h "
                    "you need — aim for an earlier night."})
    if mood is not None and mood <= 2:
        out.append({"kind": "mood", "text": "Feeling low? A short easy walk outside often "
                    "helps — and rest is fine too."})
    if reviewed:
        out.append({"kind": "review", "text": "Your last run has a coach review waiting."})
    return out
