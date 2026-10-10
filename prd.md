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

### Out of Scope
- Authentication
- Billing
- Account Management
- Third-party Integrations
- Mobile Compatibility
- holiday calendars
- One-off overrides
- Tickets that are not marked completed within a shift are not reassigned
- Completion: External system reports ticket completion, freeing agent capacity

## 4. Assumptions
- Agents have a recurring weekly schedule
- All agents have the same pre-configured active ticket limit
- Ticket lifecycle (creation, completion, re-queuing unassigned tickets)
  is managed by an external system

## 5. Definitions
- Available: An agent is available to be assigned a ticket if they are currently in their recurring weekly window. Their active ticket count must also be below the limit.
- Fair assignment:  Among available agents, assignment is fair when the ticket goes to the agent with the fewest active tickets. Ties go to the agent who was assigned a ticket longest ago. Any remaining tie is broken by agent ID so results are deterministic
