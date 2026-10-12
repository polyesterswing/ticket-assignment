# Implementation

## Data Model

- Timezones are geographic time zone identifiers like Europe/London
- Active ticket limit is a global config value

company (
    id  PK,
    name,
    timezone,
)

agent (
    id  PK,
    company_id  FK,
    name,
    timezone,
    updated_at
)

shift (
    id  PK,
    agent_id    FK,
    day_of_week,
    start_time,
    end_time,
    created_at,
    updated_at

    UNIQUE (agent_id, day_of_week, start_time), -- overlaps are checked for in the app
    CHECK (day_of_week BETWEEN 0 AND 6),
    CHECK (start_time <> end_time)
)

required_hours ( -- Required coverage hours
    id  PK,
    company_id  FK,
    day_of_week,
    start_time, -- defined in company tz
    end_time,
    CHECK (start_time < end_time) -- no overnight hours; overlaps checked in app
)

ticket_assignment (
    company_id,
    ticket_id,
    PRIMARY KEY (company_id, ticket_id),
    agent_id,
    reason_code,
    assigned_at,
    completed_at,
    created_at
)

assignment_log (
    id  PK,
    company_id, ticket_id,
    agent_id, -- selected agent id
    evaluated_at,
    reason_code,
    snapshot -- active ticket count and assignment times of scheduled agents
)


### Reason Code values
FEWEST_ACTIVE - Agent with the fewest active tickets was selected
TIE_LONGEST_SINCE_ASSIGNED - Tied on active count; won because their last assignment was oldest
TIE_AGENT_ID - Still tied after both rules; lowest agent ID won
NO_AGENT_SCHEDULED - Nobody is in a shift right now
NO_AGENT_CAPACITY - At least one agent is in a shift, but all of them are at the limit


### Assignment Log JSON Snapshot
- timestamps are in UTC

{
  "active_ticket_limit": 5,
  "scheduled_agents": [
    {"agent_id": 4, "active": 1, "last_assigned_at": "2026-10-12T08:50:00Z", "local_tz": "Asia/Kolkata", "matched_shift": {"day": "MON", "start": "09:00", "end": "17:00"}},

    {"agent_id": 7, "active": 1, "last_assigned_at": "2026-10-12T09:50:00Z", "local_tz": "Asia/Kolkata", "matched_shift": {"day": "MON", "start": "09:00", "end": "17:00"}}
  ]
}

## API
## Ownership and Scoping

Every route resolves its path ids through scoped lookups

  company: SELECT ... FROM company WHERE id = $company_id
  agent:   SELECT ... FROM agent   WHERE id = $agent_id AND company_id = $company_id
  shift:   SELECT ... FROM shift   WHERE id = $shift_id AND agent_id = $agent_id
           (the agent was already resolved within the company)
  ticket:  SELECT ... FROM ticket_assignment
           WHERE company_id = $company_id AND ticket_id = $ticket_id

An id is never looked up on its own. A valid company_id in the URL does not
make any other id in the URL valid.

Mismatch response: 404, the same body as for a nonexistent id.
  COMPANY_NOT_FOUND / AGENT_NOT_FOUND / SHIFT_NOT_FOUND / TICKET_NOT_FOUND

### Assignment API
POST /companies/{company_id}/tickets/{ticket_id}/assign
200 - Assigned

{
  "company_id": 1,
  "ticket_id": "T-1001",
  "agent_id": 4,
  "reason_code": "FEWEST_ACTIVE",
  "assigned_at": "2026-10-12T09:55:00Z",
  "completed_at": null
}

200 - Unassigned

{
  "company_id": 1,
  "ticket_id": "T-1002",
  "agent_id": null,
  "reason_code": "NO_AGENT_CAPACITY",
  "assigned_at": null,
  "completed_at": null
}

## Assignment Ranking
1. Lowest active ticket count.
2. Earliest last_assigned_at (ascending),
   last_assigned_at = MAX(assigned_at) across all assignments, including completed ones
   Never-assigned agents rank first.
3. Lowest agent ID as the final tie-breaker.

### Completion API

POST /companies/{company_id}/tickets/{ticket_id}/complete

State transition: a ticket moves from ASSIGNED (agent_id NOT NULL, completed_at NULL) 
to COMPLETED (completed_at set).

Repeated calls to complete a completed ticket does not reset `completed_at`

200: { "ticket_id": "T-1001", "agent_id": 4, "completed_at": "2026-10-12T09:55:00Z" }
404	TICKET_NOT_FOUND	No stored row for (company_id, ticket_id), or the ticket belongs to another company
409	TICKET_NOT_ASSIGNED	The ticket exists but is unassigned.

### Shifts
GET /companies/{company_id}/agents/{agent_id}/shifts
- Sorted by day, then start

POST /companies/{company_id}/agents/{agent_id}/shifts
{"day": "MON", "start": "22:00", "end": "06:00" }
Create. 201

PUT /companies/{company_id}/agents/{agent_id}/shifts/{shift_id}
{"day": "MON", "start": "22:00", "end": "06:00" }
Replace.

DELETE /companies/{company_id}/agents/{agent_id}/shifts/{shift_id}

### Required Hours
GET /companies/{company_id}/required-hours
Returns windows in company timezone

PUT /companies/{company_id}/required-hours
Replaces the full set

{
  "windows": [
    { "day": "MON", "start": "08:00", "end": "20:00" },
    { "day": "SAT", "start": "10:00", "end": "14:00" }
  ]
}

### Coverage View

GET /companies/{company_id}/coverage?week_of=2026-10-12
{
  "company_timezone": "Europe/London",
  "week_start": "2026-10-12",
  "fully_covered": false,
  "gaps": [
    { "day": "MON", "date": "2026-10-12", "start": "08:00", "end": "17:00" },
    { "day": "TUE", "date": "2026-10-13", "start": "08:00", "end": "20:00" }
  ]
}

- week_of is optional
- Each agent's shifts are converted to company time, and overnight ones are split at midnight. They are then merged with back-to-back shifts and clipped to the required windows. Gaps are required minus covered.

### UI Related
GET /companies	Populate the company selector
GET /companies/{company_id}/agents	List the company's agents

PATCH /companies/{company_id}/agents/{agent_id}
- Update the agent's timezone.
- Existing shifts keep their local clock times.

Request:
{ "timezone": "Asia/Kolkata" }

200 Response:
{
  "id": 4,
  "company_id": 1,
  "name": "Priya",
  "timezone": "Asia/Kolkata",
  "updated_at": "2026-10-12T09:55:00Z"
}

404	AGENT_NOT_FOUND     No such agent in this company
422	INVALID_TIMEZONE	Missing, not a string, or not a valid IANA identifier

### Assignment Log
GET /companies/{company_id}/assignment-log?ticket_id=&outcome=&limit=50&cursor=
{
  "items": [
    {
      "id": 301,
      "ticket_id": "T-1002",
      "outcome": "UNASSIGNED",
      "agent": null,
      "reason_code": "NO_AGENT_CAPACITY",
      "evaluated_at": "2026-10-12T09:55:00Z",
      "snapshot": {
        "active_ticket_limit": 5,
        "scheduled_agents": [
          {
            "agent_id": 4,
            "active": 5,
            "last_assigned_at": "2026-10-12T09:50:00Z",
            "local_tz": "Asia/Kolkata",
            "matched_shift": { "day": "MON", "start": "09:00", "end": "17:00" }
          }
        ]
      }
    }
  ],
  "next_cursor": null
}


### Concurrency

Two simultaneous requests can both read an agent at 4 active tickets (limit 5), both assign to them, and leave the agent at 6, which breaks the limit. The same race exists if two calls for the same new ticket both try to create its row.

**Approach: serialize assignments per company.**

`/assign` runs in one transaction with this row lock;

    SET LOCAL lock_timeout = '5s'
    SELECT id FROM company WHERE id = $1 FOR UPDATE;

Inside the lock, the transaction:

1. Returns the stored result if the ticket is already assigned or completed.
2. Finds scheduled agents and counts active tickets (`completed_at IS NULL`).
3. Picks the winner, or sets `NO_AGENT_SCHEDULED` / `NO_AGENT_CAPACITY`.
4. Upserts `ticket_assignment` and inserts `assignment_log`.
5. Commits, which releases the lock.

If the lock cannot be acquired before the timeout a 503 is returned back to the caller

Because the count and the write happen under the same lock, no other assignment in that company can run in between. A concurrent request for the same ticket waits, then sees it already assigned in step 1 and returns the stored result.

**Why per company:** fair assignment compares every agent's active count, so concurrent decisions in one company conflict. Different companies lock different rows and do not block each other. Each transaction is a few small queries, so waiting is negligible at support-ticket volumes.

## UI Flow

Companies and agents are seeded, so the UI never creates them. There is no login. The UI is a plain web app that calls the API; it does not need to be polished, but every screen must work.

### Navigation

A top bar shows the company selector (seeded companies) and the company timezone. Tabs: **Agents**, **Required Hours**, **Coverage**, **Assignment Log**.

### Main flow (set up availability)

1. Select a company. The Agents tab lists its agents.
2. Open an agent and set their timezone.
3. Add weekly shifts for that agent (day, start, end).
4. Open Required Hours and define the hours the company needs covered, per weekday, in company time.
5. Open Coverage and see the gaps for the current week. Go back, add or change shifts, and the gaps update.
6. Open Assignment Log to see how tickets were assigned and why.

### Edge Cases
Case: Ticket is assigned to agent right before shift ends
Behaviour: Ticket remains with that agent

Case: Two tickets come in at the same time for the same company
Behaviour: Processing for the tickets occur in two serial transactions controlled by a row lock,
           Timed out lock acquisitions return a 503 to the API caller.

## Test Plan

### Approach
- **Unit tests** for pure logic: shift matching, overlap detection, tie-break ordering, coverage calculation. These take a time and timezone as inputs, so they need no database.
- **API / integration tests** against a real Postgres test database, because the concurrency guarantees depend on Postgres row locks.
- **Clock control:** the service takes `now` from an injectable clock. Tests pass fixed UTC instants instead of mocking system time, so DST and boundary cases are deterministic.

### Availability and coverage
1. Boundaries (U): A Mon 09:00-17:00 shift is available at 09:00:00 and not available at 17:00:00 (start inclusive, end exclusive).
2. Overnight and week rollover (U): A Mon 22:00-06:00 shift is available Tue 05:59 and not at Tue 06:00. A Sun 22:00-06:00 shift is still available Mon 05:59.
3. Timezone and DST coverage (U): The PRD example, where only the LA agent works Mon 09:00-17:00 local, gives gaps of Mon 08:00-17:00 and Tue-Fri full days, with no gap for Tue 00:00-01:00. Repeat across the Oct 2026 clock-change weeks and expect each date’s own offset to apply.
4. Overlaps and merging (U/I): Back-to-back shifts (08:00-12:00 and 12:00-20:00) leave no gap. Overlapping shifts return 422, including the cross-day case Mon 22:00-06:00 vs Tue 05:00-08:00. No required hours gives fully_covered: true and empty gaps

### Ranking
5. Lowest load (I): The agent with fewer active tickets wins (FEWEST_ACTIVE). An agent at the limit or out of shift is never chosen.
6. Last-assigned tie (I): Tied on active, A assigned at 09:00 and 11:55, B at 10:30. B wins (TIE_LONGEST_SINCE_ASSIGNED), because MAX is used, not MIN.
7. Never-assigned and ID ties (I): A never-assigned agent beats one with history. Two never-assigned agents give the lower ID (TIE_AGENT_ID).
8. No eligible agent (I): Nobody in a shift gives NO_AGENT_SCHEDULED. Everyone in a shift at the limit gives NO_AGENT_CAPACITY.

### Retries and completion
9. Assigned/completed retry (I): A repeat /assign returns the same body (plus completion status if completed). It writes no new log row and counts don’t change, even if the shift has ended.
10. Unassigned retry (I): A NO_AGENT_CAPACITY ticket, after one of the agent’s tickets is completed and /assign is retried, becomes assigned on the same row, and a second log row is written.
11. Completion (I): The first call sets completed_at and drops the agent’s active count by 1. A repeat returns the identical completed_at with no second decrement. An unknown ticket gives 404 with no row created. An unassigned ticket gives 409 and can still be assigned later.

### Isolation
12. Company isolation (I): Another company’s agent returns 404 on GET, PATCH and /shifts, and a shift from another agent returns 404 on PUT and DELETE, with nothing modified. The same ticket_id in two companies gives independent rows. /assign never picks another company’s agent, and completing in A doesn’t touch B.

### Concurrency
13. Same ticket (I): 10 parallel /assign calls for one new ticket all return the same body. There is 1 ticket_assignment row, 1 log row, and total active across agents is 1.
14. Different tickets, one slot (I): One agent is at 1 of 2, and T-A and T-B are fired together. Exactly one is assigned and the other is NO_AGENT_CAPACITY. The agent ends at 2 active, never 3, and the loser’s snapshot shows active: 2. Also, with company A’s lock held, /assign for A returns 503 with no rows written, while /assign for B succeeds.

### UI
15. Timezone edit (M): Open the Kolkata agent, change the timezone to Europe/London and save. The same shift (same id) still reads Mon 09:00-17:00, and the Coverage gaps change accordingly. Entering IST shows an inline error and the old value persists after reload.
