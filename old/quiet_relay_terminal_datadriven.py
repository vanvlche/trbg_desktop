
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
from typing import Dict, List, Optional, Sequence, Tuple

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
            f"{self.affinity:<5}  posture={self.posture:<7}{condition_text}"
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
    combatant = Combatant(
        entity_id=boss_id,
        name=raw["display_name"],
        team="enemy",
        affinity=raw["primary_affinity"],
        max_hp=stats["hp"],
        hp=stats["hp"],
        max_guard=stats["guard"],
        guard=stats["guard"],
        max_break=stats["break"],
        break_meter=stats["break"],
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
    last_player_inputs: Tuple[int, int, int] = (60, 60, 60)
    relay_target_id: Optional[str] = None
    relay_source_name: Optional[str] = None
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

    def change_spotlight(self, amount: int, reason: str) -> None:
        old = self.spotlight
        self.spotlight = clamp_int(self.spotlight + amount, 0, self.spotlight_max)
        delta = self.spotlight - old
        if delta != 0:
            sign_text = "+" if delta > 0 else ""
            self.logger.log(self.round_number, f"Spotlight {sign_text}{delta} ({reason}) -> {self.spotlight}/{self.spotlight_max}")

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
        print(f"ROUND {self.round_number} | Spotlight {self.spotlight}/{self.spotlight_max}")
        print("-" * 84)
        print("PLAYERS")
        for idx, unit in enumerate(self.players, start=1):
            prefix = ">" if unit.alive() else "x"
            print(f"{prefix}{idx}. {unit.summary_line()}")
        print("-" * 84)
        print("ENEMIES")
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


def crit_chance(actor: Combatant, skill: Skill, inputs: ResolvedInputs, target: Combatant, extra_bonus: int = 0) -> int:
    chance = 5
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
    }

    if not source.alive() or not target.alive():
        return result

    damage_mult, break_mult = posture_damage_break_multipliers(source.posture)
    damage = ceil_int(damage * damage_mult)
    break_damage = ceil_int(break_damage * break_mult)

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
        reaction = choose_reaction(state, target, source, skill)
        result["reaction"] = reaction
        damage, break_damage, prevented, extra_logs = resolve_reaction(
            state=state,
            target=target,
            attacker=source,
            incoming_damage=damage,
            incoming_break=break_damage,
            reaction=reaction,
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
    if damage > 0 and target.guard > 0:
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
    if break_damage > 0 and target.alive():
        result["break_damage"] = apply_break_damage(state, target, break_damage)

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
        state.logger.log(state.round_number, f"{target.name} is staggered!")
    return dealt


def grant_barrier_to_lowest_guard_ally(state: BattleState, source: Combatant, amount: int) -> None:
    allies = state.get_allies(source)
    if not allies:
        return
    target = min(allies, key=lambda unit: (unit.guard / max(unit.max_guard, 1), unit.hp))
    target.barrier += amount
    state.logger.log(state.round_number, f"{target.name} gains {amount} barrier from {source.name}'s passive.")


# ---------------------------------------------------------------------------
# Reaction system
# ---------------------------------------------------------------------------


def choose_reaction(state: BattleState, target: Combatant, attacker: Combatant, skill: Skill) -> str:
    if not state.interactive:
        # Auto logic: bastion likes parry, low guard likes dodge, otherwise guard.
        if target.posture == "bastion" or target.has_condition("feint_circuit"):
            return "parry"
        if target.guard <= 8:
            return "dodge"
        return "guard"

    while True:
        print(f"\nReaction for {target.name}: [g]uard, [d]odge, [p]arry")
        print(f"Incoming: {attacker.name} uses {skill.display_name}. {target.name} posture={target.posture}.")
        choice = input("> ").strip().lower()
        if choice in {"g", "guard", ""}:
            return "guard"
        if choice in {"d", "dodge"}:
            return "dodge"
        if choice in {"p", "parry"}:
            return "parry"
        print("Please type g, d, or p.")


def resolve_reaction(
    state: BattleState,
    target: Combatant,
    attacker: Combatant,
    incoming_damage: int,
    incoming_break: int,
    reaction: str,
) -> Tuple[int, int, bool, List[str]]:
    logs: List[str] = []
    prevented = False

    if reaction == "guard":
        hp_spill_mult = 1.0
        if target.has_condition("brace_guard"):
            hp_spill_mult *= 0.80
            target.remove_condition("brace_guard")
            logs.append(f"{target.name}'s Brace softens the impact.")
        if target.posture == "bastion":
            hp_spill_mult *= 0.90
        # Guard sends damage into guard first, but any spill to HP is reduced by spill multiplier.
        if target.guard > 0:
            overflow = max(0, incoming_damage - target.guard)
            adjusted_overflow = ceil_int(overflow * hp_spill_mult)
            effective_damage = min(incoming_damage, target.guard) + adjusted_overflow
        else:
            effective_damage = ceil_int(incoming_damage * hp_spill_mult)
        return effective_damage, incoming_break, prevented, logs

    if reaction == "dodge":
        chance = 35
        if target.posture == "focus":
            chance += 10
        if target.posture == "flow":
            chance += 8
        if target.posture == "bastion":
            chance += 5
        if target.has_condition("snare"):
            chance -= 15
        if target.has_condition("soak"):
            chance -= 10
        chance = clamp_int(chance, 5, 80)
        roll = state.rng.randint(1, 100)
        if roll <= chance:
            prevented = True
            logs.append(f"{target.name} dodges cleanly!")
            return 0, 0, prevented, logs
        reduced = ceil_int(incoming_damage * 0.60)
        logs.append(f"{target.name} mistimes the dodge and still takes reduced damage.")
        return reduced, ceil_int(incoming_break * 0.50), prevented, logs

    # parry
    chance = 18
    if target.posture == "bastion":
        chance += 18
    if target.posture == "flow":
        chance += 6
    if target.has_condition("feint_circuit"):
        chance += 15
    chance = clamp_int(chance, 5, 85)
    roll = state.rng.randint(1, 100)
    if roll <= chance:
        prevented = True
        logs.append(f"{target.name} parries the blow!")
        parry_break = 18 + (6 if target.posture == "bastion" else 0)
        apply_break_damage(state, attacker, parry_break)
        state.change_spotlight(1, f"{target.name} parry")
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
    multiplier = 1.20
    if target.posture == "bastion":
        multiplier = 1.08
    logs.append(f"{target.name} misses the parry and is punished.")
    return ceil_int(incoming_damage * multiplier), incoming_break, prevented, logs


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
    if actor.posture == "flow":
        state.change_spotlight(1, f"{actor.name} entered Flow")
        cleanse_one_debuff(state, actor)
    if actor.entity_id == "vanguard" and actor.posture in {"bastion", "ravage"}:
        restored = actor.restore_guard(max(1, actor.max_guard // 10))
        if restored:
            state.logger.log(state.round_number, f"{actor.name} restores {restored} guard from passive.")


def cleanse_one_debuff(state: BattleState, actor: Combatant) -> None:
    for status in ("scorch", "snare", "soak", "jolt", "hex", "reveal"):
        if actor.has_condition(status):
            actor.remove_condition(status)
            state.logger.log(state.round_number, f"{actor.name} cleanses {status} via Flow.")
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


def perform_player_action(state: BattleState, actor: Combatant) -> None:
    if state.interactive:
        state.render_state()
        skill = choose_player_skill(state, actor)
        targets = choose_target(state, actor, skill)
        resolved_inputs = prompt_triplet(state.last_player_inputs, skill)
        state.last_player_inputs = (resolved_inputs.power, resolved_inputs.precision, resolved_inputs.composure)
    else:
        skill = auto_choose_player_skill(state, actor)
        targets = choose_target(state, actor, skill)
        resolved_inputs = auto_triplet_for_skill(actor, skill, state.rng)

    if state.spotlight < skill.spotlight_cost:
        state.logger.log(state.round_number, f"{actor.name} lacks the Spotlight for {skill.display_name}.")
        return

    state.change_spotlight(-skill.spotlight_cost, f"{actor.name} used {skill.display_name}")
    actor.metadata["last_inputs"] = resolved_inputs
    apply_posture_and_post_action_effects(state, actor, resolved_inputs)
    context = ActionContext(user=actor, skill=skill, targets=targets, inputs=resolved_inputs, spotlight_spent=skill.spotlight_cost)
    resolve_action(state, context)
    actor.times_acted += 1
    actor.last_skill_used = skill.skill_id


def resolve_action(state: BattleState, context: ActionContext) -> None:
    actor = context.user
    skill = context.skill
    targets = context.targets
    inputs = context.inputs
    scale = compute_scale_multiplier(actor, skill, inputs)

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
        return

    if skill.effect_id == "ward_bell":
        for ally in state.get_allies(actor):
            gained = ally.restore_guard(ceil_int(ally.max_guard * 0.20))
            if gained:
                state.logger.log(state.round_number, f"{ally.name} restores {gained} guard from Ward Bell.")
        actor.add_condition("taunt", 1)
        state.logger.log(state.round_number, f"{actor.name} rings Ward Bell and draws enemy focus.")
        return

    if skill.effect_id == "feint_circuit":
        actor.add_condition("feint_circuit", 1)
        state.logger.log(state.round_number, f"{actor.name} enters Feint Circuit stance.")
        return

    if skill.effect_id == "undertow_litany":
        for ally in state.get_allies(actor):
            cleanse_one_debuff(state, ally)
            ally.barrier += 10
            state.logger.log(state.round_number, f"{ally.name} gains 10 barrier from Undertow Litany.")
        return

    if skill.effect_id == "blood_oath":
        hp_cost = max(8, ceil_int(actor.max_hp * 0.10))
        actor.hp = max(1, actor.hp - hp_cost)
        actor.next_attack_power_bonus = 1
        actor.add_condition("exposed_self", 1)
        state.change_spotlight(1, f"{actor.name} Blood Oath")
        state.logger.log(state.round_number, f"{actor.name} pays {hp_cost} HP for Blood Oath.")
        return

    # Most direct skills are resolved through attack / effect application.
    base_damage = DAMAGE_TIERS[skill.damage_tier]
    base_break = BREAK_TIERS[skill.break_tier]
    damage = ceil_int(base_damage * scale)
    break_damage = ceil_int(base_break * scale)

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
        return

    if skill.effect_id == "relay_beacon":
        target = targets[0]
        apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=damage,
            break_damage=break_damage,
            skill=skill,
            can_crit=False,
            status_to_apply=("reveal", 1, 90),
        )
        state.relay_target_id = target.entity_id
        state.relay_source_name = actor.name
        target.add_condition("relay_mark", 1)
        state.logger.log(state.round_number, f"{target.name} is tagged by Relay Beacon.")
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
        apply_damage_to_target(
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

        if skill.effect_id == "read_opening" and is_affinity_advantage(skill.affinity, target.affinity):
            state.change_spotlight(1, f"{actor.name} Read Opening")
        if skill.effect_id == "anchor_cleave":
            guard_loss = ceil_int(actor.guard * 0.10)
            if actor.posture == "flow":
                guard_loss = ceil_int(guard_loss * 0.50)
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
        cleanse_one_debuff(state, debuffed_ally)
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


def process_turn(state: BattleState, actor: Combatant) -> None:
    if not actor.alive():
        return
    can_act = actor.start_turn_tick(state)
    if not actor.alive():
        return
    if not can_act:
        actor.times_acted += 1
        return

    # Small natural guard recovery at turn start.
    recovered = actor.restore_guard(4 if actor.team == "player" else 3)
    if recovered > 0:
        state.logger.log(state.round_number, f"{actor.name} recovers {recovered} guard.")

    if actor.team == "player":
        perform_player_action(state, actor)
    else:
        enemy_action_template(state, actor)
        actor.times_acted += 1

    state.check_end()


def run_battle(state: BattleState) -> str:
    state.logger.log(state.round_number, "Battle begins.")
    while not state.battle_over:
        order = state.initiative_order()
        names = ", ".join(unit.name for unit in order)
        state.logger.log(state.round_number, f"Turn order: {names}")
        for actor in order:
            if state.check_end():
                break
            process_turn(state, actor)
            if state.check_end():
                break
        if not state.battle_over:
            state.round_number += 1
            state.logger.log(state.round_number, "-" * 60)
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
        default="/mnt/data/quiet_relay_last_battle_log_datadriven.txt",
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
    print("\nQuiet Relay: 2026 - Terminal Combat Core")
    print("=" * 60)
    print(f"Party: {', '.join(party_ids)}")
    print(f"Scenario: {args.scenario}")
    print(f"Mode: {'AUTO' if args.auto else 'INTERACTIVE'}")
    print(f"Content: {CONTENT.base_dir}")
    print("=" * 60)
    print("Tip: player actions require manual Power Precision Composure inputs such as: 72 61 84")
    if not args.auto:
        print("Enemy attacks will ask for Guard / Dodge / Parry reactions.")
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
