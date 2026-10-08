"""Coach memory (R17 §16): grouping facts and keeping the private habit out. Pure.

The private habit (R9 §B) never reaches a model, so it must never be stored as a fact
either — a fact is injected into every chat prompt. Any fact that mentions it is
refused, whatever its source (the app, the chat tool, the automatic extraction, a
check-in note).
"""

from __future__ import annotations

import re

CATEGORIES = {"health": "Injuries & health", "schedule": "Schedule & preferences",
              "goals": "Goals", "other": "Other"}
ORDER = ("health", "schedule", "goals", "other")
MAX_PINNED = 10
CONTEXT_MAX = 40

_PRIVATE = re.compile(
    r"private\s+habit|private\s+log|\bmasturbat\w*|\bporn\w*|\bnofap\b|\bno[\s-]?fap\b"
    r"|\bfap\w*|self[\s-]?pleasur\w*|\bsexual\s+habit\w*|\bjerk(?:ing)?\s+off\b",
    re.IGNORECASE)

_KEYWORDS = {
    "health": r"injur|pain|sore|hurt|knee|ankle|shin|calf|hamstring|\bhip|\bback\b|achilles|"
              r"plantar|asthma|allerg|\bill\b|sick|cold|flu|fever|surgery|physio|doctor|"
              r"medic|blood pressure|heart|diabet|sleep|smok|alcohol|caffeine|diet|"
              r"vegetarian|vegan|weight",
    "goals": r"goal|target|race|marathon|half|\b5k\b|\b10k\b|sub[\s-]?\d|pb\b|pr\b|"
             r"personal best|finish|qualif|want to|aim|dream",
    "schedule": r"morning|evening|night|weekend|weekday|monday|tuesday|wednesday|thursday|"
                r"friday|saturday|sunday|work|shift|office|travel|commute|kids|family|"
                r"time|prefer|like|dislike|hate|love|treadmill|gym|trail|track|route|"
                r"before|after|early|late",
}


def mentions_private_habit(text: str) -> bool:
    return bool(_PRIVATE.search(text or ""))


def guess_category(text: str) -> str:
    lower = (text or "").lower()
    for key in ("health", "goals", "schedule"):
        if re.search(_KEYWORDS[key], lower):
            return key
    return "other"


def context_facts(facts: list[tuple[str, bool]], limit: int = CONTEXT_MAX) -> list[str]:
    """facts = [(text, pinned)] newest first → pinned first (all), then the newest
    others up to `limit` in total. Private-habit text is dropped defensively."""
    clean = [(t, p) for t, p in facts if not mentions_private_habit(t)]
    pinned = [t for t, p in clean if p]
    others = [t for t, p in clean if not p]
    return pinned + others[:max(0, limit - len(pinned))]
