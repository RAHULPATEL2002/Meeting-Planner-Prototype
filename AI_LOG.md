# AI usage log

The exercise permits AI tooling and asks for a record of it. This is that record.

**Tool:** Claude (Claude Code, in VS Code), used as a pair-programmer for the
whole build. **Everything committed here was read, run and verified by me** —
the test suites, the lint run and a live end-to-end smoke test against a running
server all pass, and several things the model produced first time were wrong and
had to be corrected (listed at the bottom).

---

## 1. Framing the problem

> Build a meeting planner prototype: FastAPI + SQLite + Angular, sign-up/login,
> avatar upload, and useful meeting details after creation. Timebox 2–3 hours.
> Before writing code, decide what a "participant" is, and what "useful meeting
> details" should mean. Give me the trade-offs, not a survey.

This produced the decision that shaped everything else: **a participant is an
email address that may or may not resolve to an account.** The alternative — a
plain many-to-many between `User` and `Meeting` — is simpler but cannot express
"invite someone who hasn't signed up", which is the normal case. See the README's
design-decisions section.

## 2. Data model

> Draft the SQLAlchemy 2.0 models for User / Meeting / Participant. Where do
> constraints belong — application, database, or both? Assume SQLite.

Useful output: the composite unique constraint on `(meeting_id, email)`, and the
reminder that **SQLite ignores foreign keys unless `PRAGMA foreign_keys=ON` is
set on every connection** — hooked into the engine's `connect` event in
`app/database.py`, with `test_deleting_a_meeting_removes_its_participants`
proving it actually works.

## 3. The timezone boundary

> SQLite has no timezone-aware storage. Give me one rule for handling datetimes
> across DB / API / browser, and the failure mode if I get it wrong.

Result: store naive UTC, normalise on the way in, re-attach `Z` on the way out
(`app/time_utils.py`), and convert local↔UTC in exactly one place on the client
(`core/datetime.ts`). Both have dedicated tests — `test_timezone_offset_input_is_stored_as_utc`
asserts `09:00+02:00` is stored as `07:00Z`, which is the exact bug this prevents.

## 4. Conflict detection

> Write the overlap query for "meetings this user is part of that clash with
> [start, end)". Enumerate the edge cases I should be testing.

Gave the half-open interval predicate (`existing.starts_at < new_end AND
existing.ends_at > new_start`) and the case I would most likely have missed:
**back-to-back meetings must not count as a conflict.** That is now
`test_back_to_back_meetings_are_not_conflicts`, plus a parametrised table over
partial / identical / contained / disjoint / touching windows.

## 5. Upload security

> Threat-model an avatar upload endpoint. What does a malicious client try, and
> what does each defence actually buy me?

Produced the four-point threat model now documented at the top of
`app/services/avatars.py`: bounded chunked reads (`Content-Length` can lie),
decode-don't-trust (a `Content-Type` header proves nothing), UUID filenames (no
path traversal), and re-encoding (drops EXIF/GPS and any appended payload).

## 6. Angular structure

> Angular 20 standalone + signals. Where does auth state live, how is the token
> attached, and how should a 401 be handled globally?

Gave the shape used: signal-backed `AuthService` mirrored to `localStorage`, a
functional `HttpInterceptorFn` for the bearer header, and centralised 401
handling. **I corrected one thing here:** the first version logged the user out
on *any* 401, including a wrong password on the login screen — which bounced you
to `/login` mid-sign-in. Fixed, and pinned by
`does NOT sign the user out when login itself returns 401`.

## 7. Tests

> What edge cases would a reviewer expect to see tested here, that a happy-path
> suite would miss?

Most of the security and boundary tests came out of this: 404-not-403 for
meetings you cannot see, identical error text for unknown-email vs wrong-password
login, a token that outlives its user, bcrypt's 72-**byte** limit versus a
72-**character** password (a 25-emoji password is 100 bytes), `invited` not being
a valid RSVP answer, and re-uploading an avatar deleting the old file.

## 8. Documentation

> Write the README: how to run, how to test, design decisions, assumptions,
> known limitations, what's next. Be specific about what is *not* done.

Drafted by the model, then edited for accuracy — several "limitations" it listed
were things I had actually implemented, and several real ones (no pagination, no
edit UI, avatars being public-by-URL) I had to add myself.

---

## Where the AI was wrong, and how I caught it

| Problem | How it surfaced | Fix |
|---|---|---|
| The `.ics` test asserted an `ATTENDEE` line as one substring | Test failed on first run | The line was correctly folded at 75 octets per RFC 5545 — **the test was wrong, not the code.** Added an `unfold()` helper that reverses folding the way a calendar client does. |
| 401 interceptor logged the user out during a failed login | Manual click-through | Excluded the auth endpoints; added a regression test. |
| Deprecated Starlette status constants (`HTTP_422_UNPROCESSABLE_ENTITY`) | `DeprecationWarning` in the pytest output | Switched to the current names; the suite now runs warning-free. |
| First `login()` implementation returned early for an unknown email | Code review | Unknown emails now still run a bcrypt comparison against a dummy hash, so response timing doesn't leak which addresses are registered. |
| Suggested `passlib[bcrypt]` | Known version incompatibility with bcrypt 4.x | Used the `bcrypt` package directly — fewer layers, and the 72-byte limit is handled explicitly rather than silently. |
| README overstated what was finished | Read it against the code | Rewrote the limitations section; added the missing edit-UI gap. |

## What I did not delegate

Choosing the domain model, the access-control rules (organiser-only mutations,
404 for invisible meetings), the business constraints (5 min – 7 days, 50
participants), what belongs on the detail page, and the scope cuts. Those are the
decisions the exercise is actually asking about.

## Verification performed

- `pytest` — 115 passed, no warnings; `--cov=app` reports 98% line coverage.
- `ruff check .` — clean.
- `npm run test:ci` — 36 passed (headless Chrome).
- `ng build` — clean, with per-route lazy chunks.
- A scripted end-to-end run against a live `uvicorn` server: register → upload an
  avatar → fetch it back over HTTP → create a meeting → create an overlapping one
  and confirm the 30-minute conflict → RSVP → download the `.ics` → confirm 401
  without a token, 403 for a non-organiser edit, and 422 for a reversed time
  window.
