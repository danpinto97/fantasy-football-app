"""Shared ESPN recorded-fixture helpers for adapter and overview tests."""

import copy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

FIXTURES = Path(__file__).parent / "fixtures" / "espn"
LEAGUE_ID = "96876878"
SEASON = 2024


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def settings_team() -> dict:
    return load_fixture("league-96876878-2024-mSettings-mTeam.json")


def matchup() -> dict:
    return load_fixture("league-96876878-2024-mMatchup.json")


def roster() -> dict:
    return load_fixture("league-96876878-2024-mRoster.json")


def draft() -> dict:
    return load_fixture("league-96876878-2024-mDraftDetail.json")


def settings_and_matchup() -> dict:
    raw = settings_team()
    raw["schedule"] = matchup()["schedule"]
    return raw


class FixtureTransport:
    def __init__(self, payloads):
        self.payloads = payloads
        self.urls = []

    def get_json(self, url: str, *, headers=None):
        self.urls.append(url)
        views = tuple(parse_qs(urlparse(url).query).get("view") or [])
        for key, payload in self.payloads.items():
            if set(key) == set(views):
                return copy.deepcopy(payload)
        raise KeyError(f"No fixture for views {views}")
