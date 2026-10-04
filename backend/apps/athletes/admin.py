from django.contrib import admin

from .models import Athlete


@admin.register(Athlete)
class AthleteAdmin(admin.ModelAdmin):
    list_display = ("display_name", "user", "timezone", "garmin_connected", "garmin_last_sync")
    list_filter = ("garmin_connected", "timezone")
    search_fields = ("display_name", "user__username", "user__email")
    readonly_fields = ("created_at", "updated_at")


from .models import MetricEntry  # noqa: E402


@admin.register(MetricEntry)
class MetricEntryAdmin(admin.ModelAdmin):
    list_display = ("recorded_at", "athlete", "kind", "value", "source")
    list_filter = ("kind", "source")


from django.contrib import messages  # noqa: E402
from django.shortcuts import redirect  # noqa: E402
from django.urls import path, reverse  # noqa: E402

from .models import InviteCode  # noqa: E402


def _generate(note: str = "", max_uses: int = 1, expires_at=None) -> InviteCode:
    return InviteCode.objects.create(note=note, max_uses=max_uses, expires_at=expires_at)


@admin.register(InviteCode)
class InviteCodeAdmin(admin.ModelAdmin):
    """Codes are generated, not typed: "Generate code" on the list page, or the
    action to mint a fresh code like each selected one (same note, uses, expiry)."""

    list_display = ("code", "note", "uses", "max_uses", "expires_at", "created_at")
    search_fields = ("code", "note")
    readonly_fields = ("uses", "created_at")
    actions = ["generate_like_selected"]
    change_list_template = "admin/athletes/invitecode/change_list.html"

    @admin.action(description="Generate a new code like each selected one")
    def generate_like_selected(self, request, queryset):
        made = [_generate(c.note, c.max_uses, c.expires_at).code for c in queryset]
        self.message_user(request, f"New code(s): {', '.join(made)}", messages.SUCCESS)

    def get_urls(self):
        return [
            path(
                "generate/",
                self.admin_site.admin_view(self.generate_view),
                name="athletes_invitecode_generate",
            ),
        ] + super().get_urls()

    def generate_view(self, request):
        if request.method != "POST" or not self.has_add_permission(request):
            return redirect(reverse("admin:athletes_invitecode_changelist"))
        code = _generate(note="generated from admin").code
        self.message_user(request, f"New invite code: {code}", messages.SUCCESS)
        return redirect(reverse("admin:athletes_invitecode_changelist"))
