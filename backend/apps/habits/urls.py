from django.urls import path

from . import r13, views
from .lung import lung_recovery

urlpatterns = [
    path("habits/logs/", views.logs, name="habit-logs"),
    path("habits/logs/<int:pk>/", views.log_detail, name="habit-log"),
    path("habits/today/", views.today, name="habit-today"),
    path("habits/summary/", views.summary, name="habit-summary"),
    path("habits/lung-recovery/", lung_recovery, name="habit-lung-recovery"),
    # R13 §8 / §9
    path("habits/cravings/", r13.cravings, name="habit-cravings"),
    path("habits/cravings/summary/", r13.craving_summary, name="habit-cravings-summary"),
    path("habits/cravings/<int:pk>/", r13.craving_detail, name="habit-craving"),
    path("habits/caffeine/", r13.caffeine, name="habit-caffeine"),
]
