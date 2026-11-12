from django.urls import path

from .compare_views import compare
from .progress_views import progress, progress_review
from .r17_views import (
    activity_quality, activity_recovery, activity_recovery_done, deleted_activities,
    deleted_reimport, recovery_today,
)
from .review_views import review_ai, reviews_recent
from .share_views import share_data
from .views import (
    ActivityDetail, ActivityList, activity_facets, activity_route, activity_routes,
    activity_series,
)

urlpatterns = [
    path("activities/", ActivityList.as_view(), name="activity-list"),
    path("activities/facets/", activity_facets, name="activity-facets"),
    path("activities/compare/", compare, name="activity-compare"),
    path("activities/<int:pk>/", ActivityDetail.as_view(), name="activity-detail"),
    path("activities/<int:pk>/series/", activity_series, name="activity-series"),
    path("activities/<int:pk>/route/", activity_route, name="activity-route"),
    path("activities/<int:pk>/share-data/", share_data, name="activity-share-data"),
    path("activities/routes/", activity_routes, name="activity-routes"),
    path("progress/", progress, name="progress"),
    path("progress/review/", progress_review, name="progress-review"),
    # R13 §7 (GET /activities/{id}/review/ lives with the planning views' POST).
    path("activities/<int:pk>/review/ai/", review_ai, name="activity-review-ai"),
    path("reviews/recent/", reviews_recent, name="reviews-recent"),
    # R17
    path("activities/<int:pk>/quality/", activity_quality, name="activity-quality"),
    path("activities/<int:pk>/recovery/", activity_recovery, name="activity-recovery"),
    path("activities/<int:pk>/recovery/done/", activity_recovery_done,
         name="activity-recovery-done"),
    path("recovery/today/", recovery_today, name="recovery-today"),
    path("activities/deleted/", deleted_activities, name="activities-deleted"),
    path("activities/deleted/<int:pk>/reimport/", deleted_reimport,
         name="activities-deleted-reimport"),
]
