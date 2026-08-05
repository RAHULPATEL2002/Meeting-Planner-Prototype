import { Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { describeApiError } from '../core/api-error';
import { AuthService } from '../core/auth.service';

@Component({
  selector: 'app-login',
  imports: [ReactiveFormsModule, RouterLink],
  template: `
    <div class="auth-card">
      <h1>Sign in</h1>
      <p class="muted">Plan meetings, invite people, keep track of who is coming.</p>

      @if (expired()) {
        <div class="alert alert--warning">Your session expired. Please sign in again.</div>
      }

      <form [formGroup]="form" (ngSubmit)="submit()" novalidate>
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
          autocomplete="current-password"
        />
        @if (showError('password')) {
          <small class="error">Password is required.</small>
        }

        @if (error()) {
          <div class="alert alert--error">{{ error() }}</div>
        }

        <button type="submit" class="btn btn--primary" [disabled]="busy()">
          {{ busy() ? 'Signing in…' : 'Sign in' }}
        </button>
      </form>

      <p class="muted">No account yet? <a routerLink="/register">Create one</a></p>
    </div>
  `,
})
export class LoginComponent {
  private readonly fb = inject(FormBuilder);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  protected readonly busy = signal(false);
  protected readonly error = signal('');
  protected readonly expired = signal(
    this.route.snapshot.queryParamMap.get('reason') === 'expired',
  );

  protected readonly form = this.fb.nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required]],
  });

  protected showError(control: 'email' | 'password'): boolean {
    const field = this.form.controls[control];
    return field.invalid && (field.dirty || field.touched);
  }

  protected submit(): void {
    if (this.form.invalid) {
      // Touch everything so the user sees *which* field is wrong, not just
      // a form that silently refuses to submit.
      this.form.markAllAsTouched();
      return;
    }

    this.busy.set(true);
    this.error.set('');
    const { email, password } = this.form.getRawValue();

    this.auth.login(email, password).subscribe({
      next: () => {
        const returnUrl = this.route.snapshot.queryParamMap.get('returnUrl') ?? '/meetings';
        void this.router.navigateByUrl(returnUrl);
      },
      error: (err) => {
        this.error.set(describeApiError(err, 'Sign in failed'));
        this.busy.set(false);
      },
    });
  }
}
