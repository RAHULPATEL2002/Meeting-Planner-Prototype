/**
 * TypeScript mirrors of the FastAPI response schemas.
 *
 * These are hand-written rather than generated. With more time the honest move
 * is to generate them from the backend's OpenAPI document so the two can never
 * drift apart (see "What I'd improve" in the README).
 */

export type ParticipantStatus = 'invited' | 'accepted' | 'declined' | 'tentative';

/** A response a participant is allowed to give ('invited' is the initial state). */
export type RsvpAnswer = Exclude<ParticipantStatus, 'invited'>;

export type MeetingScope = 'upcoming' | 'past' | 'all';

export interface UserPublic {
  id: number;
  email: string;
  full_name: string;
  avatar_url: string | null;
}

export interface UserMe extends UserPublic {
  timezone: string;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
  user: UserMe;
}

export interface Participant {
  id: number;
  email: string;
  status: ParticipantStatus;
  responded_at: string | null;
  user: UserPublic | null;
  name: string;
  is_registered: boolean;
  is_organizer: boolean;
}

export interface ResponseSummary {
  total: number;
  accepted: number;
  declined: number;
  tentative: number;
  invited: number;
}

export interface MeetingConflict {
  id: number;
  title: string;
  starts_at: string;
  ends_at: string;
  overlap_minutes: number;
}

export interface MeetingSummary {
  id: number;
  title: string;
  location: string | null;
  starts_at: string;
  ends_at: string;
  duration_minutes: number;
  organizer: UserPublic;
  participant_count: number;
  my_status: ParticipantStatus | null;
  is_organizer: boolean;
}

export interface MeetingDetail extends MeetingSummary {
  description: string | null;
  created_at: string;
  updated_at: string;
  participants: Participant[];
  response_summary: ResponseSummary;
  conflicts: MeetingConflict[];
  ics_url: string;
}

export interface MeetingListResponse {
  items: MeetingSummary[];
  total: number;
}

export interface CreateMeetingRequest {
  title: string;
  description?: string | null;
  location?: string | null;
  /** ISO-8601 with an explicit offset or trailing Z. */
  starts_at: string;
  ends_at: string;
  participants: { email: string; display_name?: string | null }[];
}
