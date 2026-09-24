from datetime import UTC, datetime, timedelta

from tollbooth.domain import BudgetPeriod


def period_window(period: BudgetPeriod, now: datetime) -> tuple[datetime, datetime]:
    """The UTC calendar period containing `now`, as [start, end). Weeks start on Monday."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(UTC)
    day = datetime(now.year, now.month, now.day, tzinfo=UTC)
    match period:
        case BudgetPeriod.DAY:
            return day, day + timedelta(days=1)
        case BudgetPeriod.WEEK:
            start = day - timedelta(days=day.weekday())
            return start, start + timedelta(days=7)
        case BudgetPeriod.MONTH:
            start = day.replace(day=1)
            if start.month == 12:
                return start, start.replace(year=start.year + 1, month=1)
            return start, start.replace(month=start.month + 1)
