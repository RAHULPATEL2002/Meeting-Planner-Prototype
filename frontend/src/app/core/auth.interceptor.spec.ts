import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';

import { authInterceptor } from './auth.interceptor';
import { AuthService } from './auth.service';

describe('authInterceptor', () => {
  let http: HttpClient;
  let controller: HttpTestingController;
  let auth: AuthService;
  let router: Router;

  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem('mp.token', 'a.jwt.token');

    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });

    http = TestBed.inject(HttpClient);
    controller = TestBed.inject(HttpTestingController);
    auth = TestBed.inject(AuthService);
    router = TestBed.inject(Router);
    spyOn(router, 'navigate').and.resolveTo(true);
  });

  afterEach(() => {
    controller.verify();
    localStorage.clear();
  });

  it('adds the bearer token to API requests', () => {
    http.get('/api/meetings').subscribe();
    const request = controller.expectOne('/api/meetings');
    expect(request.request.headers.get('Authorization')).toBe('Bearer a.jwt.token');
    request.flush({ items: [], total: 0 });
  });

  it('leaves non-API requests untouched', () => {
    http.get('/assets/config.json').subscribe();
    const request = controller.expectOne('/assets/config.json');
    expect(request.request.headers.has('Authorization')).toBeFalse();
    request.flush({});
  });

  it('signs the user out and redirects on a 401 from a protected endpoint', () => {
    http.get('/api/meetings').subscribe({ error: () => undefined });
    controller
      .expectOne('/api/meetings')
      .flush({ detail: 'Could not validate credentials' }, { status: 401, statusText: 'Unauthorized' });

    expect(auth.isAuthenticated()).toBeFalse();
    expect(router.navigate).toHaveBeenCalledWith(
      ['/login'],
      jasmine.objectContaining({ queryParams: jasmine.objectContaining({ reason: 'expired' }) }),
    );
  });

  it('does NOT sign the user out when login itself returns 401', () => {
    // A wrong password must show an inline error, not bounce the page.
    http.post('/api/auth/login', {}).subscribe({ error: () => undefined });
    controller
      .expectOne('/api/auth/login')
      .flush({ detail: 'Incorrect email or password' }, { status: 401, statusText: 'Unauthorized' });

    expect(auth.isAuthenticated()).toBeTrue();
    expect(router.navigate).not.toHaveBeenCalled();
  });

  it('passes other error statuses through untouched', () => {
    let status = 0;
    http.get('/api/meetings/1').subscribe({ error: (e) => (status = e.status) });
    controller.expectOne('/api/meetings/1').flush({ detail: 'Meeting not found' }, { status: 404, statusText: 'Not Found' });

    expect(status).toBe(404);
    expect(auth.isAuthenticated()).toBeTrue();
  });
});
