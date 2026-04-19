#!/usr/bin/env python3
"""
Quiet Relay: 2026 - Vertical Slice

A small terminal-first vertical slice built on top of the combat core.
Includes:
- 3 playable characters: Vanguard, Duelist, Cantor
- 1 district with 6 regular enemies, 1 elite, 1 boss
- 1 hub screen
- save/load support
- recovery charges and small expedition boons

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

SAVE_VERSION = 1
DEFAULT_SAVE_FILE = "/mnt/data/quiet_relay_vertical_slice_datadriven_save.json"
DEFAULT_RUN_REPORT = "/mnt/data/quiet_relay_vertical_slice_datadriven_last_run.txt"
DEFAULT_LOG_DIR = "/mnt/data/quiet_relay_vertical_slice_datadriven_logs"
DEFAULT_PARTY = ["vanguard", "duelist", "cantor"]

NEGATIVE_STATUSES = {"scorch", "snare", "soak", "jolt", "hex", "reveal"}


@dataclass(frozen=True)
class OptionDef:
    option_id: str
    name: str
    description: str


@dataclass(frozen=True)
class DistrictNode:
    node_id: str
    title: str
    kind: str
    text: str
    enemy_ids: Tuple[str, ...] = ()
    reward_options: Tuple[str, ...] = ()
    shards: int = 0


@dataclass
class CampaignState:
    players: List[qr.Combatant]
    rng: random.Random
    expedition_active: bool = False
    current_node_index: int = 0
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
        return self.current_node_index

    def record(self, text: str) -> None:
        self.report_lines.append(text)


OPTION_DEFS: Dict[str, OptionDef] = {
    "iron_mesh": OptionDef("iron_mesh", "Iron Mesh", "+12 max guard to all allies, and restore 12 guard."),
    "stage_light": OptionDef("stage_light", "Stage Light", "+1 starting Spotlight for future battles this run (max 3)."),
    "field_dressing": OptionDef("field_dressing", "Field Dressing", "Heal all allies for 18 HP."),
    "supply_cache": OptionDef("supply_cache", "Supply Cache", "+1 recovery charge, up to 5."),
    "keen_wires": OptionDef("keen_wires", "Keen Wires", "+2 speed to all allies."),
    "red_salt": OptionDef("red_salt", "Red Salt Tonics", "+12 max HP to all allies and heal 12 HP."),
    "ward_flares": OptionDef("ward_flares", "Ward Flares", "All allies start future battles with 10 barrier."),
    "bellbreaker_oil": OptionDef("bellbreaker_oil", "Bellbreaker Oil", "Bosses start with 25 less guard."),
    "steady_chimes": OptionDef("steady_chimes", "Steady Chimes", "+10 max break to all allies."),
}


DISTRICT_NAME = "District 03: Rain Toll Corridor"
DISTRICT_NODES: List[DistrictNode] = [
    DistrictNode(
        node_id="overpass_watch",
        title="Overpass Watch",
        kind="battle",
        text=(
            "An elevated roadway buckles under cathedral stone. A Rustbound Pilgrim drags its bell-metal blade "
            "through the rain while ivy crawls across the guardrail."
        ),
        enemy_ids=("rustbound_pilgrim", "ivy_strangler"),
        reward_options=("iron_mesh", "stage_light", "field_dressing"),
        shards=1,
    ),
    DistrictNode(
        node_id="flooded_arcade",
        title="Flooded Arcade",
        kind="battle",
        text=(
            "Neon signage flickers beneath rising water. A Flood Acolyte chants in the puddles while a Switchblade "
            "Drone skates between broken kiosks."
        ),
        enemy_ids=("flood_acolyte", "switchblade_drone"),
        reward_options=("supply_cache", "keen_wires", "steady_chimes"),
        shards=1,
    ),
    DistrictNode(
        node_id="service_niche",
        title="Service Niche",
        kind="event",
        text=(
            "You find a dry maintenance recess behind a humming panel. The team can patch wounds, rewire defenses, or "
            "prepare for the toll plaza ahead."
        ),
        reward_options=("field_dressing", "ward_flares", "stage_light"),
        shards=0,
    ),
    DistrictNode(
        node_id="witness_chapel",
        title="Witness Chapel",
        kind="battle",
        text=(
            "A transit chapel flickers with cheap halos. A Veil Leech hangs in the rafters while a Lamp Witness raises "
            "its glass lantern toward your party."
        ),
        enemy_ids=("veil_leech", "lamp_witness"),
        reward_options=("red_salt", "bellbreaker_oil", "field_dressing"),
        shards=1,
    ),
    DistrictNode(
        node_id="toll_plaza",
        title="Toll Plaza",
        kind="battle",
        text=(
            "The lanes narrow into a dead checkpoint under immense bells. A Toll Knight waits motionless among cracked "
            "barriers and drowned ticket booths."
        ),
        enemy_ids=("toll_knight",),
        reward_options=("field_dressing", "stage_light", "bellbreaker_oil"),
        shards=2,
    ),
    DistrictNode(
        node_id="bell_tower",
        title="Bell Tower Threshold",
        kind="boss",
        text=(
            "At the district heart, a tilted bell tower grows out of the overpass itself. The Bell Warden steps forward, "
            "pulling heat and ash from every toll the city forgot."
        ),
        enemy_ids=("bell_warden",),
        reward_options=(),
        shards=4,
    ),
]


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
# Campaign state creation / serialization
# ---------------------------------------------------------------------------


def new_campaign(seed: int) -> CampaignState:
    rng = random.Random(seed)
    players = qr.build_party(DEFAULT_PARTY)
    campaign = CampaignState(players=players, rng=rng)
    campaign.record(f"Created new campaign with seed {seed}.")
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
        "expedition_active": campaign.expedition_active,
        "current_node_index": campaign.current_node_index,
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


def campaign_from_dict(payload: Dict[str, object]) -> CampaignState:
    version = int(payload.get("save_version", 0))
    if version != SAVE_VERSION:
        raise ValueError(f"Unsupported save version: {version}")

    players = [player_from_payload(item) for item in list(payload["players"])]
    rng = decode_rng_state(str(payload["rng_state"]))
    return CampaignState(
        players=players,
        rng=rng,
        expedition_active=bool(payload.get("expedition_active", False)),
        current_node_index=int(payload.get("current_node_index", 0)),
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


def reset_party_for_new_expedition(campaign: CampaignState) -> None:
    campaign.players = qr.build_party(DEFAULT_PARTY)
    campaign.expedition_active = True
    campaign.current_node_index = 0
    campaign.recovery_charges = 3
    campaign.max_recovery_charges = 3
    campaign.starting_spotlight = 0
    campaign.prebattle_barrier = 0
    campaign.boss_guard_penalty = 0
    campaign.run_shards = 0
    campaign.boons = []
    campaign.record("Started a new expedition.")


def clear_battle_only_state(player: qr.Combatant) -> None:
    player.barrier = 0
    player.posture = "flow"
    player.conditions = {name: duration for name, duration in player.conditions.items() if name not in NEGATIVE_STATUSES}
    player.next_attack_power_bonus = 0
    player.crit_spotlight_used_this_turn = False
    player.times_acted = 0
    player.last_skill_used = None
    preserved_metadata = {
        key: value
        for key, value in player.metadata.items()
        if key not in {"last_inputs"}
    }
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
    campaign.boons.append(option_id)

    if option_id == "iron_mesh":
        for player in campaign.players:
            player.max_guard += 12
            player.guard = min(player.max_guard, player.guard + 12)
        return "The team threads bellwire mesh through their armor. Max guard rises for all allies."

    if option_id == "stage_light":
        before = campaign.starting_spotlight
        campaign.starting_spotlight = min(3, campaign.starting_spotlight + 1)
        gained = campaign.starting_spotlight - before
        return f"The team rehearses the opening beat. Starting Spotlight increases by {gained}."

    if option_id == "field_dressing":
        healed = heal_party(campaign, 18)
        return f"Field dressings are applied. The party restores {healed} total HP."

    if option_id == "supply_cache":
        before = campaign.recovery_charges
        campaign.max_recovery_charges = min(5, campaign.max_recovery_charges + 1)
        campaign.recovery_charges = min(campaign.max_recovery_charges, campaign.recovery_charges + 1)
        gained = campaign.recovery_charges - before
        return f"A sealed cache yields supplies. Recovery charges increase by {gained}."

    if option_id == "keen_wires":
        for player in campaign.players:
            player.speed += 2
        return "Signal wire tuning sharpens reflexes. All allies gain +2 speed."

    if option_id == "red_salt":
        for player in campaign.players:
            player.max_hp += 12
            player.hp = min(player.max_hp, player.hp + 12)
        return "Red salt tonics steady the body. All allies gain HP and recover a little health."

    if option_id == "ward_flares":
        campaign.prebattle_barrier += 10
        return "Ward flares are packed for the route. Future battles start with extra barrier."

    if option_id == "bellbreaker_oil":
        campaign.boss_guard_penalty += 25
        return "Bellbreaker oil is brushed onto blades. Boss guard will be lower."

    if option_id == "steady_chimes":
        for player in campaign.players:
            player.max_break += 10
            player.break_meter = player.max_break
        return "Steady chimes train the body against impact. All allies gain +10 max break."

    raise ValueError(f"Unknown option id: {option_id}")


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
            if boon_id in OPTION_DEFS:
                print(f"  - {OPTION_DEFS[boon_id].name}: {OPTION_DEFS[boon_id].description}")
    else:
        print("Run Boons: none")
    print()


def render_hub(campaign: CampaignState, save_file: str) -> None:
    clear_screen()
    print("Quiet Relay: 2026 - Operations Base [Data-Driven]")
    print("-" * 84)
    print(wrap(
        "Late 2026. Rain ticks against emergency floodlights while the expedition team regroups in a ruined signal base. "
        "Beyond the shutters waits the Rain Toll Corridor, a short but hostile district warped by bells, transit steel, and ash."
    ))
    print()
    print(f"District: {DISTRICT_NAME}")
    print(f"Last result: {campaign.last_result}")
    print(f"Record: {campaign.wins} wins / {campaign.losses} losses | Best nodes cleared: {campaign.best_nodes_cleared}")
    print(f"Save file: {save_file}")
    if campaign.expedition_active:
        node = DISTRICT_NODES[campaign.current_node_index]
        print(f"Expedition in progress: node {campaign.current_node_index + 1}/{len(DISTRICT_NODES)} - {node.title}")
    else:
        print("No expedition currently active.")
    render_party(campaign)


def render_node_banner(node: DistrictNode, campaign: CampaignState) -> None:
    clear_screen()
    print(f"{DISTRICT_NAME}")
    print(f"Node {campaign.current_node_index + 1}/{len(DISTRICT_NODES)} - {node.title}")
    print("-" * 84)
    print(wrap(node.text))
    print()


# ---------------------------------------------------------------------------
# Expedition flow
# ---------------------------------------------------------------------------


def create_slice_enemies(node: DistrictNode) -> List[qr.Combatant]:
    enemies: List[qr.Combatant] = []
    for idx, enemy_id in enumerate(node.enemy_ids, start=1):
        if enemy_id in qr.BOSS_BLUEPRINTS:
            enemies.append(qr.create_boss(enemy_id))
        else:
            enemies.append(qr.create_enemy(enemy_id, idx))
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
    if "bellbreaker_oil" in option_ids and campaign.current_node_index >= 3:
        return "bellbreaker_oil"
    if "stage_light" in option_ids and campaign.starting_spotlight < 2:
        return "stage_light"
    if "iron_mesh" in option_ids:
        return "iron_mesh"
    return option_ids[0]


def offer_rewards(campaign: CampaignState, option_ids: Sequence[str], auto: bool) -> None:
    if not option_ids:
        return
    print("Choose one reward:")
    menu = [(option_id, f"{OPTION_DEFS[option_id].name} - {OPTION_DEFS[option_id].description}") for option_id in option_ids]
    choice = prompt_menu(
        title="",
        options=menu,
        auto=auto,
        auto_choice=auto_choose_option(campaign, option_ids) if auto else None,
    )
    result = apply_option(campaign, choice)
    print(wrap(result))
    campaign.record(f"Reward chosen: {OPTION_DEFS[choice].name}.")


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


def write_run_report(campaign: CampaignState, filepath: str) -> None:
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as handle:
        handle.write("Quiet Relay: 2026 - Vertical Slice Run Report\n")
        handle.write("=" * 72 + "\n")
        handle.write(f"District: {DISTRICT_NAME}\n")
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
    log_path = os.path.join(log_dir, f"{campaign.current_node_index + 1:02d}_{node.node_id}.txt")
    state.save_log(log_path)
    campaign.record(f"Battle at {node.title}: {winner}. Log: {log_path}")
    print(f"Battle log written to: {log_path}")

    normalize_party_between_battles(campaign)

    if winner != "player":
        campaign.losses += 1
        campaign.best_nodes_cleared = max(campaign.best_nodes_cleared, campaign.current_node_index)
        campaign.last_result = f"Defeat at {node.title} after clearing {campaign.current_node_index} nodes."
        campaign.expedition_active = False
        campaign.record(campaign.last_result)
        return False

    campaign.run_shards += node.shards
    print(f"Victory. Echo shards gained: {node.shards}. Total shards this run: {campaign.run_shards}")
    campaign.record(f"Cleared {node.title}. Shards total: {campaign.run_shards}.")
    if node.reward_options:
        offer_rewards(campaign, node.reward_options, auto=auto)
    return True


def resolve_event_node(campaign: CampaignState, node: DistrictNode, auto: bool) -> None:
    print(wrap(node.text))
    if node.reward_options:
        offer_rewards(campaign, node.reward_options, auto=auto)
    campaign.record(f"Resolved event node: {node.title}.")


def finish_victory(campaign: CampaignState) -> None:
    campaign.expedition_active = False
    campaign.wins += 1
    campaign.best_nodes_cleared = max(campaign.best_nodes_cleared, len(DISTRICT_NODES))
    campaign.last_result = f"Victory in {DISTRICT_NAME}. Total shards earned: {campaign.run_shards}."
    campaign.record(campaign.last_result)


def run_expedition(campaign: CampaignState, auto: bool, save_file: str, log_dir: str) -> None:
    while campaign.expedition_active and campaign.current_node_index < len(DISTRICT_NODES):
        node = DISTRICT_NODES[campaign.current_node_index]
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

        campaign.current_node_index += 1
        campaign.best_nodes_cleared = max(campaign.best_nodes_cleared, campaign.current_node_index)
        save_campaign(campaign, save_file)

        if campaign.current_node_index >= len(DISTRICT_NODES):
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
                reset_party_for_new_expedition(campaign)
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
            reset_party_for_new_expedition(campaign)
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
            campaign.expedition_active = loaded.expedition_active
            campaign.current_node_index = loaded.current_node_index
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
        description="Quiet Relay: 2026 vertical slice",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--auto", action="store_true", help="Run the slice without prompts.")
    parser.add_argument("--seed", type=int, default=2026, help="Seed used when creating a new campaign.")
    parser.add_argument("--save-file", default=DEFAULT_SAVE_FILE, help="JSON save file path.")
    parser.add_argument("--log-dir", default=DEFAULT_LOG_DIR, help="Directory for per-battle logs.")
    parser.add_argument("--fresh", action="store_true", help="Ignore existing save data and start a fresh campaign.")
    parser.add_argument("--load", action="store_true", help="Load the save file immediately if it exists.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    if args.load and not os.path.exists(args.save_file):
        print(f"No save file found at {args.save_file}")
        return 2

    if args.load and not args.fresh:
        campaign = load_campaign(args.save_file)
    else:
        campaign = new_campaign(args.seed)
        if os.path.exists(args.save_file) and not args.fresh and not args.auto:
            print(f"Existing save found at {args.save_file}. You can load it from the hub menu.")

    hub_menu(campaign, save_file=args.save_file, auto=args.auto, log_dir=args.log_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
