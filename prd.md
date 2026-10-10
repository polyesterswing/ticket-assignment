# Product Requirements Document: Support Ticket Assignment

## 1. Problem Statement
Manually assigning support tickets takes time and makes the team dependent on a team lead being available. This leads to delayed assignments, uneven workloads, and difficulty identifying gaps in team coverage.

The product should automatically assign tickets to eligible agents based on their schedules and current workload, while distributing work fairly.

## 2. Target Users
- Support Team Leads: Manage schedules, Monitor coverage, View assignments
- Ticketing system: Calls the API to assign a ticket, and to mark a ticket as completed

## 3. Scope

### In Scope
- Schedule Management: Configure recurring weekly availability and timezones.
- Coverage View: 
    - Company defines required hours per weekday according to the company timezone,
    - See periods of the week where no one is scheduled to take on tickets.
- Assignment: Must be fair, and tickets that cannot be assigned are left unassigned
- Assignment Transparency: Explain why an agent was selected.
- Completion Reports: accept a report from the ticketing system that an assigned ticket is completed and free relevant capacity once

### Out of Scope
- Authentication
- Billing
- Account Management
- Third-party Integrations
- Mobile Compatibility
- holiday calendars
- One-off overrides
- Tickets that are not marked completed within a shift are not reassigned
- Ticket lifecycle (creation, requeuing unassigned tickets) is owned by the external system

## 4. Assumptions
- Agents have a recurring weekly schedule
- All agents have the same pre-configured active ticket limit
- Ticket lifecycle (creation, completion notification, re-queuing unassigned tickets)
  is managed by an external system

## 5. Definitions
- Available: An agent is available to be assigned a ticket if they are currently in their recurring weekly window. Their active ticket count must also be below the limit.
- Fair assignment:  Among available agents, assignment is fair when the ticket goes to the agent with the fewest active tickets. Ties go to the agent who was assigned a ticket longest ago. Any remaining tie is broken by agent ID so results are deterministic

## 6. Schedule and Timezone Rules
### Agent Availability:
- Each agent has a home timezone.
- A shift is a day of the week, a start time and an end time
- Overlapping shifts are not allowed.
- A shift where start=end is rejected.
- Availability is determined at the current instant in the agent's configured timezone.
  The agent is in their window if that local time falls inside one of their shifts.
- Start is inclusive and End is exclusive. 
- Overnight Shifts are supported. If the end time is before the start time (eg. Monday 22:00 - 06:00)
  the shift ends on Tuesday and belongs to monday, meaning you can set another shift on Tuesday.
- The coverage view shows all shifts in the Company's timezone.

**Example.** The company is in London (`Europe/London`) and requires coverage Monday to Friday, 08:00-20:00. In January, London is on UTC+0 and Los Angeles is on UTC-8. An agent in `America/Los_Angeles` works Monday 09:00-17:00 local.
    - In London time, that shift is Monday 17:00 to Tuesday 01:00. It crosses midnight in the company timezone, even though it doesn't in the agent's own timezone.
    - Only the part inside required hours counts: Monday 17:00-20:00 London. The 20:00-01:00 part is outside required hours and does not affect coverage.
    - If no one else works Monday afternoon, the coverage view shows a gap for Monday 08:00-17:00 London, not a gap for the whole day.

## 7. API Behaviour
### Assignment API
- A ticket is identified by the `company_id` and `ticket_id`
- First request returns the assigned agent details after evaluating assignment rules
- Repeated requests return the assigned agent without re-evaluating assignment rules or reducing capacity
- Repeated requests for a completed ticket also returns completion status
- Repeated request for a previously unassigned ticket re runs assignment rules and determines the agent to assign or leaves it unassigned if none are available.

- **Unassigned Tickets**
    - If a ticket is unassignable and there is no agent scheduled currently it gets: NO_AGENT_SCHEDULED
    - If a ticket is unassignable but all scheduled agents at capacity it responds with: NO_AGENT_CAPACITY
    - The service does not retry on its own. Re-submitting unassigned tickets is the external system’s responsibility, and tickets may remain unassigned until it does
    - Unassigned tickets can be viewed in the Assignment Transparency Log

### Completion API
- First request reduces the active ticket count of an agent
- Repeated requests to mark a ticket as completed do not keep reducing the active ticket count for an agent
