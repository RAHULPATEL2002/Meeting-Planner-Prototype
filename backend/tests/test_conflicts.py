"""Scheduling-conflict detection — the trickiest bit of arithmetic in the app."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.time_utils import overlap_minutes, to_utc_naive, utcnow
from tests.conftest import iso

BASE = datetime(2030, 6, 1, 9, 0)


def at(hour: float, minutes: int = 0) -> str:
    return iso(BASE + timedelta(hours=hour, minutes=minutes))


# --------------------------------------------------------------------------
# Pure functions
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ((0, 60), (30, 90), 30),   # partial overlap
        ((0, 60), (0, 60), 60),    # identical
        ((0, 120), (30, 60), 30),  # fully contained
        ((0, 60), (60, 120), 0),   # back-to-back -> not a conflict
        ((0, 60), (90, 120), 0),   # disjoint
        ((60, 120), (0, 60), 0),   # back-to-back, reversed
    ],
)
def test_overlap_minutes(a, b, expected):
    start = datetime(2030, 1, 1, 0, 0)
    assert (
        overlap_minutes(
            start + timedelta(minutes=a[0]),
            start + timedelta(minutes=a[1]),
            start + timedelta(minutes=b[0]),
            start + timedelta(minutes=b[1]),
        )
        == expected
    )


def test_to_utc_naive_converts_offsets():
    assert to_utc_naive(datetime.fromisoformat("2030-03-01T09:00:00+02:00")) == datetime(
        2030, 3, 1, 7, 0
    )


def test_to_utc_naive_treats_naive_input_as_utc():
    assert to_utc_naive(datetime(2030, 3, 1, 9, 0)) == datetime(2030, 3, 1, 9, 0)


# --------------------------------------------------------------------------
# Through the API
# --------------------------------------------------------------------------


def _create(client, user, title, start, end, participants=None):
    return client.post(
        "/api/meetings",
        json={
            "title": title,
            "starts_at": start,
            "ends_at": end,
            "participants": participants or [],
        },
        headers=user.headers,
    ).json()


def test_detail_reports_an_overlapping_meeting(client, alice):
    first = _create(client, alice, "Design review", at(0), at(1))
    second = _create(client, alice, "Standup", at(0, 30), at(1, 30))

    detail = client.get(f"/api/meetings/{second['id']}", headers=alice.headers).json()
    assert len(detail["conflicts"]) == 1
    assert detail["conflicts"][0]["id"] == first["id"]
    assert detail["conflicts"][0]["title"] == "Design review"
    assert detail["conflicts"][0]["overlap_minutes"] == 30


def test_back_to_back_meetings_are_not_conflicts(client, alice):
    _create(client, alice, "First", at(0), at(1))
    second = _create(client, alice, "Second", at(1), at(2))

    detail = client.get(f"/api/meetings/{second['id']}", headers=alice.headers).json()
    assert detail["conflicts"] == []


def test_a_meeting_never_conflicts_with_itself(client, alice):
    meeting = _create(client, alice, "Only one", at(0), at(1))
    detail = client.get(f"/api/meetings/{meeting['id']}", headers=alice.headers).json()
    assert detail["conflicts"] == []


def test_conflicts_are_personal_to_the_viewer(client, alice, bob):
    """Alice being double-booked is not Bob's problem."""
    _create(client, alice, "Alice only", at(0), at(1))
    shared = _create(client, alice, "Shared", at(0, 30), at(1, 30), [{"email": bob.email}])

    alice_view = client.get(f"/api/meetings/{shared['id']}", headers=alice.headers).json()
    bob_view = client.get(f"/api/meetings/{shared['id']}", headers=bob.headers).json()

    assert len(alice_view["conflicts"]) == 1
    assert bob_view["conflicts"] == []


def test_invitees_conflicts_include_meetings_they_were_invited_to(client, alice, bob):
    _create(client, alice, "Busy elsewhere", at(0), at(1), [{"email": bob.email}])
    shared = _create(client, alice, "Shared", at(0, 30), at(1, 30), [{"email": bob.email}])

    bob_view = client.get(f"/api/meetings/{shared['id']}", headers=bob.headers).json()
    assert [c["title"] for c in bob_view["conflicts"]] == ["Busy elsewhere"]


def test_conflict_preview_before_the_meeting_exists(client, alice):
    _create(client, alice, "Existing", at(0), at(1))

    response = client.get(
        "/api/meetings/conflicts",
        params={"starts_at": at(0, 30), "ends_at": at(1, 30)},
        headers=alice.headers,
    )
    assert response.status_code == 200
    assert [c["title"] for c in response.json()] == ["Existing"]


def test_conflict_preview_can_exclude_the_meeting_being_edited(client, alice):
    meeting = _create(client, alice, "Existing", at(0), at(1))

    response = client.get(
        "/api/meetings/conflicts",
        params={"starts_at": at(0), "ends_at": at(1), "exclude_meeting_id": meeting["id"]},
        headers=alice.headers,
    )
    assert response.json() == []


def test_conflict_preview_validates_its_input(client, alice):
    bad_format = client.get(
        "/api/meetings/conflicts",
        params={"starts_at": "yesterday", "ends_at": at(1)},
        headers=alice.headers,
    )
    assert bad_format.status_code == 422

    reversed_window = client.get(
        "/api/meetings/conflicts",
        params={"starts_at": at(2), "ends_at": at(1)},
        headers=alice.headers,
    )
    assert reversed_window.status_code == 422


def test_conflict_preview_requires_auth(client):
    response = client.get(
        "/api/meetings/conflicts", params={"starts_at": at(0), "ends_at": at(1)}
    )
    assert response.status_code == 401


def test_conflicts_route_is_not_shadowed_by_the_id_route(client, alice):
    """`/meetings/conflicts` must not be parsed as `/meetings/{meeting_id}`."""
    response = client.get(
        "/api/meetings/conflicts",
        params={"starts_at": iso(utcnow()), "ends_at": iso(utcnow() + timedelta(hours=1))},
        headers=alice.headers,
    )
    assert response.status_code == 200
