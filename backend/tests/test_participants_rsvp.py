"""Invitations and RSVP flow."""

from __future__ import annotations

import pytest


@pytest.fixture
def meeting(client, alice, bob, meeting_payload):
    """A meeting organised by Alice with Bob invited."""
    return client.post(
        "/api/meetings",
        json=meeting_payload(participants=[{"email": bob.email}]),
        headers=alice.headers,
    ).json()


# --------------------------------------------------------------------------
# Invitations
# --------------------------------------------------------------------------


def test_organizer_can_invite_someone_later(client, alice, meeting):
    response = client.post(
        f"/api/meetings/{meeting['id']}/participants",
        json={"email": "carol@example.com", "display_name": "Carol"},
        headers=alice.headers,
    )
    assert response.status_code == 201
    assert response.json()["email"] == "carol@example.com"
    assert response.json()["status"] == "invited"

    detail = client.get(f"/api/meetings/{meeting['id']}", headers=alice.headers).json()
    assert detail["participant_count"] == 3


def test_inviting_the_same_email_twice_is_a_conflict(client, alice, bob, meeting):
    response = client.post(
        f"/api/meetings/{meeting['id']}/participants",
        json={"email": bob.email},
        headers=alice.headers,
    )
    assert response.status_code == 409


def test_only_the_organizer_can_invite(client, bob, meeting):
    response = client.post(
        f"/api/meetings/{meeting['id']}/participants",
        json={"email": "carol@example.com"},
        headers=bob.headers,
    )
    assert response.status_code == 403


def test_organizer_can_withdraw_an_invitation(client, alice, bob, meeting):
    bob_row = next(p for p in meeting["participants"] if p["email"] == bob.email)

    response = client.delete(
        f"/api/meetings/{meeting['id']}/participants/{bob_row['id']}", headers=alice.headers
    )
    assert response.status_code == 204
    # Bob loses access along with the invitation.
    assert client.get(f"/api/meetings/{meeting['id']}", headers=bob.headers).status_code == 404


def test_the_organizer_cannot_be_removed(client, alice, meeting):
    organizer_row = next(p for p in meeting["participants"] if p["is_organizer"])
    response = client.delete(
        f"/api/meetings/{meeting['id']}/participants/{organizer_row['id']}", headers=alice.headers
    )
    assert response.status_code == 400


def test_removing_an_unknown_participant_is_404(client, alice, meeting):
    response = client.delete(
        f"/api/meetings/{meeting['id']}/participants/9999", headers=alice.headers
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# RSVP
# --------------------------------------------------------------------------


@pytest.mark.parametrize("answer", ["accepted", "declined", "tentative"])
def test_participant_can_respond(client, bob, meeting, answer):
    response = client.post(
        f"/api/meetings/{meeting['id']}/rsvp", json={"status": answer}, headers=bob.headers
    )
    assert response.status_code == 200

    body = response.json()
    assert body["my_status"] == answer
    bob_row = next(p for p in body["participants"] if p["email"] == bob.email)
    assert bob_row["responded_at"] is not None


def test_rsvp_updates_the_response_summary(client, alice, bob, meeting):
    client.post(
        f"/api/meetings/{meeting['id']}/rsvp", json={"status": "declined"}, headers=bob.headers
    )
    detail = client.get(f"/api/meetings/{meeting['id']}", headers=alice.headers).json()

    assert detail["response_summary"]["declined"] == 1
    assert detail["response_summary"]["invited"] == 0
    assert detail["response_summary"]["accepted"] == 1  # the organiser


def test_rsvp_can_be_changed(client, bob, meeting):
    client.post(
        f"/api/meetings/{meeting['id']}/rsvp", json={"status": "accepted"}, headers=bob.headers
    )
    second = client.post(
        f"/api/meetings/{meeting['id']}/rsvp", json={"status": "declined"}, headers=bob.headers
    )
    assert second.json()["my_status"] == "declined"


def test_invited_is_not_a_valid_answer(client, bob, meeting):
    """'invited' is the initial state, not a response a user can pick."""
    response = client.post(
        f"/api/meetings/{meeting['id']}/rsvp", json={"status": "invited"}, headers=bob.headers
    )
    assert response.status_code == 422


def test_unknown_status_is_rejected(client, bob, meeting):
    response = client.post(
        f"/api/meetings/{meeting['id']}/rsvp", json={"status": "maybe-ish"}, headers=bob.headers
    )
    assert response.status_code == 422


def test_a_stranger_cannot_rsvp(client, register_user, meeting):
    stranger = register_user(email="mallory@example.com", full_name="Mallory")
    response = client.post(
        f"/api/meetings/{meeting['id']}/rsvp", json={"status": "accepted"}, headers=stranger.headers
    )
    # Not visible to them at all, so the meeting simply does not exist.
    assert response.status_code == 404


def test_a_guest_who_signs_up_later_can_rsvp(client, alice, meeting_payload, register_user):
    """Invite by email first, account created afterwards, RSVP still works."""
    created = client.post(
        "/api/meetings",
        json=meeting_payload(participants=[{"email": "newcomer@example.com"}]),
        headers=alice.headers,
    ).json()

    newcomer = register_user(email="newcomer@example.com", full_name="New Comer")
    response = client.post(
        f"/api/meetings/{created['id']}/rsvp",
        json={"status": "accepted"},
        headers=newcomer.headers,
    )
    assert response.status_code == 200
    assert response.json()["my_status"] == "accepted"
