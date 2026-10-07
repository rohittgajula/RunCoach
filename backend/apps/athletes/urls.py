from django.urls import path

from . import export
from .profile_views import entries_view, entry_delete, fitness_view, profile_summary
from .views import (
    AthleteDetailView, LoginView, LogoutView, MeView, RefreshView, RegisterView,
    RegistrationModeView,
)

urlpatterns = [
    path("auth/register/", RegisterView.as_view(), name="register"),
    path("auth/registration/", RegistrationModeView.as_view(), name="registration-mode"),
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/refresh/", RefreshView.as_view(), name="refresh"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("auth/me/", MeView.as_view(), name="me"),
    path("athlete/", AthleteDetailView.as_view(), name="athlete"),
    path("profile/summary/", profile_summary, name="profile-summary"),
    path("metrics/fitness/", fitness_view, name="metrics-fitness"),
    path("metrics/entries/", entries_view, name="metrics-entries"),
    path("metrics/entries/<int:pk>/", entry_delete, name="metrics-entry"),
    # R13 §15
    path("export/", export.create, name="export"),
    path("export/latest/", export.latest, name="export-latest"),
    path("export/<int:pk>/download/", export.download, name="export-download"),
]
