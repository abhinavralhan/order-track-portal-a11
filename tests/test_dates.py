from datetime import date

import pytest

from portal.dates import add_working_days


@pytest.mark.parametrize("ready, expected", [
    (date(2026, 11, 2), date(2026, 11, 5)),    # Mon -> Thu
    (date(2026, 11, 6), date(2026, 11, 11)),   # Fri -> Wed
    (date(2026, 11, 7), date(2026, 11, 11)),   # Sat -> Wed
    (date(2026, 11, 8), date(2026, 11, 11)),   # Sun -> Wed
    (date(2026, 12, 23), date(2026, 12, 29)),  # Wed, skips 25/26 Dec -> Tue
    (date(2026, 12, 31), date(2027, 1, 6)),    # Thu, skips 1 Jan -> Wed
])
def test_three_working_days(ready, expected):
    assert add_working_days(ready, 3) == expected


def test_destination_state_holiday_is_skipped():
    fri = date(2026, 11, 13)
    assert add_working_days(fri, 3) == date(2026, 11, 18)        # NRW: Wed 18 Nov is a working day
    assert add_working_days(fri, 3, "SN") == date(2026, 11, 19)  # Saxony: Buss- und Bettag


def test_holidays_include_factory_and_destination():
    from portal.dates import holidays
    assert date(2026, 12, 25) in holidays("SN") and date(2026, 11, 18) in holidays("SN")
    assert date(2026, 11, 18) not in holidays("BE")
