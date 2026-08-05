import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Observable, tap } from 'rxjs';

import { AuthResponse, UserMe } from './models';

const TOKEN_KEY = 'mp.token';
const USER_KEY = 'mp.user';

/**
 * Holds the session: the JWT and the signed-in user.
 *
 * State lives in signals so templates re-render automatically, and is mirrored
 * into localStorage so a page refresh does not sign the user out. The cached
 * user is treated as a *hint* only — `restoreSession()` re-validates the token
 * against the API on boot, because a token can expire while the tab is closed.
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);

  private readonly token = signal<string | null>(localStorage.getItem(TOKEN_KEY));
  private readonly user = signal<UserMe | null>(readCachedUser());

  /** The signed-in user, or null. Read this from templates. */
  readonly currentUser = this.user.asReadonly();
  readonly isAuthenticated = computed(() => this.token() !== null);

  get accessToken(): string | null {
    return this.token();
  }

  register(payload: {
    email: string;
    password: string;
    full_name: string;
    timezone: string;
  }): Observable<AuthResponse> {
    return this.http
      .post<AuthResponse>('/api/auth/register', payload)
      .pipe(tap((response) => this.persist(response)));
  }

  login(email: string, password: string): Observable<AuthResponse> {
    return this.http
      .post<AuthResponse>('/api/auth/login', { email, password })
      .pipe(tap((response) => this.persist(response)));
  }

  /**
   * Confirm a restored token is still valid, refreshing the cached profile.
   * Called once at startup; a failure logs the user out via the interceptor.
   */
  restoreSession(): Observable<UserMe> {
    return this.http.get<UserMe>('/api/auth/me').pipe(tap((user) => this.setUser(user)));
  }

  /** Keep the cached profile in step after a rename or avatar change. */
  setUser(user: UserMe): void {
    this.user.set(user);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  }

  logout(redirect = true): void {
    this.token.set(null);
    this.user.set(null);
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    if (redirect) {
      void this.router.navigate(['/login']);
    }
  }

  private persist(response: AuthResponse): void {
    this.token.set(response.access_token);
    localStorage.setItem(TOKEN_KEY, response.access_token);
    this.setUser(response.user);
  }
}

function readCachedUser(): UserMe | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw) as UserMe;
  } catch {
    // Corrupt storage should never break the app on boot.
    localStorage.removeItem(USER_KEY);
    return null;
  }
}
