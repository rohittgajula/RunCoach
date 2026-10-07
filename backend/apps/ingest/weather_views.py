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
