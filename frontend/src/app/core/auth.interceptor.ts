import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';

import { AuthService } from './auth.service';

/**
 * Attaches the bearer token to same-origin API calls and centralises 401
 * handling, so no component has to think about either.
 *
 * A 401 on the login/register endpoints is a genuine "wrong password" answer
 * and must be passed through untouched; a 401 anywhere else means the token has
 * expired or been revoked, so we clear the session and bounce to /login.
 */
export const authInterceptor: HttpInterceptorFn = (request, next) => {
  const auth = inject(AuthService);
  const router = inject(Router);

  const token = auth.accessToken;
  const isApiCall = request.url.startsWith('/api/');
  const authenticated =
    token && isApiCall
      ? request.clone({ setHeaders: { Authorization: `Bearer ${token}` } })
      : request;

  return next(authenticated).pipe(
    catchError((error: HttpErrorResponse) => {
      const isCredentialCheck =
        request.url.includes('/api/auth/login') || request.url.includes('/api/auth/register');

      if (error.status === 401 && !isCredentialCheck) {
        auth.logout(false);
        void router.navigate(['/login'], {
          queryParams: { returnUrl: router.url, reason: 'expired' },
        });
      }
      return throwError(() => error);
    }),
  );
};
