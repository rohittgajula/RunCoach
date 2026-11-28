from django.urls import path

from .food_views import food_list, missing, plan_today, profile
from .media import serve_signed
from .views import (
    MealCreate, MealDetail, day_view, estimate_view, precheck_view, trend_view,
)
from .water import water, water_delete

urlpatterns = [
    path("diet/day/", day_view, name="diet-day"),
    path("diet/trend/", trend_view, name="diet-trend"),
    path("diet/meals/", MealCreate.as_view(), name="diet-meals"),
    path("diet/meals/estimate/", estimate_view, name="diet-meal-estimate"),
    # R25: "should I eat this?" — asked before the meal, never saved.
    path("diet/precheck/", precheck_view, name="diet-precheck"),
    # R25: what to eat today, and what has been missing.
    path("diet/profile/", profile, name="diet-profile"),
    path("diet/foods/", food_list, name="diet-foods"),
    path("diet/plan/", plan_today, name="diet-plan"),
    path("diet/missing/", missing, name="diet-missing"),
    path("diet/meals/<int:pk>/", MealDetail.as_view(), name="diet-meal"),
    # R11 §D
    path("diet/water/", water, name="diet-water"),
    path("diet/water/<int:pk>/", water_delete, name="diet-water-delete"),
    # No auth header possible from <img>; the signature is the permission.
    path("media/signed/<path:path>", serve_signed, name="media-signed"),
]
