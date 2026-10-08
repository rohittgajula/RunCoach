"""R16 §B: the coach must never say the plan changed when it did not.

`claimed_change(text)` finds a sentence that claims a change to the plan ("I've moved
your long run to Sunday", "Your workout has been updated"); `mutation_succeeded(audit)`
says whether any plan-changing tool actually succeeded in the turn. When the first is
true and the second false, chat.run_turn re-prompts the model once with the facts and,
if the reply is still not honest, appends CORRECTION_NOTE.

Deliberately conservative: a claim needs a change verb in the first person / perfect
passive AND a plan word in the same sentence; questions and negated sentences ("I
haven't changed anything", "nothing was moved") are not claims.
"""

from __future__ import annotations

import json
import re

MUTATING_TOOLS = ("edit_workout", "edit_week", "move_workout", "skip_workout", "clear_day")
# A proposal is not a change to the active plan, but saying "I've set up a new plan" after
# one is honest — so it counts for the guard (not for `plan_changed`).
HONEST_TOOLS = MUTATING_TOOLS + ("propose_plan",)

VERBS = (r"updated|increased|changed|moved|extended|lengthened|shortened|reduced|"
         r"decreased|added|adjusted|edited|rescheduled|swapped|skipped|cleared|replaced|"
         r"bumped|switched|converted|scaled|cut|pushed|made|set|removed|tweaked|modified|"
         r"upped|dropped|sent|synced")
PASSIVE_VERBS = (r"updated|increased|changed|moved|extended|lengthened|shortened|reduced|"
                 r"adjusted|edited|rescheduled|swapped|skipped|cleared|replaced|switched|"
                 r"converted|scaled|modified|synced")
FIRST_PERSON = re.compile(
    r"\b(?:i(?:'ve|’ve| have)?|we(?:'ve|’ve| have)?)\s+"
    r"(?:just\s+|now\s+|also\s+|already\s+|gone ahead and\s+|went ahead and\s+)?"
    rf"(?:{VERBS})\b", re.IGNORECASE)
PASSIVE = re.compile(
    rf"\b(?:(?:has|have)\s+(?:now\s+|just\s+|already\s+)?been|(?:is|are)\s+now|"
    rf"(?:was|were)\s+(?:just\s+|now\s+)?)\s*(?:{PASSIVE_VERBS})\b", re.IGNORECASE)
PLAN_WORDS = re.compile(
    r"\b(?:workouts?|runs?|sessions?|plan|week|intervals?|tempo|long run|walks?|minutes|min|"
    r"watch|garmin|schedule|calendar|tomorrow|today|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday|steps?|heart rate|hr|pace|warm-up|cool-down|strides)\b", re.IGNORECASE)
NEGATION = re.compile(
    r"(?:n't|n’t|\bnot\b|\bnothing\b|\bno change|\bnever\b|\bwithout\b|\bunable\b|\bwould\b|"
    r"\bwill\b|\bcan\b|\bcould\b|\bif\b|\bonce\b|\bshould\b|\bwant me\b|\bshall\b)", re.IGNORECASE)

CORRECTION_NOTE = "_Correction: nothing in your plan was changed in this reply._"


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def claimed_change(text: str) -> str | None:
    """The first sentence that claims a plan change, else None."""
    for sentence in _sentences(text):
        if sentence.endswith("?"):
            continue
        match = FIRST_PERSON.search(sentence) or PASSIVE.search(sentence)
        if not match or not PLAN_WORDS.search(sentence):
            continue
        if NEGATION.search(sentence[:match.end()]):
            continue
        return sentence[:200]
    return None


def tool_succeeded(name: str, result) -> bool:
    if name not in HONEST_TOOLS or not isinstance(result, dict) or result.get("error"):
        return False
    if name in ("edit_workout", "edit_week"):
        return result.get("status") == "updated"
    if name == "propose_plan":
        return bool(result.get("plan_id"))
    return True


def mutation_succeeded(audit: list[dict]) -> bool:
    return any(tool_succeeded(a.get("name"), a.get("result")) for a in audit or [])


def facts(audit: list[dict]) -> str:
    """What the tools in this turn really did, for the corrective re-prompt."""
    if not audit:
        return "No tool was called in this turn."
    lines = []
    for call in audit:
        result = call.get("result")
        if isinstance(result, dict):
            status = result.get("error") and f"error: {result['error']}" \
                or result.get("status") or ("ok" if tool_succeeded(call.get("name"), result)
                                            else "read only")
        else:
            status = "ok"
        lines.append(f"- {call.get('name')}({json.dumps(call.get('arguments'), default=str)[:200]})"
                     f" → {str(status)[:200]}")
    return "Tool calls in this turn:\n" + "\n".join(lines)


def reprompt(audit: list[dict]) -> str:
    return (
        "[Automatic check — not from the athlete] Your last reply says the plan or a workout "
        "was changed, but no change was saved in this turn.\n"
        f"{facts(audit)}\n"
        "Never claim a change that did not happen. Either call the right tool now "
        "(edit_workout, edit_week, move_workout, skip_workout or clear_day) to make the change "
        "the athlete asked for — if it returns needs_confirmation, ask the athlete instead — or "
        "rewrite your reply so it says plainly that nothing has been changed yet. Answer the "
        "athlete directly and don't mention this check.")
