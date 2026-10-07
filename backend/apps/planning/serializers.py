from rest_framework import serializers

from .models import Race


class RaceSerializer(serializers.ModelSerializer):
    # R13 §2: the race-day planner's inputs.
    goal_time_s = serializers.IntegerField(min_value=600, max_value=172800, allow_null=True,
                                           required=False)
    start_time = serializers.TimeField(format="%H:%M", input_formats=["%H:%M", "%H:%M:%S"],
                                       allow_null=True, required=False)

    class Meta:
        model = Race
        fields = ["id", "name", "date", "distance_km", "is_target", "notes", "goal_time_s",
                  "start_time"]

    def validate(self, attrs):
        athlete = self.context["request"].user.athlete
        target = attrs.get("is_target", getattr(self.instance, "is_target", False))
        if target:
            # Two A races means two ramps, and the resolver would silently pick the
            # earlier one. Refuse rather than let the plan disagree with itself.
            existing = Race.objects.filter(athlete=athlete, is_target=True)
            if self.instance:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise serializers.ValidationError(
                    {"is_target": "You already have a target race. Unset that one first."}
                )
        return attrs
