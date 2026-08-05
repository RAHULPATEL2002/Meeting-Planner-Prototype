"""SQLAlchemy ORM models.

Domain summary
--------------
``User``         an account that can sign in, owns a profile + avatar.
``Meeting``      a scheduled block of time owned by exactly one organiser.
``Participant``  the association between a meeting and an *email address*.
                 If that email belongs to a registered ``User`` we link the row
                 to the account so the UI can show a real name and avatar;
                 otherwise the invite is still valid as an "external guest".
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.database import Base


class ParticipantStatus(str, enum.Enum):
    """RSVP state for one participant of one meeting."""

    INVITED = "invited"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    TENTATIVE = "tentative"


def _utcnow() -> datetime:
    """Naive UTC 'now'.

    SQLite has no timezone-aware storage, so the whole application stores naive
    datetimes that are UTC *by convention* and re-attaches the UTC tzinfo at the
    serialisation boundary (see ``app/schemas.py``).
    """
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Stored lower-cased so lookups are case-insensitive without a functional index.
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    # Only the filename is stored; the URL is derived, so moving the static
    # mount point does not require a data migration.
    avatar_filename: Mapped[str | None] = mapped_column(String(255), default=None)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, server_default=func.current_timestamp(), nullable=False
    )

    organized_meetings: Mapped[list[Meeting]] = relationship(
        back_populates="organizer",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    participations: Mapped[list[Participant]] = relationship(back_populates="user")

    @property
    def avatar_url(self) -> str | None:
        """Public URL of the avatar, or ``None`` when the user has not set one."""
        if not self.avatar_filename:
            return None
        return f"{settings.static_url_prefix}/avatars/{self.avatar_filename}"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User id={self.id} email={self.email!r}>"


class Meeting(Base):
    __tablename__ = "meetings"
    __table_args__ = (
        # Belt and braces: the API validates this too, but the DB is the last
        # line of defence against a bad write from a future code path.
        CheckConstraint("ends_at > starts_at", name="ck_meetings_end_after_start"),
        Index("ix_meetings_window", "starts_at", "ends_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    # Free text: a room name, an address, or a video-call link.
    location: Mapped[str | None] = mapped_column(String(300), default=None)
    starts_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    organizer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )

    organizer: Mapped[User] = relationship(back_populates="organized_meetings", lazy="joined")
    participants: Mapped[list[Participant]] = relationship(
        back_populates="meeting",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Participant.id",
    )

    @property
    def duration_minutes(self) -> int:
        return int((self.ends_at - self.starts_at).total_seconds() // 60)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Meeting id={self.id} title={self.title!r}>"


class Participant(Base):
    __tablename__ = "participants"
    __table_args__ = (
        # One invite per email per meeting; the DB enforces it so two concurrent
        # requests cannot both insert the same guest.
        UniqueConstraint("meeting_id", "email", name="uq_participants_meeting_email"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    # Populated for guests without an account; registered users render via ``user``.
    display_name: Mapped[str | None] = mapped_column(String(120), default=None)
    # Nullable on purpose: you can invite someone who has not signed up yet.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )
    status: Mapped[ParticipantStatus] = mapped_column(
        # native_enum=False -> stored as VARCHAR, which keeps SQLite happy and
        # lets us add new statuses without an ALTER TYPE.
        SAEnum(
            ParticipantStatus,
            native_enum=False,
            length=16,
            values_callable=lambda e: [member.value for member in e],
        ),
        default=ParticipantStatus.INVITED,
        nullable=False,
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    meeting: Mapped[Meeting] = relationship(back_populates="participants")
    user: Mapped[User | None] = relationship(back_populates="participations", lazy="joined")

    @property
    def name(self) -> str:
        """Best available human-readable name for this participant."""
        if self.user is not None:
            return self.user.full_name
        return self.display_name or self.email.split("@")[0]

    @property
    def is_registered(self) -> bool:
        return self.user_id is not None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Participant meeting={self.meeting_id} "
            f"email={self.email!r} status={self.status.value}>"
        )
