"""Django settings.

Everything environment-dependent comes from the environment. Nothing here holds a
secret, a model name, or a threshold — those live in .env so they can change without
a code change, and so a bad value is a config bug rather than a deploy.
"""

import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(int(default))).lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


from .security import (  # noqa: E402
    DEV_SECRET_KEY, check_production_settings, resolve_registration_mode,
)

DEBUG = env_bool("DJANGO_DEBUG", True)
# The dev default only ever applies with DEBUG on: check_production_settings refuses
# to start a DEBUG=0 process with it, a short key, or ALLOWED_HOSTS="*".
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", DEV_SECRET_KEY if DEBUG else "")
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "*")
check_production_settings(DEBUG, SECRET_KEY, ALLOWED_HOSTS)
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# --- HTTPS behind Cloudflare + Traefik (docs/DEPLOY.md §1) --------------------
# No SECURE_SSL_REDIRECT: Cloudflare and Traefik already redirect, and a third
# redirect behind a TLS-terminating proxy is how you get a loop.
SECURE = env_bool("DJANGO_SECURE", False)
if SECURE:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31_536_000      # one year, no preload
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False
    # Deliberate per docs/DEPLOY.md §1, so `check --deploy` stays readable:
    # redirect is done by Cloudflare/Traefik (W008); no subdomains/preload (W005/W021).
    SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W008", "security.W021"]
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"

# Throttles key on REMOTE_ADDR. Behind Cloudflare that is a Cloudflare edge, so
# config.middleware.RealClientIPMiddleware swaps in CF-Connecting-IP — only when
# this is on, because anywhere else the header is attacker-controlled.
TRUST_CF_CONNECTING_IP = env_bool("TRUST_CF_CONNECTING_IP", False)

# open · invite · closed. See apps/athletes/invites.py.
REGISTRATION_MODE = resolve_registration_mode(os.environ.get("REGISTRATION_MODE"), DEBUG)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "django_filters",
    "django_celery_beat",
    # Bundled with simplejwt. Without it in INSTALLED_APPS *and* migrated,
    # ROTATE_REFRESH_TOKENS and BLACKLIST_AFTER_ROTATION are silently inert:
    # the settings are accepted, logout appears to work, and nothing is revoked.
    "rest_framework_simplejwt.token_blacklist",
    # Project apps go here as you create them at M1. See docs/ROADMAP.md.
    "apps.athletes",
    "apps.ingest",
    "apps.activities",
    "apps.planning",
    "apps.coaching",
    "apps.journal",
    "apps.diet",
    "apps.habits",
    # R10
    "apps.gear",
    "apps.health",
    "apps.reminders",
]

MIDDLEWARE = [
    # First: everything after it (throttles included) should see the real client.
    "config.middleware.RealClientIPMiddleware",
    # Answers the probes before ALLOWED_HOSTS is enforced: kubelet sends Host=<pod IP>.
    "config.middleware.HealthProbeMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # R18 §B: data_version on mutation responses + X-Data-Version.
    "config.middleware.DataVersionMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "runanalizer"),
        "USER": os.environ.get("POSTGRES_USER", "runanalizer"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "runanalizer"),
        "HOST": os.environ.get("POSTGRES_HOST", "db"),
        "PORT": os.environ.get("POSTGRES_PORT_INTERNAL", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": f"django.contrib.auth.password_validation.{v}"}
    for v in (
        "UserAttributeSimilarityValidator",
        "MinimumLengthValidator",
        "CommonPasswordValidator",
        "NumericPasswordValidator",
    )
]

LANGUAGE_CODE = "en-us"

# Deliberately UTC. Every athlete-facing date goes through the athlete's own
# local-today helper instead — Django's localdate() at 00:48 in Kolkata still
# returns yesterday, which silently mis-files a run and its journal entry.
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
# Set from day one. Without it the admin loses its CSS the moment DEBUG=0, and you
# find that out during a deploy rather than now.
STATIC_ROOT = BASE_DIR / "staticfiles"
# Served by WhiteNoise from STATIC_ROOT (collectstatic runs at image build). Hashed
# names in production; plain ones in DEBUG so nothing needs collectstatic locally.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedStaticFilesStorage" if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        ),
    },
}
# Under /api/ so the frontend's dev proxy (which forwards only /api) reaches it.
# Public serving of MEDIA_URL happens in DEBUG only. Meal photos are handed out as
# signed, expiring URLs (apps/diet/media.py) that work with or without DEBUG.
MEDIA_URL = "/api/media/"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT") or BASE_DIR / "media")
SIGNED_MEDIA_TTL_SEC = int(os.environ.get("SIGNED_MEDIA_TTL_SEC", "3600"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    # 0 = ignore X-Forwarded-For and key on REMOTE_ADDR. DRF's default (None) uses
    # the whole client-supplied XFF header, so anyone could reset their own counter.
    # The real client IP comes from RealClientIPMiddleware instead.
    "NUM_PROXIES": 0,
    # AllowAny does not mean unthrottled. These three are the public endpoints, and
    # an unthrottled login on a public host is found by scanners within days.
    "DEFAULT_THROTTLE_RATES": {
        "register": "5/hour",   # per IP
        "login": "10/min",      # per IP — brute-force ceiling (also: account deletion)
        "refresh": "60/min",    # per IP — generous; a 15-min access token refreshes often
        "garmin_connect": "5/hour",  # per IP — each attempt is a real Garmin login
        "garmin": "10/hour",    # per user — sync; Garmin rate-limits by IP, see docs/HOSTING.md
        "ai": "30/day",         # per user — this one is money, see docs/COST.md
        # Chat turns and meal estimates. Higher than "ai" because a conversation is
        # many short turns; the monthly call budget in coaching/services.py is still
        # the real money limit.
        "chat": "150/day",
    },
}

# Access token: 15 minutes, held in JS memory only on the client.
# Refresh token: 7 days, in an httpOnly cookie the client cannot read.
# localStorage was rejected for either — XSS can read it, and a JWT stored there
# cannot be revoked on logout.
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    # Without this, rotation issues a new refresh token and leaves the OLD one valid
    # for its full 7 days — a stolen one keeps working alongside the real one.
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
}

REFRESH_COOKIE_NAME = "refresh_token"
# Scoped so the cookie is not attached to every API call, only the auth endpoints.
REFRESH_COOKIE_PATH = "/api/auth/"

CORS_ALLOWED_ORIGINS = [
    o for o in os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o
]
CORS_ALLOW_CREDENTIALS = True

# --- Celery ------------------------------------------------------------------
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

# Redis-backed so the Garmin circuit breaker is shared across workers. A per-process
# cache would let each worker discover the rate limit separately, which is how you
# turn one block into several.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# A task that is retried must not double-write, so acks_late is paired with
# idempotent tasks rather than used to paper over non-idempotent ones.
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

# Queue separation matters: a stuck AI call must not block the next Garmin sync, and
# Garmin work is deliberately serialised (see docs/HOSTING.md) while metrics are not.
CELERY_TASK_ROUTES = {
    # R7: pushing workouts to Garmin shares the serialised garmin queue.
    "planning.garmin_push": {"queue": "garmin"},
    "planning.garmin_forget": {"queue": "garmin"},
    # R13 §4: strength workouts to the watch, same serialised queue and breaker.
    "planning.garmin_strength_push": {"queue": "garmin"},
    "ingest.*": {"queue": "garmin"},
    "activities.*": {"queue": "metrics"},
    "coaching.*": {"queue": "ai"},
    "planning.*": {"queue": "planning"},
    # R10: report cards, badges and reminders are light database work (and push sends).
    "health.*": {"queue": "metrics"},
    "reminders.*": {"queue": "metrics"},
    # R13 §15: data export (database reads + a ZIP on the media volume).
    "athletes.*": {"queue": "metrics"},
}

from celery.schedules import crontab  # noqa: E402

CELERY_BEAT_SCHEDULE = {
    "sync-every-morning": {
        "task": "ingest.sync_all",
        # Staggered inside the task by athlete id; this is only the window opening.
        "schedule": crontab(hour=5, minute=30),
    },
    "derive-anything-stale": {
        "task": "activities.derive_stale",
        "schedule": crontab(minute="*/20"),
    },
    "analyse-what-is-ready": {
        "task": "coaching.analyse_ready",
        "schedule": crontab(minute="*/30"),
    },
    # Monday 01:00 UTC (06:30 in India): adapt the new week to last week's running.
    "adapt-plans-monday": {
        "task": "planning.adapt_all",
        "schedule": crontab(hour=1, minute=0, day_of_week=1),
    },
    # R22: daily, after the morning sync has landed. Asks each active plan
    # whether the last fortnight actually happened, and rebuilds the weeks
    # ahead from what did. Daily because what it looks for is silence, and a
    # weekly check means up to seven more days of a plan nobody is following.
    "catch-the-plan-up-daily": {
        "task": "planning.catchup_all",
        "schedule": crontab(hour=6, minute=30),
    },
    # R7 §1: hourly; the task picks athletes whose local time is 07:xx, syncs their
    # wellness, then computes the check-in (never applies it).
    "morning-checkins": {
        "task": "planning.morning_checkins",
        "schedule": crontab(minute=5),
    },
    "weekly-review-sunday-evening": {
        "task": "coaching.weekly_reviews",
        "schedule": crontab(hour=18, minute=0, day_of_week=0),
    },
    # R10 §C10: hourly; the task builds last week's report for athletes whose local
    # time is Monday 06:xx (idempotent per athlete and week).
    "weekly-reports-monday-morning": {
        "task": "health.weekly_reports",
        "schedule": crontab(minute=2),
    },
    # R10 §C13: badges are also awarded on read and after each sync; this catches the
    # rest (smoke-free days tick over with no other activity).
    "award-achievements": {
        "task": "health.award_all",
        "schedule": crontab(minute=40),
    },
    # R10 §C12: every 5 minutes; each reminder goes once per local day at its time.
    # R13 §11: hourly; builds last month's report on the 1st at 06:xx local.
    "monthly-reports": {
        "task": "health.monthly_reports",
        "schedule": crontab(minute=4),
    },
    # R13 §6/§4/§15: hourly — briefings at the wake time, strength placement top-up,
    # expired export cleanup.
    "morning-briefings": {
        "task": "health.morning_briefings",
        "schedule": crontab(minute="*/15"),
    },
    "strength-topup": {
        "task": "planning.strength_topup",
        "schedule": crontab(hour=2, minute=20),
    },
    "export-cleanup": {
        "task": "athletes.export_cleanup",
        "schedule": crontab(minute=50),
    },
    # R14 §3: weather-smart reschedule check, 18:xx local (the task filters by hour).
    "weather-checks": {
        "task": "planning.weather_checks",
        "schedule": crontab(minute=12),
    },
    "send-reminders": {
        "task": "reminders.send_due",
        "schedule": crontab(minute="*/5"),
    },
    # R11 §C: today's steps + stress for athletes with the move/breathing nudge on,
    # at most every INTRADAY_REFRESH_MIN minutes inside their nudge hours.
    "intraday-refresh-for-nudges": {
        "task": "ingest.intraday_refresh",
        "schedule": crontab(minute="*/15"),
    },
}

# Queue separation matters from the start: a stuck AI call must not block the next
# Garmin sync. M7 routes tasks onto these.
CELERY_TASK_QUEUES_NAMES = ["garmin", "metrics", "ai", "planning"]

# --- Garmin ------------------------------------------------------------------
# Only the refreshable OAuth token is ever written here. The password is used once
# to obtain it and is never persisted, logged, or echoed back.
GARMIN_TOKEN_DIR = os.environ.get("GARMIN_TOKEN_DIR", "/app/.garmin")

# R10 §B: pause between the slow-changing Garmin calls (endurance score, PRs, gear …),
# so one athlete's daily fetch never arrives as a burst from this IP.
GARMIN_SLOW_PAUSE_S = float(os.environ.get("GARMIN_SLOW_PAUSE_S", "1.5"))

# R11 §C: how often (minutes) today's intraday steps + stress are refreshed for athletes
# who turned on the move or breathing nudge (2 requests each, only inside their hours).
# 0 turns the refresh off; nudges then use whatever the regular syncs fetched.
INTRADAY_REFRESH_MIN = int(os.environ.get("INTRADAY_REFRESH_MIN", "60"))

# --- Web push (R10 §C12) -----------------------------------------------------------
# All three or the reminders feature hides itself. Generate the key pair once with the
# one-liner in docs/API_NOTES.md (R10 §C12). The private key never leaves the server;
# the public key is handed to browsers by GET /api/reminders/.
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "")

# --- AI ----------------------------------------------------------------------
# One provider is active at a time. Operations name a TIER, never a model ID, so
# switching provider or upgrading a model is an .env edit rather than a code change.
AI_PROVIDER = os.environ.get("AI_PROVIDER", "openai")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
# R14 §14: Google AI Studio (Gemini) through its OpenAI-compatible endpoint, same client
# code (apps/coaching/client.py PROVIDERS). Empty = the provider shows "not configured"
# and no tier can be pointed at it. AI_PROVIDER stays the env default for every tier;
# the admin page's AIConfig rows override it per tier.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Provider-neutral names: only one provider is live, and operations resolve through
# the tier map below rather than reaching for a vendor-specific setting.
AI_MODELS = {
    "lite": os.environ.get("AI_LITE_MODEL", ""),
    "fast": os.environ.get("AI_FAST_MODEL", ""),
    "coach": os.environ.get("AI_COACH_MODEL", ""),
    "deep": os.environ.get("AI_DEEP_MODEL", ""),
}

# journal_extract is deliberately NOT on `lite`. It reads casual, code-switched
# Hindi/English written straight after a run, and it is where pain gets detected —
# the hardest reading task in the system and the one with safety consequences.
AI_MODEL_TIERS = {
    "journal_extract": "fast",
    "guidance": "coach",
    "run_analysis": "fast",
    "weekly_review": "coach",
    "plan_generation": "coach",
    "monthly_review": "deep",
    "summary": "lite",
    # RunCoach. Chat is the coach's voice; memory extraction is a cheap structured
    # pass after every reply; meal estimates need vision but not deep reasoning.
    "chat": "coach",
    "memory_extract": "lite",
    # R18: structured parameters from a memory fact the parser could not read.
    "memory_params": "lite",
    "meal_estimate": "fast",
    # R25: transcribing a lab report. On `fast` for its vision, not for reasoning —
    # it is a transcription job, and the numbers are validated in Python afterwards.
    "lab_extract": "fast",
    # R25: the pre-meal check. The coach's voice, and the one place a food answer
    # has to hold his bloods, his training load and his weight goal at once.
    "meal_precheck": "coach",
    # R25: arranging a day of food. The coach's voice, and it has to hold his
    # targets, his PG menu, his training and his bloods at once.
    "day_plan": "coach",
    # R6: the per-workout review and the Insights overview are the coach's voice.
    "workout_review": "coach",
    "insights_summary": "coach",
    # R7: the one-line morning check-in "why".
    "checkin_explain": "lite",
    # R8: habits explanation and the progress review are the coach's voice.
    "habits_summary": "coach",
    "progress_review": "coach",
    # R10 §C10: the optional paragraph on the weekly report card.
    "weekly_report": "coach",
    # R13: briefing phrasing is a cheap one-liner; the run review and monthly report
    # paragraphs are the coach's voice.
    "morning_briefing": "lite",
    "run_review": "coach",
    "monthly_report": "coach",
}

# Per athlete per month, every model call counted. Read by coaching/services.py.
AI_MONTHLY_CALL_BUDGET = int(os.environ.get("AI_MONTHLY_CALL_BUDGET", "200"))

AI_TIMEOUT_SEC = int(os.environ.get("AI_TIMEOUT_SEC", "60"))

# R14 §14: the GCP free-trial card on the admin page. Shown only, never enforced.
GCP_TRIAL_END = os.environ.get("GCP_TRIAL_END", "2027-01-03")
GCP_CREDIT_INR = os.environ.get("GCP_CREDIT_INR", "")
AI_MAX_RETRIES = int(os.environ.get("AI_MAX_RETRIES", "2"))

# --- Training safety ---------------------------------------------------------
# Thresholds live here, not scattered through the planner. Every one of these is a
# conservative choice open to review, not a universal law.
TRAINING = {
    "MAX_WEEKLY_INCREASE_PCT": float(os.environ.get("MAX_WEEKLY_INCREASE_PCT", "10")),
    "MAX_HARD_SESSIONS_PER_WEEK": int(os.environ.get("MAX_HARD_SESSIONS_PER_WEEK", "2")),
    "MIN_RECOVERY_DAYS_AFTER_HARD": int(os.environ.get("MIN_RECOVERY_DAYS_AFTER_HARD", "2")),
    "MAX_LONG_RUN_PCT_OF_WEEK": float(os.environ.get("MAX_LONG_RUN_PCT_OF_WEEK", "35")),
    "MIN_BUILD_WEEKS": int(os.environ.get("MIN_BUILD_WEEKS", "4")),
    "CUTBACK_EVERY_N_WEEKS": int(os.environ.get("CUTBACK_EVERY_N_WEEKS", "4")),
    "CUTBACK_FACTOR": float(os.environ.get("CUTBACK_FACTOR", "0.7")),
    # Prediction stays silent below this. A point estimate off six runs is fiction.
    "MIN_RUNS_FOR_PREDICTION": int(os.environ.get("MIN_RUNS_FOR_PREDICTION", "8")),
    "MIN_WEEKS_FOR_PREDICTION": int(os.environ.get("MIN_WEEKS_FOR_PREDICTION", "3")),
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
