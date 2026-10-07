"""R15: plain-English model cards for the admin page — what each model is good at, how
fast, how good and how costly — plus the per-tier preference lists the one-click
"Use <provider> for all tiers" switch picks from.

Static and approximate on purpose: the measured numbers (latency, error rate, cost per
call) come from our own AIRequestLog, prices from the editable ModelPrice table.
Unknown ids get a generic card derived from the name family.
"""

from __future__ import annotations

import re

TIERS = ("lite", "fast", "coach", "deep")

# Generic cards per family. cost_level is for a paid key; Gemini models that work on the
# free key show "free_tier" (decided at read time from the probe).
FAMILIES: dict[str, dict] = {
    "flash-lite": {
        "summary": "Google's cheapest and fastest Gemini tier. Good for short, simple "
                   "answers (one-liners, quick explanations); weaker at long reasoning.",
        "best_for": ["lite", "fast"], "speed": "fast", "quality": "basic", "cost_level": "$",
    },
    "flash": {
        "summary": "Gemini's balanced model: quick and capable enough for coaching text and "
                   "chat with tools, at a low price.",
        "best_for": ["fast", "coach"], "speed": "fast", "quality": "good", "cost_level": "$",
    },
    "pro": {
        "summary": "Gemini's strongest reasoning model — best answers for long reviews and "
                   "plans, but slower and the most expensive (needs billing; no free tier).",
        "best_for": ["coach", "deep"], "speed": "slow", "quality": "best",
        "cost_level": "$$$",
    },
    "gemma": {
        "summary": "Google's small open model served through AI Studio. Fine for simple "
                   "text; no strong reasoning and limited tool use.",
        "best_for": ["lite"], "speed": "fast", "quality": "basic", "cost_level": "$",
    },
    "nano": {
        "summary": "OpenAI's smallest, cheapest model. Good for tiny structured jobs "
                   "(one-liners, extraction); not for coaching prose.",
        "best_for": ["lite"], "speed": "fast", "quality": "basic", "cost_level": "$",
    },
    "mini": {
        "summary": "OpenAI's small model: fast and cheap, decent for short coaching text and "
                   "structured output.",
        "best_for": ["lite", "fast"], "speed": "fast", "quality": "good", "cost_level": "$",
    },
    "full": {
        "summary": "A full-size OpenAI model: strong writing and reasoning for the coach's "
                   "voice and chat, at a higher price.",
        "best_for": ["coach", "deep"], "speed": "medium", "quality": "strong",
        "cost_level": "$$",
    },
    "other": {
        "summary": "A text model we have no notes on yet. Run \"Check models\" and a "
                   "compare before routing a tier to it.",
        "best_for": [], "speed": "medium", "quality": "good", "cost_level": "$$",
    },
}

# Known ids: overrides on top of the family card.
KNOWN: dict[str, dict] = {
    # --- OpenAI (the models this app is priced for) ---
    "gpt-5-nano": {"label": "GPT-5 nano", "family": "nano", "context_window": 400_000},
    "gpt-5.4-mini": {"label": "GPT-5.4 mini", "family": "mini", "context_window": 400_000},
    "gpt-5.6-luna": {"label": "GPT-5.6 Luna", "family": "mini",
                     "summary": "OpenAI's light GPT-5.6 model: quick and inexpensive, a good "
                                "default for one-liners and short explanations.",
                     "best_for": ["lite", "fast"]},
    "gpt-5.6-terra": {"label": "GPT-5.6 Terra", "family": "full",
                      "summary": "OpenAI's mid GPT-5.6 model: solid coaching prose and "
                                 "reliable tool calling for chat. The usual coach-tier choice.",
                      "best_for": ["fast", "coach"], "speed": "medium", "quality": "strong",
                      "cost_level": "$$"},
    "gpt-5.6-sol": {"label": "GPT-5.6 Sol", "family": "full",
                    "summary": "OpenAI's largest GPT-5.6 model: the best reasoning for "
                               "monthly reviews and plans; slow and the most expensive.",
                    "best_for": ["deep"], "speed": "slow", "quality": "best",
                    "cost_level": "$$$"},
    # --- Gemini text models ---
    "gemini-2.5-flash-lite": {"label": "Gemini 2.5 Flash-Lite", "context_window": 1_048_576},
    "gemini-2.5-flash": {"label": "Gemini 2.5 Flash", "context_window": 1_048_576,
                         "summary": "Gemini 2.5's balanced model. Google no longer offers it "
                                    "to new keys — prefer a 3.x Flash."},
    "gemini-2.5-pro": {"label": "Gemini 2.5 Pro", "context_window": 1_048_576},
    "gemini-3-flash-preview": {"label": "Gemini 3 Flash (preview)",
                               "context_window": 1_048_576},
    "gemini-3-pro-preview": {"label": "Gemini 3 Pro (preview)", "context_window": 1_048_576},
    "gemini-3.1-pro-preview": {"label": "Gemini 3.1 Pro (preview)",
                               "context_window": 1_048_576},
    "gemini-3.5-flash-lite": {"label": "Gemini 3.5 Flash-Lite", "context_window": 1_048_576,
                              "summary": "Gemini's cheapest, fastest current model. Works on "
                                         "the free key; good for short answers and simple "
                                         "coaching text.",
                              "best_for": ["lite", "fast", "coach"]},
    "gemini-3.8-flash": {"label": "Gemini 3.8 Flash", "context_window": 1_048_576},
    "gemini-flash-latest": {"label": "Gemini Flash (latest)",
                            "summary": "Alias that always points at Google's newest Flash — "
                                       "balanced speed and quality; the model behind it can "
                                       "change without notice."},
    "gemini-flash-lite-latest": {"label": "Gemini Flash-Lite (latest)",
                                 "summary": "Alias for Google's newest Flash-Lite — the "
                                            "cheapest, fastest tier; the model behind it can "
                                            "change without notice."},
    "gemini-pro-latest": {"label": "Gemini Pro (latest)",
                          "summary": "Alias for Google's newest Pro — the strongest reasoning, "
                                     "slow and expensive; needs billing (no free tier)."},
}

# Per-tier preference for the one-click switch (first usable wins).
RECOMMENDED: dict[str, dict[str, list[str]]] = {
    "gemini": {
        "lite": ["gemini-3.5-flash-lite", "gemini-flash-lite-latest", "gemini-2.5-flash-lite"],
        "fast": ["gemini-3.5-flash-lite", "gemini-flash-lite-latest", "gemini-3.8-flash",
                 "gemini-flash-latest"],
        "coach": ["gemini-3.8-flash", "gemini-flash-latest", "gemini-3-flash-preview",
                  "gemini-3.5-flash-lite", "gemini-flash-lite-latest"],
        "deep": ["gemini-3.1-pro-preview", "gemini-pro-latest", "gemini-3.8-flash",
                 "gemini-flash-latest", "gemini-3.5-flash-lite"],
    },
    "openai": {
        "lite": ["gpt-5.6-luna", "gpt-5-nano", "gpt-5.4-mini"],
        "fast": ["gpt-5.6-luna", "gpt-5.4-mini", "gpt-5.6-terra"],
        "coach": ["gpt-5.6-terra", "gpt-5.4-mini"],
        "deep": ["gpt-5.6-sol", "gpt-5.6-terra"],
    },
}


def family_of(model: str) -> str:
    m = (model or "").lower()
    if m.startswith("gemma"):
        return "gemma"
    if m.startswith("gemini"):
        if "flash-lite" in m or "flash_lite" in m:
            return "flash-lite"
        if "flash" in m:
            return "flash"
        if "pro" in m:
            return "pro"
        return "other"
    if re.search(r"(^|-)nano($|-)", m):
        return "nano"
    if re.search(r"(^|-)mini($|-)", m):
        return "mini"
    if m.startswith(("gpt-", "o1", "o3", "o4", "chatgpt")):
        return "full"
    return "other"


def _label(model: str) -> str:
    parts = (model or "").replace("models/", "").split("-")
    return " ".join(p.capitalize() if p.isalpha() else p for p in parts)


def card(model: str) -> dict:
    """Static description of one model: {label, family, known, summary, best_for, speed,
    quality, cost_level, context_window}."""
    known = KNOWN.get(model)
    family = (known or {}).get("family") or family_of(model)
    base = dict(FAMILIES.get(family, FAMILIES["other"]))
    out = {"label": _label(model), "family": family, "known": known is not None,
           "context_window": 1_048_576 if family in ("flash-lite", "flash", "pro") else None,
           **base}
    if known:
        out.update({k: v for k, v in known.items() if k != "family"})
    out["best_for"] = list(out.get("best_for") or [])
    return out
