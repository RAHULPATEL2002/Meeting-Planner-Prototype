"""Registration, login and token handling through the HTTP API."""

from __future__ import annotations

import pytest


def test_register_returns_token_and_profile(client):
    response = client.post(
        "/api/auth/register",
        json={
            "email": "New.User@Example.com",
            "password": "correct horse battery",
            "full_name": "  New User  ",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    # Email is normalised to lower case, name is trimmed.
    assert body["user"]["email"] == "new.user@example.com"
    assert body["user"]["full_name"] == "New User"
    assert body["user"]["avatar_url"] is None
    # The password must never come back in a response.
    assert "password" not in body["user"]
    assert "hashed_password" not in body["user"]


def test_duplicate_email_is_rejected(client, alice):
    response = client.post(
        "/api/auth/register",
        json={"email": "ALICE@example.com", "password": "another-password", "full_name": "Fake"},
    )
    assert response.status_code == 409


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("email", "not-an-email"),
        ("password", "short"),
        ("full_name", ""),
        ("full_name", "   "),
    ],
)
def test_register_validation(client, field, value):
    payload = {
        "email": "someone@example.com",
        "password": "correct horse battery",
        "full_name": "Someone",
    }
    payload[field] = value
    assert client.post("/api/auth/register", json=payload).status_code == 422


def test_password_longer_than_72_bytes_is_rejected(client):
    """Multi-byte characters can exceed bcrypt's byte limit within 72 characters."""
    payload = {
        "email": "emoji@example.com",
        "password": "🔒" * 25,  # 25 chars, 100 bytes
        "full_name": "Emoji Fan",
    }
    assert client.post("/api/auth/register", json=payload).status_code == 422


def test_login_succeeds_and_is_case_insensitive(client, alice):
    response = client.post(
        "/api/auth/login", json={"email": "ALICE@EXAMPLE.COM", "password": alice.password}
    )
    assert response.status_code == 200
    assert response.json()["user"]["id"] == alice.id


def test_login_with_wrong_password_is_401(client, alice):
    response = client.post(
        "/api/auth/login", json={"email": alice.email, "password": "wrong-password"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"


def test_login_for_unknown_account_gives_the_same_error(client):
    """Identical wording prevents using login to enumerate registered emails."""
    response = client.post(
        "/api/auth/login", json={"email": "ghost@example.com", "password": "whatever"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"


def test_oauth2_form_login_works_for_swagger(client, alice):
    response = client.post(
        "/api/auth/token",
        data={"username": alice.email, "password": alice.password},
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_me_returns_the_signed_in_user(client, alice):
    response = client.get("/api/auth/me", headers=alice.headers)
    assert response.status_code == 200
    assert response.json()["email"] == alice.email
    assert response.json()["timezone"] == "UTC"


def test_me_requires_a_token(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_rejects_a_bogus_token(client):
    response = client.get("/api/auth/me", headers={"Authorization": "Bearer nonsense"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_token_for_a_deleted_account_is_rejected(client, alice, db_session):
    """A JWT stays cryptographically valid after the user is gone."""
    from app.models import User

    db_session.delete(db_session.get(User, alice.id))
    db_session.commit()

    assert client.get("/api/auth/me", headers=alice.headers).status_code == 401


def test_registering_claims_invites_sent_before_sign_up(client, alice, meeting_payload):
    """Someone invited by email should see the meeting as soon as they join."""
    created = client.post(
        "/api/meetings",
        json=meeting_payload(participants=[{"email": "later@example.com"}]),
        headers=alice.headers,
    )
    assert created.status_code == 201

    late = client.post(
        "/api/auth/register",
        json={
            "email": "later@example.com",
            "password": "correct horse battery",
            "full_name": "Late Joiner",
        },
    ).json()
    headers = {"Authorization": f"Bearer {late['access_token']}"}

    listed = client.get("/api/meetings", headers=headers).json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == created.json()["id"]
    assert listed["items"][0]["my_status"] == "invited"


def test_health_endpoint_is_public(client):
    assert client.get("/api/health").json()["status"] == "ok"
