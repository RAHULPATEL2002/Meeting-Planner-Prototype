"""Meeting creation, validation, listing and access control."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.time_utils import utcnow
from tests.conftest import iso

# --------------------------------------------------------------------------
# Creation
# --------------------------------------------------------------------------


def test_create_meeting_returns_the_full_detail_view(client, alice, bob, meeting_payload):
    response = client.post(
        "/api/meetings",
        json=meeting_payload(participants=[{"email": bob.email}]),
        headers=alice.headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["title"] == "Sprint planning"
    assert body["duration_minutes"] == 60
    assert body["is_organizer"] is True
    assert body["organizer"]["email"] == alice.email
    assert body["ics_url"] == f"/api/meetings/{body['id']}/calendar.ics"
    # Timestamps come back as unambiguous UTC.
    assert body["starts_at"].endswith("Z")


def test_organizer_is_added_as_an_accepted_participant(client, alice, meeting_payload):
    body = client.post("/api/meetings", json=meeting_payload(), headers=alice.headers).json()

    assert body["participant_count"] == 1
    organizer_row = body["participants"][0]
    assert organizer_row["email"] == alice.email
    assert organizer_row["status"] == "accepted"
    assert organizer_row["is_organizer"] is True
    assert body["my_status"] == "accepted"


def test_inviting_a_registered_user_links_their_account(client, alice, bob, meeting_payload):
    body = client.post(
        "/api/meetings",
        json=meeting_payload(participants=[{"email": "BOB@EXAMPLE.COM"}]),
        headers=alice.headers,
    ).json()

    row = next(p for p in body["participants"] if p["email"] == bob.email)
    assert row["is_registered"] is True
    assert row["user"]["full_name"] == "Bob Brown"
    assert row["status"] == "invited"


def test_inviting_an_unregistered_email_still_works(client, alice, meeting_payload):
    body = client.post(
        "/api/meetings",
        json=meeting_payload(
            participants=[{"email": "guest@partner.example", "display_name": "Guest Speaker"}]
        ),
        headers=alice.headers,
    ).json()

    row = next(p for p in body["participants"] if p["email"] == "guest@partner.example")
    assert row["is_registered"] is False
    assert row["user"] is None
    assert row["name"] == "Guest Speaker"


def test_organizer_inviting_themselves_is_ignored(client, alice, meeting_payload):
    """Convenience over a 409: the organiser is already on the list."""
    body = client.post(
        "/api/meetings",
        json=meeting_payload(participants=[{"email": alice.email}]),
        headers=alice.headers,
    ).json()
    assert body["participant_count"] == 1


def test_response_summary_counts_every_status(client, alice, bob, meeting_payload):
    body = client.post(
        "/api/meetings",
        json=meeting_payload(participants=[{"email": bob.email}, {"email": "x@example.com"}]),
        headers=alice.headers,
    ).json()

    assert body["response_summary"] == {
        "total": 3,
        "accepted": 1,
        "declined": 0,
        "tentative": 0,
        "invited": 2,
    }


def test_creating_a_meeting_requires_auth(client, meeting_payload):
    assert client.post("/api/meetings", json=meeting_payload()).status_code == 401


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def test_end_before_start_is_rejected(client, alice, meeting_payload):
    start = utcnow() + timedelta(days=1)
    payload = meeting_payload(starts_at=iso(start), ends_at=iso(start - timedelta(hours=1)))
    assert client.post("/api/meetings", json=payload, headers=alice.headers).status_code == 422


def test_zero_length_meeting_is_rejected(client, alice, meeting_payload):
    start = utcnow() + timedelta(days=1)
    payload = meeting_payload(starts_at=iso(start), ends_at=iso(start))
    assert client.post("/api/meetings", json=payload, headers=alice.headers).status_code == 422


def test_meeting_shorter_than_the_minimum_is_rejected(client, alice, meeting_payload, window):
    payload = meeting_payload(**window(duration_minutes=1))
    assert client.post("/api/meetings", json=payload, headers=alice.headers).status_code == 422


def test_meeting_longer_than_a_week_is_rejected(client, alice, meeting_payload, window):
    payload = meeting_payload(**window(duration_minutes=8 * 24 * 60))
    assert client.post("/api/meetings", json=payload, headers=alice.headers).status_code == 422


def test_duplicate_invitees_are_rejected(client, alice, meeting_payload):
    payload = meeting_payload(
        participants=[{"email": "dup@example.com"}, {"email": "DUP@example.com"}]
    )
    assert client.post("/api/meetings", json=payload, headers=alice.headers).status_code == 422


@pytest.mark.parametrize("title", ["", "  ", "ab"])
def test_short_titles_are_rejected(client, alice, meeting_payload, title):
    payload = meeting_payload(title=title)
    assert client.post("/api/meetings", json=payload, headers=alice.headers).status_code == 422


def test_invalid_invitee_email_is_rejected(client, alice, meeting_payload):
    payload = meeting_payload(participants=[{"email": "not-an-email"}])
    assert client.post("/api/meetings", json=payload, headers=alice.headers).status_code == 422


def test_timezone_offset_input_is_stored_as_utc(client, alice, meeting_payload):
    """09:00+02:00 is 07:00 UTC — the API must not keep the local wall time."""
    payload = meeting_payload(
        starts_at="2030-03-01T09:00:00+02:00", ends_at="2030-03-01T10:00:00+02:00"
    )
    body = client.post("/api/meetings", json=payload, headers=alice.headers).json()
    assert body["starts_at"] == "2030-03-01T07:00:00Z"
    assert body["ends_at"] == "2030-03-01T08:00:00Z"


# --------------------------------------------------------------------------
# Listing & scopes
# --------------------------------------------------------------------------


def test_list_defaults_to_upcoming_meetings(client, alice, meeting_payload, window):
    client.post("/api/meetings", json=meeting_payload(**window(24)), headers=alice.headers)
    client.post(
        "/api/meetings",
        json=meeting_payload(title="Old retro", **window(start_in_hours=-48)),
        headers=alice.headers,
    )

    upcoming = client.get("/api/meetings", headers=alice.headers).json()
    assert [m["title"] for m in upcoming["items"]] == ["Sprint planning"]

    past = client.get("/api/meetings", params={"scope": "past"}, headers=alice.headers).json()
    assert [m["title"] for m in past["items"]] == ["Old retro"]

    every = client.get("/api/meetings", params={"scope": "all"}, headers=alice.headers).json()
    assert every["total"] == 2


def test_in_progress_meetings_still_count_as_upcoming(client, alice, meeting_payload, window):
    client.post(
        "/api/meetings",
        json=meeting_payload(**window(start_in_hours=-0.5, duration_minutes=60)),
        headers=alice.headers,
    )
    assert client.get("/api/meetings", headers=alice.headers).json()["total"] == 1


def test_upcoming_meetings_are_sorted_by_start_time(client, alice, meeting_payload, window):
    for title, hours in [("Later", 72), ("Sooner", 12)]:
        client.post(
            "/api/meetings",
            json=meeting_payload(title=title, **window(hours)),
            headers=alice.headers,
        )

    listed = client.get("/api/meetings", headers=alice.headers).json()
    titles = [m["title"] for m in listed["items"]]
    assert titles == ["Sooner", "Later"]


def test_invitees_see_the_meeting_in_their_list(client, alice, bob, meeting_payload):
    client.post(
        "/api/meetings",
        json=meeting_payload(participants=[{"email": bob.email}]),
        headers=alice.headers,
    )
    listed = client.get("/api/meetings", headers=bob.headers).json()
    assert listed["total"] == 1
    assert listed["items"][0]["is_organizer"] is False
    assert listed["items"][0]["my_status"] == "invited"


def test_unrelated_users_see_nothing(client, alice, bob, meeting_payload):
    client.post("/api/meetings", json=meeting_payload(), headers=alice.headers)
    assert client.get("/api/meetings", headers=bob.headers).json()["total"] == 0


# --------------------------------------------------------------------------
# Detail, update, delete
# --------------------------------------------------------------------------


def test_a_stranger_gets_404_not_403(client, alice, bob, meeting_payload):
    """403 would confirm the meeting exists; 404 reveals nothing."""
    meeting_id = client.post(
        "/api/meetings", json=meeting_payload(), headers=alice.headers
    ).json()["id"]
    assert client.get(f"/api/meetings/{meeting_id}", headers=bob.headers).status_code == 404


def test_missing_meeting_is_404(client, alice):
    assert client.get("/api/meetings/9999", headers=alice.headers).status_code == 404


def test_organizer_can_update_a_meeting(client, alice, meeting_payload):
    meeting_id = client.post(
        "/api/meetings", json=meeting_payload(), headers=alice.headers
    ).json()["id"]

    response = client.patch(
        f"/api/meetings/{meeting_id}",
        json={"title": "Sprint planning (moved)", "location": "Zoom"},
        headers=alice.headers,
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Sprint planning (moved)"
    assert response.json()["location"] == "Zoom"


def test_partial_update_validates_against_the_stored_window(client, alice, meeting_payload, window):
    """Moving only the end time must still be checked against the existing start."""
    payload = meeting_payload(**window(24, 60))
    meeting_id = client.post("/api/meetings", json=payload, headers=alice.headers).json()["id"]

    response = client.patch(
        f"/api/meetings/{meeting_id}",
        json={"ends_at": payload["starts_at"]},  # end == start
        headers=alice.headers,
    )
    assert response.status_code == 422


def test_participants_cannot_update_a_meeting(client, alice, bob, meeting_payload):
    meeting_id = client.post(
        "/api/meetings",
        json=meeting_payload(participants=[{"email": bob.email}]),
        headers=alice.headers,
    ).json()["id"]

    response = client.patch(
        f"/api/meetings/{meeting_id}", json={"title": "Hijacked"}, headers=bob.headers
    )
    assert response.status_code == 403


def test_empty_update_payload_is_rejected(client, alice, meeting_payload):
    meeting_id = client.post(
        "/api/meetings", json=meeting_payload(), headers=alice.headers
    ).json()["id"]
    response = client.patch(f"/api/meetings/{meeting_id}", json={}, headers=alice.headers)
    assert response.status_code == 422


def test_organizer_can_delete_and_participants_cannot(client, alice, bob, meeting_payload):
    meeting_id = client.post(
        "/api/meetings",
        json=meeting_payload(participants=[{"email": bob.email}]),
        headers=alice.headers,
    ).json()["id"]

    assert client.delete(f"/api/meetings/{meeting_id}", headers=bob.headers).status_code == 403
    assert client.delete(f"/api/meetings/{meeting_id}", headers=alice.headers).status_code == 204
    assert client.get(f"/api/meetings/{meeting_id}", headers=alice.headers).status_code == 404


def test_deleting_a_meeting_removes_its_participants(
    client, alice, bob, meeting_payload, db_session
):
    """Relies on SQLite foreign keys actually being enabled."""
    from app.models import Participant

    meeting_id = client.post(
        "/api/meetings",
        json=meeting_payload(participants=[{"email": bob.email}]),
        headers=alice.headers,
    ).json()["id"]

    client.delete(f"/api/meetings/{meeting_id}", headers=alice.headers)
    remaining = db_session.query(Participant).filter_by(meeting_id=meeting_id).count()
    assert remaining == 0
