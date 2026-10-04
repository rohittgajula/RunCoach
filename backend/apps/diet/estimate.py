"""Meal estimation from a photo and/or a sentence.

The one nutrition job only the model can do. It returns ITEMS with per-item numbers;
the totals are summed here in Python, so a model that adds up wrong cannot produce a
wrong total. The result is never saved by this module — the athlete confirms or edits
it first.
"""

from __future__ import annotations

import base64
from typing import Literal

from pydantic import BaseModel, Field

from apps.athletes.models import Athlete
from apps.coaching.client import AIUnavailable, complete, model_for
from apps.coaching.services import check_budget, log_call

OPERATION = "meal_estimate"
PROMPT_VERSION = "meal-v1"

SYSTEM = """You estimate the nutritional content of a meal for a recreational runner's \
food log. You are given a photo, a description, or both.

Rules:
- List each distinct food or drink as its own item with a realistic household \
quantity ("2 dosa", "1 katori sambar", "1 cup chai with 1 tsp sugar").
- Estimate kcal, carbohydrate, protein and fat in grams for that quantity of that item.
- Be realistic about Indian home cooking and restaurant portions when the food is Indian: \
include cooking oil and ghee you can reasonably infer.
- If the description and photo disagree, trust the description for what was eaten and the \
photo for how much.
- Confidence: high only when the food and portion are both clear; low when you are \
guessing the portion or the dish.
- Do not give advice. Only the estimate."""


class EstimatedItem(BaseModel):
    model_config = {"extra": "forbid"}

    name: str
    quantity: str = Field(description="Household measure, e.g. '2 pieces', '1 cup'.")
    kcal: float
    carbs_g: float
    protein_g: float
    fat_g: float


class MealEstimate(BaseModel):
    model_config = {"extra": "forbid"}

    description: str = Field(description="Short description of the whole meal.")
    items: list[EstimatedItem]
    confidence: Literal["low", "medium", "high"]


def _data_url(photo_bytes: bytes, content_type: str | None) -> str:
    kind = content_type if content_type and content_type.startswith("image/") else "image/jpeg"
    return f"data:{kind};base64,{base64.b64encode(photo_bytes).decode()}"


def estimate_meal(
    athlete: Athlete,
    *,
    text: str | None = None,
    photo_bytes: bytes | None = None,
    content_type: str | None = None,
    meal_type: str | None = None,
) -> dict:
    """Returns {description, items, kcal, carbs_g, protein_g, fat_g, confidence}.

    Raises AIUnavailable (including BudgetExceeded) for the view to turn into a 503 —
    the UI then lets the athlete enter the meal by hand.
    """
    if not text and not photo_bytes:
        raise ValueError("Send a photo, a description, or both.")
    model = model_for(OPERATION)
    check_budget(athlete, OPERATION, model)

    prompt = "Estimate this meal."
    if meal_type:
        prompt += f" It was {meal_type}."
    if text:
        prompt += f'\n\nThe athlete described it as:\n"""{text.strip()[:1000]}"""'
    if photo_bytes:
        prompt += "\n\nA photo of the meal is attached."

    try:
        result, stats = complete(
            operation=OPERATION, system=SYSTEM, user=prompt, schema=MealEstimate,
            image_data_url=_data_url(photo_bytes, content_type) if photo_bytes else None,
        )
    except AIUnavailable as exc:
        log_call(athlete, OPERATION, {"model": model}, exc, PROMPT_VERSION)
        raise
    log_call(athlete, OPERATION, stats, None, PROMPT_VERSION)

    items = [
        {k: (round(v, 1) if isinstance(v, float) else v) for k, v in item.model_dump().items()}
        for item in result.items
    ]
    return {
        "description": result.description.strip()[:300],
        "items": items,
        **totals(items),
        "confidence": result.confidence,
    }


def totals(items: list[dict]) -> dict:
    return {
        key: round(sum(float(item.get(key) or 0) for item in items), 1)
        for key in ("kcal", "carbs_g", "protein_g", "fat_g")
    }
