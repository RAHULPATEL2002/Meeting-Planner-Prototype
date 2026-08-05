"""Shared FastAPI dependencies (authentication, current user lookup)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User
from app.security import TokenError, decode_access_token

# ``tokenUrl`` only affects the OpenAPI document: it tells Swagger UI which
# endpoint its "Authorize" button should post credentials to.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_prefix}/auth/token")

CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: DbSession,
) -> User:
    """Resolve the bearer token to a live ``User`` row.

    The database lookup is not optional: a token stays cryptographically valid
    until it expires, so a deleted account must be rejected here.
    """
    try:
        user_id = decode_access_token(token)
    except TokenError as exc:
        raise CREDENTIALS_EXCEPTION from exc

    user = db.get(User, user_id)
    if user is None:
        raise CREDENTIALS_EXCEPTION
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
