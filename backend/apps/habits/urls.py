from django.urls import path

from . import views
from .lung import lung_recovery

urlpatterns = [
    path("habits/logs/", views.logs, name="habit-logs"),
    path("habits/logs/<int:pk>/", views.log_detail, name="habit-log"),
    path("habits/today/", views.today, name="habit-today"),
    path("habits/summary/", views.summary, name="habit-summary"),
    path("habits/lung-recovery/", lung_recovery, name="habit-lung-recovery"),
]
