"""R15: Gemini robustness (error kinds, bounded retry, per-tier fallback, live model
lists, "Check models", model cards, one-click switch), compare providers, the watch-sized
run summary push and share data. No real HTTP anywhere: every AI client is a fake."""

import datetime as dt
from types import SimpleNamespace

import pytest
from django.utils import timezone

from analysis import share as share_maths
from apps.activities import run_summary
from apps.activities.models import ActivityRecord, RunReview
from apps.coaching import client as ai_client
from apps.coaching import model_catalog, model_list
from apps.coaching.models import AIConfig, AIRequestLog, CompareRun, ModelPrice, ModelStatus
from tests.r10_helpers import run
from tests.test_r14_admin_ai import (  # noqa: F401 — fixtures
    GEMINI_KEY, fakes, keys, response, staff,
)


class HTTPError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status_code = status


BUSY = HTTPError(503, "Error code: 503 - The model is overloaded due to high demand.")
GONE = HTTPError(404, "models/gemini-2.5-flash is no longer available to new users.")
PRO_QUOTA = HTTPError(429, "You exceeded your current quota, please check your plan and "
                           "billing details. Quota exceeded for metric: generate_content_free_"
                           "tier_requests, limit: 0, model: gemini-3.1-pro")
RATE = HTTPError(429, "Rate limit reached: requests per minute (RPM): limit 15")


def _tier(tier, provider, model, fallback=None):
    ModelPrice.objects.get_or_create(provider=provider, model=model,
                                     defaults={"input_per_m_usd": 1.0, "output_per_m_usd": 2.0})
    AIConfig.objects.create(tier=tier, provider=provider, model=model,
                            fallback_provider=fallback[0] if fallback else None,
                            fallback_model=fallback[1] if fallback else None)


# --- error kinds + backoff (pure) ---------------------------------------------------------

@pytest.mark.parametrize("exc,kind", [
    (BUSY, "busy"),
    (HTTPError(500, "internal"), "busy"),
    (RATE, "busy"),
    (PRO_QUOTA, "no_quota"),
    (HTTPError(429, "insufficient_quota: You exceeded your current quota"), "no_quota"),
    (GONE, "unavailable"),
    (HTTPError(401, "Incorrect API key provided"), "auth"),
    (HTTPError(403, "PERMISSION_DENIED"), "auth"),
    (HTTPError(400, "Invalid argument"), "bad_request"),
    (TimeoutError("timed out"), "timeout"),
    (type("APITimeoutError", (Exception,), {})("Request timed out."), "timeout"),
    (ValueError("weird"), "other"),
])
def test_error_kind_mapping(exc, kind):
    assert ai_client.classify(exc) == kind
    assert ai_client.is_transient(kind) is (kind == "busy")


def test_hints_are_plain_sentences():
    assert ai_client.hint_for("no_quota", "gemini", "gemini-3.1-pro-preview") == \
        "Pro models need billing on your Google AI Studio key."
    assert "free-tier" in ai_client.hint_for("no_quota", "gemini", "gemini-3.8-flash")
    for kind in ("busy", "unavailable", "auth", "bad_request", "timeout", "other"):
        assert ai_client.hint_for(kind, "gemini", "x").endswith(".")


def test_backoff_is_bounded(monkeypatch):
    monkeypatch.setattr(ai_client, "_jitter", lambda high: high)     # worst case
    delays = [ai_client.backoff_delay(i) for i in range(ai_client.MAX_TRANSIENT_RETRIES)]
    assert delays == [3.0, 4.5] and sum(delays) <= ai_client.BACKOFF_BUDGET_S
    monkeypatch.setattr(ai_client, "_jitter", lambda high: 0.0)
    assert ai_client.backoff_delay(0) == 1.5


def test_call_policy_retries_busy_only(no_real_model_list):
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise BUSY
        return "ok"

    assert ai_client.call_policy(flaky) == ("ok", 2)
    assert len(no_real_model_list) == 2 and sum(no_real_model_list) <= 12

    calls.clear()

    def quota():
        calls.append(1)
        raise PRO_QUOTA

    with pytest.raises(HTTPError):
        ai_client.call_policy(quota)
    assert len(calls) == 1                                  # quota is never retried


# --- fallback -----------------------------------------------------------------------------

def _explain(athlete):
    from apps.coaching.services import checkin_explanation

    payload = {"date": "2026-10-07", "verdict": "easy", "headline": "Take it easy",
               "signals": [], "signals_missing": [], "planned": "Easy run", "changed_to": None}
    return checkin_explanation(athlete, payload)


def test_busy_gemini_retries_then_falls_back_to_env_openai(keys, fakes, athlete,
                                                           no_real_model_list):
    _tier("lite", "gemini", "gemini-3.8-flash")
    gemini = fakes("gemini", [BUSY, BUSY, BUSY])
    openai = fakes("openai", [response(content='{"text": "Easy today."}')])
    assert _explain(athlete) == "Easy today."
    assert len(gemini.requests) == 3 and len(openai.requests) == 1
    assert openai.requests[0]["model"] == "test-model"          # env route for the tier
    assert len(no_real_model_list) == 2 and sum(no_real_model_list) <= 12
    rows = list(AIRequestLog.objects.filter(athlete=athlete).order_by("id"))
    assert [(r.status, r.provider, r.error_kind) for r in rows] == [
        ("fallback", "gemini", "busy"), ("ok", "openai", "")]
    assert rows[0].retry_count == 2 and rows[0].model == "gemini-3.8-flash"
    # A fallback costs one budgeted call: only ok/invalid rows count towards the budget.
    # (Counted directly: _spent_this_month uses the local month, which at 20:00 UTC on
    # the 31st is already the next month in Asia/Kolkata.)
    assert AIRequestLog.objects.filter(athlete=athlete,
                                       status__in=["ok", "invalid"]).count() == 1


def test_quota_falls_back_without_retry_to_the_tiers_own_fallback(keys, fakes, athlete,
                                                                  no_real_model_list):
    _tier("lite", "gemini", "gemini-pro-latest", fallback=("gemini", "gemini-3.5-flash-lite"))
    gemini = fakes("gemini", [PRO_QUOTA, response(content='{"text": "Fine."}')])
    assert _explain(athlete) == "Fine."
    assert [r["model"] for r in gemini.requests] == ["gemini-pro-latest",
                                                     "gemini-3.5-flash-lite"]
    assert no_real_model_list == []
    fb = AIRequestLog.objects.get(athlete=athlete, status="fallback")
    assert fb.error_kind == "no_quota" and fb.retry_count == 0


def test_both_routes_failing_logs_fallback_then_error(keys, fakes, athlete):
    _tier("lite", "gemini", "gemini-2.5-flash")
    fakes("gemini", [GONE])
    fakes("openai", [HTTPError(401, "Incorrect API key provided")])
    from apps.coaching.client import AIUnavailable

    with pytest.raises(AIUnavailable) as caught:
        ai_client.complete(operation="checkin_explain", system="s", user="u",
                           schema=__import__("apps.coaching.schemas", fromlist=["x"])
                           .CheckinExplanation)
    assert [a["error_kind"] for a in caught.value.attempts] == ["unavailable", "auth"]
    from apps.coaching.services import log_call

    log_call(athlete, "checkin_explain", {}, caught.value)
    rows = list(AIRequestLog.objects.filter(athlete=athlete).order_by("id"))
    assert [(r.status, r.error_kind) for r in rows] == [("fallback", "unavailable"),
                                                        ("error", "auth")]


def test_no_fallback_when_it_equals_the_primary(keys, fakes, athlete, no_real_model_list):
    fakes("openai", [BUSY, BUSY, BUSY])
    from apps.coaching.client import AIUnavailable

    with pytest.raises(AIUnavailable):
        _explain(athlete)
    rows = list(AIRequestLog.objects.filter(athlete=athlete))
    assert [(r.status, r.error_kind) for r in rows] == [("error", "busy")]
    assert len(no_real_model_list) == 2


def test_chat_falls_back_mid_loop_and_strips_thought_signatures(keys, fakes, api, athlete):
    _tier("coach", "gemini", "gemini-3.8-flash")
    call = SimpleNamespace(id="c1", type="function",
                           function=SimpleNamespace(name="get_training_summary",
                                                    arguments='{"weeks": 2}'),
                           extra_content={"google": {"thought_signature": "sig=="}})
    fakes("gemini", [response(tool_calls=[call]), GONE])
    openai = fakes("openai", [response(content="All good.")])
    from apps.coaching.models import ChatThread

    thread = ChatThread.objects.create(athlete=athlete)
    r = api.post(f"/api/chat/threads/{thread.pk}/messages/", {"content": "how am I"},
                 format="json")
    assert r.json()["assistant"]["content"] == "All good."
    sent = openai.requests[0]
    assert "extra_content" not in sent["messages"][-2]["tool_calls"][0]
    assert sent["reasoning_effort"] == "none"
    statuses = list(AIRequestLog.objects.filter(athlete=athlete, operation="chat")
                    .order_by("id").values_list("status", "provider", "error_kind"))
    assert statuses == [("ok", "gemini", ""), ("fallback", "gemini", "unavailable"),
                        ("ok", "openai", "")]


# --- live model list, check, cards, switch -------------------------------------------------

RAW_GEMINI = ["models/gemini-3.5-flash-lite", "models/gemini-3.8-flash",
              "models/gemini-pro-latest", "models/gemini-2.5-flash-preview-tts",
              "models/gemini-2.5-flash-image", "models/text-embedding-004",
              "models/gemini-embedding-001", "models/gemini-live-2.5-flash",
              "models/gemini-robotics-er-1.5-preview", "models/gemini-2.5-computer-use-preview",
              "models/gemini-3-pro-image-preview", "models/nano-banana-pro",
              "models/gemini-omni-preview", "models/gemini-3.1-pro-preview-customtools",
              "models/gemini-transcribe-1", "models/imagen-4.0-generate-001",
              "models/gemma-3-27b-it", "models/veo-3.0-generate-001",
              "models/gemini-2.5-flash-native-audio"]


def test_models_filter():
    assert model_list.filter_ids("gemini", RAW_GEMINI) == [
        "gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-pro-latest", "gemma-3-27b-it"]
    assert model_list.filter_ids("openai", ["gpt-5.6-terra", "gpt-4o-mini-tts", "whisper-1",
                                            "text-embedding-3-small", "dall-e-3",
                                            "gpt-realtime", "omni-moderation-latest",
                                            "gpt-image-1", "o4-mini"]) == ["gpt-5.6-terra",
                                                                           "o4-mini"]


@pytest.fixture
def live(monkeypatch):
    calls = []

    def fetch(provider):
        calls.append(provider)
        return RAW_GEMINI if provider == "gemini" else ["gpt-5.6-terra", "gpt-5.6-luna",
                                                        "tts-1"]

    monkeypatch.setattr(model_list, "_fetch_ids", fetch)
    return calls


def test_providers_use_the_live_list_cached(staff, keys, live):
    by = {p["key"]: p for p in staff.get("/api/admin/ai/providers/").json()}
    assert by["gemini"]["models"] == ["gemini-3.5-flash-lite", "gemini-3.8-flash",
                                      "gemini-pro-latest", "gemma-3-27b-it"]
    assert by["gemini"]["models_source"] == "live" and by["gemini"]["models_fetched_at"]
    info = by["gemini"]["model_info"][0]
    assert info == {"id": "gemini-3.5-flash-lite", "priced": False, "status": "unknown",
                    "checked_at": None, "note": None}
    staff.get("/api/admin/ai/providers/")
    assert live.count("gemini") == 1                         # cached for the hour
    staff.get("/api/admin/ai/providers/?refresh=1")
    assert live.count("gemini") == 2


def test_providers_fall_back_to_the_price_table_offline(staff, keys):
    by = {p["key"]: p for p in staff.get("/api/admin/ai/providers/").json()}
    assert by["gemini"]["models_source"] == "price_table"
    assert "gemini-2.5-flash-lite" in by["gemini"]["models"]


def test_check_models_probes_spaced_capped_and_cached(staff, keys, live, fakes,
                                                      no_real_model_list):
    fake = fakes("gemini", [response(content="OK"), BUSY, PRO_QUOTA, GONE])
    r = staff.post("/api/admin/ai/models/check/", {"provider": "gemini"}, format="json")
    assert r.status_code == 202
    assert sorted(r.json()["queued"]) == ["gemini-3.5-flash-lite", "gemini-3.8-flash",
                                          "gemini-pro-latest", "gemma-3-27b-it"]
    assert len(fake.requests) == 4 and fake.requests[0]["max_tokens"] == 5
    assert no_real_model_list == [1.5, 1.5, 1.5]             # spaced, never retried
    got = dict(ModelStatus.objects.values_list("model", "status"))
    assert sorted(got.values()) == ["busy", "no_quota", "ok", "unavailable"]
    assert AIRequestLog.objects.filter(operation="admin_check", tier="admin").count() == 4
    again = staff.post("/api/admin/ai/models/check/", {"provider": "gemini"}, format="json")
    assert again.json()["queued"] == [] and len(again.json()["skipped"]) == 4
    info = {m["id"]: m for m in staff.get("/api/admin/ai/providers/").json()[1]["model_info"]}
    bad = next(m for m in info.values() if m["status"] == "no_quota")
    assert bad["note"] and bad["checked_at"]
    assert staff.post("/api/admin/ai/models/check/", {"provider": "gemini",
                                                      "models": ["x"] * 13},
                      format="json").status_code == 400


def test_check_is_capped_at_twelve(db, keys):
    ids = [f"gemini-{i}-flash" for i in range(20)]
    queued, skipped = model_list.plan_check("gemini", ids, force=False)
    assert len(queued) == 12 and skipped == []


def test_config_shows_status_warning_and_fallback(staff, keys, live):
    staff.get("/api/admin/ai/prices/")
    ModelStatus.objects.create(provider="gemini", model="gemini-pro-latest",
                               status="no_quota", error_kind="no_quota",
                               checked_at=timezone.now())
    r = staff.put("/api/admin/ai/config/", {"tiers": [
        {"tier": "deep", "provider": "gemini", "model": "gemini-pro-latest",
         "fallback_provider": "gemini", "fallback_model": "gemini-3.5-flash-lite"}]},
        format="json")
    assert r.status_code == 200                                # live list makes it valid
    deep = next(t for t in r.json()["tiers"] if t["tier"] == "deep")
    assert deep["model_status"] == "no_quota" and "billing" in deep["warning"]
    assert deep["fallback"] == {"provider": "gemini", "model": "gemini-3.5-flash-lite",
                                "source": "db"}
    lite = next(t for t in r.json()["tiers"] if t["tier"] == "lite")
    assert lite["fallback"] is None and lite["warning"] is None   # env route: none
    r = staff.put("/api/admin/ai/config/", {"tiers": [
        {"tier": "deep", "provider": "gemini", "model": "gemini-pro-latest",
         "fallback_provider": None, "fallback_model": None}]}, format="json")
    deep = next(t for t in r.json()["tiers"] if t["tier"] == "deep")
    assert deep["fallback"] == {"provider": "openai", "model": "test-model", "source": "env"}
    bad = staff.put("/api/admin/ai/config/", {"tiers": [
        {"tier": "deep", "provider": "gemini", "model": "gemini-pro-latest",
         "fallback_provider": "gemini", "fallback_model": "nope"}]}, format="json")
    assert bad.status_code == 400 and bad.json()["detail"].startswith("Fallback")


def test_model_cards(staff, keys, live, athlete):
    staff.get("/api/admin/ai/prices/")
    ModelPrice.objects.create(provider="gemini", model="gemini-3.5-flash-lite",
                              input_per_m_usd=0.1, output_per_m_usd=0.4)
    ModelStatus.objects.create(provider="gemini", model="gemini-3.5-flash-lite", status="ok",
                               checked_at=timezone.now())
    for status, latency in (("ok", 400), ("ok", 600), ("error", 0)):
        AIRequestLog.objects.create(athlete=athlete, operation="checkin_explain",
                                    provider="gemini", model="gemini-3.5-flash-lite",
                                    prompt_version="v", status=status, input_tokens=1000,
                                    output_tokens=100, latency_ms=latency,
                                    estimated_cost_usd=0.0001)
    body = staff.get("/api/admin/ai/models/?provider=gemini").json()
    assert body["source"] == "live"
    cards = {c["id"]: c for c in body["models"]}
    lite = cards["gemini-3.5-flash-lite"]
    assert lite["known"] and lite["family"] == "flash-lite" and lite["speed"] == "fast"
    assert lite["cost_level"] == "free_tier" and lite["free_tier_ok"] is True
    assert lite["price_in_per_1m"] == 0.1 and lite["calls"] == 3
    assert lite["avg_latency_ms"] == 500 and lite["error_rate"] == pytest.approx(0.333, 0.01)
    # lite tier median tokens (1000 in / 100 out) × price
    assert lite["est_cost_per_call_usd"]["lite"] == pytest.approx(1000 / 1e6 * 0.1 +
                                                                  100 / 1e6 * 0.4)
    assert set(lite["est_cost_per_call_usd"]) == {"lite", "fast", "coach", "deep"}
    pro = cards["gemini-pro-latest"]
    assert pro["quality"] == "best" and pro["free_tier_ok"] is None and pro["summary"]
    gemma = cards["gemma-3-27b-it"]
    assert gemma["known"] is False and gemma["family"] == "gemma"
    for card in cards.values():
        assert set(card) >= {"summary", "best_for", "speed", "quality", "cost_level",
                             "price_in_per_1m", "price_out_per_1m", "est_cost_per_call_usd",
                             "context_window", "free_tier_ok", "calls", "avg_latency_ms",
                             "error_rate", "avg_cost_usd"}
    assert staff.get("/api/admin/ai/models/?provider=x").status_code == 400


def test_catalog_generic_cards_by_family():
    assert model_catalog.card("gemini-9-flash-lite-preview")["family"] == "flash-lite"
    assert model_catalog.card("gemini-9-flash")["quality"] == "good"
    assert model_catalog.card("gemini-9-pro")["cost_level"] == "$$$"
    assert model_catalog.card("gpt-9-nano")["family"] == "nano"
    assert model_catalog.card("gpt-9-mini")["family"] == "mini"
    assert model_catalog.card("gpt-9")["family"] == "full"
    assert model_catalog.card("gpt-5.6-sol")["best_for"] == ["deep"]


def test_switch_all_tiers_to_gemini_skips_bad_models_keeps_fallbacks(staff, keys, live):
    staff.get("/api/admin/ai/prices/")
    _tier("deep", "openai", "test-model", fallback=("openai", "gpt-5.6-terra"))
    ModelStatus.objects.create(provider="gemini", model="gemini-pro-latest",
                               status="no_quota", checked_at=timezone.now())
    ModelStatus.objects.create(provider="gemini", model="gemini-3.8-flash",
                               status="busy", checked_at=timezone.now())
    r = staff.post("/api/admin/ai/config/switch/", {"provider": "gemini"}, format="json")
    assert r.status_code == 200
    tiers = {t["tier"]: t for t in r.json()["tiers"]}
    assert {t: tiers[t]["model"] for t in tiers} == {
        "lite": "gemini-3.5-flash-lite", "fast": "gemini-3.5-flash-lite",
        "coach": "gemini-3.5-flash-lite", "deep": "gemini-3.5-flash-lite"}
    assert AIConfig.objects.get(tier="deep").fallback_model == "gpt-5.6-terra"
    assert {c["tier"] for c in r.json()["changed"]} == {"lite", "fast", "coach", "deep"}
    back = staff.post("/api/admin/ai/config/switch/", {"provider": "openai"}, format="json")
    assert {t["model"] for t in back.json()["tiers"]} == {"test-model"}
    keys.GEMINI_API_KEY = ""
    assert staff.post("/api/admin/ai/config/switch/", {"provider": "gemini"},
                      format="json").status_code == 400


def test_stats_error_kinds_fallbacks_and_hints(staff, athlete):
    AIRequestLog.objects.create(athlete=athlete, operation="chat", provider="gemini",
                                model="gemini-pro-latest", prompt_version="v",
                                status="fallback", error_kind="no_quota", error="429")
    AIRequestLog.objects.create(athlete=athlete, operation="chat", provider="openai",
                                model="m", prompt_version="v", status="ok")
    body = staff.get("/api/admin/ai/stats/?range=7d").json()
    assert body["totals"]["fallbacks"] == 1
    assert body["by_error_kind"] == [{"error_kind": "no_quota", "count": 1}]
    err = body["recent_errors"][0]
    assert err["status"] == "fallback" and err["error_kind"] == "no_quota"
    assert err["hint"] == "Pro models need billing on your Google AI Studio key."


# --- compare -------------------------------------------------------------------------------

def test_compare_is_staff_only(api):
    assert api.post("/api/admin/ai/compare/", {}, format="json").status_code == 403
    assert api.get("/api/admin/ai/compare/").status_code == 403


def test_compare_two_targets_logged_and_rated(staff, keys, fakes):
    fakes("openai", [response(content="Answer A", prompt=50, completion=10)])
    fakes("gemini", [BUSY])
    r = staff.post("/api/admin/ai/compare/", {
        "prompt": "Say hi", "targets": [{"provider": "openai", "model": "gpt-5.6-terra"},
                                        {"provider": "gemini", "model": "gemini-3.8-flash"}]},
        format="json")
    assert r.status_code == 201
    body = r.json()
    a, b = body["results"]
    assert a["ok"] and a["text"] == "Answer A" and a["input_tokens"] == 50
    assert b["ok"] is False and b["error_kind"] == "busy" and b["hint"]
    assert body["created_by"]["username"] == "boss" and body["operation"] is None
    logs = AIRequestLog.objects.filter(operation="admin_compare")
    assert logs.count() == 2 and set(logs.values_list("tier", flat=True)) == {"admin"}
    assert not logs.exclude(athlete=None).exists()
    rated = staff.patch(f"/api/admin/ai/compare/{body['id']}/",
                        {"ratings": [{"index": 0, "rating": 5}]}, format="json")
    assert rated.json()["results"][0]["rating"] == 5
    assert staff.patch(f"/api/admin/ai/compare/{body['id']}/",
                       {"ratings": [{"index": 0, "rating": 6}]},
                       format="json").status_code == 400
    listed = staff.get("/api/admin/ai/compare/").json()
    assert [x["id"] for x in listed] == [body["id"]]


def test_compare_validation(staff, keys):
    one = [{"provider": "openai", "model": "a"}]
    assert staff.post("/api/admin/ai/compare/", {"prompt": "x", "targets": one},
                      format="json").status_code == 400
    same = one * 2
    assert staff.post("/api/admin/ai/compare/", {"prompt": "x", "targets": same},
                      format="json").status_code == 400
    two = one + [{"provider": "gemini", "model": "b"}]
    assert staff.post("/api/admin/ai/compare/", {"targets": two},
                      format="json").status_code == 400
    assert staff.post("/api/admin/ai/compare/", {"targets": two, "operation": "nope"},
                      format="json").status_code == 400
    assert staff.post("/api/admin/ai/compare/", {"targets": two, "operation": "run_review",
                                                 "athlete_id": 999999},
                      format="json").status_code == 404


def test_compare_replays_run_review_with_aggregates_only(staff, keys, fakes, athlete):
    from apps.activities.reviews import build_review
    from apps.habits.models import HabitLog

    athlete.private_habit_enabled = True
    athlete.save()
    HabitLog.objects.create(athlete=athlete, kind="private", at=timezone.now(),
                            local_date=athlete.local_today, quantity=3)
    for offset in (-10, -5):
        run(athlete, athlete.local_today + dt.timedelta(days=offset), pace=420)
    build_review(run(athlete, athlete.local_today, pace=400))
    o = fakes("openai", [response(content="A")])
    g = fakes("gemini", [response(content="B")])
    r = staff.post("/api/admin/ai/compare/", {
        "operation": "run_review", "athlete_id": athlete.pk,
        "targets": [{"provider": "openai", "model": "m1"}, {"provider": "gemini", "model": "m2"}]},
        format="json")
    assert r.status_code == 201 and r.json()["context_note"]
    sent = str(o.requests[0]["messages"]) + str(g.requests[0]["messages"])
    assert "compared_with" in sent
    assert "Tester" not in sent and "private" not in sent.lower()
    assert CompareRun.objects.get().operation == "run_review"


# --- run summary ---------------------------------------------------------------------------

def test_compose_lengths_and_wording():
    body = run_summary.compose(km=5.2, moving_s=2590, pace_s=418, usual_pace_s=421, hr=141,
                               zone_top=150, next_title=None, has_plan=True)
    assert body["title"] == "Run 5.2 km · 43:10"
    assert body["body"] == "Pace 6:58 (3 s faster than usual) · HR 141 on target\n" \
                           "Next: rest day"
    long = run_summary.compose(km=42.2, moving_s=4 * 3600 + 59 * 60 + 59, pace_s=425,
                               usual_pace_s=300, hr=171, zone_top=150,
                               next_title="Recovery jog with strides and a very long title "
                                          "that goes on and on",
                               has_plan=True)
    assert len(long["title"]) <= run_summary.TITLE_MAX
    lines = long["body"].split("\n")
    assert len(lines) == 2 and all(len(line) <= run_summary.LINE_MAX for line in lines)
    assert "slower" in lines[0] and "above target" in lines[0] and lines[1].endswith("…")
    bare = run_summary.compose(km=3.0, moving_s=1200, pace_s=None, usual_pace_s=None, hr=None,
                               zone_top=None, next_title=None, has_plan=False)
    assert bare == {"title": "Run 3.0 km · 20:00", "body": ""}


@pytest.fixture
def pushes(monkeypatch):
    sent = []
    monkeypatch.setattr("apps.reminders.push.available", lambda: True)
    monkeypatch.setattr("apps.reminders.push.send_to_athlete",
                        lambda a, body: (sent.append(body) or 1, 0))
    return sent


def _fresh_run(athlete):
    activity = run(athlete, athlete.local_today)
    activity.started_at = timezone.now() - dt.timedelta(hours=1)
    activity.save(update_fields=["started_at"])
    return activity


def _not_quiet(athlete):
    from apps.reminders.service import settings_for

    row = settings_for(athlete)
    row.quiet_start = row.quiet_end = dt.time(0, 0)          # start == end: never quiet
    row.save()
    return row


def test_run_summary_sent_once_per_activity(athlete, pushes):
    from apps.activities.reviews import build_review

    _not_quiet(athlete)
    activity = _fresh_run(athlete)
    build_review(activity, push=True)
    build_review(activity, push=True)                        # rebuilt: no second push
    assert len(pushes) == 1
    msg = pushes[0]
    assert msg["kind"] == "run_summary" and msg["tag"] == f"run_summary-{activity.pk}"
    assert len(msg["title"]) <= 30 and msg["title"].startswith("Run 4.0 km")
    assert all(len(line) <= 60 for line in msg["body"].split("\n"))
    assert len(msg["body"].split("\n")) <= 2
    assert RunReview.objects.get(activity=activity).pushed_at is not None
    assert run_summary.on_review_built(RunReview.objects.get(activity=activity)) == "skipped"


def test_run_summary_off_or_old_run_is_not_sent(athlete, pushes):
    from apps.activities.reviews import build_review

    row = _not_quiet(athlete)
    build_review(run(athlete, athlete.local_today - dt.timedelta(days=3)), push=True)
    assert pushes == []                                       # a backfilled old run
    row.run_summary = False
    row.save()
    build_review(_fresh_run(athlete), push=True)
    assert pushes == []


def test_run_summary_waits_for_quiet_hours_to_end(athlete, pushes, monkeypatch):
    from apps.activities.reviews import build_review
    from apps.reminders.service import settings_for

    row = settings_for(athlete)
    local_now = athlete.local_now
    row.quiet_start = (local_now - dt.timedelta(hours=1)).time().replace(second=0,
                                                                         microsecond=0)
    row.quiet_end = (local_now + dt.timedelta(hours=1)).time().replace(second=0, microsecond=0)
    row.save()
    activity = _fresh_run(athlete)
    build_review(activity, push=True)
    review = RunReview.objects.get(activity=activity)
    assert pushes == [] and review.summary_due_at is not None
    assert review.summary_due_at > timezone.now()
    assert run_summary.send_queued() == 0                     # not yet
    # Quiet hours end: the beat sends it, once.
    RunReview.objects.filter(pk=review.pk).update(
        summary_due_at=timezone.now() - dt.timedelta(minutes=1))
    _not_quiet(athlete)
    assert run_summary.send_queued() == 1 and len(pushes) == 1
    assert run_summary.send_queued() == 0
    review.refresh_from_db()
    assert review.summary_due_at is None and review.pushed_at is not None


def test_quiet_until_wraps_midnight():
    row = SimpleNamespace(quiet_start=dt.time(22, 0), quiet_end=dt.time(7, 0))
    tz = dt.timezone(dt.timedelta(hours=5, minutes=30))
    late = dt.datetime(2026, 10, 11, 23, 50, tzinfo=tz)
    assert run_summary.quiet_until(row, late) == dt.datetime(2026, 10, 12, 7, 0, tzinfo=tz)
    early = dt.datetime(2026, 10, 12, 3, 0, tzinfo=tz)
    assert run_summary.quiet_until(row, early) == dt.datetime(2026, 10, 12, 7, 0, tzinfo=tz)
    assert run_summary.quiet_until(row, dt.datetime(2026, 10, 12, 12, 0, tzinfo=tz)) is None


def test_reminder_defaults_on_and_alias(api):
    body = api.get("/api/reminders/").json()
    by = {r["key"]: r for r in body["reminders"]}
    assert by["run_summary"]["enabled"] is True and by["run_summary"]["time"] is None
    r = api.patch("/api/reminders/", {"run_reviewed": {"enabled": False}}, format="json")
    assert {x["key"]: x for x in r.json()["reminders"]}["run_summary"]["enabled"] is False


# --- share data ----------------------------------------------------------------------------

def test_km_splits_and_best_km():
    samples = [(t, t * 3.0, 140 + (t // 400)) for t in range(0, 1101)]   # 3 m/s, 3.3 km
    splits = share_maths.km_splits(samples)
    assert [s["km"] for s in splits] == [1, 2, 3, 4]
    assert [s["pace_s"] for s in splits[:3]] == [333, 333, 334] or \
        all(abs(s["pace_s"] - 333) <= 1 for s in splits[:3])
    assert splits[-1]["partial"] and splits[-1]["distance_m"] == pytest.approx(300, abs=1)
    assert abs(splits[-1]["pace_s"] - 333) <= 2
    assert share_maths.best_km(splits)["km"] in (1, 2, 3)
    assert share_maths.km_splits([(0, 0, None), (30, 50, None)]) == []
    assert share_maths.title_for(7) == "Morning run" and share_maths.title_for(23) == "Night run"


@pytest.fixture
def local_cache(monkeypatch):
    from django.core import cache as cache_module
    from django.core.cache.backends.locmem import LocMemCache

    cache = LocMemCache("share-tests", {})
    cache.clear()
    monkeypatch.setattr(cache_module, "cache", cache)


def _gps_run(athlete):
    activity = run(athlete, athlete.local_today, km=2.0)
    activity.total_ascent_m = 12.0
    activity.calories = 210
    activity.save()
    rows = []
    for t in range(0, 801):
        d = t * 2.5
        rows.append(ActivityRecord(activity=activity, offset_s=t, distance_m=d,
                                   heart_rate=140, latitude=12.9 + d / 111_000,
                                   longitude=77.6, altitude_m=900.0))
    ActivityRecord.objects.bulk_create(rows)
    return activity


def test_share_data_shape_trimming_and_isolation(api, other_api, athlete, local_cache):
    activity = _gps_run(athlete)
    body = api.get(f"/api/activities/{activity.pk}/share-data/").json()
    assert set(body) == {"activity_id", "sport", "title", "workout_title", "date",
                         "started_at", "start_local", "distance_m", "distance_km", "moving_s",
                         "elapsed_s", "avg_pace_s_per_km", "run_pace_s_per_km", "avg_hr",
                         "max_hr", "cadence_spm", "elevation_gain_m", "calories", "splits",
                         "best_km", "weather", "route"}
    assert body["distance_km"] == 2.0 and body["moving_s"] == 1800
    assert body["avg_pace_s_per_km"] == 900 and body["calories"] == 210
    assert body["elevation_gain_m"] == 12.0 and body["weather"] is None
    assert [s["km"] for s in body["splits"]] == [1, 2] and body["best_km"]["km"] in (1, 2)
    route = body["route"]
    assert route["available"] and route["hidden_endpoints"] and route["trimmed_m"] == 200
    first_lat = route["points"][0][0]
    assert first_lat >= 12.9 + 199 / 111_000                  # start trimmed
    assert route["points"][-1][0] <= 12.9 + 1801 / 111_000    # finish trimmed
    athlete.map_hide_endpoints = False
    athlete.save()
    open_route = api.get(f"/api/activities/{activity.pk}/share-data/").json()["route"]
    assert open_route["hidden_endpoints"] is False
    assert open_route["points"][0][0] == pytest.approx(12.9, abs=1e-5)
    assert other_api.get(f"/api/activities/{activity.pk}/share-data/").status_code == 404


def test_share_data_weather_when_known(api, athlete, local_cache):
    from apps.health.models import ActivityWeather

    activity = run(athlete, athlete.local_today)
    ActivityWeather.objects.create(activity=activity, temp_c=24.0, feels_like_c=26.0,
                                   humidity=70.0, dew_point_c=18.0)
    body = api.get(f"/api/activities/{activity.pk}/share-data/").json()
    assert body["weather"] == {"temp_c": 24.0, "feels_like_c": 26.0, "humidity": 70.0,
                               "dew_point_c": 18.0}
    assert body["route"]["available"] is False and body["splits"] == []
