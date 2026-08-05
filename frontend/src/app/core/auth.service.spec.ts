import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { AuthService } from './auth.service';
import { AuthResponse } from './models';

const RESPONSE: AuthResponse = {
  access_token: 'a.jwt.token',
  token_type: 'bearer',
  expires_in: 3600,
  user: {
    id: 1,
    email: 'alice@example.com',
    full_name: 'Alice Adams',
    avatar_url: null,
    timezone: 'UTC',
    created_at: '2026-08-01T10:00:00Z',
  },
};

describe('AuthService', () => {
  let service: AuthService;
  let http: HttpTestingController;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    service = TestBed.inject(AuthService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    localStorage.clear();
  });

  it('starts signed out when storage is empty', () => {
    expect(service.isAuthenticated()).toBeFalse();
    expect(service.currentUser()).toBeNull();
  });

  it('stores the token and user after a successful login', () => {
    service.login('alice@example.com', 'secret').subscribe();

    const request = http.expectOne('/api/auth/login');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ email: 'alice@example.com', password: 'secret' });
    request.flush(RESPONSE);

    expect(service.isAuthenticated()).toBeTrue();
    expect(service.currentUser()?.full_name).toBe('Alice Adams');
    expect(service.accessToken).toBe('a.jwt.token');
    expect(localStorage.getItem('mp.token')).toBe('a.jwt.token');
  });

  it('does not sign the user in when login fails', () => {
    service.login('alice@example.com', 'wrong').subscribe({ error: () => undefined });
    http.expectOne('/api/auth/login').flush(
      { detail: 'Incorrect email or password' },
      { status: 401, statusText: 'Unauthorized' },
    );

    expect(service.isAuthenticated()).toBeFalse();
    expect(localStorage.getItem('mp.token')).toBeNull();
  });

  it('clears everything on logout', () => {
    service.login('alice@example.com', 'secret').subscribe();
    http.expectOne('/api/auth/login').flush(RESPONSE);

    service.logout(false);

    expect(service.isAuthenticated()).toBeFalse();
    expect(service.currentUser()).toBeNull();
    expect(localStorage.getItem('mp.token')).toBeNull();
    expect(localStorage.getItem('mp.user')).toBeNull();
  });

  it('restores a session from localStorage on construction', () => {
    localStorage.setItem('mp.token', 'restored.token');
    localStorage.setItem('mp.user', JSON.stringify(RESPONSE.user));
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });

    const restored = TestBed.inject(AuthService);
    expect(restored.isAuthenticated()).toBeTrue();
    expect(restored.currentUser()?.email).toBe('alice@example.com');

    http = TestBed.inject(HttpTestingController);
  });

  it('survives corrupt cached user data instead of crashing on boot', () => {
    localStorage.setItem('mp.token', 'restored.token');
    localStorage.setItem('mp.user', '{not json');
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });

    const restored = TestBed.inject(AuthService);
    expect(restored.currentUser()).toBeNull();
    // The token is still present, so `restoreSession()` will re-fetch the profile.
    expect(restored.isAuthenticated()).toBeTrue();

    http = TestBed.inject(HttpTestingController);
  });
});
