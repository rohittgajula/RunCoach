from django.urls import path

from . import (
    achievements, briefing, compare_views, day_views, forecast_views, garmin_views, injury,
    monthly, mood, reports, wake_views,
)
from . import data_review, experiments, goals, heart, illness

urlpatterns = [
    path("health/fitness/", garmin_views.fitness, name="health-fitness"),
    path("health/training-status/", garmin_views.training_status,
         name="health-training-status"),
    path("health/sleep/", garmin_views.sleep, name="health-sleep"),
    path("health/form/", garmin_views.form, name="health-form"),
    path("health/records/", garmin_views.records, name="health-records"),
    path("health/body/", garmin_views.body, name="health-body"),
    path("health/compare/", compare_views.compare, name="health-compare"),
    path("health/compare/metrics/", compare_views.metrics, name="health-compare-metrics"),
    path("health/readiness-forecast/", forecast_views.readiness_forecast,
         name="health-readiness-forecast"),
    # R11
    path("health/day/", day_views.day, name="health-day"),
    path("health/day/summary/", day_views.day_summary, name="health-day-summary"),
    path("health/day/trends/", day_views.day_trends, name="health-day-trends"),
    # R12
    path("health/wake-plan/", wake_views.wake_plan_view, name="health-wake-plan"),
    path("health/watch-alarms/", wake_views.watch_alarms_view, name="health-watch-alarms"),
    path("alarm/", wake_views.alarm_view, name="alarm"),
    path("reports/weekly/", reports.weekly, name="weekly-report"),
    path("reports/weekly/list/", reports.weekly_list, name="weekly-report-list"),
    path("reports/weekly/ai/", reports.weekly_ai, name="weekly-report-ai"),
    path("achievements/", achievements.achievements, name="achievements"),
    path("achievements/seen/", achievements.achievements_seen, name="achievements-seen"),
    # R13
    path("health/injury/", injury.injury, name="health-injury"),
    path("health/pain/", injury.pain, name="health-pain"),
    path("health/pain/<int:pk>/", injury.pain_detail, name="health-pain-detail"),
    path("briefing/today/", briefing.today, name="briefing-today"),
    path("briefing/today/dismiss/", briefing.dismiss, name="briefing-dismiss"),
    path("briefing/today/ai/", briefing.briefing_ai, name="briefing-ai"),
    path("mood/", mood.moods, name="mood"),
    path("mood/today/", mood.mood_today, name="mood-today"),
    path("mood/<str:day>/", mood.mood_delete, name="mood-day"),
    path("reports/monthly/", monthly.monthly, name="monthly-report"),
    path("reports/monthly/list/", monthly.monthly_list, name="monthly-report-list"),
    path("reports/monthly/ai/", monthly.monthly_ai, name="monthly-report-ai"),
    # R14
    path("experiments/", experiments.experiments, name="experiments"),
    path("experiments/templates/", experiments.templates, name="experiment-templates"),
    path("experiments/active/", experiments.experiment_active, name="experiment-active"),
    path("experiments/<int:pk>/", experiments.experiment_detail, name="experiment"),
    path("experiments/<int:pk>/stop/", experiments.experiment_stop, name="experiment-stop"),
    path("goals/", goals.goals, name="goals"),
    path("goals/chip/", goals.goal_chip, name="goal-chip"),
    path("goals/<int:pk>/", goals.goal_detail, name="goal"),
    path("goals/<int:pk>/values/", goals.goal_values, name="goal-values"),
    path("health/heart/", heart.heart, name="health-heart"),
    # R17
    path("illness/", illness.illness_view, name="illness"),
    path("illness/history/", illness.illness_history, name="illness-history"),
    path("illness/<int:pk>/", illness.illness_detail, name="illness-detail"),
    path("illness/<int:pk>/recover/", illness.illness_recover, name="illness-recover"),
    path("data-review/", data_review.data_review, name="data-review"),
    path("data-review/decide/", data_review.data_review_decide, name="data-review-decide"),
]
