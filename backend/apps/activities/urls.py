from django.urls import path

from .progress_views import progress, progress_review
from .views import (
    ActivityDetail, ActivityList, activity_facets, activity_route, activity_routes,
    activity_series,
)

urlpatterns = [
    path("activities/", ActivityList.as_view(), name="activity-list"),
    path("activities/facets/", activity_facets, name="activity-facets"),
    path("activities/<int:pk>/", ActivityDetail.as_view(), name="activity-detail"),
    path("activities/<int:pk>/series/", activity_series, name="activity-series"),
    path("activities/<int:pk>/route/", activity_route, name="activity-route"),
    path("activities/routes/", activity_routes, name="activity-routes"),
    path("progress/", progress, name="progress"),
    path("progress/review/", progress_review, name="progress-review"),
]
