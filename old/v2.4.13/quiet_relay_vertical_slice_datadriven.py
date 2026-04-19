#!/usr/bin/env python3
"""
Quiet Relay: 2026 - Vertical Slice [Fully Data-Driven]

A small terminal-first vertical slice built on top of the combat core.
The remaining expedition content is data-driven too:
- district graph from JSON
- reward tables and reward option metadata from JSON
- event and node text from JSON

Standard library only.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import pickle
import random
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import quiet_relay_terminal_datadriven as qr

SAVE_VERSION = 2
DEFAULT_SAVE_FILE = "/mnt/data/quiet_relay_vertical_slice_datadriven_save.json"
DEFAULT_RUN_REPORT = "/mnt/data/quiet_relay_vertical_slice_datadriven_last_run.txt"
DEFAULT_LOG_DIR = "/mnt/data/quiet_relay_vertical_slice_datadriven_logs"
DEFAULT_PARTY = ["vanguard", "duelist", "cantor"]
NEGATIVE_STATUSES = {"scorch", "snare", "soak", "jolt", "hex", "reveal"}
CONTENT = qr.CONTENT
DEFAULT_DISTRICT_ID = str(CONTENT.default_district_id)


@dataclass(frozen=True)
class RewardOptionDef:
    option_id: str
    name: str
    description: str
    effect_type: str
    params: Dict[str, object]


@dataclass(frozen=True)
class RewardTableDef:
    table_id: str
    name: str
    option_ids: Tuple[str, ...]
    pick_count: int = 1


@dataclass(frozen=True)
class EventText:
    event_id: str
    title: str
    text: str


@dataclass(frozen=True)
class DistrictNode:
    node_id: str
    title: str
    kind: str
    event_id: str
    encounter_ids: Tuple[str, ...] = ()
    reward_table_id: Optional[str] = None
    shards: int = 0
    next_node_ids: Tuple[str, ...] = ()


@dataclass(frozen=True)
class DistrictDef:
    district_id: str
    display_name: str
    hub_event_id: str
    start_node_id: str
    node_order: Tuple[str, ...]
    nodes: Dict[str, DistrictNode]

    def total_nodes(self) -> int:
        return len(self.node_order)

    def node_position(self, node_id: str) -> int:
        return self.node_order.index(node_id)


@dataclass
class CampaignState:
    players: List[qr.Combatant]
    rng: random.Random
    district_id: str = DEFAULT_DISTRICT_ID
    expedition_active: bool = False
    current_node_id: Optional[str] = None
    cleared_node_ids: List[str] = field(default_factory=list)
    recovery_charges: int = 3
    max_recovery_charges: int = 3
    starting_spotlight: int = 0
    prebattle_barrier: int = 0
    boss_guard_penalty: int = 0
    run_shards: int = 0
    boons: List[str] = field(default_factory=list)
    best_nodes_cleared: int = 0
    wins: int = 0
    losses: int = 0
    last_result: str = "No expeditions yet."
    report_lines: List[str] = field(default_factory=list)

    def nodes_cleared(self) -> int:
        return len(self.cleared_node_ids)

    def record(self, text: str) -> None:
        self.report_lines.append(text)


# ---------------------------------------------------------------------------
# Content parsing
# ---------------------------------------------------------------------------


def _parse_reward_options() -> Dict[str, RewardOptionDef]:
    parsed: Dict[str, RewardOptionDef] = {}
    for option_id, raw in CONTENT.reward_options.items():
        params = {str(key): value for key, value in raw.items() if key not in {"display_name", "description", "effect_type"}}
        parsed[option_id] = RewardOptionDef(
            option_id=option_id,
            name=str(raw["display_name"]),
            description=str(raw["description"]),
            effect_type=str(raw["effect_type"]),
            params=params,
        )
    return parsed


def _parse_reward_tables() -> Dict[str, RewardTableDef]:
    parsed: Dict[str, RewardTableDef] = {}
    for table_id, raw in CONTENT.reward_tables.items():
        parsed[table_id] = RewardTableDef(
            table_id=table_id,
            name=str(raw.get("display_name", table_id)),
            option_ids=tuple(str(option_id) for option_id in raw.get("options", [])),
            pick_count=int(raw.get("pick_count", 1)),
        )
    return parsed


def _parse_events() -> Dict[str, EventText]:
    parsed: Dict[str, EventText] = {}
    for event_id, raw in CONTENT.events.items():
        parsed[event_id] = EventText(
            event_id=event_id,
            title=str(raw.get("title", "")),
            text=str(raw["text"]),
        )
    return parsed


def _parse_districts() -> Dict[str, DistrictDef]:
    parsed: Dict[str, DistrictDef] = {}
    for district_id, raw in CONTENT.districts.items():
        nodes: Dict[str, DistrictNode] = {}
        raw_nodes = dict(raw.get("nodes", {}))
        for node_id, node_raw in raw_nodes.items():
            nodes[node_id] = DistrictNode(
                node_id=node_id,
                title=str(node_raw.get("title", node_id)),
                kind=str(node_raw["kind"]),
                event_id=str(node_raw["event_id"]),
                encounter_ids=tuple(str(enc_id) for enc_id in node_raw.get("encounter_ids", [])),
                reward_table_id=(str(node_raw["reward_table_id"]) if node_raw.get("reward_table_id") is not None else None),
                shards=int(node_raw.get("shards", 0)),
                next_node_ids=tuple(str(next_id) for next_id in node_raw.get("next_node_ids", [])),
            )
        parsed[district_id] = DistrictDef(
            district_id=district_id,
            display_name=str(raw["display_name"]),
            hub_event_id=str(raw["hub_event_id"]),
            start_node_id=str(raw["start_node_id"]),
            node_order=tuple(str(node_id) for node_id in raw.get("node_order", [])),
            nodes=nodes,
        )
    return parsed


REWARD_OPTIONS = _parse_reward_options()
REWARD_TABLES = _parse_reward_tables()
EVENTS = _parse_events()
DISTRICTS = _parse_districts()


# ---------------------------------------------------------------------------
# Formatting and menu helpers
# ---------------------------------------------------------------------------


def wrap(text: str, width: int = 80) -> str:
    return textwrap.fill(text, width=width)


def clear_screen() -> None:
    # Kept intentionally soft so logs remain visible in many terminals.
    print("\n" + "=" * 84)


def prompt_menu(
    title: str,
    options: Sequence[Tuple[str, str]],
    auto: bool = False,
    auto_choice: Optional[str] = None,
    allow_blank: bool = False,
    blank_value: str = "",
) -> str:
    if title:
        print(title)
    for idx, (_, label) in enumerate(options, start=1):
        print(f"  {idx}. {label}")
    if allow_blank:
        print("  Enter: continue")

    if auto:
        if auto_choice is not None:
            return auto_choice
        return options[0][0]

    while True:
        raw = input("> ").strip()
        if raw == "" and allow_blank:
            return blank_value
        try:
            idx = int(raw)
        except ValueError:
            print("Choose a number from the menu.")
            continue
        if 1 <= idx <= len(options):
            return options[idx - 1][0]
        print("That number is out of range.")


# ---------------------------------------------------------------------------
# Slice data helpers
# ---------------------------------------------------------------------------


def get_district(district_id: str) -> DistrictDef:
    if district_id not in DISTRICTS:
        return DISTRICTS[DEFAULT_DISTRICT_ID]
    return DISTRICTS[district_id]


def get_event(event_id: str) -> EventText:
    return EVENTS[event_id]


def get_current_node(campaign: CampaignState) -> Optional[DistrictNode]:
    if not campaign.expedition_active or campaign.current_node_id is None:
        return None
    district = get_district(campaign.district_id)
    return district.nodes.get(campaign.current_node_id)


def current_progress_text(campaign: CampaignState) -> str:
    node = get_current_node(campaign)
    district = get_district(campaign.district_id)
    if node is None:
        return "No expedition currently active."
    position = district.node_position(node.node_id) + 1
    return f"Expedition in progress: node {position}/{district.total_nodes()} - {node.title}"


# ---------------------------------------------------------------------------
# Campaign state creation / serialization
# ---------------------------------------------------------------------------


def new_campaign(seed: int, district_id: str = DEFAULT_DISTRICT_ID) -> CampaignState:
    rng = random.Random(seed)
    players = qr.build_party(DEFAULT_PARTY)
    campaign = CampaignState(players=players, rng=rng, district_id=district_id)
    campaign.record(f"Created new campaign with seed {seed} in district {district_id}.")
    return campaign


def base_player_payload(player: qr.Combatant) -> Dict[str, object]:
    return {
        "entity_id": player.entity_id,
        "affinity": player.affinity,
        "max_hp": player.max_hp,
        "hp": player.hp,
        "max_guard": player.max_guard,
        "guard": player.guard,
        "max_break": player.max_break,
        "break_meter": player.break_meter,
        "speed": player.speed,
        "skills": list(player.skills),
        "role": player.role,
        "posture": player.posture,
        "barrier": player.barrier,
        "conditions": dict(player.conditions),
        "metadata": dict(player.metadata),
    }


def player_from_payload(payload: Dict[str, object]) -> qr.Combatant:
    entity_id = str(payload["entity_id"])
    player = qr.create_player(entity_id)
    player.affinity = str(payload.get("affinity", player.affinity))
    player.max_hp = int(payload.get("max_hp", player.max_hp))
    player.hp = int(payload.get("hp", player.hp))
    player.max_guard = int(payload.get("max_guard", player.max_guard))
    player.guard = int(payload.get("guard", player.guard))
    player.max_break = int(payload.get("max_break", player.max_break))
    player.break_meter = int(payload.get("break_meter", player.break_meter))
    player.speed = int(payload.get("speed", player.speed))
    player.skills = list(payload.get("skills", player.skills))
    player.role = str(payload.get("role", player.role))
    player.posture = str(payload.get("posture", player.posture))
    player.barrier = int(payload.get("barrier", player.barrier))
    player.conditions = {str(k): int(v) for k, v in dict(payload.get("conditions", {})).items()}
    player.next_attack_power_bonus = 0
    player.crit_spotlight_used_this_turn = False
    player.times_acted = 0
    player.last_skill_used = None
    merged_metadata = dict(player.metadata)
    merged_metadata.update(dict(payload.get("metadata", {})))
    merged_metadata.pop("last_inputs", None)
    player.metadata = merged_metadata
    return player


def encode_rng_state(rng: random.Random) -> str:
    raw = pickle.dumps(rng.getstate())
    return base64.b64encode(raw).decode("ascii")


def decode_rng_state(encoded: str) -> random.Random:
    rng = random.Random()
    state = pickle.loads(base64.b64decode(encoded.encode("ascii")))
    rng.setstate(state)
    return rng


def campaign_to_dict(campaign: CampaignState) -> Dict[str, object]:
    return {
        "save_version": SAVE_VERSION,
        "players": [base_player_payload(player) for player in campaign.players],
        "rng_state": encode_rng_state(campaign.rng),
        "district_id": campaign.district_id,
        "expedition_active": campaign.expedition_active,
        "current_node_id": campaign.current_node_id,
        "cleared_node_ids": list(campaign.cleared_node_ids),
        "recovery_charges": campaign.recovery_charges,
        "max_recovery_charges": campaign.max_recovery_charges,
        "starting_spotlight": campaign.starting_spotlight,
        "prebattle_barrier": campaign.prebattle_barrier,
        "boss_guard_penalty": campaign.boss_guard_penalty,
        "run_shards": campaign.run_shards,
        "boons": list(campaign.boons),
        "best_nodes_cleared": campaign.best_nodes_cleared,
        "wins": campaign.wins,
        "losses": campaign.losses,
        "last_result": campaign.last_result,
        "report_lines": list(campaign.report_lines[-200:]),
    }


def _legacy_state_to_nodes(payload: Dict[str, object], district: DistrictDef) -> tuple[bool, Optional[str], List[str]]:
    expedition_active = bool(payload.get("expedition_active", False))
    current_index = int(payload.get("current_node_index", 0))
    current_index = max(0, min(current_index, district.total_nodes()))
    cleared_node_ids = list(district.node_order[:current_index])
    current_node_id: Optional[str] = None
    if expedition_active and current_index < district.total_nodes():
        current_node_id = district.node_order[current_index]
    else:
        expedition_active = False
    return expedition_active, current_node_id, cleared_node_ids


def _normalize_saved_nodes(
    district: DistrictDef,
    expedition_active: bool,
    current_node_id: Optional[str],
    cleared_node_ids: Sequence[str],
) -> tuple[bool, Optional[str], List[str]]:
    ordered_unique: List[str] = []
    seen = set()
    raw_cleared = {str(node_id) for node_id in cleared_node_ids if str(node_id) in district.nodes}
    for node_id in district.node_order:
        if node_id in raw_cleared and node_id not in seen:
            ordered_unique.append(node_id)
            seen.add(node_id)

    if current_node_id is not None:
        current_node_id = str(current_node_id)
        if current_node_id not in district.nodes:
            current_node_id = None
    if current_node_id in ordered_unique:
        ordered_unique.remove(current_node_id)
    if not expedition_active or current_node_id is None:
        return False, None, ordered_unique
    return True, current_node_id, ordered_unique


def campaign_from_dict(payload: Dict[str, object]) -> CampaignState:
    version = int(payload.get("save_version", 0))
    if version not in {1, SAVE_VERSION}:
        raise ValueError(f"Unsupported save version: {version}")

    players = [player_from_payload(item) for item in list(payload["players"])]
    rng = decode_rng_state(str(payload["rng_state"]))
    district_id = str(payload.get("district_id", DEFAULT_DISTRICT_ID))
    district = get_district(district_id)

    if version == 1:
        expedition_active, current_node_id, cleared_node_ids = _legacy_state_to_nodes(payload, district)
    else:
        expedition_active, current_node_id, cleared_node_ids = _normalize_saved_nodes(
            district=district,
            expedition_active=bool(payload.get("expedition_active", False)),
            current_node_id=payload.get("current_node_id"),
            cleared_node_ids=list(payload.get("cleared_node_ids", [])),
        )

    return CampaignState(
        players=players,
        rng=rng,
        district_id=district.district_id,
        expedition_active=expedition_active,
        current_node_id=current_node_id,
        cleared_node_ids=cleared_node_ids,
        recovery_charges=int(payload.get("recovery_charges", 3)),
        max_recovery_charges=int(payload.get("max_recovery_charges", 3)),
        starting_spotlight=int(payload.get("starting_spotlight", 0)),
        prebattle_barrier=int(payload.get("prebattle_barrier", 0)),
        boss_guard_penalty=int(payload.get("boss_guard_penalty", 0)),
        run_shards=int(payload.get("run_shards", 0)),
        boons=list(payload.get("boons", [])),
        best_nodes_cleared=int(payload.get("best_nodes_cleared", 0)),
        wins=int(payload.get("wins", 0)),
        losses=int(payload.get("losses", 0)),
        last_result=str(payload.get("last_result", "No expeditions yet.")),
        report_lines=list(payload.get("report_lines", [])),
    )


def save_campaign(campaign: CampaignState, filepath: str) -> None:
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(campaign_to_dict(campaign), handle, indent=2)


def load_campaign(filepath: str) -> CampaignState:
    path = Path(filepath)
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return campaign_from_dict(payload)


# ---------------------------------------------------------------------------
# Slice-specific rules and state mutation
# ---------------------------------------------------------------------------


def reset_party_for_new_expedition(campaign: CampaignState, district_id: str = DEFAULT_DISTRICT_ID) -> None:
    district = get_district(district_id)
    campaign.players = qr.build_party(DEFAULT_PARTY)
    campaign.district_id = district.district_id
    campaign.expedition_active = True
    campaign.current_node_id = district.start_node_id
    campaign.cleared_node_ids = []
    campaign.recovery_charges = 3
    campaign.max_recovery_charges = 3
    campaign.starting_spotlight = 0
    campaign.prebattle_barrier = 0
    campaign.boss_guard_penalty = 0
    campaign.run_shards = 0
    campaign.boons = []
    campaign.record(f"Started a new expedition in {district.display_name}.")


def clear_battle_only_state(player: qr.Combatant) -> None:
    player.barrier = 0
    player.posture = "flow"
    player.conditions = {name: duration for name, duration in player.conditions.items() if name not in NEGATIVE_STATUSES}
    player.next_attack_power_bonus = 0
    player.crit_spotlight_used_this_turn = False
    player.times_acted = 0
    player.last_skill_used = None
    preserved_metadata = {key: value for key, value in player.metadata.items() if key not in {"last_inputs"}}
    player.metadata = preserved_metadata
    player.guard = player.max_guard
    player.break_meter = player.max_break


def normalize_party_between_battles(campaign: CampaignState) -> None:
    for player in campaign.players:
        clear_battle_only_state(player)


def heal_party(campaign: CampaignState, amount: int) -> int:
    total = 0
    for player in campaign.players:
        before = player.hp
        player.hp = min(player.max_hp, player.hp + amount)
        total += player.hp - before
    return total


def heal_one_player(player: qr.Combatant, amount: int) -> int:
    before = player.hp
    player.hp = min(player.max_hp, player.hp + amount)
    return player.hp - before


def apply_option(campaign: CampaignState, option_id: str) -> str:
    option = REWARD_OPTIONS[option_id]
    campaign.boons.append(option_id)

    if option.effect_type == "party_stat_boost":
        stat = str(option.params["stat"])
        amount = int(option.params.get("amount", 0))
        restore_current = bool(option.params.get("restore_current_on_gain", False))
        refill_to_max = bool(option.params.get("refill_to_max", False))
        heal_amount = int(option.params.get("heal_amount", 0))

        if stat == "max_guard":
            for player in campaign.players:
                player.max_guard += amount
                if restore_current:
                    player.guard = min(player.max_guard, player.guard + amount)
            return "The team threads bellwire mesh through their armor. Max guard rises for all allies."

        if stat == "speed":
            for player in campaign.players:
                player.speed += amount
            return "Signal wire tuning sharpens reflexes. All allies gain speed."

        if stat == "max_hp":
            total_healed = 0
            for player in campaign.players:
                player.max_hp += amount
                before = player.hp
                if heal_amount > 0:
                    player.hp = min(player.max_hp, player.hp + heal_amount)
                total_healed += player.hp - before
            return f"Red salt steadies the body. Max HP rises for all allies and the party restores {total_healed} total HP."

        if stat == "max_break":
            for player in campaign.players:
                player.max_break += amount
                if refill_to_max:
                    player.break_meter = player.max_break
            return "Steady chimes train the body against impact. All allies gain max Break."

        raise ValueError(f"Unsupported party_stat_boost stat: {stat}")

    if option.effect_type == "campaign_counter_boost":
        counter = str(option.params["counter"])
        amount = int(option.params.get("amount", 0))
        max_value = option.params.get("max_value")
        before = int(getattr(campaign, counter))
        after = before + amount
        if max_value is not None:
            after = min(after, int(max_value))
        setattr(campaign, counter, after)
        gained = after - before

        if counter == "starting_spotlight":
            return f"The team rehearses the opening beat. Starting Spotlight increases by {gained}."
        if counter == "prebattle_barrier":
            return f"Ward flares are packed for the route. Future battles start with +{gained} barrier."
        if counter == "boss_guard_penalty":
            return f"Bellbreaker oil is brushed onto blades. Boss guard penalty increases by {gained}."
        return f"{option.name} changes {counter} by {gained}."

    if option.effect_type == "party_heal":
        amount = int(option.params.get("amount", 0))
        healed = heal_party(campaign, amount)
        return f"Field dressings are applied. The party restores {healed} total HP."

    if option.effect_type == "recovery_charge_boost":
        amount = int(option.params.get("amount", 0))
        max_cap = int(option.params.get("max_cap", campaign.max_recovery_charges + amount))
        before = campaign.recovery_charges
        campaign.max_recovery_charges = min(max_cap, campaign.max_recovery_charges + amount)
        campaign.recovery_charges = min(campaign.max_recovery_charges, campaign.recovery_charges + amount)
        gained = campaign.recovery_charges - before
        return f"A sealed cache yields supplies. Recovery charges increase by {gained}."

    raise ValueError(f"Unsupported reward effect_type: {option.effect_type}")


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def render_party(campaign: CampaignState) -> None:
    print("\nPARTY STATUS")
    print("-" * 84)
    for idx, player in enumerate(campaign.players, start=1):
        weapon_name = str(player.metadata.get("weapon_name", "Unknown Weapon"))
        relic_names = [str(name) for name in player.metadata.get("relic_names", [])]
        extra_bits = [f"weapon={weapon_name}"]
        if relic_names:
            extra_bits.append("relics=" + ", ".join(relic_names))
        print(f"{idx}. {player.summary_line()} | " + " | ".join(extra_bits))
    print("-" * 84)
    print(
        f"Recovery Charges: {campaign.recovery_charges}/{campaign.max_recovery_charges} | "
        f"Start Spotlight: {campaign.starting_spotlight} | Prebattle Barrier: {campaign.prebattle_barrier} | "
        f"Boss Guard Penalty: {campaign.boss_guard_penalty}"
    )
    print(f"Content Pack: {qr.CONTENT.base_dir}")
    if campaign.boons:
        print("Run Boons:")
        for boon_id in campaign.boons:
            if boon_id in REWARD_OPTIONS:
                option = REWARD_OPTIONS[boon_id]
                print(f"  - {option.name}: {option.description}")
    else:
        print("Run Boons: none")
    print()


def render_hub(campaign: CampaignState, save_file: str) -> None:
    clear_screen()
    district = get_district(campaign.district_id)
    hub_event = get_event(district.hub_event_id)
    print(f"Quiet Relay: 2026 - {hub_event.title} [Fully Data-Driven]")
    print("-" * 84)
    print(wrap(hub_event.text))
    print()
    print(f"District: {district.display_name}")
    print(f"Last result: {campaign.last_result}")
    print(f"Record: {campaign.wins} wins / {campaign.losses} losses | Best nodes cleared: {campaign.best_nodes_cleared}")
    print(f"Save file: {save_file}")
    print(current_progress_text(campaign))
    render_party(campaign)


def render_node_banner(node: DistrictNode, campaign: CampaignState) -> None:
    clear_screen()
    district = get_district(campaign.district_id)
    event = get_event(node.event_id)
    position = district.node_position(node.node_id) + 1
    print(f"{district.display_name}")
    print(f"Node {position}/{district.total_nodes()} - {node.title}")
    print("-" * 84)
    print(wrap(event.text))
    print()


# ---------------------------------------------------------------------------
# Expedition flow
# ---------------------------------------------------------------------------


def create_slice_enemies(node: DistrictNode) -> List[qr.Combatant]:
    enemies: List[qr.Combatant] = []
    for idx, encounter_id in enumerate(node.encounter_ids, start=1):
        if encounter_id in qr.BOSS_BLUEPRINTS:
            enemies.append(qr.create_boss(encounter_id))
        else:
            enemies.append(qr.create_enemy(encounter_id, idx))
    return enemies


def prepare_players_for_battle(campaign: CampaignState) -> None:
    normalize_party_between_battles(campaign)
    for player in campaign.players:
        if campaign.prebattle_barrier > 0:
            player.barrier += campaign.prebattle_barrier


def prepare_enemies_for_battle(campaign: CampaignState, node: DistrictNode, enemies: List[qr.Combatant]) -> None:
    if node.kind == "boss" and campaign.boss_guard_penalty > 0:
        for enemy in enemies:
            enemy.guard = max(0, enemy.guard - campaign.boss_guard_penalty)
            enemy.max_guard = max(enemy.guard, enemy.max_guard - campaign.boss_guard_penalty)


def auto_choose_option(campaign: CampaignState, option_ids: Sequence[str]) -> str:
    # Practical priorities for auto test runs.
    total_missing_hp = sum(max(0, player.max_hp - player.hp) for player in campaign.players)
    if "field_dressing" in option_ids and total_missing_hp >= 24:
        return "field_dressing"
    if "supply_cache" in option_ids and campaign.recovery_charges <= 1:
        return "supply_cache"
    if "bellbreaker_oil" in option_ids and campaign.nodes_cleared() >= 3:
        return "bellbreaker_oil"
    if "stage_light" in option_ids and campaign.starting_spotlight < 2:
        return "stage_light"
    if "iron_mesh" in option_ids:
        return "iron_mesh"
    return option_ids[0]


def offer_rewards(campaign: CampaignState, reward_table_id: Optional[str], auto: bool) -> None:
    if not reward_table_id:
        return
    table = REWARD_TABLES[reward_table_id]
    print(f"Choose one reward from {table.name}:")
    menu = [(option_id, f"{REWARD_OPTIONS[option_id].name} - {REWARD_OPTIONS[option_id].description}") for option_id in table.option_ids]
    choice = prompt_menu(
        title="",
        options=menu,
        auto=auto,
        auto_choice=auto_choose_option(campaign, table.option_ids) if auto else None,
    )
    result = apply_option(campaign, choice)
    print(wrap(result))
    campaign.record(f"Reward chosen: {REWARD_OPTIONS[choice].name}.")


def choose_recovery_target(campaign: CampaignState, auto: bool) -> Optional[qr.Combatant]:
    wounded = [player for player in campaign.players if player.alive() and player.hp < player.max_hp]
    if not wounded:
        return None
    if auto:
        return min(wounded, key=lambda unit: unit.hp / max(1, unit.max_hp))

    options = [(str(idx), f"{player.name} - heal 45 HP (currently {player.hp}/{player.max_hp})") for idx, player in enumerate(wounded, start=1)]
    print("Choose an ally to recover:")
    for idx, (_, label) in enumerate(options, start=1):
        print(f"  {idx}. {label}")
    print("  Enter: cancel")
    while True:
        raw = input("> ").strip()
        if raw == "":
            return None
        try:
            idx = int(raw)
        except ValueError:
            print("Choose a number or press Enter to cancel.")
            continue
        if 1 <= idx <= len(wounded):
            return wounded[idx - 1]
        print("That number is out of range.")


def use_recovery_charge(campaign: CampaignState, auto: bool) -> None:
    if campaign.recovery_charges <= 0:
        print("No recovery charges remain.")
        return
    target = choose_recovery_target(campaign, auto)
    if target is None:
        if auto:
            print("Auto mode keeps the recovery charge for later.")
        else:
            print("Recovery canceled.")
        return
    healed = heal_one_player(target, 45)
    target.guard = target.max_guard
    target.break_meter = target.max_break
    campaign.recovery_charges -= 1
    print(f"{target.name} restores {healed} HP and returns to full guard.")
    campaign.record(f"Used a recovery charge on {target.name}.")


def maybe_interstitial_menu(campaign: CampaignState, save_file: str, auto: bool) -> bool:
    """Return True if expedition should continue, False if the player returned to hub."""
    if auto:
        low_hp_count = sum(1 for player in campaign.players if player.hp <= player.max_hp * 0.45)
        if campaign.recovery_charges > 0 and low_hp_count >= 1:
            use_recovery_charge(campaign, auto=True)
        save_campaign(campaign, save_file)
        return True

    while True:
        print("\nExpedition menu")
        print("  1. Continue")
        print("  2. Inspect party")
        print("  3. Use recovery charge")
        print("  4. Save")
        print("  5. Return to hub")
        raw = input("> ").strip()
        if raw in {"", "1"}:
            return True
        if raw == "2":
            render_party(campaign)
            continue
        if raw == "3":
            use_recovery_charge(campaign, auto=False)
            continue
        if raw == "4":
            save_campaign(campaign, save_file)
            print(f"Saved to {save_file}")
            continue
        if raw == "5":
            save_campaign(campaign, save_file)
            print("Returning to hub.")
            return False
        print("Choose a number from the menu.")


def choose_next_node(campaign: CampaignState, next_node_ids: Sequence[str], auto: bool) -> Optional[str]:
    if not next_node_ids:
        return None
    if len(next_node_ids) == 1:
        return next_node_ids[0]

    district = get_district(campaign.district_id)
    if auto:
        return next_node_ids[0]

    options = [(node_id, district.nodes[node_id].title) for node_id in next_node_ids]
    choice = prompt_menu("Choose the next route:", options)
    campaign.record(f"Route chosen: {district.nodes[choice].title}.")
    return choice


def write_run_report(campaign: CampaignState, filepath: str) -> None:
    district = get_district(campaign.district_id)
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as handle:
        handle.write("Quiet Relay: 2026 - Vertical Slice Run Report\n")
        handle.write("=" * 72 + "\n")
        handle.write(f"District: {district.display_name}\n")
        handle.write(f"Last result: {campaign.last_result}\n")
        handle.write(f"Wins/Losses: {campaign.wins}/{campaign.losses}\n")
        handle.write(f"Best nodes cleared: {campaign.best_nodes_cleared}\n")
        handle.write("\nRecent events:\n")
        for line in campaign.report_lines[-60:]:
            handle.write(f"- {line}\n")


def resolve_battle_node(
    campaign: CampaignState,
    node: DistrictNode,
    auto: bool,
    log_dir: str,
) -> bool:
    prepare_players_for_battle(campaign)
    enemies = create_slice_enemies(node)
    prepare_enemies_for_battle(campaign, node, enemies)

    logger = qr.BattleLogger(echo=True)
    state = qr.BattleState(
        players=campaign.players,
        enemies=enemies,
        rng=campaign.rng,
        logger=logger,
        interactive=not auto,
        spotlight=campaign.starting_spotlight,
    )

    print(f"Battle setup: starting Spotlight {campaign.starting_spotlight}, prebattle barrier {campaign.prebattle_barrier}.")
    winner = qr.run_battle(state)

    os.makedirs(log_dir, exist_ok=True)
    district = get_district(campaign.district_id)
    log_path = os.path.join(log_dir, f"{district.node_position(node.node_id) + 1:02d}_{node.node_id}.txt")
    state.save_log(log_path)
    campaign.record(f"Battle at {node.title}: {winner}. Log: {log_path}")
    print(f"Battle log written to: {log_path}")

    normalize_party_between_battles(campaign)

    if winner != "player":
        campaign.losses += 1
        campaign.best_nodes_cleared = max(campaign.best_nodes_cleared, campaign.nodes_cleared())
        campaign.last_result = f"Defeat at {node.title} after clearing {campaign.nodes_cleared()} nodes."
        campaign.expedition_active = False
        campaign.current_node_id = None
        campaign.record(campaign.last_result)
        return False

    campaign.run_shards += node.shards
    print(f"Victory. Echo shards gained: {node.shards}. Total shards this run: {campaign.run_shards}")
    campaign.record(f"Cleared {node.title}. Shards total: {campaign.run_shards}.")
    if node.reward_table_id:
        offer_rewards(campaign, node.reward_table_id, auto=auto)
    return True


def resolve_event_node(campaign: CampaignState, node: DistrictNode, auto: bool) -> None:
    if node.reward_table_id:
        offer_rewards(campaign, node.reward_table_id, auto=auto)
    campaign.record(f"Resolved event node: {node.title}.")


def finish_victory(campaign: CampaignState) -> None:
    district = get_district(campaign.district_id)
    campaign.expedition_active = False
    campaign.current_node_id = None
    campaign.wins += 1
    campaign.best_nodes_cleared = max(campaign.best_nodes_cleared, district.total_nodes())
    campaign.last_result = f"Victory in {district.display_name}. Total shards earned: {campaign.run_shards}."
    campaign.record(campaign.last_result)


def run_expedition(campaign: CampaignState, auto: bool, save_file: str, log_dir: str) -> None:
    district = get_district(campaign.district_id)
    while campaign.expedition_active and campaign.current_node_id is not None:
        node = district.nodes[campaign.current_node_id]
        render_node_banner(node, campaign)

        if node.kind in {"battle", "boss"}:
            success = resolve_battle_node(campaign, node, auto=auto, log_dir=log_dir)
            save_campaign(campaign, save_file)
            if not success:
                write_run_report(campaign, DEFAULT_RUN_REPORT)
                return
        elif node.kind == "event":
            resolve_event_node(campaign, node, auto=auto)
            save_campaign(campaign, save_file)
        else:
            raise ValueError(f"Unknown node kind: {node.kind}")

        if node.node_id not in campaign.cleared_node_ids:
            campaign.cleared_node_ids.append(node.node_id)
        campaign.best_nodes_cleared = max(campaign.best_nodes_cleared, campaign.nodes_cleared())

        next_node_id = choose_next_node(campaign, node.next_node_ids, auto=auto)
        campaign.current_node_id = next_node_id
        save_campaign(campaign, save_file)

        if campaign.current_node_id is None:
            finish_victory(campaign)
            save_campaign(campaign, save_file)
            write_run_report(campaign, DEFAULT_RUN_REPORT)
            return

        if not maybe_interstitial_menu(campaign, save_file=save_file, auto=auto):
            write_run_report(campaign, DEFAULT_RUN_REPORT)
            return

    write_run_report(campaign, DEFAULT_RUN_REPORT)


# ---------------------------------------------------------------------------
# Hub flow
# ---------------------------------------------------------------------------


def hub_menu(campaign: CampaignState, save_file: str, auto: bool, log_dir: str) -> None:
    while True:
        render_hub(campaign, save_file)

        if auto:
            if campaign.expedition_active:
                run_expedition(campaign, auto=True, save_file=save_file, log_dir=log_dir)
            else:
                reset_party_for_new_expedition(campaign, district_id=campaign.district_id)
                run_expedition(campaign, auto=True, save_file=save_file, log_dir=log_dir)
            save_campaign(campaign, save_file)
            write_run_report(campaign, DEFAULT_RUN_REPORT)
            return

        options: List[Tuple[str, str]] = []
        if campaign.expedition_active:
            options.append(("resume", "Resume expedition"))
        else:
            options.append(("start", "Start new expedition"))
        options.extend(
            [
                ("inspect", "Inspect party"),
                ("save", "Save"),
                ("load", "Load"),
                ("quit", "Quit"),
            ]
        )

        choice = prompt_menu("Hub menu", options)

        if choice == "resume":
            run_expedition(campaign, auto=False, save_file=save_file, log_dir=log_dir)
            save_campaign(campaign, save_file)
            continue
        if choice == "start":
            reset_party_for_new_expedition(campaign, district_id=campaign.district_id)
            save_campaign(campaign, save_file)
            run_expedition(campaign, auto=False, save_file=save_file, log_dir=log_dir)
            save_campaign(campaign, save_file)
            continue
        if choice == "inspect":
            render_party(campaign)
            input("Press Enter to return to the hub.")
            continue
        if choice == "save":
            save_campaign(campaign, save_file)
            write_run_report(campaign, DEFAULT_RUN_REPORT)
            print(f"Saved to {save_file}")
            input("Press Enter to continue.")
            continue
        if choice == "load":
            if not os.path.exists(save_file):
                print(f"No save file found at {save_file}")
                input("Press Enter to continue.")
                continue
            loaded = load_campaign(save_file)
            campaign.players = loaded.players
            campaign.rng = loaded.rng
            campaign.district_id = loaded.district_id
            campaign.expedition_active = loaded.expedition_active
            campaign.current_node_id = loaded.current_node_id
            campaign.cleared_node_ids = loaded.cleared_node_ids
            campaign.recovery_charges = loaded.recovery_charges
            campaign.max_recovery_charges = loaded.max_recovery_charges
            campaign.starting_spotlight = loaded.starting_spotlight
            campaign.prebattle_barrier = loaded.prebattle_barrier
            campaign.boss_guard_penalty = loaded.boss_guard_penalty
            campaign.run_shards = loaded.run_shards
            campaign.boons = loaded.boons
            campaign.best_nodes_cleared = loaded.best_nodes_cleared
            campaign.wins = loaded.wins
            campaign.losses = loaded.losses
            campaign.last_result = loaded.last_result
            campaign.report_lines = loaded.report_lines
            print(f"Loaded {save_file}")
            input("Press Enter to continue.")
            continue
        if choice == "quit":
            save_campaign(campaign, save_file)
            write_run_report(campaign, DEFAULT_RUN_REPORT)
            print("Session ended.")
            return


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Quiet Relay: 2026 vertical slice [fully data-driven]",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--auto", action="store_true", help="Run the slice without prompts.")
    parser.add_argument("--seed", type=int, default=2026, help="Seed used when creating a new campaign.")
    parser.add_argument("--save-file", default=DEFAULT_SAVE_FILE, help="JSON save file path.")
    parser.add_argument("--log-dir", default=DEFAULT_LOG_DIR, help="Directory for per-battle logs.")
    parser.add_argument("--fresh", action="store_true", help="Ignore existing save data and start a fresh campaign.")
    parser.add_argument("--load", action="store_true", help="Load the save file immediately if it exists.")
    parser.add_argument("--district", default=DEFAULT_DISTRICT_ID, help="District id to use for new campaigns.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    if args.load and not os.path.exists(args.save_file):
        print(f"No save file found at {args.save_file}")
        return 2

    if args.load and not args.fresh:
        campaign = load_campaign(args.save_file)
    else:
        district_id = args.district if args.district in DISTRICTS else DEFAULT_DISTRICT_ID
        campaign = new_campaign(args.seed, district_id=district_id)
        if os.path.exists(args.save_file) and not args.fresh and not args.auto:
            print(f"Existing save found at {args.save_file}. You can load it from the hub menu.")

    hub_menu(campaign, save_file=args.save_file, auto=args.auto, log_dir=args.log_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
