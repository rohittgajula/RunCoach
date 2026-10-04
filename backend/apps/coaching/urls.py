from django.urls import path

from .chat_views import memory, memory_delete, messages, thread_detail, threads
from .insights import insights, insights_summary
from .views import guidance, review, run_analysis, usage

urlpatterns = [
    path("coach/guidance/", guidance, name="coach-guidance"),
    path("coach/weekly/", review, name="coach-weekly"),
    path("coach/usage/", usage, name="coach-usage"),
    path("activities/<int:pk>/analysis/", run_analysis, name="run-analysis"),
    path("chat/threads/", threads, name="chat-threads"),
    path("chat/threads/<int:pk>/", thread_detail, name="chat-thread"),
    path("chat/threads/<int:pk>/messages/", messages, name="chat-messages"),
    path("memory/", memory, name="memory"),
    path("memory/<int:pk>/", memory_delete, name="memory-fact"),
    path("insights/", insights, name="insights"),
    path("insights/summary/", insights_summary, name="insights-summary"),
]
