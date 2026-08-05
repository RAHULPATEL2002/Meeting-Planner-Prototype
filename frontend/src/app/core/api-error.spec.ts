import { HttpErrorResponse } from '@angular/common/http';

import { describeApiError } from './api-error';

function httpError(status: number, body: unknown): HttpErrorResponse {
  return new HttpErrorResponse({ status, error: body, statusText: 'Error' });
}

describe('describeApiError', () => {
  it('passes through a plain string detail from HTTPException', () => {
    expect(describeApiError(httpError(409, { detail: 'That email is already invited' }))).toBe(
      'That email is already invited',
    );
  });

  it('flattens pydantic validation arrays into readable text', () => {
    const error = httpError(422, {
      detail: [
        { loc: ['body', 'title'], msg: 'String should have at least 3 characters' },
        { loc: ['body', 'participants', 0, 'email'], msg: 'value is not a valid email address' },
      ],
    });

    expect(describeApiError(error)).toBe(
      'title: String should have at least 3 characters; ' +
        'participants.email: value is not a valid email address',
    );
  });

  it('strips pydantic’s "Value error, " prefix', () => {
    const error = httpError(422, {
      detail: [{ loc: ['body'], msg: 'Value error, Meeting must end after it starts' }],
    });
    expect(describeApiError(error)).toBe('Meeting must end after it starts');
  });

  it('explains a status 0 as the backend being unreachable', () => {
    expect(describeApiError(httpError(0, null))).toContain('Cannot reach the API');
  });

  it('falls back for non-HTTP errors', () => {
    expect(describeApiError(new Error('boom'), 'Fallback')).toBe('Fallback');
  });

  it('never renders "[object Object]"', () => {
    const error = httpError(422, { detail: [{ loc: ['body', 'x'], msg: 'bad' }] });
    expect(describeApiError(error)).not.toContain('[object Object]');
  });
});
