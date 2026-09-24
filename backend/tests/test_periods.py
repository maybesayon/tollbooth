from datetime import UTC, datetime

import pytest

from tollbooth.domain import BudgetPeriod
from tollbooth.periods import period_window


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


@pytest.mark.parametrize(
    ("period", "now", "start", "end"),
    [
        (BudgetPeriod.DAY, utc(2026, 9, 24, 15, 30), utc(2026, 9, 24), utc(2026, 9, 25)),
        (BudgetPeriod.WEEK, utc(2026, 9, 24, 15), utc(2026, 9, 21), utc(2026, 9, 28)),
        (BudgetPeriod.WEEK, utc(2026, 9, 21), utc(2026, 9, 21), utc(2026, 9, 28)),
        (BudgetPeriod.WEEK, utc(2026, 9, 27, 23, 59), utc(2026, 9, 21), utc(2026, 9, 28)),
        (BudgetPeriod.MONTH, utc(2026, 9, 24), utc(2026, 9, 1), utc(2026, 10, 1)),
        (BudgetPeriod.MONTH, utc(2026, 12, 31, 23), utc(2026, 12, 1), utc(2027, 1, 1)),
        (BudgetPeriod.MONTH, utc(2028, 2, 29), utc(2028, 2, 1), utc(2028, 3, 1)),
    ],
)
def test_period_window(period: BudgetPeriod, now: datetime, start: datetime, end: datetime) -> None:
    assert period_window(period, now) == (start, end)


def test_converts_other_timezones_to_utc() -> None:
    from datetime import timedelta, timezone

    tokyo = datetime(2026, 10, 1, 8, tzinfo=timezone(timedelta(hours=9)))
    assert period_window(BudgetPeriod.MONTH, tokyo) == (utc(2026, 9, 1), utc(2026, 10, 1))


def test_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        period_window(BudgetPeriod.DAY, datetime(2026, 9, 24))
