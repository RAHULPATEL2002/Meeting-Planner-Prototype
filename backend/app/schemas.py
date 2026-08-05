"""Pydantic v2 schemas — the API's public contract.

ORM models and API schemas are kept separate on purpose: the wire format can
evolve (add ``avatar_url``, hide ``hashed_password``) without touching the
database, and every request is validated before a router ever sees it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    PlainSerializer,
    field_validator,
    model_validator,
)

from app.config import settings
from app.models import ParticipantStatus
from app.security import BCRYPT_MAX_PASSWORD_BYTES
from app.time_utils import as_utc, to_utc_naive

# --------------------------------------------------------------------------
# Reusable annotated types
# --------------------------------------------------------------------------

#: Datetimes leaving the API are always rendered as ``2026-08-05T09:00:00Z``.
UtcDateTime = Annotated[
    datetime,
    PlainSerializer(
        lambda value: as_utc(value).isoformat().replace("+00:00", "Z"),
        return_type=str,
        when_used="json",
    ),
]

#: Datetimes entering the API are normalised to naive UTC for storage.
InboundDateTime = Annotated[datetime, AfterValidator(to_utc_naive)]

Password = Annotated[
    str,
    Field(
        min_length=8,
        max_length=BCRYPT_MAX_PASSWORD_BYTES,
        description="8-72 characters. Stored only as a bcrypt hash.",
    ),
]


def _normalise_email(value: str) -> str:
    """Emails are compared and stored case-insensitively."""
    return value.strip().lower()


NormalisedEmail = Annotated[EmailStr, AfterValidator(_normalise_email)]


class ApiModel(BaseModel):
    """Base for response models that are built straight from ORM objects."""

    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------
# Users & auth
# --------------------------------------------------------------------------


class UserCreate(BaseModel):
    email: NormalisedEmail
    full_name: str = Field(min_length=1, max_length=120)
    password: Password
    timezone: str = Field(default="UTC", max_length=64)

    @field_validator("full_name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Full name cannot be blank")
        return cleaned

    @field_validator("password")
    @classmethod
    def _password_bytes_fit_bcrypt(cls, value: str) -> str:
        # max_length counts characters; bcrypt counts bytes. A 40-character
        # emoji password can still blow the 72-byte limit.
        if len(value.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES:
            raise ValueError(
                f"Password must be at most {BCRYPT_MAX_PASSWORD_BYTES} bytes when UTF-8 encoded"
            )
        return value


class UserUpdate(BaseModel):
    """Partial update of the signed-in user's own profile."""

    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    timezone: str | None = Field(default=None, max_length=64)


class UserPublic(ApiModel):
    """What any authenticated caller may see about another user."""

    id: int
    email: EmailStr
    full_name: str
    # Derived from ``User.avatar_filename`` by a property on the ORM model.
    avatar_url: str | None = None


class UserMe(UserPublic):
    """Adds fields only the owner should see."""

    timezone: str
    created_at: UtcDateTime


class LoginRequest(BaseModel):
    email: NormalisedEmail
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Token lifetime in seconds.")
    user: UserMe


# --------------------------------------------------------------------------
# Participants
# --------------------------------------------------------------------------


class ParticipantCreate(BaseModel):
    email: NormalisedEmail
    display_name: str | None = Field(default=None, max_length=120)


class ParticipantOut(ApiModel):
    id: int
    email: EmailStr
    status: ParticipantStatus
    responded_at: UtcDateTime | None = None
    #: Resolved account, when the invited email belongs to a registered user.
    user: UserPublic | None = None
    #: Best display name available (account name, given name, or email local part).
    name: str
    is_registered: bool
    is_organizer: bool = False


class RsvpRequest(BaseModel):
    # "invited" is the initial state, not something a participant can choose.
    status: Literal[
        ParticipantStatus.ACCEPTED,
        ParticipantStatus.DECLINED,
        ParticipantStatus.TENTATIVE,
    ]


class ResponseSummary(BaseModel):
    """Aggregate RSVP counts, so the UI does not have to compute them."""

    total: int = 0
    accepted: int = 0
    declined: int = 0
    tentative: int = 0
    invited: int = 0


# --------------------------------------------------------------------------
# Meetings
# --------------------------------------------------------------------------


def _validate_window(starts_at: datetime, ends_at: datetime) -> None:
    """Shared business rules for a meeting's time window."""
    if ends_at <= starts_at:
        raise ValueError("Meeting must end after it starts")
    duration = ends_at - starts_at
    if duration < timedelta(minutes=settings.meeting_min_duration_minutes):
        raise ValueError(
            f"Meeting must last at least {settings.meeting_min_duration_minutes} minutes"
        )
    if duration > timedelta(minutes=settings.meeting_max_duration_minutes):
        raise ValueError(
            "Meeting cannot be longer than "
            f"{settings.meeting_max_duration_minutes // (24 * 60)} days"
        )


class MeetingCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    location: str | None = Field(default=None, max_length=300)
    starts_at: InboundDateTime
    ends_at: InboundDateTime
    participants: list[ParticipantCreate] = Field(
        default_factory=list,
        max_length=settings.meeting_max_participants,
        description="Invitees. The organiser is added automatically.",
    )

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 3:
            raise ValueError("Title must be at least 3 characters")
        return cleaned

    @model_validator(mode="after")
    def _check_window(self) -> MeetingCreate:
        _validate_window(self.starts_at, self.ends_at)
        return self

    @model_validator(mode="after")
    def _reject_duplicate_invitees(self) -> MeetingCreate:
        emails = [p.email for p in self.participants]
        if len(emails) != len(set(emails)):
            raise ValueError("The same email was invited more than once")
        return self


class MeetingUpdate(BaseModel):
    """Partial update. Only the organiser may call it."""

    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    location: str | None = Field(default=None, max_length=300)
    starts_at: InboundDateTime | None = None
    ends_at: InboundDateTime | None = None

    @model_validator(mode="after")
    def _reject_empty_payload(self) -> MeetingUpdate:
        if not self.model_fields_set:
            raise ValueError("No fields to update")
        return self

    # NOTE: start/end are cross-checked in the service layer, because a partial
    # update may change only one of the two and must be validated against the
    # value already stored.


class MeetingConflict(BaseModel):
    """Another meeting on the viewer's calendar that overlaps this one."""

    id: int
    title: str
    starts_at: UtcDateTime
    ends_at: UtcDateTime
    overlap_minutes: int


class MeetingSummary(ApiModel):
    """Row shape for the meetings list."""

    id: int
    title: str
    location: str | None = None
    starts_at: UtcDateTime
    ends_at: UtcDateTime
    duration_minutes: int
    organizer: UserPublic
    participant_count: int
    #: The viewer's own RSVP state (``None`` if they are only the organiser view).
    my_status: ParticipantStatus | None = None
    is_organizer: bool = False


class MeetingDetail(MeetingSummary):
    """Everything the detail page needs, in one round trip."""

    description: str | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime
    participants: list[ParticipantOut] = Field(default_factory=list)
    response_summary: ResponseSummary
    #: Overlapping meetings *for the current viewer only*.
    conflicts: list[MeetingConflict] = Field(default_factory=list)
    ics_url: str


class MeetingListResponse(BaseModel):
    items: list[MeetingSummary]
    total: int


class Message(BaseModel):
    """Generic acknowledgement body."""

    detail: str
