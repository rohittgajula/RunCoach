from django.contrib import admin

from .models import Meal


@admin.register(Meal)
class MealAdmin(admin.ModelAdmin):
    list_display = ("local_date", "athlete", "meal_type", "description", "kcal", "source")
    list_filter = ("meal_type", "source")
