
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
- manual player input per turn
- AP-based player actions and battle loadouts
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
EQUIPMENT_DATA = WEAPON_DATA
RELIC_DATA = CONTENT.relic_data

STATUS_DISPLAY_ORDER = [
    "scorch",
    "snare",
    "soak",
    "jolt",
    "hex",
    "poisoned_chalice",
    "reveal",
    "rain_mark",
    "taunt",
    "brace_guard",
    "feint_circuit",
    "blood_vow",
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

DEFAULT_AXIS_TRIPLET = (60, 60, 60)
BALANCE_MODE_STANDARD = "standard"
BALANCE_MODE_EXPEDITION = "expedition"
DEFAULT_HEALING_POTIONS_PER_RUN = 1
EXTRA_ACTION_LOADOUT_SLOTS = 3
EQUIPMENT_SLOTS = ("main_hand", "off_hand", "both_hands")

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
MAX_STARTING_AP = 6

POWER_DAMAGE_MULT_PER_POINT = 0.01
POWER_DAMAGE_MULT_MIN = 0.60
POWER_DAMAGE_MULT_MAX = 1.60
POWER_BREAK_MULT_PER_POINT = 0.008
POWER_BREAK_MULT_MIN = 0.70
POWER_BREAK_MULT_MAX = 1.50
PRECISION_HIT_BONUS_PER_POINT = 0.008
PRECISION_CRIT_BONUS_PER_POINT = 0.003
PRECISION_MAX_CRIT_BONUS = 0.45
PLAYER_ATTACK_BASE_HIT_CHANCE = 70
PLAYER_MIN_HIT_CHANCE = 10
PLAYER_MAX_HIT_CHANCE = 95
HEALING_POTION_HEAL_RATIO = 0.35
NEXT_TURN_AP_BONUS_CAP = 1
DEFENSIVE_ACTIONS_ARE_BASIC = False

LIGHT_ATTACK_AP_COST = 1
HEAVY_ATTACK_POWER_REQUIREMENT = 60
HEAVY_ATTACK_DAMAGE_MULTIPLIER = 2.00
HEAVY_ATTACK_BREAK_MULTIPLIER = 1.70
HEAVY_ATTACK_POWER_SURGE_THRESHOLD = 75
HEAVY_ATTACK_POWER_SURGE_DAMAGE_MULT = 1.10
HEAVY_ATTACK_POWER_SURGE_BREAK_MULT = 1.10
FEINT_RUSH_AP_COST = 1
FEINT_RUSH_ACCURACY_BONUS = 15
DOUBLE_STRIKE_AP_COST = 2
DOUBLE_STRIKE_DAMAGE_MULTIPLIER = 0.75
DOUBLE_STRIKE_BREAK_MULTIPLIER = 0.75
DOUBLE_STRIKE_BOTH_HITS_BREAK_BONUS = 6
BACKSTEP_SLASH_AP_COST = 1
BACKSTEP_SLASH_DAMAGE_MULTIPLIER = 0.80
BACKSTEP_SLASH_ACCURACY_PENALTY = 10
BACKSTEP_SLASH_DUELIST_EVASION_BONUS = 20
BACKSTEP_SLASH_RANGER_EVASION_BONUS = 25
CHARGE_SLASH_AP_COST = 2
CHARGE_SLASH_DAMAGE_MULTIPLIER = 0.95
CHARGE_SLASH_BREAK_MULTIPLIER = 2.40
CHARGE_SLASH_SELF_GUARD_COST = 10
TRANCE_AP_COST = 3
TRANCE_REQUIRED_HIGH_COMPOSURE_TURNS = 3
TRANCE_NORMAL_MAX_HITS = 6
TRANCE_BOSS_MAX_HITS = 4
TRANCE_SPOTLIGHT_HIT_BONUS = 5
TRANCE_SPOTLIGHT_DAMAGE_BONUS_PER = 0.03
TRANCE_CHAIN_HIT_PENALTY_PER_HIT = 8
TRANCE_BOSS_FOLLOWUP_DAMAGE_MULT = 0.85
POISONED_CHALICE_AP_COST = 2
POISONED_CHALICE_DAMAGE_MULTIPLIER = 0.90
POISONED_CHALICE_DURATION = 2
POISONED_CHALICE_MIN_DOT = 4
POISONED_CHALICE_BREAK_VULNERABILITY_MULT = 1.10
POISONED_CHALICE_EVASION_PENALTY = 25
POISONED_CHALICE_ACCURACY_PENALTY = 15
BACKFLIP_AP_COST = 1
BACKFLIP_EVASION_BONUS = 25
BACKFLIP_BREAK_RECOVERY_RATIO = 0.20
BACKFLIP_NEXT_HEALING_BONUS = 0.20
BACKFLIP_MAX_USES_PER_COMBAT = 2
DEFENSIVE_TECHNIQUE_AP_COST = 1
DEFENSIVE_TECHNIQUE_GUARD_RECOVERY_RATIO = 0.25
DEFENSIVE_TECHNIQUE_BASTION_BONUS = 0.10
DEFENSIVE_TECHNIQUE_SHIELD_BONUS = 0.10
DEFENSIVE_TECHNIQUE_VANGUARD_SHIELD_BONUS = 0.10
DEFENSIVE_TECHNIQUE_REACTION_BONUS = 5
FRACTURE_SHIELD_GUARD_RECOVERY_MULT = 1.30
FRACTURE_SHIELD_EXCESS_BREAK_RATIO = 0.50
REGAIN_BALANCE_AP_COST = 1
REGAIN_BALANCE_BREAK_RECOVERY_RATIO = 0.25
REGAIN_BALANCE_LOW_STABILITY_THRESHOLD = 0.30
REGAIN_BALANCE_LOW_STABILITY_BONUS = 0.10
REGAIN_BALANCE_COMPOSURE_THRESHOLD = 70
REGAIN_BALANCE_COMPOSURE_BONUS = 0.10
REGAIN_BALANCE_STANCE_BONUS = 0.10
SHIELD_OATH_AP_COST = 1
SHIELD_OATH_GUARD_RECOVERY_RATIO = 0.20
SHIELD_OATH_BREAK_BONUS_MULT = 1.15
SHIELD_OATH_COOLDOWN_TURNS = 2
RAZOR_ENCORE_AP_COST = 2
RAZOR_ENCORE_FOLLOWUP_DAMAGE_MULTIPLIER = 0.65
QUIET_BENEDICTION_AP_COST = 2
QUIET_BENEDICTION_HEAL_RATIO = 0.22
RAIN_MARK_AP_COST = 1
RAIN_MARK_DURATION = 2
RAIN_MARK_HIT_BONUS = 10
RAIN_MARK_BREAK_BONUS_MULT = 1.10
BLOOD_VOW_AP_COST = 1
BLOOD_VOW_DAMAGE_BONUS_MULT = 1.15
BLOOD_VOW_MAX_HP_COST_RATIO = 0.08
BLOOD_VOW_CURRENT_HP_COST_RATIO = 0.10
BLOOD_VOW_STATUS_DURATION = 2
MOONCLEAVE_MAX_STACKS = 6
MOONCLEAVE_CRIT_BONUS_PER_STACK = 5
BLACK_VIAL_MAX_STACKS = 3
BLACK_VIAL_DAMAGE_BONUS_PER_STACK = 0.08
BLACK_VIAL_STATUS_BONUS_PER_STACK = 5
KINGS_WAGER_INCOMING_DAMAGE_MULT = 2.00
KINGS_WAGER_EXECUTION_THRESHOLD = 5
KINGS_WAGER_BOSS_EXECUTION_VALUE = 3
ANKLET_AP_REFUND = 1
ANKLET_AP_REFUND_EXTRA_CAP = 1
ANKLET_PRECISION_CARRY_BONUS = 10
POTION_UPGRADE_CAPACITY_BONUS = 1
POTION_UPGRADE_STRONGER_MULT = 1.20
POTION_UPGRADE_GUARD_RESTORE_RATIO = 0.18
POTION_UPGRADE_SPOTLIGHT_GAIN = 1
CHALICE_TOLERANCE_PENALTY_MULT = 0.50
VANGUARD_ONE_HANDED_DAMAGE_MULTIPLIER = 1.03
VANGUARD_ONE_HANDED_BREAK_MULTIPLIER = 1.05
VANGUARD_SHIELD_GUARD_BONUS = 2
VANGUARD_SHIELD_REACTION_BONUS = 5
VANGUARD_SHIELD_CHARGE_SLASH_BREAK_MULTIPLIER = 1.10
VANGUARD_SHIELD_CHARGE_SLASH_GUARD_DELTA = -1
DUELIST_PAIRED_HIT_BONUS = 5
DUELIST_PAIRED_CRIT_BONUS = 3
DUELIST_PAIRED_DOUBLE_STRIKE_HIT_BONUS = 5
DUELIST_PAIRED_DOUBLE_STRIKE_CRIT_BONUS = 2
DUELIST_TWO_HANDED_BLADE_DAMAGE_MULTIPLIER = 1.05
DUELIST_TWO_HANDED_BLADE_CRIT_BONUS = 2
CANTOR_MAGE_HIT_BONUS = 3
CANTOR_MAGE_STATUS_SUCCESS_BONUS = 5
CANTOR_MAGE_HEALING_MULTIPLIER = 1.10

FLOW_SPOTLIGHT_COOLDOWN_ROUNDS = 2
FOCUS_HIT_BONUS = 10
FOCUS_MIN_HIT_CHANCE = 72
FOCUS_GRAZE_MARGIN = 14
RAVAGE_BREAK_FINISH_RATIO = 0.45
RAVAGE_BREAK_FINISH_MULTIPLIER = 1.35

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


def stdout_supports_text(text: str) -> bool:
    if not text:
        return True
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    if "utf" not in encoding.lower() and not text.isascii():
        return False
    try:
        text.encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return False
    return True


def ui_icon(key: str) -> str:
    if not ENABLE_SEMANTIC_EMOJI_UI:
        return ""
    icon = UI_ICONS.get(key, "")
    return icon if stdout_supports_text(icon) else ""


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
class BattleActionDef:
    action_id: str
    name: str
    description: str
    ap_cost: int
    force_turn_end: bool = False
    requires_full_ap: bool = False
    consumes_all_ap: bool = False
    requires_class: Tuple[str, ...] = ()
    target: str = "single_enemy"
    kind: str = "attack"
    affinity: Optional[str] = None
    primary_scale: str = "power"
    secondary_scale: str = "precision"
    damage_tier: str = "medium"
    break_tier: str = "low"
    tags: Tuple[str, ...] = ()
    is_extra_action: bool = False


@dataclass(frozen=True)
class EquipmentItem:
    item_id: str
    display_name: str
    type: str
    handedness: str
    slot: str
    tags: Tuple[str, ...]
    description: str
    base_damage_bonus: int = 0
    damage_multiplier: float = 1.0
    break_multiplier: float = 1.0
    hit_bonus: int = 0
    crit_bonus: int = 0
    guard_bonus: int = 0
    evasion_bonus: int = 0
    ap_bonus: int = 0
    healing_multiplier: float = 1.0
    potion_heal_bonus: int = 0
    status_success_bonus: int = 0
    reaction_bonus: int = 0
    action_modifiers: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    class_bonuses: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass
class EquipmentModifiers:
    base_damage_bonus: int = 0
    damage_multiplier: float = 1.0
    break_multiplier: float = 1.0
    hit_bonus: int = 0
    crit_bonus: int = 0
    guard_bonus: int = 0
    evasion_bonus: int = 0
    ap_bonus: int = 0
    healing_multiplier: float = 1.0
    potion_heal_bonus: int = 0
    status_success_bonus: int = 0
    reaction_bonus: int = 0
    self_guard_cost_delta: int = 0


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


@dataclass(frozen=True)
class PartyBalanceProfile:
    party_size: int
    mode: str
    enemy_hp_mult: float = 1.0
    enemy_guard_mult: float = 1.0
    enemy_break_mult: float = 1.0
    enemy_damage_mult: float = 1.0
    boss_hp_mult: float = 1.0
    boss_guard_mult: float = 1.0
    boss_break_mult: float = 1.0
    boss_pressure_mult: float = 1.0
    reaction_failure_damage_mult: float = 1.0
    healing_reward_mult: float = 1.0
    recovery_heal_mult: float = 1.0


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
        if self.team == "player":
            self.metadata["used_light_attack_this_turn"] = False
            self.metadata["current_ap"] = 0
            self.metadata["starting_ap"] = 0
            self.metadata.pop("turn_inputs", None)
            self.metadata.pop("turn_power", None)
            self.metadata.pop("turn_precision", None)
            self.metadata.pop("turn_composure", None)
            self.metadata.pop("action_input_logged_round", None)
            self.metadata.pop("evasion_bonus_until_next_turn", None)
            self.metadata.pop("evasion_penalty_until_next_turn", None)
            self.metadata.pop("cannot_guard_next_turn", None)
            self.metadata.pop("cannot_parry_next_turn", None)
            self.metadata.pop("current_action_accuracy_modifier", None)
            self.metadata.pop("defensive_reaction_bonus_until_next_turn", None)
            self.metadata["defensive_technique_used_turn"] = False
            self.metadata["regain_balance_used_turn"] = False
            self.metadata["fracture_shield_overflow_used_turn"] = False
            self.metadata["anklet_refund_used_this_turn"] = False
            self.metadata.pop("turn_accuracy_penalty", None)
            pending_turn_accuracy_penalty = clamp_int(
                int(self.metadata.pop("pending_poisoned_chalice_accuracy_penalty", 0)),
                0,
                100,
            )
            if pending_turn_accuracy_penalty > 0:
                self.metadata["turn_accuracy_penalty"] = pending_turn_accuracy_penalty
                state.logger.log(
                    state.round_number,
                    f"{self.name} is still reeling from Poisoned Chalice: attack accuracy -{pending_turn_accuracy_penalty} this turn.",
                )
            shield_oath_cooldown = max(0, int(self.metadata.get("shield_oath_cooldown", 0)))
            if shield_oath_cooldown > 0:
                self.metadata["shield_oath_cooldown"] = shield_oath_cooldown - 1

        # Tick ongoing effects before duration reduction.
        if self.has_condition("scorch"):
            dmg = max(4, int(self.max_hp * 0.05))
            state.logger.log(state.round_number, f"{self.name} is scorched for {dmg} damage.")
            state.apply_direct_hp_loss(self, dmg, reason="scorch")
        if self.has_condition("poisoned_chalice"):
            dmg = max(
                POISONED_CHALICE_MIN_DOT,
                int(self.metadata.get("poisoned_chalice_dot", POISONED_CHALICE_MIN_DOT)),
            )
            state.logger.log(state.round_number, f"{self.name} suffers {dmg} damage from Poisoned Chalice.")
            state.apply_direct_hp_loss(self, dmg, reason="poisoned_chalice")
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

BATTLE_ACTIONS: Dict[str, BattleActionDef] = {
    "light_attack": BattleActionDef(
        action_id="light_attack",
        name="Light Attack",
        description="Reliable 1 AP attack. Can be chained into Feint Rush.",
        ap_cost=LIGHT_ATTACK_AP_COST,
        primary_scale="power",
        secondary_scale="precision",
        damage_tier="medium",
        break_tier="low",
    ),
    "heavy_attack": BattleActionDef(
        action_id="heavy_attack",
        name="Heavy Attack",
        description="Full-AP finisher. Falters if Power is below 60.",
        ap_cost=1,
        force_turn_end=True,
        requires_full_ap=True,
        consumes_all_ap=True,
        primary_scale="power",
        secondary_scale="precision",
        damage_tier="high",
        break_tier="medium",
        tags=("heavy",),
    ),
    "use_healing_potion": BattleActionDef(
        action_id="use_healing_potion",
        name="Use Healing Potion",
        description="Consume 1 potion to restore 35% max HP and end the turn.",
        ap_cost=1,
        force_turn_end=True,
        consumes_all_ap=True,
        target="self",
        kind="utility",
        primary_scale="composure",
        secondary_scale="power",
        damage_tier="none",
        break_tier="none",
    ),
    "feint_rush": BattleActionDef(
        action_id="feint_rush",
        name="Feint Rush",
        description="After Light Attack, end the turn to boost the next attack's accuracy.",
        ap_cost=FEINT_RUSH_AP_COST,
        force_turn_end=True,
        requires_class=(),
        target="self",
        kind="utility",
        primary_scale="precision",
        secondary_scale="composure",
        damage_tier="none",
        break_tier="none",
        is_extra_action=True,
    ),
    "double_strike": BattleActionDef(
        action_id="double_strike",
        name="Double Strike",
        description="Attack twice for 2 AP, but Guard and Parry are disabled until your next turn.",
        ap_cost=DOUBLE_STRIKE_AP_COST,
        primary_scale="precision",
        secondary_scale="power",
        damage_tier="medium",
        break_tier="low",
        is_extra_action=True,
    ),
    "backstep_slash": BattleActionDef(
        action_id="backstep_slash",
        name="Backstep Slash",
        description="Duelist/Ranger only. Slash, gain evasion, and take an accuracy penalty on the next attack.",
        ap_cost=BACKSTEP_SLASH_AP_COST,
        requires_class=("duelist", "ranger"),
        primary_scale="precision",
        secondary_scale="composure",
        damage_tier="medium",
        break_tier="low",
        is_extra_action=True,
    ),
    "charge_slash": BattleActionDef(
        action_id="charge_slash",
        name="Charge Slash",
        description="Vanguard only. Spend Guard to hammer enemy Break and gain +1 AP next turn on stagger.",
        ap_cost=CHARGE_SLASH_AP_COST,
        requires_class=("vanguard",),
        primary_scale="power",
        secondary_scale="composure",
        damage_tier="medium",
        break_tier="high",
        tags=("heavy", "burst_start"),
        is_extra_action=True,
    ),
    "trance": BattleActionDef(
        action_id="trance",
        name="Trance",
        description="Once per combat. Requires 3 turns of Composure 80+ and 1+ Spotlight to launch a chain finisher.",
        ap_cost=TRANCE_AP_COST,
        force_turn_end=True,
        consumes_all_ap=True,
        kind="finisher",
        primary_scale="composure",
        secondary_scale="precision",
        damage_tier="medium",
        break_tier="medium",
        tags=("combo", "heavy"),
        is_extra_action=True,
    ),
    "poisoned_chalice": BattleActionDef(
        action_id="poisoned_chalice",
        name="Poisoned Chalice",
        description="Spend 1 potion to heal, strike, and poison the target, but suffer next-turn penalties.",
        ap_cost=POISONED_CHALICE_AP_COST,
        force_turn_end=True,
        consumes_all_ap=True,
        kind="attack",
        primary_scale="power",
        secondary_scale="precision",
        damage_tier="medium",
        break_tier="low",
        is_extra_action=True,
    ),
    "backflip": BattleActionDef(
        action_id="backflip",
        name="Backflip",
        description="Recover stability, raise evasion, and strengthen the next heal. Max 2 uses per combat.",
        ap_cost=BACKFLIP_AP_COST,
        target="self",
        kind="utility",
        primary_scale="composure",
        secondary_scale="precision",
        damage_tier="none",
        break_tier="none",
        is_extra_action=True,
    ),
    "defensive_technique": BattleActionDef(
        action_id="defensive_technique",
        name="Defensive Technique",
        description="Recover Guard and sharpen defensive timing. Once per turn.",
        ap_cost=DEFENSIVE_TECHNIQUE_AP_COST,
        target="self",
        kind="defense",
        primary_scale="composure",
        secondary_scale="power",
        damage_tier="none",
        break_tier="none",
        is_extra_action=True,
    ),
    "regain_balance": BattleActionDef(
        action_id="regain_balance",
        name="Regain Balance",
        description="Recover Break stability, stronger when near collapse. Once per turn.",
        ap_cost=REGAIN_BALANCE_AP_COST,
        target="self",
        kind="utility",
        primary_scale="composure",
        secondary_scale="power",
        damage_tier="none",
        break_tier="none",
        is_extra_action=True,
    ),
    "shield_oath": BattleActionDef(
        action_id="shield_oath",
        name="Shield Oath",
        description="Vanguard only. Restore Guard and empower the next Break action.",
        ap_cost=SHIELD_OATH_AP_COST,
        requires_class=("vanguard",),
        target="self",
        kind="utility",
        primary_scale="composure",
        secondary_scale="power",
        damage_tier="none",
        break_tier="none",
        is_extra_action=True,
    ),
    "razor_encore": BattleActionDef(
        action_id="razor_encore",
        name="Razor Encore",
        description="Duelist only. Crit to trigger a reduced follow-up slash.",
        ap_cost=RAZOR_ENCORE_AP_COST,
        requires_class=("duelist",),
        primary_scale="precision",
        secondary_scale="power",
        damage_tier="medium",
        break_tier="low",
        is_extra_action=True,
    ),
    "quiet_benediction": BattleActionDef(
        action_id="quiet_benediction",
        name="Quiet Benediction",
        description="Cantor only. Heal the most wounded ally, cleanse one debuff, and gain extra value from mage gear.",
        ap_cost=QUIET_BENEDICTION_AP_COST,
        requires_class=("cantor",),
        target="self",
        kind="support",
        primary_scale="composure",
        secondary_scale="precision",
        damage_tier="none",
        break_tier="none",
        is_extra_action=True,
    ),
    "rain_mark": BattleActionDef(
        action_id="rain_mark",
        name="Rain Mark",
        description="Ranger only. Mark an enemy for reliable follow-up hits and the next Break push.",
        ap_cost=RAIN_MARK_AP_COST,
        requires_class=("ranger",),
        kind="utility",
        primary_scale="precision",
        secondary_scale="composure",
        damage_tier="none",
        break_tier="none",
        is_extra_action=True,
    ),
    "blood_vow": BattleActionDef(
        action_id="blood_vow",
        name="Blood Vow",
        description="Penitent only. Sacrifice HP to empower the next attack with damage and curse pressure.",
        ap_cost=BLOOD_VOW_AP_COST,
        requires_class=("penitent",),
        target="self",
        kind="utility",
        primary_scale="power",
        secondary_scale="composure",
        damage_tier="none",
        break_tier="none",
        is_extra_action=True,
    ),
}

BASIC_BATTLE_ACTION_IDS = (
    "light_attack",
    "heavy_attack",
    "use_healing_potion",
) + (() if not DEFENSIVE_ACTIONS_ARE_BASIC else ("defensive_technique", "regain_balance"))
EXTRA_BATTLE_ACTION_IDS = (
    "feint_rush",
    "double_strike",
    "backstep_slash",
    "charge_slash",
    "trance",
    "poisoned_chalice",
    "backflip",
    "shield_oath",
    "razor_encore",
    "quiet_benediction",
    "rain_mark",
    "blood_vow",
) + (() if DEFENSIVE_ACTIONS_ARE_BASIC else ("defensive_technique", "regain_balance"))


# ---------------------------------------------------------------------------
# Equipment registry and helpers
# ---------------------------------------------------------------------------


def chance_bonus_points(value: Any) -> int:
    if value is None:
        return 0
    number = float(value)
    if -1.0 <= number <= 1.0:
        return int(round(number * 100.0))
    return int(round(number))


def build_equipment_registry() -> Dict[str, EquipmentItem]:
    registry: Dict[str, EquipmentItem] = {}
    for item_id, raw in EQUIPMENT_DATA.items():
        registry[item_id] = EquipmentItem(
            item_id=item_id,
            display_name=str(raw["display_name"]),
            type=str(raw.get("type", "weapon")),
            handedness=str(raw.get("handedness", "one_handed")),
            slot=str(raw.get("slot", "main_hand")),
            tags=tuple(str(tag) for tag in raw.get("tags", [])),
            description=str(raw.get("description", "")),
            base_damage_bonus=int(raw.get("base_damage_bonus", 0)),
            damage_multiplier=float(raw.get("damage_multiplier", 1.0)),
            break_multiplier=float(raw.get("break_multiplier", 1.0)),
            hit_bonus=chance_bonus_points(raw.get("hit_bonus", 0)),
            crit_bonus=chance_bonus_points(raw.get("crit_bonus", 0)),
            guard_bonus=int(raw.get("guard_bonus", 0)),
            evasion_bonus=chance_bonus_points(raw.get("evasion_bonus", 0)),
            ap_bonus=int(raw.get("ap_bonus", 0)),
            healing_multiplier=float(raw.get("healing_multiplier", 1.0)),
            potion_heal_bonus=int(raw.get("potion_heal_bonus", 0)),
            status_success_bonus=chance_bonus_points(raw.get("status_success_bonus", 0)),
            reaction_bonus=chance_bonus_points(raw.get("reaction_bonus", 0)),
            action_modifiers={
                str(action_id): dict(payload)
                for action_id, payload in dict(raw.get("action_modifiers", {})).items()
                if isinstance(payload, dict)
            },
            class_bonuses={
                str(class_id): dict(payload)
                for class_id, payload in dict(raw.get("class_bonuses", {})).items()
                if isinstance(payload, dict)
            },
        )
    return registry


EQUIPMENT = build_equipment_registry()


def get_equipment(item_id: object) -> Optional[EquipmentItem]:
    if item_id is None:
        return None
    return EQUIPMENT.get(str(item_id))


def equipment_occupies_both_hands(item: EquipmentItem) -> bool:
    return item.slot == "both_hands" or item.handedness in {"two_handed", "paired"}


def starting_equipment_slots_for_character(character_id: str) -> Dict[str, str]:
    raw = CHARACTER_BLUEPRINTS.get(character_id, {})
    configured = raw.get("starting_equipment", {})
    slot_map: Dict[str, str] = {}
    if isinstance(configured, dict):
        for slot_name in EQUIPMENT_SLOTS:
            item_id = configured.get(slot_name)
            if item_id and get_equipment(item_id) is not None:
                slot_map[slot_name] = str(item_id)
    if slot_map:
        return slot_map
    fallback_weapon_id = str(raw.get("weapon", "")).strip()
    fallback_item = get_equipment(fallback_weapon_id)
    if fallback_item is None:
        return {}
    return {fallback_item.slot: fallback_item.item_id}


def sanitize_equipment_slot_map(slot_map: object) -> Dict[str, str]:
    raw_slots = dict(slot_map) if isinstance(slot_map, dict) else {}
    both_hands_id = raw_slots.get("both_hands")
    both_hands_item = get_equipment(both_hands_id)
    if both_hands_item is not None and equipment_occupies_both_hands(both_hands_item):
        return {"both_hands": both_hands_item.item_id}

    cleaned: Dict[str, str] = {}
    main_hand_id = raw_slots.get("main_hand")
    main_hand_item = get_equipment(main_hand_id)
    if main_hand_item is not None and main_hand_item.slot == "main_hand":
        cleaned["main_hand"] = main_hand_item.item_id

    off_hand_id = raw_slots.get("off_hand")
    off_hand_item = get_equipment(off_hand_id)
    if off_hand_item is not None and off_hand_item.slot == "off_hand":
        cleaned["off_hand"] = off_hand_item.item_id

    return cleaned


def update_legacy_weapon_metadata(actor: Combatant) -> None:
    slot_map = sanitize_equipment_slot_map(actor.metadata.get("equipment_slots"))
    primary_item = get_equipment(slot_map.get("both_hands")) or get_equipment(slot_map.get("main_hand"))
    if primary_item is not None:
        actor.metadata["weapon_id"] = primary_item.item_id
        actor.metadata["weapon_name"] = primary_item.display_name
    else:
        actor.metadata["weapon_id"] = None
        actor.metadata["weapon_name"] = "Unarmed"


def ensure_actor_equipment_state(actor: Combatant) -> None:
    if actor.team != "player":
        return
    slots = sanitize_equipment_slot_map(actor.metadata.get("equipment_slots"))
    if not slots:
        slots = sanitize_equipment_slot_map(starting_equipment_slots_for_character(actor.entity_id))
    actor.metadata["equipment_slots"] = slots
    update_legacy_weapon_metadata(actor)


def get_character_equipment(actor: Combatant) -> Dict[str, EquipmentItem]:
    ensure_actor_equipment_state(actor)
    slot_map = sanitize_equipment_slot_map(actor.metadata.get("equipment_slots"))
    actor.metadata["equipment_slots"] = slot_map
    return {
        slot_name: item
        for slot_name in EQUIPMENT_SLOTS
        for item in [get_equipment(slot_map.get(slot_name))]
        if item is not None
    }


def can_equip_item(actor: Combatant, item: EquipmentItem, slot_name: Optional[str] = None) -> bool:
    target_slot = item.slot if slot_name is None else str(slot_name)
    if target_slot != item.slot:
        return False
    current_equipment = get_character_equipment(actor)
    if target_slot == "off_hand" and "both_hands" in current_equipment:
        return False
    return True


def equip_item(actor: Combatant, item_id: str, slot_name: Optional[str] = None) -> bool:
    item = get_equipment(item_id)
    if item is None:
        return False
    target_slot = item.slot if slot_name is None else str(slot_name)
    if not can_equip_item(actor, item, target_slot):
        return False
    current_slots = sanitize_equipment_slot_map(actor.metadata.get("equipment_slots"))
    if target_slot == "both_hands":
        current_slots = {"both_hands": item.item_id}
    else:
        current_slots.pop("both_hands", None)
        current_slots[target_slot] = item.item_id
    actor.metadata["equipment_slots"] = sanitize_equipment_slot_map(current_slots)
    update_legacy_weapon_metadata(actor)
    return True


def equipment_summary_text(actor: Combatant) -> str:
    equipment = get_character_equipment(actor)
    both_hands = equipment.get("both_hands")
    if both_hands is not None:
        return both_hands.display_name
    parts = []
    main_hand = equipment.get("main_hand")
    off_hand = equipment.get("off_hand")
    if main_hand is not None:
        parts.append(main_hand.display_name)
    if off_hand is not None:
        parts.append(off_hand.display_name)
    return " + ".join(parts) if parts else "Unarmed"


def starting_equipment_summary(character_id: str) -> str:
    stub = Combatant(
        entity_id=character_id,
        name=character_id,
        team="player",
        affinity="neutral",
        max_hp=1,
        hp=1,
        max_guard=0,
        guard=0,
        max_break=0,
        break_meter=0,
        speed=0,
        skills=[],
    )
    stub.metadata["equipment_slots"] = starting_equipment_slots_for_character(character_id)
    return equipment_summary_text(stub)


def equipment_has_tag(item: Optional[EquipmentItem], tag: str) -> bool:
    return item is not None and tag in item.tags


def merge_equipment_modifier_payload(modifiers: EquipmentModifiers, payload: Dict[str, Any]) -> None:
    modifiers.base_damage_bonus += int(payload.get("base_damage_bonus", 0))
    modifiers.damage_multiplier *= float(payload.get("damage_multiplier", 1.0))
    modifiers.break_multiplier *= float(payload.get("break_multiplier", 1.0))
    modifiers.hit_bonus += chance_bonus_points(payload.get("hit_bonus", 0))
    modifiers.crit_bonus += chance_bonus_points(payload.get("crit_bonus", 0))
    modifiers.guard_bonus += int(payload.get("guard_bonus", 0))
    modifiers.evasion_bonus += chance_bonus_points(payload.get("evasion_bonus", 0))
    modifiers.ap_bonus += int(payload.get("ap_bonus", 0))
    modifiers.healing_multiplier *= float(payload.get("healing_multiplier", 1.0))
    modifiers.potion_heal_bonus += int(payload.get("potion_heal_bonus", 0))
    modifiers.status_success_bonus += chance_bonus_points(payload.get("status_success_bonus", 0))
    modifiers.reaction_bonus += chance_bonus_points(payload.get("reaction_bonus", 0))
    modifiers.self_guard_cost_delta += int(payload.get("self_guard_cost_delta", 0))


def apply_equipment_modifiers(modifiers: EquipmentModifiers, payload: Dict[str, Any]) -> EquipmentModifiers:
    merge_equipment_modifier_payload(modifiers, payload)
    return modifiers


def class_equipment_bonus_payload(actor: Combatant, action_id: Optional[str] = None) -> Dict[str, Any]:
    equipment = get_character_equipment(actor)
    both_hands = equipment.get("both_hands")
    main_hand = equipment.get("main_hand")
    off_hand = equipment.get("off_hand")
    has_shield = equipment_has_tag(off_hand, "shield")
    mage_weapon = any(equipment_has_tag(item, "mage") for item in equipment.values())

    if actor.entity_id == "vanguard":
        if both_hands is None and main_hand is not None and has_shield:
            payload: Dict[str, Any] = {
                "damage_multiplier": VANGUARD_ONE_HANDED_DAMAGE_MULTIPLIER,
                "break_multiplier": VANGUARD_ONE_HANDED_BREAK_MULTIPLIER,
                "guard_bonus": VANGUARD_SHIELD_GUARD_BONUS,
                "reaction_bonus": VANGUARD_SHIELD_REACTION_BONUS,
            }
            if action_id == "charge_slash":
                payload["break_multiplier"] *= VANGUARD_SHIELD_CHARGE_SLASH_BREAK_MULTIPLIER
                payload["self_guard_cost_delta"] = VANGUARD_SHIELD_CHARGE_SLASH_GUARD_DELTA
            return payload
        if both_hands is None and main_hand is not None and main_hand.handedness == "one_handed":
            return {
                "damage_multiplier": VANGUARD_ONE_HANDED_DAMAGE_MULTIPLIER,
                "break_multiplier": VANGUARD_ONE_HANDED_BREAK_MULTIPLIER,
            }
        return {}

    if actor.entity_id == "duelist":
        if both_hands is not None and both_hands.handedness == "paired":
            payload = {
                "hit_bonus": DUELIST_PAIRED_HIT_BONUS,
                "crit_bonus": DUELIST_PAIRED_CRIT_BONUS,
            }
            if action_id == "double_strike":
                payload["hit_bonus"] += DUELIST_PAIRED_DOUBLE_STRIKE_HIT_BONUS
                payload["crit_bonus"] += DUELIST_PAIRED_DOUBLE_STRIKE_CRIT_BONUS
            return payload
        if both_hands is not None and both_hands.handedness == "two_handed" and "blade" in both_hands.tags:
            return {
                "damage_multiplier": DUELIST_TWO_HANDED_BLADE_DAMAGE_MULTIPLIER,
                "crit_bonus": DUELIST_TWO_HANDED_BLADE_CRIT_BONUS,
            }
        return {}

    if actor.entity_id == "cantor" and mage_weapon:
        return {
            "hit_bonus": CANTOR_MAGE_HIT_BONUS,
            "status_success_bonus": CANTOR_MAGE_STATUS_SUCCESS_BONUS,
            "healing_multiplier": CANTOR_MAGE_HEALING_MULTIPLIER,
        }

    return {}


def get_class_equipment_bonus(actor: Combatant, equipment: Dict[str, EquipmentItem], action_id: Optional[str] = None) -> EquipmentModifiers:
    modifiers = EquipmentModifiers()
    merge_equipment_modifier_payload(modifiers, class_equipment_bonus_payload(actor, action_id=action_id))
    return modifiers


def calculate_equipment_modifiers(
    actor: Combatant,
    action_id: Optional[str] = None,
    skill: Optional[Skill] = None,
) -> EquipmentModifiers:
    if actor.team != "player":
        return EquipmentModifiers()

    resolved_action_id = action_id or (skill.effect_id if skill is not None else None)
    equipment = get_character_equipment(actor)
    modifiers = EquipmentModifiers()
    for item in equipment.values():
        merge_equipment_modifier_payload(
            modifiers,
            {
                "base_damage_bonus": item.base_damage_bonus,
                "damage_multiplier": item.damage_multiplier,
                "break_multiplier": item.break_multiplier,
                "hit_bonus": item.hit_bonus,
                "crit_bonus": item.crit_bonus,
                "guard_bonus": item.guard_bonus,
                "evasion_bonus": item.evasion_bonus,
                "ap_bonus": item.ap_bonus,
                "healing_multiplier": item.healing_multiplier,
                "potion_heal_bonus": item.potion_heal_bonus,
                "status_success_bonus": item.status_success_bonus,
                "reaction_bonus": item.reaction_bonus,
            },
        )
        class_payload = item.class_bonuses.get(actor.entity_id, {})
        if class_payload:
            merge_equipment_modifier_payload(modifiers, class_payload)
            if resolved_action_id is not None:
                merge_equipment_modifier_payload(modifiers, dict(class_payload.get("action_modifiers", {})).get(resolved_action_id, {}))
        if resolved_action_id is not None:
            merge_equipment_modifier_payload(modifiers, item.action_modifiers.get(resolved_action_id, {}))

    class_modifiers = get_class_equipment_bonus(actor, equipment, action_id=resolved_action_id)
    modifiers.base_damage_bonus += class_modifiers.base_damage_bonus
    modifiers.damage_multiplier *= class_modifiers.damage_multiplier
    modifiers.break_multiplier *= class_modifiers.break_multiplier
    modifiers.hit_bonus += class_modifiers.hit_bonus
    modifiers.crit_bonus += class_modifiers.crit_bonus
    modifiers.guard_bonus += class_modifiers.guard_bonus
    modifiers.evasion_bonus += class_modifiers.evasion_bonus
    modifiers.ap_bonus += class_modifiers.ap_bonus
    modifiers.healing_multiplier *= class_modifiers.healing_multiplier
    modifiers.potion_heal_bonus += class_modifiers.potion_heal_bonus
    modifiers.status_success_bonus += class_modifiers.status_success_bonus
    modifiers.reaction_bonus += class_modifiers.reaction_bonus
    modifiers.self_guard_cost_delta += class_modifiers.self_guard_cost_delta
    return modifiers


def equipment_bonus_summary_lines(actor: Combatant) -> List[str]:
    equipment = get_character_equipment(actor)
    lines: List[str] = [f"{actor.name} equips {equipment_summary_text(actor)}."]
    both_hands = equipment.get("both_hands")
    main_hand = equipment.get("main_hand")
    off_hand = equipment.get("off_hand")
    if actor.entity_id == "vanguard" and both_hands is None and main_hand is not None and equipment_has_tag(off_hand, "shield"):
        lines.append(
            f"{actor.name} shield discipline: Guard +{VANGUARD_SHIELD_GUARD_BONUS}, "
            f"reaction +{VANGUARD_SHIELD_REACTION_BONUS}%, Break +5%, Charge Slash Break +10%."
        )
    elif actor.entity_id == "duelist" and both_hands is not None and both_hands.handedness == "paired":
        lines.append(
            f"{actor.name} paired tempo: Hit +{DUELIST_PAIRED_HIT_BONUS}%, "
            f"Crit +{DUELIST_PAIRED_CRIT_BONUS}%, Double Strike hit +{DUELIST_PAIRED_DOUBLE_STRIKE_HIT_BONUS}%."
        )
    elif actor.entity_id == "cantor" and any(equipment_has_tag(item, "mage") for item in equipment.values()):
        lines.append(
            f"{actor.name} mage focus: Hit +{CANTOR_MAGE_HIT_BONUS}%, "
            f"status +{CANTOR_MAGE_STATUS_SUCCESS_BONUS}%, healing x{CANTOR_MAGE_HEALING_MULTIPLIER:.2f}."
        )
    return lines


def actor_has_item_equipped(actor: Combatant, item_id: str) -> bool:
    return any(item.item_id == item_id for item in get_character_equipment(actor).values())


def actor_has_shield_equipped(actor: Combatant) -> bool:
    equipment = get_character_equipment(actor)
    return equipment_has_tag(equipment.get("off_hand"), "shield")


def actor_uses_one_handed_shield_setup(actor: Combatant) -> bool:
    equipment = get_character_equipment(actor)
    both_hands = equipment.get("both_hands")
    main_hand = equipment.get("main_hand")
    return both_hands is None and main_hand is not None and actor_has_shield_equipped(actor)

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
    combatant.metadata["relic_ids"] = list(raw.get("starting_relics", []))
    combatant.metadata["relic_names"] = [
        RELIC_DATA.get(relic_id, {}).get("display_name", relic_id)
        for relic_id in raw.get("starting_relics", [])
    ]
    combatant.metadata["equipment_slots"] = starting_equipment_slots_for_character(character_id)
    ensure_actor_equipment_state(combatant)
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
    combatant.metadata["counts_for_execution"] = True
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
    combatant.metadata["counts_for_execution"] = True
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
    balance_mode: str = BALANCE_MODE_STANDARD
    healing_potions: int = DEFAULT_HEALING_POTIONS_PER_RUN
    potion_upgrade_ids: List[str] = field(default_factory=list)
    selected_extra_actions: List[str] = field(default_factory=list)
    round_number: int = 1
    spotlight: int = 0
    spotlight_max: int = 5
    enemy_spotlight: int = 0
    enemy_spotlight_max: int = 5
    node_axis_scores: Dict[str, int] = field(default_factory=lambda: {"power": DEFAULT_AXIS_TRIPLET[0], "precision": DEFAULT_AXIS_TRIPLET[1], "composure": DEFAULT_AXIS_TRIPLET[2]})
    player_tempo_meter: int = 0
    bonus_action_rounds: Set[Tuple[int, str]] = field(default_factory=set)
    last_player_inputs: Tuple[int, int, int] = DEFAULT_AXIS_TRIPLET
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

    def party_balance_profile(self) -> PartyBalanceProfile:
        return get_party_balance_profile(len(self.players), self.balance_mode)

    def apply_enemy_balance(self, enemy: Combatant) -> None:
        if enemy.team != "enemy":
            return
        if bool(enemy.metadata.get("party_balance_applied", False)):
            return
        profile = self.party_balance_profile()
        hp_mult = profile.enemy_hp_mult * (profile.boss_hp_mult if enemy.is_boss else 1.0)
        guard_mult = profile.enemy_guard_mult * (profile.boss_guard_mult if enemy.is_boss else 1.0)
        break_mult = profile.enemy_break_mult * (profile.boss_break_mult if enemy.is_boss else 1.0)
        enemy.max_hp = scaled_amount(enemy.max_hp, hp_mult)
        enemy.hp = min(enemy.max_hp, scaled_amount(enemy.hp, hp_mult))
        enemy.max_guard = scaled_amount(enemy.max_guard, guard_mult) if enemy.max_guard > 0 else 0
        enemy.guard = min(enemy.max_guard, scaled_amount(enemy.guard, guard_mult)) if enemy.max_guard > 0 else 0
        enemy.max_break = scaled_amount(enemy.max_break, break_mult) if enemy.max_break > 0 else 0
        enemy.break_meter = min(enemy.max_break, scaled_amount(enemy.break_meter, break_mult)) if enemy.max_break > 0 else 0
        enemy.metadata["party_balance_applied"] = True

    def initialize_enemy_balance(self) -> None:
        for enemy in self.enemies:
            self.apply_enemy_balance(enemy)

    def enemy_pressure_multiplier(self, enemy: Combatant) -> float:
        profile = self.party_balance_profile()
        multiplier = profile.enemy_damage_mult
        if enemy.is_boss:
            multiplier *= profile.boss_pressure_mult
        return multiplier

    def reaction_failure_damage_multiplier(self, enemy: Combatant) -> float:
        profile = self.party_balance_profile()
        multiplier = profile.reaction_failure_damage_mult
        if enemy.is_boss:
            multiplier *= profile.boss_pressure_mult
        return multiplier

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
            self.check_end()

    def damage_taken_mult(self, target: Combatant) -> float:
        mult = 1.0
        if target.has_condition("hex"):
            mult *= 1.10
        if target.has_condition("exposed_self"):
            mult *= 1.15
        if target.has_condition("reveal"):
            mult *= 1.05
        if target.team == "player" and actor_has_relic(target, "kings_wager"):
            mult *= KINGS_WAGER_INCOMING_DAMAGE_MULT
        return mult

    def render_state(self) -> None:
        print("\n" + "=" * 84)
        axes = self.node_axis_scores
        print(
            f"{emoji_label('round', f'ROUND {self.round_number}')} | "
            f"{emoji_label('spotlight', 'Player Spotlight')} {self.spotlight}/{self.spotlight_max} | "
            f"Enemy Spotlight {self.enemy_spotlight}/{self.enemy_spotlight_max} | "
            f"Potions {self.healing_potions}"
        )
        print(
            f"Node Axis: Power {axes.get('power', 60)}, "
            f"Precision {axes.get('precision', 60)}, "
            f"Composure {axes.get('composure', 60)}"
        )
        if self.selected_extra_actions:
            loadout_names = ", ".join(BATTLE_ACTIONS[action_id].name for action_id in self.selected_extra_actions if action_id in BATTLE_ACTIONS)
            if loadout_names:
                print(f"Battle Loadout: {loadout_names}")
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
    if unit.team == "player":
        ensure_actor_equipment_state(unit)
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
        "balance_mode": state.balance_mode,
        "healing_potions": state.healing_potions,
        "potion_upgrade_ids": list(state.potion_upgrade_ids),
        "selected_extra_actions": list(state.selected_extra_actions),
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
        balance_mode=str(payload.get("balance_mode", BALANCE_MODE_STANDARD)),
        healing_potions=max(0, int(payload.get("healing_potions", DEFAULT_HEALING_POTIONS_PER_RUN))),
        potion_upgrade_ids=[str(upgrade_id) for upgrade_id in list(payload.get("potion_upgrade_ids", []))],
        selected_extra_actions=[
            str(action_id)
            for action_id in list(payload.get("selected_extra_actions", []))
            if str(action_id) in BATTLE_ACTIONS
        ],
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
    else:
        chance += int(round(precision_crit_bonus(inputs.precision) * 100))
        precision_carry = max(0, current_precision_carry_bonus(actor))
        if precision_carry > 0:
            chance += int(round(max(0.0, precision_carry * PRECISION_CRIT_BONUS_PER_POINT * 100)))
        chance += calculate_equipment_modifiers(actor, action_id=skill.effect_id, skill=skill).crit_bonus
        chance += mooncleave_crit_bonus(actor)
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
    equipment_modifiers = calculate_equipment_modifiers(actor, action_id=skill.effect_id, skill=skill)
    chance = PLAYER_ATTACK_BASE_HIT_CHANCE + int(round(precision_hit_bonus(inputs.precision) * 100))
    precision_carry = max(0, current_precision_carry_bonus(actor))
    if precision_carry > 0:
        chance += int(round(precision_carry * PRECISION_HIT_BONUS_PER_POINT * 100))
    if skill.primary_scale == "precision":
        chance += 6
    if skill.secondary_scale == "precision":
        chance += 3
    if target.has_condition("reveal"):
        chance += 5
    if target.has_condition("rain_mark"):
        chance += RAIN_MARK_HIT_BONUS
    if target.has_condition("staggered"):
        chance += 10
    if actor.has_condition("snare"):
        chance -= 10
    if actor.has_condition("hex"):
        chance -= 5
    ranged_attack = skill.kind == "ranged_attack" or "ranged" in skill.tags or skill.effect_id == "linebreaker_shot"
    if target.has_condition("airborne"):
        chance += 5 if ranged_attack else -8
    if actor.posture == "focus":
        chance += FOCUS_HIT_BONUS
        chance = max(chance, FOCUS_MIN_HIT_CHANCE)
    chance += equipment_modifiers.hit_bonus
    chance += action_accuracy_modifier(actor)
    return clamp_int(chance, PLAYER_MIN_HIT_CHANCE, PLAYER_MAX_HIT_CHANCE)


def player_power_damage_multiplier(state: BattleState, actor: Combatant, skill: Skill, inputs: ResolvedInputs) -> float:
    return power_damage_multiplier(inputs.power)


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
    if target.has_condition("poisoned_chalice"):
        break_damage = ceil_int(break_damage * POISONED_CHALICE_BREAK_VULNERABILITY_MULT)
    if (
        source.team == "player"
        and target.has_condition("rain_mark")
        and bool(target.metadata.get("rain_mark_break_bonus_pending", False))
        and break_damage > 0
    ):
        break_damage = ceil_int(break_damage * RAIN_MARK_BREAK_BONUS_MULT)
        target.metadata["rain_mark_break_bonus_pending"] = False
        state.logger.log(state.round_number, f"Rain Mark buckles {target.name}'s footing for extra Break pressure.")

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
            inputs = make_resolved_inputs(
                *current_node_axis_triplet(state),
                skill,
            )
        hit_chance = player_hit_chance(source, skill, inputs, target)
        roll = state.rng.randint(1, 100)
        margin = roll - hit_chance
        graze_margin = FOCUS_GRAZE_MARGIN if source.posture == "focus" else 10
        high_risk = (
            skill.effect_id == "anchor_cleave"
            or skill.damage_tier in {"high", "extreme"}
            or any(tag in POSITION_PUNISH_TAGS for tag in resolved_tags)
        )
        if roll <= hit_chance:
            result["hit_outcome"] = "hit"
            state.logger.log(state.round_number, f"{source.name} lines up {target.name} [hit roll {roll}/{hit_chance}].")
        elif margin <= graze_margin:
            result["hit_outcome"] = "graze"
            damage = ceil_int(damage * 0.50)
            break_damage = ceil_int(break_damage * 0.50)
            status_to_apply = None
            can_crit = False
            if source.posture == "focus" and margin > 10:
                state.logger.log(
                    state.round_number,
                    f"{source.name} turns a near miss into a graze on {target.name} [hit roll {roll}/{hit_chance}].",
                )
            else:
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
        pressure_mult = state.enemy_pressure_multiplier(source)
        damage = ceil_int(damage * ENEMY_DAMAGE_MULTIPLIER * pressure_mult)
        break_damage = ceil_int(break_damage * ENEMY_DAMAGE_MULTIPLIER * pressure_mult)
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

    if source.posture == "ravage" and target.team == "enemy" and break_damage > 0:
        finish_threshold = max(1, ceil_int(target.max_break * RAVAGE_BREAK_FINISH_RATIO))
        if target.break_meter <= finish_threshold:
            boosted_break = ceil_int(break_damage * RAVAGE_BREAK_FINISH_MULTIPLIER)
            if boosted_break > break_damage:
                state.logger.log(state.round_number, f"{source.name}'s Ravage posture bears down on the break line.")
                break_damage = boosted_break

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
        if source.team == "player" and target.team == "enemy":
            handle_kings_wager_execution(state, source, target)
        state.check_end()

    # Status application after damage, if target survived.
    if status_to_apply and target.alive():
        status_name, duration, chance = status_to_apply
        equipment_modifiers = calculate_equipment_modifiers(source, action_id=skill.effect_id, skill=skill)
        final_chance = chance
        if source.posture == "focus":
            final_chance += 20
        if is_affinity_advantage(skill.affinity, target.affinity):
            final_chance += 15
        if is_affinity_disadvantage(skill.affinity, target.affinity):
            final_chance -= 15
        final_chance += equipment_modifiers.status_success_bonus
        final_chance += black_vial_status_bonus(source)
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

    if source.team == "player" and is_offensive_skill(skill):
        handle_mooncleave_on_result(state, source, result)
        if result.get("hit_outcome") in {"hit", "graze"}:
            handle_anklet_refund_on_result(state, source, result)
            consume_black_vial_stacks(state, source)
            if bool(source.metadata.get("blood_vow_status_ready", False)) and target.alive() and result.get("status_applied") is None:
                target.add_condition("hex", BLOOD_VOW_STATUS_DURATION)
                result["status_applied"] = "hex"
                state.logger.log(state.round_number, f"{target.name} is hexed by Blood Vow.")

    if source.next_attack_power_bonus and skill.kind not in {"support", "defense", "utility", "stance", "self_buff"}:
        source.next_attack_power_bonus = 0
        state.logger.log(state.round_number, f"{source.name}'s Blood Oath surge is consumed.")
    if source.team == "player" and is_offensive_skill(skill):
        consume_next_attack_accuracy_modifiers(source)
        consume_single_use_offense_flags(source)

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


def actor_has_relic(actor: Combatant, relic_id: str) -> bool:
    return relic_id in equipped_relic_ids(actor)


def battle_has_potion_upgrade(state: BattleState, upgrade_id: str) -> bool:
    return upgrade_id in state.potion_upgrade_ids


def healing_potion_capacity(state: BattleState) -> int:
    capacity = DEFAULT_HEALING_POTIONS_PER_RUN
    if battle_has_potion_upgrade(state, "potion_capacity_plus_one"):
        capacity += POTION_UPGRADE_CAPACITY_BONUS
    return max(1, capacity)


def poisoned_chalice_penalty_mult(state: BattleState) -> float:
    return CHALICE_TOLERANCE_PENALTY_MULT if battle_has_potion_upgrade(state, "chalice_tolerance") else 1.0


def actor_has_mooncleave_weapon(actor: Combatant) -> bool:
    return actor_has_item_equipped(actor, "mooncleave_sword")


def actor_has_fracture_shield(actor: Combatant) -> bool:
    return actor_has_item_equipped(actor, "fracture_shield")


def actor_has_anklet_bell(actor: Combatant) -> bool:
    return actor_has_relic(actor, "anklet_bell_in_rain")


def restore_break_stability(actor: Combatant, amount: int) -> int:
    if amount <= 0:
        return 0
    before = actor.break_meter
    actor.break_meter = min(actor.max_break, actor.break_meter + amount)
    return actor.break_meter - before


def current_precision_carry_bonus(actor: Combatant) -> int:
    return int(actor.metadata.get("next_attack_precision_bonus", 0))


def mooncleave_crit_bonus(actor: Combatant) -> int:
    if not actor_has_mooncleave_weapon(actor):
        return 0
    stacks = clamp_int(int(actor.metadata.get("mooncleave_stacks", 0)), 0, MOONCLEAVE_MAX_STACKS)
    return stacks * MOONCLEAVE_CRIT_BONUS_PER_STACK


def black_vial_damage_multiplier(actor: Combatant) -> float:
    if not actor_has_relic(actor, "black_vial_cord"):
        return 1.0
    stacks = clamp_int(int(actor.metadata.get("black_vial_stacks", 0)), 0, BLACK_VIAL_MAX_STACKS)
    return 1.0 + (stacks * BLACK_VIAL_DAMAGE_BONUS_PER_STACK)


def black_vial_status_bonus(actor: Combatant) -> int:
    if not actor_has_relic(actor, "black_vial_cord"):
        return 0
    stacks = clamp_int(int(actor.metadata.get("black_vial_stacks", 0)), 0, BLACK_VIAL_MAX_STACKS)
    return stacks * BLACK_VIAL_STATUS_BONUS_PER_STACK


def grant_black_vial_stacks(state: BattleState, actor: Combatant, amount: int, source_text: str) -> None:
    if amount <= 0 or not actor_has_relic(actor, "black_vial_cord"):
        return
    before = clamp_int(int(actor.metadata.get("black_vial_stacks", 0)), 0, BLACK_VIAL_MAX_STACKS)
    after = clamp_int(before + amount, 0, BLACK_VIAL_MAX_STACKS)
    if after <= before:
        return
    actor.metadata["black_vial_stacks"] = after
    state.logger.log(state.round_number, f"Black Vial Cord tightens from {source_text}: {after}/{BLACK_VIAL_MAX_STACKS}.")


def consume_black_vial_stacks(state: BattleState, actor: Combatant) -> None:
    stacks = clamp_int(int(actor.metadata.pop("black_vial_stacks", 0)), 0, BLACK_VIAL_MAX_STACKS)
    if stacks > 0:
        state.logger.log(state.round_number, f"Black Vial power spills into {actor.name}'s strike and is spent.")


def battle_actor_status_lines(state: BattleState, actor: Combatant) -> List[str]:
    lines: List[str] = []
    if actor_has_mooncleave_weapon(actor):
        stacks = clamp_int(int(actor.metadata.get("mooncleave_stacks", 0)), 0, MOONCLEAVE_MAX_STACKS)
        lines.append(f"Mooncleave: +{stacks * MOONCLEAVE_CRIT_BONUS_PER_STACK}% crit ({stacks}/{MOONCLEAVE_MAX_STACKS})")
    if actor_has_relic(actor, "black_vial_cord"):
        stacks = clamp_int(int(actor.metadata.get("black_vial_stacks", 0)), 0, BLACK_VIAL_MAX_STACKS)
        lines.append(f"Black Vial: {stacks}/{BLACK_VIAL_MAX_STACKS}")
    if actor_has_relic(actor, "kings_wager"):
        counter = clamp_int(int(actor.metadata.get("kings_wager_executions", 0)), 0, KINGS_WAGER_EXECUTION_THRESHOLD)
        lines.append(f"King's Wager: {counter}/{KINGS_WAGER_EXECUTION_THRESHOLD}")
    composure_turns = clamp_int(
        int(actor.metadata.get("high_composure_turns_this_combat", 0)),
        0,
        TRANCE_REQUIRED_HIGH_COMPOSURE_TURNS,
    )
    if int(actor.metadata.get("evasion_penalty_until_next_turn", 0)) > 0 or int(actor.metadata.get("pending_poisoned_chalice_accuracy_penalty", 0)) > 0:
        lines.append(
            f"Poisoned Chalice penalty: evade -{int(actor.metadata.get('evasion_penalty_until_next_turn', 0))}, "
            f"next-turn accuracy -{int(actor.metadata.get('pending_poisoned_chalice_accuracy_penalty', 0))}"
        )
    if float(actor.metadata.get("next_healing_multiplier_bonus", 0.0)) > 0:
        lines.append(f"Next heal +{int(round(float(actor.metadata.get('next_healing_multiplier_bonus', 0.0)) * 100))}%")
    trance_used = bool(actor.metadata.get("trance_used_this_combat", False))
    lines.append(
        f"Trance: {'spent' if trance_used else f'{composure_turns}/{TRANCE_REQUIRED_HIGH_COMPOSURE_TURNS} high-Composure turns'} | "
        f"Spotlight {state.spotlight}/{state.spotlight_max}"
    )
    return lines


def reset_actor_combat_metadata(actor: Combatant) -> None:
    for key in (
        "high_composure_turns_this_combat",
        "trance_used_this_combat",
        "backflip_uses_this_combat",
        "shield_oath_cooldown",
        "shield_oath_break_bonus_mult",
        "mooncleave_stacks",
        "black_vial_stacks",
        "anklet_refund_primed",
        "anklet_refund_used_this_turn",
        "next_attack_precision_bonus",
        "next_healing_multiplier_bonus",
        "pending_poisoned_chalice_accuracy_penalty",
        "turn_accuracy_penalty",
        "poisoned_chalice_dot",
        "evasion_penalty_until_next_turn",
        "defensive_technique_used_turn",
        "regain_balance_used_turn",
        "fracture_shield_overflow_used_turn",
        "blood_vow_ready",
        "blood_vow_status_ready",
        "current_action_accuracy_modifier",
        "defensive_reaction_bonus_until_next_turn",
    ):
        actor.metadata.pop(key, None)
    actor.remove_condition("blood_vow")


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


def reaction_unavailable_reason(target: Combatant, reaction: str) -> Optional[str]:
    if reaction == "guard" and bool(target.metadata.get("cannot_guard_next_turn", False)):
        return "Guard is disabled until your next turn."
    if reaction == "parry" and bool(target.metadata.get("cannot_parry_next_turn", False)):
        return "Parry is disabled until your next turn."
    return None


def choose_reaction(
    state: BattleState,
    target: Combatant,
    attacker: Combatant,
    skill: Skill,
    incoming_tags: Sequence[str] = (),
) -> str:
    resolved_tags = tuple(str(tag) for tag in incoming_tags)
    has_pressure_tags = any(tag in POSITION_PUNISH_TAGS for tag in resolved_tags)
    allowed_reactions = [reaction for reaction in ("guard", "dodge", "parry") if reaction_unavailable_reason(target, reaction) is None]
    if not allowed_reactions:
        allowed_reactions = ["dodge"]
    if not state.interactive:
        if target.position == "pressing":
            if "dodge" in allowed_reactions and target.guard <= 8:
                return "dodge"
            if "parry" in allowed_reactions and has_pressure_tags:
                return "parry"
        if target.position == "withdrawn":
            if "dodge" in allowed_reactions and target.guard <= 8:
                return "dodge"
            if "guard" in allowed_reactions:
                return "guard"
        # Auto logic: bastion likes parry, low guard likes dodge, otherwise guard.
        if "parry" in allowed_reactions and (target.posture == "bastion" or target.has_condition("feint_circuit")):
            return "parry"
        if "dodge" in allowed_reactions and target.guard <= 8:
            return "dodge"
        if "guard" in allowed_reactions:
            return "guard"
        return allowed_reactions[0]

    while True:
        print(f"\nReaction for {target.name}: [g]uard, [d]odge, [p]arry")
        tag_text = ", ".join(resolved_tags) if resolved_tags else "-"
        print(
            f"Incoming: {attacker.name} uses {skill.display_name} [{tag_text}]. "
            f"{target.name} posture={target.posture} pos={target.position}."
        )
        choice = input("> ").strip().lower()
        if choice in {"g", "guard", ""}:
            reason = reaction_unavailable_reason(target, "guard")
            if reason is None:
                return "guard"
            print(reason)
            continue
        if choice in {"d", "dodge"}:
            return "dodge"
        if choice in {"p", "parry"}:
            reason = reaction_unavailable_reason(target, "parry")
            if reason is None:
                return "parry"
            print(reason)
            continue
        print("Please type g, d, or p.")


def get_current_axis_inputs_for_reaction(state: BattleState, target: Combatant, incoming_skill: Skill) -> ResolvedInputs:
    return make_resolved_inputs(*current_node_axis_triplet(state), incoming_skill)


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
    equipment_modifiers = calculate_equipment_modifiers(target)
    defensive_guard_bonus = int(target.metadata.get("defensive_reaction_bonus_until_next_turn", 0))
    incoming_tags_tuple = tuple(str(tag) for tag in incoming_tags)
    tagged_pressure = any(tag in POSITION_PUNISH_TAGS for tag in incoming_tags_tuple)
    defensive_profile = resolve_defensive_read_profile(incoming_tags_tuple)
    read_tier = effective_defensive_read_tier(defensive_read, defensive_profile, reaction)

    if reaction == "guard":
        if inputs.power < GUARD_POWER_REQUIREMENT:
            target.metadata["bypass_guard_this_hit"] = True
            state.change_enemy_spotlight(1, f"{target.name} failed guard gate")
            logs.append(f"Guard gate failed: Power {inputs.power} < {GUARD_POWER_REQUIREMENT}.")
            return scale_reaction_failure_damage(state, attacker, incoming_damage), incoming_break, prevented, logs
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
        total_guard_bonus = equipment_modifiers.reaction_bonus + defensive_guard_bonus
        if total_guard_bonus > 0:
            hp_spill_mult *= max(0.70, 1.0 - (total_guard_bonus / 100.0))
        # Guard sends damage into guard first, but any spill to HP is reduced by spill multiplier.
        overflow = 0
        if target.guard > 0:
            overflow = max(0, incoming_damage - (target.guard + max(0, equipment_modifiers.guard_bonus)))
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
        maybe_grant_bastion_guard_reward(state, target)
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
                scale_reaction_failure_damage(state, attacker, ceil_int(incoming_damage * 1.20)),
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
        chance += int(target.metadata.get("evasion_bonus_until_next_turn", 0))
        chance -= int(target.metadata.get("evasion_penalty_until_next_turn", 0))
        chance += equipment_modifiers.evasion_bonus
        chance += equipment_modifiers.reaction_bonus
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
        return scale_reaction_failure_damage(state, attacker, reduced), ceil_int(incoming_break * failed_break_mult), prevented, logs

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
            scale_reaction_failure_damage(state, attacker, ceil_int(incoming_damage * 1.35)),
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
            scale_reaction_failure_damage(state, attacker, ceil_int(incoming_damage * 1.35)),
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
    chance += equipment_modifiers.reaction_bonus
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
    return scale_reaction_failure_damage(state, attacker, ceil_int(incoming_damage * 1.15)), incoming_break + 6, prevented, logs


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


def current_node_axis_triplet(state: BattleState) -> Tuple[int, int, int]:
    raw = state.node_axis_scores
    return (
        clamp_int(int(raw.get("power", DEFAULT_AXIS_TRIPLET[0])), 0, 100),
        clamp_int(int(raw.get("precision", DEFAULT_AXIS_TRIPLET[1])), 0, 100),
        clamp_int(int(raw.get("composure", DEFAULT_AXIS_TRIPLET[2])), 0, 100),
    )


def player_action_input_defaults(state: BattleState) -> Tuple[int, int, int]:
    if state.last_player_inputs != DEFAULT_AXIS_TRIPLET:
        return state.last_player_inputs
    return current_node_axis_triplet(state)


def power_damage_multiplier(power: int) -> float:
    return clamp(
        1.0 + ((clamp_int(power, 0, 100) - 50) * POWER_DAMAGE_MULT_PER_POINT),
        POWER_DAMAGE_MULT_MIN,
        POWER_DAMAGE_MULT_MAX,
    )


def power_break_multiplier(power: int) -> float:
    return clamp(
        1.0 + ((clamp_int(power, 0, 100) - 50) * POWER_BREAK_MULT_PER_POINT),
        POWER_BREAK_MULT_MIN,
        POWER_BREAK_MULT_MAX,
    )


def precision_hit_bonus(precision: int) -> float:
    return (clamp_int(precision, 0, 100) - 50) * PRECISION_HIT_BONUS_PER_POINT


def precision_crit_bonus(precision: int) -> float:
    return clamp(
        max(0.0, (clamp_int(precision, 0, 100) - 50) * PRECISION_CRIT_BONUS_PER_POINT),
        0.0,
        PRECISION_MAX_CRIT_BONUS,
    )


def composure_to_ap(composure: int) -> int:
    value = clamp_int(composure, 0, 100)
    if value < 40:
        return 1
    if value < 60:
        return 2
    if value < 80:
        return 3
    if value < 95:
        return 4
    return 5


def action_skill_for_actor(actor: Combatant, action: BattleActionDef) -> Skill:
    return Skill(
        skill_id=action.action_id,
        display_name=action.name,
        owner=actor.entity_id,
        kind=action.kind,
        affinity=actor.affinity if action.affinity is None else action.affinity,
        target=action.target,
        spotlight_cost=0,
        primary_scale=action.primary_scale,
        secondary_scale=action.secondary_scale,
        damage_tier=action.damage_tier,
        break_tier=action.break_tier,
        effect_id=action.action_id,
        tags=action.tags,
    )


def default_turn_skill(actor: Combatant) -> Skill:
    for skill_id in actor.skills:
        skill = SKILLS.get(skill_id)
        if skill is not None and is_offensive_skill(skill):
            return skill
    return SKILLS["standard_strike"]


def turn_inputs_for_actor(state: BattleState, actor: Combatant) -> ResolvedInputs:
    inputs = actor.metadata.get("turn_inputs")
    if isinstance(inputs, ResolvedInputs):
        return inputs
    fallback_skill = default_turn_skill(actor)
    return make_resolved_inputs(*current_node_axis_triplet(state), fallback_skill)


def get_turn_axis_scores(state: BattleState, actor: Combatant, interactive: bool) -> ResolvedInputs:
    fallback_skill = default_turn_skill(actor)
    if actor.team == "player" and interactive:
        defaults = player_action_input_defaults(state)
        resolved = prompt_triplet(defaults, fallback_skill)
    else:
        resolved = make_resolved_inputs(*current_node_axis_triplet(state), fallback_skill)
    state.last_player_inputs = (resolved.power, resolved.precision, resolved.composure)
    return resolved


def actor_current_ap(actor: Combatant) -> int:
    return max(0, int(actor.metadata.get("current_ap", 0)))


def actor_starting_ap(actor: Combatant) -> int:
    return max(0, int(actor.metadata.get("starting_ap", 0)))


def start_player_turn_ap(state: BattleState, actor: Combatant, axis_scores: ResolvedInputs) -> int:
    pending_bonus = clamp_int(int(actor.metadata.pop("next_turn_ap_bonus", 0)), 0, NEXT_TURN_AP_BONUS_CAP)
    equipment_bonus = max(0, calculate_equipment_modifiers(actor).ap_bonus)
    starting_ap = min(MAX_STARTING_AP, composure_to_ap(axis_scores.composure) + pending_bonus + equipment_bonus)
    if axis_scores.composure >= 80:
        actor.metadata["high_composure_turns_this_combat"] = int(actor.metadata.get("high_composure_turns_this_combat", 0)) + 1
    actor.metadata["turn_inputs"] = axis_scores
    actor.metadata["last_inputs"] = axis_scores
    actor.metadata["turn_power"] = axis_scores.power
    actor.metadata["turn_precision"] = axis_scores.precision
    actor.metadata["turn_composure"] = axis_scores.composure
    actor.metadata["starting_ap"] = starting_ap
    actor.metadata["current_ap"] = starting_ap
    actor.metadata["used_light_attack_this_turn"] = False
    if pending_bonus > 0:
        state.logger.log(state.round_number, f"{actor.name} cashes in +{pending_bonus} AP from last turn's setup.")
    if equipment_bonus > 0:
        state.logger.log(state.round_number, f"{actor.name}'s equipment adds +{equipment_bonus} AP.")
    return starting_ap


def spend_actor_ap(actor: Combatant, amount: int) -> None:
    actor.metadata["current_ap"] = max(0, actor_current_ap(actor) - max(0, int(amount)))


def set_actor_ap(actor: Combatant, amount: int) -> None:
    actor.metadata["current_ap"] = max(0, int(amount))


def action_accuracy_modifier(actor: Combatant) -> int:
    return (
        int(actor.metadata.get("next_attack_accuracy_bonus", 0))
        - int(actor.metadata.get("next_attack_accuracy_penalty", 0))
        - int(actor.metadata.get("turn_accuracy_penalty", 0))
        + int(actor.metadata.get("current_action_accuracy_modifier", 0))
    )


def consume_next_attack_accuracy_modifiers(actor: Combatant) -> None:
    actor.metadata.pop("next_attack_accuracy_bonus", None)
    actor.metadata.pop("next_attack_accuracy_penalty", None)
    actor.metadata.pop("next_attack_precision_bonus", None)
    actor.metadata.pop("current_action_accuracy_modifier", None)


def consume_single_use_offense_flags(actor: Combatant) -> None:
    actor.metadata.pop("blood_vow_action_active", None)
    actor.metadata.pop("blood_vow_status_ready", None)
    actor.remove_condition("blood_vow")


def healing_effect_multiplier(state: BattleState, actor: Combatant, action_id: str) -> tuple[float, int]:
    equipment_modifiers = calculate_equipment_modifiers(actor, action_id=action_id)
    multiplier = equipment_modifiers.healing_multiplier
    flat_bonus = equipment_modifiers.potion_heal_bonus if action_id in {"use_healing_potion", "poisoned_chalice"} else 0
    if action_id in {"use_healing_potion", "poisoned_chalice"} and battle_has_potion_upgrade(state, "stronger_potions"):
        multiplier *= POTION_UPGRADE_STRONGER_MULT
    next_bonus = max(0.0, float(actor.metadata.pop("next_healing_multiplier_bonus", 0.0)))
    if next_bonus > 0:
        multiplier *= 1.0 + next_bonus
        state.logger.log(state.round_number, f"{actor.name}'s next healing bonus is consumed.")
    return multiplier, flat_bonus


def apply_healing_effect(
    state: BattleState,
    healer: Combatant,
    target: Combatant,
    base_amount: int,
    source_text: str,
    action_id: str,
) -> int:
    multiplier, flat_bonus = healing_effect_multiplier(state, healer, action_id)
    amount = max(1, ceil_int(base_amount * multiplier) + flat_bonus)
    before = target.hp
    target.hp = min(target.max_hp, target.hp + amount)
    restored = target.hp - before
    state.logger.log(state.round_number, f"{target.name} restores {restored} HP from {source_text}.")
    return restored


def apply_potion_side_effects(
    state: BattleState,
    actor: Combatant,
    source_text: str,
    black_vial_stacks: int,
) -> None:
    if battle_has_potion_upgrade(state, "guarding_draught"):
        gained = actor.restore_guard(ceil_int(actor.max_guard * POTION_UPGRADE_GUARD_RESTORE_RATIO))
        if gained > 0:
            state.logger.log(state.round_number, f"{source_text} restores {gained} guard to {actor.name}.")
    if battle_has_potion_upgrade(state, "spotlight_tonic"):
        state.change_spotlight(POTION_UPGRADE_SPOTLIGHT_GAIN, f"{actor.name} {source_text}")
    grant_black_vial_stacks(state, actor, black_vial_stacks, source_text)


def consume_healing_potion(
    state: BattleState,
    actor: Combatant,
    source_text: str,
    black_vial_stacks: int = 1,
) -> int:
    if state.healing_potions <= 0:
        return 0
    base_amount = max(1, ceil_int(actor.max_hp * HEALING_POTION_HEAL_RATIO))
    restored = apply_healing_effect(state, actor, actor, base_amount, source_text, action_id="use_healing_potion")
    state.healing_potions = max(0, state.healing_potions - 1)
    apply_potion_side_effects(state, actor, source_text, black_vial_stacks)
    state.logger.log(
        state.round_number,
        f"{actor.name} spends a potion. Potions left: {state.healing_potions}/{healing_potion_capacity(state)}.",
    )
    return restored


def consume_next_break_action_bonus(actor: Combatant) -> float:
    multiplier = max(1.0, float(actor.metadata.pop("shield_oath_break_bonus_mult", 1.0)))
    return multiplier


def consume_blood_vow_damage_bonus(actor: Combatant) -> float:
    if not bool(actor.metadata.pop("blood_vow_ready", False)):
        return 1.0
    actor.metadata["blood_vow_action_active"] = True
    actor.metadata["blood_vow_status_ready"] = True
    return BLOOD_VOW_DAMAGE_BONUS_MULT


def prime_anklet_refund(actor: Combatant) -> None:
    if actor_has_anklet_bell(actor):
        actor.metadata["anklet_refund_primed"] = True


def grant_next_attack_precision_bonus(state: BattleState, actor: Combatant, amount: int) -> None:
    if amount <= 0:
        return
    actor.metadata["next_attack_precision_bonus"] = max(
        amount,
        int(actor.metadata.get("next_attack_precision_bonus", 0)),
    )
    state.logger.log(state.round_number, f"{actor.name}'s next attack gains +{amount} virtual Precision.")


def choose_priority_enemy_target(state: BattleState, actor: Combatant) -> Optional[Combatant]:
    living_enemies = state.living_enemies()
    if not living_enemies:
        return None
    skill = default_turn_skill(actor)
    return auto_choose_target(state, actor, skill, living_enemies)


def choose_most_wounded_ally(state: BattleState, actor: Combatant) -> Combatant:
    allies = state.get_allies(actor)
    if not allies:
        return actor
    return min(allies, key=lambda unit: (unit.hp / max(unit.max_hp, 1), unit.hp))


def handle_kings_wager_execution(state: BattleState, actor: Combatant, target: Combatant) -> None:
    if not actor_has_relic(actor, "kings_wager"):
        return
    if not bool(target.metadata.get("counts_for_execution", True)):
        return
    gained = KINGS_WAGER_BOSS_EXECUTION_VALUE if target.is_boss else 1
    counter = max(0, int(actor.metadata.get("kings_wager_executions", 0))) + gained
    if counter >= KINGS_WAGER_EXECUTION_THRESHOLD:
        actor.metadata["kings_wager_executions"] = 0
        for ally in state.living_players():
            ally.hp = ally.max_hp
        state.logger.log(state.round_number, "King's Wager pays out - the whole party is restored.")
        return
    actor.metadata["kings_wager_executions"] = counter
    state.logger.log(state.round_number, f"King's Wager deepens: {counter}/{KINGS_WAGER_EXECUTION_THRESHOLD}.")


def handle_mooncleave_on_result(state: BattleState, actor: Combatant, result: Dict[str, object]) -> None:
    if not actor_has_mooncleave_weapon(actor):
        return
    if result.get("crit"):
        actor.metadata["mooncleave_stacks"] = 0
        state.logger.log(state.round_number, "Mooncleave releases on a critical hit.")
        return
    if result.get("hit_outcome") not in {"hit", "graze"}:
        return
    before = clamp_int(int(actor.metadata.get("mooncleave_stacks", 0)), 0, MOONCLEAVE_MAX_STACKS)
    after = clamp_int(before + 1, 0, MOONCLEAVE_MAX_STACKS)
    if after > before:
        actor.metadata["mooncleave_stacks"] = after
        state.logger.log(state.round_number, f"Mooncleave sharpens: crit chance rises to +{after * MOONCLEAVE_CRIT_BONUS_PER_STACK}%.")


def handle_anklet_refund_on_result(state: BattleState, actor: Combatant, result: Dict[str, object]) -> None:
    if not actor_has_anklet_bell(actor):
        return
    if not bool(actor.metadata.get("anklet_refund_primed", False)):
        return
    if bool(actor.metadata.get("anklet_refund_used_this_turn", False)):
        return
    if result.get("hit_outcome") not in {"hit", "graze"}:
        return
    actor.metadata["anklet_refund_used_this_turn"] = True
    actor.metadata["anklet_refund_primed"] = False
    refund_cap = actor_starting_ap(actor) + ANKLET_AP_REFUND_EXTRA_CAP
    actor.metadata["current_ap"] = min(refund_cap, actor_current_ap(actor) + ANKLET_AP_REFUND)
    state.logger.log(state.round_number, f"The anklet bell keeps time: {ANKLET_AP_REFUND} AP returns.")
    if result.get("crit"):
        grant_next_attack_precision_bonus(state, actor, ANKLET_PRECISION_CARRY_BONUS)


def default_auto_loadout(state: BattleState) -> List[str]:
    actor_ids = {player.entity_id for player in state.players}
    if len(actor_ids) == 1:
        solo_actor = next(iter(actor_ids))
        solo_defaults = {
            "vanguard": ["charge_slash", "shield_oath", "defensive_technique"],
            "duelist": ["double_strike", "razor_encore", "backflip"],
            "cantor": ["quiet_benediction", "regain_balance", "backflip"],
            "ranger": ["backstep_slash", "rain_mark", "backflip"],
            "penitent": ["poisoned_chalice", "blood_vow", "backflip"],
        }
        if solo_actor in solo_defaults:
            return solo_defaults[solo_actor]

    recommended: List[str] = []
    if "vanguard" in actor_ids:
        recommended.extend(["charge_slash", "shield_oath"])
    if "duelist" in actor_ids:
        recommended.extend(["double_strike", "razor_encore"])
    if "cantor" in actor_ids:
        recommended.append("quiet_benediction")
    if "ranger" in actor_ids:
        recommended.extend(["backstep_slash", "rain_mark"])
    if "penitent" in actor_ids:
        recommended.extend(["poisoned_chalice", "blood_vow"])
    recommended.extend(["defensive_technique", "regain_balance", "backflip", "trance", "feint_rush"])
    return list(dict.fromkeys(recommended))


def ensure_battle_loadout(state: BattleState) -> None:
    deduped_existing = [action_id for action_id in state.selected_extra_actions if action_id in BATTLE_ACTIONS]
    deduped_existing = list(dict.fromkeys(deduped_existing))
    if len(deduped_existing) == EXTRA_ACTION_LOADOUT_SLOTS:
        state.selected_extra_actions = deduped_existing
        return
    state.selected_extra_actions = []

    default_ids = [action_id for action_id in default_auto_loadout(state) if action_id in BATTLE_ACTIONS]
    if not state.interactive:
        state.selected_extra_actions = default_ids[:EXTRA_ACTION_LOADOUT_SLOTS]
        loadout_text = ", ".join(BATTLE_ACTIONS[action_id].name for action_id in state.selected_extra_actions)
        if loadout_text:
            state.logger.log(state.round_number, f"Battle loadout: {loadout_text}.")
        return

    print("\nChoose 3 extra actions for this battle.")
    print("Press Enter for the recommended loadout shown below.")
    for idx, action_id in enumerate(EXTRA_BATTLE_ACTION_IDS, start=1):
        action = BATTLE_ACTIONS[action_id]
        class_text = ""
        if action.requires_class:
            class_text = " [" + "/".join(class_id.title() for class_id in action.requires_class) + " only]"
        print(f"  {idx}. {action.name:<16} AP {action.ap_cost} - {action.description}{class_text}")
    recommended = ", ".join(BATTLE_ACTIONS[action_id].name for action_id in default_ids[:EXTRA_ACTION_LOADOUT_SLOTS])
    print(f"Recommended: {recommended}")

    while True:
        raw = input("> ").strip()
        if raw == "":
            selected = default_ids[:EXTRA_ACTION_LOADOUT_SLOTS]
            break
        parts = raw.replace(",", " ").split()
        if len(parts) != EXTRA_ACTION_LOADOUT_SLOTS:
            print(f"Choose exactly {EXTRA_ACTION_LOADOUT_SLOTS} action numbers.")
            continue
        try:
            indices = [int(part) for part in parts]
        except ValueError:
            print("Enter action numbers such as: 1 2 4")
            continue
        if len(set(indices)) != EXTRA_ACTION_LOADOUT_SLOTS:
            print("Choose 3 different actions.")
            continue
        if not all(1 <= idx <= len(EXTRA_BATTLE_ACTION_IDS) for idx in indices):
            print("One or more action numbers are out of range.")
            continue
        selected = [EXTRA_BATTLE_ACTION_IDS[idx - 1] for idx in indices]
        break

    state.selected_extra_actions = selected
    loadout_text = ", ".join(BATTLE_ACTIONS[action_id].name for action_id in state.selected_extra_actions)
    state.logger.log(state.round_number, f"Battle loadout: {loadout_text}.")


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
        last_spotlight_round = int(actor.metadata.get("flow_spotlight_round", -FLOW_SPOTLIGHT_COOLDOWN_ROUNDS))
        cleansed = cleanse_one_debuff(state, actor)
        if not cleansed and (state.round_number - last_spotlight_round) >= FLOW_SPOTLIGHT_COOLDOWN_ROUNDS:
            actor.metadata["flow_spotlight_round"] = state.round_number
            state.change_spotlight(1, f"{actor.name} entered Flow")
    if actor.entity_id == "vanguard" and actor.posture in {"bastion", "ravage"}:
        restored = actor.restore_guard(max(1, actor.max_guard // 10))
        if restored:
            state.logger.log(state.round_number, f"{actor.name} restores {restored} guard from passive.")


def cleanse_one_debuff(state: BattleState, actor: Combatant, source_text: str = "Flow") -> bool:
    for status in MINOR_NEGATIVE_STATUSES:
        if actor.has_condition(status):
            actor.remove_condition(status)
            state.logger.log(state.round_number, f"{actor.name} cleanses {status} via {source_text}.")
            return True
    return False


def maybe_grant_bastion_guard_reward(state: BattleState, actor: Combatant) -> None:
    if actor.posture != "bastion":
        return
    if int(actor.metadata.get("bastion_guard_reward_round", -1)) == state.round_number:
        return
    actor.metadata["bastion_guard_reward_round"] = state.round_number
    state.change_spotlight(1, f"{actor.name} Bastion guard")
    state.logger.log(state.round_number, f"{actor.name} turns a Bastion guard into fresh Spotlight.")


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


def visible_battle_actions_for_actor(state: BattleState, actor: Combatant) -> List[BattleActionDef]:
    actions: List[BattleActionDef] = [BATTLE_ACTIONS[action_id] for action_id in BASIC_BATTLE_ACTION_IDS]
    for action_id in state.selected_extra_actions:
        action = BATTLE_ACTIONS.get(action_id)
        if action is None:
            continue
        if action.requires_class and actor.entity_id not in action.requires_class:
            continue
        actions.append(action)
    return actions


def action_ap_label(actor: Combatant, action: BattleActionDef) -> str:
    if action.requires_full_ap:
        return "FULL AP"
    return f"{action.ap_cost} AP"


def get_action_lock_reason(state: BattleState, actor: Combatant, action: BattleActionDef) -> Optional[str]:
    if action.requires_class and actor.entity_id not in action.requires_class:
        class_text = "/".join(class_id.title() for class_id in action.requires_class)
        return f"{class_text} only."
    if action.action_id in {"use_healing_potion", "poisoned_chalice"} and state.healing_potions <= 0:
        return "No healing potions remaining."
    if action.action_id == "feint_rush" and not bool(actor.metadata.get("used_light_attack_this_turn", False)):
        return "Requires Light Attack first."
    if action.action_id == "trance":
        if bool(actor.metadata.get("trance_used_this_combat", False)):
            return "Once per combat."
        if int(actor.metadata.get("high_composure_turns_this_combat", 0)) < TRANCE_REQUIRED_HIGH_COMPOSURE_TURNS:
            return f"Requires Composure 80+ on {TRANCE_REQUIRED_HIGH_COMPOSURE_TURNS} turns."
        if state.spotlight <= 0:
            return "Requires at least 1 Spotlight."
    if action.action_id == "backflip" and int(actor.metadata.get("backflip_uses_this_combat", 0)) >= BACKFLIP_MAX_USES_PER_COMBAT:
        return f"Max {BACKFLIP_MAX_USES_PER_COMBAT} uses per combat."
    if action.action_id == "defensive_technique" and bool(actor.metadata.get("defensive_technique_used_turn", False)):
        return "Once per turn."
    if action.action_id == "regain_balance" and bool(actor.metadata.get("regain_balance_used_turn", False)):
        return "Once per turn."
    if action.action_id == "shield_oath":
        if not actor_has_shield_equipped(actor):
            return "Requires a shield."
        cooldown = max(0, int(actor.metadata.get("shield_oath_cooldown", 0)))
        if cooldown > 0:
            return f"Recharging for {cooldown} more turn(s)."
    if action.action_id == "blood_vow" and (bool(actor.metadata.get("blood_vow_ready", False)) or actor.has_condition("blood_vow")):
        return "Blood Vow is already active."
    if action.requires_full_ap and actor_current_ap(actor) != actor_starting_ap(actor):
        return "Requires full AP."
    if actor_current_ap(actor) < action.ap_cost:
        return f"Requires {action.ap_cost} AP."
    return None


def actor_can_use_action(state: BattleState, actor: Combatant, action: BattleActionDef) -> bool:
    return get_action_lock_reason(state, actor, action) is None


def unavailable_battle_action_reason(state: BattleState, actor: Combatant, action: BattleActionDef) -> Optional[str]:
    return get_action_lock_reason(state, actor, action)


def choose_player_battle_action(state: BattleState, actor: Combatant) -> Optional[BattleActionDef]:
    actions = visible_battle_actions_for_actor(state, actor)
    while True:
        print(f"\n{actor.name}'s turn. Current AP: {actor_current_ap(actor)}/{actor_starting_ap(actor)}")
        print(f"Healing Potions: {state.healing_potions}/{healing_potion_capacity(state)}")
        for line in battle_actor_status_lines(state, actor):
            print(f"  {line}")
        for idx, action in enumerate(actions, start=1):
            reason = unavailable_battle_action_reason(state, actor, action)
            locked_text = f" (locked: {reason})" if reason else ""
            print(f"  {idx}. {action.name:<18} [{action_ap_label(actor, action)}] - {action.description}{locked_text}")
        print(f"  {len(actions) + 1}. End Turn")

        raw = input("> ").strip()
        if raw == "":
            return None
        try:
            choice = int(raw)
        except ValueError:
            print("Choose a number.")
            continue
        if choice == len(actions) + 1:
            return None
        if not (1 <= choice <= len(actions)):
            print("That number is out of range.")
            continue
        action = actions[choice - 1]
        reason = unavailable_battle_action_reason(state, actor, action)
        if reason is not None:
            print(reason)
            continue
        return action


def auto_choose_battle_action_and_targets(
    state: BattleState,
    actor: Combatant,
    inputs: ResolvedInputs,
) -> Tuple[Optional[BattleActionDef], List[Combatant]]:
    action_map = {action.action_id: action for action in visible_battle_actions_for_actor(state, actor)}
    living_enemies = state.living_enemies()
    if not living_enemies:
        return None, []

    def ready(action_id: str) -> bool:
        action = action_map.get(action_id)
        return action is not None and unavailable_battle_action_reason(state, actor, action) is None

    dangerous_target = max(
        living_enemies,
        key=lambda unit: (
            int(unit.is_boss),
            unit.hp + unit.guard + unit.break_meter,
            unit.max_hp,
        ),
    )

    if ready("use_healing_potion") and actor.hp <= ceil_int(actor.max_hp * 0.30):
        return action_map["use_healing_potion"], [actor]

    if ready("poisoned_chalice") and actor.hp <= ceil_int(actor.max_hp * 0.45):
        return action_map["poisoned_chalice"], [dangerous_target]

    if ready("trance") and (dangerous_target.is_boss or dangerous_target.hp <= ceil_int(dangerous_target.max_hp * 0.50)):
        return action_map["trance"], [dangerous_target]

    if ready("defensive_technique") and actor.guard <= ceil_int(actor.max_guard * 0.35):
        return action_map["defensive_technique"], [actor]

    if ready("regain_balance") and actor.break_meter <= ceil_int(actor.max_break * REGAIN_BALANCE_LOW_STABILITY_THRESHOLD):
        return action_map["regain_balance"], [actor]

    if ready("backflip") and (actor.hp <= ceil_int(actor.max_hp * 0.45) or actor.break_meter <= ceil_int(actor.max_break * 0.35)):
        return action_map["backflip"], [actor]

    if ready("quiet_benediction"):
        ally = choose_most_wounded_ally(state, actor)
        if (ally.max_hp - ally.hp) >= max(12, ceil_int(ally.max_hp * 0.18)):
            return action_map["quiet_benediction"], [actor]

    if ready("shield_oath") and actor.guard <= ceil_int(actor.max_guard * 0.65):
        return action_map["shield_oath"], [actor]

    if ready("rain_mark"):
        unmarked = next((unit for unit in living_enemies if not unit.has_condition("rain_mark")), dangerous_target)
        return action_map["rain_mark"], [unmarked]

    if ready("blood_vow") and actor.hp > max(12, ceil_int(actor.max_hp * 0.30)):
        return action_map["blood_vow"], [actor]

    if ready("charge_slash"):
        target = max(living_enemies, key=lambda unit: (unit.break_meter, unit.max_break, unit.hp))
        if target.break_meter >= max(8, ceil_int(target.max_break * 0.33)):
            return action_map["charge_slash"], [target]

    if ready("razor_encore"):
        return action_map["razor_encore"], [dangerous_target]

    if ready("double_strike"):
        skill = action_skill_for_actor(actor, action_map["double_strike"])
        target = auto_choose_target(state, actor, skill, living_enemies)
        return action_map["double_strike"], [target]

    if ready("heavy_attack") and inputs.power >= HEAVY_ATTACK_POWER_REQUIREMENT:
        skill = action_skill_for_actor(actor, action_map["heavy_attack"])
        target = auto_choose_target(state, actor, skill, living_enemies)
        return action_map["heavy_attack"], [target]

    if ready("light_attack"):
        skill = action_skill_for_actor(actor, action_map["light_attack"])
        target = auto_choose_target(state, actor, skill, living_enemies)
        return action_map["light_attack"], [target]

    return None, []


def choose_targets_for_battle_action(state: BattleState, actor: Combatant, action: BattleActionDef) -> List[Combatant]:
    if action.target == "self":
        return [actor]
    skill = action_skill_for_actor(actor, action)
    return choose_target(state, actor, skill)


def log_player_action_inputs_once(state: BattleState, actor: Combatant, inputs: ResolvedInputs, starting_ap: int) -> None:
    if int(actor.metadata.get("action_input_logged_round", -1)) == state.round_number:
        return
    actor.metadata["action_input_logged_round"] = state.round_number
    state.logger.log(
        state.round_number,
        f"Turn input: Power {inputs.power} / Precision {inputs.precision} / Composure {inputs.composure} -> "
        f"{inputs.posture.title()}, {starting_ap} AP",
    )


def prepare_attack_action(
    state: BattleState,
    actor: Combatant,
    action: BattleActionDef,
    inputs: ResolvedInputs,
    damage_multiplier: float = 1.0,
    break_multiplier: float = 1.0,
) -> Tuple[Skill, int, int]:
    skill = action_skill_for_actor(actor, action)
    equipment_modifiers = calculate_equipment_modifiers(actor, action_id=action.action_id, skill=skill)
    before_damage_mult, before_break_mult = process_relic_trigger(
        state=state,
        actor=actor,
        trigger="before_offense",
        skill=skill,
    )
    counterphrase_damage_mult, counterphrase_break_mult = consume_counterphrase_bonus(state, actor, skill)
    base_damage = max(0, DAMAGE_TIERS[skill.damage_tier] + equipment_modifiers.base_damage_bonus)
    base_break = max(0, BREAK_TIERS[skill.break_tier])
    blood_vow_damage_mult = consume_blood_vow_damage_bonus(actor)
    black_vial_mult = black_vial_damage_multiplier(actor)
    next_break_action_mult = consume_next_break_action_bonus(actor) if base_break > 0 else 1.0
    damage = ceil_int(
        base_damage
        * damage_multiplier
        * before_damage_mult
        * counterphrase_damage_mult
        * blood_vow_damage_mult
        * black_vial_mult
        * power_damage_multiplier(inputs.power)
        * equipment_modifiers.damage_multiplier
    )
    break_damage = ceil_int(
        base_break
        * break_multiplier
        * before_break_mult
        * counterphrase_break_mult
        * next_break_action_mult
        * power_break_multiplier(inputs.power)
        * equipment_modifiers.break_multiplier
    )
    state.logger.log(
        state.round_number,
        f"{actor.name} uses {action.name} "
        f"[P:{inputs.power}/{inputs.band_names['power']}, "
        f"R:{inputs.precision}/{inputs.band_names['precision']}, "
        f"C:{inputs.composure}/{inputs.band_names['composure']}]",
    )
    state.logger.log(
        state.round_number,
        f"Power output x{power_damage_multiplier(inputs.power):.2f} damage / "
        f"x{power_break_multiplier(inputs.power):.2f} break from Power {inputs.power}.",
    )
    if blood_vow_damage_mult > 1.0:
        state.logger.log(state.round_number, f"Blood Vow surges through {action.name}.")
    if black_vial_mult > 1.0:
        state.logger.log(state.round_number, f"Black Vial empowers {action.name} x{black_vial_mult:.2f}.")
    if next_break_action_mult > 1.0:
        state.logger.log(state.round_number, f"Shield Oath sharpens the next Break action x{next_break_action_mult:.2f}.")
    return skill, damage, break_damage


def heal_with_potion(state: BattleState, actor: Combatant) -> None:
    consume_healing_potion(state, actor, "Healing Potion", black_vial_stacks=1)
    finalize_action_resolution(state, actor, action_skill_for_actor(actor, BATTLE_ACTIONS["use_healing_potion"]))


def resolve_light_attack(state: BattleState, actor: Combatant, target: Combatant, inputs: ResolvedInputs) -> None:
    action = BATTLE_ACTIONS["light_attack"]
    skill, damage, break_damage = prepare_attack_action(state, actor, action, inputs)
    apply_damage_to_target(
        state=state,
        source=actor,
        target=target,
        damage=damage,
        break_damage=break_damage,
        skill=skill,
        can_crit=True,
    )
    actor.metadata["used_light_attack_this_turn"] = True
    finalize_offensive_resolution(state, actor, skill)


def resolve_heavy_attack(state: BattleState, actor: Combatant, target: Combatant, inputs: ResolvedInputs) -> None:
    action = BATTLE_ACTIONS["heavy_attack"]
    if inputs.power < HEAVY_ATTACK_POWER_REQUIREMENT:
        state.logger.log(state.round_number, "Heavy Attack falters: Power below 60.")
        expire_counterphrase_if_unused(state, actor, action_skill_for_actor(actor, action))
        return
    damage_multiplier = HEAVY_ATTACK_DAMAGE_MULTIPLIER
    break_multiplier = HEAVY_ATTACK_BREAK_MULTIPLIER
    if inputs.power >= HEAVY_ATTACK_POWER_SURGE_THRESHOLD:
        damage_multiplier *= HEAVY_ATTACK_POWER_SURGE_DAMAGE_MULT
        break_multiplier *= HEAVY_ATTACK_POWER_SURGE_BREAK_MULT
    skill, damage, break_damage = prepare_attack_action(state, actor, action, inputs, damage_multiplier=damage_multiplier, break_multiplier=break_multiplier)
    apply_damage_to_target(
        state=state,
        source=actor,
        target=target,
        damage=damage,
        break_damage=break_damage,
        skill=skill,
        can_crit=True,
        attack_tags=("heavy",),
    )
    finalize_offensive_resolution(state, actor, skill)


def resolve_feint_rush(state: BattleState, actor: Combatant) -> None:
    actor.metadata["next_attack_accuracy_bonus"] = max(int(actor.metadata.get("next_attack_accuracy_bonus", 0)), FEINT_RUSH_ACCURACY_BONUS)
    state.logger.log(state.round_number, "Feint Rush sets up the next strike: accuracy increased.")
    finalize_action_resolution(state, actor, action_skill_for_actor(actor, BATTLE_ACTIONS["feint_rush"]))


def resolve_double_strike(state: BattleState, actor: Combatant, target: Combatant, inputs: ResolvedInputs) -> None:
    action = BATTLE_ACTIONS["double_strike"]
    skill, damage, break_damage = prepare_attack_action(
        state,
        actor,
        action,
        inputs,
        damage_multiplier=DOUBLE_STRIKE_DAMAGE_MULTIPLIER,
        break_multiplier=DOUBLE_STRIKE_BREAK_MULTIPLIER,
    )
    hits_landed = 0
    for hit_index in range(1, 3):
        if not target.alive():
            break
        result = apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=damage,
            break_damage=break_damage,
            skill=skill,
            can_crit=True,
        ) or {}
        if result.get("hit_outcome") in {"hit", "graze"}:
            hits_landed += 1
        state.logger.log(state.round_number, f"Double Strike hit {hit_index}/2 resolves.")
    if hits_landed == 2 and target.alive():
        apply_break_damage(state, target, DOUBLE_STRIKE_BOTH_HITS_BREAK_BONUS)
        state.logger.log(state.round_number, "Double Strike piles on extra Break pressure.")
    actor.metadata["cannot_guard_next_turn"] = True
    actor.metadata["cannot_parry_next_turn"] = True
    state.logger.log(state.round_number, f"{actor.name} is left open: Guard and Parry are disabled until the next turn.")
    finalize_offensive_resolution(state, actor, skill)


def backstep_slash_evasion_bonus(actor: Combatant) -> int:
    if actor.entity_id == "ranger":
        return BACKSTEP_SLASH_RANGER_EVASION_BONUS
    return BACKSTEP_SLASH_DUELIST_EVASION_BONUS


def resolve_backstep_slash(state: BattleState, actor: Combatant, target: Combatant, inputs: ResolvedInputs) -> None:
    action = BATTLE_ACTIONS["backstep_slash"]
    skill, damage, break_damage = prepare_attack_action(
        state,
        actor,
        action,
        inputs,
        damage_multiplier=BACKSTEP_SLASH_DAMAGE_MULTIPLIER,
        break_multiplier=BACKSTEP_SLASH_DAMAGE_MULTIPLIER,
    )
    apply_damage_to_target(
        state=state,
        source=actor,
        target=target,
        damage=damage,
        break_damage=break_damage,
        skill=skill,
        can_crit=True,
    )
    actor.metadata["evasion_bonus_until_next_turn"] = max(
        int(actor.metadata.get("evasion_bonus_until_next_turn", 0)),
        backstep_slash_evasion_bonus(actor),
    )
    actor.metadata["next_attack_accuracy_penalty"] = max(
        int(actor.metadata.get("next_attack_accuracy_penalty", 0)),
        BACKSTEP_SLASH_ACCURACY_PENALTY,
    )
    prime_anklet_refund(actor)
    state.logger.log(
        state.round_number,
        f"Backstep Slash grants +{backstep_slash_evasion_bonus(actor)} dodge chance until the next turn, "
        f"but the next attack loses {BACKSTEP_SLASH_ACCURACY_PENALTY} hit chance.",
    )
    finalize_offensive_resolution(state, actor, skill)


def resolve_charge_slash(state: BattleState, actor: Combatant, target: Combatant, inputs: ResolvedInputs) -> None:
    action = BATTLE_ACTIONS["charge_slash"]
    had_staggered = target.has_condition("staggered")
    equipment_modifiers = calculate_equipment_modifiers(actor, action_id="charge_slash")
    guard_cost = max(0, CHARGE_SLASH_SELF_GUARD_COST + equipment_modifiers.self_guard_cost_delta)
    spent_guard = min(actor.guard, guard_cost)
    actor.guard = max(0, actor.guard - spent_guard)
    state.logger.log(state.round_number, f"{actor.name} spends {spent_guard} guard to wind up Charge Slash.")
    skill, damage, break_damage = prepare_attack_action(
        state,
        actor,
        action,
        inputs,
        damage_multiplier=CHARGE_SLASH_DAMAGE_MULTIPLIER,
        break_multiplier=CHARGE_SLASH_BREAK_MULTIPLIER,
    )
    result = apply_damage_to_target(
        state=state,
        source=actor,
        target=target,
        damage=damage,
        break_damage=break_damage,
        skill=skill,
        can_crit=True,
        attack_tags=("heavy", "burst_start"),
    ) or {}
    state.logger.log(state.round_number, "Charge Slash batters the enemy's Break.")
    if not had_staggered and target.has_condition("staggered"):
        actor.metadata["next_turn_ap_bonus"] = min(
            NEXT_TURN_AP_BONUS_CAP,
            max(int(actor.metadata.get("next_turn_ap_bonus", 0)), 1),
        )
        state.logger.log(state.round_number, "The enemy staggers - Vanguard gains +1 AP next turn.")
    finalize_offensive_resolution(state, actor, skill)


def resolve_trance(state: BattleState, actor: Combatant, target: Combatant, inputs: ResolvedInputs) -> None:
    action = BATTLE_ACTIONS["trance"]
    spotlight_spent = max(1, state.spotlight)
    state.change_spotlight(-spotlight_spent, f"{actor.name} Trance")
    actor.metadata["trance_used_this_combat"] = True
    state.logger.log(state.round_number, "Trance begins: Spotlight is burned into motion.")
    skill, base_damage, base_break = prepare_attack_action(
        state,
        actor,
        action,
        inputs,
        damage_multiplier=1.0 + (spotlight_spent * TRANCE_SPOTLIGHT_DAMAGE_BONUS_PER),
        break_multiplier=1.0 + (spotlight_spent * 0.02),
    )
    max_hits = TRANCE_BOSS_MAX_HITS if target.is_boss else TRANCE_NORMAL_MAX_HITS
    for hit_index in range(1, max_hits + 1):
        if not target.alive():
            break
        actor.metadata["current_action_accuracy_modifier"] = (spotlight_spent * TRANCE_SPOTLIGHT_HIT_BONUS) - (
            (hit_index - 1) * TRANCE_CHAIN_HIT_PENALTY_PER_HIT
        )
        hit_damage = base_damage
        if target.is_boss and hit_index > 1:
            hit_damage = ceil_int(base_damage * (TRANCE_BOSS_FOLLOWUP_DAMAGE_MULT ** (hit_index - 1)))
        result = apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=hit_damage,
            break_damage=base_break,
            skill=skill,
            can_crit=True,
            attack_tags=("combo", "heavy"),
        ) or {}
        if result.get("hit_outcome") not in {"hit", "graze"}:
            state.logger.log(state.round_number, f"Trance falters on hit {hit_index}.")
            break
        state.logger.log(state.round_number, f"Trance chain hit {hit_index} lands.")
    actor.metadata.pop("current_action_accuracy_modifier", None)
    finalize_offensive_resolution(state, actor, skill)


def resolve_poisoned_chalice(state: BattleState, actor: Combatant, target: Combatant, inputs: ResolvedInputs) -> None:
    action = BATTLE_ACTIONS["poisoned_chalice"]
    consume_healing_potion(state, actor, "Poisoned Chalice", black_vial_stacks=2)
    penalty_mult = poisoned_chalice_penalty_mult(state)
    evasion_penalty = ceil_int(POISONED_CHALICE_EVASION_PENALTY * penalty_mult)
    accuracy_penalty = ceil_int(POISONED_CHALICE_ACCURACY_PENALTY * penalty_mult)
    actor.metadata["evasion_penalty_until_next_turn"] = max(
        int(actor.metadata.get("evasion_penalty_until_next_turn", 0)),
        evasion_penalty,
    )
    actor.metadata["pending_poisoned_chalice_accuracy_penalty"] = max(
        int(actor.metadata.get("pending_poisoned_chalice_accuracy_penalty", 0)),
        accuracy_penalty,
    )
    boosted_dot = POISONED_CHALICE_MIN_DOT + ceil_int(inputs.power * 0.12)
    boosted_duration = POISONED_CHALICE_DURATION
    if bool(actor.metadata.get("blood_vow_ready", False)):
        boosted_dot += 2
        boosted_duration += 1
    skill, damage, break_damage = prepare_attack_action(
        state,
        actor,
        action,
        inputs,
        damage_multiplier=POISONED_CHALICE_DAMAGE_MULTIPLIER,
        break_multiplier=POISONED_CHALICE_DAMAGE_MULTIPLIER,
    )
    result = apply_damage_to_target(
        state=state,
        source=actor,
        target=target,
        damage=damage,
        break_damage=break_damage,
        skill=skill,
        can_crit=True,
        status_to_apply=("poisoned_chalice", boosted_duration, 90),
    ) or {}
    if result.get("status_applied") == "poisoned_chalice":
        target.metadata["poisoned_chalice_dot"] = boosted_dot
        state.logger.log(state.round_number, "The chalice strike poisons the opening.")
    state.logger.log(state.round_number, "Poisoned Chalice burns as it heals.")
    state.logger.log(state.round_number, "Next turn: evasion and accuracy are impaired.")
    finalize_offensive_resolution(state, actor, skill)


def resolve_backflip(state: BattleState, actor: Combatant) -> None:
    uses = int(actor.metadata.get("backflip_uses_this_combat", 0)) + 1
    actor.metadata["backflip_uses_this_combat"] = uses
    actor.metadata["evasion_bonus_until_next_turn"] = max(
        int(actor.metadata.get("evasion_bonus_until_next_turn", 0)),
        BACKFLIP_EVASION_BONUS,
    )
    recovered = restore_break_stability(actor, ceil_int(actor.max_break * BACKFLIP_BREAK_RECOVERY_RATIO))
    actor.metadata["next_healing_multiplier_bonus"] = max(
        float(actor.metadata.get("next_healing_multiplier_bonus", 0.0)),
        BACKFLIP_NEXT_HEALING_BONUS,
    )
    prime_anklet_refund(actor)
    state.logger.log(state.round_number, "Backflip resets the rhythm: evasion rises.")
    state.logger.log(state.round_number, f"Break pressure eases by {recovered}.")
    state.logger.log(state.round_number, "The next healing effect will be stronger.")
    finalize_action_resolution(state, actor, action_skill_for_actor(actor, BATTLE_ACTIONS["backflip"]))


def resolve_defensive_technique(state: BattleState, actor: Combatant) -> None:
    recovery_ratio = DEFENSIVE_TECHNIQUE_GUARD_RECOVERY_RATIO
    if actor.posture == "bastion":
        recovery_ratio += DEFENSIVE_TECHNIQUE_BASTION_BONUS
    if actor_has_shield_equipped(actor):
        recovery_ratio += DEFENSIVE_TECHNIQUE_SHIELD_BONUS
    if actor.entity_id == "vanguard" and actor_uses_one_handed_shield_setup(actor):
        recovery_ratio += DEFENSIVE_TECHNIQUE_VANGUARD_SHIELD_BONUS
    if actor_has_fracture_shield(actor):
        recovery_ratio *= FRACTURE_SHIELD_GUARD_RECOVERY_MULT
    attempted = ceil_int(actor.max_guard * recovery_ratio)
    before_guard = actor.guard
    gained = actor.restore_guard(attempted)
    actor.metadata["defensive_technique_used_turn"] = True
    actor.metadata["defensive_reaction_bonus_until_next_turn"] = max(
        int(actor.metadata.get("defensive_reaction_bonus_until_next_turn", 0)),
        DEFENSIVE_TECHNIQUE_REACTION_BONUS,
    )
    state.logger.log(state.round_number, f"Defensive Technique restores {gained} guard.")
    excess = max(0, before_guard + attempted - actor.max_guard)
    if actor_has_fracture_shield(actor) and excess > 0 and not bool(actor.metadata.get("fracture_shield_overflow_used_turn", False)):
        spill_target = choose_priority_enemy_target(state, actor)
        if spill_target is not None:
            actor.metadata["fracture_shield_overflow_used_turn"] = True
            spill_break = ceil_int(excess * FRACTURE_SHIELD_EXCESS_BREAK_RATIO)
            apply_break_damage(state, spill_target, spill_break)
            state.logger.log(state.round_number, "Fracture Shield turns excess Guard into Break pressure.")
    finalize_action_resolution(state, actor, action_skill_for_actor(actor, BATTLE_ACTIONS["defensive_technique"]))


def resolve_regain_balance(state: BattleState, actor: Combatant, inputs: ResolvedInputs) -> None:
    recovery_ratio = REGAIN_BALANCE_BREAK_RECOVERY_RATIO
    if actor.break_meter <= ceil_int(actor.max_break * REGAIN_BALANCE_LOW_STABILITY_THRESHOLD):
        recovery_ratio += REGAIN_BALANCE_LOW_STABILITY_BONUS
    if inputs.composure >= REGAIN_BALANCE_COMPOSURE_THRESHOLD:
        recovery_ratio += REGAIN_BALANCE_COMPOSURE_BONUS
    if actor.posture in {"flow", "bastion"}:
        recovery_ratio += REGAIN_BALANCE_STANCE_BONUS
    recovered = restore_break_stability(actor, ceil_int(actor.max_break * recovery_ratio))
    actor.metadata["regain_balance_used_turn"] = True
    state.logger.log(state.round_number, f"Regain Balance steadies the line and restores {recovered} Break.")
    finalize_action_resolution(state, actor, action_skill_for_actor(actor, BATTLE_ACTIONS["regain_balance"]))


def resolve_shield_oath(state: BattleState, actor: Combatant) -> None:
    gained = actor.restore_guard(ceil_int(actor.max_guard * SHIELD_OATH_GUARD_RECOVERY_RATIO))
    actor.metadata["shield_oath_break_bonus_mult"] = max(
        float(actor.metadata.get("shield_oath_break_bonus_mult", 1.0)),
        SHIELD_OATH_BREAK_BONUS_MULT,
    )
    actor.metadata["shield_oath_cooldown"] = SHIELD_OATH_COOLDOWN_TURNS
    state.logger.log(state.round_number, f"Shield Oath restores {gained} guard and strengthens the next Break action.")
    if actor.posture == "bastion":
        state.change_spotlight(1, f"{actor.name} Shield Oath")
    finalize_action_resolution(state, actor, action_skill_for_actor(actor, BATTLE_ACTIONS["shield_oath"]))


def resolve_razor_encore(state: BattleState, actor: Combatant, target: Combatant, inputs: ResolvedInputs) -> None:
    action = BATTLE_ACTIONS["razor_encore"]
    skill, damage, break_damage = prepare_attack_action(state, actor, action, inputs)
    result = apply_damage_to_target(
        state=state,
        source=actor,
        target=target,
        damage=damage,
        break_damage=break_damage,
        skill=skill,
        can_crit=True,
    ) or {}
    if result.get("crit") and target.alive():
        apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=ceil_int(damage * RAZOR_ENCORE_FOLLOWUP_DAMAGE_MULTIPLIER),
            break_damage=ceil_int(break_damage * RAZOR_ENCORE_FOLLOWUP_DAMAGE_MULTIPLIER),
            skill=skill,
            can_crit=True,
        )
        state.logger.log(state.round_number, "Razor Encore follows through on the critical opening.")
    actor.metadata["cannot_parry_next_turn"] = True
    finalize_offensive_resolution(state, actor, skill)


def resolve_quiet_benediction(state: BattleState, actor: Combatant) -> None:
    target = choose_most_wounded_ally(state, actor)
    base_heal = max(1, ceil_int(target.max_hp * QUIET_BENEDICTION_HEAL_RATIO))
    apply_healing_effect(state, actor, target, base_heal, "Quiet Benediction", action_id="quiet_benediction")
    cleanse_one_debuff(state, target, source_text="Quiet Benediction")
    if any(equipment_has_tag(item, "mage") for item in get_character_equipment(actor).values()):
        state.change_spotlight(1, f"{actor.name} Quiet Benediction")
    finalize_action_resolution(state, actor, action_skill_for_actor(actor, BATTLE_ACTIONS["quiet_benediction"]))


def resolve_rain_mark(state: BattleState, actor: Combatant, target: Combatant) -> None:
    target.add_condition("rain_mark", RAIN_MARK_DURATION)
    target.metadata["rain_mark_break_bonus_pending"] = True
    state.logger.log(state.round_number, f"{target.name} is marked by rain for {RAIN_MARK_DURATION} turns.")
    finalize_action_resolution(state, actor, action_skill_for_actor(actor, BATTLE_ACTIONS["rain_mark"]))


def resolve_blood_vow(state: BattleState, actor: Combatant) -> None:
    current_cost = ceil_int(actor.hp * BLOOD_VOW_CURRENT_HP_COST_RATIO)
    max_cost = ceil_int(actor.max_hp * BLOOD_VOW_MAX_HP_COST_RATIO)
    hp_cost = max(1, min(current_cost, max_cost))
    actor.hp = max(1, actor.hp - hp_cost)
    actor.metadata["blood_vow_ready"] = True
    actor.add_condition("blood_vow", BLOOD_VOW_STATUS_DURATION)
    state.logger.log(state.round_number, f"{actor.name} pays {hp_cost} HP for Blood Vow.")
    finalize_action_resolution(state, actor, action_skill_for_actor(actor, BATTLE_ACTIONS["blood_vow"]))


def resolve_battle_action(state: BattleState, actor: Combatant, action: BattleActionDef, targets: List[Combatant]) -> bool:
    inputs = turn_inputs_for_actor(state, actor)
    if action.consumes_all_ap:
        set_actor_ap(actor, 0)
    else:
        spend_actor_ap(actor, action.ap_cost)

    force_turn_end = action.force_turn_end or actor_current_ap(actor) <= 0
    if action.action_id == "use_healing_potion":
        heal_with_potion(state, actor)
    elif action.action_id == "light_attack":
        resolve_light_attack(state, actor, targets[0], inputs)
    elif action.action_id == "heavy_attack":
        resolve_heavy_attack(state, actor, targets[0], inputs)
    elif action.action_id == "feint_rush":
        resolve_feint_rush(state, actor)
    elif action.action_id == "double_strike":
        resolve_double_strike(state, actor, targets[0], inputs)
    elif action.action_id == "backstep_slash":
        resolve_backstep_slash(state, actor, targets[0], inputs)
    elif action.action_id == "charge_slash":
        resolve_charge_slash(state, actor, targets[0], inputs)
    elif action.action_id == "trance":
        resolve_trance(state, actor, targets[0], inputs)
    elif action.action_id == "poisoned_chalice":
        resolve_poisoned_chalice(state, actor, targets[0], inputs)
    elif action.action_id == "backflip":
        resolve_backflip(state, actor)
    elif action.action_id == "defensive_technique":
        resolve_defensive_technique(state, actor)
    elif action.action_id == "regain_balance":
        resolve_regain_balance(state, actor, inputs)
    elif action.action_id == "shield_oath":
        resolve_shield_oath(state, actor)
    elif action.action_id == "razor_encore":
        resolve_razor_encore(state, actor, targets[0], inputs)
    elif action.action_id == "quiet_benediction":
        resolve_quiet_benediction(state, actor)
    elif action.action_id == "rain_mark":
        resolve_rain_mark(state, actor, targets[0])
    elif action.action_id == "blood_vow":
        resolve_blood_vow(state, actor)
    actor.last_skill_used = action.action_id
    return force_turn_end or state.check_end()


def perform_player_action(state: BattleState, actor: Combatant) -> bool:
    turn_inputs = get_turn_axis_scores(state, actor, interactive=state.interactive)
    starting_ap = start_player_turn_ap(state, actor, turn_inputs)
    log_player_action_inputs_once(state, actor, turn_inputs, starting_ap)
    apply_posture_and_post_action_effects(state, actor, turn_inputs)

    acted = False
    while actor.alive() and actor_current_ap(actor) > 0 and not state.battle_over:
        if state.interactive:
            state.render_state()
            action = choose_player_battle_action(state, actor)
            if action is None:
                break
            targets = choose_targets_for_battle_action(state, actor, action)
        else:
            action, targets = auto_choose_battle_action_and_targets(state, actor, turn_inputs)
            if action is None:
                break

        if not targets:
            state.check_end()
            break
        acted = True
        if resolve_battle_action(state, actor, action, targets):
            break
    actor.metadata.pop("turn_accuracy_penalty", None)
    actor.metadata.pop("current_action_accuracy_modifier", None)
    return acted


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
            power_break_mult = power_break_multiplier(inputs.power)
            state.logger.log(
                state.round_number,
                f"Power output x{power_damage_mult:.2f} damage / x{power_break_mult:.2f} break from Power {inputs.power}.",
            )
    self_risk_reduction = current_self_risk_reduction(state, actor, skill)
    equipment_modifiers = calculate_equipment_modifiers(actor, action_id=skill.effect_id, skill=skill)

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
    base_damage = max(0, DAMAGE_TIERS[skill.damage_tier] + equipment_modifiers.base_damage_bonus)
    base_break = max(0, BREAK_TIERS[skill.break_tier])
    blood_vow_damage_mult = consume_blood_vow_damage_bonus(actor) if offensive_skill else 1.0
    black_vial_mult = black_vial_damage_multiplier(actor) if offensive_skill else 1.0
    next_break_action_mult = consume_next_break_action_bonus(actor) if offensive_skill and base_break > 0 else 1.0
    damage = ceil_int(
        base_damage
        * scale
        * before_damage_mult
        * counterphrase_damage_mult
        * blood_vow_damage_mult
        * black_vial_mult
        * power_damage_mult
        * equipment_modifiers.damage_multiplier
    )
    break_damage = ceil_int(
        base_break
        * scale
        * before_break_mult
        * counterphrase_break_mult
        * next_break_action_mult
        * power_break_mult
        * equipment_modifiers.break_multiplier
    )

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

        result = apply_damage_to_target(
            state=state,
            source=actor,
            target=target,
            damage=damage,
            break_damage=break_damage,
            skill=skill,
            can_crit=skill.kind not in {"support", "utility"},
            status_to_apply=status_payload,
        ) or {}

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


def enemy_action_should_stop(state: BattleState) -> bool:
    return state.check_end()


def choose_low_guard_player_target(state: BattleState) -> Optional[Combatant]:
    players = state.living_players()
    if not players:
        state.check_end()
        return None
    return min(players, key=lambda unit: (unit.guard, unit.hp))


def scale_reaction_failure_damage(state: BattleState, attacker: Combatant, damage: int) -> int:
    if damage <= 0 or attacker.team != "enemy":
        return max(0, damage)
    return ceil_int(damage * state.reaction_failure_damage_multiplier(attacker))


def enemy_choose_target(state: BattleState, actor: Combatant) -> Optional[Combatant]:
    players = state.living_players()
    if not players:
        state.check_end()
        return None
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
    if enemy_action_should_stop(state):
        return
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
    if target is None:
        return
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
    if target is None:
        return
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
    if target is None:
        return
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
    if target is None:
        return
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
    if target is None:
        return
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
        if enemy_action_should_stop(state):
            return
        if not target.alive():
            break


def enemy_veil_leech(state: BattleState, actor: Combatant) -> None:
    target = enemy_choose_target(state, actor)
    if target is None:
        return
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
        if target is None:
            return
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
    if target is None:
        return
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
    if target is None:
        return
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
    if target is None:
        return
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
            if enemy_action_should_stop(state):
                return
    else:
        target = enemy_choose_target(state, actor)
        if target is None:
            return
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
    if target is None:
        return
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
    target = choose_low_guard_player_target(state)
    if target is None:
        return
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
        if enemy_action_should_stop(state):
            return
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
            if enemy_action_should_stop(state):
                return
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
        mark_target = choose_low_guard_player_target(state)
        if mark_target is None:
            return
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
            if enemy_action_should_stop(state):
                return
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
    if target is None:
        return
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
        if enemy_action_should_stop(state):
            return
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
            if enemy_action_should_stop(state):
                return
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
    if target is None:
        return
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
        if enemy_action_should_stop(state):
            return
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
        if enemy_action_should_stop(state):
            return
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
        if enemy_action_should_stop(state):
            return
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
            if enemy_action_should_stop(state):
                return
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
        if enemy_action_should_stop(state):
            return
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
    if target is None:
        return
    if hp_ratio <= 0.35 and actor.times_acted % 3 == 2:
        inputs = make_resolved_inputs(84, 72, 84, SKILLS["standard_strike"])
        actor.metadata["last_inputs"] = inputs
        apply_posture_and_post_action_effects(state, actor, inputs)
        state.logger.log(state.round_number, f"{actor.name} invokes Quiet Relay.")
        state.logger.log(state.round_number, "The second toll comes after the breath.")
        first_toll = cycle[actor.times_acted % len(cycle)]
        second_toll = next((name for name in cycle if name != first_toll), cycle[(actor.times_acted + 1) % len(cycle)])
        result_one = _orison_execute_toll(state, actor, target, first_toll, in_quiet_relay=True)
        if enemy_action_should_stop(state):
            return
        if target.alive():
            result_two = _orison_execute_toll(state, actor, target, second_toll, in_quiet_relay=True)
        else:
            spill_target = enemy_choose_target(state, actor)
            if spill_target is None:
                return
            result_two = _orison_execute_toll(state, actor, spill_target, second_toll, in_quiet_relay=True)
        if enemy_action_should_stop(state):
            return
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
        if enemy_action_should_stop(state):
            return
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
    if enemy_action_should_stop(state):
        return
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
    if target is None:
        return
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
            if enemy_action_should_stop(state):
                return
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
    if target is None:
        return
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
                if enemy_action_should_stop(state):
                    return
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
    target = choose_low_guard_player_target(state)
    if target is None:
        return
    inputs = make_resolved_inputs(74, 82, 48, SKILLS["standard_strike"])
    actor.metadata["last_inputs"] = inputs
    apply_posture_and_post_action_effects(state, actor, inputs)
    if actor.times_acted % 3 == 1 and len(state.living_enemies()) < 3:
        # Summon one hound in terminal prototype.
        summon = create_enemy("glass_hound", index=len([e for e in state.enemies if e.entity_id.startswith('glass_hound')]) + 1)
        summon.metadata["counts_for_execution"] = False
        state.apply_enemy_balance(summon)
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
    if target is None:
        return
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
        ensure_battle_loadout(state)
        for unit in state.everyone():
            unit.position = POSITION_DEFAULT
            reset_actor_combat_metadata(unit)
        state.cursor.battle_started = True
        state.logger.log(state.round_number, "Battle begins.")
        for player in state.players:
            for line in equipment_bonus_summary_lines(player):
                state.logger.log(state.round_number, line)
            if actor_has_relic(player, "kings_wager"):
                state.logger.log(state.round_number, f"{player.name} bears King's Wager. Incoming damage is doubled.")
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
        perform_player_action(state, actor)
        actor.times_acted += 1
    else:
        if state.check_end():
            return
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


def scaled_amount(value: int, multiplier: float, minimum: int = 1) -> int:
    if value <= 0:
        return 0
    return max(minimum, ceil_int(value * multiplier))


# Party-size balance profiles keep solo expeditions survivable and
# three-person parties from steamrolling every battle.
def get_party_balance_profile(party_size: int, mode: str = BALANCE_MODE_STANDARD) -> PartyBalanceProfile:
    normalized_size = max(1, int(party_size))
    normalized_mode = BALANCE_MODE_EXPEDITION if mode == BALANCE_MODE_EXPEDITION else BALANCE_MODE_STANDARD
    if normalized_size <= 1 and normalized_mode == BALANCE_MODE_EXPEDITION:
        return PartyBalanceProfile(
            party_size=normalized_size,
            mode=normalized_mode,
            enemy_hp_mult=0.82,
            enemy_guard_mult=0.86,
            enemy_break_mult=0.84,
            enemy_damage_mult=0.90,
            boss_hp_mult=0.92,
            boss_guard_mult=0.92,
            boss_break_mult=0.90,
            boss_pressure_mult=0.92,
            reaction_failure_damage_mult=0.85,
            healing_reward_mult=1.28,
            recovery_heal_mult=1.30,
        )
    if normalized_size <= 1:
        return PartyBalanceProfile(
            party_size=normalized_size,
            mode=normalized_mode,
            enemy_hp_mult=0.88,
            enemy_guard_mult=0.90,
            enemy_break_mult=0.88,
            enemy_damage_mult=0.93,
            boss_hp_mult=0.96,
            boss_guard_mult=0.95,
            boss_break_mult=0.94,
            boss_pressure_mult=0.95,
            reaction_failure_damage_mult=0.90,
            healing_reward_mult=1.20,
            recovery_heal_mult=1.22,
        )
    if normalized_size == 2:
        return PartyBalanceProfile(
            party_size=normalized_size,
            mode=normalized_mode,
            enemy_hp_mult=0.97,
            enemy_guard_mult=0.98,
            enemy_break_mult=0.98,
            reaction_failure_damage_mult=0.95,
            healing_reward_mult=1.08,
            recovery_heal_mult=1.10,
        )
    return PartyBalanceProfile(
        party_size=normalized_size,
        mode=normalized_mode,
        enemy_hp_mult=1.12,
        enemy_guard_mult=1.08,
        enemy_break_mult=1.10,
        boss_hp_mult=1.08,
        boss_guard_mult=1.08,
        boss_break_mult=1.10,
        boss_pressure_mult=1.06,
    )


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
    print(emoji_label("inspect", "Tip: each player turn starts with one Power Precision Composure input such as: 72 61 84"))
    if not args.auto:
        print("Manual battles also ask for a 3-action extra loadout at battle start.")
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
    state.initialize_enemy_balance()

    print_intro(args, party_ids)
    winner = run_battle(state)
    state.save_log(args.log_file)
    print(f"\nBattle log written to: {args.log_file}")
    return 0 if winner == "player" else 1


if __name__ == "__main__":
    raise SystemExit(main())
