"""Minimal RFC 5545 (iCalendar) export.

Written by hand rather than pulled from a library: the subset we need is tiny,
and the two things people usually get wrong — text escaping and 75-octet line
folding — are the interesting part, so they are explicit and testable here.
"""

from __future__ import annotations

from datetime import datetime

from app.models import Meeting, ParticipantStatus
from app.time_utils import as_utc, utcnow

PRODID = "-//Meeting Planner Prototype//EN"
LINE_ENDING = "\r\n"  # RFC 5545 requires CRLF
MAX_LINE_OCTETS = 75

_PARTSTAT = {
    ParticipantStatus.ACCEPTED: "ACCEPTED",
    ParticipantStatus.DECLINED: "DECLINED",
    ParticipantStatus.TENTATIVE: "TENTATIVE",
    ParticipantStatus.INVITED: "NEEDS-ACTION",
}


def escape_text(value: str) -> str:
    """Escape a TEXT value: backslash first, then the structural characters."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def fold(line: str) -> str:
    """Fold a content line to 75 octets, continuing with a leading space.

    Folding is measured in *octets*, not characters, and a multi-byte character
    must not be split across the fold, so we accumulate encoded bytes.
    """
    encoded = line.encode("utf-8")
    if len(encoded) <= MAX_LINE_OCTETS:
        return line

    parts: list[str] = []
    current = bytearray()
    limit = MAX_LINE_OCTETS
    for char in line:
        char_bytes = char.encode("utf-8")
        if len(current) + len(char_bytes) > limit:
            parts.append(current.decode("utf-8"))
            current = bytearray()
            limit = MAX_LINE_OCTETS - 1  # continuation lines start with a space
        current.extend(char_bytes)
    parts.append(current.decode("utf-8"))
    return (LINE_ENDING + " ").join(parts)


def _stamp(value: datetime) -> str:
    """Format as a UTC iCalendar timestamp: ``20260810T090000Z``."""
    return as_utc(value).strftime("%Y%m%dT%H%M%SZ")


def meeting_to_ics(meeting: Meeting) -> str:
    """Render one meeting as a single-event VCALENDAR document."""
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        # Stable + globally unique: re-importing updates the event instead of
        # creating a duplicate.
        f"UID:meeting-{meeting.id}@meeting-planner.local",
        f"DTSTAMP:{_stamp(utcnow())}",
        f"DTSTART:{_stamp(meeting.starts_at)}",
        f"DTEND:{_stamp(meeting.ends_at)}",
        f"SUMMARY:{escape_text(meeting.title)}",
    ]

    if meeting.description:
        lines.append(f"DESCRIPTION:{escape_text(meeting.description)}")
    if meeting.location:
        lines.append(f"LOCATION:{escape_text(meeting.location)}")

    organizer = meeting.organizer
    lines.append(
        f"ORGANIZER;CN={escape_text(organizer.full_name)}:mailto:{organizer.email}"
    )

    for participant in meeting.participants:
        if participant.user_id == meeting.organizer_id:
            continue
        partstat = _PARTSTAT[participant.status]
        lines.append(
            f"ATTENDEE;CN={escape_text(participant.name)};"
            f"PARTSTAT={partstat};RSVP=TRUE:mailto:{participant.email}"
        )

    lines += ["END:VEVENT", "END:VCALENDAR"]
    return LINE_ENDING.join(fold(line) for line in lines) + LINE_ENDING
