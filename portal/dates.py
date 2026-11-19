from datetime import date, timedelta

# shortcut: holidays for the data's range only (Nov 2026 - Jan 2027); add a yearly table or the `holidays` package before importing later dates.
NATIONAL = {date(2026, 12, 25), date(2026, 12, 26), date(2027, 1, 1)}
STATE = {
    "SN": {date(2026, 11, 18)},  # Buss- und Bettag, Saxony only
    "BY": {date(2027, 1, 6)},
    "BW": {date(2027, 1, 6)},
}
FACTORY_STATE = "NW"
# The tables above are complete for this window only (next missing holiday: Good Friday 2027-03-26).
COVERED = (date(2026, 11, 2), date(2027, 3, 25))


def holidays(state: str) -> set:
    """Days closed by a public holiday at the factory (NRW) or at the destination state."""
    return NATIONAL | STATE.get(FACTORY_STATE, set()) | STATE.get(state, set())


def add_working_days(start: date, days: int, state: str = FACTORY_STATE) -> date:
    """A working day is Mon-Fri and not a holiday at the factory or the destination."""
    closed = holidays(state)
    d = start
    while days:
        d += timedelta(days=1)
        if d.weekday() < 5 and d not in closed:
            days -= 1
    return d
