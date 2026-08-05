"""Profile management, avatar upload, and the invitee lookup used by the UI."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Query, UploadFile, status
from sqlalchemy import or_, select

from app.deps import CurrentUser, DbSession
from app.models import User
from app.schemas import UserMe, UserPublic, UserUpdate
from app.services.avatars import delete_avatar, store_avatar

router = APIRouter(prefix="/users", tags=["users"])


@router.patch("/me", response_model=UserMe, summary="Update your own profile")
def update_me(payload: UserUpdate, current_user: CurrentUser, db: DbSession) -> User:
    # exclude_unset distinguishes "field omitted" from "field set to null".
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post(
    "/me/avatar",
    response_model=UserMe,
    status_code=status.HTTP_200_OK,
    summary="Upload or replace your avatar",
)
async def upload_avatar(
    current_user: CurrentUser,
    db: DbSession,
    file: Annotated[UploadFile, File(description="JPEG, PNG, WebP or GIF, max 2 MB")],
) -> User:
    """Store a normalised 256x256 JPEG and point the account at it.

    The previous file is deleted only *after* the new one is safely written, so a
    failed upload never leaves the user without an avatar.
    """
    previous = current_user.avatar_filename
    current_user.avatar_filename = await store_avatar(file)
    db.commit()
    db.refresh(current_user)

    if previous and previous != current_user.avatar_filename:
        delete_avatar(previous)
    return current_user


@router.delete("/me/avatar", response_model=UserMe, summary="Remove your avatar")
def remove_avatar(current_user: CurrentUser, db: DbSession) -> User:
    previous = current_user.avatar_filename
    current_user.avatar_filename = None
    db.commit()
    db.refresh(current_user)
    delete_avatar(previous)
    return current_user


@router.get(
    "",
    response_model=list[UserPublic],
    summary="Search registered users (invitee autocomplete)",
)
def search_users(
    current_user: CurrentUser,
    db: DbSession,
    q: Annotated[str, Query(min_length=1, max_length=120, description="Name or email fragment")],
    limit: Annotated[int, Query(ge=1, le=25)] = 10,
) -> list[User]:
    """Substring search over name and email, excluding the caller.

    Requires authentication: an open user-directory endpoint would let anyone
    harvest the address book.
    """
    pattern = f"%{q.strip().lower()}%"
    rows = db.execute(
        select(User)
        .where(
            User.id != current_user.id,
            or_(User.email.like(pattern), User.full_name.ilike(pattern)),
        )
        .order_by(User.full_name.asc())
        .limit(limit)
    ).scalars().all()
    return list(rows)
