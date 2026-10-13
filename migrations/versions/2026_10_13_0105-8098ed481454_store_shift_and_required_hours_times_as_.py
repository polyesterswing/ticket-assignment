"""store shift and required hours times as minutes

Revision ID: 8098ed481454
Revises: 5d4f801f57f1
Create Date: 2026-10-13 01:05:25.209211

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8098ed481454'
down_revision: Union[str, Sequence[str], None] = '5d4f801f57f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _minutes(column: str) -> str:
    return f"(EXTRACT(HOUR FROM {column}) * 60 + EXTRACT(MINUTE FROM {column}))::smallint"


def _add_minute_columns(table: str) -> None:
    op.add_column(table, sa.Column("start_minute", sa.SmallInteger(), nullable=True))
    op.add_column(table, sa.Column("end_minute", sa.SmallInteger(), nullable=True))


def _require_minute_columns(table: str) -> None:
    op.alter_column(table, "start_minute", nullable=False)
    op.alter_column(table, "end_minute", nullable=False)


def upgrade() -> None:
    """Replace time columns with minutes since midnight; 1440 means 24:00."""
    # shift: an end of 00:00 (overnight until midnight) becomes 1440.
    _add_minute_columns("shift")
    op.execute(
        f"""
        UPDATE shift SET
            start_minute = {_minutes("start_time")},
            end_minute = CASE WHEN end_time = '00:00' THEN 1440 ELSE {_minutes("end_time")} END
        """
    )
    _require_minute_columns("shift")
    op.drop_constraint(op.f("uq_shift_agent_id_day_of_week_start_time"), "shift", type_="unique")
    op.drop_constraint(op.f("ck_shift_non_empty"), "shift", type_="check")
    op.drop_column("shift", "start_time")
    op.drop_column("shift", "end_time")
    op.create_unique_constraint(
        op.f("uq_shift_agent_id_day_of_week_start_minute"),
        "shift",
        ["agent_id", "day_of_week", "start_minute"],
    )
    op.create_check_constraint(
        op.f("ck_shift_minute_range"),
        "shift",
        "start_minute BETWEEN 0 AND 1439 AND end_minute BETWEEN 1 AND 1440",
    )
    op.create_check_constraint(op.f("ck_shift_non_empty"), "shift", "start_minute <> end_minute")

    # required_hours: start < end was already enforced, so no 00:00 ends exist.
    _add_minute_columns("required_hours")
    op.execute(
        f"""
        UPDATE required_hours SET
            start_minute = {_minutes("start_time")},
            end_minute = {_minutes("end_time")}
        """
    )
    _require_minute_columns("required_hours")
    op.drop_constraint(op.f("ck_required_hours_start_before_end"), "required_hours", type_="check")
    op.drop_column("required_hours", "start_time")
    op.drop_column("required_hours", "end_time")
    op.create_check_constraint(
        op.f("ck_required_hours_minute_range"),
        "required_hours",
        "start_minute >= 0 AND start_minute < end_minute AND end_minute <= 1440",
    )


def _times(column: str) -> str:
    # time + interval wraps at midnight, so 1440 becomes 00:00.
    return f"TIME '00:00' + make_interval(mins => {column})"


def downgrade() -> None:
    """Back to time columns.

    Lossy for required_hours windows ending at 24:00: the old schema can't
    represent them, so they become 23:59.
    """
    op.add_column("shift", sa.Column("start_time", sa.Time(), nullable=True))
    op.add_column("shift", sa.Column("end_time", sa.Time(), nullable=True))
    op.execute(
        f"UPDATE shift SET start_time = {_times('start_minute')}, end_time = {_times('end_minute')}"
    )
    op.alter_column("shift", "start_time", nullable=False)
    op.alter_column("shift", "end_time", nullable=False)
    op.drop_constraint(op.f("uq_shift_agent_id_day_of_week_start_minute"), "shift", type_="unique")
    op.drop_constraint(op.f("ck_shift_minute_range"), "shift", type_="check")
    op.drop_constraint(op.f("ck_shift_non_empty"), "shift", type_="check")
    op.drop_column("shift", "start_minute")
    op.drop_column("shift", "end_minute")
    op.create_unique_constraint(
        op.f("uq_shift_agent_id_day_of_week_start_time"),
        "shift",
        ["agent_id", "day_of_week", "start_time"],
    )
    op.create_check_constraint(op.f("ck_shift_non_empty"), "shift", "start_time <> end_time")

    op.add_column("required_hours", sa.Column("start_time", sa.Time(), nullable=True))
    op.add_column("required_hours", sa.Column("end_time", sa.Time(), nullable=True))
    op.execute(
        f"""
        UPDATE required_hours SET
            start_time = {_times('start_minute')},
            end_time = {_times('LEAST(end_minute, 1439)')}
        """
    )
    op.alter_column("required_hours", "start_time", nullable=False)
    op.alter_column("required_hours", "end_time", nullable=False)
    op.drop_constraint(op.f("ck_required_hours_minute_range"), "required_hours", type_="check")
    op.drop_column("required_hours", "start_minute")
    op.drop_column("required_hours", "end_minute")
    op.create_check_constraint(
        op.f("ck_required_hours_start_before_end"), "required_hours", "start_time < end_time"
    )
