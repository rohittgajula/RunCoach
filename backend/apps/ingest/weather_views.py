"""GET /weather/today/ (R8 §D). Never an error for weather reasons: no location or an
Open-Meteo outage is `available: false` with a `reason`."""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .weather_services import weather_today


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def weather_today_view(request):
    return Response(weather_today(request.user.athlete))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def weather_report_view(request):
    """R14 §3. Always 200 (`available: false` + reason without weather)."""
    from .weather_report import report

    return Response(report(request.user.athlete))
