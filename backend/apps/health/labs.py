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

    POST /labs/extract/   read an uploaded PDF or photo into an unsaved draft

Entry is manual and structured, and the upload does not change that: it fills the
same form in, and he still presses save. The reason the earlier version refused to
read a report at all — a mis-OCR'd decimal point on a ferritin result is a number
somebody might act on — is answered by never saving what the model produced.
`lab_extract` returns a draft carrying, for each row, the text it read the number
from, so confirming it is a glance at the report rather than a second typing of it.
"""

from __future__ import annotations

import datetime as dt

from rest_framework import serializers, status
from rest_framework.decorators import (
    api_view, parser_classes, permission_classes, throttle_classes,
)
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis import bloodwork
from apps.coaching.client import AIUnavailable
from apps.coaching.throttles import ChatThrottle

from .lab_extract import MAX_BYTES, extract_panel
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


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ChatThrottle])
@parser_classes([MultiPartParser, FormParser])
def extract(request):
    """Read an uploaded report into a draft. Saves nothing, here or anywhere.

    The response is the shape the review screen needs: rows that passed every
    check, rows that did not and why, markers the app does not track, and what
    the report did not say. 503 when the model is unavailable, so the UI can
    offer the typed form instead of showing a failure.
    """
    upload = request.FILES.get("file")
    if upload is None:
        return Response({"detail": "Attach the report as a PDF or a photo."}, status=400)
    if upload.size > MAX_BYTES:
        return Response(
            {"detail": f"The file must be under {MAX_BYTES // (1024 * 1024)} MB."}, status=400
        )
    try:
        draft = extract_panel(
            request.user.athlete,
            data=upload.read(),
            content_type=getattr(upload, "content_type", None),
            filename=getattr(upload, "name", "") or "",
        )
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=400)
    except AIUnavailable as exc:
        return Response(
            {"detail": f"I could not read the report right now ({exc}). "
                       "You can still type the results in."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response(draft)
