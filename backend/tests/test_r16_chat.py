"""R16 §B: the coach edits workouts through tools — and never pretends. The model is
always the FakeOpenAI client; no real AI calls."""

import datetime as dt
import logging

import pytest

from apps.coaching.honesty import CORRECTION_NOTE
from apps.coaching.models import ChatMessage, ChatThread
from apps.planning.models import PlannedWorkout
from tests.r7_helpers import make_workout, tomorrow
from tests.test_chat_tools import fake_ai, response, tool_call  # noqa: F401 — fixture


@pytest.fixture
def thread(athlete):
    return ChatThread.objects.create(athlete=athlete, title="t")


def say(api, thread, text="Make Saturday's run longer"):
    r = api.post(f"/api/chat/threads/{thread.pk}/messages/", {"content": text}, format="json")
    assert r.status_code == 200, r.json()
    return r.json()


def test_edit_within_cap_applies_and_reports_plan_changed(api, athlete, thread, fake_ai):
    w = make_workout(athlete, tomorrow(athlete))             # 720 s running
    fake = fake_ai([
        response(tool_calls=[tool_call("edit_workout", {"id": w.pk, "add_minutes": 2})]),
        response(content="Done — I've added 2 minutes: tomorrow 23 → 25 min."),
    ])
    body = say(api, thread)
    w.refresh_from_db()
    assert w.edited_by == "user" and w.edited_via == "chat" and w.duration_s == 1500
    [changed] = body["plan_changed"]
    assert changed["workout_id"] == w.pk and changed["date"] == str(w.date)
    assert "23 → 25 min" in changed["summary"]
    assert body["assistant"]["plan_changed"] == body["plan_changed"]
    assert body["assistant"]["needs_confirmation"] is None and body["needs_confirmation"] is None
    assert body["assistant"]["attachments"][0]["workout"]["id"] == w.pk
    assert CORRECTION_NOTE not in body["assistant"]["content"]
    assert len(fake.requests) == 2
    message = ChatMessage.objects.get(pk=body["assistant"]["id"])
    assert message.guard is None
    # GET shows the chip too
    listed = api.get(f"/api/chat/threads/{thread.pk}/messages/").json()
    assert listed[-1]["plan_changed"] == body["plan_changed"]


def test_big_increase_needs_confirmation_then_applies(api, athlete, thread, fake_ai):
    w = make_workout(athlete, tomorrow(athlete))
    fake_ai([
        response(tool_calls=[tool_call("edit_workout", {"id": w.pk, "add_minutes": 5})]),
        response(content="That's 42 % more running than planned. Shall I go ahead?"),
    ])
    body = say(api, thread)
    w.refresh_from_db()
    assert w.edited_by == "" and body["plan_changed"] == []
    pending = body["assistant"]["needs_confirmation"]
    assert pending["workout_id"] == w.pk and pending["date"] == str(w.date)
    assert pending["increase_pct"] == 42 and pending["summary"].endswith("(+42%)")
    assert body["needs_confirmation"] == pending
    message = ChatMessage.objects.get(pk=body["assistant"]["id"])
    [call] = message.tool_calls
    assert call["result"]["status"] == "needs_confirmation"
    assert "NOTHING WAS SAVED" in call["result"]["message"]
    assert api.get(f"/api/chat/threads/{thread.pk}/messages/").json()[-1][
        "needs_confirmation"] == pending

    fake_ai([
        response(tool_calls=[tool_call("edit_workout", {"id": w.pk, "add_minutes": 5,
                                                        "confirmed": True})]),
        response(content="Done: tomorrow 23 → 28 min."),
    ])
    body = say(api, thread, "Yes, do it.")
    w.refresh_from_db()
    assert w.edited_by == "user" and body["needs_confirmation"] is None
    assert body["plan_changed"][0]["workout_id"] == w.pk


def test_confirmation_cleared_when_applied_in_the_same_turn(api, athlete, thread, fake_ai):
    w = make_workout(athlete, tomorrow(athlete))
    fake_ai([
        response(tool_calls=[tool_call("edit_workout", {"id": w.pk, "add_minutes": 5})]),
        response(tool_calls=[tool_call("edit_workout", {"id": w.pk, "add_minutes": 5,
                                                        "confirmed": True}, "c2")]),
        response(content="Updated: 23 → 28 min."),
    ])
    body = say(api, thread)
    assert body["needs_confirmation"] is None and len(body["plan_changed"]) == 1


def test_edit_week_tool(api, athlete, thread, fake_ai):
    today = athlete.local_today
    monday = today + dt.timedelta(days=7 - today.weekday())
    a = make_workout(athlete, monday)
    b = make_workout(athlete, monday + dt.timedelta(days=2))
    fake_ai([
        response(tool_calls=[tool_call("edit_week", {"week_start": str(monday),
                                                     "action": "set_hr_range",
                                                     "hr_low": 120, "hr_high": 140})]),
        response(content="Set HR 120–140 on next week's runs."),
    ])
    body = say(api, thread, "Cap my HR next week")
    assert {c["workout_id"] for c in body["plan_changed"]} == {a.pk, b.pk}
    a.refresh_from_db()
    assert all(s["hr_max"] == 140 for s in a.steps if s["intensity"] != "walk")

    fake_ai([
        response(tool_calls=[tool_call("edit_week", {"week_start": str(monday),
                                                     "action": "scale", "value": 1.5})]),
        response(content="That would be a big jump — want me to do it?"),
    ])
    body = say(api, thread, "Make next week 50% bigger")
    assert body["needs_confirmation"]["week_start"] == str(monday)
    assert body["plan_changed"] == []


def test_tools_are_scoped_to_the_athlete(api, athlete, other_athlete, thread, fake_ai):
    theirs = make_workout(other_athlete, tomorrow(other_athlete))
    fake = fake_ai([
        response(tool_calls=[tool_call("edit_workout", {"id": theirs.pk, "add_minutes": 1})]),
        response(content="I couldn't find that workout, so nothing changed."),
    ])
    body = say(api, thread)
    theirs.refresh_from_db()
    assert theirs.edited_by == "" and body["plan_changed"] == []
    tool_msg = fake.requests[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and "No such workout" in tool_msg["content"]


def test_system_prompt_has_the_honesty_rule_and_ids(athlete):
    from apps.coaching.chat import system_prompt

    w = make_workout(athlete, tomorrow(athlete))
    prompt = system_prompt(athlete)
    assert "Honesty rule" in prompt and "needs_confirmation" in prompt
    assert f'"id": {w.pk}' in prompt and "next_7_days" in prompt


# --- honesty guard -------------------------------------------------------------------------------

def test_guard_reprompts_a_false_claim(api, athlete, thread, fake_ai, caplog):
    w = make_workout(athlete, tomorrow(athlete))
    fake = fake_ai([
        response(content="I've moved your run to Friday."),           # no tool called
        response(content="I haven't changed anything yet — should I move it to Friday?"),
    ])
    with caplog.at_level(logging.WARNING, logger="apps.coaching.chat"):
        body = say(api, thread, "Move tomorrow's run to Friday")
    assert body["assistant"]["content"].startswith("I haven't changed anything yet")
    assert body["plan_changed"] == []
    reprompt = fake.requests[1]["messages"][-1]
    assert reprompt["role"] == "user" and "No tool was called" in reprompt["content"]
    assert fake.requests[1]["messages"][-2] == {"role": "assistant",
                                                "content": "I've moved your run to Friday."}
    message = ChatMessage.objects.get(pk=body["assistant"]["id"])
    assert message.guard["fired"] and message.guard["outcome"] == "corrected"
    assert "honesty guard" in caplog.text
    w.refresh_from_db()
    assert w.date == tomorrow(athlete)


def test_guard_appends_a_correction_when_still_dishonest(api, athlete, thread, fake_ai):
    fake_ai([
        response(content="Your workout has been updated on the watch."),
        response(content="All done — I've updated your run to 40 minutes."),
    ])
    body = say(api, thread)
    assert body["assistant"]["content"].endswith(CORRECTION_NOTE)
    message = ChatMessage.objects.get(pk=body["assistant"]["id"])
    assert message.guard["outcome"] == "note_appended"


def test_guard_counts_needs_confirmation_as_no_change(api, athlete, thread, fake_ai):
    w = make_workout(athlete, tomorrow(athlete))
    fake = fake_ai([
        response(tool_calls=[tool_call("edit_workout", {"id": w.pk, "add_minutes": 10})]),
        response(content="I've increased tomorrow's run by 10 minutes."),
        response(tool_calls=[tool_call("edit_workout", {"id": w.pk, "add_minutes": 2},
                                       "c2")]),
        response(content="I added 2 minutes now (23 → 25 min); the full 10 needs your OK."),
    ])
    body = say(api, thread)
    # (the fake keeps a reference to the live conversation list, so search it)
    assert any(m["role"] == "user" and "Automatic check" in m["content"]
               and "needs_confirmation" in m["content"] for m in fake.requests[2]["messages"])
    message = ChatMessage.objects.get(pk=body["assistant"]["id"])
    assert message.guard["outcome"] == "tool_succeeded"
    assert body["plan_changed"][0]["workout_id"] == w.pk
    assert not body["assistant"]["content"].endswith(CORRECTION_NOTE)


def test_guard_reprompt_failure_appends_note(api, athlete, thread, fake_ai):
    fake_ai([response(content="I've moved your long run to Sunday."),
             RuntimeError("503 overloaded")])
    body = say(api, thread)
    assert body["assistant"]["status"] == "done"
    assert body["assistant"]["content"] == ("I've moved your long run to Sunday.\n\n"
                                            + CORRECTION_NOTE)


def test_guard_quiet_when_the_tool_succeeded(api, athlete, thread, fake_ai):
    w = make_workout(athlete, tomorrow(athlete))
    fake = fake_ai([
        response(tool_calls=[tool_call("move_workout", {"id": w.pk,
                                                        "new_date": str(tomorrow(athlete, 2))})]),
        response(content="I've moved your run to the day after."),
    ])
    body = say(api, thread)
    assert len(fake.requests) == 2 and body["plan_changed"][0]["workout_id"] == w.pk
    assert "moved" in body["plan_changed"][0]["summary"]
    assert PlannedWorkout.objects.get(pk=w.pk).date == tomorrow(athlete, 2)
