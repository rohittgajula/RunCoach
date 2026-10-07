"""iCalendar (RFC 5545) serialisation for the calendar feed (R14 §5). Pure — no Django.

Only what a subscribed calendar needs: VEVENTs with a stable UID, SEQUENCE, DTSTAMP,
LAST-MODIFIED, all-day DTSTART/DTEND (VALUE=DATE) or a timed event in UTC ("Z", so no
VTIMEZONE block is needed), SUMMARY and DESCRIPTION. Text is escaped and lines are folded
at 75 octets with CRLF endings, as the RFC requires.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass

PRODID = "-//RunCoach//Training plan//EN"


@dataclass(frozen=True)
class Event:
    uid: str
    summary: str
    description: str
    day: dt.date | None = None                  # all-day event
    start_utc: dt.datetime | None = None        # timed event (aware, any zone)
    duration_s: int | None = None               # timed events only
    status: str = "CONFIRMED"                   # CONFIRMED | CANCELLED

    def content_hash(self) -> str:
        """What a change means: date/time, title, description or status."""
        blob = "|".join(str(x) for x in (self.day, self.start_utc, self.duration_s,
                                          self.summary, self.description, self.status))
        return hashlib.sha256(blob.encode()).hexdigest()


def escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", ""))


def fold(line: str) -> str:
    """Fold to 75 octets per line (continuations start with one space), never splitting
    a UTF-8 character."""
    out, current = [], b""
    limit = 75
    for char in line:
        encoded = char.encode()
        if len(current) + len(encoded) > limit:
            out.append(current.decode())
            current = b" "
            limit = 75
        current += encoded
    out.append(current.decode())
    return "\r\n".join(out)


def _utc(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _date(value: dt.date) -> str:
    return value.strftime("%Y%m%d")


def calendar(events: list[tuple[Event, int, dt.datetime]], *, name: str,
             stamp: dt.datetime) -> str:
    """events: (event, sequence, last_modified). `stamp` is DTSTAMP (generation time)."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{escape(name)}",
             "REFRESH-INTERVAL;VALUE=DURATION:PT1H", "X-PUBLISHED-TTL:PT1H"]
    for event, sequence, modified in events:
        lines += ["BEGIN:VEVENT", f"UID:{event.uid}", f"SEQUENCE:{sequence}",
                  f"DTSTAMP:{_utc(stamp)}", f"LAST-MODIFIED:{_utc(modified)}"]
        if event.start_utc is not None:
            end = event.start_utc + dt.timedelta(seconds=event.duration_s or 3600)
            lines += [f"DTSTART:{_utc(event.start_utc)}", f"DTEND:{_utc(end)}"]
        else:
            lines += [f"DTSTART;VALUE=DATE:{_date(event.day)}",
                      f"DTEND;VALUE=DATE:{_date(event.day + dt.timedelta(days=1))}",
                      "TRANSP:TRANSPARENT"]
        lines += [f"SUMMARY:{escape(event.summary)}",
                  f"DESCRIPTION:{escape(event.description)}", f"STATUS:{event.status}",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in lines) + "\r\n"


def minutes(seconds: int | float | None) -> str:
    total = int(round((seconds or 0) / 60))
    if total >= 60:
        hours, rest = divmod(total, 60)
        return f"{hours} h {rest} min" if rest else f"{hours} h"
    return f"{total} min"


def step_line(step: dict) -> str:
    """One workout step as a calendar line: 'Run 4:30 · easy (HR 130–145)'."""
    label = step.get("label") or (step.get("kind") or "Step").title()
    bits = [label]
    if step.get("duration_s") and not any(ch.isdigit() for ch in label):
        bits.append(minutes(step["duration_s"]))
    detail = []
    if step.get("hr_min") and step.get("hr_max"):
        detail.append(f"HR {step['hr_min']}–{step['hr_max']}")
    if step.get("pace_min_s") and step.get("pace_max_s"):
        detail.append(f"pace {_pace(step['pace_min_s'])}–{_pace(step['pace_max_s'])}/km")
    line = " · ".join(bits)
    return f"{line} ({', '.join(detail)})" if detail else line


def _pace(seconds) -> str:
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def steps_text(steps: list[dict], limit: int = 40) -> str:
    """Steps as lines, consecutive identical steps collapsed ('3 × Run 4:30 …')."""
    lines: list[tuple[str, int]] = []
    for step in steps or []:
        text = step_line(step)
        if lines and lines[-1][0] == text:
            lines[-1] = (text, lines[-1][1] + 1)
        else:
            lines.append((text, 1))
    out = [f"{n} × {text}" if n > 1 else text for text, n in lines[:limit]]
    return "\n".join(out)
