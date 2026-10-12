from datetime import UTC, datetime

from clearfeed.domain.ranking import Candidate, rank
from clearfeed.models import ReasonCode


def at(hhmm: str) -> datetime:
    return datetime.fromisoformat(f"2026-10-12T{hhmm}").replace(tzinfo=UTC)


def winner_id(candidates: list[Candidate], limit: int = 5) -> tuple[int | None, ReasonCode]:
    winner, reason = rank(candidates, limit)
    return (winner.agent_id if winner else None), reason


def test_no_scheduled_agents() -> None:
    assert winner_id([]) == (None, ReasonCode.NO_AGENT_SCHEDULED)


def test_everyone_at_limit() -> None:
    candidates = [Candidate(1, 2, at("09:00")), Candidate(2, 2, None)]

    assert winner_id(candidates, limit=2) == (None, ReasonCode.NO_AGENT_CAPACITY)


def test_fewest_active_wins() -> None:
    candidates = [Candidate(1, 1, None), Candidate(2, 0, at("11:00")), Candidate(3, 2, None)]

    assert winner_id(candidates) == (2, ReasonCode.FEWEST_ACTIVE)


def test_agent_at_limit_is_skipped() -> None:
    candidates = [Candidate(1, 2, None), Candidate(2, 1, at("11:00"))]

    assert winner_id(candidates, limit=2) == (2, ReasonCode.FEWEST_ACTIVE)


def test_only_eligible_agent_wins_on_fewest_active() -> None:
    assert winner_id([Candidate(7, 3, at("09:00"))]) == (7, ReasonCode.FEWEST_ACTIVE)


def test_tie_goes_to_longest_since_assigned() -> None:
    candidates = [Candidate(1, 1, at("11:55")), Candidate(2, 1, at("10:30"))]

    assert winner_id(candidates) == (2, ReasonCode.TIE_LONGEST_SINCE_ASSIGNED)


def test_never_assigned_beats_assigned() -> None:
    candidates = [Candidate(1, 0, at("08:00")), Candidate(2, 0, None)]

    assert winner_id(candidates) == (2, ReasonCode.TIE_LONGEST_SINCE_ASSIGNED)


def test_two_never_assigned_go_to_lowest_id() -> None:
    candidates = [Candidate(9, 0, None), Candidate(4, 0, None)]

    assert winner_id(candidates) == (4, ReasonCode.TIE_AGENT_ID)


def test_same_last_assigned_goes_to_lowest_id() -> None:
    candidates = [Candidate(9, 1, at("10:00")), Candidate(4, 1, at("10:00"))]

    assert winner_id(candidates) == (4, ReasonCode.TIE_AGENT_ID)
