"""Diet endpoints (spec §5). Every query is scoped to the requesting athlete."""

from __future__ import annotations

import datetime as dt
import json

from django.utils import timezone
from rest_framework import generics, serializers, status
from rest_framework.decorators import api_view, parser_classes, permission_classes, throttle_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.athletes.mixins import AthleteScopedMixin
from apps.coaching.client import AIUnavailable
from apps.coaching.throttles import ChatThrottle

from .estimate import estimate_meal
from .precheck import precheck_meal
from .models import Meal
from .services import diet_day, meal_json, trend

MAX_PHOTO_BYTES = 8 * 1024 * 1024
ITEM_NUMBERS = ("kcal", "carbs_g", "protein_g", "fat_g")


def _clean_items(raw) -> list[dict]:
    """Items arrive as a JSON string in multipart and as a list in JSON bodies."""
    if raw in (None, ""):
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError as exc:
            raise serializers.ValidationError({"items": "Must be a JSON list."}) from exc
    if not isinstance(raw, list):
        raise serializers.ValidationError({"items": "Must be a list."})
    items = []
    for entry in raw[:50]:
        if not isinstance(entry, dict):
            raise serializers.ValidationError({"items": "Each item must be an object."})
        item = {"name": str(entry.get("name") or "")[:120],
                "quantity": str(entry.get("quantity") or "")[:60]}
        for key in ITEM_NUMBERS:
            try:
                value = float(entry.get(key) or 0)
            except (TypeError, ValueError) as exc:
                raise serializers.ValidationError({"items": f"{key} must be a number."}) from exc
            if value < 0 or value > 10000:
                raise serializers.ValidationError({"items": f"{key} is out of range."})
            item[key] = round(value, 1)
        items.append(item)
    return items


class MealWriteSerializer(serializers.ModelSerializer):
    items = serializers.JSONField(required=False)

    class Meta:
        model = Meal
        fields = ["meal_type", "eaten_at", "description", "items", "photo", "source", "ai_confidence"]
        extra_kwargs = {
            "eaten_at": {"required": False},
            "source": {"required": False},
            "ai_confidence": {"required": False},
        }

    def validate_items(self, value):
        return _clean_items(value)

    def validate_photo(self, value):
        if value and value.size > MAX_PHOTO_BYTES:
            raise serializers.ValidationError("Photo must be under 8 MB.")
        return value


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def day_view(request):
    athlete = request.user.athlete
    raw = request.query_params.get("date")
    try:
        day = dt.date.fromisoformat(raw) if raw else athlete.local_today
    except ValueError:
        return Response({"detail": "date must be YYYY-MM-DD."}, status=400)
    return Response(diet_day(athlete, day))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def trend_view(request):
    return Response(trend(request.user.athlete, request.query_params.get("range", "3m")))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ChatThrottle])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def estimate_view(request):
    """Not saved. 503 {detail} when the model is unavailable, so the UI can fall back
    to manual entry rather than show an error."""
    text = (request.data.get("text") or "").strip()
    photo = request.FILES.get("photo")
    if not text and not photo:
        return Response({"detail": "Send a photo, a description, or both."}, status=400)
    if photo and photo.size > MAX_PHOTO_BYTES:
        return Response({"detail": "Photo must be under 8 MB."}, status=400)
    try:
        result = estimate_meal(
            request.user.athlete,
            text=text or None,
            photo_bytes=photo.read() if photo else None,
            content_type=getattr(photo, "content_type", None),
            meal_type=request.data.get("meal_type") or None,
        )
    except AIUnavailable as exc:
        return Response(
            {"detail": f"Meal estimates are unavailable right now ({exc}). Enter it manually."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response(result)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ChatThrottle])
def precheck_view(request):
    """R25: before he eats it. Saves nothing — this is a question, not a log entry.

    503 when the model is unavailable: the fit numbers would still be worth
    showing, but a verdict card with no verdict on it is worse than the typed
    estimate flow he already has.
    """
    try:
        result = precheck_meal(
            request.user.athlete,
            text=request.data.get("text") or "",
            meal_type=request.data.get("meal_type") or None,
        )
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=400)
    except AIUnavailable as exc:
        return Response(
            {"detail": f"I could not look at that right now ({exc})."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response(result)


class MealCreate(AthleteScopedMixin, generics.CreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MealWriteSerializer
    queryset = Meal.objects.all()
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        meal = serializer.save(
            athlete=request.user.athlete,
            eaten_at=serializer.validated_data.get("eaten_at") or timezone.now(),
        )
        return Response(meal_json(meal), status=status.HTTP_201_CREATED)


class MealDetail(AthleteScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MealWriteSerializer
    queryset = Meal.objects.all()
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    http_method_names = ["get", "patch", "delete"]

    def retrieve(self, request, *args, **kwargs):
        return Response(meal_json(self.get_object()))

    def update(self, request, *args, **kwargs):
        meal = self.get_object()
        serializer = self.get_serializer(meal, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        meal = serializer.save()
        return Response(meal_json(meal))

    def perform_destroy(self, instance):
        if instance.photo:
            instance.photo.delete(save=False)
        instance.delete()
