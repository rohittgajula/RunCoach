from django.urls import path

from .checkin_views import activity_checkin, activity_checkin_skip, pending_checkins
from .views import JournalList, chat_view

urlpatterns = [
    path("coach/chat/", chat_view, name="coach-chat"),
    path("journal/", JournalList.as_view(), name="journal"),
    # R7 §2.
    path("checkins/pending/", pending_checkins, name="checkins-pending"),
    path("activities/<int:pk>/checkin/", activity_checkin, name="activity-checkin"),
    path("activities/<int:pk>/checkin/skip/", activity_checkin_skip,
         name="activity-checkin-skip"),
]
