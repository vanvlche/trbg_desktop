
#!/usr/bin/env python3
"""
Quiet Relay: 2026 - Terminal Combat Core

A pure-Python terminal combat prototype for the user's design spec.
Features:
- battle state
- turn order
- skill resolution
- band conversion
- posture system
- break / stagger
- guard / dodge / parry
- Spotlight meter
- rich logging
- manual player input per action
- auto mode for tests

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import textwrap
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import quiet_relay_content_loader as qrc

# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def clamp_int(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def ceil_int(value: float) -> int:
    return int(math.ceil(value))


def sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


# ---------------------------------------------------------------------------
# Bands, affinities, postures, and content loaded from JSON
# ---------------------------------------------------------------------------

CONTENT = qrc.load_content(reference_file=__file__)

BANDS = [
    (entry["name"], int(entry["min"]), int(entry["max"]))
    for entry in CONTENT.rules["bands"]
]
BAND_NAME_TO_INDEX = {name: idx for idx, (name, _, _) in enumerate(BANDS)}
INDEX_TO_BAND_NAME = {idx: name for idx, (name, _, _) in enumerate(BANDS)}

DAMAGE_TIERS = {name: int(value) for name, value in CONTENT.rules["damage_tiers"].items()}
BREAK_TIERS = {name: int(value) for name, value in CONTENT.rules["break_tiers"].items()}

AFFINITY_ORDER = list(CONTENT.affinity_order)
AFFINITY_STRONG_VS = dict(CONTENT.affinity_strong_vs)
AFFINITY_STATUS = dict(CONTENT.affinity_status)

CHARACTER_BLUEPRINTS = CONTENT.character_blueprints
SKILL_DATA = CONTENT.skill_data
ENEMY_BLUEPRINTS = CONTENT.enemy_data
BOSS_BLUEPRINTS = CONTENT.boss_data
WEAPON_DATA = CONTENT.weapon_data
RELIC_DATA = CONTENT.relic_data

STATUS_DISPLAY_ORDER = [
    "scorch",
    "snare",
    "soak",
    "jolt",
    "hex",
    "reveal",
    "taunt",
    "brace_guard",
    "feint_circuit",
    "exposed_self",
    "delayed_overhead",
    "airborne",
    "relay_mark",
]
OFFENSIVE_SKILL_KINDS = {"attack", "spell", "ranged_attack", "finisher"}
MINOR_NEGATIVE_STATUSES = ("scorch", "snare", "soak", "jolt", "hex", "reveal")
POSITION_SYSTEM = CONTENT.rules.get("position_system", {})
POSITION_ORDER = ("withdrawn", "set", "pressing")
POSITION_INDEX = {name: idx for idx, name in enumerate(POSITION_ORDER)}
POSITION_DEFAULT = str(POSITION_SYSTEM.get("default", "set"))
if POSITION_DEFAULT not in POSITION_INDEX:
    POSITION_DEFAULT = "set"
POSITION_PUNISH_TAGS = {"heavy", "channel", "burst_start"}
ENABLE_SEMANTIC_EMOJI_UI = True

BOSS_STAT_MULTIPLIER = 1.5
ENEMY_DAMAGE_MULTIPLIER = 1.25
ENEMY_SPOTLIGHT_DAMAGE_MULTIPLIER = 1.15
ENEMY_SPOTLIGHT_BREAK_MULTIPLIER = 1.15

GUARD_POWER_REQUIREMENT = 55
DODGE_PRECISION_REQUIREMENT = 62
PARRY_POWER_REQUIREMENT = 64
PARRY_PRECISION_REQUIREMENT = 66
PARRY_COMPOSURE_REQUIREMENT = 64

DODGE_BREAK_COST = 8
DODGE_EXTRA_BREAK_ON_FAIL = 10
PARRY_GUARD_COST = 10
PARRY_BREAK_COST = 12
PARRY_EXTRA_BREAK_ON_FAIL = 12
COMPOSURE_TEMPO_THRESHOLD = 160

UI_ICONS = {
    "battle": "⚔️",
    "boss": "👑",
    "hub": "🕯️",
    "party": "⛭",
    "enemies": "◬",
    "round": "⏱️",
    "spotlight": "☀️",
    "load": "📂",
    "continue": "▶️",
    "inspect": "🔎",
}


def ui_icon(key: str) -> str:
    if not ENABLE_SEMANTIC_EMOJI_UI:
        return ""
    return UI_ICONS.get(key, "")


def emoji_label(key: str, text: str) -> str:
    icon = ui_icon(key)
    return f"{icon} {text}" if icon else text

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Skill:
    skill_id: str
    display_name: str
    owner: str
    kind: str
    affinity: str
    target: str
    spotlight_cost: int
    primary_scale: str
    secondary_scale: str
    damage_tier: str
    break_tier: str
    effect_id: str
    tags: Tuple[str, ...] = ()


@dataclass(frozen=True)
class DefensiveReadProfile:
    tag: str
    primary_axis: str
    secondary_axis: str
    preferred_reactions: Tuple[str, ...]


@dataclass(frozen=True)
class PatternReadSnapshot:
    profile_tag: str
    primary_band_idx: int
    secondary_band_idx: int
    raw_tier: int
    triplet: Tuple[int, int, int]


@dataclass
class BattleCursor:
    battle_started: bool = False
    turn_order_ids: List[str] = field(default_factory=list)
    next_actor_index: int = 0


@dataclass
class LogEntry:
    round_number: int
    text: str


@dataclass
class BattleLogger:
    echo: bool = True
    entries: List[LogEntry] = field(default_factory=list)

    def log(self, round_number: int, text: str) -> None:
        entry = LogEntry(round_number=round_number, text=text)
        self.entries.append(entry)
        if self.echo:
            print(text)

    def dump(self, filepath: str) -> None:
        with open(filepath, "w", encoding="utf-8") as handle:
            for entry in self.entries:
                handle.write(f"[Round {entry.round_number:02d}] {entry.text}\n")


@dataclass
class Combatant:
    entity_id: str
    name: str
    team: str
    affinity: str
    max_hp: int
    hp: int
    max_guard: int
    guard: int
    max_break: int
    break_meter: int
    speed: int
    skills: List[str]
    role: str = ""
    is_boss: bool = False
    posture: str = "flow"
    position: str = "set"
    barrier: int = 0
    conditions: Dict[str, int] = field(default_factory=dict)
    next_attack_power_bonus: int = 0
    crit_spotlight_used_this_turn: bool = False
    times_acted: int = 0
    last_skill_used: Optional[str] = None
    metadata: Dict[str, object] = field(default_factory=dict)

    def alive(self) -> bool:
        return self.hp > 0

    def has_condition(self, name: str) -> bool:
        return self.conditions.get(name, 0) > 0

    def add_condition(self, name: str, duration: int) -> None:
        self.conditions[name] = max(duration, self.conditions.get(name, 0))

    def remove_condition(self, name: str) -> None:
        if name in self.conditions:
            del self.conditions[name]

    def condition_summary(self) -> str:
        parts = []
        for status in STATUS_DISPLAY_ORDER:
            if self.conditions.get(status, 0) > 0:
                parts.append(f"{status}:{self.conditions[status]}")
        if self.barrier > 0:
            parts.append(f"barrier:{self.barrier}")
        return ", ".join(parts)

    def start_turn_tick(self, state: "BattleState") -> bool:
        """
        Returns True if the unit can act this turn, False if its turn is skipped.
        """
        if not self.alive():
            return False

        self.crit_spotlight_used_this_turn = False

        # Tick ongoing effects before duration reduction.
        if self.has_condition("scorch"):
            dmg = max(4, int(self.max_hp * 0.05))
            state.logger.log(state.round_number, f"{self.name} is scorched for {dmg} damage.")
            state.apply_direct_hp_loss(self, dmg, reason="scorch")
        if self.has_condition("jolt"):
            guard_loss = 8
            state.logger.log(state.round_number, f"{self.name} crackles with jolt and loses {guard_loss} guard.")
            self.guard = max(0, self.guard - guard_loss)
        if self.has_condition("staggered"):
            state.logger.log(state.round_number, f"{self.name} is staggered and loses the turn.")
            self.break_meter = self.max_break
            self.remove_condition("staggered")
            # Decrement other timed conditions even on a skipped turn.
            self._decrement_conditions(state)
            return False

        self._decrement_conditions(state)
        return True

    def _decrement_conditions(self, state: "BattleState") -> None:
        expired: List[str] = []
        for name in list(self.conditions.keys()):
            if name == "staggered":
                continue
            self.conditions[name] -= 1
            if self.conditions[name] <= 0:
                expired.append(name)
        for name in expired:
            del self.conditions[name]
            if name not in {"relay_mark"}:
                state.logger.log(state.round_number, f"{self.name} is no longer affected by {name}.")

    def restore_guard(self, amount: int) -> int:
        if amount <= 0:
            return 0
        before = self.guard
        self.guard = min(self.max_guard, self.guard + amount)
        return self.guard - before

    def summary_line(self) -> str:
        condition_text = self.condition_summary()
        if condition_text:
            condition_text = f" | {condition_text}"
        return (
            f"{self.name:<18} HP {self.hp:>3}/{self.max_hp:<3}  "
            f"GUARD {self.guard:>3}/{self.max_guard:<3}  "
            f"BREAK {self.break_meter:>3}/{self.max_break:<3}  "
            f"{self.affinity:<5}  posture={self.posture:<7} pos={self.position:<9}{condition_text}"
        )


@dataclass
class ResolvedInputs:
    power: int
    precision: int
    composure: int
    band_indices: Dict[str, int]
    band_names: Dict[str, str]
    posture: str
    posture_reason: str


@dataclass
class ActionContext:
    user: Combatant
    skill: Skill
    targets: List[Combatant]
    inputs: ResolvedInputs
    spotlight_spent: int = 0
    crit_happened: bool = False
    notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parsing static data into Skill objects
# ---------------------------------------------------------------------------


def build_skills() -> Dict[str, Skill]:
    result: Dict[str, Skill] = {}
    for skill_id, raw in SKILL_DATA.items():
        result[skill_id] = Skill(
            skill_id=skill_id,
            display_name=raw["display_name"],
            owner=raw["owner"],
            kind=raw["kind"],
            affinity=raw["affinity"],
            target=raw["target"],
            spotlight_cost=int(raw["spotlight_cost"]),
            primary_scale=raw["scale"]["primary"],
            secondary_scale=raw["scale"]["secondary"],
            damage_tier=raw["output"]["damage"],
            break_tier=raw["output"]["break"],
            effect_id=raw["effect_id"],
            tags=tuple(str(tag) for tag in raw.get("tags", [])),
        )
    return result


SKILLS = build_skills()

# ---------------------------------------------------------------------------
# Blueprints -> combatant constructors
# ---------------------------------------------------------------------------

HP_PROFILE = {name: int(value) for name, value in CONTENT.rules["stat_profiles"]["hp"].items()}
GUARD_PROFILE = {name: int(value) for name, value in CONTENT.rules["stat_profiles"]["guard"].items()}
BREAK_PROFILE = {name: int(value) for name, value in CONTENT.rules["stat_profiles"]["break"].items()}
SPEED_PROFILE = {name: int(value) for name, value in CONTENT.rules["stat_profiles"]["speed"].items()}


def create_player(character_id: str) -> Combatant:
    raw = CHARACTER_BLUEPRINTS[character_id]
    stats = raw["stat_profile"]
    combatant = Combatant(
        entity_id=character_id,
        name=raw["display_name"],
        team="player",
        affinity=raw["default_affinity"],
        max_hp=HP_PROFILE[stats["hp"]],
        hp=HP_PROFILE[stats["hp"]],
        max_guard=GUARD_PROFILE[stats["guard"]],
        guard=GUARD_PROFILE[stats["guard"]],
        max_break=BREAK_PROFILE[stats["break"]],
        break_meter=BREAK_PROFILE[stats["break"]],
        speed=SPEED_PROFILE[stats["speed"]],
        skills=list(raw["skills"]),
        role=raw["role"],
        is_boss=False,
    )
    combatant.metadata["weapon_id"] = raw.get("weapon")
    combatant.metadata["weapon_name"] = WEAPON_DATA.get(raw.get("weapon", ""), {}).get("display_name", raw.get("weapon", ""))
    combatant.metadata["relic_ids"] = list(raw.get("starting_relics", []))
    combatant.metadata["relic_names"] = [
        RELIC_DATA.get(relic_id, {}).get("display_name", relic_id)
        for relic_id in raw.get("starting_relics", [])
    ]
    return combatant


def create_enemy(enemy_id: str, index: int = 1) -> Combatant:
    raw = ENEMY_BLUEPRINTS[enemy_id]
    stats = raw["stat_profile"]

    hp = HP_PROFILE[stats["hp"]]
    guard = GUARD_PROFILE[stats["guard"]]
    break_value = BREAK_PROFILE[stats["break"]]
    speed = SPEED_PROFILE[stats["speed"]]

    if raw["tier"] == "elite":
        hp = int(hp * 1.35)
        guard = int(guard * 1.25)
        break_value = int(break_value * 1.25)
        speed = max(speed, 10)

    combatant = Combatant(
        entity_id=f"{enemy_id}_{index}",
        name=raw["display_name"] if index == 1 else f"{raw['display_name']} #{index}",
        team="enemy",
        affinity=raw["affinity"],
        max_hp=hp,
        hp=hp,
        max_guard=guard,
        guard=guard,
        max_break=break_value,
        break_meter=break_value,
        speed=speed,
        skills=[],
        role=raw["role"],
        is_boss=False,
    )

    combatant.metadata["blueprint_id"] = enemy_id
    if enemy_id == "canal_seraph":
        combatant.add_condition("airborne", 99)
    return combatant


def create_boss(boss_id: str) -> Combatant:
    raw = BOSS_BLUEPRINTS[boss_id]
    stats = raw["base_stats"]
    hp = ceil_int(int(stats["hp"]) * BOSS_STAT_MULTIPLIER)
    guard = ceil_int(int(stats["guard"]) * BOSS_STAT_MULTIPLIER)
    break_value = ceil_int(int(stats["break"]) * BOSS_STAT_MULTIPLIER)
    combatant = Combatant(
        entity_id=boss_id,
        name=raw["display_name"],
        team="enemy",
        affinity=raw["primary_affinity"],
        max_hp=hp,
        hp=hp,
        max_guard=guard,
        guard=guard,
        max_break=break_value,
        break_meter=break_value,
        speed=stats["speed"],
        skills=[],
        role=raw["role"],
        is_boss=True,
    )
    combatant.metadata["blueprint_id"] = boss_id
    return combatant


# ---------------------------------------------------------------------------
# Band conversion and posture resolution
# ---------------------------------------------------------------------------


def band_index_for_value(value: int) -> int:
    value = clamp_int(value, 0, 100)
    for idx, (_, low, high) in enumerate(BANDS):
        if low <= value <= high:
            return idx
    return 0


def band_name_for_value(value: int) -> str:
    return INDEX_TO_BAND_NAME[band_index_for_value(value)]


def describe_band(value: int) -> str:
    return f"{value:>3} ({band_name_for_value(value)})"


def resolve_posture(
    power: int,
    precision: int,
    composure: int,
    primary_scale: str,
) -> Tuple[str, str, Dict[str, int], Dict[str, str]]:
    raw_values = {"power": power, "precision": precision, "composure": composure}
    band_indices = {key: band_index_for_value(val) for key, val in raw_values.items()}
    band_names = {key: INDEX_TO_BAND_NAME[idx] for key, idx in band_indices.items()}
    idx_values = list(band_indices.values())

    if max(idx_values) - min(idx_values) <= 1:
        return ("flow", "balanced spread", band_indices, band_names)

    highest = max(band_indices.values())
    tied = [dim for dim, idx in band_indices.items() if idx == highest]
    if len(tied) == 1:
        dominant = tied[0]
    else:
        highest_raw = max(raw_values[dim] for dim in tied)
        tied_by_raw = [dim for dim in tied if raw_values[dim] == highest_raw]
        if len(tied_by_raw) == 1:
            dominant = tied_by_raw[0]
        elif primary_scale in tied_by_raw:
            dominant = primary_scale
        else:
            for fallback in ("power", "precision", "composure"):
                if fallback in tied_by_raw:
                    dominant = fallback
                    break

    posture = {
        "power": "ravage",
        "precision": "focus",
        "composure": "bastion",
    }[dominant]
    return (posture, f"{dominant} dominant", band_indices, band_names)


def make_resolved_inputs(power: int, precision: int, composure: int, skill: Skill) -> ResolvedInputs:
    posture, reason, band_indices, band_names = resolve_posture(
        power=power,
        precision=precision,
        composure=composure,
        primary_scale=skill.primary_scale,
    )
    return ResolvedInputs(
        power=clamp_int(power, 0, 100),
        precision=clamp_int(precision, 0, 100),
        composure=clamp_int(composure, 0, 100),
        band_indices=band_indices,
        band_names=band_names,
        posture=posture,
        posture_reason=reason,
    )


def virtual_enemy_inputs(enemy: Combatant) -> Tuple[int, int, int]:
    role = enemy.role
    # Crafted to yield varied postures.
    if role in {"slow_bruiser", "armored_tank", "boss_guard_break"}:
        return (84, 36, 54)
    if role in {"controller", "defender_controller"}:
        return (42, 74, 55)
    if role in {"setup_caster", "flying_caster", "burst_caster", "support_cleanser", "boss_affinity_rotate"}:
        return (38, 70, 62)
    if role in {"fast_skirmisher", "predator", "boss_pack_hunter"}:
        return (68, 78, 46)
    if role in {"guard_drain_parasite", "mimic", "boss_pattern_punisher"}:
        return (54, 66, 74)
    return (55, 55, 55)


# ---------------------------------------------------------------------------
# Battle state
# ---------------------------------------------------------------------------


@dataclass
class BattleState:
    players: List[Combatant]
    enemies: List[Combatant]
    rng: random.Random
    logger: BattleLogger
    interactive: bool = True
    round_number: int = 1
    spotlight: int = 0
    spotlight_max: int = 5
    enemy_spotlight: int = 0
    enemy_spotlight_max: int = 5
    node_axis_scores: Dict[str, int] = field(default_factory=lambda: {"power": 60, "precision": 60, "composure": 60})
    player_tempo_meter: int = 0
    bonus_action_rounds: Set[Tuple[int, str]] = field(default_factory=set)
    last_player_inputs: Tuple[int, int, int] = (60, 60, 60)
    relay_target_id: Optional[str] = None
    relay_source_name: Optional[str] = None
    last_successful_reaction: Optional[str] = None
    last_successful_reaction_actor_id: Optional[str] = None
    last_incoming_skill_tags: Tuple[str, ...] = ()
    last_reaction_round: int = 0
    once_per_battle_flags: Set[str] = field(default_factory=set)
    stored_offense_bonus: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    counterphrase_charge_actors: Set[str] = field(default_factory=set)
    counterphrase_payloads: Dict[str, Dict[str, float]] = field(default_factory=dict)
    reaction_read_cache: Dict[Tuple[int, str, str, str], PatternReadSnapshot] = field(default_factory=dict)
    next_self_risk_reduction: Dict[str, float] = field(default_factory=dict)
    cursor: BattleCursor = field(default_factory=BattleCursor)
    battle_over: bool = False
    winner: Optional[str] = None

    def living_players(self) -> List[Combatant]:
        return [unit for unit in self.players if unit.alive()]

    def living_enemies(self) -> List[Combatant]:
        return [unit for unit in self.enemies if unit.alive()]

    def everyone(self) -> List[Combatant]:
        return self.players + self.enemies

    def get_opponents(self, unit: Combatant) -> List[Combatant]:
        return self.living_enemies() if unit.team == "player" else self.living_players()

    def get_allies(self, unit: Combatant) -> List[Combatant]:
        return self.living_players() if unit.team == "player" else self.living_enemies()

    def change_player_spotlight(self, amount: int, reason: str) -> None:
        old = self.spotlight
        self.spotlight = clamp_int(self.spotlight + amount, 0, self.spotlight_max)
        delta = self.spotlight - old
        if delta != 0:
            sign_text = "+" if delta > 0 else ""
            self.logger.log(self.round_number, f"Player Spotlight {sign_text}{delta} ({reason}) -> {self.spotlight}/{self.spotlight_max}")

    def change_enemy_spotlight(self, amount: int, reason: str) -> None:
        old = self.enemy_spotlight
        self.enemy_spotlight = clamp_int(self.enemy_spotlight + amount, 0, self.enemy_spotlight_max)
        delta = self.enemy_spotlight - old
        if delta != 0:
            sign_text = "+" if delta > 0 else ""
            self.logger.log(
                self.round_number,
                f"Enemy Spotlight {sign_text}{delta} ({reason}) -> {self.enemy_spotlight}/{self.enemy_spotlight_max}",
            )

    def change_spotlight(self, amount: int, reason: str) -> None:
        self.change_player_spotlight(amount, reason)

    def apply_direct_hp_loss(self, target: Combatant, amount: int, reason: str = "") -> None:
        if not target.alive():
            return
        final = ceil_int(amount * self.damage_taken_mult(target))
        final = max(0, final)
        target.hp = max(0, target.hp - final)
        if reason:
            self.logger.log(self.round_number, f"{target.name} loses {final} HP ({reason}).")
        if target.hp <= 0:
            self.logger.log(self.round_number, f"{target.name} falls.")

    def damage_taken_mult(self, target: Combatant) -> float:
        mult = 1.0
        if target.has_condition("hex"):
            mult *= 1.10
        if target.has_condition("exposed_self"):
            mult *= 1.15
        if target.has_condition("reveal"):
            mult *= 1.05
        return mult

    def render_state(self) -> None:
        print("\n" + "=" * 84)
        axes = self.node_axis_scores
        print(
            f"{emoji_label('round', f'ROUND {self.round_number}')} | "
            f"{emoji_label('spotlight', 'Player Spotlight')} {self.spotlight}/{self.spotlight_max} | "
            f"Enemy Spotlight {self.enemy_spotlight}/{self.enemy_spotlight_max} | "
            f"Tempo {self.player_tempo_meter}/{COMPOSURE_TEMPO_THRESHOLD}"
        )
        print(
            f"Node Axis: Power {axes.get('power', 60)}, "
            f"Precision {axes.get('precision', 60)}, "
            f"Composure {axes.get('composure', 60)}"
        )
        print("-" * 84)
        print(emoji_label("party", "PLAYERS"))
        for idx, unit in enumerate(self.players, start=1):
            prefix = ">" if unit.alive() else "x"
            print(f"{prefix}{idx}. {unit.summary_line()}")
        print("-" * 84)
        print(emoji_label("enemies", "ENEMIES"))
        for idx, unit in enumerate(self.enemies, start=1):
            prefix = ">" if unit.alive() else "x"
            print(f"{prefix}{idx}. {unit.summary_line()}")
        print("=" * 84 + "\n")

    def initiative_order(self) -> List[Combatant]:
        units = [unit for unit in self.everyone() if unit.alive()]
        def initiative_value(unit: Combatant) -> float:
            speed = unit.speed
            if unit.has_condition("snare"):
                speed -= 3
            if unit.has_condition("jolt"):
                speed -= 1
            # Small variance to keep turns dynamic.
            return speed + self.rng.random() * 2.0
        return sorted(units, key=initiative_value, reverse=True)

    def check_end(self) -> bool:
        if not self.living_players():
            self.battle_over = True
            self.winner = "enemy"
            return True
        if not self.living_enemies():
            self.battle_over = True
            self.winner = "player"
            return True
        return False

    def save_log(self, filepath: str) -> None:
        self.logger.dump(filepath)


def resolved_inputs_to_payload(inputs: ResolvedInputs) -> Dict[str, object]:
    return {
        "power": inputs.power,
        "precision": inputs.precision,
        "composure": inputs.composure,
        "band_indices": {str(key): int(value) for key, value in inputs.band_indices.items()},
        "band_names": {str(key): str(value) for key, value in inputs.band_names.items()},
        "posture": inputs.posture,
        "posture_reason": inputs.posture_reason,
    }


def resolved_inputs_from_payload(payload: Dict[str, object]) -> ResolvedInputs:
    band_indices = {str(key): int(value) for key, value in dict(payload.get("band_indices", {})).items()}
    band_names = {
        str(key): str(value)
        for key, value in dict(payload.get("band_names", {})).items()
    }
    if not band_names:
        band_names = {
            key: INDEX_TO_BAND_NAME.get(value, "set")
            for key, value in band_indices.items()
        }
    return ResolvedInputs(
        power=int(payload["power"]),
        precision=int(payload["precision"]),
        composure=int(payload["composure"]),
        band_indices=band_indices,
        band_names=band_names,
        posture=str(payload.get("posture", "flow")),
        posture_reason=str(payload.get("posture_reason", "")),
    )


def pattern_read_snapshot_to_payload(snapshot: PatternReadSnapshot) -> Dict[str, object]:
    return {
        "profile_tag": snapshot.profile_tag,
        "primary_band_idx": snapshot.primary_band_idx,
        "secondary_band_idx": snapshot.secondary_band_idx,
        "raw_tier": snapshot.raw_tier,
        "triplet": list(snapshot.triplet),
    }


def pattern_read_snapshot_from_payload(payload: Dict[str, object]) -> PatternReadSnapshot:
    return PatternReadSnapshot(
        profile_tag=str(payload["profile_tag"]),
        primary_band_idx=int(payload["primary_band_idx"]),
        secondary_band_idx=int(payload["secondary_band_idx"]),
        raw_tier=int(payload["raw_tier"]),
        triplet=tuple(int(value) for value in list(payload["triplet"])[:3]),
    )


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, ResolvedInputs):
        payload = resolved_inputs_to_payload(value)
        payload["__qr_type"] = "ResolvedInputs"
        return payload
    if isinstance(value, PatternReadSnapshot):
        payload = pattern_read_snapshot_to_payload(value)
        payload["__qr_type"] = "PatternReadSnapshot"
        return payload
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, set):
        return sorted(_json_safe_value(item) for item in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _json_restore_value(value: Any) -> Any:
    if isinstance(value, dict):
        kind = value.get("__qr_type")
        if kind == "ResolvedInputs":
            return resolved_inputs_from_payload(value)
        if kind == "PatternReadSnapshot":
            return pattern_read_snapshot_from_payload(value)
        return {str(key): _json_restore_value(item) for key, item in value.items() if key != "__qr_type"}
    if isinstance(value, list):
        return [_json_restore_value(item) for item in value]
    return value


def combatant_to_payload(unit: Combatant) -> Dict[str, object]:
    return {
        "entity_id": unit.entity_id,
        "name": unit.name,
        "team": unit.team,
        "affinity": unit.affinity,
        "max_hp": unit.max_hp,
        "hp": unit.hp,
        "max_guard": unit.max_guard,
        "guard": unit.guard,
        "max_break": unit.max_break,
        "break_meter": unit.break_meter,
        "speed": unit.speed,
        "skills": list(unit.skills),
        "role": unit.role,
        "is_boss": unit.is_boss,
        "posture": unit.posture,
        "position": unit.position,
        "barrier": unit.barrier,
        "conditions": {str(key): int(value) for key, value in unit.conditions.items()},
        "next_attack_power_bonus": unit.next_attack_power_bonus,
        "crit_spotlight_used_this_turn": unit.crit_spotlight_used_this_turn,
        "times_acted": unit.times_acted,
        "last_skill_used": unit.last_skill_used,
        "metadata": _json_safe_value(unit.metadata),
    }


def combatant_from_payload(payload: Dict[str, object]) -> Combatant:
    unit = Combatant(
        entity_id=str(payload["entity_id"]),
        name=str(payload.get("name", payload["entity_id"])),
        team=str(payload.get("team", "player")),
        affinity=str(payload.get("affinity", "neutral")),
        max_hp=int(payload.get("max_hp", 1)),
        hp=int(payload.get("hp", payload.get("max_hp", 1))),
        max_guard=int(payload.get("max_guard", 0)),
        guard=int(payload.get("guard", payload.get("max_guard", 0))),
        max_break=int(payload.get("max_break", 0)),
        break_meter=int(payload.get("break_meter", payload.get("max_break", 0))),
        speed=int(payload.get("speed", 0)),
        skills=[str(skill_id) for skill_id in list(payload.get("skills", []))],
        role=str(payload.get("role", "")),
        is_boss=bool(payload.get("is_boss", False)),
        posture=str(payload.get("posture", "flow")),
        position=str(payload.get("position", POSITION_DEFAULT)),
        barrier=int(payload.get("barrier", 0)),
        conditions={str(key): int(value) for key, value in dict(payload.get("conditions", {})).items()},
        next_attack_power_bonus=int(payload.get("next_attack_power_bonus", 0)),
        crit_spotlight_used_this_turn=bool(payload.get("crit_spotlight_used_this_turn", False)),
        times_acted=int(payload.get("times_acted", 0)),
        last_skill_used=(
            str(payload["last_skill_used"])
            if payload.get("last_skill_used") is not None
            else None
        ),
        metadata=dict(_json_restore_value(payload.get("metadata", {}))),
    )
    return unit


def battle_cursor_to_payload(cursor: BattleCursor) -> Dict[str, object]:
    return {
        "battle_started": cursor.battle_started,
        "turn_order_ids": list(cursor.turn_order_ids),
        "next_actor_index": cursor.next_actor_index,
    }


def battle_cursor_from_payload(payload: Dict[str, object]) -> BattleCursor:
    turn_order_ids = [str(actor_id) for actor_id in list(payload.get("turn_order_ids", []))]
    next_actor_index = int(payload.get("next_actor_index", 0))
    next_actor_index = max(0, min(next_actor_index, len(turn_order_ids)))
    return BattleCursor(
        battle_started=bool(payload.get("battle_started", False)),
        turn_order_ids=turn_order_ids,
        next_actor_index=next_actor_index,
    )


def reaction_read_cache_to_payload(
    cache: Dict[Tuple[int, str, str, str], PatternReadSnapshot],
) -> List[Dict[str, object]]:
    entries: List[Dict[str, object]] = []
    for key, snapshot in cache.items():
        round_number, attacker_id, target_id, profile_tag = key
        entries.append(
            {
                "key": {
                    "round_number": round_number,
                    "attacker_id": attacker_id,
                    "target_id": target_id,
                    "profile_tag": profile_tag,
                },
                "snapshot": pattern_read_snapshot_to_payload(snapshot),
            }
        )
    return entries


def reaction_read_cache_from_payload(
    entries: Sequence[Dict[str, object]],
) -> Dict[Tuple[int, str, str, str], PatternReadSnapshot]:
    cache: Dict[Tuple[int, str, str, str], PatternReadSnapshot] = {}
    for entry in entries:
        key_payload = dict(entry.get("key", {}))
        key = (
            int(key_payload["round_number"]),
            str(key_payload["attacker_id"]),
            str(key_payload["target_id"]),
            str(key_payload["profile_tag"]),
        )
        cache[key] = pattern_read_snapshot_from_payload(dict(entry["snapshot"]))
    return cache


def battle_state_to_payload(state: BattleState) -> Dict[str, object]:
    return {
        "round_number": state.round_number,
        "spotlight": state.spotlight,
        "spotlight_max": state.spotlight_max,
        "enemy_spotlight": state.enemy_spotlight,
        "enemy_spotlight_max": state.enemy_spotlight_max,
        "node_axis_scores": {str(key): int(value) for key, value in state.node_axis_scores.items()},
        "player_tempo_meter": state.player_tempo_meter,
        "bonus_action_rounds": [[int(round_number), str(actor_id)] for round_number, actor_id in state.bonus_action_rounds],
        "last_player_inputs": list(state.last_player_inputs),
        "relay_target_id": state.relay_target_id,
        "relay_source_name": state.relay_source_name,
        "last_successful_reaction": state.last_successful_reaction,
        "last_successful_reaction_actor_id": state.last_successful_reaction_actor_id,
        "last_incoming_skill_tags": list(state.last_incoming_skill_tags),
        "last_reaction_round": state.last_reaction_round,
        "once_per_battle_flags": sorted(state.once_per_battle_flags),
        "stored_offense_bonus": _json_safe_value(state.stored_offense_bonus),
        "counterphrase_charge_actors": sorted(state.counterphrase_charge_actors),
        "counterphrase_payloads": _json_safe_value(state.counterphrase_payloads),
        "reaction_read_cache": reaction_read_cache_to_payload(state.reaction_read_cache),
        "next_self_risk_reduction": _json_safe_value(state.next_self_risk_reduction),
        "battle_over": state.battle_over,
        "winner": state.winner,
    }


def battle_state_from_payload(
    payload: Dict[str, object],
    players: List[Combatant],
    enemies: List[Combatant],
    rng: random.Random,
    logger: BattleLogger,
    interactive: bool = True,
) -> BattleState:
    return BattleState(
        players=players,
        enemies=enemies,
        rng=rng,
        logger=logger,
        interactive=interactive,
        round_number=int(payload.get("round_number", 1)),
        spotlight=int(payload.get("spotlight", 0)),
        spotlight_max=int(payload.get("spotlight_max", 5)),
        enemy_spotlight=int(payload.get("enemy_spotlight", 0)),
        enemy_spotlight_max=int(payload.get("enemy_spotlight_max", 5)),
        node_axis_scores={
            "power": clamp_int(int(dict(payload.get("node_axis_scores", {})).get("power", 60)), 0, 100),
            "precision": clamp_int(int(dict(payload.get("node_axis_scores", {})).get("precision", 60)), 0, 100),
            "composure": clamp_int(int(dict(payload.get("node_axis_scores", {})).get("composure", 60)), 0, 100),
        },
        player_tempo_meter=int(payload.get("player_tempo_meter", 0)),
        bonus_action_rounds={
            (int(item[0]), str(item[1]))
            for item in list(payload.get("bonus_action_rounds", []))
            if isinstance(item, list) and len(item) >= 2
        },
        last_player_inputs=tuple(int(value) for value in list(payload.get("last_player_inputs", [60, 60, 60]))[:3]),
        relay_target_id=(
            str(payload["relay_target_id"])
            if payload.get("relay_target_id") is not None
            else None
        ),
        relay_source_name=(
            str(payload["relay_source_name"])
            if payload.get("relay_source_name") is not None
            else None
        ),
        last_successful_reaction=(
            str(payload["last_successful_reaction"])
            if payload.get("last_successful_reaction") is not None
            else None
        ),
        last_successful_reaction_actor_id=(
            str(payload["last_successful_reaction_actor_id"])
            if payload.get("last_successful_reaction_actor_id") is not None
            else None
        ),
        last_incoming_skill_tags=tuple(str(tag) for tag in list(payload.get("last_incoming_skill_tags", []))),
        last_reaction_round=int(payload.get("last_reaction_round", 0)),
        once_per_battle_flags={str(flag) for flag in list(payload.get("once_per_battle_flags", []))},
        stored_offense_bonus=dict(_json_restore_value(payload.get("stored_offense_bonus", {}))),
        counterphrase_charge_actors={str(actor_id) for actor_id in list(payload.get("counterphrase_charge_actors", []))},
        counterphrase_payloads=dict(_json_restore_value(payload.get("counterphrase_payloads", {}))),
        reaction_read_cache=reaction_read_cache_from_payload(
            list(payload.get("reaction_read_cache", []))
        ),
        next_self_risk_reduction={
            str(key): float(value)
            for key, value in dict(_json_restore_value(payload.get("next_self_risk_reduction", {}))).items()
        },
        battle_over=bool(payload.get("battle_over", False)),
        winner=(str(payload["winner"]) if payload.get("winner") is not None else None),
    )


def rng_state_to_payload(rng: random.Random) -> Dict[str, object]:
    state = rng.getstate()
    return {
        "kind": "python_random_state",
        "version": int(state[0]),
        "internal_state": [int(value) for value in state[1]],
        "gauss_next": state[2],
    }


def rng_from_payload(payload: Dict[str, object]) -> random.Random:
    if payload.get("kind") != "python_random_state":
        raise ValueError("Unsupported RNG payload kind.")
    rng = random.Random()
    internal_state = tuple(int(value) for value in list(payload["internal_state"]))
    rng.setstate((int(payload["version"]), internal_state, payload.get("gauss_next")))
    return rng


# ---------------------------------------------------------------------------
# Affinity and damage math
# ---------------------------------------------------------------------------


def affinity_modifier(skill_affinity: str, target_affinity: str) -> float:
    if skill_affinity == "neutral":
        return 1.0
    if AFFINITY_STRONG_VS.get(skill_affinity) == target_affinity:
        return 1.25
    if AFFINITY_STRONG_VS.get(target_affinity) == skill_affinity:
        return 0.80
    return 1.0


def is_affinity_advantage(skill_affinity: str, target_affinity: str) -> bool:
    return AFFINITY_STRONG_VS.get(skill_affinity) == target_affinity


def is_affinity_disadvantage(skill_affinity: str, target_affinity: str) -> bool:
    return AFFINITY_STRONG_VS.get(target_affinity) == skill_affinity


def compute_scale_multiplier(
    actor: Combatant,
    skill: Skill,
    inputs: ResolvedInputs,
) -> float:
    primary_idx = inputs.band_indices[skill.primary_scale]
    secondary_idx = inputs.band_indices[skill.secondary_scale]

    if actor.next_attack_power_bonus and skill.kind not in {"support", "defense", "utility", "stance", "self_buff"}:
        if skill.primary_scale == "power":
            primary_idx = clamp_int(primary_idx + actor.next_attack_power_bonus, 0, 4)
        if skill.secondary_scale == "power":
            secondary_idx = clamp_int(secondary_idx + actor.next_attack_power_bonus, 0, 4)

    if actor.entity_id == "penitent" and skill.kind == "finisher" and actor.hp <= actor.max_hp // 2:
        if skill.primary_scale == "power":
            primary_idx = clamp_int(primary_idx + 1, 0, 4)
        elif skill.secondary_scale == "power":
            secondary_idx = clamp_int(secondary_idx + 1, 0, 4)

    return 0.78 + 0.17 * primary_idx + 0.07 * secondary_idx


def posture_damage_break_multipliers(posture: str) -> Tuple[float, float]:
    if posture == "ravage":
        return (1.20, 1.30)
    if posture == "focus":
        return (1.00, 0.85)
    if posture == "bastion":
        return (0.95, 1.00)
    return (1.00, 1.00)


def normalized_position_name(position_name: str) -> str:
    if position_name in POSITION_INDEX:
        return position_name
    return POSITION_DEFAULT


def position_profile(position_name: str) -> Dict[str, float]:
    defaults: Dict[str, float] = {
        "outgoing_damage_mult": 1.0,
        "outgoing_break_mult": 1.0,
        "guard_hp_spill_mult": 1.0,
        "guard_break_mult": 1.0,
        "dodge_bonus": 0.0,
        "parry_bonus": 0.0,
        "parry_break_bonus": 0.0,
        "counterphrase_damage_mult": 1.0,
        "counterphrase_break_mult": 1.0,
    }
    states = POSITION_SYSTEM.get("states", {})
    if not isinstance(states, dict):
        return defaults
    raw = states.get(normalized_position_name(position_name), {})
    if not isinstance(raw, dict):
        return defaults
    for key in defaults:
        if key in raw:
            try:
                defaults[key] = float(raw[key])
            except (TypeError, ValueError):
                continue
    return defaults


def position_recent_channel_break_mult(position_name: str) -> float:
    raw = POSITION_SYSTEM.get("recent_channel_break_mult", {})
    if not isinstance(raw, dict):
        return 1.0
    try:
        return float(raw.get(normalized_position_name(position_name), 1.0))
    except (TypeError, ValueError):
        return 1.0


def set_position(state: BattleState, actor: Combatant, new_position: str, reason: Optional[str] = None) -> bool:
    current = normalized_position_name(getattr(actor, "position", POSITION_DEFAULT))
    target = normalized_position_name(new_position)
    actor.position = current
    if current == target:
        return False
    actor.position = target
    if target == "pressing":
        text = f"{actor.name} presses the line."
    elif target == "withdrawn":
        text = f"{actor.name} withdraws behind the guard."
    else:
        text = f"{actor.name} recenters to set footing."
    if reason:
        text = f"{text[:-1]} ({reason})."
    state.logger.log(state.round_number, text)
    return True


def _step_position(state: BattleState, actor: Combatant, delta: int, reason: Optional[str] = None) -> bool:
    current = normalized_position_name(getattr(actor, "position", POSITION_DEFAULT))
    current_idx = POSITION_INDEX[current]
    new_idx = clamp_int(current_idx + delta, 0, len(POSITION_ORDER) - 1)
    return set_position(state, actor, POSITION_ORDER[new_idx], reason=reason)


def step_position_toward_pressing(state: BattleState, actor: Combatant, reason: Optional[str] = None) -> bool:
    return _step_position(state, actor, +1, reason=reason)


def step_position_toward_withdrawn(state: BattleState, actor: Combatant, reason: Optional[str] = None) -> bool:
    return _step_position(state, actor, -1, reason=reason)


def step_position_toward_set(state: BattleState, actor: Combatant, reason: Optional[str] = None) -> bool:
    current = normalized_position_name(getattr(actor, "position", POSITION_DEFAULT))
    current_idx = POSITION_INDEX[current]
    set_idx = POSITION_INDEX["set"]
    if current_idx == set_idx:
        return False
    return _step_position(state, actor, +1 if current_idx < set_idx else -1, reason=reason)


def position_outgoing_multipliers(position_name: str) -> Tuple[float, float]:
    profile = position_profile(position_name)
    return profile["outgoing_damage_mult"], profile["outgoing_break_mult"]


def position_guard_modifiers(position_name: str) -> Tuple[float, float]:
    profile = position_profile(position_name)
    return profile["guard_hp_spill_mult"], profile["guard_break_mult"]


def position_dodge_bonus(position_name: str) -> int:
    profile = position_profile(position_name)
    return int(round(profile["dodge_bonus"]))


def position_parry_modifiers(position_name: str) -> Tuple[int, int]:
    profile = position_profile(position_name)
    return int(round(profile["parry_bonus"])), int(round(profile["parry_break_bonus"]))


def position_counterphrase_multipliers(position_name: str) -> Tuple[float, float]:
    profile = position_profile(position_name)
    return profile["counterphrase_damage_mult"], profile["counterphrase_break_mult"]


PATTERN_READ_SUPPORTED_TAGS = {"heavy", "channel", "burst_start"}


def build_defensive_read_profiles() -> Dict[str, DefensiveReadProfile]:
    raw = CONTENT.rules.get("defensive_reads", {})
    profiles = raw.get("profiles", {}) if isinstance(raw, dict) else {}
    built: Dict[str, DefensiveReadProfile] = {}
    if not isinstance(profiles, dict):
        return built
    for tag, profile_raw in profiles.items():
        if str(tag) not in PATTERN_READ_SUPPORTED_TAGS:
            continue
        if not isinstance(profile_raw, dict):
            continue
        primary_axis = str(profile_raw.get("primary", ""))
        secondary_axis = str(profile_raw.get("secondary", ""))
        preferred = tuple(str(item) for item in profile_raw.get("preferred_reactions", ()))
        if primary_axis and secondary_axis and preferred:
            built[str(tag)] = DefensiveReadProfile(
                tag=str(tag),
                primary_axis=primary_axis,
                secondary_axis=secondary_axis,
                preferred_reactions=preferred,
            )
    return built


DEFENSIVE_READ_PROFILES = build_defensive_read_profiles()
DEFENSIVE_READ_FICTION = {
    "heavy": ("weight", "commits to a heavy toll"),
    "channel": ("channel beat", "opens a channel beat"),
    "burst_start": ("burst", "starts a burst"),
}
GUARD_READ_BONUSES = {
    1: (0.90, 0.90),
    2: (0.80, 0.75),
    3: (0.70, 0.60),
}
DODGE_READ_BONUSES = {
    1: (6, 0.55, 0.45),
    2: (12, 0.45, 0.35),
    3: (18, 0.35, 0.25),
}
PARRY_READ_BONUSES = {
    1: (8, 4),
    2: (14, 8),
    3: (20, 12),
}
COUNTERPHRASE_READ_PAYLOADS = {
    0: (1.20, 1.25),
    1: (1.25, 1.30),
    2: (1.35, 1.45),
    3: (1.45, 1.60),
}
AXIS_LABELS = {"power": "Power", "precision": "Precision", "composure": "Composure"}
AXIS_INDEX = {"power": 0, "precision": 1, "composure": 2}


def select_defensive_profile_tag(incoming_tags: Sequence[str]) -> Optional[str]:
    for tag in incoming_tags:
        tag_text = str(tag)
        if tag_text in DEFENSIVE_READ_PROFILES:
            return tag_text
    return None


def resolve_defensive_read_profile(incoming_tags: Sequence[str]) -> Optional[DefensiveReadProfile]:
    tag = select_defensive_profile_tag(incoming_tags)
    if tag is None:
        return None
    return DEFENSIVE_READ_PROFILES.get(tag)


def defensive_axis_band(triplet: Tuple[int, int, int], axis: str) -> int:
    return band_index_for_value(triplet[AXIS_INDEX[axis]])


def resolve_defensive_read_tier(primary_band_idx: int, secondary_band_idx: int) -> int:
    keen = BAND_NAME_TO_INDEX.get("keen", 2)
    fierce = BAND_NAME_TO_INDEX.get("fierce", 3)
    exalted = BAND_NAME_TO_INDEX.get("exalted", 4)
    if primary_band_idx >= exalted and secondary_band_idx >= fierce:
        return 3
    if primary_band_idx >= fierce and secondary_band_idx >= keen:
        return 2
    if primary_band_idx >= keen:
        return 1
    return 0


def effective_defensive_read_tier(
    snapshot: Optional[PatternReadSnapshot],
    profile: Optional[DefensiveReadProfile],
    reaction: str,
) -> int:
    if snapshot is None or profile is None or snapshot.profile_tag != profile.tag:
        return 0
    tier = snapshot.raw_tier
    if reaction not in profile.preferred_reactions:
        tier -= 1
    return clamp_int(tier, 0, 3)


def parse_optional_defensive_triplet(raw: str) -> Optional[Tuple[int, int, int]]:
    if raw.strip() == "":
        return None
    parts = raw.replace("/", " ").replace(",", " ").split()
    if len(parts) != 3:
        raise ValueError("Pattern Read expects exactly three numbers.")
    values = [clamp_int(int(part), 0, 100) for part in parts]
    return (values[0], values[1], values[2])


def prompt_optional_defensive_triplet(
    profile: DefensiveReadProfile,
    attacker: Combatant,
    target: Combatant,
    reaction: str,
) -> Optional[Tuple[int, int, int]]:
    _, fiction = DEFENSIVE_READ_FICTION.get(profile.tag, (profile.tag, f"shows a {profile.tag} pattern"))
    print(f"\nIncoming pattern: {attacker.name} {fiction}.")
    primary = AXIS_LABELS.get(profile.primary_axis, profile.primary_axis.title())
    secondary = AXIS_LABELS.get(profile.secondary_axis, profile.secondary_axis.title())
    while True:
        raw = input(
            f"{profile.tag.replace('_', ' ').title()} Pattern Read available. "
            f"Favor {primary}; {secondary} helps. "
            "Enter power precision composure to sharpen the reaction, "
            "or press Enter to keep the base reaction > "
        )
        try:
            return parse_optional_defensive_triplet(raw)
        except ValueError:
            print("Enter three numbers, for example 42 74 65, or press Enter to skip Pattern Read.")


def auto_triplet_for_defensive_profile(
    profile: DefensiveReadProfile,
    reaction: str,
    rng: random.Random,
) -> Tuple[int, int, int]:
    values = {"power": 58, "precision": 58, "composure": 58}
    values[profile.primary_axis] = 84
    values[profile.secondary_axis] = 72
    if reaction not in profile.preferred_reactions:
        values[profile.primary_axis] = 72
        values[profile.secondary_axis] = 62
    # Keep auto reads deterministic for a given RNG stream without making every read identical.
    values[profile.primary_axis] = clamp_int(values[profile.primary_axis] + rng.randint(0, 4), 0, 100)
    values[profile.secondary_axis] = clamp_int(values[profile.secondary_axis] + rng.randint(0, 3), 0, 100)
    return (values["power"], values["precision"], values["composure"])


def make_defensive_read_snapshot(
    profile: DefensiveReadProfile,
    triplet: Optional[Tuple[int, int, int]],
) -> PatternReadSnapshot:
    if triplet is None:
        triplet = (0, 0, 0)
    primary_band = defensive_axis_band(triplet, profile.primary_axis)
    secondary_band = defensive_axis_band(triplet, profile.secondary_axis)
    raw_tier = resolve_defensive_read_tier(primary_band, secondary_band)
    return PatternReadSnapshot(
        profile_tag=profile.tag,
        primary_band_idx=primary_band,
        secondary_band_idx=secondary_band,
        raw_tier=raw_tier,
        triplet=triplet,
    )


def get_or_create_defensive_read_snapshot(
    state: BattleState,
    attacker: Combatant,
    target: Combatant,
    incoming_tags: Sequence[str],
    reaction: str,
) -> Optional[PatternReadSnapshot]:
    profile = resolve_defensive_read_profile(incoming_tags)
    if profile is None:
        return None
    cache_key = (state.round_number, attacker.entity_id, target.entity_id, profile.tag)
    cached = state.reaction_read_cache.get(cache_key)
    if cached is not None:
        if cached.raw_tier > 0:
            state.logger.log(
                state.round_number,
                f"{target.name} holds the same {profile.tag.replace('_', ' ')} Pattern Read.",
            )
        return cached
    if state.interactive:
        triplet = prompt_optional_defensive_triplet(profile, attacker, target, reaction)
    else:
        triplet = auto_triplet_for_defensive_profile(profile, reaction, state.rng)
    snapshot = make_defensive_read_snapshot(profile, triplet)
    state.reaction_read_cache[cache_key] = snapshot
    return snapshot


def counterphrase_payload_for_tier(tier: int) -> Dict[str, float]:
    damage_mult, break_mult = COUNTERPHRASE_READ_PAYLOADS.get(clamp_int(tier, 0, 3), COUNTERPHRASE_READ_PAYLOADS[0])
    return {"damage_mult": damage_mult, "break_mult": break_mult}


def pattern_read_reaction_line(
    target: Combatant,
    profile: DefensiveReadProfile,
    reaction: str,
    effective_tier: int,
) -> str:
    pattern_name, _ = DEFENSIVE_READ_FICTION.get(profile.tag, (profile.tag, "pattern"))
    if reaction == "guard":
        return f"{target.name} reads the {pattern_name} and hardens the guard."
    if reaction == "dodge":
        return f"{target.name} reads the {pattern_name} and slips clear."
    tier_text = "cleanly" if effective_tier >= 3 else "sharply"
    return f"{target.name} catches the Pattern Read {tier_text}. Counterphrase stores a stronger answer."


def crit_chance(actor: Combatant, skill: Skill, inputs: ResolvedInputs, target: Combatant, extra_bonus: int = 0) -> int:
    chance = 5
    if actor.team != "player":
        chance += inputs.band_indices["precision"] * 5
    if actor.posture == "focus":
        chance += 15
    if target.has_condition("reveal"):
        chance += 10
    if skill.effect_id == "mark_lunge":
        chance += 10 if target.has_condition("reveal") else 0
    if skill.effect_id == "glass_reprise" and (target.has_condition("reveal") or target.has_condition("staggered")):
        chance += 15
    if actor.entity_id == "ranger" and target.has_condition("reveal"):
        chance += 5
    chance += extra_bonus
    return clamp_int(chance, 0, 95)


def player_hit_chance(actor: Combatant, skill: Skill, inputs: ResolvedInputs, target: Combatant) -> int:
    precision = inputs.precision
    chance = 55 + int(precision * 0.40)
    if skill.primary_scale == "precision":
        chance += 8
    if skill.secondary_scale == "precision":
        chance += 4
    if target.has_condition("reveal"):
        chance += 5
    if target.has_condition("staggered"):
        chance += 10
    if actor.has_condition("snare"):
        chance -= 10
    if actor.has_condition("hex"):
        chance -= 5
    ranged_attack = skill.kind == "ranged_attack" or "ranged" in skill.tags or skill.effect_id == "linebreaker_shot"
    if target.has_condition("airborne"):
        chance += 5 if ranged_attack else -8
    return clamp_int(chance, 35, 95)


def player_power_damage_multiplier(state: BattleState, actor: Combatant, skill: Skill, inputs: ResolvedInputs) -> float:
    power = inputs.power
    low = clamp(0.65 + power * 0.0035, 0.65, 1.00)
    high = clamp(0.95 + power * 0.0070, 0.95, 1.70)
    mode = clamp(0.80 + power * 0.0055, low, high)
    return state.rng.triangular(low, high, mode)


def apply_damage_to_target(
    state: BattleState,
    source: Combatant,
    target: Combatant,
    damage: int,
    break_damage: int,
    skill: Skill,
    can_crit: bool = True,
    crit_bonus: int = 0,
    status_to_apply: Optional[Tuple[str, int, int]] = None,
    ignore_reaction: bool = False,
    attack_tags: Optional[Sequence[str]] = None,
) -> Dict[str, object]:
    """
    status_to_apply = (status_name, duration, base_chance)
    """
    result = {
        "damage_to_hp": 0,
        "damage_to_guard": 0,
        "break_damage": 0,
        "crit": False,
        "reaction": None,
        "killed": False,
        "status_applied": None,
        "hit_outcome": None,
    }

    if not source.alive() or not target.alive():
        return result

    resolved_tags = tuple(str(tag) for tag in (attack_tags if attack_tags is not None else skill.tags))
    source.metadata["last_outgoing_tags"] = list(resolved_tags)
    source.metadata["last_outgoing_round"] = state.round_number

    damage_mult, break_mult = posture_damage_break_multipliers(source.posture)
    position_damage_mult, position_break_mult = position_outgoing_multipliers(source.position)
    damage = ceil_int(damage * damage_mult * position_damage_mult)
    break_damage = ceil_int(break_damage * break_mult * position_break_mult)
    if target_recently_channeled(target):
        break_damage = ceil_int(break_damage * position_recent_channel_break_mult(source.position))

    affinity_mult = affinity_modifier(skill.affinity, target.affinity)
    damage = ceil_int(damage * affinity_mult)
    break_damage = ceil_int(break_damage * (1.10 if affinity_mult > 1.0 else 1.0))
    if target.has_condition("staggered"):
        damage = ceil_int(damage * 1.30)

    if target.has_condition("reveal"):
        damage = ceil_int(damage * 1.10)

    # Special cases.
    if skill.effect_id == "execution_drop" and target.has_condition("staggered"):
        damage = ceil_int(damage * 1.50)
    if skill.effect_id == "last_rite":
        if target.has_condition("staggered") or target.has_condition("hex"):
            damage = ceil_int(damage * 1.35)
        if source.hp <= source.max_hp // 2:
            damage = ceil_int(damage * 1.15)
    if skill.effect_id == "thorn_spiral" and source.hp <= source.max_hp // 2:
        damage = ceil_int(damage * 1.25)
    if skill.effect_id == "linebreaker_shot" and (target.guard > 0 or target.has_condition("airborne")):
        break_damage = ceil_int(break_damage * 1.35)
    if skill.effect_id == "anchor_cleave":
        pass

    if source.team == "player" and target.team == "enemy" and is_offensive_skill(skill):
        inputs = source.metadata.get("last_inputs")
        if not isinstance(inputs, ResolvedInputs):
            raw_axes = state.node_axis_scores
            inputs = make_resolved_inputs(
                int(raw_axes.get("power", 60)),
                int(raw_axes.get("precision", 60)),
                int(raw_axes.get("composure", 60)),
                skill,
            )
        hit_chance = player_hit_chance(source, skill, inputs, target)
        roll = state.rng.randint(1, 100)
        margin = roll - hit_chance
        high_risk = (
            skill.effect_id == "anchor_cleave"
            or skill.damage_tier in {"high", "extreme"}
            or any(tag in POSITION_PUNISH_TAGS for tag in resolved_tags)
        )
        if roll <= hit_chance:
            result["hit_outcome"] = "hit"
            state.logger.log(state.round_number, f"{source.name} lines up {target.name} [hit roll {roll}/{hit_chance}].")
        elif margin <= 10:
            result["hit_outcome"] = "graze"
            damage = ceil_int(damage * 0.50)
            break_damage = ceil_int(break_damage * 0.50)
            status_to_apply = None
            can_crit = False
            state.logger.log(state.round_number, f"{source.name} grazes {target.name} [hit roll {roll}/{hit_chance}].")
            if high_risk and margin >= 6:
                state.change_enemy_spotlight(1, f"{source.name} risky graze")
        else:
            result["hit_outcome"] = "miss"
            damage = 0
            break_damage = ceil_int(break_damage * 0.20)
            status_to_apply = None
            can_crit = False
            state.logger.log(state.round_number, f"{source.name} misses {target.name} [hit roll {roll}/{hit_chance}].")
            if margin >= 20:
                state.change_enemy_spotlight(1, f"{source.name} missed by {margin}")
            if high_risk:
                state.change_enemy_spotlight(1, f"{source.name} risky miss")

    if source.team == "enemy" and target.team == "player":
        damage = ceil_int(damage * ENEMY_DAMAGE_MULTIPLIER)
        break_damage = ceil_int(break_damage * ENEMY_DAMAGE_MULTIPLIER)
        if state.enemy_spotlight > 0 and (damage > 0 or break_damage > 0):
            state.change_enemy_spotlight(-1, "cashed for pressure")
            damage = ceil_int(damage * ENEMY_SPOTLIGHT_DAMAGE_MULTIPLIER)
            break_damage = ceil_int(break_damage * ENEMY_SPOTLIGHT_BREAK_MULTIPLIER)
            state.logger.log(state.round_number, "Enemy Spotlight is cashed for pressure.")

    if can_crit:
        chance = crit_chance(source, skill, make_resolved_inputs(50, 50, 50, skill), target, extra_bonus=crit_bonus)
        # Replace with true action inputs if present on source metadata.
        if source.metadata.get("last_inputs") is not None:
            last_inputs = source.metadata["last_inputs"]
            chance = crit_chance(source, skill, last_inputs, target, extra_bonus=crit_bonus)
        if state.rng.randint(1, 100) <= chance:
            result["crit"] = True
            damage = ceil_int(damage * 1.50)
            break_damage = ceil_int(break_damage * 1.10)

    # Reactions apply only when enemies attack player characters with direct attacks.
    reaction = None
    if target.team == "player" and source.team == "enemy" and damage > 0 and not ignore_reaction:
        reaction = choose_reaction(state, target, source, skill, incoming_tags=resolved_tags)
        result["reaction"] = reaction
        defensive_read = get_or_create_defensive_read_snapshot(
            state=state,
            attacker=source,
            target=target,
            incoming_tags=resolved_tags,
            reaction=reaction,
        )
        damage, break_damage, prevented, extra_logs = resolve_reaction(
            state=state,
            target=target,
            attacker=source,
            incoming_skill=skill,
            incoming_damage=damage,
            incoming_break=break_damage,
            reaction=reaction,
            incoming_tags=resolved_tags,
            defensive_read=defensive_read,
        )
        for line in extra_logs:
            state.logger.log(state.round_number, line)
        if prevented:
            if status_to_apply and reaction != "guard":
                # successful dodge/parry avoid status
                status_to_apply = None

    # Barrier first.
    if target.barrier > 0 and damage > 0:
        absorbed = min(target.barrier, damage)
        target.barrier -= absorbed
        damage -= absorbed
        result["damage_to_guard"] += absorbed
        if absorbed > 0:
            state.logger.log(state.round_number, f"{target.name}'s barrier absorbs {absorbed} damage.")

    # Guard then HP.
    hp_damage = 0
    guard_damage = 0
    bypass_guard = bool(target.metadata.pop("bypass_guard_this_hit", False))
    if damage > 0 and target.guard > 0 and not bypass_guard:
        guard_damage = min(target.guard, damage)
        target.guard -= guard_damage
        damage -= guard_damage
    if damage > 0:
        hp_damage = damage
        hp_damage = ceil_int(hp_damage * state.damage_taken_mult(target))
        target.hp = max(0, target.hp - hp_damage)

    result["damage_to_guard"] += guard_damage
    result["damage_to_hp"] += hp_damage

    # Break damage.
    had_staggered = target.has_condition("staggered")
    if break_damage > 0 and target.alive():
        result["break_damage"] = apply_break_damage(state, target, break_damage)
        if source.team == "enemy" and target.team == "player" and not had_staggered and target.has_condition("staggered"):
            state.change_enemy_spotlight(1, f"{source.name} staggered {target.name}")

    if hp_damage > 0 or guard_damage > 0:
        chunks = []
        if guard_damage > 0:
            chunks.append(f"{guard_damage} guard")
        if hp_damage > 0:
            chunks.append(f"{hp_damage} hp")
        crit_text = " CRIT!" if result["crit"] else ""
        state.logger.log(state.round_number, f"{source.name} hits {target.name} for {', '.join(chunks)}.{crit_text}")

    if result["crit"] and source.team == "player" and source.entity_id == "duelist" and not source.crit_spotlight_used_this_turn:
        state.change_spotlight(1, f"{source.name} passive crit")
        source.crit_spotlight_used_this_turn = True

    if target.hp <= 0:
        result["killed"] = True
        state.logger.log(state.round_number, f"{target.name} falls.")

    # Status application after damage, if target survived.
    if status_to_apply and target.alive():
        status_name, duration, chance = status_to_apply
        final_chance = chance
        if source.posture == "focus":
            final_chance += 20
        if is_affinity_advantage(skill.affinity, target.affinity):
            final_chance += 15
        if is_affinity_disadvantage(skill.affinity, target.affinity):
            final_chance -= 15
        final_chance = clamp_int(final_chance, 5, 100)
        if state.rng.randint(1, 100) <= final_chance:
            target.add_condition(status_name, duration)
            result["status_applied"] = status_name
            state.logger.log(state.round_number, f"{target.name} gains {status_name} ({duration}).")
            if source.team == "enemy" and target.team == "player" and status_name in {"reveal", "hex", "staggered"}:
                state.change_enemy_spotlight(1, f"{source.name} applied {status_name}")
            if source.entity_id == "cantor":
                grant_barrier_to_lowest_guard_ally(state, source, amount=8)

    # Ranger adapted passive.
    if source.entity_id == "ranger" and target.has_condition("reveal"):
        gained = source.restore_guard(8)
        if gained:
            state.logger.log(state.round_number, f"{source.name} gains {gained} guard from adapted ranger passive.")

    if source.next_attack_power_bonus and skill.kind not in {"support", "defense", "utility", "stance", "self_buff"}:
        source.next_attack_power_bonus = 0
        state.logger.log(state.round_number, f"{source.name}'s Blood Oath surge is consumed.")

    if is_affinity_advantage(skill.affinity, target.affinity) and source.team == "player":
        state.change_spotlight(1, f"{source.name} exploited affinity")
    return result


def apply_break_damage(state: BattleState, target: Combatant, amount: int) -> int:
    if amount <= 0 or not target.alive():
        return 0
    amount = ceil_int(amount)
    before = target.break_meter
    target.break_meter = max(0, target.break_meter - amount)
    dealt = before - target.break_meter
    if dealt > 0:
        state.logger.log(state.round_number, f"{target.name} loses {dealt} break.")
    if target.break_meter <= 0 and not target.has_condition("staggered"):
        target.add_condition("staggered", 1)
        set_position(state, target, "withdrawn", reason="staggered")
        state.logger.log(state.round_number, f"{target.name} is staggered!")
    return dealt


def grant_barrier_to_lowest_guard_ally(state: BattleState, source: Combatant, amount: int) -> None:
    allies = state.get_allies(source)
    if not allies:
        return
    target = min(allies, key=lambda unit: (unit.guard / max(unit.max_guard, 1), unit.hp))
    target.barrier += amount
    state.logger.log(state.round_number, f"{target.name} gains {amount} barrier from {source.name}'s passive.")


def equipped_relic_ids(actor: Combatant) -> List[str]:
    raw = actor.metadata.get("relic_ids", [])
    return [str(relic_id) for relic_id in raw if str(relic_id) in RELIC_DATA]


def enemy_action_tags(actor: Combatant, action_id: str) -> Tuple[str, ...]:
    blueprint_id = str(actor.metadata.get("blueprint_id", actor.entity_id))
    entry = ENEMY_BLUEPRINTS.get(blueprint_id)
    if entry is None:
        entry = BOSS_BLUEPRINTS.get(actor.entity_id, {})
    action_map = entry.get("action_tags", {}) if isinstance(entry, dict) else {}
    tags = action_map.get(action_id, [])
    if not isinstance(tags, list):
        return ()
    return tuple(str(tag) for tag in tags)


def is_offensive_skill(skill: Skill) -> bool:
    return skill.kind in OFFENSIVE_SKILL_KINDS


def recent_successful_reaction(state: BattleState, actor: Combatant) -> bool:
    if state.last_successful_reaction_actor_id != actor.entity_id:
        return False
    return (state.round_number - state.last_reaction_round) <= 1


def target_recently_channeled(target: Combatant) -> bool:
    if target.has_condition("delayed_overhead"):
        return True
    last_tags = [str(tag) for tag in target.metadata.get("last_outgoing_tags", [])]
    return "channel" in last_tags


def _rule_once_key(actor: Combatant, relic_id: str, trigger: str, index: int) -> str:
    return f"{actor.entity_id}:{relic_id}:{trigger}:{index}"


def _rule_matches(
    state: BattleState,
    actor: Combatant,
    rule: Dict[str, Any],
    trigger: str,
    skill: Optional[Skill],
    reaction: Optional[str],
    incoming_tags: Tuple[str, ...],
) -> bool:
    if str(rule.get("trigger", "")) != trigger:
        return False

    if reaction is not None and str(rule.get("reaction", reaction)) != reaction:
        return False

    required_tags = [str(tag) for tag in rule.get("incoming_tags_any", [])]
    if required_tags and not any(tag in incoming_tags for tag in required_tags):
        return False

    requires_charge = str(rule.get("requires_charge_id", "")).strip()
    if requires_charge:
        payload = state.stored_offense_bonus.get(actor.entity_id)
        if not payload or str(payload.get("charge_id", "")) != requires_charge:
            return False

    if skill is not None and bool(rule.get("offensive_only", False)) and not is_offensive_skill(skill):
        return False

    return True


def _effect_amount(effect: Dict[str, Any], actor: Combatant) -> float:
    base = float(effect.get("amount", 0))
    posture_bonus = effect.get("posture_bonus")
    if isinstance(posture_bonus, dict):
        base += float(posture_bonus.get(actor.posture, 0))
    return base


def _run_relic_effects(
    state: BattleState,
    actor: Combatant,
    relic_name: str,
    effects: Sequence[Dict[str, Any]],
    attacker: Optional[Combatant],
) -> Tuple[float, float]:
    damage_mult = 1.0
    break_mult = 1.0
    for effect in effects:
        effect_type = str(effect.get("type", ""))
        if effect_type == "apply_status_to_attacker":
            if attacker is None or not attacker.alive():
                continue
            status = str(effect.get("status", "")).strip()
            if not status:
                continue
            duration = int(effect.get("duration", effect.get("stacks", max(1, int(_effect_amount(effect, actor))))))
            attacker.add_condition(status, duration)
            state.logger.log(state.round_number, f"{relic_name} inflicts {status} on {attacker.name}.")
            continue

        if effect_type == "apply_status_to_self":
            status = str(effect.get("status", "")).strip()
            if not status:
                continue
            duration = int(effect.get("duration", effect.get("stacks", max(1, int(_effect_amount(effect, actor))))))
            actor.add_condition(status, duration)
            state.logger.log(state.round_number, f"{relic_name} grants {actor.name} {status}.")
            continue

        if effect_type == "gain_spotlight":
            amount = int(_effect_amount(effect, actor))
            if amount:
                state.change_spotlight(amount, relic_name)
            continue

        if effect_type == "apply_break_to_attacker":
            if attacker is None or not attacker.alive():
                continue
            amount = int(_effect_amount(effect, actor))
            if amount > 0:
                apply_break_damage(state, attacker, amount)
                state.logger.log(state.round_number, f"{relic_name} drives extra break into {attacker.name}.")
            continue

        if effect_type == "restore_guard_self":
            amount = int(_effect_amount(effect, actor))
            if amount > 0:
                gained = actor.restore_guard(amount)
                if gained > 0:
                    state.logger.log(state.round_number, f"{relic_name} restores {gained} guard to {actor.name}.")
            continue

        if effect_type == "gain_barrier_self":
            amount = int(_effect_amount(effect, actor))
            if amount > 0:
                actor.barrier += amount
                state.logger.log(state.round_number, f"{relic_name} grants {actor.name} {amount} barrier.")
            continue

        if effect_type == "cleanse_minor_self":
            cleanse_one_debuff(state, actor, source_text=relic_name)
            continue

        if effect_type == "set_next_self_risk_reduction":
            amount = max(0.0, min(0.90, _effect_amount(effect, actor)))
            if amount > 0:
                state.next_self_risk_reduction[actor.entity_id] = max(
                    amount,
                    state.next_self_risk_reduction.get(actor.entity_id, 0.0),
                )
                state.logger.log(state.round_number, f"{relic_name} steadies {actor.name}'s next offensive risk.")
            continue

        if effect_type == "store_charge_bonus":
            charge_id = str(effect.get("charge_id", ""))
            if not charge_id:
                continue
            damage_bonus = float(effect.get("damage_bonus_mult", 1.30))
            break_bonus = float(effect.get("break_bonus_mult", 1.30))
            label = str(effect.get("label", relic_name))
            state.stored_offense_bonus[actor.entity_id] = {
                "charge_id": charge_id,
                "damage_bonus_mult": damage_bonus,
                "break_bonus_mult": break_bonus,
                "label": label,
            }
            state.logger.log(state.round_number, f"{label} stores a charge.")
            continue

        if effect_type == "consume_stored_charge_bonus":
            payload = state.stored_offense_bonus.get(actor.entity_id)
            if not payload:
                continue
            needed = str(effect.get("charge_id", payload.get("charge_id", "")))
            if needed and str(payload.get("charge_id", "")) != needed:
                continue
            damage_mult *= float(payload.get("damage_bonus_mult", 1.0))
            break_mult *= float(payload.get("break_bonus_mult", 1.0))
            label = str(payload.get("label", relic_name))
            state.logger.log(state.round_number, f"{label} is consumed by the next offense.")
            del state.stored_offense_bonus[actor.entity_id]
            continue

    return damage_mult, break_mult


def process_relic_trigger(
    state: BattleState,
    actor: Combatant,
    trigger: str,
    attacker: Optional[Combatant] = None,
    skill: Optional[Skill] = None,
    reaction: Optional[str] = None,
    incoming_tags: Tuple[str, ...] = (),
) -> Tuple[float, float]:
    total_damage_mult = 1.0
    total_break_mult = 1.0
    for relic_id in equipped_relic_ids(actor):
        relic_raw = RELIC_DATA.get(relic_id, {})
        relic_name = str(relic_raw.get("display_name", relic_id))
        rules = relic_raw.get("trigger_rules", [])
        if not isinstance(rules, list):
            continue
        for idx, raw_rule in enumerate(rules):
            if not isinstance(raw_rule, dict):
                continue
            if not _rule_matches(
                state=state,
                actor=actor,
                rule=raw_rule,
                trigger=trigger,
                skill=skill,
                reaction=reaction,
                incoming_tags=incoming_tags,
            ):
                continue
            once_per_battle = bool(raw_rule.get("once_per_battle", False))
            key = _rule_once_key(actor, relic_id, trigger, idx)
            if once_per_battle and key in state.once_per_battle_flags:
                continue
            effects = raw_rule.get("effects", [])
            if not isinstance(effects, list):
                effects = []
            damage_mult, break_mult = _run_relic_effects(
                state=state,
                actor=actor,
                relic_name=relic_name,
                effects=[item for item in effects if isinstance(item, dict)],
                attacker=attacker,
            )
            total_damage_mult *= damage_mult
            total_break_mult *= break_mult
            if once_per_battle:
                state.once_per_battle_flags.add(key)
    return total_damage_mult, total_break_mult


def handle_reaction_success_triggers(
    state: BattleState,
    reactor: Combatant,
    attacker: Combatant,
    reaction: str,
    incoming_tags: Tuple[str, ...],
) -> None:
    state.last_successful_reaction = reaction
    state.last_successful_reaction_actor_id = reactor.entity_id
    state.last_incoming_skill_tags = incoming_tags
    state.last_reaction_round = state.round_number
    process_relic_trigger(
        state=state,
        actor=reactor,
        trigger="reaction_success",
        attacker=attacker,
        reaction=reaction,
        incoming_tags=incoming_tags,
    )


def current_self_risk_reduction(state: BattleState, actor: Combatant, skill: Skill) -> float:
    if not is_offensive_skill(skill):
        return 0.0
    return max(0.0, min(0.90, state.next_self_risk_reduction.get(actor.entity_id, 0.0)))


def consume_counterphrase_bonus(state: BattleState, actor: Combatant, skill: Skill) -> Tuple[float, float]:
    if not is_offensive_skill(skill):
        return (1.0, 1.0)
    if actor.entity_id not in state.counterphrase_charge_actors:
        return (1.0, 1.0)
    state.counterphrase_charge_actors.discard(actor.entity_id)
    payload = state.counterphrase_payloads.pop(actor.entity_id, None)
    if payload is None:
        payload = counterphrase_payload_for_tier(0)
    state.logger.log(state.round_number, f"{skill.display_name} consumes Counterphrase.")
    pos_damage_mult, pos_break_mult = position_counterphrase_multipliers(actor.position)
    if pos_damage_mult != 1.0 or pos_break_mult != 1.0:
        state.logger.log(state.round_number, f"{skill.display_name} cashes Counterphrase from {actor.position} position.")
    return (
        float(payload.get("damage_mult", 1.20)) * pos_damage_mult,
        float(payload.get("break_mult", 1.25)) * pos_break_mult,
    )


def expire_counterphrase_if_unused(state: BattleState, actor: Combatant, skill: Skill) -> None:
    if is_offensive_skill(skill):
        return
    if actor.entity_id in state.counterphrase_charge_actors:
        state.counterphrase_charge_actors.discard(actor.entity_id)
        state.counterphrase_payloads.pop(actor.entity_id, None)
        state.logger.log(state.round_number, f"Counterphrase fades before {actor.name} can cash it out.")


def finalize_offensive_resolution(state: BattleState, actor: Combatant, skill: Skill) -> None:
    if not is_offensive_skill(skill):
        return
    process_relic_trigger(state=state, actor=actor, trigger="after_offense", skill=skill)
    if actor.entity_id in state.next_self_risk_reduction:
        del state.next_self_risk_reduction[actor.entity_id]
        state.logger.log(state.round_number, f"{actor.name}'s slip window closes.")


def finalize_action_resolution(state: BattleState, actor: Combatant, skill: Skill) -> None:
    if is_offensive_skill(skill):
        finalize_offensive_resolution(state, actor, skill)
        return
    expire_counterphrase_if_unused(state, actor, skill)


# ---------------------------------------------------------------------------
# Reaction system
# ---------------------------------------------------------------------------


def choose_reaction(
    state: BattleState,
    target: Combatant,
    attacker: Combatant,
    skill: Skill,
    incoming_tags: Sequence[str] = (),
) -> str:
    resolved_tags = tuple(str(tag) for tag in incoming_tags)
    has_pressure_tags = any(tag in POSITION_PUNISH_TAGS for tag in resolved_tags)
    if not state.interactive:
        if target.position == "pressing":
            if target.guard <= 8:
                return "dodge"
            if has_pressure_tags:
                return "parry"
        if target.position == "withdrawn":
            if target.guard <= 8:
                return "dodge"
            return "guard"
        # Auto logic: bastion likes parry, low guard likes dodge, otherwise guard.
        if target.posture == "bastion" or target.has_condition("feint_circuit"):
            return "parry"
        if target.guard <= 8:
            return "dodge"
        return "guard"

    while True:
        print(f"\nReaction for {target.name}: [g]uard, [d]odge, [p]arry")
        tag_text = ", ".join(resolved_tags) if resolved_tags else "-"
        print(
            f"Incoming: {attacker.name} uses {skill.display_name} [{tag_text}]. "
            f"{target.name} posture={target.posture} pos={target.position}."
        )
        choice = input("> ").strip().lower()
        if choice in {"g", "guard", ""}:
            return "guard"
        if choice in {"d", "dodge"}:
            return "dodge"
        if choice in {"p", "parry"}:
            return "parry"
        print("Please type g, d, or p.")


def get_current_axis_inputs_for_reaction(state: BattleState, target: Combatant, incoming_skill: Skill) -> ResolvedInputs:
    raw = state.node_axis_scores
    return make_resolved_inputs(
        int(raw.get("power", 60)),
        int(raw.get("precision", 60)),
        int(raw.get("composure", 60)),
        incoming_skill,
    )


def spend_guard_for_reaction(target: Combatant, amount: int) -> int:
    spent = min(max(0, amount), max(0, target.guard))
    target.guard = max(0, target.guard - spent)
    return spent


def spend_break_for_reaction(target: Combatant, amount: int) -> int:
    spent = min(max(0, amount), max(0, target.break_meter))
    target.break_meter = max(0, target.break_meter - spent)
    return spent


def resolve_reaction(
    state: BattleState,
    target: Combatant,
    attacker: Combatant,
    incoming_skill: Skill,
    incoming_damage: int,
    incoming_break: int,
    reaction: str,
    incoming_tags: Sequence[str] = (),
    defensive_read: Optional[PatternReadSnapshot] = None,
) -> Tuple[int, int, bool, List[str]]:
    logs: List[str] = []
    prevented = False
    inputs = get_current_axis_inputs_for_reaction(state, target, incoming_skill)
    incoming_tags_tuple = tuple(str(tag) for tag in incoming_tags)
    tagged_pressure = any(tag in POSITION_PUNISH_TAGS for tag in incoming_tags_tuple)
    defensive_profile = resolve_defensive_read_profile(incoming_tags_tuple)
    read_tier = effective_defensive_read_tier(defensive_read, defensive_profile, reaction)

    if reaction == "guard":
        if inputs.power < GUARD_POWER_REQUIREMENT:
            target.metadata["bypass_guard_this_hit"] = True
            state.change_enemy_spotlight(1, f"{target.name} failed guard gate")
            logs.append(f"Guard gate failed: Power {inputs.power} < {GUARD_POWER_REQUIREMENT}.")
            return incoming_damage, incoming_break, prevented, logs
        logs.append(f"Guard gate success: Power {inputs.power} >= {GUARD_POWER_REQUIREMENT}.")
        hp_spill_mult, guard_break_mult = position_guard_modifiers(target.position)
        if read_tier > 0:
            read_hp_mult, read_break_mult = GUARD_READ_BONUSES[read_tier]
            hp_spill_mult *= read_hp_mult
            guard_break_mult *= read_break_mult
        if target.has_condition("brace_guard"):
            hp_spill_mult *= 0.80
            target.remove_condition("brace_guard")
            logs.append(f"{target.name}'s Brace softens the impact.")
        if target.posture == "bastion":
            hp_spill_mult *= 0.90
        # Guard sends damage into guard first, but any spill to HP is reduced by spill multiplier.
        overflow = 0
        if target.guard > 0:
            overflow = max(0, incoming_damage - target.guard)
            adjusted_overflow = ceil_int(overflow * hp_spill_mult)
            effective_damage = min(incoming_damage, target.guard) + adjusted_overflow
        else:
            effective_damage = ceil_int(incoming_damage * hp_spill_mult)
        effective_break = ceil_int(incoming_break * guard_break_mult)
        if target.position == "withdrawn" and overflow > 0:
            logs.append(f"Withdrawn footing trims the spill on {target.name}'s guard.")
        if read_tier > 0 and defensive_profile is not None:
            logs.append(pattern_read_reaction_line(target, defensive_profile, "guard", read_tier))
        handle_reaction_success_triggers(
            state=state,
            reactor=target,
            attacker=attacker,
            reaction="guard",
            incoming_tags=incoming_tags_tuple,
        )
        step_position_toward_withdrawn(state, target)
        if tagged_pressure:
            step_position_toward_withdrawn(state, attacker, reason="pressure answered")
        return effective_damage, effective_break, prevented, logs

    if reaction == "dodge":
        before_break = target.break_meter
        spent_break = spend_break_for_reaction(target, DODGE_BREAK_COST)
        logs.append(f"{target.name} spends {spent_break}/{DODGE_BREAK_COST} Break to dodge.")
        if inputs.precision < DODGE_PRECISION_REQUIREMENT:
            target.metadata["bypass_guard_this_hit"] = True
            state.change_enemy_spotlight(1, f"{target.name} failed dodge gate")
            logs.append(f"Dodge gate failed: Precision {inputs.precision} < {DODGE_PRECISION_REQUIREMENT}.")
            return (
                ceil_int(incoming_damage * 1.20),
                incoming_break + DODGE_EXTRA_BREAK_ON_FAIL,
                prevented,
                logs,
            )
        chance = 45 + int((inputs.precision - DODGE_PRECISION_REQUIREMENT) * 0.7)
        if target.posture == "focus":
            chance += 8
        if target.posture == "flow":
            chance += 5
        if target.has_condition("snare"):
            chance -= 15
        if target.has_condition("soak"):
            chance -= 10
        chance += position_dodge_bonus(target.position)
        if before_break <= 0 or spent_break < DODGE_BREAK_COST:
            chance -= 20
            logs.append(f"{target.name}'s empty Break meter makes the dodge shaky.")
        failed_damage_mult = 0.75
        failed_break_mult = 0.75
        if read_tier > 0:
            read_chance_bonus, _, _ = DODGE_READ_BONUSES[read_tier]
            chance += read_chance_bonus
        chance = clamp_int(chance, 10, 90)
        roll = state.rng.randint(1, 100)
        if roll <= chance:
            prevented = True
            logs.append(f"{target.name} dodges cleanly [dodge roll {roll}/{chance}].")
            if read_tier > 0 and defensive_profile is not None:
                logs.append(pattern_read_reaction_line(target, defensive_profile, "dodge", read_tier))
            if target.position == "withdrawn":
                logs.append(f"{target.name} slips wide from withdrawn footing.")
            handle_reaction_success_triggers(
                state=state,
                reactor=target,
                attacker=attacker,
                reaction="dodge",
                incoming_tags=incoming_tags_tuple,
            )
            step_position_toward_set(state, target)
            if tagged_pressure:
                step_position_toward_withdrawn(state, attacker, reason="pressure answered")
            return 0, 0, prevented, logs
        reduced = ceil_int(incoming_damage * failed_damage_mult)
        state.change_enemy_spotlight(1, f"{target.name} mistimed dodge")
        logs.append(f"{target.name} mistimes the dodge [dodge roll {roll}/{chance}].")
        return reduced, ceil_int(incoming_break * failed_break_mult), prevented, logs

    # parry
    spent_guard = spend_guard_for_reaction(target, PARRY_GUARD_COST)
    spent_break = spend_break_for_reaction(target, PARRY_BREAK_COST)
    logs.append(f"{target.name} spends {spent_guard}/{PARRY_GUARD_COST} Guard and {spent_break}/{PARRY_BREAK_COST} Break to parry.")
    if spent_guard < PARRY_GUARD_COST or spent_break < PARRY_BREAK_COST:
        target.metadata["bypass_guard_this_hit"] = True
        state.change_spotlight(-1, f"{target.name} underfunded parry")
        state.change_enemy_spotlight(1, f"{target.name} underfunded parry")
        logs.append(
            f"Parry resource gate failed: Guard {spent_guard}/{PARRY_GUARD_COST}, "
            f"Break {spent_break}/{PARRY_BREAK_COST}."
        )
        return (
            ceil_int(incoming_damage * 1.35),
            incoming_break + PARRY_EXTRA_BREAK_ON_FAIL,
            prevented,
            logs,
        )
    failed_axes: List[str] = []
    if inputs.power < PARRY_POWER_REQUIREMENT:
        failed_axes.append(f"Power {inputs.power} < {PARRY_POWER_REQUIREMENT}")
    if inputs.precision < PARRY_PRECISION_REQUIREMENT:
        failed_axes.append(f"Precision {inputs.precision} < {PARRY_PRECISION_REQUIREMENT}")
    if inputs.composure < PARRY_COMPOSURE_REQUIREMENT:
        failed_axes.append(f"Composure {inputs.composure} < {PARRY_COMPOSURE_REQUIREMENT}")
    if failed_axes:
        target.metadata["bypass_guard_this_hit"] = True
        state.change_spotlight(-1, f"{target.name} failed parry gate")
        state.change_enemy_spotlight(1, f"{target.name} failed parry gate")
        logs.append("Parry gate failed: " + "; ".join(failed_axes) + ".")
        return (
            ceil_int(incoming_damage * 1.35),
            incoming_break + PARRY_EXTRA_BREAK_ON_FAIL,
            prevented,
            logs,
        )

    chance = 35
    chance += int((inputs.power - PARRY_POWER_REQUIREMENT) * 0.25)
    chance += int((inputs.precision - PARRY_PRECISION_REQUIREMENT) * 0.35)
    chance += int((inputs.composure - PARRY_COMPOSURE_REQUIREMENT) * 0.25)
    parry_bonus, parry_break_bonus = position_parry_modifiers(target.position)
    read_parry_break_bonus = 0
    if read_tier > 0:
        read_chance_bonus, read_parry_break_bonus = PARRY_READ_BONUSES[read_tier]
        chance += read_chance_bonus
    if target.posture == "bastion":
        chance += 8
    if target.posture == "flow":
        chance += 4
    if target.has_condition("feint_circuit"):
        chance += 15
    chance += parry_bonus
    chance = clamp_int(chance, 10, 92)
    roll = state.rng.randint(1, 100)
    if roll <= chance:
        prevented = True
        logs.append(f"Parry! {target.name} rings the bell-note false [parry roll {roll}/{chance}].")
        if read_tier > 0 and defensive_profile is not None:
            logs.append(pattern_read_reaction_line(target, defensive_profile, "parry", read_tier))
        parry_break = max(0, 18 + (6 if target.posture == "bastion" else 0) + parry_break_bonus + read_parry_break_bonus)
        apply_break_damage(state, attacker, parry_break)
        attacker.add_condition("reveal", 1)
        logs.append(f"{attacker.name} is revealed by the parry opening.")
        if target.entity_id in state.counterphrase_charge_actors:
            logs.append("Counterphrase is refreshed.")
        else:
            logs.append("Counterphrase stored.")
        state.counterphrase_charge_actors.add(target.entity_id)
        state.counterphrase_payloads[target.entity_id] = counterphrase_payload_for_tier(read_tier)
        state.change_spotlight(1, f"{target.name} parry")
        handle_reaction_success_triggers(
            state=state,
            reactor=target,
            attacker=attacker,
            reaction="parry",
            incoming_tags=incoming_tags_tuple,
        )
        step_position_toward_pressing(state, target)
        step_position_toward_withdrawn(state, attacker)
        if tagged_pressure:
            step_position_toward_withdrawn(state, attacker, reason="pressure answered")
        if target.has_condition("feint_circuit"):
            target.remove_condition("feint_circuit")
            counter_damage = 12
            logs.append(f"{target.name} unleashes a Feint Circuit counter!")
            # Direct counter is light, no extra reaction.
            apply_damage_to_target(
                state=state,
                source=target,
                target=attacker,
                damage=counter_damage,
                break_damage=8,
                skill=SKILLS["standard_strike"],
                can_crit=False,
                ignore_reaction=True,
            )
            state.change_spotlight(1, f"{target.name} Feint Circuit")
        return 0, 0, prevented, logs

    # Failed parry.
    state.change_enemy_spotlight(1, f"{target.name} missed parry")
    logs.append(f"{target.name} misses the parry [parry roll {roll}/{chance}] and is punished.")
    return ceil_int(incoming_damage * 1.15), incoming_break + 6, prevented, logs


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------


def prompt_int(prompt_text: str, default: Optional[int] = None, low: int = 0, high: int = 100) -> int:
    while True:
        suffix = f" [{default}]" if default is not None else ""
        raw = input(f"{prompt_text}{suffix}: ").strip()
        if raw == "" and default is not None:
            return default
        try:
            value = int(raw)
        except ValueError:
            print("Please enter a whole number.")
            continue
        if low <= value <= high:
            return value
        print(f"Please enter a value between {low} and {high}.")


def prompt_triplet(defaults: Tuple[int, int, int], skill: Skill) -> ResolvedInputs:
    while True:
        raw = input(
            f"Enter power precision composure [default {defaults[0]} {defaults[1]} {defaults[2]}] > "
        ).strip()
        if raw == "":
            power, precision, composure = defaults
        else:
            parts = raw.replace("/", " ").replace(",", " ").split()
            if len(parts) != 3:
                print("Enter exactly 3 integers, for example: 72 61 84")
                continue
            try:
                power, precision, composure = [clamp_int(int(part), 0, 100) for part in parts]
            except ValueError:
                print("All 3 entries must be integers.")
                continue

        resolved = make_resolved_inputs(power, precision, composure, skill)
        preview = (
            f"Preview -> Power {describe_band(power)}, "
            f"Precision {describe_band(precision)}, "
            f"Composure {describe_band(composure)} | "
            f"Posture: {resolved.posture} ({resolved.posture_reason})"
        )
        print(preview)
        confirm = input("Press Enter to confirm or type r to re-enter > ").strip().lower()
        if confirm in {"", "y", "yes"}:
            return resolved


def auto_triplet_for_skill(user: Combatant, skill: Skill, rng: random.Random) -> ResolvedInputs:
    preferred = {
        "vanguard": ("power", "composure"),
        "duelist": ("precision", "composure"),
        "cantor": ("precision", "composure"),
        "ranger": ("precision", "power"),
        "penitent": ("power", "precision"),
    }.get(user.entity_id, (skill.primary_scale, skill.secondary_scale))
    values = {"power": 50, "precision": 50, "composure": 50}
    values[preferred[0]] = rng.randint(68, 92)
    values[preferred[1]] = rng.randint(58, 82)
    remaining = [dim for dim in ("power", "precision", "composure") if dim not in preferred][0]
    values[remaining] = rng.randint(38, 64)

    # Some skills prefer balanced play.
    if skill.effect_id in {"brace", "feint_circuit", "undertow_litany"}:
        values = {
            "power": rng.randint(45, 60),
            "precision": rng.randint(45, 60),
            "composure": rng.randint(60, 82),
        }

    return make_resolved_inputs(values["power"], values["precision"], values["composure"], skill)


# ---------------------------------------------------------------------------
# Action resolution
# ---------------------------------------------------------------------------


def apply_posture_and_post_action_effects(state: BattleState, actor: Combatant, inputs: ResolvedInputs) -> None:
    actor.posture = inputs.posture
    state.logger.log(
        state.round_number,
        f"{actor.name} enters {actor.posture} posture ({inputs.posture_reason}).",
    )
    if actor.posture in {"ravage", "focus"}:
        step_position_toward_pressing(state, actor)
    elif actor.posture == "bastion":
        step_position_toward_withdrawn(state, actor)
    elif actor.posture == "flow":
        step_position_toward_set(state, actor)
    if actor.posture == "flow":
        state.change_spotlight(1, f"{actor.name} entered Flow")
        cleanse_one_debuff(state, actor)
    if actor.entity_id == "vanguard" and actor.posture in {"bastion", "ravage"}:
        restored = actor.restore_guard(max(1, actor.max_guard // 10))
        if restored:
            state.logger.log(state.round_number, f"{actor.name} restores {restored} guard from passive.")


def cleanse_one_debuff(state: BattleState, actor: Combatant, source_text: str = "Flow") -> None:
    for status in MINOR_NEGATIVE_STATUSES:
        if actor.has_condition(status):
            actor.remove_condition(status)
            state.logger.log(state.round_number, f"{actor.name} cleanses {status} via {source_text}.")
            return


def choose_player_skill(state: BattleState, actor: Combatant) -> Skill:
    available: List[Skill] = []
    for skill_id in actor.skills:
        skill = SKILLS[skill_id]
        if state.spotlight < skill.spotlight_cost:
            continue
        available.append(skill)

    while True:
        print(f"\n{actor.name}'s turn. Choose a skill:")
        for idx, skill in enumerate(available, start=1):
            print(
                f"  {idx}. {skill.display_name:<18} "
                f"[{skill.kind}] cost={skill.spotlight_cost} "
                f"scale={skill.primary_scale}/{skill.secondary_scale} "
                f"target={skill.target}"
            )
        raw = input("> ").strip()
        if raw == "" and available:
            return available[0]
        try:
            idx = int(raw)
        except ValueError:
            print("Choose a number.")
            continue
        if 1 <= idx <= len(available):
            return available[idx - 1]
        print("That number is out of range.")


def auto_choose_player_skill(state: BattleState, actor: Combatant) -> Skill:
    available = [SKILLS[skill_id] for skill_id in actor.skills if state.spotlight >= SKILLS[skill_id].spotlight_cost]
    enemies = state.living_enemies()

    # Simple priorities.
    staggered = [enemy for enemy in enemies if enemy.has_condition("staggered")]
    if actor.entity_id == "vanguard":
        if state.spotlight >= 2 and staggered:
            return SKILLS["execution_drop"]
        return SKILLS["anchor_cleave"]
    if actor.entity_id == "duelist":
        target = max(enemies, key=lambda unit: unit.hp) if enemies else None
        if state.spotlight >= 2 and target and (target.has_condition("reveal") or target.has_condition("staggered")):
            return SKILLS["glass_reprise"]
        return SKILLS["mark_lunge"]
    if actor.entity_id == "cantor":
        if state.spotlight >= 2 and any(enemy.has_condition("reveal") or enemy.has_condition("staggered") for enemy in enemies):
            return SKILLS["final_verse"]
        if any(enemy.has_condition("reveal") or target_recently_channeled(enemy) for enemy in enemies):
            return SKILLS["tuning_fork_cut"]
        if state.spotlight >= 1 and any(enemy.has_condition("hex") or enemy.has_condition("reveal") or enemy.has_condition("snare") for enemy in enemies):
            return SKILLS["hex_burst"]
        return SKILLS["salt_psalm"]
    if actor.entity_id == "ranger":
        if any(enemy.has_condition("airborne") or enemy.guard > 0 for enemy in enemies):
            return SKILLS["linebreaker_shot"]
        return SKILLS["pinning_round"]
    if actor.entity_id == "penitent":
        if actor.hp > actor.max_hp * 0.65 and not actor.next_attack_power_bonus:
            return SKILLS["blood_oath"]
        if state.spotlight >= 2 and any(enemy.has_condition("hex") or enemy.has_condition("staggered") for enemy in enemies):
            return SKILLS["last_rite"]
        return SKILLS["thorn_spiral"]

    return available[0] if available else SKILLS["standard_strike"]


def choose_target(state: BattleState, actor: Combatant, skill: Skill) -> List[Combatant]:
    if skill.target == "self":
        return [actor]
    if skill.target == "all_allies":
        return state.get_allies(actor)
    if skill.target == "all_enemies":
        return state.get_opponents(actor)
    candidates = state.get_opponents(actor)
    if not state.interactive:
        return [auto_choose_target(state, actor, skill, candidates)]
    while True:
        print("Choose a target:")
        for idx, target in enumerate(candidates, start=1):
            print(f"  {idx}. {target.summary_line()}")
        raw = input("> ").strip()
        if raw == "" and candidates:
            return [candidates[0]]
        try:
            idx = int(raw)
        except ValueError:
            print("Choose a number.")
            continue
        if 1 <= idx <= len(candidates):
            return [candidates[idx - 1]]
        print("That number is out of range.")


def auto_choose_target(state: BattleState, actor: Combatant, skill: Skill, candidates: Sequence[Combatant]) -> Combatant:
    # Finish staggered or low HP targets first.
    staggered = [unit for unit in candidates if unit.has_condition("staggered")]
    if staggered:
        return min(staggered, key=lambda unit: unit.hp)
    if skill.affinity != "neutral":
        advantaged = [unit for unit in candidates if is_affinity_advantage(skill.affinity, unit.affinity)]
        if advantaged:
            return min(advantaged, key=lambda unit: unit.hp)
    if actor.entity_id == "duelist":
        revealed = [unit for unit in candidates if unit.has_condition("reveal")]
        if revealed:
            return min(revealed, key=lambda unit: unit.hp)
    return min(candidates, key=lambda unit: (unit.hp, unit.guard))


def perform_player_action(state: BattleState, actor: Combatant) -> bool:
    if state.interactive:
        state.render_state()
        skill = choose_player_skill(state, actor)
        targets = choose_target(state, actor, skill)
    else:
        skill = auto_choose_player_skill(state, actor)
        targets = choose_target(state, actor, skill)

    raw = state.node_axis_scores
    resolved_inputs = make_resolved_inputs(
        int(raw.get("power", 60)),
        int(raw.get("precision", 60)),
        int(raw.get("composure", 60)),
        skill,
    )
    state.last_player_inputs = (resolved_inputs.power, resolved_inputs.precision, resolved_inputs.composure)

    if state.spotlight < skill.spotlight_cost:
        state.logger.log(state.round_number, f"{actor.name} lacks the Spotlight for {skill.display_name}.")
        return False

    state.change_spotlight(-skill.spotlight_cost, f"{actor.name} used {skill.display_name}")
    actor.metadata["last_inputs"] = resolved_inputs
    apply_posture_and_post_action_effects(state, actor, resolved_inputs)
    context = ActionContext(user=actor, skill=skill, targets=targets, inputs=resolved_inputs, spotlight_spent=skill.spotlight_cost)
    resolve_action(state, context)
    actor.times_acted += 1
    actor.last_skill_used = skill.skill_id
    return True


def resolve_action(state: BattleState, context: ActionContext) -> None:
    actor = context.user
    skill = context.skill
    targets = context.targets
    inputs = context.inputs
    offensive_skill = is_offensive_skill(skill)
    scale = 1.0 if actor.team == "player" and offensive_skill else compute_scale_multiplier(actor, skill, inputs)
    had_counterphrase_charge = actor.entity_id in state.counterphrase_charge_actors
    before_damage_mult = 1.0
    before_break_mult = 1.0
    counterphrase_damage_mult = 1.0
    counterphrase_break_mult = 1.0
    power_damage_mult = 1.0
    power_break_mult = 1.0
    if offensive_skill:
        before_damage_mult, before_break_mult = process_relic_trigger(
            state=state,
            actor=actor,
            trigger="before_offense",
            skill=skill,
        )
        counterphrase_damage_mult, counterphrase_break_mult = consume_counterphrase_bonus(state, actor, skill)
        if actor.team == "player":
            power_damage_mult = player_power_damage_multiplier(state, actor, skill, inputs)
            power_break_mult = 1.0 + (power_damage_mult - 1.0) * 0.50
            state.logger.log(state.round_number, f"Power output x{power_damage_mult:.2f} from Power {inputs.power}.")
    self_risk_reduction = current_self_risk_reduction(state, actor, skill)

    state.logger.log(
        state.round_number,
        f"{actor.name} uses {skill.display_name} "
        f"[P:{inputs.power}/{inputs.band_names['power']}, "
        f"R:{inputs.precision}/{inputs.band_names['precision']}, "
        f"C:{inputs.composure}/{inputs.band_names['composure']}]",
    )

    if skill.effect_id == "brace":
        gained = actor.restore_guard(ceil_int(actor.max_guard * 0.35))
        actor.add_condition("brace_guard", 1)
        state.logger.log(state.round_number, f"{actor.name} braces, restoring {gained} guard.")
        finalize_action_resolution(state, actor, skill)
        return

    if skill.effect_id == "ward_bell":
        for ally in state.get_allies(actor):
            gained = ally.restore_guard(ceil_int(ally.max_guard * 0.20))
            if gained:
                state.logger.log(state.round_number, f"{ally.name} restores {gained} guard from Ward Bell.")
        actor.add_condition("taunt", 1)
        state.logger.log(state.round_number, f"{actor.name} rings Ward Bell and draws enemy focus.")
        finalize_action_resolution(state, actor, skill)
        return

    if skill.effect_id == "feint_circuit":
        actor.add_condition("feint_circuit", 1)
        state.logger.log(state.round_number, f"{actor.name} enters Feint Circuit stance.")
        finalize_action_resolution(state, actor, skill)
        return

    if skill.effect_id == "undertow_litany":
        for ally in state.get_allies(actor):
            cleanse_one_debuff(state, ally, source_text="Undertow Litany")
            ally.barrier += 10
            state.logger.log(state.round_number, f"{ally.name} gains 10 barrier from Undertow Litany.")
        finalize_action_resolution(state, actor, skill)
        return

    if skill.effect_id == "blood_oath":
        hp_cost = max(8, ceil_int(actor.max_hp * 0.10))
        actor.hp = max(1, actor.hp - hp_cost)
        actor.next_attack_power_bonus = 1
        actor.add_condition("exposed_self", 1)
        state.change_spotlight(1, f"{actor.name} Blood Oath")
        state.logger.log(state.round_number, f"{actor.name} pays {hp_cost} HP for Blood Oath.")
        finalize_action_resolution(state, actor, skill)
        return

    # Most direct skills are resolved through attack / effect application.
    base_damage = DAMAGE_TIERS[skill.damage_tier]
    base_break = BREAK_TIERS[skill.break_tier]
    damage = ceil_int(base_damage * scale * before_damage_mult * counterphrase_damage_mult * power_damage_mult)
    break_damage = ceil_int(base_break * scale * before_break_mult * counterphrase_break_mult * power_break_mult)

    # Multi-hit skills handled explicitly.
    if skill.effect_id == "glass_reprise":
        target = targets[0]
        for hit_index in range(1, 4):
            if not target.alive():
                break
            apply_damage_to_target(
                state=state,
                source=actor,
                target=target,
                damage=ceil_int(damage * 0.55),
                break_damage=ceil_int(break_damage * 0.45),
                skill=skill,
                can_crit=True,
            )
            state.logger.log(state.round_number, f"{skill.display_name} hit {hit_index}/3 lands.")
        finalize_action_resolution(state, actor, skill)
        return

    if skill.effect_id == "thorn_spiral":
        target = targets[0]
        status = None
        if actor.hp <= actor.max_hp // 2:
            status = ("snare", 2, 85)
        for hit_index in range(1, 3):
            apply_damage_to_target(
                state=state,
                source=actor,
                target=target,
                damage=ceil_int(damage * 0.60),
                break_damage=ceil_int(break_damage * 0.60),
                skill=skill,
                can_crit=True,
                status_to_apply=status if hit_index == 2 else None,
            )
            state.logger.log(state.round_number, f"{skill.display_name} hit {hit_index}/2 lands.")
            if not target.alive():
                break
        finalize_action_resolution(state, actor, skill)
        return

    if skill.effect_id == "relay_beacon":
        target = targets[0]
        result = apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=damage,
            break_damage=break_damage,
            skill=skill,
            can_crit=False,
            status_to_apply=("reveal", 1, 90),
        )
        if result.get("hit_outcome") == "hit":
            state.relay_target_id = target.entity_id
            state.relay_source_name = actor.name
            target.add_condition("relay_mark", 1)
            state.logger.log(state.round_number, f"{target.name} is tagged by Relay Beacon.")
        else:
            state.logger.log(state.round_number, f"Relay Beacon fails to establish a clean tag on {target.name}.")
        finalize_action_resolution(state, actor, skill)
        return

    if skill.effect_id == "hex_burst":
        target = targets[0]
        consumed_status = None
        for status in ("hex", "reveal", "snare", "soak", "scorch", "jolt"):
            if target.has_condition(status):
                consumed_status = status
                target.remove_condition(status)
                break
        if consumed_status:
            damage = ceil_int(damage * 1.35)
            break_damage = ceil_int(break_damage * 1.20)
            state.logger.log(state.round_number, f"{skill.display_name} consumes {consumed_status} for bonus damage.")
        result = apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=damage,
            break_damage=break_damage,
            skill=skill,
            can_crit=True,
        )
        for splash in state.living_enemies():
            if splash is not target:
                apply_break_damage(state, splash, 6)
        finalize_action_resolution(state, actor, skill)
        return

    if skill.effect_id == "tuning_fork_cut":
        target = targets[0]
        tuning_window = (
            target.has_condition("reveal")
            or target.position == "withdrawn"
            or target_recently_channeled(target)
            or recent_successful_reaction(state, actor)
        )
        tuned_break = break_damage
        status_duration = 1
        status_chance = 70
        if tuning_window:
            tuned_break = ceil_int(tuned_break * 1.45)
            if target_recently_channeled(target) and actor.position == "pressing":
                tuned_break = ceil_int(tuned_break * 1.10)
            status_duration = 2
            status_chance = 92
            state.logger.log(state.round_number, f"{skill.display_name} finds a resonant opening.")
        apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=damage,
            break_damage=tuned_break,
            skill=skill,
            can_crit=True,
            status_to_apply=("hex", status_duration, status_chance),
        )
        finalize_action_resolution(state, actor, skill)
        return

    if skill.effect_id == "final_verse":
        target = targets[0]
        payoff_window = (
            target.has_condition("reveal")
            or target.has_condition("staggered")
            or had_counterphrase_charge
            or (state.last_successful_reaction == "parry" and recent_successful_reaction(state, actor))
        )
        verse_damage = damage
        verse_break = break_damage
        verse_crit_bonus = 0
        if payoff_window:
            verse_damage = ceil_int(verse_damage * 1.60)
            verse_break = ceil_int(verse_break * 1.35)
            verse_crit_bonus = 12
            state.change_spotlight(1, f"{actor.name} Final Verse")
            state.logger.log(state.round_number, f"{skill.display_name} crescendos on an exposed target.")
        apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=verse_damage,
            break_damage=verse_break,
            skill=skill,
            can_crit=True,
            crit_bonus=verse_crit_bonus,
        )
        finalize_action_resolution(state, actor, skill)
        return

    # Default single-target or all-target direct handling.
    for target in targets:
        status_payload = None
        if skill.effect_id == "read_opening":
            status_payload = ("reveal", 1, 90)
        elif skill.effect_id == "mark_lunge":
            status_payload = ("reveal", 2, 90)
        elif skill.effect_id == "salt_psalm":
            status_payload = ("hex", 2, 85)
        elif skill.effect_id == "pinning_round":
            status_payload = ("snare", 2, 85)
        elif skill.effect_id == "anchor_cleave":
            pass
        elif skill.affinity in AFFINITY_STATUS and skill.kind in {"spell", "attack", "ranged_attack", "finisher"}:
            # Very light baseline chance for affinity-themed attacks.
            status_payload = None

        apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=damage,
            break_damage=break_damage,
            skill=skill,
            can_crit=skill.kind not in {"support", "utility"},
            status_to_apply=status_payload,
        )

        if (
            skill.effect_id == "read_opening"
            and result.get("hit_outcome") == "hit"
            and is_affinity_advantage(skill.affinity, target.affinity)
        ):
            state.change_spotlight(1, f"{actor.name} Read Opening")
        if skill.effect_id == "anchor_cleave":
            guard_loss = ceil_int(actor.guard * 0.10)
            if actor.posture == "flow":
                guard_loss = ceil_int(guard_loss * 0.50)
            if self_risk_reduction > 0:
                guard_loss = ceil_int(guard_loss * (1.0 - self_risk_reduction))
            actor.guard = max(0, actor.guard - guard_loss)
            state.logger.log(state.round_number, f"{actor.name} loses {guard_loss} guard from Anchor Cleave.")
    # Relay Beacon adapted effect: next allied direct hit against marked target.
    if state.relay_target_id and targets and targets[0].entity_id == state.relay_target_id and actor.team == "player" and skill.effect_id != "relay_beacon":
        actor.restore_guard(8)
        state.logger.log(state.round_number, f"{actor.name} gains 8 guard from Relay Beacon follow-up.")
        # Assist shot from ranger-style relay.
        relay_target = targets[0]
        if relay_target.alive():
            state.logger.log(state.round_number, f"Relay Beacon triggers an assist shot on {relay_target.name}.")
            apply_damage_to_target(
                state=state,
                source=actor,
                target=relay_target,
                damage=8,
                break_damage=5,
                skill=SKILLS["standard_strike"],
                can_crit=False,
                ignore_reaction=True,
            )
        state.relay_target_id = None
        state.relay_source_name = None
        relay_target.remove_condition("relay_mark")
    finalize_action_resolution(state, actor, skill)


def maybe_grant_composure_bonus_action(state: BattleState, actor: Combatant, inputs: ResolvedInputs) -> bool:
    if actor.team != "player":
        return False
    if not actor.alive():
        return False
    if state.battle_over:
        return False

    key = (state.round_number, actor.entity_id)
    if key in state.bonus_action_rounds:
        return False

    state.player_tempo_meter += clamp_int(inputs.composure, 0, 100)
    threshold = COMPOSURE_TEMPO_THRESHOLD
    if state.player_tempo_meter >= threshold:
        state.player_tempo_meter -= threshold
        state.bonus_action_rounds.add(key)
        state.logger.log(state.round_number, f"{actor.name} keeps tempo from Composure {inputs.composure}: bonus action.")
        return True

    state.logger.log(state.round_number, f"Composure tempo {state.player_tempo_meter}/{threshold}.")
    return False


# ---------------------------------------------------------------------------
# Enemy AI and enemy actions
# ---------------------------------------------------------------------------


def enemy_choose_target(state: BattleState, actor: Combatant) -> Combatant:
    players = state.living_players()
    taunted = [unit for unit in players if unit.has_condition("taunt")]
    if taunted:
        return taunted[0]
    if actor.role == "predator":
        return min(players, key=lambda unit: (unit.guard, unit.hp))
    if actor.role in {"fast_skirmisher", "burst_caster"}:
        return min(players, key=lambda unit: (unit.hp, unit.guard))
    if actor.role in {"controller", "defender_controller"}:
        return max(players, key=lambda unit: unit.speed)
    return max(players, key=lambda unit: (unit.hp + unit.guard))


def enemy_action_template(state: BattleState, actor: Combatant) -> None:
    if actor.entity_id.startswith("rustbound_pilgrim"):
        return enemy_rustbound_pilgrim(state, actor)
    if actor.entity_id.startswith("ivy_strangler"):
        return enemy_ivy_strangler(state, actor)
    if actor.entity_id.startswith("flood_acolyte"):
        return enemy_flood_acolyte(state, actor)
    if actor.entity_id.startswith("switchblade_drone"):
        return enemy_switchblade_drone(state, actor)
    if actor.entity_id.startswith("veil_leech"):
        return enemy_veil_leech(state, actor)
    if actor.entity_id.startswith("lamp_witness"):
        return enemy_lamp_witness(state, actor)
    if actor.entity_id.startswith("toll_knight"):
        return enemy_toll_knight(state, actor)
    if actor.entity_id.startswith("root_jury"):
        return enemy_root_jury(state, actor)
    if actor.entity_id.startswith("canal_seraph"):
        return enemy_canal_seraph(state, actor)
    if actor.entity_id.startswith("static_chorister"):
        return enemy_static_chorister(state, actor)
    if actor.entity_id.startswith("archive_shade"):
        return enemy_archive_shade(state, actor)
    if actor.entity_id.startswith("glass_hound"):
        return enemy_glass_hound(state, actor)
    if actor.entity_id == "bell_warden":
        return boss_bell_warden(state, actor)
    if actor.entity_id == "flood_archivist":
        return boss_flood_archivist(state, actor)
    if actor.entity_id == "glass_hound_matriarch":
        return boss_glass_hound_matriarch(state, actor)
    if actor.entity_id == "quiet_magistrate":
        return boss_quiet_magistrate(state, actor)
    if actor.entity_id == "moraine_bailiff":
        return boss_moraine_bailiff(state, actor)
    if actor.entity_id == "bellglass_precentor":
        return boss_bellglass_precentor(state, actor)
    if actor.entity_id == "orison_last_toll":
        return boss_orison_last_toll(state, actor)

    # Fallback basic attack.
    target = enemy_choose_target(state, actor)
    inputs = make_resolved_inputs(*virtual_enemy_inputs(actor), SKILLS["standard_strike"])
    actor.metadata["last_inputs"] = inputs
    apply_posture_and_post_action_effects(state, actor, inputs)
    state.logger.log(state.round_number, f"{actor.name} lashes out at {target.name}.")
    apply_damage_to_target(
        state=state,
        source=actor,
        target=target,
        damage=12,
        break_damage=8,
        skill=SKILLS["standard_strike"],
        can_crit=False,
    )


def enemy_rustbound_pilgrim(state: BattleState, actor: Combatant) -> None:
    target = enemy_choose_target(state, actor)
    if actor.has_condition("delayed_overhead"):
        actor.remove_condition("delayed_overhead")
        inputs = make_resolved_inputs(88, 38, 52, SKILLS["standard_strike"])
        actor.metadata["last_inputs"] = inputs
        apply_posture_and_post_action_effects(state, actor, inputs)
        state.logger.log(state.round_number, f"{actor.name} brings down a rusted overhead on {target.name}.")
        apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=24,
            break_damage=20,
            skill=SKILLS["standard_strike"],
            can_crit=False,
            status_to_apply=("scorch", 2, 80),
            attack_tags=enemy_action_tags(actor, "charged_overhead_release"),
        )
    else:
        actor.add_condition("delayed_overhead", 2)
        actor.restore_guard(6)
        state.logger.log(state.round_number, f"{actor.name} raises its weapon and begins charging a heavy overhead.")


def enemy_ivy_strangler(state: BattleState, actor: Combatant) -> None:
    target = enemy_choose_target(state, actor)
    inputs = make_resolved_inputs(42, 72, 54, SKILLS["standard_strike"])
    actor.metadata["last_inputs"] = inputs
    apply_posture_and_post_action_effects(state, actor, inputs)
    state.logger.log(state.round_number, f"{actor.name} lashes thorn-vines at {target.name}.")
    apply_damage_to_target(
        state=state,
        source=actor,
        target=target,
        damage=12,
        break_damage=8,
        skill=SKILLS["standard_strike"],
        can_crit=False,
        status_to_apply=("snare", 2, 85),
    )


def enemy_flood_acolyte(state: BattleState, actor: Combatant) -> None:
    target = enemy_choose_target(state, actor)
    inputs = make_resolved_inputs(36, 68, 62, SKILLS["standard_strike"])
    actor.metadata["last_inputs"] = inputs
    apply_posture_and_post_action_effects(state, actor, inputs)
    if any(player.has_condition("soak") for player in state.living_players()):
        state.logger.log(state.round_number, f"{actor.name} unleashes a deluge on {target.name}.")
        apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=18,
            break_damage=10,
            skill=SKILLS["standard_strike"],
            can_crit=False,
        )
    else:
        state.logger.log(state.round_number, f"{actor.name} drenches {target.name}.")
        apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=8,
            break_damage=6,
            skill=SKILLS["standard_strike"],
            can_crit=False,
            status_to_apply=("soak", 2, 90),
        )


def enemy_switchblade_drone(state: BattleState, actor: Combatant) -> None:
    target = enemy_choose_target(state, actor)
    inputs = make_resolved_inputs(68, 78, 46, SKILLS["standard_strike"])
    actor.metadata["last_inputs"] = inputs
    apply_posture_and_post_action_effects(state, actor, inputs)
    base = 10
    if target.has_condition("soak"):
        base = 15
    state.logger.log(state.round_number, f"{actor.name} darts in with a switchblade flurry.")
    for hit in range(2):
        apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=base,
            break_damage=6,
            skill=SKILLS["standard_strike"],
            can_crit=False,
            attack_tags=enemy_action_tags(actor, "flurry"),
        )
        if not target.alive():
            break


def enemy_veil_leech(state: BattleState, actor: Combatant) -> None:
    target = enemy_choose_target(state, actor)
    inputs = make_resolved_inputs(54, 66, 74, SKILLS["standard_strike"])
    actor.metadata["last_inputs"] = inputs
    apply_posture_and_post_action_effects(state, actor, inputs)
    state.logger.log(state.round_number, f"{actor.name} siphons warding light from {target.name}.")
    apply_damage_to_target(
        state=state,
        source=actor,
        target=target,
        damage=10,
        break_damage=8,
        skill=SKILLS["standard_strike"],
        can_crit=False,
        status_to_apply=("hex", 2, 70),
    )
    drained = min(10, target.guard)
    target.guard = max(0, target.guard - drained)
    actor.barrier += drained
    if drained:
        state.logger.log(state.round_number, f"{actor.name} steals {drained} guard and turns it into barrier.")


def enemy_lamp_witness(state: BattleState, actor: Combatant) -> None:
    allies = state.living_enemies()
    debuffed_ally = next((unit for unit in allies if any(unit.has_condition(s) for s in ("scorch", "snare", "soak", "jolt", "hex", "reveal"))), None)
    inputs = make_resolved_inputs(38, 64, 74, SKILLS["standard_strike"])
    actor.metadata["last_inputs"] = inputs
    apply_posture_and_post_action_effects(state, actor, inputs)
    if debuffed_ally:
        cleanse_one_debuff(state, debuffed_ally, source_text=actor.name)
        state.logger.log(state.round_number, f"{actor.name} cleanses {debuffed_ally.name}.")
    else:
        target = enemy_choose_target(state, actor)
        state.logger.log(state.round_number, f"{actor.name} judges {target.name} with burning light.")
        apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=10,
            break_damage=5,
            skill=SKILLS["standard_strike"],
            can_crit=False,
            status_to_apply=("reveal", 1, 80),
        )


def enemy_toll_knight(state: BattleState, actor: Combatant) -> None:
    target = enemy_choose_target(state, actor)
    inputs = make_resolved_inputs(82, 34, 60, SKILLS["standard_strike"])
    actor.metadata["last_inputs"] = inputs
    apply_posture_and_post_action_effects(state, actor, inputs)
    if target.guard > 18:
        state.logger.log(state.round_number, f"{actor.name} crashes a bell-forged halberd into {target.name}.")
        apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=20,
            break_damage=18,
            skill=SKILLS["standard_strike"],
            can_crit=False,
            attack_tags=enemy_action_tags(actor, "halberd_swing"),
        )
    else:
        gained = actor.restore_guard(12)
        state.logger.log(state.round_number, f"{actor.name} tightens its stance and restores {gained} guard.")


def enemy_root_jury(state: BattleState, actor: Combatant) -> None:
    target = enemy_choose_target(state, actor)
    inputs = make_resolved_inputs(46, 70, 58, SKILLS["standard_strike"])
    actor.metadata["last_inputs"] = inputs
    apply_posture_and_post_action_effects(state, actor, inputs)
    target.add_condition("taunt", 1)
    state.logger.log(state.round_number, f"{actor.name} binds {target.name} with accusing roots.")
    apply_damage_to_target(
        state=state,
        source=actor,
        target=target,
        damage=12,
        break_damage=10,
        skill=SKILLS["standard_strike"],
        can_crit=False,
        status_to_apply=("snare", 2, 85),
    )


def enemy_canal_seraph(state: BattleState, actor: Combatant) -> None:
    target = enemy_choose_target(state, actor)
    inputs = make_resolved_inputs(40, 68, 64, SKILLS["standard_strike"])
    actor.metadata["last_inputs"] = inputs
    apply_posture_and_post_action_effects(state, actor, inputs)
    if actor.has_condition("airborne"):
        state.logger.log(state.round_number, f"{actor.name} dives from above at {target.name}.")
        apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=16,
            break_damage=10,
            skill=SKILLS["standard_strike"],
            can_crit=False,
            status_to_apply=("soak", 1, 75),
        )
    else:
        actor.add_condition("airborne", 2)
        state.logger.log(state.round_number, f"{actor.name} rises into the air, harder to pin down.")


def enemy_static_chorister(state: BattleState, actor: Combatant) -> None:
    inputs = make_resolved_inputs(44, 72, 62, SKILLS["standard_strike"])
    actor.metadata["last_inputs"] = inputs
    apply_posture_and_post_action_effects(state, actor, inputs)
    soaked_targets = [player for player in state.living_players() if player.has_condition("soak")]
    if soaked_targets:
        state.logger.log(state.round_number, f"{actor.name} sings a static hymn through soaked bodies!")
        for target in soaked_targets:
            apply_damage_to_target(
                state=state,
                source=actor,
                target=target,
                damage=14,
                break_damage=9,
                skill=SKILLS["standard_strike"],
                can_crit=False,
                status_to_apply=("jolt", 1, 85),
            )
    else:
        target = enemy_choose_target(state, actor)
        state.logger.log(state.round_number, f"{actor.name} snaps a charge into {target.name}.")
        apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=13,
            break_damage=10,
            skill=SKILLS["standard_strike"],
            can_crit=False,
            status_to_apply=("jolt", 1, 75),
        )


def enemy_archive_shade(state: BattleState, actor: Combatant) -> None:
    target = enemy_choose_target(state, actor)
    # Copy the target posture for one turn.
    actor.posture = target.posture
    state.logger.log(state.round_number, f"{actor.name} mirrors {target.name}'s {target.posture} posture.")
    apply_damage_to_target(
        state=state,
        source=actor,
        target=target,
        damage=16,
        break_damage=12,
        skill=SKILLS["standard_strike"],
        can_crit=False,
        status_to_apply=("hex", 1, 70),
    )


def enemy_glass_hound(state: BattleState, actor: Combatant) -> None:
    target = min(state.living_players(), key=lambda unit: (unit.guard, unit.hp))
    inputs = make_resolved_inputs(66, 80, 44, SKILLS["standard_strike"])
    actor.metadata["last_inputs"] = inputs
    apply_posture_and_post_action_effects(state, actor, inputs)
    target.add_condition("reveal", 1)
    state.change_enemy_spotlight(1, f"{actor.name} revealed {target.name}")
    state.logger.log(state.round_number, f"{actor.name} pounces on the weakest guard: {target.name}.")
    apply_damage_to_target(
        state=state,
        source=actor,
        target=target,
        damage=18,
        break_damage=9,
        skill=SKILLS["standard_strike"],
        can_crit=False,
    )


# ---------------------------------------------------------------------------
# Boss logic
# ---------------------------------------------------------------------------


def _lookup_combatant_by_id(state: BattleState, entity_id: str) -> Optional[Combatant]:
    for unit in state.everyone():
        if unit.entity_id == entity_id and unit.alive():
            return unit
    return None


def _reaction_answered_cleanly(result: Dict[str, object]) -> bool:
    reaction = str(result.get("reaction", "") or "")
    hp_damage = int(result.get("damage_to_hp", 0) or 0)
    guard_damage = int(result.get("damage_to_guard", 0) or 0)
    if reaction == "guard":
        return hp_damage <= 0
    if reaction in {"dodge", "parry"}:
        return hp_damage <= 0 and guard_damage <= 0
    return False


def _open_punish_window(
    state: BattleState,
    actor: Combatant,
    reason_text: str,
    guard_loss: int,
    break_damage: int,
    reveal_duration: int = 1,
) -> None:
    if reveal_duration > 0:
        actor.add_condition("reveal", reveal_duration)
    if guard_loss > 0:
        actor.guard = max(0, actor.guard - guard_loss)
    if break_damage > 0:
        apply_break_damage(state, actor, break_damage)
    state.logger.log(state.round_number, reason_text)


def _stamp_telegraph_tags(state: BattleState, actor: Combatant, action_id: str) -> None:
    tags = enemy_action_tags(actor, action_id)
    actor.metadata["last_outgoing_tags"] = list(tags)
    actor.metadata["last_outgoing_round"] = state.round_number


def boss_moraine_bailiff(state: BattleState, actor: Combatant) -> None:
    players = state.living_players()
    if not players:
        return
    hp_ratio = actor.hp / max(1, actor.max_hp)
    phase_two = hp_ratio <= 0.55
    if phase_two and not actor.metadata.get("moraine_phase_two_announced", False):
        actor.metadata["moraine_phase_two_announced"] = True
        state.logger.log(state.round_number, f"{actor.name} abandons the lockstep rhythm and slides into a faster flow.")

    marked_target_id = str(actor.metadata.get("moraine_mark_target_id", ""))
    primed_until = int(actor.metadata.get("moraine_primed_until_round", 0) or 0)
    if marked_target_id and state.round_number > primed_until:
        actor.metadata.pop("moraine_mark_target_id", None)
        actor.metadata.pop("moraine_primed_until_round", None)
        state.logger.log(state.round_number, "Moraine's undertow writ collapses under pressure.")

    marked_target: Optional[Combatant] = None
    if marked_target_id and state.round_number <= primed_until:
        marked_target = _lookup_combatant_by_id(state, marked_target_id)

    if marked_target is not None:
        inputs = make_resolved_inputs(86 if phase_two else 80, 52, 70 if phase_two else 82, SKILLS["standard_strike"])
        actor.metadata["last_inputs"] = inputs
        apply_posture_and_post_action_effects(state, actor, inputs)
        state.logger.log(state.round_number, "The spillway screams open.")
        main_result = apply_damage_to_target(
            state=state,
            source=actor,
            target=marked_target,
            damage=26 if phase_two else 22,
            break_damage=22 if phase_two else 18,
            skill=SKILLS["standard_strike"],
            can_crit=False,
            status_to_apply=("soak", 2, 80),
            attack_tags=enemy_action_tags(actor, "spillway_release"),
        )
        clean_answers = 1 if _reaction_answered_cleanly(main_result) else 0
        side_targets = [unit for unit in state.living_players() if unit.entity_id != marked_target.entity_id]
        if side_targets:
            lane_target = min(side_targets, key=lambda unit: (unit.guard, unit.hp))
            state.logger.log(state.round_number, f"Undertow pressure rips down the side lane toward {lane_target.name}.")
            lane_result = apply_damage_to_target(
                state=state,
                source=actor,
                target=lane_target,
                damage=14 if phase_two else 11,
                break_damage=11 if phase_two else 8,
                skill=SKILLS["standard_strike"],
                can_crit=False,
                attack_tags=enemy_action_tags(actor, "spillway_release"),
            )
            if _reaction_answered_cleanly(lane_result):
                clean_answers += 1
        if clean_answers >= 1:
            _open_punish_window(
                state=state,
                actor=actor,
                reason_text="The sluice overcommits and leaves Moraine exposed.",
                guard_loss=12,
                break_damage=16,
                reveal_duration=1,
            )
        else:
            gained = actor.restore_guard(6)
            if gained:
                state.logger.log(state.round_number, f"{actor.name} catches the recoil and restores {gained} guard.")
        actor.metadata.pop("moraine_mark_target_id", None)
        actor.metadata.pop("moraine_primed_until_round", None)
        return

    cycle = actor.times_acted % 3
    if cycle == 1:
        mark_target = min(state.living_players(), key=lambda unit: (unit.guard, unit.hp))
        inputs = make_resolved_inputs(66, 44, 88, SKILLS["standard_strike"])
        actor.metadata["last_inputs"] = inputs
        apply_posture_and_post_action_effects(state, actor, inputs)
        actor.metadata["moraine_mark_target_id"] = mark_target.entity_id
        actor.metadata["moraine_primed_until_round"] = state.round_number + 1
        _stamp_telegraph_tags(state, actor, "undertow_writ")
        state.logger.log(state.round_number, "Moraine plants the flood-key.")
        state.logger.log(state.round_number, f"The sluice pressure rises behind {mark_target.name}.")
        return

    if cycle == 2:
        inputs = make_resolved_inputs(74, 58, 74, SKILLS["standard_strike"])
        actor.metadata["last_inputs"] = inputs
        apply_posture_and_post_action_effects(state, actor, inputs)
        state.logger.log(state.round_number, f"{actor.name} sweeps the breakwater across every lane.")
        clean_reads = 0
        for target in list(state.living_players()):
            result = apply_damage_to_target(
                state=state,
                source=actor,
                target=target,
                damage=13 if phase_two else 11,
                break_damage=11 if phase_two else 9,
                skill=SKILLS["standard_strike"],
                can_crit=False,
                status_to_apply=("soak", 1, 55 if phase_two else 40),
                attack_tags=enemy_action_tags(actor, "breakwater_sweep"),
            )
            if _reaction_answered_cleanly(result):
                clean_reads += 1
        if clean_reads >= 2:
            _open_punish_window(
                state=state,
                actor=actor,
                reason_text="Two clean reads force Moraine off balance.",
                guard_loss=8,
                break_damage=10,
                reveal_duration=1,
            )
        return

    target = enemy_choose_target(state, actor)
    inputs = make_resolved_inputs(82 if phase_two else 78, 42, 80 if not phase_two else 66, SKILLS["standard_strike"])
    actor.metadata["last_inputs"] = inputs
    apply_posture_and_post_action_effects(state, actor, inputs)
    state.logger.log(state.round_number, f"{actor.name} slams a gate stamp into {target.name}.")
    apply_damage_to_target(
        state=state,
        source=actor,
        target=target,
        damage=24 if phase_two else 21,
        break_damage=17,
        skill=SKILLS["standard_strike"],
        can_crit=False,
        attack_tags=enemy_action_tags(actor, "gate_stamp"),
    )


def boss_bellglass_precentor(state: BattleState, actor: Combatant) -> None:
    players = state.living_players()
    if not players:
        return
    hp_ratio = actor.hp / max(1, actor.max_hp)
    phase_two = hp_ratio <= 0.55
    if phase_two and not actor.metadata.get("precentor_phase_two_announced", False):
        actor.metadata["precentor_phase_two_announced"] = True
        state.logger.log(state.round_number, "The chapel mirrors answer back. The precentor's cadence gains an echo.")

    marked_target_id = str(actor.metadata.get("precentor_mark_target_id", ""))
    marked_until = int(actor.metadata.get("precentor_mark_until_round", 0) or 0)
    if marked_target_id and state.round_number > marked_until:
        actor.metadata.pop("precentor_mark_target_id", None)
        actor.metadata.pop("precentor_mark_until_round", None)
        state.logger.log(state.round_number, "The glass sentence loses its count before it can resolve.")

    marked_target: Optional[Combatant] = None
    if marked_target_id and state.round_number <= marked_until:
        marked_target = _lookup_combatant_by_id(state, marked_target_id)
    if marked_target is not None:
        inputs = make_resolved_inputs(64, 88, 70, SKILLS["standard_strike"])
        actor.metadata["last_inputs"] = inputs
        apply_posture_and_post_action_effects(state, actor, inputs)
        state.logger.log(state.round_number, "The last note comes late.")
        finale_result = apply_damage_to_target(
            state=state,
            source=actor,
            target=marked_target,
            damage=26 if phase_two else 22,
            break_damage=18 if phase_two else 15,
            skill=SKILLS["standard_strike"],
            can_crit=False,
            status_to_apply=("hex", 1, 60),
            attack_tags=enemy_action_tags(actor, "final_cadence"),
        )
        if phase_two and marked_target.alive():
            state.logger.log(state.round_number, "A single echo follows the cadence.")
            apply_damage_to_target(
                state=state,
                source=actor,
                target=marked_target,
                damage=12,
                break_damage=9,
                skill=SKILLS["standard_strike"],
                can_crit=False,
                attack_tags=enemy_action_tags(actor, "final_cadence"),
            )
        if _reaction_answered_cleanly(finale_result):
            _open_punish_window(
                state=state,
                actor=actor,
                reason_text="The cadence is answered cleanly and the precentor is exposed.",
                guard_loss=10,
                break_damage=14,
                reveal_duration=1,
            )
        actor.metadata.pop("precentor_mark_target_id", None)
        actor.metadata.pop("precentor_mark_until_round", None)
        return

    cycle = actor.times_acted % 4
    target = enemy_choose_target(state, actor)
    if cycle == 1:
        inputs = make_resolved_inputs(56, 84, 76, SKILLS["standard_strike"])
        actor.metadata["last_inputs"] = inputs
        apply_posture_and_post_action_effects(state, actor, inputs)
        actor.metadata["precentor_mark_target_id"] = target.entity_id
        actor.metadata["precentor_mark_until_round"] = state.round_number + 1
        _stamp_telegraph_tags(state, actor, "witness_beam")
        state.logger.log(state.round_number, "One clear bell rings.")
        state.logger.log(state.round_number, "A pale bar lights behind the cantor.")
        return

    if cycle == 3:
        inputs = make_resolved_inputs(62, 86, 68, SKILLS["standard_strike"])
        actor.metadata["last_inputs"] = inputs
        apply_posture_and_post_action_effects(state, actor, inputs)
        state.logger.log(state.round_number, f"{actor.name} pronounces Sentence of Glass.")
        apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=11,
            break_damage=8,
            skill=SKILLS["standard_strike"],
            can_crit=False,
            attack_tags=enemy_action_tags(actor, "sentence_of_glass"),
        )
        state.logger.log(state.round_number, "The count snaps to two.")
        apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=14,
            break_damage=10,
            skill=SKILLS["standard_strike"],
            can_crit=False,
            attack_tags=enemy_action_tags(actor, "amen_cut"),
        )
        state.logger.log(state.round_number, "The final note comes late.")
        apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=22 if phase_two else 20,
            break_damage=16,
            skill=SKILLS["standard_strike"],
            can_crit=False,
            status_to_apply=("hex", 1, 55),
            attack_tags=enemy_action_tags(actor, "final_cadence"),
        )
        if phase_two and target.alive():
            state.logger.log(state.round_number, "A glass echo answers the finisher.")
            apply_damage_to_target(
                state=state,
                source=actor,
                target=target,
                damage=10,
                break_damage=8,
                skill=SKILLS["standard_strike"],
                can_crit=False,
                attack_tags=enemy_action_tags(actor, "final_cadence"),
            )
        _open_punish_window(
            state=state,
            actor=actor,
            reason_text="Sentence of Glass overreaches, exposing a punish window.",
            guard_loss=12,
            break_damage=16,
            reveal_duration=1,
        )
        return

    inputs = make_resolved_inputs(58, 82, 74, SKILLS["standard_strike"])
    actor.metadata["last_inputs"] = inputs
    apply_posture_and_post_action_effects(state, actor, inputs)
    if target.has_condition("reveal") or (phase_two and actor.times_acted % 2 == 0):
        state.logger.log(state.round_number, f"{actor.name} drops an Amen Cut on {target.name}.")
        result = apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=22 if phase_two else 19,
            break_damage=14,
            skill=SKILLS["standard_strike"],
            can_crit=False,
            attack_tags=enemy_action_tags(actor, "amen_cut"),
        )
        if _reaction_answered_cleanly(result):
            _open_punish_window(
                state=state,
                actor=actor,
                reason_text="A clean defensive read turns the cut into an opening.",
                guard_loss=6,
                break_damage=8,
                reveal_duration=1,
            )
        return
    state.logger.log(state.round_number, f"{actor.name} begins with the first bell against {target.name}.")
    apply_damage_to_target(
        state=state,
        source=actor,
        target=target,
        damage=17 if phase_two else 15,
        break_damage=11 if phase_two else 9,
        skill=SKILLS["standard_strike"],
        can_crit=False,
        status_to_apply=("reveal", 1, 75),
        attack_tags=enemy_action_tags(actor, "first_bell"),
    )


def _orison_cycle(state: BattleState, actor: Combatant) -> Tuple[str, ...]:
    existing = actor.metadata.get("orison_cycle")
    if isinstance(existing, list) and len(existing) == 3:
        return tuple(str(item) for item in existing)
    bias = str(actor.metadata.get("orison_route_bias", "neutral"))
    if bias == "maintenance":
        cycle = ["debt_of_force", "debt_of_nerve", "debt_of_aim"]
    elif bias == "chapel":
        cycle = ["debt_of_aim", "debt_of_force", "debt_of_nerve"]
    else:
        cycle = ["debt_of_force", "debt_of_aim", "debt_of_nerve"]
        state.rng.shuffle(cycle)
    if state.rng.random() < 0.5:
        cycle[1], cycle[2] = cycle[2], cycle[1]
    actor.metadata["orison_cycle"] = list(cycle)
    return tuple(cycle)


def _orison_execute_toll(
    state: BattleState,
    actor: Combatant,
    target: Combatant,
    toll_id: str,
    in_quiet_relay: bool = False,
) -> Dict[str, object]:
    if toll_id == "debt_of_force":
        state.logger.log(state.round_number, "The tower tolls red.")
        return apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=24 if not in_quiet_relay else 20,
            break_damage=20 if not in_quiet_relay else 16,
            skill=SKILLS["standard_strike"],
            can_crit=False,
            status_to_apply=("scorch", 1, 60),
            attack_tags=enemy_action_tags(actor, "debt_of_force"),
        )
    if toll_id == "debt_of_aim":
        state.logger.log(state.round_number, "Only one bellflash is true.")
        state.logger.log(state.round_number, "A false flash skims high before the true cut arrives.")
        return apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=22 if not in_quiet_relay else 18,
            break_damage=16 if not in_quiet_relay else 12,
            skill=SKILLS["standard_strike"],
            can_crit=False,
            status_to_apply=("reveal", 1, 70),
            attack_tags=enemy_action_tags(actor, "debt_of_aim"),
        )
    state.logger.log(state.round_number, "Orison tolls for nerve; the pressure lands after the breath.")
    barrier_shred = min(target.barrier, 10 if not in_quiet_relay else 7)
    if barrier_shred > 0:
        target.barrier -= barrier_shred
        state.logger.log(state.round_number, f"{target.name}'s barrier is sheared by {barrier_shred}.")
    return apply_damage_to_target(
        state=state,
        source=actor,
        target=target,
        damage=20 if not in_quiet_relay else 16,
        break_damage=18 if not in_quiet_relay else 14,
        skill=SKILLS["standard_strike"],
        can_crit=False,
        status_to_apply=("jolt", 1, 55),
        attack_tags=enemy_action_tags(actor, "debt_of_nerve"),
    )


def boss_orison_last_toll(state: BattleState, actor: Combatant) -> None:
    players = state.living_players()
    if not players:
        return
    hp_ratio = actor.hp / max(1, actor.max_hp)
    cycle = _orison_cycle(state, actor)
    bias = str(actor.metadata.get("orison_route_bias", "neutral"))
    if not actor.metadata.get("orison_bias_announced", False):
        actor.metadata["orison_bias_announced"] = True
        if bias == "maintenance":
            state.logger.log(state.round_number, "Orison weighs the party like flood-forged debt.")
        elif bias == "chapel":
            state.logger.log(state.round_number, "Orison's aim toll rises first, as if the chapel was listening.")
    if hp_ratio <= 0.35 and not actor.metadata.get("orison_desperation_announced", False):
        actor.metadata["orison_desperation_announced"] = True
        state.logger.log(state.round_number, f"{actor.name} enters Quiet Relay cadence.")

    target = enemy_choose_target(state, actor)
    if hp_ratio <= 0.35 and actor.times_acted % 3 == 2:
        inputs = make_resolved_inputs(84, 72, 84, SKILLS["standard_strike"])
        actor.metadata["last_inputs"] = inputs
        apply_posture_and_post_action_effects(state, actor, inputs)
        state.logger.log(state.round_number, f"{actor.name} invokes Quiet Relay.")
        state.logger.log(state.round_number, "The second toll comes after the breath.")
        first_toll = cycle[actor.times_acted % len(cycle)]
        second_toll = next((name for name in cycle if name != first_toll), cycle[(actor.times_acted + 1) % len(cycle)])
        result_one = _orison_execute_toll(state, actor, target, first_toll, in_quiet_relay=True)
        if target.alive():
            result_two = _orison_execute_toll(state, actor, target, second_toll, in_quiet_relay=True)
        else:
            spill_target = enemy_choose_target(state, actor)
            result_two = _orison_execute_toll(state, actor, spill_target, second_toll, in_quiet_relay=True)
        if _reaction_answered_cleanly(result_one) or _reaction_answered_cleanly(result_two):
            _open_punish_window(
                state=state,
                actor=actor,
                reason_text="A clean relay read turns Orison's climax into a punish window.",
                guard_loss=16,
                break_damage=18,
                reveal_duration=1,
            )
        else:
            _open_punish_window(
                state=state,
                actor=actor,
                reason_text="Quiet Relay exhausts Orison's footing and opens a brief punish window.",
                guard_loss=10,
                break_damage=12,
                reveal_duration=1,
            )
        return

    if actor.times_acted % 4 == 0:
        inputs = make_resolved_inputs(82, 54, 74, SKILLS["standard_strike"])
        actor.metadata["last_inputs"] = inputs
        apply_posture_and_post_action_effects(state, actor, inputs)
        state.logger.log(state.round_number, f"{actor.name} drives a tower step through {target.name}.")
        result = apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=22 if hp_ratio > 0.35 else 25,
            break_damage=16,
            skill=SKILLS["standard_strike"],
            can_crit=False,
            attack_tags=enemy_action_tags(actor, "tower_step"),
        )
        if _reaction_answered_cleanly(result):
            _open_punish_window(
                state=state,
                actor=actor,
                reason_text="Orison oversteps into an exposed beat.",
                guard_loss=8,
                break_damage=10,
                reveal_duration=1,
            )
        return

    toll_id = cycle[actor.times_acted % len(cycle)]
    if toll_id == "debt_of_force":
        inputs = make_resolved_inputs(86, 44, 76, SKILLS["standard_strike"])
    elif toll_id == "debt_of_aim":
        inputs = make_resolved_inputs(62, 88, 60, SKILLS["standard_strike"])
    else:
        inputs = make_resolved_inputs(64, 60, 88, SKILLS["standard_strike"])
    actor.metadata["last_inputs"] = inputs
    apply_posture_and_post_action_effects(state, actor, inputs)
    result = _orison_execute_toll(state, actor, target, toll_id, in_quiet_relay=False)
    if _reaction_answered_cleanly(result):
        _open_punish_window(
            state=state,
            actor=actor,
            reason_text="The toll is answered cleanly and Orison yields ground.",
            guard_loss=7,
            break_damage=9,
            reveal_duration=1,
        )


def boss_bell_warden(state: BattleState, actor: Combatant) -> None:
    hp_ratio = actor.hp / actor.max_hp
    target = enemy_choose_target(state, actor)
    if hp_ratio <= 0.35:
        # Desperation: burn its own guard for aggression.
        burned = min(actor.guard, 15)
        actor.guard -= burned
        state.logger.log(state.round_number, f"{actor.name} burns {burned} of its own guard in desperation.")
    if actor.times_acted % 3 == 2:
        # Signature move every third action.
        inputs = make_resolved_inputs(90, 34, 68, SKILLS["standard_strike"])
        actor.metadata["last_inputs"] = inputs
        apply_posture_and_post_action_effects(state, actor, inputs)
        state.logger.log(state.round_number, f"{actor.name} unleashes Cathedral Toll on {target.name}!")
        # Three delayed hits modeled as three medium-heavy hits, one reaction each for terminal play.
        total_hits = 3
        for hit in range(1, total_hits + 1):
            if not target.alive():
                break
            hit_damage = 14 if hp_ratio > 0.35 else 18
            hit_break = 12 if hit < total_hits else 18
            apply_damage_to_target(
                state=state,
                source=actor,
                target=target,
                damage=hit_damage,
                break_damage=hit_break,
                skill=SKILLS["standard_strike"],
                can_crit=False,
                status_to_apply=("scorch", 2, 70 if hit == total_hits else 35),
                attack_tags=enemy_action_tags(actor, "cathedral_toll"),
            )
            state.logger.log(state.round_number, f"Cathedral Toll hit {hit}/3 lands.")
        return

    inputs = make_resolved_inputs(82, 40, 66, SKILLS["standard_strike"])
    actor.metadata["last_inputs"] = inputs
    apply_posture_and_post_action_effects(state, actor, inputs)

    if actor.guard < actor.max_guard // 3 and actor.times_acted % 2 == 0:
        gained = actor.restore_guard(20)
        state.logger.log(state.round_number, f"{actor.name} gathers itself and restores {gained} guard.")
        return

    state.logger.log(state.round_number, f"{actor.name} hammers a bell swing into {target.name}.")
    apply_damage_to_target(
        state=state,
        source=actor,
        target=target,
        damage=22 if hp_ratio > 0.5 else 26,
        break_damage=18,
        skill=SKILLS["standard_strike"],
        can_crit=False,
        status_to_apply=("scorch", 1, 45),
        attack_tags=enemy_action_tags(actor, "bell_swing"),
    )


def boss_flood_archivist(state: BattleState, actor: Combatant) -> None:
    # Rotates affinity every 2 actions.
    idx = (actor.times_acted // 2) % len(AFFINITY_ORDER)
    actor.affinity = AFFINITY_ORDER[idx]
    target = enemy_choose_target(state, actor)
    inputs = make_resolved_inputs(44, 72, 68, SKILLS["standard_strike"])
    actor.metadata["last_inputs"] = inputs
    apply_posture_and_post_action_effects(state, actor, inputs)
    state.logger.log(state.round_number, f"{actor.name} rewrites its affinity to {actor.affinity}.")
    if actor.times_acted % 3 == 1:
        forbidden = actor.affinity
        state.logger.log(state.round_number, f"{actor.name} declares {forbidden} forbidden this turn.")
        afflicted = [unit for unit in state.living_players() if unit.affinity == forbidden]
        if afflicted:
            for player in afflicted:
                apply_damage_to_target(
                    state=state,
                    source=actor,
                    target=player,
                    damage=18,
                    break_damage=10,
                    skill=SKILLS["standard_strike"],
                    can_crit=False,
                    status_to_apply=("soak", 2, 80),
                    attack_tags=enemy_action_tags(actor, "rewrite_surge"),
                )
        else:
            apply_damage_to_target(
                state=state,
                source=actor,
                target=target,
                damage=16,
                break_damage=12,
                skill=SKILLS["standard_strike"],
                can_crit=False,
                status_to_apply=("soak", 2, 80),
                attack_tags=enemy_action_tags(actor, "rewrite_surge"),
            )
        return
    apply_damage_to_target(
        state=state,
        source=actor,
        target=target,
        damage=16,
        break_damage=12,
        skill=SKILLS["standard_strike"],
        can_crit=False,
        status_to_apply=("soak", 2, 80),
        attack_tags=enemy_action_tags(actor, "rewrite_surge"),
    )


def boss_glass_hound_matriarch(state: BattleState, actor: Combatant) -> None:
    target = min(state.living_players(), key=lambda unit: (unit.guard, unit.hp))
    inputs = make_resolved_inputs(74, 82, 48, SKILLS["standard_strike"])
    actor.metadata["last_inputs"] = inputs
    apply_posture_and_post_action_effects(state, actor, inputs)
    if actor.times_acted % 3 == 1 and len(state.living_enemies()) < 3:
        # Summon one hound in terminal prototype.
        summon = create_enemy("glass_hound", index=len([e for e in state.enemies if e.entity_id.startswith('glass_hound')]) + 1)
        state.enemies.append(summon)
        state.logger.log(state.round_number, f"{actor.name} summons a Glass Hound!")
    state.logger.log(state.round_number, f"{actor.name} launches a mirrored pounce at {target.name}.")
    apply_damage_to_target(
        state=state,
        source=actor,
        target=target,
        damage=20,
        break_damage=12,
        skill=SKILLS["standard_strike"],
        can_crit=False,
    )


def boss_quiet_magistrate(state: BattleState, actor: Combatant) -> None:
    target = enemy_choose_target(state, actor)
    repeated = False
    recent_skills = [player.last_skill_used for player in state.players if player.last_skill_used]
    if recent_skills:
        repeated = len(set(recent_skills)) < len(recent_skills)
    inputs = make_resolved_inputs(58, 74, 76, SKILLS["standard_strike"])
    actor.metadata["last_inputs"] = inputs
    apply_posture_and_post_action_effects(state, actor, inputs)
    if repeated and actor.times_acted % 2 == 0:
        state.logger.log(state.round_number, f"{actor.name} pronounces Sentence of Repetition!")
        apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=24,
            break_damage=18,
            skill=SKILLS["standard_strike"],
            can_crit=False,
            status_to_apply=("hex", 2, 75),
        )
    else:
        apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=17,
            break_damage=12,
            skill=SKILLS["standard_strike"],
            can_crit=False,
            status_to_apply=("hex", 1, 65),
        )


# ---------------------------------------------------------------------------
# Battle loop
# ---------------------------------------------------------------------------


def ensure_round_ready(state: BattleState) -> None:
    if state.check_end():
        return

    if not state.cursor.battle_started:
        for unit in state.everyone():
            unit.position = POSITION_DEFAULT
        state.cursor.battle_started = True
        state.logger.log(state.round_number, "Battle begins.")
        axes = state.node_axis_scores
        state.logger.log(
            state.round_number,
            f"Node axis scores: Power {axes.get('power', 60)}, Precision {axes.get('precision', 60)}, Composure {axes.get('composure', 60)}.",
        )

    if state.cursor.turn_order_ids and state.cursor.next_actor_index < len(state.cursor.turn_order_ids):
        return

    if state.cursor.turn_order_ids:
        state.round_number += 1
        state.logger.log(state.round_number, "-" * 60)

    order = state.initiative_order()
    state.cursor.turn_order_ids = [unit.entity_id for unit in order]
    state.cursor.next_actor_index = 0
    names = ", ".join(unit.name for unit in order)
    state.logger.log(state.round_number, f"Turn order: {names}")


def process_turn(state: BattleState, actor: Combatant) -> None:
    if not actor.alive():
        return
    can_act = actor.start_turn_tick(state)
    if not actor.alive():
        return
    if not can_act:
        actor.times_acted += 1
        return

    # Hardmode attrition: only enemies naturally recover guard.
    recovered = actor.restore_guard(3) if actor.team == "enemy" else 0
    if recovered > 0:
        state.logger.log(state.round_number, f"{actor.name} recovers {recovered} guard.")

    if actor.team == "player":
        acted = perform_player_action(state, actor)
        if acted and not state.check_end():
            inputs = actor.metadata.get("last_inputs")
            if isinstance(inputs, ResolvedInputs) and maybe_grant_composure_bonus_action(state, actor, inputs):
                if actor.alive() and not state.battle_over:
                    perform_player_action(state, actor)
    else:
        enemy_action_template(state, actor)
        actor.times_acted += 1

    state.check_end()


def run_one_actor_turn(state: BattleState) -> bool:
    while not state.battle_over:
        ensure_round_ready(state)
        if state.check_end():
            return False
        if state.cursor.next_actor_index >= len(state.cursor.turn_order_ids):
            continue

        actor_id = state.cursor.turn_order_ids[state.cursor.next_actor_index]
        state.cursor.next_actor_index += 1
        actor = _lookup_combatant_by_id(state, actor_id)
        if actor is None or not actor.alive():
            continue

        process_turn(state, actor)
        return True
    return False


def run_battle(
    state: BattleState,
    after_actor_turn: Optional[Callable[[BattleState], None]] = None,
) -> str:
    while not state.battle_over:
        acted = run_one_actor_turn(state)
        if acted and after_actor_turn is not None:
            after_actor_turn(state)
        if not acted and state.check_end():
            break
    if state.winner == "player":
        state.logger.log(state.round_number, "Players win the battle.")
    else:
        state.logger.log(state.round_number, "Enemies win the battle.")
    return state.winner or "unknown"


# ---------------------------------------------------------------------------
# Scenario building
# ---------------------------------------------------------------------------


def build_party(party_ids: Sequence[str]) -> List[Combatant]:
    return [create_player(character_id) for character_id in party_ids]


def build_scenario(name: str) -> List[Combatant]:
    if name == "skirmish":
        return [
            create_enemy("rustbound_pilgrim", 1),
            create_enemy("ivy_strangler", 1),
            create_enemy("flood_acolyte", 1),
        ]
    if name == "elites":
        return [
            create_enemy("toll_knight", 1),
            create_enemy("static_chorister", 1),
        ]
    if name == "pack":
        return [
            create_enemy("glass_hound", 1),
            create_enemy("switchblade_drone", 1),
            create_enemy("veil_leech", 1),
        ]
    if name in BOSS_BLUEPRINTS:
        return [create_boss(name)]
    raise ValueError(f"Unknown scenario: {name}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Quiet Relay: 2026 terminal combat core",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--party",
        default="vanguard,duelist,cantor",
        help="Comma-separated list of 3 party members from: vanguard, duelist, cantor, ranger, penitent",
    )
    parser.add_argument(
        "--scenario",
        default="bell_warden",
        help="Battle scenario: skirmish, elites, pack, bell_warden, flood_archivist, glass_hound_matriarch, quiet_magistrate",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Run without prompts using simple AI for players",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=2026,
        help="RNG seed",
    )
    parser.add_argument(
        "--log-file",
        default="quiet_relay_last_battle_log_datadriven.txt",
        help="Where to write the battle log after the fight",
    )
    return parser.parse_args(argv)


def validate_party_ids(raw: str) -> List[str]:
    party_ids = [part.strip() for part in raw.split(",") if part.strip()]
    if len(party_ids) != 3:
        raise ValueError("Party must contain exactly 3 character ids.")
    invalid = [char for char in party_ids if char not in CHARACTER_BLUEPRINTS]
    if invalid:
        raise ValueError(f"Unknown character ids: {', '.join(invalid)}")
    return party_ids


def print_intro(args: argparse.Namespace, party_ids: Sequence[str]) -> None:
    print("\n" + emoji_label("hub", "Quiet Relay: 2026 - Terminal Combat Core"))
    print("=" * 60)
    print(f"{emoji_label('party', 'Party')}: {', '.join(party_ids)}")
    print(f"{emoji_label('battle', 'Scenario')}: {args.scenario}")
    print(f"{emoji_label('continue', 'Mode')}: {'AUTO' if args.auto else 'INTERACTIVE'}")
    print(f"{emoji_label('load', 'Content')}: {CONTENT.base_dir}")
    print("=" * 60)
    print(emoji_label("inspect", "Tip: player actions require manual Power Precision Composure inputs such as: 72 61 84"))
    if not args.auto:
        print("Enemy attacks will ask for Guard / Dodge / Parry reactions.")
        print("Some heavy, channel, or burst-start attacks may offer a Pattern Read after that choice.")
    print()


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        party_ids = validate_party_ids(args.party)
    except ValueError as exc:
        print(f"Party error: {exc}", file=sys.stderr)
        return 2

    if args.scenario not in {"skirmish", "elites", "pack", *BOSS_BLUEPRINTS.keys()}:
        print(f"Unknown scenario: {args.scenario}", file=sys.stderr)
        return 2

    rng = random.Random(args.seed)
    players = build_party(party_ids)
    enemies = build_scenario(args.scenario)
    logger = BattleLogger(echo=True)
    state = BattleState(
        players=players,
        enemies=enemies,
        rng=rng,
        logger=logger,
        interactive=not args.auto,
    )

    print_intro(args, party_ids)
    winner = run_battle(state)
    state.save_log(args.log_file)
    print(f"\nBattle log written to: {args.log_file}")
    return 0 if winner == "player" else 1


if __name__ == "__main__":
    raise SystemExit(main())
