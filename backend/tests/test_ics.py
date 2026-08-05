"""iCalendar export: text escaping, line folding, and the HTTP endpoint."""

from __future__ import annotations

from app.services.ics import MAX_LINE_OCTETS, escape_text, fold


def unfold(document: str) -> str:
    """Reverse RFC 5545 line folding, the way a calendar client would.

    Content lines are wrapped at 75 octets, so assertions about a long line
    (an ATTENDEE with a real email address, say) have to unfold first.
    """
    return document.replace("\r\n ", "")


def test_escape_handles_every_special_character():
    assert escape_text("a,b") == "a\\,b"
    assert escape_text("a;b") == "a\\;b"
    assert escape_text("a\\b") == "a\\\\b"
    assert escape_text("line1\nline2") == "line1\\nline2"
    assert escape_text("line1\r\nline2") == "line1\\nline2"


def test_backslash_is_escaped_before_the_others():
    """Wrong ordering would double-escape and corrupt the output."""
    assert escape_text("a\\,b") == "a\\\\\\,b"


def test_short_lines_are_left_alone():
    assert fold("SUMMARY:hello") == "SUMMARY:hello"


def test_long_lines_are_folded_with_a_leading_space():
    line = "DESCRIPTION:" + "x" * 200
    folded = fold(line)

    segments = folded.split("\r\n")
    assert len(segments) > 1
    assert all(segment.startswith(" ") for segment in segments[1:])
    # Reassembling by dropping the CRLF+space must return the original.
    assert segments[0] + "".join(s[1:] for s in segments[1:]) == line
    assert all(len(s.encode()) <= MAX_LINE_OCTETS for s in segments)


def test_folding_never_splits_a_multibyte_character():
    line = "SUMMARY:" + "é" * 120
    for segment in fold(line).split("\r\n"):
        segment.encode("utf-8").decode("utf-8")  # would raise if a char were cut


def test_ics_endpoint_returns_a_calendar_document(client, alice, bob, meeting_payload):
    meeting = client.post(
        "/api/meetings",
        json=meeting_payload(
            title="Quarterly; review, part 2",
            participants=[{"email": bob.email}],
        ),
        headers=alice.headers,
    ).json()

    response = client.get(f"/api/meetings/{meeting['id']}/calendar.ics", headers=alice.headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    disposition = response.headers["content-disposition"]
    assert f'filename="meeting-{meeting["id"]}.ics"' in disposition

    assert response.text.startswith("BEGIN:VCALENDAR\r\n")
    assert response.text.rstrip().endswith("END:VCALENDAR")

    body = unfold(response.text)
    assert f"UID:meeting-{meeting['id']}@meeting-planner.local" in body
    # Structural characters in the title are escaped, not emitted raw.
    assert "SUMMARY:Quarterly\\; review\\, part 2" in body
    assert f"ORGANIZER;CN=Alice Adams:mailto:{alice.email}" in body
    assert f"PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:{bob.email}" in body


def test_ics_reflects_rsvp_status(client, alice, bob, meeting_payload):
    meeting = client.post(
        "/api/meetings",
        json=meeting_payload(participants=[{"email": bob.email}]),
        headers=alice.headers,
    ).json()
    client.post(
        f"/api/meetings/{meeting['id']}/rsvp", json={"status": "accepted"}, headers=bob.headers
    )

    response = client.get(f"/api/meetings/{meeting['id']}/calendar.ics", headers=alice.headers)
    body = unfold(response.text)
    assert f"PARTSTAT=ACCEPTED;RSVP=TRUE:mailto:{bob.email}" in body


def test_ics_is_not_available_to_strangers(client, bob, alice, meeting_payload):
    meeting = client.post("/api/meetings", json=meeting_payload(), headers=alice.headers).json()
    response = client.get(f"/api/meetings/{meeting['id']}/calendar.ics", headers=bob.headers)
    assert response.status_code == 404
