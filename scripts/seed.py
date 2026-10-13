"""Seed demo companies, agents, shifts and required hours.

Run with: uv run python scripts/seed.py

Idempotent: companies and agents are upserted by fixed id, and their shifts and
required hours are reset to the values below.
"""

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from clearfeed.core.db import SessionLocal
from clearfeed.domain.schedule import parse_hhmm
from clearfeed.models import Agent, Company, RequiredHours, Shift

MON, TUE, WED, THU, FRI, SAT, SUN = range(7)
WEEKDAYS = [MON, TUE, WED, THU, FRI]

COMPANIES = [
    {"id": 1, "name": "Acme Support", "timezone": "Europe/London"},
    {"id": 2, "name": "Globex", "timezone": "America/New_York"},
]

# (id, company_id, name, timezone, [(day, "HH:MM" start, "HH:MM" end), ...])
AGENTS = [
    # Same timezone and hours as Arjun, for tie-break scenarios.
    (1, 1, "Priya", "Asia/Kolkata", [(d, "09:00", "17:00") for d in WEEKDAYS]),
    (2, 1, "Arjun", "Asia/Kolkata", [(d, "09:00", "17:00") for d in WEEKDAYS]),
    # PRD example: Mon 09:00-17:00 LA is Mon 17:00-Tue 01:00 London in January.
    (3, 1, "Maria", "America/Los_Angeles", [(MON, "09:00", "17:00")]),
    # Overnight shift: belongs to Monday, ends Tuesday 06:00.
    (4, 1, "Tom", "Europe/London", [(MON, "22:00", "06:00")]),
    (5, 2, "Lena", "America/New_York", [(d, "08:00", "16:00") for d in WEEKDAYS]),
    (6, 2, "Kenji", "Asia/Tokyo", [(d, "09:00", "17:00") for d in WEEKDAYS]),
]

# company_id -> [(day, start, end), ...] in company time
REQUIRED_HOURS = {
    1: [(d, "08:00", "20:00") for d in WEEKDAYS],
    2: [(d, "09:00", "17:00") for d in WEEKDAYS],
}


def seed(session: Session) -> None:
    for company in COMPANIES:
        stmt = insert(Company).values(**company)
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Company.id],
                set_={"name": stmt.excluded.name, "timezone": stmt.excluded.timezone},
            )
        )

    for agent_id, company_id, name, tz, shifts in AGENTS:
        stmt = insert(Agent).values(id=agent_id, company_id=company_id, name=name, timezone=tz)
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Agent.id],
                set_={
                    "company_id": stmt.excluded.company_id,
                    "name": stmt.excluded.name,
                    "timezone": stmt.excluded.timezone,
                },
            )
        )
        session.execute(delete(Shift).where(Shift.agent_id == agent_id))
        session.add_all(
            Shift(
                agent_id=agent_id,
                day_of_week=day,
                start_minute=parse_hhmm(start),
                end_minute=parse_hhmm(end),
            )
            for day, start, end in shifts
        )

    for company_id, windows in REQUIRED_HOURS.items():
        session.execute(delete(RequiredHours).where(RequiredHours.company_id == company_id))
        session.add_all(
            RequiredHours(
                company_id=company_id,
                day_of_week=day,
                start_minute=parse_hhmm(start),
                end_minute=parse_hhmm(end),
            )
            for day, start, end in windows
        )

    # Explicit ids don't advance the serial sequences; move them past the seeded ids.
    for table in ("company", "agent"):
        session.execute(
            text(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"(SELECT MAX(id) FROM {table}))"
            )
        )


def main() -> None:
    with SessionLocal.begin() as session:
        seed(session)
        companies = session.scalar(select(func.count()).select_from(Company))
        agents = session.scalar(select(func.count()).select_from(Agent))
    print(f"Seeded {companies} companies and {agents} agents.")


if __name__ == "__main__":
    main()
