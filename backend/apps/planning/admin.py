from django.contrib import admin

from .models import Race


@admin.register(Race)
class RaceAdmin(admin.ModelAdmin):
    list_display = ("name", "date", "distance_km", "is_target", "athlete")
    list_filter = ("is_target",)


from .models import PlannedWorkout, PlanPhase, TrainingPlan  # noqa: E402


@admin.register(TrainingPlan)
class TrainingPlanAdmin(admin.ModelAdmin):
    list_display = ("created_at", "athlete", "name", "status")
    list_filter = ("status",)


@admin.register(PlanPhase)
class PlanPhaseAdmin(admin.ModelAdmin):
    list_display = ("plan", "order", "name", "kind", "start", "end")


@admin.register(PlannedWorkout)
class PlannedWorkoutAdmin(admin.ModelAdmin):
    list_display = ("date", "athlete", "title", "kind", "status")
    list_filter = ("status", "kind")
