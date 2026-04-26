from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import quiet_relay_terminal_datadriven as qr
import quiet_relay_vertical_slice_datadriven as slice_game


SESSION_ID_RE = re.compile(r"^[a-f0-9]{32}$")
WEB_SAVE_KIND = "quiet-relay-web-session-save"
WEB_SAVE_SCHEMA_VERSION = 1


class WebApiError(Exception):
    status_code = 400


class NotFoundError(WebApiError):
    status_code = 404


class BadRequestError(WebApiError):
    status_code = 400


@dataclass
class WebSession:
    session_id: str
    campaign: slice_game.CampaignState
    created_at: str
    client_state: Optional[Dict[str, Any]] = None
    last_saved_at: Optional[str] = None
    last_events: List[Dict[str, Any]] = field(default_factory=list)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validate_session_id(session_id: str) -> str:
    normalized = str(session_id).strip().lower()
    if not SESSION_ID_RE.fullmatch(normalized):
        raise NotFoundError("session not found")
    return normalized


def _clone_json(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _combatant_view(unit: qr.Combatant) -> Dict[str, Any]:
    return {
        "entity_id": unit.entity_id,
        "name": unit.name,
        "team": unit.team,
        "hp": unit.hp,
        "max_hp": unit.max_hp,
        "guard": unit.guard,
        "max_guard": unit.max_guard,
        "break_meter": unit.break_meter,
        "max_break": unit.max_break,
        "barrier": unit.barrier,
        "conditions": dict(unit.conditions),
        "posture": unit.posture,
        "position": unit.position,
        "alive": unit.alive(),
    }


def _log_entries(state: qr.BattleState, start: int = 0) -> List[str]:
    return [entry.text for entry in state.logger.entries[start:]]


def _event(event_type: str, title: str, lines: Sequence[str], **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "type": event_type,
        "title": title,
        "lines": [str(line) for line in lines if str(line)],
    }
    payload.update(extra)
    return payload


def _events_for_log_delta(
    state: qr.BattleState,
    actor: Optional[qr.Combatant],
    start: int,
    fallback_type: str,
    fallback_title: str,
) -> List[Dict[str, Any]]:
    lines = _log_entries(state, start)
    if not lines:
        return []
    if actor and actor.team == "enemy":
        attack_lines = [line for line in lines if actor.name in line and ("uses " in line or "prepares " in line)]
        result_lines = [line for line in lines if line not in attack_lines]
        events: List[Dict[str, Any]] = []
        events.append(
            _event(
                "enemy_attack",
                "적의 공격",
                attack_lines or lines[:1],
                actor=actor.name,
            )
        )
        if result_lines:
            events.append(_event("enemy_result", "피해 결과", result_lines, actor=actor.name))
        return events
    if actor and actor.team == "player":
        action_lines = [line for line in lines if actor.name in line and ("uses " in line or "drinks " in line)]
        result_lines = [line for line in lines if line not in action_lines]
        events = [
            _event(
                "player_action",
                "플레이어 행동",
                action_lines or lines[:1],
                actor=actor.name,
            )
        ]
        if result_lines:
            events.append(_event("player_result", "행동 결과", result_lines, actor=actor.name))
        return events
    return [_event(fallback_type, fallback_title, lines)]


class WebGameManager:
    def __init__(self, session_root: Path) -> None:
        self.session_root = Path(session_root)
        self.sessions: Dict[str, WebSession] = {}

    def session_dir(self, session_id: str) -> Path:
        return self.session_root / validate_session_id(session_id)

    def save_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "save.json"

    def create_session(self, *, seed: int = 2026, district_id: str = slice_game.DEFAULT_DISTRICT_ID) -> Dict[str, Any]:
        session_id = uuid.uuid4().hex
        campaign = slice_game.new_campaign(seed=seed, district_id=district_id)
        session = WebSession(session_id=session_id, campaign=campaign, created_at=utc_now_iso())
        self.sessions[session_id] = session
        self.session_dir(session_id).mkdir(parents=True, exist_ok=True)
        return self.response(session, events=[])

    def get_session(self, session_id: str) -> WebSession:
        session_id = validate_session_id(session_id)
        session = self.sessions.get(session_id)
        if session is not None:
            return session
        path = self.save_path(session_id)
        if not path.exists():
            raise NotFoundError("session not found")
        session = self._load_session_from_path(session_id, path)
        self.sessions[session_id] = session
        return session

    def response(self, session: WebSession, events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        session.last_events = [_clone_json(event) for event in events]
        return {
            "session_id": session.session_id,
            "state": self.view_state(session),
            "events": list(events),
            "available_actions": self.available_actions(session),
        }

    def view_state(self, session: WebSession) -> Dict[str, Any]:
        if session.client_state is not None:
            return {
                "mode": "client_state",
                "client_state": _clone_json(session.client_state),
                "summary": self.summary(session),
            }

        campaign = session.campaign
        district = slice_game.get_district(campaign.district_id)
        node = district.nodes.get(campaign.current_node_id) if campaign.current_node_id else None
        battle = self._battle_view(campaign)
        return {
            "mode": "api_state",
            "created_at": session.created_at,
            "last_saved_at": session.last_saved_at,
            "district": {
                "district_id": district.district_id,
                "display_name": district.display_name,
            },
            "progress": {
                "expedition_active": campaign.expedition_active,
                "current_node_id": campaign.current_node_id,
                "current_node_title": node.title if node else None,
                "current_node_kind": node.kind if node else None,
                "cleared_node_ids": list(campaign.cleared_node_ids),
                "nodes_cleared": campaign.nodes_cleared(),
                "run_shards": campaign.run_shards,
                "wins": campaign.wins,
                "losses": campaign.losses,
                "last_result": campaign.last_result,
            },
            "party": [_combatant_view(player) for player in campaign.players],
            "battle": battle,
            "summary": self.summary(session),
        }

    def _battle_view(self, campaign: slice_game.CampaignState) -> Optional[Dict[str, Any]]:
        snapshot = campaign.battle_snapshot
        if not snapshot:
            return None
        players = [qr.combatant_from_payload(dict(item)) for item in list(snapshot.get("players", []))]
        enemies = [qr.combatant_from_payload(dict(item)) for item in list(snapshot.get("enemies", []))]
        state_payload = dict(snapshot.get("battle_state", {}))
        cursor = dict(snapshot.get("cursor", {}))
        return {
            "node_id": snapshot.get("node_id"),
            "node_kind": snapshot.get("node_kind"),
            "round_number": state_payload.get("round_number", 1),
            "battle_over": bool(state_payload.get("battle_over", False)),
            "winner": state_payload.get("winner"),
            "spotlight": state_payload.get("spotlight", 0),
            "spotlight_max": state_payload.get("spotlight_max", 5),
            "enemy_spotlight": state_payload.get("enemy_spotlight", 0),
            "enemy_spotlight_max": state_payload.get("enemy_spotlight_max", 5),
            "cursor": cursor,
            "players": [_combatant_view(player) for player in players],
            "enemies": [_combatant_view(enemy) for enemy in enemies],
            "recent_log_lines": list(snapshot.get("recent_log_lines", []))[-80:],
        }

    def available_actions(self, session: WebSession) -> List[Dict[str, str]]:
        campaign = session.campaign
        if session.client_state is not None:
            return [{"type": "save"}, {"type": "load"}]
        if campaign.battle_snapshot:
            return [{"type": "battle_action", "action_id": action_id} for action_id in ("light_attack", "heavy_attack", "use_healing_potion")]
        if not campaign.expedition_active:
            return [{"type": "start_expedition"}]
        if campaign.current_node_id:
            return [{"type": "enter_node", "node_id": campaign.current_node_id}]
        return []

    def summary(self, session: WebSession) -> Dict[str, Any]:
        if session.client_state is not None:
            return self._client_summary(session.client_state, session.last_saved_at)
        campaign = session.campaign
        district = slice_game.get_district(campaign.district_id)
        node = district.nodes.get(campaign.current_node_id) if campaign.current_node_id else None
        return {
            "saved_at": session.last_saved_at,
            "party": ", ".join(player.name for player in campaign.players),
            "party_status": [
                f"{player.name} {player.hp}/{player.max_hp} HP {player.guard}/{player.max_guard} Guard"
                for player in campaign.players
            ],
            "progress": {
                "district": district.display_name,
                "node_id": campaign.current_node_id,
                "node_title": node.title if node else None,
                "node_kind": node.kind if node else None,
                "nodes_cleared": campaign.nodes_cleared(),
                "run_shards": campaign.run_shards,
                "wins": campaign.wins,
                "losses": campaign.losses,
            },
            "in_battle": campaign.battle_snapshot is not None,
        }

    def _client_summary(self, client_state: Dict[str, Any], saved_at: Optional[str]) -> Dict[str, Any]:
        campaign = dict(client_state.get("campaign") or {})
        battle = client_state.get("battle")
        players = list((campaign.get("players") or []) if isinstance(campaign.get("players"), list) else [])
        names = [str(player.get("name", player.get("entityId", "Unknown"))) for player in players if isinstance(player, dict)]
        current_node_id = campaign.get("currentNodeId")
        return {
            "saved_at": saved_at,
            "party": ", ".join(names) if names else str(campaign.get("soloCharacterId") or "Unknown party"),
            "party_status": [
                f"{player.get('name', 'Unknown')} {player.get('hp', '?')}/{player.get('maxHp', '?')} HP"
                for player in players
                if isinstance(player, dict)
            ],
            "progress": {
                "district": campaign.get("districtId"),
                "node_id": current_node_id,
                "node_title": current_node_id,
                "nodes_cleared": len(campaign.get("clearedNodeIds") or []),
                "run_shards": campaign.get("runShards", 0),
                "wins": campaign.get("wins", 0),
                "losses": campaign.get("losses", 0),
            },
            "in_battle": bool(battle),
        }

    def handle_action(self, session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        session = self.get_session(session_id)
        action_type = str(payload.get("type", "") or payload.get("action", ""))
        if not action_type:
            raise BadRequestError("missing action type")
        session.client_state = None
        if action_type == "start_expedition":
            return self._start_expedition(session, payload)
        if action_type == "enter_node":
            return self._enter_node(session, payload)
        if action_type == "battle_action":
            return self._battle_action(session, payload)
        raise BadRequestError(f"unsupported action type: {action_type}")

    def _start_expedition(self, session: WebSession, payload: Dict[str, Any]) -> Dict[str, Any]:
        district_id = str(payload.get("district_id") or session.campaign.district_id)
        slice_game.reset_party_for_new_expedition(session.campaign, district_id=district_id)
        district = slice_game.get_district(session.campaign.district_id)
        event = _event(
            "route",
            "탐사 시작",
            [f"{district.display_name} 탐사를 시작합니다.", f"시작 노드: {session.campaign.current_node_id}"],
        )
        return self.response(session, [event])

    def _enter_node(self, session: WebSession, payload: Dict[str, Any]) -> Dict[str, Any]:
        campaign = session.campaign
        if not campaign.expedition_active:
            raise BadRequestError("expedition is not active")
        district = slice_game.get_district(campaign.district_id)
        node_id = str(payload.get("node_id") or campaign.current_node_id or "")
        if node_id != campaign.current_node_id or node_id not in district.nodes:
            raise BadRequestError("node is not currently available")
        node = district.nodes[node_id]
        if node.kind not in {"battle", "boss"}:
            campaign.record(f"Resolved event node: {node.title}.")
            if node_id not in campaign.cleared_node_ids:
                campaign.cleared_node_ids.append(node_id)
            campaign.current_node_id = node.next_node_ids[0] if node.next_node_ids else None
            return self.response(session, [_event("reward", "보상/귀환", [f"{node.title} resolved."])])
        state = self._ensure_battle_started(campaign, node)
        events = [_event("battle_start", "전투 시작", _log_entries(state, 0))]
        events.extend(self._advance_until_player_or_end(session, node, state))
        self._persist_battle_state(session, node, state)
        return self.response(session, events)

    def _ensure_battle_started(self, campaign: slice_game.CampaignState, node: slice_game.DistrictNode) -> qr.BattleState:
        if campaign.battle_snapshot:
            return self._state_from_snapshot(campaign, node)
        slice_game.prepare_players_for_battle(campaign)
        axis_scores = slice_game.normalize_axis_scores(campaign.current_node_axis_scores)
        campaign.current_node_axis_scores = axis_scores
        campaign.node_axis_history[node.node_id] = axis_scores
        encounter_info = slice_game.resolve_node_encounter(campaign, node)
        enemies = slice_game.create_slice_enemies(node, [str(item) for item in list(encounter_info["encounter_ids"])])
        slice_game.prepare_enemies_for_battle(campaign, node, enemies)
        logger = qr.BattleLogger(echo=False)
        state = qr.BattleState(
            players=campaign.players,
            enemies=enemies,
            rng=campaign.rng,
            logger=logger,
            interactive=False,
            balance_mode=qr.BALANCE_MODE_EXPEDITION,
            healing_potions=campaign.healing_potions,
            potion_upgrade_ids=list(campaign.potion_upgrade_ids),
            spotlight=campaign.starting_spotlight,
            node_axis_scores=axis_scores,
        )
        state.initialize_enemy_balance()
        state.logger.log(state.round_number, f"Battle setup: starting Spotlight {campaign.starting_spotlight}, prebattle barrier {campaign.prebattle_barrier}.")
        variant_id = str(encounter_info.get("variant_id", "fixed"))
        if variant_id != "fixed":
            state.logger.log(state.round_number, f"Encounter variant: {variant_id}.")
        return state

    def _state_from_snapshot(self, campaign: slice_game.CampaignState, node: slice_game.DistrictNode) -> qr.BattleState:
        state = slice_game.resume_battle_from_snapshot(campaign, node, auto=True)
        if state is None:
            raise BadRequestError("battle snapshot could not be resumed")
        state.logger.echo = False
        state.interactive = False
        return state

    def _battle_action(self, session: WebSession, payload: Dict[str, Any]) -> Dict[str, Any]:
        campaign = session.campaign
        if not campaign.expedition_active or not campaign.current_node_id:
            raise BadRequestError("no active battle node")
        node = slice_game.get_district(campaign.district_id).nodes[campaign.current_node_id]
        if node.kind not in {"battle", "boss"}:
            raise BadRequestError("current node is not a battle")
        state = self._ensure_battle_started(campaign, node)
        events = self._apply_player_battle_action(state, payload)
        if not state.battle_over:
            events.extend(self._advance_until_player_or_end(session, node, state))
        if state.battle_over:
            events.extend(self._finish_battle(session, node, state))
        else:
            self._persist_battle_state(session, node, state)
        return self.response(session, events)

    def _current_actor(self, state: qr.BattleState) -> Optional[qr.Combatant]:
        qr.ensure_round_ready(state)
        if state.cursor.next_actor_index >= len(state.cursor.turn_order_ids):
            return None
        actor_id = state.cursor.turn_order_ids[state.cursor.next_actor_index]
        return qr._lookup_combatant_by_id(state, actor_id)

    def _apply_player_battle_action(self, state: qr.BattleState, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        actor = self._current_actor(state)
        if actor is None:
            return []
        if actor.team != "player":
            raise BadRequestError("battle is not waiting for a player action")
        state.cursor.next_actor_index += 1
        start_log = len(state.logger.entries)
        if actor.alive() and actor.start_turn_tick(state):
            action_id = str(payload.get("action_id") or "light_attack")
            action = qr.BATTLE_ACTIONS.get(action_id)
            if action is None:
                raise BadRequestError("unknown battle action")
            skill = qr.action_skill_for_actor(actor, action)
            raw_axis = dict(payload.get("axis") or {})
            axis = {
                "power": int(raw_axis.get("power", state.node_axis_scores.get("power", 60))),
                "precision": int(raw_axis.get("precision", state.node_axis_scores.get("precision", 60))),
                "composure": int(raw_axis.get("composure", state.node_axis_scores.get("composure", 60))),
            }
            inputs = qr.make_resolved_inputs(axis["power"], axis["precision"], axis["composure"], skill)
            starting_ap = qr.start_player_turn_ap(state, actor, inputs)
            qr.log_player_action_inputs_once(state, actor, inputs, starting_ap)
            qr.apply_posture_and_post_action_effects(state, actor, inputs)
            reason = qr.unavailable_battle_action_reason(state, actor, action)
            if reason is not None:
                raise BadRequestError(reason)
            targets = self._targets_for_action(state, actor, action, payload)
            if targets:
                qr.resolve_battle_action(state, actor, action, targets)
            actor.metadata.pop("turn_accuracy_penalty", None)
            actor.metadata.pop("current_action_accuracy_modifier", None)
            actor.times_acted += 1
            state.check_end()
        else:
            actor.times_acted += 1
        return _events_for_log_delta(state, actor, start_log, "player_action", "플레이어 행동")

    def _targets_for_action(
        self,
        state: qr.BattleState,
        actor: qr.Combatant,
        action: qr.BattleActionDef,
        payload: Dict[str, Any],
    ) -> List[qr.Combatant]:
        if action.target == "self":
            return [actor]
        candidates = state.get_opponents(actor)
        target_id = payload.get("target_id")
        if target_id:
            target = next((unit for unit in candidates if unit.entity_id == str(target_id) and unit.alive()), None)
            if target is not None:
                return [target]
        if not candidates:
            return []
        skill = qr.action_skill_for_actor(actor, action)
        return [qr.auto_choose_target(state, actor, skill, candidates)]

    def _advance_until_player_or_end(
        self,
        session: WebSession,
        node: slice_game.DistrictNode,
        state: qr.BattleState,
    ) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        while not state.battle_over:
            actor = self._current_actor(state)
            if actor is None:
                continue
            if actor.team == "player":
                break
            start_log = len(state.logger.entries)
            qr.run_one_actor_turn(state)
            events.extend(_events_for_log_delta(state, actor, start_log, "enemy_attack", "적의 공격"))
            if state.battle_over:
                events.extend(self._finish_battle(session, node, state))
                break
        return events

    def _finish_battle(
        self,
        session: WebSession,
        node: slice_game.DistrictNode,
        state: qr.BattleState,
    ) -> List[Dict[str, Any]]:
        campaign = session.campaign
        if state.winner == "player":
            if not state.logger.entries or state.logger.entries[-1].text != "Players win the battle.":
                state.logger.log(state.round_number, "Players win the battle.")
            campaign.battle_snapshot = None
            campaign.players = state.players
            campaign.rng = state.rng
            campaign.healing_potions = state.healing_potions
            slice_game.normalize_party_between_battles(campaign)
            campaign.run_shards += node.shards
            campaign.record(f"Cleared {node.title}. Echo Shards balance: {campaign.run_shards}.")
            return [
                _event("battle_victory", "전투 성공", [f"{node.title} 전투에서 승리했습니다.", f"Echo Shards +{node.shards}."]),
                _event("reward", "보상/귀환", [f"현재 Echo Shards: {campaign.run_shards}."]),
            ]
        if not state.logger.entries or state.logger.entries[-1].text != "Enemies win the battle.":
            state.logger.log(state.round_number, "Enemies win the battle.")
        campaign.battle_snapshot = None
        campaign.players = state.players
        campaign.rng = state.rng
        campaign.healing_potions = state.healing_potions
        slice_game.normalize_party_between_battles(campaign)
        campaign.losses += 1
        campaign.best_nodes_cleared = max(campaign.best_nodes_cleared, campaign.nodes_cleared())
        campaign.last_result = f"Defeat at {node.title} after clearing {campaign.nodes_cleared()} nodes."
        campaign.expedition_active = False
        campaign.current_node_id = None
        campaign.record(campaign.last_result)
        return [_event("battle_defeat", "전투 실패", [campaign.last_result])]

    def _persist_battle_state(
        self,
        session: WebSession,
        node: slice_game.DistrictNode,
        state: qr.BattleState,
    ) -> None:
        campaign = session.campaign
        campaign.players = state.players
        campaign.rng = state.rng
        campaign.healing_potions = state.healing_potions
        campaign.current_node_axis_scores = slice_game.normalize_axis_scores(state.node_axis_scores)
        campaign.node_axis_history[node.node_id] = slice_game.normalize_axis_scores(state.node_axis_scores)
        campaign.battle_snapshot = slice_game.create_battle_snapshot(campaign, node, state)

    def save_session(self, session_id: str, client_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        session = self.get_session(session_id)
        if client_state is not None:
            if not isinstance(client_state, dict):
                raise BadRequestError("client_state must be a JSON object")
            session.client_state = _clone_json(client_state)
        saved_at = utc_now_iso()
        session.last_saved_at = saved_at
        payload = {
            "kind": WEB_SAVE_KIND,
            "schema_version": WEB_SAVE_SCHEMA_VERSION,
            "session_id": session.session_id,
            "saved_at": saved_at,
            "summary": self.summary(session),
            "campaign": slice_game.campaign_to_dict(session.campaign),
            "client_state": session.client_state,
        }
        self._assert_web_safe_campaign_payload(payload["campaign"])
        path = self.save_path(session.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        tmp_path.replace(path)
        return {
            "ok": True,
            "save_id": session.session_id,
            "session_id": session.session_id,
            "saved_at": saved_at,
            "summary": payload["summary"],
        }

    def load_session(self, session_id: str) -> Dict[str, Any]:
        session_id = validate_session_id(session_id)
        path = self.save_path(session_id)
        if not path.exists():
            raise NotFoundError("save not found")
        session = self._load_session_from_path(session_id, path)
        self.sessions[session_id] = session
        return self.response(session, [])

    def _load_session_from_path(self, session_id: str, path: Path) -> WebSession:
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise BadRequestError(f"save could not be read: {exc}") from exc
        if not isinstance(payload, dict):
            raise BadRequestError("save root must be an object")
        if payload.get("kind") != WEB_SAVE_KIND or int(payload.get("schema_version", 0)) != WEB_SAVE_SCHEMA_VERSION:
            raise BadRequestError("unsupported web save format")
        if str(payload.get("session_id", "")).lower() != session_id:
            raise BadRequestError("save does not belong to this session")
        campaign_payload = dict(payload.get("campaign") or {})
        self._assert_web_safe_campaign_payload(campaign_payload)
        campaign = slice_game.campaign_from_dict(campaign_payload)
        session = WebSession(
            session_id=session_id,
            campaign=campaign,
            created_at=str(payload.get("created_at") or payload.get("saved_at") or utc_now_iso()),
            client_state=payload.get("client_state") if isinstance(payload.get("client_state"), dict) else None,
            last_saved_at=str(payload.get("saved_at") or ""),
        )
        return session

    def _assert_web_safe_campaign_payload(self, campaign_payload: Dict[str, Any]) -> None:
        if int(campaign_payload.get("save_version", 0)) != slice_game.SAVE_VERSION:
            raise BadRequestError("web saves only load the current JSON save version")
        rng_state = campaign_payload.get("rng_state")
        if not isinstance(rng_state, dict):
            raise BadRequestError("web saves require JSON rng_state; legacy pickle fallback is disabled")

    def list_saves(self) -> Dict[str, Any]:
        saves: List[Dict[str, Any]] = []
        if not self.session_root.exists():
            return {"saves": saves}
        for save_path in sorted(self.session_root.glob("*/save.json")):
            session_id = save_path.parent.name
            if not SESSION_ID_RE.fullmatch(session_id):
                continue
            try:
                with save_path.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict) or payload.get("kind") != WEB_SAVE_KIND:
                continue
            summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
            saves.append(
                {
                    "save_id": session_id,
                    "session_id": session_id,
                    "saved_at": payload.get("saved_at"),
                    "summary": summary,
                }
            )
        return {"saves": saves}
