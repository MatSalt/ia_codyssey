"""Pure calendar-based summary; no database access or persistent zero filling."""
from datetime import date, timedelta

from ..models import (Comparison, ComparisonPeriod, Extreme, Metrics, Period,
                      Record, RecordCreate, Summary)


def _insufficient() -> Comparison:
    return Comparison(status="insufficient_data", window_days=0, previous=None,
                      recent=None, change_percent=None, trend="insufficient_data",
                      message="비교 기간이 부족합니다. 최소 2일이 필요합니다.")


def _compare(records: list[Record], end: date, days: int) -> Comparison:
    if days < 2:
        return _insufficient()
    k = min(7, days // 2)
    recent_start = end - timedelta(days=k - 1)
    previous_end = recent_start - timedelta(days=1)
    previous_start = recent_start - timedelta(days=k)
    previous_sum = sum(r.value for r in records if previous_start <= r.date <= previous_end)
    recent_sum = sum(r.value for r in records if recent_start <= r.date <= end)
    previous_average, recent_average = previous_sum / k, recent_sum / k
    trend = "increase" if recent_sum > previous_sum else "decrease" if recent_sum < previous_sum else "unchanged"
    change = (recent_sum - previous_sum) / previous_sum * 100 if previous_sum else None
    if previous_sum:
        message = (f"최근 {recent_start.isoformat()} ~ {end.isoformat()}의 일평균은 {recent_average:.2f}회이며, "
                   f"직전 {previous_start.isoformat()} ~ {previous_end.isoformat()}의 {previous_average:.2f}회 대비 "
                   f"{change:+.2f}% 변화했습니다.")
    elif recent_sum:
        message = (f"직전 기간에는 열람이 없었고, 최근 기간에는 일평균 {recent_average:.2f}회가 기록됐습니다. "
                   "기준값이 0이므로 변화율은 계산하지 않습니다.")
    else:
        message = "두 기간 모두 열람이 0회입니다. 변화율은 계산하지 않습니다."
    return Comparison(status="comparable" if previous_sum else "zero_baseline", window_days=k,
                      previous=ComparisonPeriod(start=previous_start, end=previous_end, average=previous_average),
                      recent=ComparisonPeriod(start=recent_start, end=end, average=recent_average),
                      change_percent=change, trend=trend, message=message)


def build_summary(records: list[Record]) -> Summary:
    if not records:
        return Summary(period=None, count=0, calendar_days=0, filled_zero_days=0,
                       metrics=Metrics(total=0, daily_average=None, max=None, min=None),
                       comparison=_insufficient(), notable_memos=[])
    ordered = sorted(records, key=lambda r: r.date)
    start, end = ordered[0].date, ordered[-1].date
    days = (end - start).days + 1
    by_date = {r.date: r.value for r in ordered}
    total = sum(r.value for r in ordered)
    missing = days - len(ordered)
    lowest = 0 if missing else min(by_date.values())
    highest = max(by_date.values())
    # Only enumerate the complete calendar when zero days are actual extrema.
    def dates_at(value):
        if value == 0 and missing:
            return [start + timedelta(days=i) for i in range(days)
                    if by_date.get(start + timedelta(days=i), 0) == 0]
        return [r.date for r in ordered if r.value == value]
    return Summary(
        period=Period(start=start, end=end), count=len(ordered), calendar_days=days,
        filled_zero_days=missing,
        metrics=Metrics(total=total, daily_average=total / days,
                        max=Extreme(value=highest, dates=dates_at(highest)),
                        min=Extreme(value=lowest, dates=dates_at(lowest))),
        comparison=_compare(ordered, end, days),
        notable_memos=[RecordCreate(date=r.date, value=r.value, memo=r.memo)
                       for r in ordered if r.memo.strip()],
    )
