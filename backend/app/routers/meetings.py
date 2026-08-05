"""Meeting CRUD, invitations, RSVPs, conflict preview and calendar export."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.deps import CurrentUser, DbSession
from app.schemas import (
    MeetingConflict,
    MeetingCreate,
    MeetingDetail,
    MeetingListResponse,
    MeetingUpdate,
    ParticipantCreate,
    ParticipantOut,
    RsvpRequest,
)
from app.services import meetings as service
from app.services.ics import meeting_to_ics
from app.time_utils import to_utc_naive

router = APIRouter(prefix="/meetings", tags=["meetings"])


@router.post(
    "",
    response_model=MeetingDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a meeting",
)
def create_meeting(
    payload: MeetingCreate, current_user: CurrentUser, db: DbSession
) -> MeetingDetail:
    """Create a meeting and return the full detail view.

    Returning the detail payload (not just an id) means the client can navigate
    straight to the meeting page without a second request — and the user
    immediately sees participants, duration and any scheduling conflicts.
    """
    meeting = service.create_meeting(db, current_user, payload)
    return service.serialise_detail(db, meeting, current_user)


@router.get("", response_model=MeetingListResponse, summary="List meetings you are part of")
def list_meetings(
    current_user: CurrentUser,
    db: DbSession,
    scope: Annotated[service.Scope, Query(description="upcoming | past | all")] = "upcoming",
) -> MeetingListResponse:
    rows = service.list_meetings(db, current_user, scope)
    return MeetingListResponse(
        items=[service.serialise_summary(m, current_user) for m in rows],
        total=len(rows),
    )


@router.get("/conflicts", response_model=list[MeetingConflict], summary="Preview clashes")
def preview_conflicts(
    current_user: CurrentUser,
    db: DbSession,
    starts_at: Annotated[str, Query(description="ISO-8601 start, e.g. 2026-08-10T09:00:00Z")],
    ends_at: Annotated[str, Query(description="ISO-8601 end")],
    exclude_meeting_id: Annotated[int | None, Query()] = None,
) -> list[MeetingConflict]:
    """Check a proposed time window *before* the meeting exists.

    Declared above ``/{meeting_id}`` because FastAPI matches routes in
    definition order and ``conflicts`` would otherwise be parsed as an id.
    """
    try:
        start = to_utc_naive(datetime.fromisoformat(starts_at.replace("Z", "+00:00")))
        end = to_utc_naive(datetime.fromisoformat(ends_at.replace("Z", "+00:00")))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="starts_at and ends_at must be ISO-8601 timestamps",
        ) from exc

    if end <= start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="ends_at must be after starts_at",
        )

    return service.find_conflicts(db, current_user, start, end, exclude_meeting_id)


@router.get("/{meeting_id}", response_model=MeetingDetail, summary="Meeting detail")
def get_meeting(meeting_id: int, current_user: CurrentUser, db: DbSession) -> MeetingDetail:
    meeting = service.get_visible_meeting(db, meeting_id, current_user)
    return service.serialise_detail(db, meeting, current_user)


@router.patch("/{meeting_id}", response_model=MeetingDetail, summary="Update a meeting")
def update_meeting(
    meeting_id: int, payload: MeetingUpdate, current_user: CurrentUser, db: DbSession
) -> MeetingDetail:
    meeting = service.get_visible_meeting(db, meeting_id, current_user)
    service.require_organizer(meeting, current_user)
    meeting = service.update_meeting(db, meeting, payload)
    return service.serialise_detail(db, meeting, current_user)


@router.delete(
    "/{meeting_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel a meeting",
)
def delete_meeting(meeting_id: int, current_user: CurrentUser, db: DbSession) -> Response:
    meeting = service.get_visible_meeting(db, meeting_id, current_user)
    service.require_organizer(meeting, current_user)
    db.delete(meeting)  # participants cascade
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{meeting_id}/participants",
    response_model=ParticipantOut,
    status_code=status.HTTP_201_CREATED,
    summary="Invite someone",
)
def add_participant(
    meeting_id: int, payload: ParticipantCreate, current_user: CurrentUser, db: DbSession
) -> ParticipantOut:
    meeting = service.get_visible_meeting(db, meeting_id, current_user)
    service.require_organizer(meeting, current_user)
    participant = service.add_participant(db, meeting, payload.email, payload.display_name)
    return service.serialise_participant(participant, meeting)


@router.delete(
    "/{meeting_id}/participants/{participant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Withdraw an invitation",
)
def remove_participant(
    meeting_id: int, participant_id: int, current_user: CurrentUser, db: DbSession
) -> Response:
    meeting = service.get_visible_meeting(db, meeting_id, current_user)
    service.require_organizer(meeting, current_user)
    service.remove_participant(db, meeting, participant_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{meeting_id}/rsvp",
    response_model=MeetingDetail,
    summary="Accept, decline or tentatively accept",
)
def rsvp(
    meeting_id: int, payload: RsvpRequest, current_user: CurrentUser, db: DbSession
) -> MeetingDetail:
    meeting = service.get_visible_meeting(db, meeting_id, current_user)
    service.set_rsvp(db, meeting, current_user, payload.status)
    db.refresh(meeting)
    return service.serialise_detail(db, meeting, current_user)


@router.get(
    "/{meeting_id}/calendar.ics",
    response_class=Response,
    summary="Download the meeting as an .ics file",
    responses={200: {"content": {"text/calendar": {}}, "description": "iCalendar document"}},
)
def download_ics(meeting_id: int, current_user: CurrentUser, db: DbSession) -> Response:
    meeting = service.get_visible_meeting(db, meeting_id, current_user)
    body = meeting_to_ics(meeting)
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="meeting-{meeting.id}.ics"',
        },
    )
