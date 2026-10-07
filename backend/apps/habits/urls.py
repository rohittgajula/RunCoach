from django.urls import path

from . import views

urlpatterns = [
    path("habits/logs/", views.logs, name="habit-logs"),
    path("habits/logs/<int:pk>/", views.log_detail, name="habit-log"),
    path("habits/today/", views.today, name="habit-today"),
    path("habits/summary/", views.summary, name="habit-summary"),
]
