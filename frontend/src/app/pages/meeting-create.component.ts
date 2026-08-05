import { Component, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { catchError, debounceTime, distinctUntilChanged, of, switchMap } from 'rxjs';

import { describeApiError } from '../core/api-error';
import { formatRange, localInputToIsoUtc, nextHalfHourLocalInput } from '../core/datetime';
import { MeetingService } from '../core/meeting.service';
import { MeetingConflict, UserPublic } from '../core/models';
import { AvatarComponent } from '../shared/avatar.component';

interface Invitee {
  email: string;
  name: string;
  avatarUrl: string | null;
  registered: boolean;
}

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

@Component({
  selector: 'app-meeting-create',
  imports: [ReactiveFormsModule, RouterLink, AvatarComponent],
  template: `
    <div class="page page--narrow">
      <header class="page__header">
        <h1>New meeting</h1>
        <a routerLink="/meetings" class="btn">Cancel</a>
      </header>

      <form [formGroup]="form" (ngSubmit)="submit()" novalidate class="card">
        <label for="title">Title</label>
        <input id="title" formControlName="title" placeholder="Sprint planning" />
        @if (invalid('title')) {
          <small class="error">Give the meeting a title of at least 3 characters.</small>
        }

        <div class="grid-2">
          <div>
            <label for="starts_at">Starts</label>
            <input id="starts_at" type="datetime-local" formControlName="starts_at" />
          </div>
          <div>
            <label for="ends_at">Ends</label>
            <input id="ends_at" type="datetime-local" formControlName="ends_at" />
          </div>
        </div>

        <div class="quick-durations">
          <span class="muted">Quick set:</span>
          @for (minutes of quickDurations; track minutes) {
            <button type="button" class="chip chip--button" (click)="setDuration(minutes)">
              {{ minutes < 60 ? minutes + ' min' : minutes / 60 + ' h' }}
            </button>
          }
        </div>

        @if (windowError()) {
          <small class="error">{{ windowError() }}</small>
        }

        @if (conflicts().length > 0) {
          <div class="alert alert--warning">
            <strong>You are already busy then.</strong>
            <ul>
              @for (clash of conflicts(); track clash.id) {
                <li>{{ clash.title }} — {{ clashRange(clash) }} ({{ clash.overlap_minutes }} min overlap)</li>
              }
            </ul>
            <small>You can still schedule this; it is only a warning.</small>
          </div>
        }

        <label for="location">Location <span class="muted">(optional)</span></label>
        <input id="location" formControlName="location" placeholder="Room 4B, or a video link" />

        <label for="description">Agenda <span class="muted">(optional)</span></label>
        <textarea id="description" rows="3" formControlName="description"></textarea>

        <label for="invitee">Invite people</label>
        <div class="invitee-input">
          <input
            id="invitee"
            [formControl]="inviteeControl"
            placeholder="Search by name, or type any email address"
            (keydown.enter)="$event.preventDefault(); addTypedEmail()"
          />
          <button type="button" class="btn" (click)="addTypedEmail()">Add</button>
        </div>

        @if (suggestions().length > 0) {
          <ul class="suggestions">
            @for (user of suggestions(); track user.id) {
              <li>
                <button type="button" (click)="addUser(user)">
                  <app-avatar [name]="user.full_name" [url]="user.avatar_url" [size]="28" />
                  <span>{{ user.full_name }}</span>
                  <span class="muted">{{ user.email }}</span>
                </button>
              </li>
            }
          </ul>
        }
        @if (inviteeError()) {
          <small class="error">{{ inviteeError() }}</small>
        }

        @if (invitees().length > 0) {
          <ul class="chips">
            @for (invitee of invitees(); track invitee.email) {
              <li class="chip">
                <app-avatar [name]="invitee.name" [url]="invitee.avatarUrl" [size]="20" />
                {{ invitee.name }}
                @if (!invitee.registered) {
                  <span class="muted">(guest)</span>
                }
                <button type="button" aria-label="Remove" (click)="removeInvitee(invitee.email)">
                  ×
                </button>
              </li>
            }
          </ul>
        }

        @if (error()) {
          <div class="alert alert--error">{{ error() }}</div>
        }

        <button type="submit" class="btn btn--primary" [disabled]="busy()">
          {{ busy() ? 'Creating…' : 'Create meeting' }}
        </button>
      </form>
    </div>
  `,
  styles: [
    `
      .grid-2 {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 1rem;
      }
      @media (max-width: 560px) {
        .grid-2 {
          grid-template-columns: 1fr;
        }
      }
      .quick-durations {
        display: flex;
        gap: 0.4rem;
        align-items: center;
        flex-wrap: wrap;
        margin: 0.5rem 0 0.25rem;
      }
      .chip--button {
        cursor: pointer;
        border: 1px solid var(--border);
        background: var(--surface-2);
      }
      .invitee-input {
        display: flex;
        gap: 0.5rem;
      }
      .invitee-input input {
        flex: 1;
      }
      .suggestions {
        list-style: none;
        margin: 0.25rem 0 0;
        padding: 0;
        border: 1px solid var(--border);
        border-radius: 8px;
        overflow: hidden;
      }
      .suggestions button {
        display: flex;
        align-items: center;
        gap: 0.6rem;
        width: 100%;
        padding: 0.5rem 0.75rem;
        background: var(--surface);
        border: none;
        cursor: pointer;
        font: inherit;
        text-align: left;
      }
      .suggestions button:hover {
        background: var(--surface-2);
      }
      .chips {
        list-style: none;
        display: flex;
        flex-wrap: wrap;
        gap: 0.4rem;
        padding: 0;
        margin: 0.75rem 0 0;
      }
      .chips .chip {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
      }
      .chips .chip button {
        border: none;
        background: none;
        cursor: pointer;
        font-size: 1rem;
        line-height: 1;
        color: var(--text-muted);
      }
    `,
  ],
})
export class MeetingCreateComponent {
  private readonly fb = inject(FormBuilder);
  private readonly meetings = inject(MeetingService);
  private readonly router = inject(Router);

  protected readonly quickDurations = [15, 30, 60, 120];

  protected readonly invitees = signal<Invitee[]>([]);
  protected readonly suggestions = signal<UserPublic[]>([]);
  protected readonly conflicts = signal<MeetingConflict[]>([]);
  protected readonly busy = signal(false);
  protected readonly error = signal('');
  protected readonly inviteeError = signal('');
  protected readonly windowError = signal('');

  protected readonly form = this.fb.nonNullable.group({
    title: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(200)]],
    description: [''],
    location: [''],
    starts_at: [nextHalfHourLocalInput(30), Validators.required],
    ends_at: [nextHalfHourLocalInput(90), Validators.required],
  });

  protected readonly inviteeControl = this.fb.nonNullable.control('');

  constructor() {
    // Type-ahead over registered users. `switchMap` cancels the previous
    // request, so a slow response cannot overwrite a newer one.
    this.inviteeControl.valueChanges
      .pipe(
        debounceTime(250),
        distinctUntilChanged(),
        switchMap((term) => {
          const query = term.trim();
          if (query.length < 2) {
            return of([] as UserPublic[]);
          }
          return this.meetings.searchUsers(query).pipe(catchError(() => of([] as UserPublic[])));
        }),
        takeUntilDestroyed(),
      )
      .subscribe((users) => this.suggestions.set(this.excludeAlreadyInvited(users)));

    // Live clash check against the user's own calendar.
    this.form.valueChanges
      .pipe(debounceTime(400), takeUntilDestroyed())
      .subscribe(() => this.checkWindow());

    this.checkWindow();
  }

  protected invalid(field: 'title'): boolean {
    const control = this.form.controls[field];
    return control.invalid && (control.dirty || control.touched);
  }

  protected clashRange = (clash: MeetingConflict) => formatRange(clash.starts_at, clash.ends_at);

  /** Keep the duration but move the end relative to the current start. */
  protected setDuration(minutes: number): void {
    const start = new Date(this.form.controls.starts_at.value);
    if (Number.isNaN(start.getTime())) {
      return;
    }
    const end = new Date(start.getTime() + minutes * 60_000);
    const pad = (n: number) => String(n).padStart(2, '0');
    this.form.controls.ends_at.setValue(
      `${end.getFullYear()}-${pad(end.getMonth() + 1)}-${pad(end.getDate())}` +
        `T${pad(end.getHours())}:${pad(end.getMinutes())}`,
    );
  }

  protected addTypedEmail(): void {
    const value = this.inviteeControl.value.trim().toLowerCase();
    if (!value) {
      return;
    }
    if (!EMAIL_PATTERN.test(value)) {
      this.inviteeError.set('That does not look like an email address.');
      return;
    }
    this.pushInvitee({ email: value, name: value.split('@')[0], avatarUrl: null, registered: false });
  }

  protected addUser(user: UserPublic): void {
    this.pushInvitee({
      email: user.email,
      name: user.full_name,
      avatarUrl: user.avatar_url,
      registered: true,
    });
  }

  protected removeInvitee(email: string): void {
    this.invitees.update((list) => list.filter((i) => i.email !== email));
  }

  protected submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const { starts_at, ends_at, title, description, location } = this.form.getRawValue();
    if (!this.validWindow(starts_at, ends_at)) {
      return;
    }

    this.busy.set(true);
    this.error.set('');

    this.meetings
      .create({
        title: title.trim(),
        description: description.trim() || null,
        location: location.trim() || null,
        // Convert from the browser's local wall time to an absolute instant.
        starts_at: localInputToIsoUtc(starts_at),
        ends_at: localInputToIsoUtc(ends_at),
        participants: this.invitees().map((i) => ({
          email: i.email,
          display_name: i.registered ? null : i.name,
        })),
      })
      .subscribe({
        // Land on the detail page: the exercise asks for useful details right
        // after creation, and that is where they live.
        next: (meeting) => void this.router.navigate(['/meetings', meeting.id]),
        error: (err) => {
          this.error.set(describeApiError(err, 'Could not create the meeting'));
          this.busy.set(false);
        },
      });
  }

  private pushInvitee(invitee: Invitee): void {
    this.inviteeError.set('');
    if (this.invitees().some((i) => i.email === invitee.email)) {
      this.inviteeError.set('That person is already on the list.');
      return;
    }
    this.invitees.update((list) => [...list, invitee]);
    this.inviteeControl.setValue('');
    this.suggestions.set([]);
  }

  private excludeAlreadyInvited(users: UserPublic[]): UserPublic[] {
    const chosen = new Set(this.invitees().map((i) => i.email));
    return users.filter((u) => !chosen.has(u.email));
  }

  private validWindow(startLocal: string, endLocal: string): boolean {
    const start = new Date(startLocal).getTime();
    const end = new Date(endLocal).getTime();

    if (Number.isNaN(start) || Number.isNaN(end)) {
      this.windowError.set('Pick a valid start and end time.');
      return false;
    }
    if (end <= start) {
      this.windowError.set('The meeting has to end after it starts.');
      return false;
    }
    if (end - start < 5 * 60_000) {
      this.windowError.set('Meetings must be at least 5 minutes long.');
      return false;
    }
    this.windowError.set('');
    return true;
  }

  private checkWindow(): void {
    const { starts_at, ends_at } = this.form.getRawValue();
    if (!this.validWindow(starts_at, ends_at)) {
      this.conflicts.set([]);
      return;
    }
    this.meetings
      .previewConflicts(localInputToIsoUtc(starts_at), localInputToIsoUtc(ends_at))
      .pipe(catchError(() => of([] as MeetingConflict[])))
      .subscribe((clashes) => this.conflicts.set(clashes));
  }
}
