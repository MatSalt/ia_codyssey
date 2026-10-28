from datetime import date, timedelta
import importlib.util

import pytest

from app.models import Record


def summarize(records):
    assert importlib.util.find_spec("app.summary") is not None, "Summary implementation missing"
    from app.summary.service import build_summary
    return build_summary(records)


def records_from_values(values, start=date(2026, 1, 1)):
    return [Record(id=(start + timedelta(days=i)).isoformat(), date=start + timedelta(days=i), value=v)
            for i, v in enumerate(values)]


def test_five_days_excludes_oldest_only_from_comparison():
    s = summarize(records_from_values([99, 2, 4, 6, 8]))
    assert s.metrics.total == 119
    assert s.metrics.daily_average == 23.8
    assert s.comparison.window_days == 2
    assert s.comparison.previous.average == 3
    assert s.comparison.recent.average == 7
    assert s.comparison.previous.start == date(2026, 1, 2)
    assert s.comparison.recent.end == date(2026, 1, 5)
    assert s.comparison.change_percent == pytest.approx(133.33333333333334)


@pytest.mark.parametrize("n,k,previous_start,recent_start", [
    (2, 1, 1, 2), (13, 6, 2, 8), (14, 7, 1, 8), (15, 7, 2, 9),
])
def test_comparison_calendar_windows(n, k, previous_start, recent_start):
    s = summarize(records_from_values([2] * n))
    assert s.count == s.calendar_days == n
    assert s.comparison.window_days == k
    assert s.comparison.previous.start == date(2026, 1, previous_start)
    assert s.comparison.recent.start == date(2026, 1, recent_start)
    assert s.comparison.recent.end == date(2026, 1, n)
    assert s.comparison.change_percent == 0
    assert s.comparison.trend == "unchanged"


def test_empty_data_has_no_invented_statistics():
    s = summarize([])
    assert s.period is None
    assert (s.count, s.calendar_days, s.filled_zero_days, s.metrics.total) == (0, 0, 0, 0)
    assert s.metrics.daily_average is s.metrics.max is s.metrics.min is None
    assert s.comparison.status == s.comparison.trend == "insufficient_data"
    assert s.comparison.previous is s.comparison.recent is s.comparison.change_percent is None
    assert s.comparison.window_days == 0
    assert s.notable_memos == []


def test_one_day_keeps_statistics_but_cannot_compare():
    s = summarize(records_from_values([9]))
    assert s.metrics.total == s.metrics.daily_average == 9
    assert s.comparison.window_days == 0
    assert s.comparison.status == "insufficient_data"
    assert s.comparison.previous is s.comparison.recent is None


def test_missing_days_are_zero_not_stored_records():
    records = [Record(id="2026-01-01", date="2026-01-01", value=4, memo="공개"),
               Record(id="2026-01-04", date="2026-01-04", value=8)]
    s = summarize(records)
    assert (s.count, s.calendar_days, s.filled_zero_days) == (2, 4, 2)
    assert s.metrics.total == 12
    assert s.metrics.daily_average == 3
    assert s.metrics.min.value == 0
    assert s.metrics.min.dates == [date(2026, 1, 2), date(2026, 1, 3)]
    assert s.comparison.previous.average == 2
    assert s.comparison.recent.average == 4
    assert s.comparison.change_percent == 100
    assert [(m.date, m.memo) for m in s.notable_memos] == [(date(2026, 1, 1), "공개")]
    assert len(records) == 2


@pytest.mark.parametrize("values,trend,status,percent", [
    ([0, 4], "increase", "zero_baseline", None),
    ([0, 0], "unchanged", "zero_baseline", None),
    ([8, 4], "decrease", "comparable", -50),
    ([4, 0], "decrease", "comparable", -100),
])
def test_zero_baseline_and_direction(values, trend, status, percent):
    s = summarize(records_from_values(values))
    assert s.comparison.status == status
    assert s.comparison.trend == trend
    assert s.comparison.change_percent == percent
    assert s.comparison.message
    if values == [0, 0]:
        assert "두 기간 모두" in s.comparison.message
    if values == [0, 4]:
        assert "기준값이 0" in s.comparison.message


def test_tied_extremes_sorted_without_mutating_input():
    records = records_from_values([2, 5, 2, 5])[::-1]
    before = [r.id for r in records]
    s = summarize(records)
    assert s.metrics.min.dates == [date(2026, 1, 1), date(2026, 1, 3)]
    assert s.metrics.max.dates == [date(2026, 1, 2), date(2026, 1, 4)]
    assert [r.id for r in records] == before


def test_small_change_is_not_rounded_before_direction():
    s = summarize(records_from_values([100000, 100000, 100001, 100000]))
    assert s.comparison.trend == "increase"
    assert s.comparison.change_percent == pytest.approx(0.0005)


def test_last_representable_date_is_valid():
    s = summarize(records_from_values([3, 4], date(9999, 12, 30)))
    assert s.period.end == date.max
    assert s.comparison.recent.average == 4


def test_missing_zero_days_are_in_both_extremes_when_all_zero():
    s = summarize([Record(id="2026-01-01", date="2026-01-01", value=0),
                   Record(id="2026-01-03", date="2026-01-03", value=0)])
    assert s.metrics.max.value == s.metrics.min.value == 0
    assert s.metrics.max.dates == s.metrics.min.dates == [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]


def test_summary_api_uses_repository(app):
    from fastapi.testclient import TestClient
    from app.dependencies import get_data_repository
    from fakes import FakeDataRepository
    app.dependency_overrides[get_data_repository] = lambda: FakeDataRepository(records_from_values([0, 4]))
    with TestClient(app) as client:
        response = client.get("/api/data/summary")
    assert response.status_code == 200
    assert response.json()["comparison"]["change_percent"] is None
    assert response.json()["count"] == 2
