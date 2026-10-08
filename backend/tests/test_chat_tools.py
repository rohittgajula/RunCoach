"""The chat tool loop with the OpenAI client mocked. No real AI calls."""

import datetime as dt
import json
from types import SimpleNamespace

import pytest

from apps.coaching import client as ai_client
from apps.coaching.models import AIRequestLog, ChatMessage, ChatThread
from apps.planning.models import TrainingPlan


def tool_call(name, args, call_id="call_1"):
    return SimpleNamespace(id=call_id, type="function",
                           function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def response(content=None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls, refusal=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message,
                                 finish_reason="tool_calls" if tool_calls else "stop")],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
    )


class FakeOpenAI:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(kwargs)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def fake_ai(settings, monkeypatch):
    settings.AI_MODELS = {"lite": "m", "fast": "m", "coach": "m", "deep": "m"}
    settings.AI_MAX_RETRIES = 0

    def install(responses):
        fake = FakeOpenAI(responses)
        monkeypatch.setattr(ai_client, "get_client", lambda provider="openai": fake)
        return fake
    return install


def test_propose_plan_creates_proposal_and_attaches_card(api, athlete, fake_ai):
    race_date = athlete.local_today + dt.timedelta(weeks=9)
    fake = fake_ai([
        response(tool_calls=[tool_call("propose_plan", {
            "race_name": "City 10K", "race_date": str(race_date), "distance_km": 10,
            "is_target": True, "available_days": [1, 3, 5, 6], "long_run_day": 6})]),
        response(content="Here is your plan. The proposal is not saved until you accept it."),
    ])
    thread = api.post("/api/chat/threads/", {}, format="json").json()
    r = api.post(f"/api/chat/threads/{thread['id']}/messages/",
                 {"content": "Build a plan for me to run 10k."}, format="json")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"user", "assistant", "plan_changed", "needs_confirmation"}   # R16
    assistant = body["assistant"]
    assert set(assistant) == {"id", "role", "content", "attachments", "status", "created_at",
                              "plan_changed", "needs_confirmation"}                  # R16
    assert assistant["status"] == "done"
    [card] = assistant["attachments"]
    assert card["type"] == "plan_proposal" and card["plan"]["status"] == "proposed"
    plan = TrainingPlan.objects.get(pk=card["plan"]["id"])
    assert plan.athlete == athlete and plan.workouts.exists()
    assert plan.chat_message_id == assistant["id"]
    # The tool result was fed back to the model, and every call was logged.
    assert fake.requests[1]["messages"][-1]["role"] == "tool"
    assert AIRequestLog.objects.filter(athlete=athlete, operation="chat").count() == 2
    stored = ChatMessage.objects.get(pk=assistant["id"])
    assert stored.tool_calls[0]["name"] == "propose_plan"
    # Thread got a title from the first message.
    assert ChatThread.objects.get(pk=thread["id"]).title.startswith("Build a plan")


def test_loop_stops_after_six_calls(api, athlete, fake_ai):
    calls = [response(tool_calls=[tool_call("get_training_summary", {"weeks": 2}, f"c{i}")])
             for i in range(5)]
    fake = fake_ai(calls + [response(content="Summary done.")])
    thread = ChatThread.objects.create(athlete=athlete)
    r = api.post(f"/api/chat/threads/{thread.pk}/messages/", {"content": "hi"}, format="json")
    assert r.json()["assistant"]["content"] == "Summary done."
    assert len(fake.requests) == 6
    assert fake.requests[-1]["tool_choice"] == "none"


def test_ai_unavailable_is_a_200_with_error_status(api, athlete, fake_ai):
    fake_ai([RuntimeError("boom")])
    thread = ChatThread.objects.create(athlete=athlete)
    r = api.post(f"/api/chat/threads/{thread.pk}/messages/", {"content": "hi"}, format="json")
    assert r.status_code == 200
    assert r.json()["assistant"]["status"] == "error"
    assert "try again" in r.json()["assistant"]["content"]
    assert AIRequestLog.objects.filter(athlete=athlete, status="error").exists()


def test_budget_exhausted_is_friendly(api, athlete, fake_ai, monkeypatch):
    from apps.coaching import services

    monkeypatch.setattr(services, "MONTHLY_CALL_BUDGET", 0)
    fake = fake_ai([])
    thread = ChatThread.objects.create(athlete=athlete)
    r = api.post(f"/api/chat/threads/{thread.pk}/messages/", {"content": "hi"}, format="json")
    assert r.status_code == 200 and r.json()["assistant"]["status"] == "error"
    assert fake.requests == []


def test_clear_day_and_tool_scoping(api, athlete, other_athlete, proposed_plan, fake_ai):
    from apps.planning.plan_store import accept_plan, propose_plan

    accept_plan(proposed_plan)
    day = proposed_plan.workouts.order_by("date").first().date
    foreign = propose_plan(other_athlete, race_name="X",
                           race_date=other_athlete.local_today + dt.timedelta(weeks=9),
                           distance_km=10)
    foreign_workout = foreign.workouts.first()
    fake_ai([
        response(tool_calls=[
            tool_call("clear_day", {"date": str(day), "reason": "Big night out"}, "a"),
            tool_call("skip_workout", {"id": foreign_workout.pk, "reason": "x"}, "b"),
        ]),
        response(content="Cleared."),
    ])
    thread = ChatThread.objects.create(athlete=athlete)
    api.post(f"/api/chat/threads/{thread.pk}/messages/", {"content": "day off"}, format="json")
    assert not proposed_plan.workouts.filter(date=day, status="planned").exists()
    foreign_workout.refresh_from_db()
    assert foreign_workout.status == "planned"          # another athlete's: untouched
    audit = ChatMessage.objects.filter(role="assistant").first().tool_calls
    assert "error" in audit[1]["result"]


def test_guide_creates_thread_with_workout_attached(api, athlete, proposed_plan, fake_ai):
    fake_ai([response(content="Warm up by walking...")])
    workout = proposed_plan.workouts.first()
    r = api.post(f"/api/workouts/{workout.pk}/guide/")
    assert r.status_code == 201
    messages = api.get(f"/api/chat/threads/{r.json()['thread_id']}/messages/").json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "How do I execute this workout?"
    assert messages[0]["attachments"][0]["type"] == "workout"


def test_client_errors_are_not_retried_and_reasoning_is_off(api, athlete, fake_ai, settings):
    class BadRequest(Exception):
        status_code = 400

    fake = fake_ai([BadRequest("400 tools with reasoning_effort")] * 3)
    settings.AI_MAX_RETRIES = 2
    thread = ChatThread.objects.create(athlete=athlete)
    r = api.post(f"/api/chat/threads/{thread.pk}/messages/", {"content": "hi"}, format="json")
    assert r.status_code == 200 and r.json()["assistant"]["status"] == "error"
    assert len(fake.requests) == 1
    assert fake.requests[0]["reasoning_effort"] == "none"


# --- races: plan for the athlete's saved race, never an invented one -------------------

def test_system_prompt_lists_saved_races(athlete):
    from apps.coaching.chat import system_prompt
    from apps.planning.models import Race

    Race.objects.create(athlete=athlete, name="Cadbury 10k", is_target=True,
                        date=athlete.local_today + dt.timedelta(weeks=14), distance_km=10)
    prompt = system_prompt(athlete)
    assert "Cadbury 10k" in prompt and '"races"' in prompt


def test_propose_plan_by_race_id_uses_the_saved_race(athlete):
    from apps.coaching.tools import ToolRunner
    from apps.planning.models import Race

    race = Race.objects.create(athlete=athlete, name="Cadbury 10k", is_target=True,
                               date=athlete.local_today + dt.timedelta(weeks=14), distance_km=10)
    result = ToolRunner(athlete).t_propose_plan(race_id=race.pk, available_days=[0, 2, 4, 5])
    assert "error" not in result
    plan = TrainingPlan.objects.get(pk=result["plan_id"])
    assert plan.race_id == race.pk
    assert Race.objects.filter(athlete=athlete).count() == 1      # nothing invented


def test_propose_plan_refuses_an_invented_date_when_races_are_saved(athlete):
    from apps.coaching.tools import ToolRunner
    from apps.planning.models import Race

    Race.objects.create(athlete=athlete, name="Cadbury 10k", is_target=True,
                        date=athlete.local_today + dt.timedelta(weeks=14), distance_km=10)
    guessed = athlete.local_today + dt.timedelta(weeks=12)
    result = ToolRunner(athlete).t_propose_plan(race_name="10K", race_date=str(guessed), distance_km=10)
    assert "error" in result and result["races"][0]["name"] == "Cadbury 10k"
    assert Race.objects.filter(athlete=athlete).count() == 1
    assert not TrainingPlan.objects.filter(athlete=athlete).exists()

    # The athlete named it themselves → allowed.
    ok = ToolRunner(athlete).t_propose_plan(race_name="Park 10K", race_date=str(guessed),
                                            distance_km=10, confirmed_new_race=True)
    assert "error" not in ok


def test_propose_plan_rejects_another_athletes_race(athlete, other_athlete):
    from apps.coaching.tools import ToolRunner
    from apps.planning.models import Race

    theirs = Race.objects.create(athlete=other_athlete, name="Theirs", is_target=True,
                                 date=athlete.local_today + dt.timedelta(weeks=10), distance_km=10)
    assert "error" in ToolRunner(athlete).t_propose_plan(race_id=theirs.pk)
