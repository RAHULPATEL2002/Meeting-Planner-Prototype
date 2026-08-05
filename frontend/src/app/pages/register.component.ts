import { Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { describeApiError } from '../core/api-error';
import { AuthService } from '../core/auth.service';
import { browserTimezone } from '../core/datetime';

@Component({
  selector: 'app-register',
  imports: [ReactiveFormsModule, RouterLink],
  template: `
    <div class="auth-card">
      <h1>Create an account</h1>
      <p class="muted">You can add a profile picture straight after signing up.</p>

      <form [formGroup]="form" (ngSubmit)="submit()" novalidate>
        <label for="full_name">Full name</label>
        <input id="full_name" formControlName="full_name" autocomplete="name" />
        @if (showError('full_name')) {
          <small class="error">Please tell us your name.</small>
        }

        <label for="email">Email</label>
        <input id="email" type="email" formControlName="email" autocomplete="email" />
        @if (showError('email')) {
          <small class="error">Enter a valid email address.</small>
        }

        <label for="password">Password</label>
        <input
          id="password"
          type="password"
          formControlName="password"
          autocomplete="new-password"
        />
        <small class="muted">At least 8 characters.</small>
        @if (showError('password')) {
          <small class="error">Password must be at least 8 characters.</small>
        }

        @if (error()) {
          <div class="alert alert--error">{{ error() }}</div>
        }

        <button type="submit" class="btn btn--primary" [disabled]="busy()">
          {{ busy() ? 'Creating account…' : 'Create account' }}
        </button>
      </form>

      <p class="muted">Already registered? <a routerLink="/login">Sign in</a></p>
    </div>
  `,
})
export class RegisterComponent {
  private readonly fb = inject(FormBuilder);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  protected readonly busy = signal(false);
  protected readonly error = signal('');

  protected readonly form = this.fb.nonNullable.group({
    full_name: ['', [Validators.required, Validators.maxLength(120)]],
    email: ['', [Validators.required, Validators.email]],
    // Mirrors the server rule (8-72 bytes). The server is still the authority;
    // this only saves a round trip.
    password: ['', [Validators.required, Validators.minLength(8), Validators.maxLength(72)]],
  });

  protected showError(control: 'full_name' | 'email' | 'password'): boolean {
    const field = this.form.controls[control];
    return field.invalid && (field.dirty || field.touched);
  }

  protected submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    this.busy.set(true);
    this.error.set('');

    this.auth
      .register({ ...this.form.getRawValue(), timezone: browserTimezone() })
      .subscribe({
        // Registration signs the user straight in, so send them to their profile
        // where the avatar upload is the obvious next step.
        next: () => void this.router.navigate(['/profile'], { queryParams: { welcome: 1 } }),
        error: (err) => {
          this.error.set(describeApiError(err, 'Could not create the account'));
          this.busy.set(false);
        },
      });
  }
}
