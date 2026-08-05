import { DatePipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { describeApiError } from '../core/api-error';
import { AuthService } from '../core/auth.service';
import { UserService } from '../core/user.service';
import { AvatarComponent } from '../shared/avatar.component';

/** Client-side guardrails that mirror the server's upload rules. */
const MAX_BYTES = 2 * 1024 * 1024;
const ACCEPTED = ['image/jpeg', 'image/png', 'image/webp', 'image/gif'];

@Component({
  selector: 'app-profile',
  imports: [ReactiveFormsModule, RouterLink, AvatarComponent, DatePipe],
  template: `
    <div class="page">
      <header class="page__header">
        <div>
          <h1>Your profile</h1>
          @if (welcome()) {
            <p class="muted">Welcome aboard. Add a picture so people recognise you.</p>
          }
        </div>
        <a routerLink="/meetings" class="btn">Back to meetings</a>
      </header>

      @if (user(); as me) {
        <section class="card">
          <h2>Profile picture</h2>
          <div class="avatar-row">
            <app-avatar [name]="me.full_name" [url]="me.avatar_url" [size]="96" />

            <div class="avatar-row__actions">
              <label class="btn btn--primary" [class.btn--busy]="uploading()">
                {{ uploading() ? 'Uploading…' : me.avatar_url ? 'Replace picture' : 'Upload picture' }}
                <input
                  type="file"
                  [accept]="accepted"
                  hidden
                  (change)="onFileSelected($event)"
                  [disabled]="uploading()"
                />
              </label>

              @if (me.avatar_url) {
                <button type="button" class="btn btn--danger-ghost" (click)="removeAvatar()">
                  Remove
                </button>
              }
              <p class="muted">JPEG, PNG, WebP or GIF · up to 2 MB · cropped to a square.</p>
            </div>
          </div>

          @if (avatarError()) {
            <div class="alert alert--error">{{ avatarError() }}</div>
          }
        </section>

        <section class="card">
          <h2>Details</h2>
          <form [formGroup]="form" (ngSubmit)="save()" novalidate>
            <label for="full_name">Full name</label>
            <input id="full_name" formControlName="full_name" />

            <label for="timezone">Timezone</label>
            <input id="timezone" formControlName="timezone" />
            <small class="muted">
              Used for display only — meetings are stored in UTC. Signed up
              {{ me.created_at | date: 'mediumDate' }}.
            </small>

            <label>Email</label>
            <input [value]="me.email" disabled />
            <small class="muted">Email is your sign-in name and cannot be changed here.</small>

            @if (profileError()) {
              <div class="alert alert--error">{{ profileError() }}</div>
            }
            @if (saved()) {
              <div class="alert alert--success">Profile updated.</div>
            }

            <button type="submit" class="btn btn--primary" [disabled]="form.invalid || saving()">
              {{ saving() ? 'Saving…' : 'Save changes' }}
            </button>
          </form>
        </section>
      }
    </div>
  `,
  styles: [
    `
      .avatar-row {
        display: flex;
        gap: 1.5rem;
        align-items: center;
        flex-wrap: wrap;
      }
      .avatar-row__actions {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
        align-items: flex-start;
      }
      .btn--busy {
        opacity: 0.6;
        pointer-events: none;
      }
    `,
  ],
})
export class ProfileComponent {
  private readonly fb = inject(FormBuilder);
  private readonly users = inject(UserService);
  private readonly auth = inject(AuthService);
  private readonly route = inject(ActivatedRoute);

  protected readonly accepted = ACCEPTED.join(',');
  protected readonly user = this.auth.currentUser;
  protected readonly welcome = signal(this.route.snapshot.queryParamMap.has('welcome'));

  protected readonly uploading = signal(false);
  protected readonly saving = signal(false);
  protected readonly saved = signal(false);
  protected readonly avatarError = signal('');
  protected readonly profileError = signal('');

  protected readonly form = this.fb.nonNullable.group({
    full_name: [this.user()?.full_name ?? '', [Validators.required, Validators.maxLength(120)]],
    timezone: [this.user()?.timezone ?? 'UTC', [Validators.required]],
  });

  protected onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) {
      return;
    }

    // Fail fast in the browser. The server repeats both checks — it has to,
    // since anyone can POST to the endpoint directly.
    if (!ACCEPTED.includes(file.type)) {
      this.avatarError.set('Please choose a JPEG, PNG, WebP or GIF image.');
      input.value = '';
      return;
    }
    if (file.size > MAX_BYTES) {
      this.avatarError.set(`That file is ${(file.size / 1024 / 1024).toFixed(1)} MB; the limit is 2 MB.`);
      input.value = '';
      return;
    }

    this.avatarError.set('');
    this.uploading.set(true);

    this.users.uploadAvatar(file).subscribe({
      next: () => {
        this.uploading.set(false);
        // Reset the input so re-selecting the same file fires `change` again.
        input.value = '';
      },
      error: (err) => {
        this.avatarError.set(describeApiError(err, 'Upload failed'));
        this.uploading.set(false);
        input.value = '';
      },
    });
  }

  protected removeAvatar(): void {
    this.users.removeAvatar().subscribe({
      error: (err) => this.avatarError.set(describeApiError(err, 'Could not remove the picture')),
    });
  }

  protected save(): void {
    if (this.form.invalid) {
      return;
    }
    this.saving.set(true);
    this.saved.set(false);
    this.profileError.set('');

    this.users.updateProfile(this.form.getRawValue()).subscribe({
      next: () => {
        this.saving.set(false);
        this.saved.set(true);
      },
      error: (err) => {
        this.profileError.set(describeApiError(err, 'Could not save your profile'));
        this.saving.set(false);
      },
    });
  }
}
