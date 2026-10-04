from django.urls import path

from .views import MealCreate, MealDetail, day_view, estimate_view, trend_view

urlpatterns = [
    path("diet/day/", day_view, name="diet-day"),
    path("diet/trend/", trend_view, name="diet-trend"),
    path("diet/meals/", MealCreate.as_view(), name="diet-meals"),
    path("diet/meals/estimate/", estimate_view, name="diet-meal-estimate"),
    path("diet/meals/<int:pk>/", MealDetail.as_view(), name="diet-meal"),
]
