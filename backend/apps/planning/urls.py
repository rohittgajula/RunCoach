from django.urls import path, re_path

from .arc_views import training_arc
from .calendar_views import calendar
from .goal_views import goal_create, goal_preview
from .plan_views import (
    PlanList, active_plan, activity_ai_review, activity_review, calendar_days, plan_accept,
    plan_decline, plan_rebuild, plan_view, workout_guide, workout_review, workout_view,
)
from .checkin_views import today, today_apply, today_explain
from .garmin_views import plan_garmin, workout_garmin
from .month_views import calendar_month
from . import (
    calendar_feed, edit_views, r13_views, r14_views, race_predict_views, reset_views,
    strength_review,
)
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
    path("plan/race-predictions/", race_predict_views.race_predictions,
         name="race-predictions"),
    path("plan/weeks/", plan_weeks, name="plan-weeks"),
    path("plan/session/", today_session_view, name="plan-session"),
    path("plan/calendar/", calendar, name="plan-calendar"),
    # RunCoach §5.
    path("plans/", PlanList.as_view(), name="plans"),
    path("plans/active/", active_plan, name="plan-active"),
    path("plans/active/rebuild/", plan_rebuild, name="plan-rebuild"),
    path("plans/reset/", reset_views.reset, name="plan-reset"),
    # R20: a distance by a date, run or run-walked. Preview first — the whole
    # value of this mode is the date it refuses.
    path("plans/goal/", goal_create, name="plan-goal"),
    path("plans/goal/preview/", goal_preview, name="plan-goal-preview"),
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
    # R13
    path("adjustments/", r13_views.adjustments, name="adjustments"),
    path("adjustments/<int:pk>/undo/", r13_views.adjustment_undo, name="adjustment-undo"),
    path("races/<int:pk>/plan/", r13_views.race_plan_view, name="race-plan"),
    path("strength/", r13_views.strength_list, name="strength"),
    path("strength/<int:pk>/", r13_views.strength_detail, name="strength-detail"),
    path("strength/<int:pk>/garmin/", r13_views.strength_garmin, name="strength-garmin"),
    path("strength/<int:pk>/review/", strength_review.strength_review,
         name="strength-review"),
    # R14
    path("plan/weather-suggestions/", r14_views.weather_suggestions,
         name="weather-suggestions"),
    path("plan/weather-suggestions/check/", r14_views.weather_suggestion_check,
         name="weather-suggestions-check"),
    path("plan/weather-suggestions/<int:pk>/apply/", r14_views.weather_suggestion_apply,
         name="weather-suggestion-apply"),
    path("plan/weather-suggestions/<int:pk>/dismiss/", r14_views.weather_suggestion_dismiss,
         name="weather-suggestion-dismiss"),
    path("calendar-feed/", calendar_feed.feed_view, name="calendar-feed"),
    # R18: the whole arc — past weeks and planned weeks on one axis.
    path("arc/", training_arc, name="training-arc"),
    # R16
    path("workouts/<int:pk>/edit/", edit_views.workout_edit, name="workout-edit"),
    path("workouts/<int:pk>/edit/undo/", edit_views.workout_edit_undo,
         name="workout-edit-undo"),
    path("plan/week-edit/", edit_views.week_edit, name="plan-week-edit"),
    re_path(r"^cal/(?P<token>[A-Za-z0-9_-]{20,100})\.ics$", calendar_feed.feed_ics,
            name="calendar-feed-ics"),
]
