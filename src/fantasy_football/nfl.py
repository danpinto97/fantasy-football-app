"""NFL calendar helpers for bye weeks and completed scoring weeks."""

from typing import Dict, Iterable, Mapping, Optional

PRO_TEAM: Dict[int, str] = {
    1: "ATL",
    2: "BUF",
    3: "CHI",
    4: "CIN",
    5: "CLE",
    6: "DAL",
    7: "DEN",
    8: "DET",
    9: "GB",
    10: "TEN",
    11: "IND",
    12: "KC",
    13: "LV",
    14: "LAR",
    15: "MIA",
    16: "MIN",
    17: "NE",
    18: "NO",
    19: "NYG",
    20: "NYJ",
    21: "PHI",
    22: "ARI",
    23: "PIT",
    24: "LAC",
    25: "SF",
    26: "SEA",
    27: "TB",
    28: "WAS",
    29: "CAR",
    30: "JAX",
    33: "BAL",
    34: "HOU",
}

# Regular-season bye week by team abbreviation. Unknown seasons skip bye omission.
BYES_BY_SEASON: Dict[int, Dict[str, int]] = {
    2026: {
        "CAR": 5,
        "KC": 5,
        "CIN": 6,
        "DET": 6,
        "MIA": 6,
        "MIN": 6,
        "BUF": 7,
        "JAX": 7,
        "LAC": 7,
        "WAS": 7,
        "HOU": 8,
        "NO": 8,
        "NYG": 8,
        "SF": 8,
        "PIT": 9,
        "TEN": 9,
        "CHI": 10,
        "DEN": 10,
        "PHI": 10,
        "TB": 10,
        "ATL": 11,
        "CLE": 11,
        "GB": 11,
        "LAR": 11,
        "NE": 11,
        "SEA": 11,
        "BAL": 13,
        "IND": 13,
        "LV": 13,
        "NYJ": 13,
        "ARI": 14,
        "DAL": 14,
    }
}

# ESPN season-long projection averages are over 16 games (17-game slate minus bye).
ESPN_PROJ_GAMES = 16


def team_abbr(pro_team_id: object) -> str:
    try:
        return PRO_TEAM.get(int(pro_team_id), "")
    except (TypeError, ValueError):
        return ""


def bye_week(season: int, abbr: Optional[str]) -> Optional[int]:
    if not abbr:
        return None
    return BYES_BY_SEASON.get(season, {}).get(abbr.upper())


def completed_scoring_week(weekly_maps: Iterable[Mapping[int, float]]) -> int:
    weeks = [max(weekly) for weekly in weekly_maps if weekly]
    return max(weeks) if weeks else 0
