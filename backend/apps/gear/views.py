"""R10 §B8 gear: GET/POST /gear/, PATCH/DELETE /gear/{id}/."""

from __future__ import annotations

from django.db import transaction
from django.db.models import Count, Max, Sum
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis import gear as maths
from apps.activities.models import Activity

from .models import Shoe, ShoeAssignment

GARMIN_EDITABLE = {"retire_km", "is_default", "retired"}


class ShoeInput(serializers.Serializer):
    name = serializers.CharField(min_length=1, max_length=80)
    brand = serializers.CharField(max_length=60, allow_blank=True, required=False)
    retire_km = serializers.FloatField(min_value=100, max_value=2000, required=False,
                                       allow_null=True)
    start_km = serializers.FloatField(min_value=0, max_value=5000, required=False)
    is_default = serializers.BooleanField(required=False)
    retired = serializers.BooleanField(required=False)
    in_use_since = serializers.DateField(required=False, allow_null=True)


def auto_assign(athlete) -> int:
    """Running activities with no shoe, dated on/after the default local shoe came into
    use, go to that shoe."""
    shoe = Shoe.objects.filter(athlete=athlete, source=Shoe.Source.LOCAL, is_default=True,
                               retired=False).first()
    if shoe is None:
        return 0
    since = shoe.in_use_since or shoe.created_at.astimezone(athlete.local_now.tzinfo).date()
    todo = (Activity.objects.filter(athlete=athlete, sport__icontains="run", local_date__gte=since,
                                    shoe_assignment__isnull=True)
            .values_list("pk", flat=True))
    rows = [ShoeAssignment(shoe=shoe, activity_id=pk) for pk in todo]
    ShoeAssignment.objects.bulk_create(rows, ignore_conflicts=True)
    return len(rows)


def shoe_json(shoe: Shoe, usage: dict) -> dict:
    stats = usage.get(shoe.pk, {})
    if shoe.source == Shoe.Source.GARMIN:
        distance = (shoe.garmin_distance_m or 0) / 1000
        activities = shoe.garmin_activities or 0
    else:
        distance = shoe.start_km + (stats.get("metres") or 0) / 1000
        activities = stats.get("count") or 0
    limit = shoe.retire_km or shoe.garmin_max_km or maths.DEFAULT_RETIRE_KM
    return {"id": shoe.pk, "name": shoe.name, "brand": shoe.brand, "source": shoe.source,
            "is_default": shoe.is_default, "retired": shoe.retired, "retire_km": limit,
            "start_km": shoe.start_km, "distance_km": round(distance, 1),
            "activities": activities, "in_use_since": shoe.in_use_since,
            "last_used": stats.get("last"), **maths.status(distance, limit),
            "garmin_uuid": shoe.garmin_uuid, "created_at": shoe.created_at}


def _usage(athlete) -> dict:
    rows = (ShoeAssignment.objects.filter(shoe__athlete=athlete).values("shoe_id")
            .annotate(metres=Sum("activity__total_distance_m"), count=Count("id"),
                      last=Max("activity__local_date")))
    return {r["shoe_id"]: r for r in rows}


def _set_default(athlete, shoe: Shoe) -> None:
    Shoe.objects.filter(athlete=athlete, is_default=True).exclude(pk=shoe.pk) \
        .update(is_default=False)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def shoes(request):
    athlete = request.user.athlete
    if request.method == "POST":
        data = ShoeInput(data=request.data)
        data.is_valid(raise_exception=True)
        with transaction.atomic():
            shoe = Shoe.objects.create(athlete=athlete, source=Shoe.Source.LOCAL,
                                       **{k: v for k, v in data.validated_data.items()
                                          if k != "retired"})
            if shoe.is_default:
                _set_default(athlete, shoe)
        auto_assign(athlete)
        return Response(shoe_json(shoe, _usage(athlete)), status=status.HTTP_201_CREATED)
    auto_assign(athlete)
    usage = _usage(athlete)
    rows = list(Shoe.objects.filter(athlete=athlete))
    return Response({"shoes": [shoe_json(s, usage) for s in rows],
                     "default_retire_km": maths.DEFAULT_RETIRE_KM})


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def shoe_detail(request, pk: int):
    athlete = request.user.athlete
    shoe = Shoe.objects.filter(athlete=athlete, pk=pk).first()
    if shoe is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    garmin = shoe.source == Shoe.Source.GARMIN
    if request.method == "DELETE":
        if garmin:
            return Response({"detail": "Shoes from Garmin are managed in Garmin Connect."},
                            status=status.HTTP_400_BAD_REQUEST)
        shoe.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    if garmin:
        extra = set(request.data) - GARMIN_EDITABLE
        if extra:
            return Response({"detail": "Only retire_km, is_default and retired can be "
                                       f"changed on a Garmin shoe (got {', '.join(sorted(extra))})."},
                            status=status.HTTP_400_BAD_REQUEST)
    data = ShoeInput(data=request.data, partial=True)
    data.is_valid(raise_exception=True)
    with transaction.atomic():
        for key, value in data.validated_data.items():
            setattr(shoe, key, value)
        shoe.save()
        if shoe.is_default:
            _set_default(athlete, shoe)
    auto_assign(athlete)
    return Response(shoe_json(shoe, _usage(athlete)))

