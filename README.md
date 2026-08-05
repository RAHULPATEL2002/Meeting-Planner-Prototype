# Meeting Planner — prototype

A small meeting planner: sign up, upload an avatar, create meetings, invite people
by email, and see useful detail about a meeting once it exists — duration, who has
replied, and whether it clashes with anything else on your calendar.

**Stack:** Python 3.12 · FastAPI · SQLAlchemy 2 · SQLite · Angular 20 (standalone
components + signals) · pytest · Jasmine/Karma.

```
.
├── backend/          FastAPI application, SQLite database, pytest suite
│   ├── app/
│   │   ├── routers/  HTTP layer (auth, users, meetings)
│   │   └── services/ business logic (meetings, avatars, iCalendar)
│   └── tests/        115 tests
├── frontend/         Angular client
│   └── src/app/
│       ├── core/     services, models, HTTP interceptor, route guards
│       ├── pages/    routed screens
│       └── shared/   reusable presentational components
├── AI_LOG.md         how AI tooling was used
└── WALKTHROUGH.md    file-by-file tour of the codebase
```

---

## Running it locally

You need **Python 3.12+**, **Node 20.19+ / 22.12+ / 24+**, and (for the frontend
tests) a Chrome-based browser. Two terminals.

### 1. Backend — http://127.0.0.1:8000

```bash
cd backend

python -m venv .venv
# Windows PowerShell:  .\.venv\Scripts\Activate.ps1
# Windows Git Bash:    source .venv/Scripts/activate
# macOS / Linux:       source .venv/bin/activate
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The database file and the `uploads/` folder are created automatically on first
start. No migrations to run, no `.env` needed — every setting has a working
default (see `backend/.env.example` to override any of them).

Interactive API docs: **http://127.0.0.1:8000/docs** — the "Authorize" button
works, so you can exercise the whole API without the UI.

### 2. Frontend — http://localhost:4200

```bash
cd frontend
npm install
npm start
```

Open http://localhost:4200 and create an account.

> The dev server proxies `/api` and `/static` to port 8000 (`proxy.conf.json`),
> so the browser only ever talks to one origin. Start the backend first.

---

## Running the tests

```bash
# Backend — 115 tests
cd backend
pip install -r requirements-dev.txt
pytest                                  # or: pytest -v
pytest --cov=app --cov-report=term-missing   # 98% line coverage
ruff check .                            # lint

# Frontend — 36 tests
cd frontend
npm run test:ci                         # headless Chrome, exits when done
npm test                                # watch mode, opens a browser
```

Backend tests need no running server and no database setup: each test gets its
own in-memory SQLite database and a temporary uploads directory.

---

## What it does

| Area | Behaviour |
|---|---|
| **Accounts** | Email + password sign-up and sign-in, bcrypt hashes, JWT bearer tokens. |
| **Avatars** | Upload JPEG/PNG/WebP/GIF up to 2 MB. Re-encoded to a 256×256 JPEG. Initials fallback everywhere else. |
| **Meetings** | Title, agenda, location, start/end. Created by an organiser who is automatically an accepted participant. |
| **Invitations** | Invite anyone **by email**. If that email has an account, the participant is linked to it (name + avatar appear). If not, they are a "guest" — and the invite is claimed automatically if they sign up later. |
| **RSVP** | Going / Maybe / Not going, with a live response breakdown. |
| **Meeting detail** | Duration, relative time, live/upcoming/finished state, participant roster, RSVP summary bar, **conflicts with your other meetings**, `.ics` download. |
| **Conflicts** | Checked live while you fill in the create form, and shown again on the detail page. |

### API surface

```
POST   /api/auth/register        create account, returns a token
POST   /api/auth/login           email + password  -> token
POST   /api/auth/token           OAuth2 form variant (for Swagger UI)
GET    /api/auth/me              current user

PATCH  /api/users/me             update name / timezone
POST   /api/users/me/avatar      multipart upload
DELETE /api/users/me/avatar      remove avatar
GET    /api/users?q=             search accounts (invitee autocomplete)

GET    /api/meetings?scope=      upcoming | past | all
POST   /api/meetings             create (returns the full detail payload)
GET    /api/meetings/conflicts   preview clashes for a proposed window
GET    /api/meetings/{id}        detail: participants, summary, conflicts
PATCH  /api/meetings/{id}        organiser only
DELETE /api/meetings/{id}        organiser only
POST   /api/meetings/{id}/participants          invite
DELETE /api/meetings/{id}/participants/{pid}    withdraw
POST   /api/meetings/{id}/rsvp                  respond
GET    /api/meetings/{id}/calendar.ics          iCalendar export

GET    /api/health
```

---

## Design decisions

**Participants are email addresses, not user ids.**
The obvious model is `participants: many-to-many(User, Meeting)`, but that makes
it impossible to invite someone who has not signed up — which is most of the
people you invite to a real meeting. So a `Participant` row always carries an
email and *optionally* a `user_id`. When the email matches an account we link it
and show their name and avatar; otherwise they are a guest. Registering claims
any pending invites for that address, so a new user's dashboard is not empty.
This one decision is why invitation, avatar display and access control all work
the way they do.

**All timestamps are naive UTC in the database.**
SQLite cannot store an offset, so `DateTime(timezone=True)` would quietly lie.
Instead there is exactly one rule (`app/time_utils.py`): inbound datetimes are
converted to UTC and stripped, outbound datetimes get UTC re-attached and
serialise as `...Z`. The browser converts to and from local wall-clock time in
`core/datetime.ts`. Both sides have tests, because this is the single most
common source of calendar bugs.

**A thin router layer over a service layer.**
Routers parse, authorise, delegate and serialise — nothing else. Conflict
detection, invite resolution and image processing live in `app/services/` and
are tested through the API but written so they could be reused by, say, a CLI or
a background job.

**Missing meetings return 404, not 403.**
Answering 403 for a meeting you are not invited to confirms that it exists.
`get_visible_meeting` filters by visibility in the same query that fetches the
row, so unauthorised and non-existent are indistinguishable from outside.

**Uploads are decoded, not trusted.**
`Content-Type: image/png` is a claim, not a fact. Every avatar is read in bounded
chunks (so a huge upload is rejected before it lands), fully decoded by Pillow,
centre-cropped, resized and *re-encoded*. That drops EXIF (including GPS), kills
any polyglot payload appended to a valid image, and normalises everything to one
format. The stored filename is a UUID; the client's filename is never used.

**The detail endpoint returns everything the page needs.**
`GET /api/meetings/{id}` includes participants, the RSVP summary and the viewer's
conflicts. `POST /api/meetings` returns the same shape, so creating a meeting and
landing on its detail page costs one request, not three. Conflicts are computed
per-viewer: whether *you* are double-booked is the useful question.

**Auth is a JWT in `localStorage`, sent as a bearer header.**
Simple, stateless, and no CSRF surface because nothing is cookie-based. The
trade-off — XSS can read the token — is noted under limitations.

**Hand-written iCalendar export.**
The subset needed is ~30 lines; the two things implementations get wrong (TEXT
escaping and 75-octet line folding) are exactly the parts worth owning and
testing, rather than adding a dependency for.

**No CSS framework.**
A dozen custom properties and a handful of utility classes cover a UI this size,
including dark mode, without a 300 kB dependency.

---

## Assumptions

- **One organiser per meeting.** They alone can edit it, cancel it, or change the
  invite list. No co-hosts, no delegation.
- **Nothing is emailed.** "Inviting" someone records the invitation; they see it
  when they sign in. Sending mail would need infrastructure the exercise
  explicitly excludes.
- **Anyone signed in can look up other users** by name or email for the invitee
  picker. In a real product this would be scoped to an organisation.
- **A datetime with no timezone means UTC.** The API accepts both; the Angular
  client always sends an explicit offset.
- **Business rules:** meetings last 5 minutes to 7 days, hold at most 50
  participants, and may be created in the past (useful for recording something
  that already happened).
- **Local single-user development.** SQLite with default settings is fine for
  one process; it is not a concurrency story.
- **Avatars are public-by-URL.** Filenames are unguessable UUIDs, but the file
  itself is served without an auth check.

---

## Known limitations

- **No schema migrations.** Tables are created with `create_all()` at startup.
  Changing a model means deleting `meeting_planner.db`. Alembic is the fix.
- **No token refresh or revocation.** A token is valid for 12 hours; signing out
  only forgets it client-side. There is no deny-list.
- **JWT in `localStorage`** is readable by any XSS. A refresh token in an
  `HttpOnly` cookie plus a short-lived in-memory access token is the upgrade.
- **Avatar files are not access-controlled** — anyone with the URL can fetch one.
- **No pagination.** `GET /api/meetings` returns every matching row. Fine for a
  prototype, wrong at a thousand meetings.
- **No recurring meetings, no reminders, no attachments, no calendar sync.**
- **Editing a meeting is API-only.** `PATCH /api/meetings/{id}` works and is
  tested, but the UI has no edit form yet — you can cancel and recreate.
- **Timezone is stored but only cosmetic**: everything renders in the browser's
  local zone rather than the profile's zone.
- **No rate limiting** on login, so password guessing is only slowed by bcrypt.
- **Frontend tests need Chrome** (Karma launches `ChromeHeadless`).
- **Frontend types are hand-written**, so they can drift from the API contract.

---

## What I would do next, in priority order

1. **Alembic migrations** — the first thing that hurts once anyone else runs it.
2. **Generate the TypeScript client from the OpenAPI schema** so the frontend
   types cannot drift from the backend. FastAPI already publishes it.
3. **An edit screen** for meetings, reusing the create form and passing
   `exclude_meeting_id` to the conflict preview (the API already supports it).
4. **Playwright end-to-end tests** covering sign-up → avatar → create → RSVP.
   The unit tests cover the pieces; nothing yet covers the seams.
5. **Refresh tokens in `HttpOnly` cookies**, plus rate limiting on `/auth/login`.
6. **Pagination and a calendar/week view** instead of a flat list.
7. **Free/busy suggestions** — the conflict query already answers "is X busy at
   time T"; inverting it into "when are we all free?" is the natural next
   feature and the most valuable one for users.
8. **Real invitation emails** with an accept/decline link that works without an
   account.
9. **Structured logging and a request id**, so a failed request can be traced.

---

## Notes on the exercise

Roughly three hours. What got the time: the participant/invite data model, the
timezone boundary, conflict detection, and the tests around all three. What got
deliberately less: styling (hand-rolled CSS, no component library), and meeting
editing in the UI.

See **[AI_LOG.md](AI_LOG.md)** for how AI tooling was used, and
**[WALKTHROUGH.md](WALKTHROUGH.md)** for a file-by-file tour.
