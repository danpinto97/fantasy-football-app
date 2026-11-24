"""Shared ESPN position / lineup-slot maps."""

from typing import Dict, Set

# player.defaultPositionId
DEFAULT_POSITION_ID: Dict[int, str] = {
    1: "QB",
    2: "RB",
    3: "WR",
    4: "TE",
    5: "K",
    16: "D/ST",
}

# settings.rosterSettings.lineupSlotCounts keys
LINEUP_SLOT_ID: Dict[int, str] = {
    0: "QB",
    2: "RB",
    4: "WR",
    6: "TE",
    16: "D/ST",
    17: "K",
    20: "BE",
    21: "IR",
    23: "FLEX",
}

FLEX_ELIGIBLE: Set[str] = {"RB", "WR", "TE"}
STREAMABLE: Set[str] = {"K", "D/ST"}
STARTER_POSITIONS: Set[str] = {"QB", "RB", "WR", "TE", "FLEX", "K", "D/ST"}
