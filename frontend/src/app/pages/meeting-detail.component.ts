import { Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { describeApiError } from '../core/api-error';
import { formatDuration, formatRange, formatRelative } from '../core/datetime';
import { MeetingService } from '../core/meeting.service';
import { MeetingDetail, RsvpAnswer } from '../core/models';
import { AvatarComponent } from '../shared/avatar.component';
import { StatusBadgeComponent } from '../shared/status-badge.component';

@Component({
  selector: 'app-meeting-detail',
  imports: [ReactiveFormsModule, RouterLink, AvatarComponent, StatusBadgeComponent],
  template: `
    <div class="page page--narrow">
      @if (loading()) {
        <p class="muted">Loading…</p>
      } @else if (loadError()) {
        <div class="alert alert--error">{{ loadError() }}</div>
        <a routerLink="/meetings" class="btn">Back to meetings</a>
      } @else if (meeting(); as m) {
        <header class="page__header">
          <a routerLink="/meetings" class="back-link">← All meetings</a>
        </header>

        <!-- ─── Headline ─────────────────────────────────────────────── -->
        <section class="card">
          <div class="title-row">
            <h1>{{ m.title }}</h1>
            <span class="chip chip--{{ phase() }}">{{ phaseLabel() }}</span>
          </div>

          <p class="when">
            <strong>{{ range() }}</strong>
            <span class="muted"> · {{ duration() }} · {{ relative() }}</span>
          </p>

          @if (m.location) {
            <p>📍 {{ m.location }}</p>
          }
          @if (m.description) {
            <p class="description">{{ m.description }}</p>
          }

          <div class="organiser">
            <app-avatar
              [name]="m.organizer.full_name"
              [url]="m.organizer.avatar_url"
              [size]="32"
            />
            <span>
              Organised by <strong>{{ m.is_organizer ? 'you' : m.organizer.full_name }}</strong>
            </span>
          </div>

          <div class="actions">
            <button type="button" class="btn" (click)="downloadIcs()">Add to calendar (.ics)</button>
            @if (m.is_organizer) {
              <button type="button" class="btn btn--danger-ghost" (click)="remove()">
                Cancel meeting
              </button>
            }
          </div>
        </section>

        <!-- ─── Your response ────────────────────────────────────────── -->
        @if (!m.is_organizer && m.my_status) {
          <section class="card">
            <h2>Your response</h2>
            <div class="rsvp">
              @for (option of rsvpOptions; track option.value) {
                <button
                  type="button"
                  class="btn"
                  [class.btn--primary]="m.my_status === option.value"
                  [disabled]="saving()"
                  (click)="respond(option.value)"
                >
                  {{ option.label }}
                </button>
              }
            </div>
          </section>
        }

        <!-- ─── Conflicts ────────────────────────────────────────────── -->
        @if (m.conflicts.length > 0) {
          <section class="alert alert--warning">
            <strong>This clashes with {{ m.conflicts.length }} other meeting(s) of yours</strong>
            <ul>
              @for (clash of m.conflicts; track clash.id) {
                <li>
                  <a [routerLink]="['/meetings', clash.id]">{{ clash.title }}</a>
                  — {{ clashRange(clash.starts_at, clash.ends_at) }}
                  ({{ clash.overlap_minutes }} min overlap)
                </li>
              }
            </ul>
          </section>
        }

        <!-- ─── Participants ─────────────────────────────────────────── -->
        <section class="card">
          <div class="title-row">
            <h2>Participants ({{ m.participant_count }})</h2>
          </div>

          <div class="summary-bar" [attr.aria-label]="summaryLabel()">
            @for (slice of summarySlices(); track slice.key) {
              @if (slice.count > 0) {
                <span
                  class="summary-bar__slice summary-bar__slice--{{ slice.key }}"
                  [style.flex-grow]="slice.count"
                  [title]="slice.count + ' ' + slice.key"
                ></span>
              }
            }
          </div>
          <p class="muted summary-text">{{ summaryLabel() }}</p>

          <ul class="participants">
            @for (participant of m.participants; track participant.id) {
              <li>
                <app-avatar
                  [name]="participant.name"
                  [url]="participant.user?.avatar_url ?? null"
                  [size]="36"
                />
                <div class="participants__who">
                  <span class="participants__name">
                    {{ participant.name }}
                    @if (participant.is_organizer) {
                      <span class="chip">Organiser</span>
                    }
                    @if (!participant.is_registered) {
                      <span class="chip" title="Invited by email, no account yet">Guest</span>
                    }
                  </span>
                  <span class="muted">{{ participant.email }}</span>
                </div>

                <app-status-badge [status]="participant.status" />

                @if (m.is_organizer && !participant.is_organizer) {
                  <button
                    type="button"
                    class="icon-btn"
                    [attr.aria-label]="'Remove ' + participant.name"
                    (click)="uninvite(participant.id)"
                  >
                    ×
                  </button>
                }
              </li>
            }
          </ul>

          @if (m.is_organizer) {
            <form [formGroup]="inviteForm" (ngSubmit)="invite()" class="invite-form">
              <input
                type="email"
                formControlName="email"
                placeholder="Invite someone by email"
                aria-label="Email address to invite"
              />
              <button type="submit" class="btn" [disabled]="inviteForm.invalid || inviting()">
                {{ inviting() ? 'Inviting…' : 'Invite' }}
              </button>
            </form>
            @if (actionError()) {
              <div class="alert alert--error">{{ actionError() }}</div>
            }
          }
        </section>

        <p class="muted meta">
          Created {{ created() }} · last updated {{ updated() }}
        </p>
      }
    </div>
  `,
  styles: [
    `
      .back-link {
        color: var(--text-muted);
        text-decoration: none;
      }
      .title-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 1rem;
        flex-wrap: wrap;
      }
      .title-row h1,
      .title-row h2 {
        margin: 0;
      }
      .when {
        font-size: 1.05rem;
        margin: 0.75rem 0 0.25rem;
      }
      .description {
        white-space: pre-wrap;
        background: var(--surface-2);
        padding: 0.75rem 1rem;
        border-radius: 8px;
      }
      .organiser {
        display: flex;
        align-items: center;
        gap: 0.6rem;
        margin: 1rem 0;
      }
      .actions,
      .rsvp {
        display: flex;
        gap: 0.5rem;
        flex-wrap: wrap;
      }
      .chip--upcoming {
        background: #e8f0fe;
        color: #1a4fb4;
      }
      .chip--live {
        background: #e6f6ec;
        color: #14713a;
      }
      .chip--finished {
        background: var(--surface-2);
        color: var(--text-muted);
      }
      .summary-bar {
        display: flex;
        height: 8px;
        border-radius: 999px;
        overflow: hidden;
        background: var(--surface-2);
        margin: 0.75rem 0 0.35rem;
      }
      .summary-bar__slice--accepted {
        background: #2f9e5f;
      }
      .summary-bar__slice--declined {
        background: #d24a4a;
      }
      .summary-bar__slice--tentative {
        background: #e2a52c;
      }
      .summary-bar__slice--invited {
        background: #c3cbd9;
      }
      .summary-text {
        margin-top: 0;
      }
      .participants {
        list-style: none;
        padding: 0;
        margin: 1rem 0 0;
        display: grid;
        gap: 0.6rem;
      }
      .participants li {
        display: flex;
        align-items: center;
        gap: 0.75rem;
      }
      .participants__who {
        display: flex;
        flex-direction: column;
        flex: 1;
        min-width: 0;
      }
      .participants__name {
        display: flex;
        align-items: center;
        gap: 0.4rem;
        flex-wrap: wrap;
      }
      .icon-btn {
        border: none;
        background: none;
        cursor: pointer;
        font-size: 1.2rem;
        color: var(--text-muted);
        line-height: 1;
      }
      .invite-form {
        display: flex;
        gap: 0.5rem;
        margin-top: 1rem;
      }
      .invite-form input {
        flex: 1;
        margin: 0;
      }
      .meta {
        font-size: 0.8rem;
      }
    `,
  ],
})
export class MeetingDetailComponent {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly meetings = inject(MeetingService);
  private readonly fb = inject(FormBuilder);

  protected readonly rsvpOptions: { value: RsvpAnswer; label: string }[] = [
    { value: 'accepted', label: '✓ Going' },
    { value: 'tentative', label: '? Maybe' },
    { value: 'declined', label: '✗ Not going' },
  ];

  protected readonly meeting = signal<MeetingDetail | null>(null);
  protected readonly loading = signal(true);
  protected readonly loadError = signal('');
  protected readonly actionError = signal('');
  protected readonly saving = signal(false);
  protected readonly inviting = signal(false);

  protected readonly inviteForm = this.fb.nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
  });

  private readonly meetingId = Number(this.route.snapshot.paramMap.get('id'));

  /** upcoming | live | finished — drives the status chip. */
  protected readonly phase = computed<'upcoming' | 'live' | 'finished'>(() => {
    const m = this.meeting();
    if (!m) return 'upcoming';
    const now = Date.now();
    if (now < new Date(m.starts_at).getTime()) return 'upcoming';
    return now <= new Date(m.ends_at).getTime() ? 'live' : 'finished';
  });

  protected readonly phaseLabel = computed(
    () => ({ upcoming: 'Upcoming', live: 'In progress', finished: 'Finished' })[this.phase()],
  );

  protected readonly summarySlices = computed(() => {
    const s = this.meeting()?.response_summary;
    return [
      { key: 'accepted', count: s?.accepted ?? 0 },
      { key: 'tentative', count: s?.tentative ?? 0 },
      { key: 'declined', count: s?.declined ?? 0 },
      { key: 'invited', count: s?.invited ?? 0 },
    ];
  });

  protected readonly summaryLabel = computed(() => {
    const s = this.meeting()?.response_summary;
    if (!s) return '';
    return `${s.accepted} going · ${s.tentative} maybe · ${s.declined} not going · ${s.invited} awaiting reply`;
  });

  constructor() {
    this.load();
  }

  protected range = () => {
    const m = this.meeting()!;
    return formatRange(m.starts_at, m.ends_at);
  };
  protected duration = () => formatDuration(this.meeting()!.duration_minutes);
  protected relative = () => formatRelative(this.meeting()!.starts_at);
  protected created = () => formatRelative(this.meeting()!.created_at);
  protected updated = () => formatRelative(this.meeting()!.updated_at);
  protected clashRange = (start: string, end: string) => formatRange(start, end);

  protected respond(status: RsvpAnswer): void {
    this.saving.set(true);
    this.meetings.rsvp(this.meetingId, status).subscribe({
      next: (updated) => {
        this.meeting.set(updated);
        this.saving.set(false);
      },
      error: (err) => {
        this.actionError.set(describeApiError(err, 'Could not save your response'));
        this.saving.set(false);
      },
    });
  }

  protected invite(): void {
    if (this.inviteForm.invalid) {
      return;
    }
    this.inviting.set(true);
    this.actionError.set('');

    this.meetings.invite(this.meetingId, this.inviteForm.getRawValue().email).subscribe({
      next: () => {
        this.inviteForm.reset();
        this.inviting.set(false);
        // Refetch so counts, the summary bar and the roster all stay consistent.
        this.load(false);
      },
      error: (err) => {
        this.actionError.set(describeApiError(err, 'Could not send that invitation'));
        this.inviting.set(false);
      },
    });
  }

  protected uninvite(participantId: number): void {
    this.meetings.uninvite(this.meetingId, participantId).subscribe({
      next: () => this.load(false),
      error: (err) => this.actionError.set(describeApiError(err, 'Could not remove them')),
    });
  }

  protected downloadIcs(): void {
    this.meetings.downloadIcs(this.meetingId, this.meeting()?.title ?? 'meeting');
  }

  protected remove(): void {
    if (!confirm('Cancel this meeting for everyone? This cannot be undone.')) {
      return;
    }
    this.meetings.remove(this.meetingId).subscribe({
      next: () => void this.router.navigate(['/meetings']),
      error: (err) => this.actionError.set(describeApiError(err, 'Could not cancel the meeting')),
    });
  }

  private load(showSpinner = true): void {
    if (showSpinner) {
      this.loading.set(true);
    }
    this.meetings.get(this.meetingId).subscribe({
      next: (meeting) => {
        this.meeting.set(meeting);
        this.loading.set(false);
      },
      error: (err) => {
        this.loadError.set(
          err.status === 404
            ? 'That meeting does not exist, or you are not invited to it.'
            : describeApiError(err, 'Could not load the meeting'),
        );
        this.loading.set(false);
      },
    });
  }
}
