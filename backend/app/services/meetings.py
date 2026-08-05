"""Meeting domain logic: creation, access control, conflicts, serialisation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models import Meeting, Participant, ParticipantStatus, User
from app.schemas import (
    MeetingConflict,
    MeetingCreate,
    MeetingDetail,
    MeetingSummary,
    MeetingUpdate,
    ParticipantOut,
    ResponseSummary,
    UserPublic,
)
from app.time_utils import overlap_minutes, utcnow

Scope = Literal["upcoming", "past", "all"]


# --------------------------------------------------------------------------
# Queries & access control
# --------------------------------------------------------------------------


def _involves(user: User):
    """SQL predicate: ``user`` organises the meeting or is on the invite list.

    Participants are matched by account id *and* by email, so an invite sent
    before the guest signed up still resolves once they do.
    """
    return or_(
        Meeting.organizer_id == user.id,
        Meeting.participants.any(
            or_(Participant.user_id == user.id, Participant.email == user.email)
        ),
    )


def _base_query():
    # Eager-load in one round trip; the list endpoint renders organiser avatars
    # and participant counts, which would otherwise be N+1 queries.
    return select(Meeting).options(
        selectinload(Meeting.participants).selectinload(Participant.user),
        selectinload(Meeting.organizer),
    )


def list_meetings(db: Session, user: User, scope: Scope = "upcoming") -> list[Meeting]:
    """Meetings the user can see, filtered by time and sorted sensibly."""
    now = utcnow()
    query = _base_query().where(_involves(user))

    if scope == "upcoming":
        # A meeting still counts as "upcoming" while it is in progress.
        query = query.where(Meeting.ends_at >= now).order_by(Meeting.starts_at.asc())
    elif scope == "past":
        query = query.where(Meeting.ends_at < now).order_by(Meeting.starts_at.desc())
    else:
        query = query.order_by(Meeting.starts_at.desc())

    return list(db.execute(query).unique().scalars().all())


def get_visible_meeting(db: Session, meeting_id: int, user: User) -> Meeting:
    """Fetch a meeting the user is allowed to see, or raise 404.

    404 rather than 403 for meetings that exist but are not theirs: a different
    status code would confirm the meeting's existence to a stranger.
    """
    meeting = db.execute(
        _base_query().where(Meeting.id == meeting_id, _involves(user))
    ).unique().scalar_one_or_none()

    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    return meeting


def require_organizer(meeting: Meeting, user: User) -> None:
    if meeting.organizer_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the organiser can modify this meeting",
        )


# --------------------------------------------------------------------------
# Mutations
# --------------------------------------------------------------------------


def _link_account(db: Session, email: str) -> User | None:
    """Find the registered account for an invited email address, if any."""
    return db.execute(select(User).where(User.email == email)).scalar_one_or_none()


def build_participant(
    db: Session,
    email: str,
    display_name: str | None = None,
    status_: ParticipantStatus = ParticipantStatus.INVITED,
) -> Participant:
    account = _link_account(db, email)
    return Participant(
        email=email,
        display_name=display_name,
        user_id=account.id if account else None,
        status=status_,
        responded_at=utcnow() if status_ is not ParticipantStatus.INVITED else None,
    )


def create_meeting(db: Session, organizer: User, payload: MeetingCreate) -> Meeting:
    """Persist a new meeting plus its invite list.

    The organiser is always participant #1 with an implicit ``accepted`` RSVP —
    they are, after all, going to their own meeting.
    """
    meeting = Meeting(
        title=payload.title,
        description=payload.description,
        location=payload.location,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        organizer_id=organizer.id,
    )

    meeting.participants.append(
        Participant(
            email=organizer.email,
            user_id=organizer.id,
            status=ParticipantStatus.ACCEPTED,
            responded_at=utcnow(),
        )
    )

    for invitee in payload.participants:
        if invitee.email == organizer.email:
            # Organisers invite themselves by accident all the time; the unique
            # constraint would reject it, so silently skip instead.
            continue
        meeting.participants.append(
            build_participant(db, invitee.email, invitee.display_name)
        )

    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    return meeting


def update_meeting(db: Session, meeting: Meeting, payload: MeetingUpdate) -> Meeting:
    """Apply a partial update, validating the *resulting* time window."""
    data = payload.model_dump(exclude_unset=True)

    starts_at = data.get("starts_at", meeting.starts_at)
    ends_at = data.get("ends_at", meeting.ends_at)
    _assert_valid_window(starts_at, ends_at)

    for field, value in data.items():
        setattr(meeting, field, value)

    db.commit()
    db.refresh(meeting)
    return meeting


def _assert_valid_window(starts_at, ends_at) -> None:
    """Time-window rules, raised as 422 to match pydantic's create-time errors."""
    problems: list[str] = []
    if ends_at <= starts_at:
        problems.append("Meeting must end after it starts")
    else:
        duration = ends_at - starts_at
        if duration < timedelta(minutes=settings.meeting_min_duration_minutes):
            problems.append(
                f"Meeting must last at least {settings.meeting_min_duration_minutes} minutes"
            )
        if duration > timedelta(minutes=settings.meeting_max_duration_minutes):
            problems.append(
                f"Meeting cannot be longer than "
                f"{settings.meeting_max_duration_minutes // (24 * 60)} days"
            )
    if problems:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="; ".join(problems)
        )


def add_participant(
    db: Session, meeting: Meeting, email: str, display_name: str | None
) -> Participant:
    if any(p.email == email for p in meeting.participants):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That email is already invited to this meeting",
        )
    if len(meeting.participants) >= settings.meeting_max_participants:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"A meeting can have at most {settings.meeting_max_participants} participants",
        )

    participant = build_participant(db, email, display_name)
    participant.meeting_id = meeting.id
    db.add(participant)
    db.commit()
    db.refresh(participant)
    return participant


def remove_participant(db: Session, meeting: Meeting, participant_id: int) -> None:
    participant = next((p for p in meeting.participants if p.id == participant_id), None)
    if participant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Participant not found")
    if participant.user_id == meeting.organizer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The organiser cannot be removed from their own meeting",
        )
    db.delete(participant)
    db.commit()


def set_rsvp(
    db: Session, meeting: Meeting, user: User, new_status: ParticipantStatus
) -> Participant:
    """Record the current user's response. Only invitees may respond."""
    participant = find_viewer_participant(meeting, user)
    if participant is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a participant of this meeting",
        )

    # Late-bind the account to the invite the first time they interact with it.
    if participant.user_id is None:
        participant.user_id = user.id

    participant.status = new_status
    participant.responded_at = utcnow()
    db.commit()
    db.refresh(participant)
    return participant


# --------------------------------------------------------------------------
# Derived data
# --------------------------------------------------------------------------


def find_viewer_participant(meeting: Meeting, user: User) -> Participant | None:
    """The viewer's own row on this meeting, matched by account or email."""
    for participant in meeting.participants:
        if participant.user_id == user.id or participant.email == user.email:
            return participant
    return None


def summarise_responses(participants: Sequence[Participant]) -> ResponseSummary:
    summary = ResponseSummary(total=len(participants))
    for participant in participants:
        setattr(summary, participant.status.value, getattr(summary, participant.status.value) + 1)
    return summary


def find_conflicts(
    db: Session, user: User, starts_at, ends_at, exclude_meeting_id: int | None = None
) -> list[MeetingConflict]:
    """Other meetings on the viewer's calendar that overlap ``[starts_at, ends_at)``.

    The overlap test is ``existing.starts_at < new_end AND existing.ends_at >
    new_start`` — the standard half-open interval intersection, so meetings that
    merely touch (10:00-11:00 and 11:00-12:00) are not reported.
    """
    query = (
        select(Meeting)
        .where(
            _involves(user),
            Meeting.starts_at < ends_at,
            Meeting.ends_at > starts_at,
        )
        .order_by(Meeting.starts_at.asc())
    )
    if exclude_meeting_id is not None:
        query = query.where(Meeting.id != exclude_meeting_id)

    return [
        MeetingConflict(
            id=other.id,
            title=other.title,
            starts_at=other.starts_at,
            ends_at=other.ends_at,
            overlap_minutes=overlap_minutes(
                starts_at, ends_at, other.starts_at, other.ends_at
            ),
        )
        for other in db.execute(query).unique().scalars().all()
    ]


def serialise_participant(participant: Participant, meeting: Meeting) -> ParticipantOut:
    return ParticipantOut(
        id=participant.id,
        email=participant.email,
        status=participant.status,
        responded_at=participant.responded_at,
        user=UserPublic.model_validate(participant.user) if participant.user else None,
        name=participant.name,
        is_registered=participant.is_registered,
        is_organizer=participant.user_id == meeting.organizer_id,
    )


def serialise_summary(meeting: Meeting, viewer: User) -> MeetingSummary:
    viewer_participant = find_viewer_participant(meeting, viewer)
    return MeetingSummary(
        id=meeting.id,
        title=meeting.title,
        location=meeting.location,
        starts_at=meeting.starts_at,
        ends_at=meeting.ends_at,
        duration_minutes=meeting.duration_minutes,
        organizer=UserPublic.model_validate(meeting.organizer),
        participant_count=len(meeting.participants),
        my_status=viewer_participant.status if viewer_participant else None,
        is_organizer=meeting.organizer_id == viewer.id,
    )


def serialise_detail(db: Session, meeting: Meeting, viewer: User) -> MeetingDetail:
    """Build the full detail payload, including viewer-specific fields.

    ``conflicts`` are intentionally personal: what matters is whether *you* are
    double-booked, not whether some other invitee is.
    """
    summary = serialise_summary(meeting, viewer)
    return MeetingDetail(
        **summary.model_dump(),
        description=meeting.description,
        created_at=meeting.created_at,
        updated_at=meeting.updated_at,
        participants=[serialise_participant(p, meeting) for p in meeting.participants],
        response_summary=summarise_responses(meeting.participants),
        conflicts=find_conflicts(
            db, viewer, meeting.starts_at, meeting.ends_at, exclude_meeting_id=meeting.id
        ),
        ics_url=f"{settings.api_prefix}/meetings/{meeting.id}/calendar.ics",
    )
