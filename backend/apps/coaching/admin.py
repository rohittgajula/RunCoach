from django.contrib import admin

from .models import AIAnalysis, AIRequestLog


@admin.register(AIRequestLog)
class AIRequestLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "operation", "model", "status",
                    "input_tokens", "output_tokens", "estimated_cost_usd", "latency_ms")
    list_filter = ("operation", "status", "model")
    date_hierarchy = "created_at"


@admin.register(AIAnalysis)
class AIAnalysisAdmin(admin.ModelAdmin):
    list_display = ("created_at", "kind", "athlete", "model", "prompt_version")
    list_filter = ("kind", "model", "prompt_version")


from .models import ChatMessage, ChatThread, MemoryFact  # noqa: E402


@admin.register(ChatThread)
class ChatThreadAdmin(admin.ModelAdmin):
    list_display = ("updated_at", "athlete", "title")


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "thread", "role", "status")
    list_filter = ("role", "status")


@admin.register(MemoryFact)
class MemoryFactAdmin(admin.ModelAdmin):
    list_display = ("created_at", "athlete", "text", "source")
