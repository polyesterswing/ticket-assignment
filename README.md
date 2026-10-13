# clearfeed: ticket assignment

A service that assigns incoming support tickets to the fairest available agent,
and a UI for team leads to manage when their agents work.

- **Assignment API:** given a `company_id` and `ticket_id`, picks an agent who is in
  a shift right now and below the active ticket limit, preferring the least loaded,
  or explains why nobody is available.
- **Availability UI:** agents' timezones and weekly shifts, the hours the company
  needs covered, the gaps in coverage, and a log explaining every assignment.

The product requirements and technical design are in [`docs/prd.md`](docs/prd.md)
and [`docs/implementation.md`](docs/implementation.md).

## Quick start

Requirements: [Docker](https://docs.docker.com/get-docker/) with Compose, and
[uv](https://docs.astral.sh/uv/) (it installs Python 3.13 if needed).

```sh
docker compose up -d --wait          # Postgres 18 on localhost:5432
uv run alembic upgrade head          # create the schema
uv run python scripts/seed.py        # demo companies, agents, shifts, required hours
uv run clearfeed                     # serve on http://127.0.0.1:8000
```

- UI: <http://127.0.0.1:8000>
- API docs (OpenAPI): <http://127.0.0.1:8000/docs>

The seed script can be rerun at any time; it resets companies, agents, shifts and
required hours to the demo values.

### Demo data

| Company | Timezone | Agents |
|---|---|---|
| Acme Support (id 1) | Europe/London | Priya and Arjun (Asia/Kolkata, Mon–Fri 09:00–17:00), Maria (America/Los_Angeles, Mon 09:00–17:00, the PRD example), Tom (Europe/London, Mon 22:00–06:00 overnight) |
| Globex (id 2) | America/New_York | Lena (America/New_York, Mon–Fri 08:00–16:00), Kenji (Asia/Tokyo, Mon–Fri 09:00–17:00) |

Required hours: Acme Mon–Fri 08:00–20:00 London time; Globex Mon–Fri 09:00–17:00 New York time.

### Trying the API

What the ticketing system would call:

```sh
curl -X POST localhost:8000/companies/1/tickets/T-1001/assign
curl -X POST localhost:8000/companies/1/tickets/T-1001/complete
```

The Assignment Log tab in the UI also has a "Send a test ticket" box that does the same.

## Tests

```sh
uv run pytest              # everything; needs the Postgres container running
uv run pytest tests/unit   # pure logic only, no database needed
```

Integration tests use a separate `clearfeed_test` database, which is created and
migrated on the first run, so they never touch the demo data. Every setting is set
explicitly in `tests/conftest.py`, so a local `.env` can't change results.

Coverage, mapped to the test plan in `docs/implementation.md`:

- **Schedule rules** (unit): start-inclusive/end-exclusive boundaries, overnight
  shifts, the Sunday-to-Monday wrap, shifts ending at 24:00, overlap detection.
- **Coverage** (unit): the PRD's London/Los Angeles example, the October 2026
  weeks where London has changed its clocks and Los Angeles hasn't, and local
  times that don't exist or happen twice on clock-change days.
- **Ranking** (unit): fewest active tickets, then longest since last assigned, then
  lowest id, with the matching reason code.
- **Assignment and completion** (integration): every reason code, `MAX` rather than
  `MIN` for "last assigned", idempotent retries, re-evaluating unassigned tickets,
  freeing capacity exactly once, and company isolation.
- **Concurrency** (integration): 10 simultaneous requests for one ticket produce one
  assignment; two tickets competing for one free slot never push the agent over the
  limit; a held company lock gives a 503 without blocking other companies.

## How it works

### Availability

Each agent has a home timezone and recurring weekly shifts in their own local
time: a day, a start and an end. An agent is available when the current moment,
converted to their timezone, falls inside one of their shifts and they have fewer
active tickets than the limit.

- Start is inclusive, end is exclusive, so back-to-back shifts meet without a gap
  or overlap.
- An end before the start is an overnight shift: it belongs to the day it starts
  and runs into the next morning. A Sunday overnight shift runs into Monday.
- `24:00` means midnight at the end of the day; `00:00` as an end means the same.
- An agent can have several shifts on the same day, as long as none overlap
  (including overlaps across midnight).
- Changing an agent's timezone keeps their shifts at the same local clock times.

Times are stored as minutes since local midnight (0–1440) next to a day of the
week. The API uses `"HH:MM"`, converted in one place (`schemas.py`).

### Fair assignment

Among agents in a shift right now and below the limit:

1. Fewest active (assigned, not completed) tickets: `FEWEST_ACTIVE`
2. Tied: the one whose most recent assignment is oldest; never-assigned agents
   first: `TIE_LONGEST_SINCE_ASSIGNED`
3. Still tied: lowest agent id, so results are deterministic: `TIE_AGENT_ID`

If nobody is in a shift the result is `NO_AGENT_SCHEDULED`; if everyone in a shift
is at the limit, `NO_AGENT_CAPACITY`. Unassigned tickets are left for the ticketing
system to retry.

### Concurrency and retries

`/assign` runs in one transaction that first locks the company's row
(`SELECT ... FOR UPDATE`). Counting active tickets, ranking and writing the
assignment all happen under that lock, so two tickets can't both take an agent's
last slot, and simultaneous requests for one ticket produce one assignment. Fair
assignment compares every agent in the company, so the lock is per company:
different companies never wait for each other. If the lock isn't acquired within
5 seconds, the API returns `503 ASSIGNMENT_LOCK_TIMEOUT`.

- Retrying `/assign` for an assigned or completed ticket returns the stored result
  without re-evaluating or writing a log entry.
- Retrying a ticket that was left unassigned evaluates it again.
- `/complete` is one atomic `UPDATE ... WHERE completed_at IS NULL`, so capacity is
  freed exactly once and repeats return the original `completed_at`.

Active ticket counts are always counted from `ticket_assignment`, never stored, so
they can't drift.

### Coverage

The coverage view places required hours (company time) and every agent's shifts
(their own time) on the selected week's real dates, converts them all to UTC
instants, and subtracts covered time from required time. Each date uses its own UTC
offset, so weeks where only one of the timezones has changed its clocks work
without special cases. Gaps are shown in the company's timezone, split at midnight.
Each gap also has `start_at`/`end_at` timestamps with their UTC offset, so a gap
during a clock change stays unambiguous (e.g. 01:45 BST to 01:15 GMT); the UI
notes when clocks change during a gap.

On clock-change days, a local time that doesn't exist is treated as the same
clock time after the jump, and a time that happens twice uses its first
occurrence. Each shift is one continuous span between those instants, and
assignment uses the same spans, so coverage and assignment always agree on who
is available.

### Transparency

Every assignment decision, including unassigned outcomes, is written to an
assignment log with a snapshot of what it was based on: the limit, and for each
agent in a shift, their active count, when they were last assigned, their timezone
and the shift they matched. The UI's "Why?" button shows it.

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/companies/{id}/tickets/{ticket_id}/assign` | Assign a ticket, or explain why not |
| `POST` | `/companies/{id}/tickets/{ticket_id}/complete` | Mark a ticket completed |
| `GET` | `/companies/{id}/assignment-log` | Assignment decisions; filter by `ticket_id`, `outcome`; `cursor` pagination |
| `GET` | `/companies/{id}/coverage?week_of=` | Uncovered required hours for a week |
| `GET` / `PUT` | `/companies/{id}/required-hours` | Get or replace the hours that need coverage |
| `GET` / `POST` | `/companies/{id}/agents/{agent_id}/shifts` | List or add an agent's shifts |
| `PUT` / `DELETE` | `/companies/{id}/agents/{agent_id}/shifts/{shift_id}` | Replace or delete a shift |
| `GET` | `/companies/{id}/agents` | List agents |
| `PATCH` | `/companies/{id}/agents/{agent_id}` | Change an agent's timezone |
| `GET` | `/companies` | List companies |

Every id in a path is looked up within its parent (an agent within the company, a
shift within the agent); a mismatch is a 404, the same as an id that doesn't exist.
Errors have one shape: `{"error": {"code": "SHIFT_OVERLAP", "message": "..."}}`.

## Configuration

Environment variables, or a `.env` file (see `.env.example`):

| Variable | Default | |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://clearfeed:clearfeed@localhost:5432/clearfeed` | |
| `ACTIVE_TICKET_LIMIT` | `5` | Max active tickets per agent |
| `ASSIGNMENT_LOCK_TIMEOUT_SECONDS` | `5` | How long `/assign` waits for the company lock |

## Project layout

```
src/clearfeed/
  app.py              FastAPI app, routers, static UI
  models.py           SQLAlchemy models
  schemas.py          API request/response shapes ("MON", "HH:MM")
  core/               config, database session, error handling
  domain/             pure business rules: schedule, coverage, ranking
  services/           transactions, locks and queries; call into domain/
  api/                routes and scoped path lookups (deps.py)
  static/             the UI: index.html, app.js, vendored Alpine.js and Bootstrap
migrations/           Alembic migrations
scripts/seed.py       demo data
tests/unit/           domain logic, no database
tests/integration/    API tests against Postgres
```

`domain/` never touches the database, the clock or FastAPI, so the timezone and
ranking rules are tested as plain functions. The current time comes from a FastAPI
dependency (`get_now`) that tests pin to fixed instants.

## Simplifications

- **One ticket limit for all agents**, from configuration.
- **No reassignment.** A ticket stays with its agent after their shift ends, and
  the service doesn't retry unassigned tickets itself; the ticketing system
  resubmits them.
- **Companies and agents are seeded.** There's no API or UI to create them, and no
  authentication, as scoped in the brief.
- **Assignments within one company are processed one at a time.** That's plenty
  for support-ticket volumes; very high volume would need a different approach
  (see below).
- **"Send a test ticket"** in the UI is a demo aid that calls the same API as the
  ticketing system.

## What I'd build next

- **Load visibility:** each agent's current active tickets in the Agents tab, so
  a team lead can see who is near the limit.
- **Per-agent capacity and skills:** different limits per agent, and routing by
  ticket type or language.
- **Holidays and one-off overrides:** time off and swapped shifts on top of the
  weekly pattern.
- **Handling unassigned tickets:** notify the ticketing system (webhook) when
  capacity frees up, instead of relying on it to retry.
- **Reassignment policy:** optionally move open tickets when an agent's shift ends.
- **Scaling assignment beyond the per-company lock**, if a single company's ticket
  volume ever outgrows one-at-a-time processing.
- **Auth and roles**, an audit trail of schedule changes, and CI running the test
  suite against Postgres.
