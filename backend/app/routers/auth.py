"""Sign-up, sign-in and 'who am I' endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select, update

from app.deps import CurrentUser, DbSession
from app.models import Participant, User
from app.schemas import LoginRequest, TokenResponse, UserCreate, UserMe
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

#: A real bcrypt hash of a random string, compared against when the email is
#: unknown so that failed logins cost the same whether or not the account exists.
_DUMMY_HASH = hash_password("not-a-real-password-timing-equaliser")


def _issue_token(user: User) -> TokenResponse:
    token, expires_in = create_access_token(user.id)
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserMe.model_validate(user),
    )


def _claim_pending_invites(db: DbSession, user: User) -> None:
    """Attach a brand-new account to invites that were sent to its address.

    Without this, someone invited before they signed up would see an empty
    dashboard: the participant row exists but points at no account.
    """
    db.execute(
        update(Participant)
        .where(Participant.email == user.email, Participant.user_id.is_(None))
        .values(user_id=user.id)
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and sign in",
)
def register(payload: UserCreate, db: DbSession) -> TokenResponse:
    existing = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if existing is not None:
        # Note: this is an account-enumeration trade-off. For a prototype the
        # clear error message is worth more than the marginal privacy gain of a
        # generic "registration failed".
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists",
        )

    user = User(
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        timezone=payload.timezone,
    )
    db.add(user)
    db.flush()  # assigns user.id without ending the transaction
    _claim_pending_invites(db, user)
    db.commit()
    db.refresh(user)

    return _issue_token(user)


def _authenticate(db: DbSession, email: str, password: str) -> User:
    """Look up an account and check its password, or raise 401."""
    user = db.execute(
        select(User).where(User.email == email.strip().lower())
    ).scalar_one_or_none()

    # Same response for "no such user" and "wrong password" so the endpoint
    # cannot be used to discover which emails are registered. verify_password is
    # still called on a dummy hash when the user is missing, so the two paths
    # take a comparable amount of time.
    if user is None:
        verify_password(password, _DUMMY_HASH)
        raise _invalid_credentials()
    if not verify_password(password, user.hashed_password):
        raise _invalid_credentials()
    return user


def _invalid_credentials() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect email or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/login", response_model=TokenResponse, summary="Sign in with email + password")
def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    return _issue_token(_authenticate(db, payload.email, payload.password))


@router.post(
    "/token",
    response_model=TokenResponse,
    include_in_schema=True,
    summary="OAuth2 password flow (used by the Swagger 'Authorize' button)",
)
def login_form(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
) -> TokenResponse:
    """Form-encoded variant of ``/login``.

    Exists purely so the interactive docs at ``/docs`` can authenticate; the
    Angular client uses the JSON endpoint above. ``username`` carries the email.
    """
    return _issue_token(_authenticate(db, form_data.username, form_data.password))


@router.get("/me", response_model=UserMe, summary="Current signed-in user")
def read_me(current_user: CurrentUser) -> User:
    return current_user
