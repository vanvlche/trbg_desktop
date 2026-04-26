#!/usr/bin/env python3
"""Smoke checks for Quiet Relay's JSON web session API core."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import quiet_relay_vertical_slice_datadriven as slice_game
from web_server.game_api import NotFoundError, WebGameManager


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def start_first_battle(manager: WebGameManager, session_id: str) -> None:
    manager.handle_action(session_id, {"type": "start_expedition"})
    response = manager.handle_action(session_id, {"type": "enter_node"})
    assert_true("events" in response, "enter_node response lacks events")
    assert_true(response["state"]["battle"] is not None, "enter_node did not create a battle")


def force_finished_battle(manager: WebGameManager, winner: str) -> list[dict[str, object]]:
    response = manager.create_session(seed=1)
    session_id = response["session_id"]
    start_first_battle(manager, session_id)
    session = manager.get_session(session_id)
    node = manager.view_state(session)["progress"]["current_node_id"]
    district = manager.view_state(session)["district"]["district_id"]
    battle_node = slice_game.get_district(district).nodes[node]
    state = manager._state_from_snapshot(session.campaign, battle_node)
    if winner == "player":
        for enemy in state.enemies:
            enemy.hp = 0
    else:
        for player in state.players:
            player.hp = 0
    state.check_end()
    return manager._finish_battle(session, battle_node, state)


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="quiet-relay-web-api-"))
    try:
      manager = WebGameManager(root)

      created = manager.create_session(seed=1)
      session_id = created["session_id"]
      assert_true(len(session_id) == 32, "session id is not an opaque hex id")
      assert_true("state" in created, "create response lacks state")

      start_first_battle(manager, session_id)
      action_response = manager.handle_action(
          session_id,
          {
              "type": "battle_action",
              "action_id": "light_attack",
              "axis": {"power": 60, "precision": 60, "composure": 60},
          },
      )
      event_types = [event["type"] for event in action_response["events"]]
      assert_true("player_action" in event_types, "battle action did not emit player_action")
      assert_true(
          any(event_type in event_types for event_type in ("enemy_attack", "enemy_result", "battle_victory", "battle_defeat")),
          "battle action did not split enemy/result/victory/defeat events",
      )

      before_view = json.dumps(manager.view_state(manager.get_session(session_id)), sort_keys=True)
      after_view = json.dumps(manager.view_state(manager.get_session(session_id)), sort_keys=True)
      assert_true(before_view == after_view, "reading/consuming events mutated battle state")

      saved = manager.save_session(session_id)
      assert_true(saved["ok"] is True, "save did not return ok")
      session = manager.get_session(session_id)
      saved_shards = session.campaign.run_shards
      session.campaign.run_shards += 99
      loaded = manager.load_session(session_id)
      assert_true(loaded["state"]["summary"]["progress"]["run_shards"] == saved_shards, "load did not restore saved shard count")

      client_saved = manager.save_session(session_id, {"screen": "map", "campaign": {"runShards": 7}, "battle": None})
      assert_true("path" not in client_saved, "save response exposed a filesystem path")
      client_loaded = manager.load_session(session_id)
      assert_true(client_loaded["state"]["client_state"]["screen"] == "map", "client state load failed")

      saves = manager.list_saves()["saves"]
      assert_true(saves and "path" not in saves[0], "save listing exposed a filesystem path")

      try:
          manager.load_session("0" * 32)
      except NotFoundError:
          pass
      else:
          raise AssertionError("missing save did not raise NotFoundError")

      victory_types = [event["type"] for event in force_finished_battle(manager, "player")]
      assert_true("battle_victory" in victory_types, "forced victory did not emit battle_victory")

      defeat_types = [event["type"] for event in force_finished_battle(manager, "enemy")]
      assert_true("battle_defeat" in defeat_types, "forced defeat did not emit battle_defeat")

      print("Quiet Relay web API smoke: PASS")
      print(f"- session: {session_id}")
      print(f"- battle action events: {', '.join(event_types)}")
      print("- save/load restored state and did not expose file paths")
      print("- victory and defeat presentation events emitted")
      return 0
    finally:
      shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
