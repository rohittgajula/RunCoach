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
        # R15: the primary route failed and the call went on to the tier's fallback.
        FALLBACK = "fallback", "Fell back"

    class ErrorKind(models.TextChoices):
        BUSY = "busy", "Busy / overloaded"
        NO_QUOTA = "no_quota", "No quota"
        UNAVAILABLE = "unavailable", "Model unavailable"
        AUTH = "auth", "Key rejected"
        BAD_REQUEST = "bad_request", "Bad request"
        TIMEOUT = "timeout", "Timed out"
        OTHER = "other", "Other"

    # Null only for an admin's "test a prompt" call (R14 §14), which belongs to nobody.
    athlete = models.ForeignKey(
        "athletes.Athlete", on_delete=models.CASCADE, related_name="ai_requests",
        null=True, blank=True,
    )
    operation = models.CharField(max_length=40, db_index=True)
    # R14: the tier the operation resolved through when the call was made, so the stats
    # stay right after an operation moves to another tier.
    tier = models.CharField(max_length=10, blank=True, default="", db_index=True)
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
    # R15: plain categorisation of `error` (blank for successful rows).
    error_kind = models.CharField(max_length=12, choices=ErrorKind.choices, blank=True,
                                  default="")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.operation} {self.status} {self.input_tokens}+{self.output_tokens}"

    def save(self, *args, **kwargs):
        if not self.tier:
            from django.conf import settings

            self.tier = ("admin" if self.operation.startswith("admin_")
                         else settings.AI_MODEL_TIERS.get(self.operation, "fast"))
        super().save(*args, **kwargs)


class AIConfig(models.Model):
    """R14 §14: which provider + model serves a tier. A row overrides the env default
    (AI_PROVIDER + AI_<TIER>_MODEL) for that tier; no row = env. Operator data, not tenant
    data."""

    class Tier(models.TextChoices):
        LITE = "lite", "Lite"
        FAST = "fast", "Fast"
        COACH = "coach", "Coach"
        DEEP = "deep", "Deep"

    tier = models.CharField(max_length=10, choices=Tier.choices, unique=True)
    provider = models.CharField(max_length=20)
    model = models.CharField(max_length=80)
    # R15: where a call goes when the primary route keeps failing. Null = the env route
    # for this tier (AI_PROVIDER + AI_<TIER>_MODEL).
    fallback_provider = models.CharField(max_length=20, null=True, blank=True)
    fallback_model = models.CharField(max_length=80, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.tier}: {self.provider}/{self.model}"


class ModelStatus(models.Model):
    """R15: the last "Check models" probe of one provider model."""

    class Status(models.TextChoices):
        OK = "ok", "OK"
        BUSY = "busy", "Busy"
        NO_QUOTA = "no_quota", "No quota"
        UNAVAILABLE = "unavailable", "Unavailable"
        ERROR = "error", "Error"

    provider = models.CharField(max_length=20)
    model = models.CharField(max_length=80)
    status = models.CharField(max_length=12, choices=Status.choices)
    error_kind = models.CharField(max_length=12, blank=True, default="")
    detail = models.CharField(max_length=300, blank=True, default="")
    checked_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["provider", "model"],
                                               name="uniq_model_status")]

    def __str__(self):
        return f"{self.provider}/{self.model}: {self.status}"


class CompareRun(models.Model):
    """R15 §B: one admin "compare providers" run — the prompt and every target's answer.
    Operator data: holds aggregates only (never a name, a note or the private habit)."""

    created_by = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True,
                                   related_name="ai_compare_runs")
    prompt = models.TextField()
    operation = models.CharField(max_length=40, blank=True, default="")
    context_note = models.CharField(max_length=200, blank=True, default="")
    # [{index, provider, model, ok, status, error_kind, error, hint, text, latency_ms,
    #   input_tokens, output_tokens, cost_usd, rating}]
    results = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"compare {self.pk} ({len(self.results)} targets)"


class ModelPrice(models.Model):
    """R14 §14: USD per million tokens, editable by an admin. Also the list of models
    a tier can be pointed at. Approximate — the provider's dashboard is authoritative."""

    provider = models.CharField(max_length=20)
    model = models.CharField(max_length=80)
    input_per_m_usd = models.FloatField()
    output_per_m_usd = models.FloatField()
    note = models.CharField(max_length=200, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["provider", "model"]
        constraints = [models.UniqueConstraint(fields=["provider", "model"],
                                               name="uniq_model_price")]

    def __str__(self):
        return f"{self.provider}/{self.model} {self.input_per_m_usd}/{self.output_per_m_usd}"


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
        BRIEFING = "briefing", "Morning briefing"
        RUN_REVIEW = "run_review", "Post-run coach review"
        MONTHLY_CARD = "monthly_card", "Monthly report"

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
