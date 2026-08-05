"""Profile updates, avatar upload validation, and user search."""

from __future__ import annotations

import io

from PIL import Image

from app.config import settings


def _upload(client, headers, content: bytes, filename="avatar.png", content_type="image/png"):
    return client.post(
        "/api/users/me/avatar",
        headers=headers,
        files={"file": (filename, content, content_type)},
    )


# --------------------------------------------------------------------------
# Profile
# --------------------------------------------------------------------------


def test_update_profile(client, alice):
    response = client.patch(
        "/api/users/me",
        json={"full_name": "Alice A. Adams", "timezone": "Europe/Berlin"},
        headers=alice.headers,
    )
    assert response.status_code == 200
    assert response.json()["full_name"] == "Alice A. Adams"
    assert response.json()["timezone"] == "Europe/Berlin"


def test_partial_update_leaves_other_fields_alone(client, alice):
    response = client.patch(
        "/api/users/me", json={"timezone": "Asia/Kolkata"}, headers=alice.headers
    )
    assert response.json()["full_name"] == "Alice Adams"
    assert response.json()["timezone"] == "Asia/Kolkata"


def test_profile_update_requires_auth(client):
    assert client.patch("/api/users/me", json={"full_name": "X"}).status_code == 401


# --------------------------------------------------------------------------
# Avatar upload
# --------------------------------------------------------------------------


def test_upload_avatar_normalises_to_a_square_jpeg(client, alice, png_bytes):
    response = _upload(client, alice.headers, png_bytes(width=400, height=200))
    assert response.status_code == 200

    avatar_url = response.json()["avatar_url"]
    assert avatar_url.startswith("/static/avatars/")
    assert avatar_url.endswith(".jpg")

    stored = settings.avatar_dir / avatar_url.rsplit("/", 1)[-1]
    assert stored.exists()

    with Image.open(stored) as image:
        # Rectangular input is centre-cropped, never squashed.
        assert image.size == (settings.avatar_edge_px, settings.avatar_edge_px)
        assert image.format == "JPEG"


def test_uploaded_avatar_is_served_over_http(client, alice, png_bytes):
    avatar_url = _upload(client, alice.headers, png_bytes()).json()["avatar_url"]
    served = client.get(avatar_url)
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/jpeg"


def test_upload_rejects_a_non_image_masquerading_as_png(client, alice):
    """A correct Content-Type header is not evidence; the bytes must decode."""
    response = _upload(client, alice.headers, b"#!/bin/sh\nrm -rf /\n")
    assert response.status_code == 400
    assert "not a readable image" in response.json()["detail"].lower()


def test_upload_rejects_disallowed_content_type(client, alice):
    response = _upload(
        client, alice.headers, b"%PDF-1.4", filename="cv.pdf", content_type="application/pdf"
    )
    assert response.status_code == 415


def test_upload_rejects_an_oversized_file(client, alice):
    oversized = b"\x89PNG\r\n\x1a\n" + b"\0" * (settings.avatar_max_bytes + 1)
    assert _upload(client, alice.headers, oversized).status_code == 413


def test_upload_rejects_an_empty_file(client, alice):
    assert _upload(client, alice.headers, b"").status_code == 400


def test_replacing_an_avatar_deletes_the_previous_file(client, alice, png_bytes):
    first = _upload(client, alice.headers, png_bytes(colour="red")).json()["avatar_url"]
    second = _upload(client, alice.headers, png_bytes(colour="blue")).json()["avatar_url"]

    assert first != second
    assert not (settings.avatar_dir / first.rsplit("/", 1)[-1]).exists()
    assert (settings.avatar_dir / second.rsplit("/", 1)[-1]).exists()


def test_delete_avatar_clears_the_field_and_the_file(client, alice, png_bytes):
    avatar_url = _upload(client, alice.headers, png_bytes()).json()["avatar_url"]

    response = client.delete("/api/users/me/avatar", headers=alice.headers)
    assert response.status_code == 200
    assert response.json()["avatar_url"] is None
    assert not (settings.avatar_dir / avatar_url.rsplit("/", 1)[-1]).exists()


def test_avatar_upload_requires_auth(client, png_bytes):
    response = client.post(
        "/api/users/me/avatar", files={"file": ("a.png", png_bytes(), "image/png")}
    )
    assert response.status_code == 401


def test_transparent_png_is_flattened_not_rejected(client, alice):
    buffer = io.BytesIO()
    Image.new("RGBA", (120, 120), (0, 128, 255, 0)).save(buffer, format="PNG")
    assert _upload(client, alice.headers, buffer.getvalue()).status_code == 200


def test_avatar_appears_on_meeting_participants(client, alice, bob, png_bytes, meeting_payload):
    """The point of avatars: they show up next to people on a meeting."""
    _upload(client, bob.headers, png_bytes())
    meeting = client.post(
        "/api/meetings",
        json=meeting_payload(participants=[{"email": bob.email}]),
        headers=alice.headers,
    ).json()

    bob_row = next(p for p in meeting["participants"] if p["email"] == bob.email)
    assert bob_row["user"]["avatar_url"].endswith(".jpg")
    assert bob_row["name"] == "Bob Brown"


# --------------------------------------------------------------------------
# User search
# --------------------------------------------------------------------------


def test_search_finds_users_by_name_or_email(client, alice, bob):
    by_name = client.get("/api/users", params={"q": "bob b"}, headers=alice.headers).json()
    assert [u["email"] for u in by_name] == [bob.email]

    by_email = client.get("/api/users", params={"q": "BOB@ex"}, headers=alice.headers).json()
    assert [u["email"] for u in by_email] == [bob.email]


def test_search_excludes_the_caller(client, alice, bob):
    results = client.get("/api/users", params={"q": "example.com"}, headers=alice.headers).json()
    assert alice.email not in [u["email"] for u in results]


def test_search_requires_auth(client):
    assert client.get("/api/users", params={"q": "a"}).status_code == 401
