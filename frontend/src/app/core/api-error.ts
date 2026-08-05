import { HttpErrorResponse } from '@angular/common/http';

/**
 * Turns any FastAPI error body into one sentence a user can read.
 *
 * FastAPI's `detail` is a plain string for handled errors (`raise
 * HTTPException(detail="...")`) but an array of `{loc, msg}` objects for
 * pydantic validation failures — rendering that array straight into the DOM is
 * how you end up showing `[object Object]` to a user.
 */
export function describeApiError(error: unknown, fallback = 'Something went wrong'): string {
  if (!(error instanceof HttpErrorResponse)) {
    return fallback;
  }

  if (error.status === 0) {
    return 'Cannot reach the API. Is the backend running on port 8000?';
  }

  const detail = error.error?.detail;

  if (typeof detail === 'string') {
    return detail;
  }

  if (Array.isArray(detail)) {
    return detail
      .map((item: { loc?: (string | number)[]; msg?: string }) => {
        // loc looks like ["body", "participants", 0, "email"] — the first entry
        // is the request part, which means nothing to a user.
        const field = (item.loc ?? []).slice(1).filter((p) => typeof p === 'string').join('.');
        const message = (item.msg ?? 'is invalid').replace(/^Value error, /, '');
        return field ? `${field}: ${message}` : message;
      })
      .join('; ');
  }

  return error.statusText || fallback;
}
