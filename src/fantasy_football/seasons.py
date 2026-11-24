"""NFL fantasy season year helpers."""

from datetime import date
from typing import Iterable, List, Optional

SEASON_MIN = 2008
SEASON_MAX = 2030
DISCOVER_LOOKBACK = 8


def current_nfl_season(today: Optional[date] = None) -> int:
    """ESPN season year: new season from August, previous year before that."""
    today = today or date.today()
    if today.month >= 8:
        return today.year
    return today.year - 1


def merge_available_seasons(
    years: Optional[Iterable[int]] = None,
    *extra: int,
    today: Optional[date] = None,
) -> List[int]:
    """Union ESPN's previousSeasons with the current NFL year and lookback."""
    current = current_nfl_season(today)
    out = {current, current - 1, current - 2}
    for year in years or []:
        try:
            out.add(int(year))
        except (TypeError, ValueError):
            continue
    for year in extra:
        try:
            out.add(int(year))
        except (TypeError, ValueError):
            continue
    return sorted((year for year in out if SEASON_MIN <= year <= SEASON_MAX), reverse=True)
