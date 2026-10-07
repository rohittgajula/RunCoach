import datetime as dt

from django.db.models import Q
from rest_framework import generics
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.athletes.mixins import AthleteScopedMixin

from .models import Activity
from .serializers import ActivityDetailSerializer, ActivityListSerializer


class ActivityPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class ActivityList(AthleteScopedMixin, generics.ListAPIView):
    """Filtered and paginated.

    Filters are applied in the database rather than in the client: an athlete with
    three years of history should not download all of it to look at last week.
    """

    serializer_class = ActivityListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = ActivityPagination
    # select_related on the one-to-one avoids a query per row for the metrics.
    queryset = Activity.objects.select_related("metrics").order_by("-started_at")

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params

        if sport := params.get("sport"):
            queryset = queryset.filter(sport=sport)

        if params.get("ran") == "true":
            # Activities containing actual running, which is not the same as
            # activities Garmin labelled "running".
            queryset = queryset.filter(metrics__run_block_count__gt=0)
        elif params.get("ran") == "false":
            queryset = queryset.filter(
                Q(metrics__isnull=True) | Q(metrics__run_block_count=0)
            )

        for param, lookup in (("from", "local_date__gte"), ("to", "local_date__lte")):
            if raw := params.get(param):
                try:
                    queryset = queryset.filter(**{lookup: dt.date.fromisoformat(raw)})
                except ValueError:
                    pass  # a malformed date filters nothing rather than 500ing

        return queryset


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def activity_facets(request):
    """The values worth offering as filters, and how many each would return.

    Computed from the athlete's own data: offering "cycling" to someone who has never
    cycled is a control that only ever returns nothing.
    """
    base = Activity.objects.filter(athlete=request.user.athlete)
    sports = {}
    for sport in base.values_list("sport", flat=True):
        sports[sport] = sports.get(sport, 0) + 1

    return Response({
        "sports": [{"value": k, "count": v} for k, v in sorted(sports.items(), key=lambda x: -x[1])],
        "with_running": base.filter(metrics__run_block_count__gt=0).count(),
        "total": base.count(),
        "earliest": base.order_by("local_date").values_list("local_date", flat=True).first(),
    })


class ActivityDetail(AthleteScopedMixin, generics.RetrieveAPIView):
    serializer_class = ActivityDetailSerializer
    permission_classes = [IsAuthenticated]
    queryset = Activity.objects.select_related("metrics").prefetch_related("segments")

    def retrieve(self, request, *args, **kwargs):
        from apps.planning.plan_views import activity_detail_json

        return Response(activity_detail_json(request.user.athlete, self.get_object()))


# A 28-minute run is ~1,670 samples and a long one is far more. Charts cannot show
# that many points and browsers should not have to parse them, so the series is
# downsampled to roughly this many.
CHART_POINTS = 320


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def activity_series(request, pk: int):
    """Per-second data, downsampled for charting.

    Downsampled by BUCKET AVERAGE rather than by taking every Nth sample: naive
    decimation on a noisy optical-HR trace shows whichever beats happened to land on
    the stride, which looks like signal and is not.
    """
    activity = Activity.objects.filter(athlete=request.user.athlete, pk=pk).first()
    if activity is None:
        return Response({"detail": "Not found."}, status=404)

    rows = list(
        activity.records.order_by("offset_s").values(
            "offset_s", "distance_m", "speed_mps", "cadence_spm", "heart_rate", "altitude_m"
        )
    )
    if not rows:
        return Response({"points": [], "has_hr": False, "has_cadence": False})

    step = max(1, len(rows) // CHART_POINTS)
    points = []
    for start in range(0, len(rows), step):
        bucket = rows[start : start + step]

        def mean(key):
            values = [r[key] for r in bucket if r[key] is not None]
            return round(sum(values) / len(values), 1) if values else None

        speed = mean("speed_mps")
        points.append({
            "t": round(bucket[0]["offset_s"]),
            "km": round((bucket[0]["distance_m"] or 0) / 1000, 3),
            # Pace is what a runner reads; speed is what the device stores. Anything
            # slower than 20 min/km is a stop, and plotting it flattens the whole axis.
            "pace": round(1000 / speed) if speed and 1000 / speed < 1200 else None,
            "hr": mean("heart_rate"),
            "cadence": mean("cadence_spm"),
            "altitude": mean("altitude_m"),
        })

    return Response({
        "points": points,
        "sampled_from": len(rows),
        "has_hr": any(p["hr"] for p in points),
        "has_cadence": any(p["cadence"] for p in points),
        "has_altitude": any(p["altitude"] for p in points),
    })


# --- R11 §E: run maps ------------------------------------------------------------------

ROUTE_CACHE_S = 24 * 3600
ROUTES_MAX = 50


def route_cache_key(activity: Activity, hide: bool) -> str:
    return f"route:v1:{activity.pk}:{activity.segmentation_version}:{int(hide)}"


def overlay_cache_key(activity: Activity, hide: bool) -> str:
    return f"route-overlay:v1:{activity.pk}:{int(hide)}"


def _route_samples(activity: Activity) -> list[dict]:
    rows = activity.records.filter(latitude__isnull=False, longitude__isnull=False).order_by(
        "offset_s").values_list("offset_s", "latitude", "longitude", "distance_m", "heart_rate",
                                "altitude_m")
    return [{"t": t, "lat": lat, "lon": lon, "dist": d, "hr": hr, "alt": alt}
            for t, lat, lon, d, hr, alt in rows]


def route_body(activity: Activity, hide: bool) -> dict:
    """Cached per activity, segmentation version and the hide setting."""
    from django.core.cache import cache

    from analysis import route as maths

    key = route_cache_key(activity, hide)
    try:
        cached = cache.get(key)
    except Exception:  # noqa: BLE001 — a cache outage only costs a recompute
        cached = None
    if cached is not None:
        return cached
    segments = [(s.start_offset_s, s.start_offset_s + s.duration_s, s.kind)
                for s in activity.segments.all()]
    body = {"activity_id": activity.pk,
            **maths.build(_route_samples(activity), segments,
                          hide_m=maths.HIDE_M if hide else 0)}
    try:
        cache.set(key, body, ROUTE_CACHE_S)
    except Exception:  # noqa: BLE001
        pass
    return body


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def activity_route(request, pk: int):
    athlete = request.user.athlete
    activity = Activity.objects.filter(athlete=athlete, pk=pk).first()
    if activity is None:
        return Response({"detail": "Not found."}, status=404)
    return Response(route_body(activity, athlete.map_hide_endpoints))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def activity_routes(request):
    """"Your routes": light polylines of the latest runs with GPS (trimmed the same way)."""
    from analysis import route as maths

    athlete = request.user.athlete
    try:
        limit = int(request.query_params.get("limit", 20))
    except ValueError:
        return Response({"detail": "limit must be a number (1–50)."}, status=400)
    if not 1 <= limit <= ROUTES_MAX:
        return Response({"detail": "limit must be between 1 and 50."}, status=400)
    hide = maths.HIDE_M if athlete.map_hide_endpoints else 0
    from django.db.models import Exists, OuterRef

    from .models import ActivityRecord

    gps = ActivityRecord.objects.filter(activity=OuterRef("pk"), latitude__isnull=False)
    with_gps = (Activity.objects.filter(athlete=athlete, sport__icontains="run")
                .filter(Exists(gps)).order_by("-started_at")[:limit])
    routes = []
    from django.core.cache import cache

    for activity in with_gps:
        key = overlay_cache_key(activity, bool(hide))
        try:
            points = cache.get(key)
        except Exception:  # noqa: BLE001
            points = None
        if points is None:
            points = maths.overlay(_route_samples(activity), hide_m=hide)
            try:
                cache.set(key, points, ROUTE_CACHE_S)
            except Exception:  # noqa: BLE001
                pass
        if points:
            routes.append({"activity_id": activity.pk, "date": activity.local_date,
                           "distance_m": round(activity.total_distance_m or 0, 1),
                           "points": points})
    return Response({"routes": routes})
