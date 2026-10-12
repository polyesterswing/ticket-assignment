"""Fair assignment among scheduled agents. Pure functions: no database, no clock.

Among agents below the active ticket limit, the winner has the fewest active
tickets; ties go to the agent assigned longest ago (never-assigned first), then
to the lowest agent id. The reason code names the rule that decided it.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from clearfeed.models import ReasonCode

_NEVER = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True)
class Candidate:
    agent_id: int
    active: int  # tickets assigned and not completed
    last_assigned_at: datetime | None  # latest assignment, including completed tickets


def rank(candidates: Sequence[Candidate], limit: int) -> tuple[Candidate | None, ReasonCode]:
    """Pick the winner among scheduled agents, or explain why there is none."""
    if not candidates:
        return None, ReasonCode.NO_AGENT_SCHEDULED

    eligible = sorted((c for c in candidates if c.active < limit), key=_order)
    if not eligible:
        return None, ReasonCode.NO_AGENT_CAPACITY

    winner = eligible[0]
    if len(eligible) == 1 or winner.active < eligible[1].active:
        return winner, ReasonCode.FEWEST_ACTIVE
    if winner.last_assigned_at != eligible[1].last_assigned_at:
        return winner, ReasonCode.TIE_LONGEST_SINCE_ASSIGNED
    return winner, ReasonCode.TIE_AGENT_ID


def _order(c: Candidate) -> tuple[int, datetime, int]:
    return c.active, c.last_assigned_at or _NEVER, c.agent_id
