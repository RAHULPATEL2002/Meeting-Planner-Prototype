import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  CreateMeetingRequest,
  MeetingConflict,
  MeetingDetail,
  MeetingListResponse,
  MeetingScope,
  Participant,
  RsvpAnswer,
  UserPublic,
} from './models';

/** Thin, typed wrapper over the meetings API. No state is cached here. */
@Injectable({ providedIn: 'root' })
export class MeetingService {
  private readonly http = inject(HttpClient);

  list(scope: MeetingScope): Observable<MeetingListResponse> {
    return this.http.get<MeetingListResponse>('/api/meetings', {
      params: new HttpParams().set('scope', scope),
    });
  }

  get(id: number): Observable<MeetingDetail> {
    return this.http.get<MeetingDetail>(`/api/meetings/${id}`);
  }

  create(payload: CreateMeetingRequest): Observable<MeetingDetail> {
    return this.http.post<MeetingDetail>('/api/meetings', payload);
  }

  update(id: number, patch: Partial<CreateMeetingRequest>): Observable<MeetingDetail> {
    return this.http.patch<MeetingDetail>(`/api/meetings/${id}`, patch);
  }

  remove(id: number): Observable<void> {
    return this.http.delete<void>(`/api/meetings/${id}`);
  }

  rsvp(id: number, status: RsvpAnswer): Observable<MeetingDetail> {
    return this.http.post<MeetingDetail>(`/api/meetings/${id}/rsvp`, { status });
  }

  invite(id: number, email: string, displayName?: string): Observable<Participant> {
    return this.http.post<Participant>(`/api/meetings/${id}/participants`, {
      email,
      display_name: displayName || null,
    });
  }

  uninvite(meetingId: number, participantId: number): Observable<void> {
    return this.http.delete<void>(`/api/meetings/${meetingId}/participants/${participantId}`);
  }

  /** Look for clashes on a proposed window before the meeting exists. */
  previewConflicts(
    startsAt: string,
    endsAt: string,
    excludeMeetingId?: number,
  ): Observable<MeetingConflict[]> {
    let params = new HttpParams().set('starts_at', startsAt).set('ends_at', endsAt);
    if (excludeMeetingId !== undefined) {
      params = params.set('exclude_meeting_id', String(excludeMeetingId));
    }
    return this.http.get<MeetingConflict[]>('/api/meetings/conflicts', { params });
  }

  searchUsers(query: string): Observable<UserPublic[]> {
    return this.http.get<UserPublic[]>('/api/users', {
      params: new HttpParams().set('q', query).set('limit', '8'),
    });
  }

  /**
   * The .ics endpoint requires the Authorization header, which a plain `<a
   * download>` cannot send — so fetch it as a blob and click a temporary link.
   */
  downloadIcs(meetingId: number, title: string): void {
    this.http
      .get(`/api/meetings/${meetingId}/calendar.ics`, { responseType: 'blob' })
      .subscribe((blob) => {
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = `${slugify(title)}.ics`;
        anchor.click();
        URL.revokeObjectURL(url);
      });
  }
}

function slugify(value: string): string {
  return (
    value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/(^-|-$)/g, '')
      .slice(0, 60) || 'meeting'
  );
}
