"""Training status and load focus (R10 §B2). Pure helpers over Garmin's words."""

from __future__ import annotations

STATUS_KEYS = ("productive", "maintaining", "recovery", "unproductive", "detraining",
               "peaking", "overreaching", "strained", "no_status")

FOCUS = (("low_aerobic", "Low aerobic", "monthlyLoadAerobicLow"),
         ("high_aerobic", "High aerobic", "monthlyLoadAerobicHigh"),
         ("anaerobic", "Anaerobic", "monthlyLoadAnaerobic"))

ENDURANCE_LEVELS = {1: "Recreational", 2: "Intermediate", 3: "Trained", 4: "Well-trained",
                    5: "Expert", 6: "Superior", 7: "Elite"}


def status_key(label: str | None) -> str | None:
    """'Productive' / 'PRODUCTIVE_3' / 'No Status' -> 'productive' / 'no_status'."""
    if not label:
        return None
    word = str(label).strip().lower().replace(" ", "_")
    for key in STATUS_KEYS:
        if word.startswith(key):
            return key
    return None


def words(phrase: str | None) -> str | None:
    """'BELOW_TARGETS' -> 'Below targets'."""
    if not phrase:
        return None
    return str(phrase).replace("_", " ").strip().capitalize() or None


def state(value: float | None, low: float | None, high: float | None) -> str | None:
    if value is None or (low is None and high is None):
        return None
    if low is not None and value < low:
        return "below"
    if high is not None and value > high:
        return "above"
    return "in_range"


def _num(value):
    try:
        return round(float(value), 1) if value is not None else None
    except (TypeError, ValueError):
        return None


def load_focus(balance: dict | None) -> dict | None:
    """One device's metricsTrainingLoadBalanceDTOMap entry -> the stored load focus."""
    if not isinstance(balance, dict):
        return None
    items = []
    for key, label, field in FOCUS:
        value = _num(balance.get(field))
        if value is None:
            continue
        low = _num(balance.get(f"{field}TargetMin"))
        high = _num(balance.get(f"{field}TargetMax"))
        items.append({"key": key, "label": label, "value": value, "target_min": low,
                      "target_max": high, "state": state(value, low, high)})
    if not items:
        return None
    return {"feedback": words(balance.get("trainingBalanceFeedbackPhrase")), "items": items}
