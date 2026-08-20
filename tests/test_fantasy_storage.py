from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from fantasy.catalog import make_player
from fantasy.service import (
    GAME_MODE_AUCTION,
    auction_managers,
    auction_player_assignment,
    auction_player_tier,
    create_league,
    new_workspace,
    update_auction_assignments,
)
from fantasy.storage import FANTASY_STATE_KEY, FantasyWorkspaceStorage


class MemoryRemote:
    available = True
    last_error = ""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def load_json_state(self, state_key: str) -> dict | None:
        payload = self.rows.get(state_key)
        return deepcopy(payload) if payload else None

    def upsert_json_state(self, state_key: str, label: str, payload: dict) -> bool:
        self.rows[state_key] = deepcopy(payload)
        return True


def _settings(sqlite_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        sqlite_path=sqlite_path,
        has_supabase=False,
        supabase_url="",
        supabase_anon_key="",
        request_timeout_seconds=2,
    )


def test_remote_workspace_keeps_leagues_managers_prices_and_tiers(tmp_path: Path) -> None:
    workspace = new_workspace()
    league = create_league(
        workspace,
        "Asta persistente",
        initial_budget=500,
        participants=3,
        game_mode=GAME_MODE_AUCTION,
    )
    player = make_player(name="Molina N.", team="Roma", role="D", quote=18)
    workspace["catalog"] = [player]
    rival_id = str(auction_managers(league)[1]["id"])
    tier_id = str(league["auction_tiers"][1]["id"])
    update_auction_assignments(
        league,
        [
            {
                "player": player,
                "manager_id": rival_id,
                "price": 37,
                "tier_id": tier_id,
            }
        ],
    )

    remote = MemoryRemote()
    first_storage = FantasyWorkspaceStorage(_settings(tmp_path / "first.sqlite3"))
    first_storage.remote = remote
    assert first_storage.save(workspace) is True
    assert remote.rows[FANTASY_STATE_KEY]["catalog"] == []

    restarted_storage = FantasyWorkspaceStorage(_settings(tmp_path / "restarted.sqlite3"))
    restarted_storage.remote = remote
    restored = restarted_storage.load()
    restored_league = restored["leagues"][0]
    assignment = auction_player_assignment(restored_league, player["id"])

    assert restored_league["name"] == "Asta persistente"
    assert len(restored_league["auction_managers"]) == 3
    assert assignment is not None
    assert assignment["manager_id"] == rival_id
    assert assignment["purchase"]["price"] == 37
    assert auction_player_tier(restored_league, player["id"])["id"] == tier_id


def test_local_workspace_survives_a_new_storage_instance(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "fantasy.sqlite3")
    workspace = new_workspace()
    create_league(workspace, "Fanta salvato")

    first_storage = FantasyWorkspaceStorage(settings)
    first_storage.save(workspace)
    restored = FantasyWorkspaceStorage(settings).load()

    assert [league["name"] for league in restored["leagues"]] == ["Fanta salvato"]
