import { Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { describeApiError } from '../core/api-error';
import { formatDuration, formatRange, formatRelative } from '../core/datetime';
import { MeetingService } from '../core/meeting.service';
import { MeetingScope, MeetingSummary } from '../core/models';
import { AvatarComponent } from '../shared/avatar.component';
import { StatusBadgeComponent } from '../shared/status-badge.component';

@Component({
  selector: 'app-meeting-list',
  imports: [RouterLink, AvatarComponent, StatusBadgeComponent],
  template: `
    <div class="page">
      <header class="page__header">
        <h1>Meetings</h1>
        <a routerLink="/meetings/new" class="btn btn--primary">New meeting</a>
      </header>

      <nav class="tabs" role="tablist">
        @for (tab of tabs; track tab.value) {
          <button
            type="button"
            role="tab"
            class="tab"
            [class.tab--active]="scope() === tab.value"
            [attr.aria-selected]="scope() === tab.value"
            (click)="setScope(tab.value)"
          >
            {{ tab.label }}
          </button>
        }
      </nav>

      @if (loading()) {
        <p class="muted">Loading…</p>
      } @else if (error()) {
        <div class="alert alert--error">{{ error() }}</div>
      } @else if (meetings().length === 0) {
        <div class="empty">
          <h2>{{ scope() === 'past' ? 'Nothing here yet' : 'No meetings scheduled' }}</h2>
          <p class="muted">
            {{
              scope() === 'past'
                ? 'Meetings move here once they have finished.'
                : 'Create one and invite people by email.'
            }}
          </p>
          <a routerLink="/meetings/new" class="btn btn--primary">Schedule a meeting</a>
        </div>
      } @else {
        <ul class="meeting-list">
          @for (meeting of meetings(); track meeting.id) {
            <li>
              <a class="meeting-card" [routerLink]="['/meetings', meeting.id]">
                <div class="meeting-card__main">
                  <div class="meeting-card__title">
                    <h2>{{ meeting.title }}</h2>
                    @if (meeting.is_organizer) {
                      <span class="chip">You organise this</span>
                    } @else if (meeting.my_status) {
                      <app-status-badge [status]="meeting.my_status" />
                    }
                  </div>

                  <p class="meeting-card__when">
                    {{ range(meeting) }}
                    <span class="muted">· {{ duration(meeting) }} · {{ relative(meeting) }}</span>
                  </p>

                  @if (meeting.location) {
                    <p class="muted">📍 {{ meeting.location }}</p>
                  }
                </div>

                <div class="meeting-card__side">
                  <app-avatar
                    [name]="meeting.organizer.full_name"
                    [url]="meeting.organizer.avatar_url"
                    [size]="32"
                  />
                  <span class="muted">{{ meeting.participant_count }} people</span>
                </div>
              </a>
            </li>
          }
        </ul>
      }
    </div>
  `,
  styles: [
    `
      .tabs {
        display: flex;
        gap: 0.25rem;
        margin-bottom: 1rem;
        border-bottom: 1px solid var(--border);
      }
      .tab {
        background: none;
        border: none;
        border-bottom: 2px solid transparent;
        padding: 0.6rem 0.9rem;
        cursor: pointer;
        color: var(--text-muted);
        font: inherit;
      }
      .tab--active {
        color: var(--brand);
        border-bottom-color: var(--brand);
        font-weight: 600;
      }
      .meeting-list {
        list-style: none;
        margin: 0;
        padding: 0;
        display: grid;
        gap: 0.75rem;
      }
      .meeting-card {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 1rem;
        padding: 1rem 1.25rem;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 12px;
        text-decoration: none;
        color: inherit;
        transition: border-color 0.15s ease, transform 0.15s ease;
      }
      .meeting-card:hover {
        border-color: var(--brand);
        transform: translateY(-1px);
      }
      .meeting-card__title {
        display: flex;
        align-items: center;
        gap: 0.6rem;
        flex-wrap: wrap;
      }
      .meeting-card h2 {
        margin: 0;
        font-size: 1.05rem;
      }
      .meeting-card__when {
        margin: 0.35rem 0 0;
      }
      .meeting-card__side {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        white-space: nowrap;
      }
      .empty {
        text-align: center;
        padding: 3rem 1rem;
        border: 1px dashed var(--border);
        border-radius: 12px;
      }
    `,
  ],
})
export class MeetingListComponent {
  private readonly meetingService = inject(MeetingService);

  protected readonly tabs: { value: MeetingScope; label: string }[] = [
    { value: 'upcoming', label: 'Upcoming' },
    { value: 'past', label: 'Past' },
    { value: 'all', label: 'All' },
  ];

  protected readonly scope = signal<MeetingScope>('upcoming');
  protected readonly meetings = signal<MeetingSummary[]>([]);
  protected readonly loading = signal(true);
  protected readonly error = signal('');

  constructor() {
    this.load();
  }

  protected setScope(scope: MeetingScope): void {
    if (scope === this.scope()) {
      return;
    }
    this.scope.set(scope);
    this.load();
  }

  protected range = (m: MeetingSummary) => formatRange(m.starts_at, m.ends_at);
  protected duration = (m: MeetingSummary) => formatDuration(m.duration_minutes);
  protected relative = (m: MeetingSummary) => formatRelative(m.starts_at);

  private load(): void {
    this.loading.set(true);
    this.error.set('');

    this.meetingService.list(this.scope()).subscribe({
      next: (response) => {
        this.meetings.set(response.items);
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(describeApiError(err, 'Could not load your meetings'));
        this.loading.set(false);
      },
    });
  }
}
