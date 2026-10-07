from django.db import models

from apps.athletes.models import OwnedByAthlete


class AIRequestLog(models.Model):
    """Every call, including the failures — failed calls are billed too.

    Token counts come from the API response, never from string length: reasoning
    models bill internal thinking as output and none of it appears in the text you
    read, so estimating from the visible answer can be several times short.
    """

    class Status(models.TextChoices):
        OK = "ok", "OK"
        CACHED = "cached", "Cached"
        INVALID = "invalid", "Failed validation"
        REFUSED = "refused", "Refused by safety gate"
        ERROR = "error", "Error"

    athlete = models.ForeignKey(
        "athletes.Athlete", on_delete=models.CASCADE, related_name="ai_requests"
    )
    operation = models.CharField(max_length=40, db_index=True)
    provider = models.CharField(max_length=20)
    model = models.CharField(max_length=60)
    prompt_version = models.CharField(max_length=20)

    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    latency_ms = models.IntegerField(default=0)
    estimated_cost_usd = models.FloatField(default=0.0)

    status = models.CharField(max_length=10, choices=Status.choices)
    retry_count = models.IntegerField(default=0)
    error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.operation} {self.status} {self.input_tokens}+{self.output_tokens}"


class AIAnalysis(OwnedByAthlete):
    """A stored model response, keyed by what produced it.

    `input_hash` covers the context, the prompt version and the model. Identical
    inputs return the stored result rather than paying for the same answer twice —
    which during development is most of the traffic.

    Storing prompt_version and model separately is what makes it possible to tell a
    model change from a prompt change from a data change later.
    """

    class Kind(models.TextChoices):
        RUN = "run", "Run analysis"
        WEEKLY = "weekly", "Weekly review"
        GUIDANCE = "guidance", "Coaching guidance"
        JOURNAL = "journal", "Journal extraction"
        REVIEW = "review", "Workout review"
        INSIGHTS = "insights", "Insights overview"
        CHECKIN = "checkin", "Morning check-in explanation"
        HABITS = "habits", "Habits summary"
        PROGRESS = "progress", "Progress review"
        WEEKLY_CARD = "weekly_card", "Weekly report card"

    kind = models.CharField(max_length=12, choices=Kind.choices, db_index=True)
    activity = models.ForeignKey(
        "activities.Activity", on_delete=models.CASCADE,
        null=True, blank=True, related_name="analyses",
    )

    input_hash = models.CharField(max_length=64, db_index=True)
    prompt_version = models.CharField(max_length=20)
    model = models.CharField(max_length=60)

    result = models.JSONField()
    # What validation found. Attached rather than silently rewriting the answer: a
    # response quietly edited is one nobody can audit, and the findings are more
    # useful surfaced than swallowed.
    findings = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "AI analyses"
        constraints = [
            models.UniqueConstraint(
                fields=["athlete", "kind", "input_hash"], name="uniq_athlete_kind_hash"
            )
        ]

    def __str__(self):
        return f"{self.kind} {self.created_at:%Y-%m-%d}"


class ChatThread(OwnedByAthlete):
    """One conversation. The chat list shows these, newest activity first."""

    title = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title or f"Thread {self.pk}"


class ChatMessage(models.Model):
    """One message. Attachments are references ({type, id}), expanded on read, so a
    workout moved after the chat shows where it is now rather than where it was."""

    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"
        TOOL = "tool", "Tool"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        DONE = "done", "Done"
        ERROR = "error", "Error"

    thread = models.ForeignKey(ChatThread, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField(blank=True)
    attachments = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.DONE)
    # Every tool the model called and what it got back. For audit: when the coach
    # moves a workout, this is how you find out why.
    tool_calls = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.role}: {self.content[:60]}"


class MemoryFact(OwnedByAthlete):
    """A durable fact about the athlete, injected into every chat system prompt.

    Short and few on purpose: injuries, schedule constraints, preferences, goals. Not a
    transcript — that is what threads are for.
    """

    class Source(models.TextChoices):
        CHAT = "chat", "Chat"
        MANUAL = "manual", "Manual"

    text = models.CharField(max_length=300)
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.MANUAL)
    source_message = models.ForeignKey(
        ChatMessage, on_delete=models.SET_NULL, null=True, blank=True, related_name="memories"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.text[:60]
