"""R14 §14: the staff-only admin API and the Gemini provider. No real AI calls: every
client is a fake; no real Kubernetes API: httpx is patched."""

import datetime as dt
import json
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.athletes.models import Athlete, InviteCode
from apps.coaching import client as ai_client
from apps.coaching.models import AIConfig, AIRequestLog, ModelPrice

ADMIN_GETS = ["/api/admin/users/", "/api/admin/invites/", "/api/admin/ai/providers/",
              "/api/admin/ai/config/", "/api/admin/ai/prices/", "/api/admin/ai/stats/",
              "/api/admin/system/"]
GEMINI_KEY = "gm-secret-key-123456"
OPENAI_KEY = "sk-secret-openai-999"


@pytest.fixture
def staff(db):
    user = User.objects.create_user("boss", password="correct-horse-battery-9", is_staff=True)
    Athlete.objects.create(user=user, display_name="Boss", timezone="Asia/Kolkata")
    client = APIClient()
    client.force_authenticate(user)
    client.user = user
    return client


@pytest.fixture
def keys(settings):
    settings.GEMINI_API_KEY = GEMINI_KEY
    settings.OPENAI_API_KEY = OPENAI_KEY
    settings.AI_PROVIDER = "openai"
    settings.AI_MAX_RETRIES = 0
    ai_client._CLIENTS.clear()
    yield settings
    ai_client._CLIENTS.clear()


def response(content=None, tool_calls=None, prompt=120, completion=30):
    message = SimpleNamespace(content=content, tool_calls=tool_calls, refusal=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message,
                                 finish_reason="tool_calls" if tool_calls else "stop")],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion))


class Fake:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs, default=str)))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def fakes(monkeypatch):
    """Per-provider fakes: {"openai": Fake, "gemini": Fake}; records which was used."""
    installed = {}

    def install(provider, responses):
        installed[provider] = Fake(responses)
        return installed[provider]

    def get_client(provider="openai"):
        if provider not in installed:
            raise AssertionError(f"unexpected provider {provider}")
        return installed[provider]

    monkeypatch.setattr(ai_client, "get_client", get_client)
    return install


# --- access -------------------------------------------------------------------------------

@pytest.mark.parametrize("url", ADMIN_GETS)
def test_non_staff_get_403_and_anonymous_401(api, url):
    assert api.get(url).status_code == 403
    assert APIClient().get(url).status_code == 401


@pytest.mark.parametrize("method,url", [
    ("patch", "/api/admin/users/1/"), ("post", "/api/admin/invites/"),
    ("post", "/api/admin/invites/1/revoke/"), ("put", "/api/admin/ai/config/"),
    ("post", "/api/admin/ai/test/"), ("post", "/api/admin/ai/prices/"),
    ("patch", "/api/admin/ai/prices/1/"), ("delete", "/api/admin/ai/prices/1/"),
])
def test_non_staff_cannot_write(api, method, url):
    assert getattr(api, method)(url, {}, format="json").status_code == 403


def test_staff_sees_every_user_non_staff_does_not(staff, api, athlete, other_athlete):
    AIRequestLog.objects.create(athlete=other_athlete, operation="chat", provider="openai",
                                model="m", prompt_version="v", status="ok",
                                estimated_cost_usd=0.25, input_tokens=10, output_tokens=5)
    body = staff.get("/api/admin/users/").json()
    names = {u["username"] for u in body["users"]}
    assert {"tester", "intruder", "boss"} <= names
    intruder = next(u for u in body["users"] if u["username"] == "intruder")
    assert intruder["ai"] == {"calls_month": 1, "cost_month_usd": 0.25,
                              "budget": body["default_budget"], "budget_source": "default"}
    assert set(intruder) >= {"id", "display_name", "email", "joined", "last_active",
                             "is_active", "is_staff", "garmin_connected", "garmin_last_sync",
                             "plan", "ai"}
    assert api.get("/api/admin/users/").status_code == 403


def test_disable_user_signs_out_and_cannot_disable_self(staff, athlete):
    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
    from rest_framework_simplejwt.tokens import RefreshToken

    RefreshToken.for_user(athlete.user)
    r = staff.patch(f"/api/admin/users/{athlete.user.pk}/", {"is_active": False}, format="json")
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert BlacklistedToken.objects.filter(token__user=athlete.user).count() == 1
    r = staff.patch(f"/api/admin/users/{staff.user.pk}/", {"is_active": False}, format="json")
    assert r.status_code == 400


def test_custom_budget_is_enforced(staff, athlete, api, monkeypatch, fakes):
    r = staff.patch(f"/api/admin/users/{athlete.user.pk}/", {"ai_budget": 0}, format="json")
    assert r.status_code == 200
    assert r.json()["ai"] == {"calls_month": 0, "cost_month_usd": 0.0, "budget": 0,
                              "budget_source": "custom"}
    fakes("openai", [])
    from apps.coaching.models import ChatThread

    thread = ChatThread.objects.create(athlete=athlete)
    r = api.post(f"/api/chat/threads/{thread.pk}/messages/", {"content": "hi"}, format="json")
    assert r.json()["assistant"]["status"] == "error"
    refused = AIRequestLog.objects.get(athlete=athlete, status="refused")
    assert "0 calls" in refused.error
    assert staff.patch(f"/api/admin/users/{athlete.user.pk}/", {"ai_budget": -1},
                       format="json").status_code == 400


def test_invites_create_and_revoke(staff, settings):
    from apps.athletes.invites import consume_invite

    r = staff.post("/api/admin/invites/", {"note": "for Asha", "max_uses": 2,
                                           "expires_in_days": 7}, format="json")
    assert r.status_code == 201
    invite = r.json()
    assert invite["usable"] and not invite["revoked"] and invite["max_uses"] == 2
    assert len(staff.get("/api/admin/invites/").json()) == 1
    r = staff.post(f"/api/admin/invites/{invite['id']}/revoke/")
    assert r.json()["revoked"] is True and r.json()["usable"] is False
    assert consume_invite(invite["code"]) is False
    assert InviteCode.objects.get(pk=invite["id"]).uses == 0
    assert staff.post("/api/admin/invites/", {"max_uses": 0}, format="json").status_code == 400


# --- providers / config / prices ----------------------------------------------------------

def test_providers_show_configured_flags_never_keys(staff, keys):
    r = staff.get("/api/admin/ai/providers/")
    text = r.content.decode()
    assert GEMINI_KEY not in text and OPENAI_KEY not in text
    by = {p["key"]: p for p in r.json()}
    assert by["gemini"]["configured"] is True
    assert by["gemini"]["base_url"] == ai_client.GEMINI_BASE_URL
    assert by["gemini"]["features"]["tools"] is True
    assert any(m.startswith("gemini") for m in by["gemini"]["models"])
    keys.GEMINI_API_KEY = ""
    by = {p["key"]: p for p in staff.get("/api/admin/ai/providers/").json()}
    assert by["gemini"]["configured"] is False


def test_config_routes_a_tier_to_gemini_and_back(staff, keys):
    staff.get("/api/admin/ai/prices/")          # seeds the table
    model = ModelPrice.objects.filter(provider="gemini").first().model
    r = staff.put("/api/admin/ai/config/", {"tiers": [
        {"tier": "lite", "provider": "gemini", "model": model}]}, format="json")
    assert r.status_code == 200
    lite = next(t for t in r.json()["tiers"] if t["tier"] == "lite")
    assert lite == {**lite, "provider": "gemini", "model": model, "source": "db",
                    "env_provider": "openai", "env_model": "test-model", "available": True}
    assert ai_client.route_for("checkin_explain") == ("gemini", model)
    assert ai_client.route_for("chat") == ("openai", "test-model")      # coach: env
    r = staff.put("/api/admin/ai/config/", {"tiers": [{"tier": "lite", "reset": True}]},
                  format="json")
    assert next(t for t in r.json()["tiers"] if t["tier"] == "lite")["source"] == "env"
    assert ai_client.route_for("checkin_explain") == ("openai", "test-model")


def test_config_refuses_unconfigured_provider_and_unknown_model(staff, keys):
    staff.get("/api/admin/ai/prices/")
    r = staff.put("/api/admin/ai/config/", {"tiers": [
        {"tier": "fast", "provider": "gemini", "model": "not-a-model"}]}, format="json")
    assert r.status_code == 400
    keys.GEMINI_API_KEY = ""
    model = ModelPrice.objects.filter(provider="gemini").first().model
    r = staff.put("/api/admin/ai/config/", {"tiers": [
        {"tier": "fast", "provider": "gemini", "model": model}]}, format="json")
    assert r.status_code == 400 and "key" in r.json()["detail"]
    assert not AIConfig.objects.exists()


def test_price_table_crud_and_cost_uses_it(staff):
    r = staff.post("/api/admin/ai/prices/", {"provider": "openai", "model": "my-model",
                                             "input_per_m_usd": 1.0, "output_per_m_usd": 4.0},
                   format="json")
    assert r.status_code == 201
    row = r.json()
    assert ai_client.estimate_cost("my-model", 1_000_000, 500_000, "openai") == 3.0
    r = staff.patch(f"/api/admin/ai/prices/{row['id']}/", {"output_per_m_usd": 8.0},
                    format="json")
    assert r.json()["output_per_m_usd"] == 8.0
    assert ai_client.estimate_cost("my-model", 1_000_000, 500_000) == 5.0
    AIConfig.objects.create(tier="deep", provider="openai", model="my-model")
    assert staff.delete(f"/api/admin/ai/prices/{row['id']}/").status_code == 409
    AIConfig.objects.all().delete()
    assert staff.delete(f"/api/admin/ai/prices/{row['id']}/").status_code == 204
    assert staff.post("/api/admin/ai/prices/", {"provider": "x", "model": "m",
                                                "input_per_m_usd": 1, "output_per_m_usd": 1},
                      format="json").status_code == 400


# --- Gemini through the client abstraction -----------------------------------------------

def test_real_gemini_client_uses_the_openai_compatible_base_url(keys):
    client = ai_client.get_client("gemini")
    assert str(client.base_url).rstrip("/") == ai_client.GEMINI_BASE_URL.rstrip("/")
    assert client.api_key == GEMINI_KEY
    assert ai_client.get_client("gemini") is client                 # cached
    keys.GEMINI_API_KEY = ""
    with pytest.raises(ai_client.AIUnavailable):
        ai_client.get_client("gemini")


def _gemini_tier(tier="lite", model="gemini-test"):
    ModelPrice.objects.create(provider="gemini", model=model, input_per_m_usd=1.0,
                              output_per_m_usd=2.0)
    AIConfig.objects.create(tier=tier, provider="gemini", model=model)


def test_structured_json_output_via_gemini_is_logged(keys, fakes, athlete):
    from apps.coaching.services import checkin_explanation

    _gemini_tier("lite")
    fake = fakes("gemini", [response(content='{"text": "Easy today: you slept 5 h."}')])
    payload = {"date": "2026-10-07", "verdict": "easy", "headline": "Take it easy",
               "signals": [], "signals_missing": [], "planned": "Easy run", "changed_to": None}
    assert checkin_explanation(athlete, payload) == "Easy today: you slept 5 h."
    sent = fake.requests[0]
    assert sent["model"] == "gemini-test"
    assert sent["response_format"]["type"] == "json_schema"
    assert "reasoning_effort" not in sent
    log = AIRequestLog.objects.get(athlete=athlete)
    assert (log.provider, log.model, log.tier, log.status) == ("gemini", "gemini-test", "lite",
                                                              "ok")
    assert (log.input_tokens, log.output_tokens) == (120, 30)
    assert log.estimated_cost_usd == pytest.approx(120 / 1e6 * 1.0 + 30 / 1e6 * 2.0)
    assert log.latency_ms >= 0


def test_schema_rejection_falls_back_to_json_mode(keys, fakes, athlete):
    from apps.coaching.schemas import CheckinExplanation

    class Rejected(Exception):
        status_code = 400

    _gemini_tier("lite")
    fake = fakes("gemini", [Rejected("Invalid JSON payload: response_format.json_schema ..."),
                            response(content='```json\n{"text": "ok"}\n```')])
    result, stats = ai_client.complete(operation="checkin_explain", system="s", user="u",
                                       schema=CheckinExplanation)
    assert result.text == "ok" and stats["provider"] == "gemini"
    assert fake.requests[1]["response_format"] == {"type": "json_object"}
    assert "JSON schema" in fake.requests[1]["messages"][0]["content"]


def test_tool_calling_via_gemini_with_missing_ids_and_thought_signatures(keys, fakes, api,
                                                                         athlete):
    _gemini_tier("coach", "gemini-coach")
    call = SimpleNamespace(id="", type="function",
                           function=SimpleNamespace(name="get_training_summary",
                                                    arguments='{"weeks": 2}'),
                           extra_content={"google": {"thought_signature": "sig=="}})
    fake = fakes("gemini", [response(tool_calls=[call]),
                            response(content="Two quiet weeks — keep it easy.")])
    from apps.coaching.models import ChatThread

    thread = ChatThread.objects.create(athlete=athlete)
    r = api.post(f"/api/chat/threads/{thread.pk}/messages/", {"content": "how am I doing"},
                 format="json")
    assert r.json()["assistant"]["content"] == "Two quiet weeks — keep it easy."
    second = fake.requests[1]
    echoed = second["messages"][-2]["tool_calls"][0]
    assert echoed["id"] == "call_0_0"
    assert echoed["extra_content"] == {"google": {"thought_signature": "sig=="}}
    assert second["messages"][-1] == {**second["messages"][-1], "role": "tool",
                                      "tool_call_id": "call_0_0"}
    assert "reasoning_effort" not in second
    logs = AIRequestLog.objects.filter(athlete=athlete, operation="chat")
    assert logs.count() == 2 and set(logs.values_list("provider", flat=True)) == {"gemini"}


def test_openai_chat_still_sends_reasoning_off(keys, fakes, api, athlete):
    fake = fakes("openai", [response(content="hello")])
    from apps.coaching.models import ChatThread

    thread = ChatThread.objects.create(athlete=athlete)
    api.post(f"/api/chat/threads/{thread.pk}/messages/", {"content": "hi"}, format="json")
    assert fake.requests[0]["reasoning_effort"] == "none"
    assert AIRequestLog.objects.get(athlete=athlete, operation="chat").provider == "openai"


def test_private_habit_never_reaches_gemini_chat_context(keys, fakes, api, athlete):
    from apps.habits.models import HabitLog
    from django.utils import timezone

    athlete.private_habit_enabled = True
    athlete.save()
    HabitLog.objects.create(athlete=athlete, kind="private", at=timezone.now(),
                            local_date=athlete.local_today, quantity=3)
    _gemini_tier("coach", "gemini-coach")
    fake = fakes("gemini", [response(content="ok")])
    from apps.coaching.models import ChatThread

    thread = ChatThread.objects.create(athlete=athlete)
    api.post(f"/api/chat/threads/{thread.pk}/messages/", {"content": "habits?"}, format="json")
    assert "private" not in json.dumps(fake.requests[0]["messages"]).lower()


# --- test prompt + stats ------------------------------------------------------------------

def test_admin_test_prompt(staff, keys, fakes):
    _gemini_tier("lite")
    fakes("gemini", [response(content='{"answer": 4}')])
    r = staff.post("/api/admin/ai/test/", {"provider": "gemini", "model": "gemini-test",
                                           "prompt": "2+2 as JSON", "json": True},
                   format="json")
    body = r.json()
    assert body["ok"] is True and body["json"] == {"answer": 4}
    assert body["input_tokens"] == 120 and body["cost_usd"] > 0
    log = AIRequestLog.objects.get(operation="admin_test")
    assert log.athlete is None and log.provider == "gemini" and log.tier == "admin"
    assert GEMINI_KEY not in r.content.decode()


def test_admin_test_prompt_error_scrubs_key(staff, keys, fakes):
    fakes("openai", [RuntimeError(f"bad key {OPENAI_KEY}")])
    r = staff.post("/api/admin/ai/test/", {"provider": "openai", "model": "x",
                                           "prompt": "hi"}, format="json")
    assert r.json()["ok"] is False and OPENAI_KEY not in r.content.decode()
    assert AIRequestLog.objects.get(operation="admin_test").status == "error"
    assert staff.post("/api/admin/ai/test/", {"provider": "openai", "model": "x",
                                              "prompt": ""}, format="json").status_code == 400


def test_stats_groupings(staff, athlete, other_athlete):
    def log(who, op, status="ok", cost=0.1, provider="openai", model="m"):
        AIRequestLog.objects.create(athlete=who, operation=op, provider=provider, model=model,
                                    prompt_version="v", status=status, input_tokens=100,
                                    output_tokens=10, estimated_cost_usd=cost, latency_ms=200)

    log(athlete, "chat")
    log(athlete, "chat", status="error", cost=0)
    log(other_athlete, "checkin_explain", provider="gemini", model="g", cost=0.02)
    log(athlete, "chat", status="refused", cost=0)
    body = staff.get("/api/admin/ai/stats/?range=7d").json()
    t = body["totals"]
    assert (t["calls"], t["errors"], t["refused"]) == (2, 1, 1)
    assert t["error_rate"] == pytest.approx(1 / 3, abs=0.001)
    assert t["cost_usd"] == pytest.approx(0.12)
    assert len(body["by_day"]) == 7
    assert {r["tier"] for r in body["by_tier"]} == {"coach", "lite"}
    assert {(r["provider"], r["model"]) for r in body["by_model"]} == {("openai", "m"),
                                                                       ("gemini", "g")}
    users = {r["name"]: r for r in body["by_user"]}
    assert users["Tester"]["calls"] == 1 and users["Tester"]["errors"] == 1
    assert body["recent_errors"][0]["operation"] == "chat"
    assert staff.get("/api/admin/ai/stats/?range=2d").status_code == 400


# --- system ---------------------------------------------------------------------------------

def test_system_outside_a_cluster_degrades(staff, monkeypatch, settings):
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.delenv("APP_VERSION", raising=False)
    settings.GCP_TRIAL_END = "2027-01-03"
    settings.GCP_CREDIT_INR = "25000"
    body = staff.get("/api/admin/system/").json()
    assert body["kubernetes"] == {"available": False, "reason": "not_in_cluster",
                                  "nodes": [], "pods": []}
    assert body["backups"]["available"] is False
    assert body["gcp"]["trial_end"] == "2027-01-03" and body["gcp"]["credit_inr"] == 25000.0
    assert isinstance(body["gcp"]["days_left"], int)
    assert set(body["garmin"]) == {"breaker_open", "reason", "retry_after_s", "users"}
    assert set(body["celery"]) == {"available", "queues"}


def test_gcp_days_left_is_date_arithmetic(settings):
    from apps.adminpanel.system import gcp

    settings.GCP_TRIAL_END = "2027-01-03"
    settings.GCP_CREDIT_INR = ""
    assert gcp(dt.date(2026, 10, 7))["days_left"] == 88
    assert gcp(dt.date(2027, 2, 1))["days_left"] == 0
    assert gcp(dt.date(2026, 10, 7))["credit_inr"] is None


class FakeHttp:
    def __init__(self, routes, status=200):
        self.routes, self.status, self.calls = routes, status, []

    def __call__(self, url, headers=None, verify=None, timeout=None):
        self.calls.append((url, headers, verify))
        path = url.split(":443", 1)[1]
        body = self.routes.get(path)
        code = self.status if body is not None else 404
        return SimpleNamespace(status_code=code, json=lambda: body or {})


@pytest.fixture
def cluster(tmp_path, monkeypatch):
    (tmp_path / "token").write_text("sa-token")
    (tmp_path / "ca.crt").write_text("ca")
    (tmp_path / "namespace").write_text("runcoach")
    monkeypatch.setenv("K8S_SA_DIR", str(tmp_path))
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.43.0.1")
    monkeypatch.setenv("KUBERNETES_SERVICE_PORT", "443")
    monkeypatch.setenv("HOSTNAME", "backend-abc")
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.delenv("APP_VERSION", raising=False)
    return tmp_path


def test_system_reads_kubernetes_with_the_service_account(staff, cluster, monkeypatch):
    from apps.adminpanel import k8s

    routes = {
        "/api/v1/nodes": {"items": [{"metadata": {"name": "vps"}, "status": {
            "capacity": {"cpu": "4", "memory": "8Gi", "ephemeral-storage": "100Gi"},
            "allocatable": {"ephemeral-storage": "90Gi"},
            "conditions": [{"type": "Ready", "status": "True"}]}}]},
        "/apis/metrics.k8s.io/v1beta1/nodes": {"items": [
            {"metadata": {"name": "vps"}, "usage": {"cpu": "1500m", "memory": "2Gi"}}]},
        "/api/v1/namespaces/runcoach/pods": {"items": [{
            "metadata": {"name": "backend-abc", "labels": {"app.kubernetes.io/name": "backend"}},
            "spec": {"nodeName": "vps"},
            "status": {"phase": "Running", "startTime": "2026-10-07T01:00:00Z",
                       "containerStatuses": [{"ready": True, "restartCount": 2}]}}]},
        "/api/v1/namespaces/runcoach/pods/backend-abc": {"spec": {"containers": [
            {"name": "backend", "image": "ghcr.io/x/runcoach-backend:abc1234"}]}},
        "/apis/batch/v1/namespaces/runcoach/cronjobs/postgres-backup": {
            "spec": {"schedule": "0 3 * * *"},
            "status": {"lastSuccessfulTime": "2026-10-06T21:30:05Z",
                       "lastScheduleTime": "2026-10-06T21:30:00Z"}},
        "/apis/batch/v1/namespaces/runcoach/jobs": {"items": [{
            "metadata": {"name": "postgres-backup-1", "ownerReferences": [
                {"kind": "CronJob", "name": "postgres-backup"}]},
            "status": {"succeeded": 1, "startTime": "2026-10-06T21:30:00Z",
                       "completionTime": "2026-10-06T21:30:05Z"}}]},
    }
    fake = FakeHttp(routes)
    monkeypatch.setattr(k8s.httpx, "get", fake)
    body = staff.get("/api/admin/system/").json()
    node = body["kubernetes"]["nodes"][0]
    assert node["cpu_cores"] == 4 and node["cpu_pct"] == 38 and node["memory_pct"] == 25
    assert node["disk_bytes"] == 100 * 2**30
    pod = body["kubernetes"]["pods"][0]
    assert pod == {"name": "backend-abc", "app": "backend", "phase": "Running", "ready": True,
                   "restarts": 2, "started_at": "2026-10-07T01:00:00Z", "node": "vps"}
    assert body["version"] == {"git_sha": "abc1234",
                               "image": "ghcr.io/x/runcoach-backend:abc1234",
                               "source": "kubernetes"}
    assert body["backups"]["last_success_at"] == "2026-10-06T21:30:05Z"
    assert body["backups"]["jobs"][0]["status"] == "succeeded"
    url, headers, verify = fake.calls[0]
    assert headers["Authorization"] == "Bearer sa-token" and verify.endswith("ca.crt")
    # Only GETs, only the resources the RBAC grants.
    assert all(u.startswith("https://10.43.0.1:443/") for u, _, _ in fake.calls)


def test_system_forbidden_degrades(staff, cluster, monkeypatch):
    from apps.adminpanel import k8s

    monkeypatch.setattr(k8s.httpx, "get", FakeHttp({"/api/v1/nodes": {}}, status=403))
    body = staff.get("/api/admin/system/").json()
    assert body["kubernetes"]["available"] is False
    assert body["kubernetes"]["reason"] == "forbidden"


def test_quantity_parser():
    from apps.adminpanel.k8s import quantity

    assert quantity("250m") == 0.25
    assert quantity("2Gi") == 2 * 2**30
    assert quantity("1000Ki") == 1024000
    assert quantity("123456n") == pytest.approx(0.000123456)
    assert quantity("3") == 3.0 and quantity(None) is None and quantity("x") is None


def test_session_user_carries_is_staff(api, staff, client, db):
    assert api.get("/api/auth/me/").json()["user"]["is_staff"] is False
    assert staff.get("/api/auth/me/").json()["user"]["is_staff"] is True
    r = client.post("/api/auth/login/", {"username": "boss",
                                         "password": "correct-horse-battery-9"},
                    content_type="application/json")
    assert r.status_code == 200 and r.json()["user"]["is_staff"] is True
