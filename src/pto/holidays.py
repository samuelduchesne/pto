"""Built-in holiday presets for common countries.

Each preset computes *observed* public holidays for a given year.
Observed rules: if a holiday falls on Saturday the observed date is
the preceding Friday; if it falls on Sunday the observed date is
the following Monday.
"""

from __future__ import annotations

import datetime

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> datetime.date:
    """Return the *n*-th occurrence of *weekday* in *month* of *year*.

    *weekday* follows ``datetime`` convention: 0 = Monday … 6 = Sunday.
    *n* is 1-based (1 = first, 2 = second, …).
    """
    first = datetime.date(year, month, 1)
    # Days until the first target weekday
    delta = (weekday - first.weekday()) % 7
    first_occurrence = first + datetime.timedelta(days=delta)
    return first_occurrence + datetime.timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> datetime.date:
    """Return the last occurrence of *weekday* in *month* of *year*."""
    # Start from the last day of the month
    if month == 12:
        last = datetime.date(year, 12, 31)
    else:
        last = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
    delta = (last.weekday() - weekday) % 7
    return last - datetime.timedelta(days=delta)


def _observed(d: datetime.date) -> datetime.date:
    """Shift a holiday to its *observed* date (Sat→Fri, Sun→Mon)."""
    if d.weekday() == 5:  # Saturday
        return d - datetime.timedelta(days=1)
    if d.weekday() == 6:  # Sunday
        return d + datetime.timedelta(days=1)
    return d


# ---------------------------------------------------------------------------
# Country presets
# ---------------------------------------------------------------------------

PRESETS: dict[str, str] = {
    "us": "United States federal holidays",
}


def us_holidays(year: int) -> list[tuple[datetime.date, str]]:
    """US federal holidays (observed) for *year*."""
    return sorted(
        [
            (_observed(datetime.date(year, 1, 1)), "New Year's Day"),
            (_nth_weekday(year, 1, 0, 3), "Martin Luther King Jr. Day"),
            (_nth_weekday(year, 2, 0, 3), "Presidents' Day"),
            (_last_weekday(year, 5, 0), "Memorial Day"),
            (_observed(datetime.date(year, 6, 19)), "Juneteenth"),
            (_observed(datetime.date(year, 7, 4)), "Independence Day"),
            (_nth_weekday(year, 9, 0, 1), "Labor Day"),
            (_nth_weekday(year, 11, 3, 4), "Thanksgiving"),
            (_observed(datetime.date(year, 12, 25)), "Christmas Day"),
        ]
    )


_PRESET_FNS: dict[str, type[object] | object] = {
    "us": us_holidays,
}


def get_holidays(country: str, year: int) -> list[tuple[datetime.date, str]]:
    """Return ``(date, name)`` pairs for the given *country* preset and *year*.

    Raises ``KeyError`` if the country is not supported.
    """
    fn = _PRESET_FNS.get(country)
    if fn is None:
        supported = ", ".join(sorted(PRESETS))
        msg = f"Unknown country preset {country!r}. Supported: {supported}"
        raise KeyError(msg)
    return fn(year)  # type: ignore[operator]
