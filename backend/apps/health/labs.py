"""R23: blood and urine panels — storing them, and reading them back.

The interpretation lives in `analysis/bloodwork.py` and is deliberately thin:
numbers against the range they were measured against, which ones runners care
about, and how they have moved. Not a diagnosis, said on every response rather
than once in a footer.

Three endpoints:

    GET  /labs/markers/   what can be entered, with units and why each matters
    GET  /labs/          every panel, read, plus a trend per marker
    POST /labs/          one panel and its readings
    DELETE /labs/{id}/   remove one

Entry is manual and structured. Reading numbers off a photograph with a model
is the obvious next step and deliberately not this step: a mis-OCR'd decimal
point on a ferritin result is a number somebody might act on, and "the app read
it wrong" is not a failure mode worth shipping for the sake of saving typing.
"""

from __future__ import annotations

import datetime as dt

from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis import bloodwork

from .models import LabPanel, LabReading


class ReadingIn(serializers.Serializer):
    key = serializers.ChoiceField(choices=[m.key for m in bloodwork.MARKERS])
    value = serializers.FloatField()
    unit = serializers.CharField(max_length=16, required=False, allow_blank=True)
    # The lab's own range, when the report printed one. Always preferred.
    ref_low = serializers.FloatField(required=False, allow_null=True)
    ref_high = serializers.FloatField(required=False, allow_null=True)


class PanelIn(serializers.Serializer):
    taken_on = serializers.DateField()
    lab = serializers.CharField(max_length=120, required=False, allow_blank=True)
    note = serializers.CharField(max_length=300, required=False, allow_blank=True)
    readings = ReadingIn(many=True)

    def validate_taken_on(self, value):
        if value > dt.date.today() + dt.timedelta(days=1):
            raise serializers.ValidationError("That date is in the future.")
        return value

    def validate_readings(self, value):
        if not value:
            raise serializers.ValidationError("A panel needs at least one result.")
        keys = [r["key"] for r in value]
        if len(keys) != len(set(keys)):
            raise serializers.ValidationError("The same marker twice.")
        return value


def panel_json(panel: LabPanel) -> dict:
    readings = [
        bloodwork.assess(r.key, r.value, r.ref_low, r.ref_high)
        for r in panel.readings.all()
    ]
    readings = [r for r in readings if r is not None]
    return {
        "id": panel.pk,
        "taken_on": panel.taken_on,
        "lab": panel.lab,
        "note": panel.note,
        "readings": [
            {
                "key": r.key, "label": r.label, "unit": r.unit, "value": r.value,
                "low": r.low, "high": r.high, "range_source": r.range_source,
                "status": r.status, "flagged": r.flagged,
                "matters": r.matters, "note": r.note, "runner_key": r.runner_key,
            }
            for r in readings
        ],
        **bloodwork.summarise(readings),
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def markers(request):
    """What can be entered. Runner-relevant markers first, because those are
    the ones worth the typing."""
    ordered = sorted(bloodwork.MARKERS, key=lambda m: (not m.runner_key, m.label))
    return Response({
        "markers": [
            {"key": m.key, "label": m.label, "unit": m.unit,
             "matters": m.matters, "runner_key": m.runner_key,
             "typical": list(m.fallback) if m.fallback else None}
            for m in ordered
        ],
        "runner_keys": list(bloodwork.RUNNER_KEYS),
    })


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def panels(request):
    athlete = request.user.athlete

    if request.method == "POST":
        form = PanelIn(data=request.data)
        form.is_valid(raise_exception=True)
        data = form.validated_data
        panel = LabPanel.objects.create(
            athlete=athlete, taken_on=data["taken_on"],
            lab=data.get("lab", ""), note=data.get("note", ""),
        )
        LabReading.objects.bulk_create([
            LabReading(
                panel=panel, key=r["key"], value=r["value"],
                unit=r.get("unit") or bloodwork.BY_KEY[r["key"]].unit,
                ref_low=r.get("ref_low"), ref_high=r.get("ref_high"),
            )
            for r in data["readings"]
        ])
        return Response(panel_json(panel), status=status.HTTP_201_CREATED)

    rows = (LabPanel.objects.filter(athlete=athlete)
            .prefetch_related("readings").order_by("-taken_on", "-id"))
    panels_out = [panel_json(p) for p in rows]
    return Response({
        "panels": panels_out,
        # One series per marker, oldest first, so a number can be seen moving.
        # A single ferritin reading says much less than three of them do.
        "trends": _trends(panels_out),
        "standing_note": bloodwork.summarise([])["standing_note"],
    })


def _trends(panels_out: list[dict]) -> dict:
    out: dict[str, list[dict]] = {}
    for panel in reversed(panels_out):
        for reading in panel["readings"]:
            out.setdefault(reading["key"], []).append({
                "taken_on": panel["taken_on"],
                "value": reading["value"],
                "status": reading["status"],
            })
    return {k: v for k, v in out.items() if len(v) > 1}


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def panel_detail(request, pk: int):
    deleted, _ = LabPanel.objects.filter(athlete=request.user.athlete, pk=pk).delete()
    if not deleted:
        return Response({"detail": "No such panel."}, status=status.HTTP_404_NOT_FOUND)
    return Response(status=status.HTTP_204_NO_CONTENT)
