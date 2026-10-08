"""R18 §C: the coach acts on explicit requests — update_profile (always confirmed by the
athlete), the refusal guard next to the R16 honesty guard. The model is always the fake
OpenAI client; no real AI calls."""

import pytest

from apps.coaching import honesty
from apps.coaching.models import ChatMessage, ChatThread
from apps.coaching.tools import ToolRunner
from tests.r7_helpers import make_workout, tomorrow
from tests.test_chat_tools import fake_ai, response, tool_call  # noqa: F401 — fixture


@pytest.fixture
def thread(athlete):
    return ChatThread.objects.create(athlete=athlete, title="t")


def say(api, thread, text):
    r = api.post(f"/api/chat/threads/{thread.pk}/messages/", {"content": text}, format="json")
    assert r.status_code == 200, r.json()
    return r.json()


def test_update_profile_asks_first_then_applies_on_yes(api, athlete, thread, fake_ai):
    fake_ai([
        response(tool_calls=[tool_call("update_profile",
                                       {"field": "sleep_need_minutes", "value": 7,
                                        "confirmed": True})]),     # self-confirm: refused
        response(content="Set your sleep need to 7 h (from Garmin's 8 h)? Do it anyway?"),
    ])
    body = say(api, thread, "Set my sleep need to 7 hours")
    athlete.refresh_from_db()
    assert athlete.sleep_need_minutes is None and body["profile_changed"] == []
    pending = body["needs_confirmation"]
    assert pending["field"] == "sleep_need_minutes" and pending["value"] == 420
    assert pending["increase_pct"] is None and "7 h" in pending["summary"]

    fake_ai([
        response(tool_calls=[tool_call("update_profile",
                                       {"field": "sleep_need_minutes", "value": 420,
                                        "confirmed": True})]),
        response(content="Done — your sleep need is now 7 h."),
    ])
    body = say(api, thread, "Yes, do it.")
    athlete.refresh_from_db()
    assert athlete.sleep_need_minutes == 420
    [changed] = body["profile_changed"]
    assert changed["field"] == "sleep_need_minutes" and changed["after_display"] == "7 h"
    assert body["needs_confirmation"] is None
    assert body["assistant"]["profile_changed"] == body["profile_changed"]
    assert honesty.CORRECTION_NOTE not in body["assistant"]["content"]


def test_update_profile_validation_and_warnings(athlete):
    runner = ToolRunner(athlete)
    assert "error" in runner("update_profile", {"field": "sleep_need_minutes", "value": 2})
    assert "error" in runner("update_profile", {"field": "long_run_day", "value": 0})   # not a run day
    out = runner("update_profile", {"field": "sleep_need_minutes", "value": 6})
    assert out["status"] == "needs_confirmation" and out["warnings"]
    out = runner("update_profile", {"field": "usual_run_time", "value": "6:30 pm"})
    assert out["display"] == "18:30"


def test_refusal_guard_reprompts_to_call_the_tool(api, athlete, thread, fake_ai):
    w = make_workout(athlete, tomorrow(athlete))            # 23 min
    fake = fake_ai([
        response(content="I can't do that — going from 23 to 40 min is too big a jump. "
                         "Let's keep it at 23 min."),
        response(tool_calls=[tool_call("edit_workout", {"id": w.pk, "total_minutes": 40})]),
        response(content="That's a big jump (+74 %). Do it anyway?"),
    ])
    body = say(api, thread, "Change tomorrow's run from 23 to 40 min")
    assert len(fake.requests) == 3
    assert body["assistant"]["content"].endswith("Do it anyway?")
    assert body["needs_confirmation"]["workout_id"] == w.pk
    guard = ChatMessage.objects.get(pk=body["assistant"]["id"]).guard
    assert guard["refusal"]["outcome"] == "tool_called"
    w.refresh_from_db()
    assert w.edited_by == ""                                 # nothing saved without a yes


def test_refusal_guard_leaves_questions_and_tool_calls_alone(api, athlete, thread, fake_ai):
    fake = fake_ai([response(content="I wouldn't recommend it yet — keep it at 23 min.")])
    body = say(api, thread, "Should I increase my run to 40 min?")      # a question
    assert len(fake.requests) == 1
    assert ChatMessage.objects.get(pk=body["assistant"]["id"]).guard is None


def test_refusal_detection():
    assert honesty.explicit_change_request("Make Thursday 30 min instead of 17")
    assert honesty.explicit_change_request("Set my sleep need to 7 h")
    assert not honesty.explicit_change_request("How did my run go?")
    assert honesty.declined("I'd recommend keeping it at 17 minutes for now.")
    assert honesty.declined("That's +76 %. Do it anyway?") is None
