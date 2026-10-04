from django.urls import path

from .calendar_views import calendar
from .plan_views import (
    PlanList, active_plan, activity_ai_review, activity_review, calendar_days, plan_accept,
    plan_decline, plan_rebuild, plan_view, workout_guide, workout_review, workout_view,
)
from .checkin_views import today, today_apply, today_explain
from .garmin_views import plan_garmin, workout_garmin
from .month_views import calendar_month
from .views import (
    RaceDetail, RaceList, plan_weeks, predictions, today_mode, today_session_view,
)

urlpatterns = [
    path("races/", RaceList.as_view(), name="race-list"),
    path("races/<int:pk>/", RaceDetail.as_view(), name="race-detail"),
    # MyRunAnalizer's regenerate-on-read projections. Kept working; the RunCoach UI
    # reads the persisted plan endpoints below.
    path("plan/today/", today_mode, name="plan-today"),
    path("plan/predictions/", predictions, name="plan-predictions"),
    path("plan/weeks/", plan_weeks, name="plan-weeks"),
    path("plan/session/", today_session_view, name="plan-session"),
    path("plan/calendar/", calendar, name="plan-calendar"),
    # RunCoach §5.
    path("plans/", PlanList.as_view(), name="plans"),
    path("plans/active/", active_plan, name="plan-active"),
    path("plans/active/rebuild/", plan_rebuild, name="plan-rebuild"),
    path("plans/<int:pk>/", plan_view, name="plan-detail"),
    path("plans/<int:pk>/accept/", plan_accept, name="plan-accept"),
    path("plans/<int:pk>/decline/", plan_decline, name="plan-decline"),
    path("calendar/", calendar_days, name="calendar"),
    path("calendar/month/", calendar_month, name="calendar-month"),
    path("workouts/<int:pk>/", workout_view, name="workout"),
    path("workouts/<int:pk>/guide/", workout_guide, name="workout-guide"),
    path("workouts/<int:pk>/review/", workout_review, name="workout-review"),
    path("activities/<int:pk>/ai-review/", activity_ai_review, name="activity-ai-review"),
    path("activities/<int:pk>/review/", activity_review, name="activity-review"),
    # R7.
    path("today/", today, name="today"),
    path("today/apply/", today_apply, name="today-apply"),
    path("today/explain/", today_explain, name="today-explain"),
    path("workouts/<int:pk>/garmin/", workout_garmin, name="workout-garmin"),
    path("plans/active/garmin/", plan_garmin, name="plan-garmin"),
]
