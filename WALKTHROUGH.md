# Code walkthrough

A file-by-file tour of the project: what each file does, why it exists, and the
one or two decisions inside it worth defending.

---

## 1. The shape of the system

```
Browser (Angular 20, port 4200)
   │
   │  relative URLs: /api/... and /static/...
   │  dev server proxies both to :8000  (proxy.conf.json)
   ▼
FastAPI (uvicorn, port 8000)
   │
   ├── routers/    HTTP: parse → authorise → delegate → serialise
   ├── services/   business logic: meetings, avatars, iCalendar
   ├── schemas.py  pydantic validation, in and out
   ├── models.py   SQLAlchemy ORM
   │
   ├──► SQLite file   (meeting_planner.db)
   └──► local disk    (uploads/avatars/*.jpg, served at /static)
```

**One request, start to finish** — `POST /api/meetings`:

1. **CORS / routing** — Starlette matches the path to `routers/meetings.py:create_meeting`.
2. **Dependencies resolve first.** `CurrentUser` runs `get_current_user`, which
   decodes the JWT and loads the row. A bad token 401s here; the handler body
   never executes.
3. **Body validation.** FastAPI parses JSON into `MeetingCreate`. Field rules
   (title ≥ 3 chars) and model rules (`ends_at > starts_at`, duration limits, no
   duplicate invitees) run now. A failure is a 422 the handler never sees.
4. **Handler** delegates to `services.meetings.create_meeting`.
5. **Service** builds the ORM objects, resolves each invited email to an account
   if one exists, commits.
6. **Serialisation.** `serialise_detail` assembles the response, including
   viewer-specific data (`my_status`, `conflicts`).
7. **Response model.** `response_model=MeetingDetail` filters and shapes the
   output — a field not on the schema cannot leak, even if the service returns it.

> **Interview point:** steps 2–3 and 7 are why the handler bodies are three lines
> long. Validation and authorisation are declarative and happen at the edges.

---

## 2. Backend, file by file

### `app/config.py` — one place for every setting

A pydantic-settings `Settings` class. Every value has a working default, so a
fresh checkout runs with no `.env`; each can be overridden by an environment
variable.

- `@lru_cache` on `get_settings()` means the `.env` file is parsed once.
- Nothing else in the codebase touches `os.environ`. That is what lets the test
  suite reconfigure the app (temp database, temp uploads directory) just by
  setting env vars *before* importing it.
- Business rules live here too — `meeting_min_duration_minutes`,
  `meeting_max_participants` — so a policy change is a config change.

*Defend it:* "the default JWT secret is deliberately named
`insecure-dev-secret-change-me` so it is obvious in a diff if it ever reaches
production."

### `app/database.py` — engine, session, and the SQLite gotcha

```python
def enable_sqlite_foreign_keys(engine):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
```

**The single most important five lines in the backend.** SQLite ships with
foreign-key enforcement *off*. Without this, `ON DELETE CASCADE` is silently
ignored and deleting a meeting leaves orphaned participant rows. It hooks the
pool's `connect` event because the pragma is per-connection, not per-database.

Also here:
- `check_same_thread: False` — FastAPI runs sync endpoints in a thread pool, and
  SQLite otherwise refuses to share a connection across threads.
- `expire_on_commit=False` — lets a router serialise the object it just saved
  without SQLAlchemy issuing another SELECT.
- `get_db()` — the request-scoped session dependency. `try/finally` guarantees
  the session closes even if the handler raises.

### `app/models.py` — the domain

Three tables, SQLAlchemy 2.0 typed style (`Mapped[int]`, `mapped_column`).

```
users                meetings                    participants
─────                ────────                    ────────────
id                   id                          id
email (unique)  ┐    title                       meeting_id ──► meetings.id  (CASCADE)
full_name       │    description                 email
hashed_password │    location                    display_name
avatar_filename │    starts_at  (indexed)        user_id ──► users.id  (SET NULL, nullable)
timezone        │    ends_at                     status  (invited/accepted/declined/tentative)
created_at      └──► organizer_id                responded_at
                     created_at / updated_at     created_at
                                                 UNIQUE(meeting_id, email)
```

**The design decision to explain first:** `Participant` links a meeting to an
**email**, with an *optional* `user_id`.

- A plain many-to-many `User ↔ Meeting` cannot express "invite someone who has
  no account", which is most real invitations.
- So the email is the identity, and `user_id` is an enrichment. Present → show
  their name and avatar. Absent → they are a guest.
- `UNIQUE(meeting_id, email)` stops the same person being invited twice, *in the
  database*, so two concurrent requests cannot both slip through the application
  check.
- `ON DELETE SET NULL` on `user_id`: deleting an account must not delete the
  historical record that they were invited.

Other things worth pointing at:
- `CheckConstraint("ends_at > starts_at")` — the API validates this too, but the
  database is the last line of defence against a future code path.
- `Index("ix_meetings_window", "starts_at", "ends_at")` — the conflict query
  filters on both columns.
- `SAEnum(..., native_enum=False)` — stores the status as `VARCHAR`, so a new
  status needs no `ALTER TYPE` and SQLite is happy.
- **Properties, not columns:** `User.avatar_url`, `Meeting.duration_minutes`,
  `Participant.name`. Pydantic's `from_attributes` picks them up automatically,
  so derived data never gets stored — and never gets stale.

### `app/time_utils.py` — the timezone rule

Four small functions, one rule: **the database holds naive UTC.**

`to_utc_naive()` (inbound), `as_utc()` (outbound), `utcnow()`, and
`overlap_minutes()`.

*Why it matters:* SQLite cannot store an offset. Declaring
`DateTime(timezone=True)` would look correct and silently discard the offset —
so a user in Berlin creating a 09:00 meeting would have it stored as 09:00 UTC,
an hour wrong. Instead the conversion is explicit, in one file, with tests.

`overlap_minutes` uses **half-open intervals** `[start, end)`: a meeting ending
at 10:00 and one starting at 10:00 are back-to-back, not a conflict.

### `app/security.py` — passwords and tokens

Four functions and no framework imports, so it unit-tests without HTTP.

- **bcrypt** with a per-password random salt. `hash_password("x") != hash_password("x")`
  — there is a test for that.
- **The 72-byte limit.** bcrypt hashes at most 72 *bytes*. Truncating silently
  means `"correcthorse…" + 60 more chars` and a shorter password could
  authenticate identically. So we raise, and validate the same limit in the
  schema. A 25-emoji password is only 25 characters but 100 bytes — there is a
  test for that too.
- **JWT** carries only `sub` (the user id), `iat` and `exp`. No email, no role:
  embedded data outlives the change that invalidates it.
- `decode_access_token` converts every PyJWT failure into one `TokenError`, so
  callers cannot accidentally handle "expired" differently from "forged".

### `app/deps.py` — the authentication dependency

```python
def get_current_user(token, db) -> User:
    user_id = decode_access_token(token)   # raises -> 401
    user = db.get(User, user_id)
    if user is None:
        raise CREDENTIALS_EXCEPTION       # deleted account -> 401
    return user
```

**The database lookup is not optional.** A JWT stays cryptographically valid
until it expires, so a token belonging to a deleted account would otherwise still
work. `test_token_for_a_deleted_account_is_rejected` proves it does not.

`CurrentUser = Annotated[User, Depends(get_current_user)]` turns authentication
into a type annotation — `def handler(current_user: CurrentUser)` — which is both
the auth check and the documentation.

### `app/schemas.py` — the API contract

Why separate schemas from models at all? Because `User` has `hashed_password` and
`UserPublic` must not. The response model is a filter, not just a hint.

Notable pieces:

| Type | Purpose |
|---|---|
| `UtcDateTime` | `PlainSerializer` that renders every outbound datetime as `2026-08-10T09:00:00Z` |
| `InboundDateTime` | `AfterValidator(to_utc_naive)` — normalises every inbound datetime |
| `NormalisedEmail` | lower-cases and trims, so `ALICE@X.COM` and `alice@x.com` are one account |
| `Password` | 8–72 chars, plus a byte-length validator for the bcrypt limit |

`_validate_window()` is shared by create; `MeetingUpdate` deliberately does *not*
use it, because a partial update may change only `ends_at` and has to be checked
against the `starts_at` already in the database — that happens in the service
layer (`_assert_valid_window`), and `test_partial_update_validates_against_the_stored_window`
covers exactly that gap.

`RsvpRequest.status` is a `Literal` of three values, **excluding `invited`** —
"invited" is the initial state, not an answer a user can give.

### `app/services/meetings.py` — the interesting logic

- **`_involves(user)`** — the visibility predicate, reused by the list query, the
  detail fetch and the conflict search:
  ```python
  or_(Meeting.organizer_id == user.id,
      Meeting.participants.any(or_(Participant.user_id == user.id,
                                   Participant.email == user.email)))
  ```
  Matching on **both** account id and email means an invite sent before the guest
  signed up still resolves the moment they do.

- **`get_visible_meeting()`** applies `_involves` in the same query that fetches
  the row and raises **404** when nothing comes back. Not 403 — a 403 would
  confirm to a stranger that the meeting exists.

- **`_base_query()`** uses `selectinload` for participants and their users. Without
  it, rendering a 20-meeting list would fire an N+1 storm of queries.

- **`create_meeting()`** adds the organiser as participant #1 with status
  `accepted`, and silently skips them if they also appear in the invite list
  (people do that; a 409 would be hostile).

- **`find_conflicts()`** — the half-open overlap predicate, scoped to the viewer.

- **`serialise_summary` / `serialise_detail`** — assemble the response including
  viewer-specific fields (`my_status`, `is_organizer`, `conflicts`). The same
  meeting genuinely looks different to two people, which is why this is a
  function of `(meeting, viewer)` and not a plain `from_attributes` conversion.

### `app/services/avatars.py` — upload handling

The docstring is a four-point threat model; the code implements each point.

| Threat | Defence |
|---|---|
| Multi-gigabyte upload | `_read_limited()` reads in 64 KB chunks and aborts past 2 MB. `Content-Length` is client-supplied and can lie. |
| `Content-Type: image/png` on a shell script | Pillow must fully `load()` the bytes. Failure → 400. |
| `../../etc/passwd` as a filename | The client filename is discarded; the stored name is `uuid4().hex + ".jpg"`. |
| EXIF GPS, appended payloads | The image is decoded and **re-encoded**, so only pixels survive. |

`_to_square()` centre-crops *before* resizing, so a 400×200 photo becomes a
256×256 square rather than a squashed one.

`delete_avatar()` resolves the path and checks it is still inside the avatar
directory before unlinking — defence in depth, in case a bad value ever reaches
the database.

### `app/services/ics.py` — calendar export

Hand-written rather than a dependency, because the subset needed is 30 lines and
the two things implementations get wrong are worth owning:

- **`escape_text()`** escapes backslash **first**, then `;` `,` and newlines.
  Wrong ordering double-escapes and corrupts the output — there is a test.
- **`fold()`** wraps lines at 75 **octets** (not characters), continuing with a
  leading space, and never splits a multi-byte character across the boundary.

`PARTSTAT` maps our RSVP statuses onto the RFC's values (`invited` →
`NEEDS-ACTION`), so an accepted invite shows as accepted in a real calendar app.

### `app/routers/auth.py`

- `POST /register` — 409 on a duplicate email, then `_claim_pending_invites()`
  back-fills `user_id` on any `Participant` rows already addressed to that email.
  **This is why a newly-registered user who was invited last week sees the
  meeting immediately.** Registration returns a token, so sign-up signs you in.
- `POST /login` — identical error text and status for "no such user" and "wrong
  password", and it runs a bcrypt comparison against a dummy hash for unknown
  emails so **response timing does not leak which addresses are registered**.
- `POST /token` — the OAuth2 form variant. It exists purely so the Swagger
  "Authorize" button works and the whole API is explorable from `/docs`.

### `app/routers/users.py`

- `POST /me/avatar` writes the new file, commits, and *then* deletes the old one
  — so a failed upload never leaves a user with no avatar.
- `GET /users?q=` requires authentication. An open user-directory endpoint would
  let anyone harvest the address book.

### `app/routers/meetings.py`

Ten endpoints, all thin. Two subtleties:

- **`/conflicts` is declared before `/{meeting_id}`.** FastAPI matches routes in
  declaration order; the other way round, `conflicts` would be parsed as a
  meeting id. There is a test named after this exact trap.
- **`POST /meetings` returns the full `MeetingDetail`**, not just an id — so
  creating a meeting and landing on its page is one round trip, and the user
  immediately sees duration, participants and conflicts.

### `app/main.py`

App assembly: CORS, static mount, routers, lifespan, health check.

- **`lifespan`** creates the uploads directory and the tables before serving.
- **`IntegrityError` handler** turns a constraint violation into a **409** rather
  than a 500 — the race where two concurrent requests both pass the application's
  duplicate check.
- CORS is configured *and* the dev server proxies, so either setup works.

---

## 3. Backend tests — `backend/tests/` (115 tests, 98% coverage)

### `conftest.py` — the two tricks

1. **Environment is set before `app` is imported.** `Settings` is cached on first
   use, so `os.environ["UPLOAD_DIR"] = <temp>` has to happen at the top of the
   file, above the imports. Otherwise a test run would write into the developer's
   real database and uploads folder.
2. **Each test gets a private in-memory database.** `create_engine("sqlite://",
   poolclass=StaticPool)` — `StaticPool` keeps the single connection alive, so
   `:memory:` behaves like a real database for the test's lifetime. Injected via
   `app.dependency_overrides[get_db]`.

Factory fixtures (`register_user`, `alice`, `bob`, `meeting_payload`, `window`,
`png_bytes`) keep the tests about behaviour instead of setup.

### What is actually tested

| File | Focus |
|---|---|
| `test_security.py` | Salts differ, wrong password fails, 72-byte limit, expired / forged / subject-less tokens |
| `test_auth.py` | Registration validation, email normalisation, duplicate 409, **identical login errors**, deleted-account token, **invite claiming on sign-up** |
| `test_users_avatar.py` | Square-crop normalisation, non-image rejection, oversized 413, wrong type 415, **old file deleted on replace**, transparent PNG flattening, avatar visible on a meeting |
| `test_meetings.py` | Creation, organiser auto-accepted, **offset input stored as UTC**, every validation boundary, list scopes and ordering, **404-not-403**, organiser-only mutations, cascade delete |
| `test_participants_rsvp.py` | Invite, duplicate 409, organiser cannot be removed, every RSVP answer, `invited` rejected, **guest who signs up later can RSVP** |
| `test_conflicts.py` | Parametrised overlap table (partial / identical / contained / disjoint / **touching**), conflicts are per-viewer, preview endpoint, route-shadowing |
| `test_ics.py` | Escaping order, folding at 75 octets, multi-byte safety, endpoint headers, PARTSTAT reflects RSVP |

*Interview line:* "the happy paths are the boring half. The tests I would point
at are `test_back_to_back_meetings_are_not_conflicts`, `test_a_stranger_gets_404_not_403`,
and `test_password_longer_than_72_bytes_is_rejected` — each is a bug that would
have shipped."

---

## 4. Frontend, file by file

### `core/models.ts`
TypeScript mirrors of the API schemas. Hand-written — and the README lists
"generate these from OpenAPI" as the first frontend improvement, because
hand-written types can drift from the server.

### `core/auth.service.ts`
Session state in **signals**, mirrored to `localStorage`.

- `currentUser` is a readonly signal — templates re-render automatically, no
  manual subscription, no `async` pipe.
- The cached user is a **hint, not the truth**: `restoreSession()` re-validates
  the token against `/api/auth/me` on boot, because a token can expire while the
  tab is closed.
- `readCachedUser()` swallows a JSON parse failure. Corrupt storage must not
  brick the app on load.

### `core/auth.interceptor.ts`
A functional `HttpInterceptorFn`. Two jobs:

1. Attach `Authorization: Bearer …` to `/api/` requests (and only those).
2. Handle 401 centrally: clear the session and redirect to `/login?reason=expired`.

**The subtlety:** a 401 from `/api/auth/login` is a *legitimate answer* — wrong
password — and must pass through untouched. The first version did not make that
distinction and bounced you off the login page while you were trying to log in.
`does NOT sign the user out when login itself returns 401` locks that down.

### `core/auth.guard.ts`
`authGuard` protects routes and stores `returnUrl`; `guestGuard` keeps signed-in
users off the login screen. The comment says it out loud: **this is UX, not
security.** Every protected resource is enforced server-side.

### `core/datetime.ts`
The client half of the timezone rule.

`<input type="datetime-local">` produces `2026-08-10T09:00` with **no zone** — it
means "09:00 where the user is". `new Date('2026-08-10T09:00')` is parsed as
local time per the ES spec, so `.toISOString()` gives the correct absolute
instant. The reverse function rebuilds the local wall-clock string.

The tests assert the **round trip** rather than a hard-coded UTC value, because
the correct answer depends on the machine's timezone — a test that only passes in
one zone is worse than no test.

Also: `formatDuration` (`90 → "1h 30m"`, `60 → "1h"` with no stray "0m"),
`formatRange`, and `formatRelative` using `Intl.RelativeTimeFormat`.

### `core/api-error.ts`
Turns any FastAPI error body into one readable sentence.

FastAPI's `detail` is a **string** for `HTTPException` but an **array of
`{loc, msg}` objects** for pydantic validation failures. Rendering that array
straight into the DOM is how you show `[object Object]` to a user. This flattens
it, drops the leading `"body"` from `loc`, strips pydantic's `"Value error, "`
prefix, and gives status 0 a human explanation ("is the backend running?").

### `core/meeting.service.ts` / `core/user.service.ts`
Typed HTTP wrappers, no cached state. Two details worth mentioning:

- **`uploadAvatar` sets no `Content-Type` header.** The browser must set it
  itself so it can append the multipart boundary — setting it by hand is the
  classic way to break a file upload.
- **`downloadIcs` fetches a blob** rather than using `<a download>`, because a
  plain link cannot send the `Authorization` header.

### `shared/avatar.component.ts`
`OnPush`, signal inputs. The initials fallback is the **common case**, not an
error case — most participants have no picture and some have no account. The
background colour is hashed from the name, so a person's tile is stable
everywhere without storing anything.

### `shared/status-badge.component.ts`
RSVP pill. Colour reinforces the label; the **text** carries the meaning, so it
still works for a colour-blind user.

### `pages/login.component.ts` / `register.component.ts`
Reactive forms with per-field errors shown only after `dirty || touched` — no
shouting at someone before they have typed. On invalid submit,
`markAllAsTouched()` reveals *which* field is wrong instead of a form that
silently refuses. Registration captures the browser timezone and lands on
`/profile`, where uploading an avatar is the obvious next step.

### `pages/profile.component.ts`
Avatar upload with client-side type/size checks that **mirror** the server's —
fail fast for the user, while the server still enforces them because anyone can
POST directly. Resets `input.value` after each attempt so re-selecting the same
file fires `change` again (a real browser quirk).

### `pages/meeting-list.component.ts`
Upcoming / Past / All tabs, each a separate request. Distinct empty states for
"no meetings yet" and "nothing in the past". A meeting still in progress counts
as upcoming — decided server-side (`ends_at >= now`), not in the UI.

### `pages/meeting-create.component.ts`
The most interesting screen.

- **Invitee picker:** debounced type-ahead over `/api/users` using `switchMap`,
  which cancels the in-flight request so a slow response cannot overwrite a newer
  one. Any email can also be typed freely — that is the guest path.
- **Live conflict preview:** `form.valueChanges` → `debounceTime(400)` →
  `/api/meetings/conflicts`. You find out you are double-booked *before*
  creating the meeting, and it is a warning, not a block — sometimes you really
  do need to overlap.
- **Quick-duration chips** (15/30/60/120 min) set the end from the start.
- Both `takeUntilDestroyed()` — no leaked subscriptions.

### `pages/meeting-detail.component.ts`
This is the exercise's "useful meeting details after a meeting is created":

Duration and relative time · live/upcoming/finished chip (a `computed` signal) ·
organiser with avatar · RSVP buttons showing your current answer · **conflict
warnings linking to the clashing meeting** · a proportional RSVP summary bar ·
the full roster with avatars, badges and guest markers · inline invite and remove
for the organiser · `.ics` download · cancel with confirmation.

Everything comes from **one** `GET /api/meetings/{id}`.

### `app.ts` / `app.html` / `app.config.ts` / `app.routes.ts`
The shell: top bar, avatar, sign-out. `app.config.ts` registers the router and
`provideHttpClient(withInterceptors([authInterceptor]))`.

Routes use **`loadComponent`** for every page, so the login screen — the only
page an anonymous visitor sees — does not ship the meeting pages. The build
output confirms it: separate lazy chunks per route. `meetings/new` is declared
before `meetings/:id` so the literal segment wins.

---

## 5. Frontend tests (36, headless Chrome)

| File | Focus |
|---|---|
| `datetime.spec.ts` | Local↔UTC round trip, midnight crossing, zero-padding, duration formatting |
| `api-error.spec.ts` | String detail, pydantic array flattening, `"Value error, "` stripping, status 0, **never renders `[object Object]`** |
| `auth.service.spec.ts` | Login stores token + user, failed login stores nothing, logout clears everything, restore from storage, **corrupt cache does not crash boot** |
| `auth.interceptor.spec.ts` | Token attached to `/api/` only, 401 signs out and redirects, **login 401 does not**, other statuses pass through |
| `avatar.component.spec.ts` | Image when URL present, initials fallback, single-word names, empty name, **stable colour per person**, `aria-label` |
| `app.spec.ts` | Nav hidden when signed out, token re-validated on boot |

---

## 6. Five flows, end to end

**Sign up →** `RegisterComponent` posts to `/api/auth/register` → 409 if the email
exists → bcrypt hash → `_claim_pending_invites()` links pending invites → token
returned → `AuthService` stores it → redirect to `/profile`.

**Avatar →** file picked → client checks type and size → `FormData` POST (no
manual `Content-Type`) → server checks type, reads ≤ 2 MB in chunks, decodes with
Pillow, centre-crops, resizes to 256², re-encodes as JPEG → saved as
`<uuid>.jpg` → old file deleted → `avatar_url` derived from the filename → served
from `/static/avatars/`.

**Create a meeting →** local times converted to UTC ISO → `MeetingCreate`
validates the window and invite list → organiser added as accepted → each invited
email resolved to an account if one exists → committed → **full detail returned**
→ router navigates straight to the detail page.

**RSVP →** participant clicks Going → `POST /rsvp` → `get_visible_meeting` (404 if
they cannot see it) → `set_rsvp` finds their row by account **or email**,
late-binds `user_id` on first interaction, records the answer and timestamp →
returns the refreshed detail, so the summary bar updates in the same round trip.

**Conflict detection →** on the create form, debounced calls to
`/api/meetings/conflicts`; on the detail page, computed inside
`serialise_detail`. Both use the same `find_conflicts`, the same `_involves`
visibility predicate and the same half-open overlap test, scoped to the viewer.

---

## 7. Questions you should expect

**"Why not a many-to-many between users and meetings?"**
It cannot express inviting someone without an account, which is most invitations.
`Participant` keys on email with an optional `user_id`; registering claims
pending invites.

**"Why naive UTC instead of timezone-aware columns?"**
SQLite cannot store an offset, so an aware column would silently discard it. One
explicit rule in `time_utils.py`, applied at both boundaries, with tests. On
Postgres I would use `timestamptz` and delete that module.

**"Why 404 instead of 403?"**
403 confirms the meeting exists. Visibility is filtered in the same query that
fetches the row, so unauthorised and non-existent are indistinguishable.

**"Is a JWT in localStorage safe?"**
It is the standard prototype trade-off: stateless, no CSRF surface, but readable
by any XSS. The upgrade is a refresh token in an `HttpOnly` cookie plus a
short-lived in-memory access token — listed in the README's limitations.

**"How do you know the file upload is really an image?"**
I do not trust the header. Pillow must fully decode the bytes, and the image is
re-encoded, which also strips EXIF GPS data and any appended payload.

**"What would break first at scale?"**
SQLite write concurrency, then the unpaginated meetings list. Both are noted;
neither is worth fixing in a prototype.

**"What did you leave out, and why?"**
The meeting edit UI (the API and tests exist; the form did not fit the timebox),
migrations, and email delivery. The timebox went to the data model, the timezone
boundary, conflict detection, and the tests around them — because those are the
parts that are expensive to get wrong later.

**"What are you least happy with?"**
Hand-written TypeScript models. They can drift from the server contract, and the
fix — generating them from the OpenAPI document FastAPI already publishes — is
cheap. It is first on the improvements list.
