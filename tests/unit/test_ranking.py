from datetime import UTC, datetime

from clearfeed.domain.ranking import Candidate, rank
from clearfeed.models import ReasonCode


def at(hhmm: str) -> datetime:
    return datetime.fromisoformat(f"2026-10-12T{hhmm}").replace(tzinfo=UTC)


def winner_id(candidates: list[Candidate], limit: int = 5) -> tuple[int | None, ReasonCode]:
    winner, reason = rank(candidates, limit)
    return (winner.agent_id if winner else None), reason


def test_only_eligible_agent_wins_on_fewest_active() -> None:
    assert winner_id([Candidate(7, 3, at("09:00"))]) == (7, ReasonCode.FEWEST_ACTIVE)


def test_same_last_assigned_goes_to_lowest_id() -> None:
    candidates = [Candidate(9, 1, at("10:00")), Candidate(4, 1, at("10:00"))]

    assert winner_id(candidates) == (4, ReasonCode.TIE_AGENT_ID)
