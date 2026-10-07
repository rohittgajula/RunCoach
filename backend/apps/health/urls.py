from django.urls import path

from . import achievements, compare_views, forecast_views, garmin_views, reports

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
    path("reports/weekly/", reports.weekly, name="weekly-report"),
    path("reports/weekly/list/", reports.weekly_list, name="weekly-report-list"),
    path("reports/weekly/ai/", reports.weekly_ai, name="weekly-report-ai"),
    path("achievements/", achievements.achievements, name="achievements"),
    path("achievements/seen/", achievements.achievements_seen, name="achievements-seen"),
]
