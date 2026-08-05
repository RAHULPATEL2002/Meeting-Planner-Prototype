import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { App } from './app';
import { UserMe } from './core/models';

const USER: UserMe = {
  id: 1,
  email: 'alice@example.com',
  full_name: 'Alice Adams',
  avatar_url: null,
  timezone: 'UTC',
  created_at: '2026-08-01T10:00:00Z',
};

describe('App shell', () => {
  beforeEach(async () => {
    localStorage.clear();
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();
  });

  afterEach(() => localStorage.clear());

  it('creates', () => {
    expect(TestBed.createComponent(App).componentInstance).toBeTruthy();
  });

  it('hides the nav and user menu when signed out', () => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('.topbar__brand')).toBeTruthy();
    expect(element.querySelector('.topbar__nav')).toBeNull();
    expect(element.querySelector('.topbar__user')).toBeNull();
  });

  it('re-validates a restored token on boot and shows the user', () => {
    localStorage.setItem('mp.token', 'restored.token');
    localStorage.setItem('mp.user', JSON.stringify(USER));

    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();

    // The shell must confirm the token is still good rather than trusting cache.
    const controller = TestBed.inject(HttpTestingController);
    controller.expectOne('/api/auth/me').flush(USER);
    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('.topbar__nav')).toBeTruthy();
    expect(element.querySelector('.topbar__name')?.textContent).toContain('Alice Adams');
    controller.verify();
  });
});
