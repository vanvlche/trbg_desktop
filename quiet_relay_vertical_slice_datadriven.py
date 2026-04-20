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
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import quiet_relay_terminal_datadriven as qr

SAVE_VERSION = 5
RUNTIME_DATA_ROOT = "/mnt/data" if os.path.isdir("/mnt/data") else os.path.dirname(os.path.abspath(__file__))
DEFAULT_SAVE_FILE = os.path.join(RUNTIME_DATA_ROOT, "quiet_relay_vertical_slice_datadriven_save.json")
DEFAULT_RUN_REPORT = os.path.join(RUNTIME_DATA_ROOT, "quiet_relay_vertical_slice_datadriven_last_run.txt")
DEFAULT_LOG_DIR = os.path.join(RUNTIME_DATA_ROOT, "quiet_relay_vertical_slice_datadriven_logs")
DEFAULT_PARTY = ["vanguard"]
DEFAULT_AXIS_SCORES = {"power": 60, "precision": 60, "composure": 60}
SUPPORTED_PARTY_IDS = tuple(qr.CHARACTER_BLUEPRINTS.keys())
NEGATIVE_STATUSES = {"scorch", "snare", "soak", "jolt", "hex", "reveal"}
CONTENT = qr.CONTENT
DEFAULT_DISTRICT_ID = str(CONTENT.default_district_id)
AUTO_ROUTE_CHOICES = ("first", "last")
LEGACY_V1_NODE_ORDER_BY_DISTRICT: Dict[str, Tuple[str, ...]] = {
    "district_03_rain_toll_corridor": (
        "overpass_watch",
        "flooded_arcade",
        "service_niche",
        "witness_chapel",
        "toll_plaza",
        "bell_tower",
    ),
}
ENABLE_SEMANTIC_EMOJI_UI = True

UI_ICONS = {
    "battle": "⚔️",
    "event": "✦",
    "boss": "👑",
    "hub": "🕯️",
    "route": "🧭",
    "save": "💾",
    "load": "📂",
    "back": "↩️",
    "inspect": "🔎",
    "continue": "▶️",
    "party": "⛭",
    "shards": "💠",
    "recovery": "🩹",
    "barrier": "🛡️",
    "spotlight": "☀️",
    "relic": "🧿",
    "maintenance": "🔧",
    "chapel": "🕯️",
    "shared": "◈",
    "neutral": "◈",
    "low": "🟢",
    "medium": "🟡",
    "high": "🔴",
    "vanguard": "🛡️",
    "duelist": "🗡️",
    "cantor": "🎼",
    "ranger": "🏹",
    "penitent": "⛓️",
}


def ui_icon(key: str) -> str:
    if not ENABLE_SEMANTIC_EMOJI_UI:
        return ""
    return UI_ICONS.get(key, "")


def emoji_label(key: str, text: str) -> str:
    icon = ui_icon(key)
    return f"{icon} {text}" if icon else text


def emoji_for_node_kind(kind: str) -> str:
    return ui_icon(kind)


def emoji_for_route_family(route_family: str) -> str:
    return ui_icon(route_family or "neutral")


def emoji_for_risk_tier(risk_tier: str) -> str:
    return ui_icon(risk_tier)


def emoji_for_character_id(character_id: str) -> str:
    return ui_icon(character_id)


def menu_label(action_id: str, text: str) -> str:
    icon_key = {
        "resume": "continue",
        "start": "route",
        "party": "party",
        "inspect": "inspect",
        "save": "save",
        "load": "load",
        "quit": "back",
    }.get(action_id, action_id)
    return emoji_label(icon_key, text)


def report_path_for_save(save_file: str) -> str:
    base_dir = os.path.dirname(os.path.abspath(save_file)) if save_file else RUNTIME_DATA_ROOT
    return os.path.join(base_dir, "quiet_relay_vertical_slice_datadriven_last_run.txt")


@dataclass(frozen=True)
class RewardOptionDef:
    option_id: str
    name: str
    description: str
    effect_type: str
    params: Dict[str, object]
    cost: int = 0


@dataclass(frozen=True)
class RewardTableDef:
    table_id: str
    name: str
    option_ids: Tuple[str, ...]
    pick_count: int = 1
    table_type: str = "choice"
    max_purchases: int = 1
    identity_tags: Tuple[str, ...] = ()
    preview_text: str = ""


@dataclass(frozen=True)
class EventText:
    event_id: str
    title: str
    text: str


@dataclass(frozen=True)
class EncounterVariant:
    variant_id: str
    encounter_ids: Tuple[str, ...]
    weight: int = 1
    route_families_any: Tuple[str, ...] = ()
    risk_tiers_any: Tuple[str, ...] = ()
    route_bias_any: Tuple[str, ...] = ()
    flavor_tags: Tuple[str, ...] = ()


@dataclass(frozen=True)
class DistrictNode:
    node_id: str
    title: str
    kind: str
    event_id: str
    encounter_ids: Tuple[str, ...] = ()
    encounter_pool_id: Optional[str] = None
    encounter_variants: Tuple[EncounterVariant, ...] = ()
    reward_table_id: Optional[str] = None
    shards: int = 0
    next_node_ids: Tuple[str, ...] = ()
    route_family: str = ""
    risk_tier: str = ""
    pacing_stage: str = ""
    preview_tags: Tuple[str, ...] = ()
    preview_text: str = ""


@dataclass(frozen=True)
class DistrictDef:
    district_id: str
    display_name: str
    hub_event_id: str
    start_node_id: str
    node_order: Tuple[str, ...]
    nodes: Dict[str, DistrictNode]
    encounter_pools: Dict[str, Tuple[EncounterVariant, ...]] = field(default_factory=dict)

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
    battle_snapshot: Optional[Dict[str, object]] = None
    selected_party_ids: List[str] = field(default_factory=lambda: list(DEFAULT_PARTY))
    solo_character_id: str = DEFAULT_PARTY[0]
    current_node_axis_scores: Dict[str, int] = field(default_factory=lambda: dict(DEFAULT_AXIS_SCORES))
    node_axis_history: Dict[str, Dict[str, int]] = field(default_factory=dict)
    resolved_node_encounters: Dict[str, Dict[str, object]] = field(default_factory=dict)

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
        params = {
            str(key): value
            for key, value in raw.items()
            if key not in {"display_name", "description", "effect_type", "cost"}
        }
        parsed[option_id] = RewardOptionDef(
            option_id=option_id,
            name=str(raw["display_name"]),
            description=str(raw["description"]),
            effect_type=str(raw["effect_type"]),
            params=params,
            cost=int(raw.get("cost", 0)),
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
            table_type=str(raw.get("table_type", "choice")),
            max_purchases=int(raw.get("max_purchases", 1)),
            identity_tags=tuple(str(tag) for tag in raw.get("identity_tags", [])),
            preview_text=str(raw.get("preview_text", "")),
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


def _parse_encounter_variant(raw: Dict[str, object], fallback_variant_id: str) -> EncounterVariant:
    return EncounterVariant(
        variant_id=str(raw.get("variant_id", fallback_variant_id)),
        encounter_ids=tuple(str(enc_id) for enc_id in raw.get("encounter_ids", [])),
        weight=max(1, int(raw.get("weight", 1))),
        route_families_any=tuple(str(value) for value in raw.get("route_families_any", [])),
        risk_tiers_any=tuple(str(value) for value in raw.get("risk_tiers_any", [])),
        route_bias_any=tuple(str(value) for value in raw.get("route_bias_any", [])),
        flavor_tags=tuple(str(value) for value in raw.get("flavor_tags", [])),
    )


def _parse_encounter_variants(raw_variants: object) -> Tuple[EncounterVariant, ...]:
    if not isinstance(raw_variants, list):
        return ()
    return tuple(
        _parse_encounter_variant(dict(raw_variant), f"variant_{idx}")
        for idx, raw_variant in enumerate(raw_variants, start=1)
        if isinstance(raw_variant, dict)
    )


def _parse_districts() -> Dict[str, DistrictDef]:
    parsed: Dict[str, DistrictDef] = {}
    for district_id, raw in CONTENT.districts.items():
        encounter_pools = {
            str(pool_id): _parse_encounter_variants(raw_variants)
            for pool_id, raw_variants in dict(raw.get("encounter_pools", {})).items()
        }
        nodes: Dict[str, DistrictNode] = {}
        raw_nodes = dict(raw.get("nodes", {}))
        for node_id, node_raw in raw_nodes.items():
            nodes[node_id] = DistrictNode(
                node_id=node_id,
                title=str(node_raw.get("title", node_id)),
                kind=str(node_raw["kind"]),
                event_id=str(node_raw["event_id"]),
                encounter_ids=tuple(str(enc_id) for enc_id in node_raw.get("encounter_ids", [])),
                encounter_pool_id=(
                    str(node_raw["encounter_pool_id"])
                    if node_raw.get("encounter_pool_id") is not None
                    else None
                ),
                encounter_variants=_parse_encounter_variants(node_raw.get("encounter_variants", [])),
                reward_table_id=(str(node_raw["reward_table_id"]) if node_raw.get("reward_table_id") is not None else None),
                shards=int(node_raw.get("shards", 0)),
                next_node_ids=tuple(str(next_id) for next_id in node_raw.get("next_node_ids", [])),
                route_family=str(node_raw.get("route_family", "")),
                risk_tier=str(node_raw.get("risk_tier", "")),
                pacing_stage=str(node_raw.get("pacing_stage", "")),
                preview_tags=tuple(str(tag) for tag in node_raw.get("preview_tags", [])),
                preview_text=str(node_raw.get("preview_text", "")),
            )
        parsed[district_id] = DistrictDef(
            district_id=district_id,
            display_name=str(raw["display_name"]),
            hub_event_id=str(raw["hub_event_id"]),
            start_node_id=str(raw["start_node_id"]),
            node_order=tuple(str(node_id) for node_id in raw.get("node_order", [])),
            nodes=nodes,
            encounter_pools=encounter_pools,
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


def indented_wrap(text: str, indent: str = "     ", width: int = 80) -> str:
    return textwrap.fill(text, width=width, initial_indent=indent, subsequent_indent=indent)


def title_from_slug(value: str) -> str:
    parts = [part for part in value.replace("-", "_").split("_") if part]
    return " ".join(part.capitalize() for part in parts)


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
        print(f"  Enter: {emoji_label('continue', 'continue')}")

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


THREAT_TAG_LABELS = {
    "heavy": "heavy pressure",
    "channel": "channeling",
    "burst_start": "burst threat",
    "burst": "burst threat",
    "attrition": "attrition",
    "evasive": "evasive target",
    "dodge": "evasive target",
    "guard": "guard pressure",
    "break": "break pressure",
    "barrier": "defensive pressure",
    "recovery": "attrition",
    "sustain": "attrition",
    "spotlight": "momentum swings",
    "boss": "boss pressure",
    "boss_prep": "tower pressure",
    "risk": "unstable pressure",
    "shards": "high stakes",
}


def vague_threat_labels(tags: Sequence[str]) -> List[str]:
    labels: List[str] = []
    for raw_tag in tags:
        label = THREAT_TAG_LABELS.get(str(raw_tag))
        if label and label not in labels:
            labels.append(label)
    return labels


def route_preview_header(
    node: DistrictNode,
    *,
    semantic_icons: bool = True,
    rules_visibility: str = qr.DEFAULT_RULES_VISIBILITY,
) -> str:
    visibility = qr.normalize_rules_visibility(rules_visibility)
    title_icon = ""
    if semantic_icons:
        title_icon = emoji_for_route_family(node.route_family) if node.route_family else emoji_for_node_kind(node.kind)
    parts = [f"{title_icon} {node.title}" if title_icon else node.title]
    parts.append(title_from_slug(node.kind))
    if node.route_family:
        family_text = f"{title_from_slug(node.route_family)} route"
        parts.append(family_text)
    if node.risk_tier and visibility != qr.RULES_VISIBILITY_HIDDEN:
        risk_icon = emoji_for_risk_tier(node.risk_tier) if semantic_icons else ""
        risk_text = f"{title_from_slug(node.risk_tier)} risk"
        parts.append(f"{risk_icon} {risk_text}" if risk_icon else risk_text)
    if node.preview_tags and visibility == qr.RULES_VISIBILITY_DEBUG:
        parts.append("[" + ", ".join(node.preview_tags[:3]) + "]")
    elif node.preview_tags and visibility == qr.RULES_VISIBILITY_FUZZY:
        vague_tags = vague_threat_labels(node.preview_tags)
        if vague_tags:
            parts.append("[" + ", ".join(vague_tags[:3]) + "]")
    return " -- ".join(parts)


def reward_preview_text(node: DistrictNode) -> str:
    if not node.reward_table_id or node.reward_table_id not in REWARD_TABLES:
        return ""
    table = REWARD_TABLES[node.reward_table_id]
    if table.identity_tags:
        return "Likely rewards: " + ", ".join(table.identity_tags[:3]) + "."
    return table.preview_text


def encounter_lesson_preview(
    node: DistrictNode,
    rules_visibility: str = qr.DEFAULT_RULES_VISIBILITY,
) -> str:
    visibility = qr.normalize_rules_visibility(rules_visibility)
    if visibility == qr.RULES_VISIBILITY_HIDDEN:
        return node.preview_text
    if visibility == qr.RULES_VISIBILITY_FUZZY:
        parts = [node.preview_text] if node.preview_text else []
        vague_tags = vague_threat_labels(node.preview_tags)
        if vague_tags:
            parts.append("Threat: " + ", ".join(vague_tags[:3]) + ".")
        return " ".join(parts)
    return node.preview_text


def route_preview_detail(
    node: DistrictNode,
    rules_visibility: str = qr.DEFAULT_RULES_VISIBILITY,
) -> str:
    visibility = qr.normalize_rules_visibility(rules_visibility)
    parts = []
    lesson = encounter_lesson_preview(node, visibility)
    if lesson:
        parts.append(lesson)
    reward_text = reward_preview_text(node)
    if reward_text and visibility != qr.RULES_VISIBILITY_HIDDEN:
        parts.append(reward_text)
    return " ".join(parts)


def route_choice_log_text(
    node: DistrictNode,
    rules_visibility: str = qr.DEFAULT_RULES_VISIBILITY,
) -> str:
    detail = route_preview_detail(node, rules_visibility)
    if detail:
        return f"{route_preview_header(node, semantic_icons=False, rules_visibility=rules_visibility)} | {detail}"
    return route_preview_header(node, semantic_icons=False, rules_visibility=rules_visibility)


def get_current_node(campaign: CampaignState) -> Optional[DistrictNode]:
    if not campaign.expedition_active or campaign.current_node_id is None:
        return None
    district = get_district(campaign.district_id)
    return district.nodes.get(campaign.current_node_id)


def current_progress_text(campaign: CampaignState) -> str:
    node = get_current_node(campaign)
    if node is None:
        return emoji_label("back", "No expedition currently active.")
    current_step = campaign.nodes_cleared() + 1
    return emoji_label("continue", f"Expedition in progress: step {current_step}, currently at {node.title}.")


# ---------------------------------------------------------------------------
# Campaign state creation / serialization
# ---------------------------------------------------------------------------


def clamp_axis_score(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 60
    return max(0, min(100, parsed))


def normalize_axis_scores(raw: object) -> Dict[str, int]:
    raw_dict = raw if isinstance(raw, dict) else {}
    return {
        "power": clamp_axis_score(raw_dict.get("power", DEFAULT_AXIS_SCORES["power"])),
        "precision": clamp_axis_score(raw_dict.get("precision", DEFAULT_AXIS_SCORES["precision"])),
        "composure": clamp_axis_score(raw_dict.get("composure", DEFAULT_AXIS_SCORES["composure"])),
    }


def load_axis_file(filepath: str) -> Dict[str, object]:
    with open(filepath, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError("Axis file must contain a JSON object.")
    return raw


def axis_scores_from_file(axis_file_data: Optional[Dict[str, object]], node: DistrictNode) -> Optional[Dict[str, int]]:
    if not axis_file_data:
        return None
    nodes = axis_file_data.get("nodes", {})
    if isinstance(nodes, dict) and node.node_id in nodes:
        return normalize_axis_scores(nodes[node.node_id])
    if "default" in axis_file_data:
        return normalize_axis_scores(axis_file_data.get("default"))
    return dict(DEFAULT_AXIS_SCORES)


def previous_axis_scores(campaign: CampaignState) -> Dict[str, int]:
    if campaign.node_axis_history:
        last_node_id = next(reversed(campaign.node_axis_history))
        return normalize_axis_scores(campaign.node_axis_history[last_node_id])
    return normalize_axis_scores(campaign.current_node_axis_scores)


def prompt_node_axis_scores(
    campaign: CampaignState,
    node: DistrictNode,
    auto: bool,
    node_axis_override: Optional[Dict[str, int]] = None,
    axis_file_data: Optional[Dict[str, object]] = None,
) -> Dict[str, int]:
    if node_axis_override is not None:
        return normalize_axis_scores(node_axis_override)

    file_scores = axis_scores_from_file(axis_file_data, node)
    if file_scores is not None:
        return file_scores

    if auto:
        return dict(DEFAULT_AXIS_SCORES)

    defaults = previous_axis_scores(campaign)
    print(f"\nNode calibration for {node.title}")
    power = qr.prompt_int("Power", default=defaults["power"], low=0, high=100)
    precision = qr.prompt_int("Precision", default=defaults["precision"], low=0, high=100)
    composure = qr.prompt_int("Composure", default=defaults["composure"], low=0, high=100)
    return normalize_axis_scores({"power": power, "precision": precision, "composure": composure})


def validate_solo_character_id(raw: object) -> str:
    character_id = str(raw).strip()
    if character_id not in qr.CHARACTER_BLUEPRINTS:
        raise ValueError(f"Unknown character id: {character_id}")
    return character_id


def validate_selected_party_ids(raw: str | Sequence[str]) -> List[str]:
    if isinstance(raw, str):
        party_ids = [part.strip() for part in raw.split(",") if part.strip()]
    else:
        party_ids = [str(part).strip() for part in raw if str(part).strip()]
    if not party_ids:
        raise ValueError("At least one character id is required.")
    if len(set(party_ids)) != len(party_ids):
        raise ValueError("Party members must be unique.")
    invalid = [party_id for party_id in party_ids if party_id not in qr.CHARACTER_BLUEPRINTS]
    if invalid:
        raise ValueError(f"Unknown character ids: {', '.join(invalid)}")
    missing_content = [party_id for party_id in party_ids if party_id not in qr.CHARACTER_BLUEPRINTS]
    if missing_content:
        raise ValueError(f"Character ids are not available in this content pack: {', '.join(missing_content)}")
    return party_ids


def apply_selected_party(campaign: CampaignState, party_ids: Sequence[str]) -> None:
    selected = validate_selected_party_ids(party_ids)
    solo_character = validate_solo_character_id(selected[0])
    campaign.solo_character_id = solo_character
    campaign.selected_party_ids = [solo_character]
    if not campaign.expedition_active:
        campaign.players = qr.build_party([solo_character])


def new_campaign(
    seed: int,
    district_id: str = DEFAULT_DISTRICT_ID,
    selected_party_ids: Optional[Sequence[str]] = None,
) -> CampaignState:
    rng = random.Random(seed)
    party_ids = validate_selected_party_ids(selected_party_ids or DEFAULT_PARTY)
    solo_character = validate_solo_character_id(party_ids[0])
    players = qr.build_party([solo_character])
    campaign = CampaignState(
        players=players,
        rng=rng,
        district_id=district_id,
        selected_party_ids=[solo_character],
        solo_character_id=solo_character,
    )
    campaign.record(f"Created new campaign with seed {seed} in district {district_id}.")
    return campaign


def base_player_payload(player: qr.Combatant) -> Dict[str, object]:
    return qr.combatant_to_payload(player)


def player_from_payload(payload: Dict[str, object]) -> qr.Combatant:
    if "name" in payload and "team" in payload:
        return qr.combatant_from_payload(payload)

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
    player.position = str(payload.get("position", player.position))
    player.barrier = int(payload.get("barrier", player.barrier))
    player.conditions = {str(k): int(v) for k, v in dict(payload.get("conditions", {})).items()}
    player.next_attack_power_bonus = int(payload.get("next_attack_power_bonus", 0))
    player.crit_spotlight_used_this_turn = bool(payload.get("crit_spotlight_used_this_turn", False))
    player.times_acted = int(payload.get("times_acted", 0))
    player.last_skill_used = str(payload["last_skill_used"]) if payload.get("last_skill_used") is not None else None
    merged_metadata = dict(player.metadata)
    merged_metadata.update(dict(payload.get("metadata", {})))
    merged_metadata.pop("last_inputs", None)
    player.metadata = merged_metadata
    return player


def encode_rng_state(rng: random.Random) -> Dict[str, object]:
    return qr.rng_state_to_payload(rng)


def decode_rng_state(encoded: object) -> random.Random:
    if isinstance(encoded, dict):
        return qr.rng_from_payload(encoded)
    if isinstance(encoded, str):
        rng = random.Random()
        state = pickle.loads(base64.b64decode(encoded.encode("ascii")))
        rng.setstate(state)
        return rng
    raise ValueError("Unsupported RNG state payload.")


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
        "battle_snapshot": campaign.battle_snapshot,
        "selected_party_ids": list(campaign.selected_party_ids),
        "solo_character_id": campaign.solo_character_id,
        "current_node_axis_scores": normalize_axis_scores(campaign.current_node_axis_scores),
        "node_axis_history": {
            str(node_id): normalize_axis_scores(scores)
            for node_id, scores in campaign.node_axis_history.items()
        },
        "resolved_node_encounters": campaign.resolved_node_encounters,
    }


def _legacy_state_to_nodes(payload: Dict[str, object], district: DistrictDef) -> tuple[bool, Optional[str], List[str]]:
    expedition_active = bool(payload.get("expedition_active", False))
    legacy_order = LEGACY_V1_NODE_ORDER_BY_DISTRICT.get(district.district_id, district.node_order)
    valid_order = tuple(node_id for node_id in legacy_order if node_id in district.nodes)
    if not valid_order:
        valid_order = district.node_order
    current_index = int(payload.get("current_node_index", 0))
    current_index = max(0, min(current_index, len(valid_order)))
    cleared_node_ids = list(valid_order[:current_index])
    current_node_id: Optional[str] = None
    if expedition_active and current_index < len(valid_order):
        current_node_id = valid_order[current_index]
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
    if version not in {1, 2, 3, 4, SAVE_VERSION}:
        raise ValueError(f"Unsupported save version: {version}")

    players = [player_from_payload(item) for item in list(payload["players"])]
    rng = decode_rng_state(payload["rng_state"])
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

    battle_snapshot = payload.get("battle_snapshot") if version >= 3 else None
    if battle_snapshot is not None and not isinstance(battle_snapshot, dict):
        raise ValueError("Invalid battle_snapshot payload.")
    if battle_snapshot is not None and (not expedition_active or current_node_id is None):
        raise ValueError("Save contains a battle snapshot without an active expedition node.")

    raw_selected_party_ids = validate_selected_party_ids(payload.get("selected_party_ids", DEFAULT_PARTY))
    solo_character_id = validate_solo_character_id(payload.get("solo_character_id", raw_selected_party_ids[0]))
    selected_party_ids = [solo_character_id]
    if not expedition_active and battle_snapshot is None:
        players = qr.build_party([solo_character_id])

    current_node_axis_scores = normalize_axis_scores(payload.get("current_node_axis_scores", DEFAULT_AXIS_SCORES))
    node_axis_history: Dict[str, Dict[str, int]] = {}
    raw_axis_history = payload.get("node_axis_history", {})
    if isinstance(raw_axis_history, dict):
        for node_id, raw_scores in raw_axis_history.items():
            node_axis_history[str(node_id)] = normalize_axis_scores(raw_scores)
    resolved_node_encounters: Dict[str, Dict[str, object]] = {}
    raw_resolved = payload.get("resolved_node_encounters", {})
    if isinstance(raw_resolved, dict):
        for node_id, raw_info in raw_resolved.items():
            if not isinstance(raw_info, dict):
                continue
            encounter_ids = [str(enc_id) for enc_id in list(raw_info.get("encounter_ids", []))]
            if not encounter_ids:
                continue
            resolved_node_encounters[str(node_id)] = {
                "variant_id": str(raw_info.get("variant_id", "fixed")),
                "encounter_ids": encounter_ids,
            }

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
        battle_snapshot=battle_snapshot,
        selected_party_ids=selected_party_ids,
        solo_character_id=solo_character_id,
        current_node_axis_scores=current_node_axis_scores,
        node_axis_history=node_axis_history,
        resolved_node_encounters=resolved_node_encounters,
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
    solo_character = validate_solo_character_id(campaign.solo_character_id)
    campaign.players = qr.build_party([solo_character])
    campaign.selected_party_ids = [solo_character]
    campaign.district_id = district.district_id
    campaign.expedition_active = True
    campaign.current_node_id = district.start_node_id
    campaign.cleared_node_ids = []
    campaign.resolved_node_encounters = {}
    campaign.current_node_axis_scores = dict(DEFAULT_AXIS_SCORES)
    campaign.node_axis_history = {}
    campaign.recovery_charges = 3
    campaign.max_recovery_charges = 3
    campaign.starting_spotlight = 0
    campaign.prebattle_barrier = 0
    campaign.boss_guard_penalty = 0
    campaign.run_shards = 0
    campaign.boons = []
    campaign.battle_snapshot = None
    campaign.record(f"Started a new expedition in {district.display_name}.")


def clear_battle_only_state(player: qr.Combatant) -> None:
    player.barrier = 0
    player.posture = "flow"
    player.position = getattr(qr, "POSITION_DEFAULT", "set")
    player.conditions = {name: duration for name, duration in player.conditions.items() if name not in NEGATIVE_STATUSES}
    player.next_attack_power_bonus = 0
    player.crit_spotlight_used_this_turn = False
    player.times_acted = 0
    player.last_skill_used = None
    preserved_metadata = {key: value for key, value in player.metadata.items() if key not in {"last_inputs"}}
    player.metadata = preserved_metadata
    if hasattr(qr, "clear_p2_battle_metadata"):
        qr.clear_p2_battle_metadata(player)
    player.guard = max(0, min(player.guard, player.max_guard))
    player.break_meter = max(0, min(player.break_meter, player.max_break))


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


def grant_relic_to_party(campaign: CampaignState, relic_id: str) -> bool:
    relic_raw = qr.RELIC_DATA.get(relic_id, {})
    relic_name = str(relic_raw.get("display_name", relic_id))
    added = False
    for player in campaign.players:
        relic_ids = [str(item) for item in player.metadata.get("relic_ids", [])]
        relic_names = [str(item) for item in player.metadata.get("relic_names", [])]
        if relic_id in relic_ids:
            continue
        relic_ids.append(relic_id)
        relic_names.append(relic_name)
        player.metadata["relic_ids"] = relic_ids
        player.metadata["relic_names"] = relic_names
        added = True
    return added


def party_has_relic(campaign: CampaignState, relic_id: str) -> bool:
    if not campaign.players:
        return False
    for player in campaign.players:
        relic_ids = {str(item) for item in player.metadata.get("relic_ids", [])}
        if relic_id not in relic_ids:
            return False
    return True


def option_cost(option: RewardOptionDef) -> int:
    return max(0, int(option.cost))


def apply_option(campaign: CampaignState, option_id: str) -> Tuple[str, bool]:
    option = REWARD_OPTIONS[option_id]

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
            campaign.boons.append(option_id)
            return "The team threads bellwire mesh through their armor. Max guard rises for all allies.", True

        if stat == "speed":
            for player in campaign.players:
                player.speed += amount
            campaign.boons.append(option_id)
            return "Signal wire tuning sharpens reflexes. All allies gain speed.", True

        if stat == "max_hp":
            total_healed = 0
            for player in campaign.players:
                player.max_hp += amount
                before = player.hp
                if heal_amount > 0:
                    player.hp = min(player.max_hp, player.hp + heal_amount)
                total_healed += player.hp - before
            campaign.boons.append(option_id)
            return f"Red salt steadies the body. Max HP rises for all allies and the party restores {total_healed} total HP.", True

        if stat == "max_break":
            for player in campaign.players:
                player.max_break += amount
                if refill_to_max:
                    player.break_meter = player.max_break
            campaign.boons.append(option_id)
            return "Steady chimes train the body against impact. All allies gain max Break.", True

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
        if gained <= 0:
            return f"{option.name} would not improve the current route kit.", False
        campaign.boons.append(option_id)

        if counter == "starting_spotlight":
            return f"The team rehearses the opening beat. Starting Spotlight increases by {gained}.", True
        if counter == "prebattle_barrier":
            return f"Ward flares are packed for the route. Future battles start with +{gained} barrier.", True
        if counter == "boss_guard_penalty":
            return f"Bellbreaker oil is brushed onto blades. Boss guard penalty increases by {gained}.", True
        return f"{option.name} changes {counter} by {gained}.", True

    if option.effect_type == "party_heal":
        amount = int(option.params.get("amount", 0))
        healed = heal_party(campaign, amount)
        if healed <= 0:
            return "No one needs the field dressings right now.", False
        campaign.boons.append(option_id)
        return f"Field dressings are applied. The party restores {healed} total HP.", True

    if option.effect_type == "recovery_charge_boost":
        amount = int(option.params.get("amount", 0))
        max_cap = int(option.params.get("max_cap", campaign.max_recovery_charges + amount))
        before = campaign.recovery_charges
        campaign.max_recovery_charges = min(max_cap, campaign.max_recovery_charges + amount)
        campaign.recovery_charges = min(campaign.max_recovery_charges, campaign.recovery_charges + amount)
        gained = campaign.recovery_charges - before
        if gained <= 0:
            return "The team cannot carry more recovery supplies right now.", False
        campaign.boons.append(option_id)
        return f"A sealed cache yields supplies. Recovery charges increase by {gained}.", True

    if option.effect_type == "grant_relic":
        relic_id = str(option.params["relic_id"])
        relic_name = str(qr.RELIC_DATA.get(relic_id, {}).get("display_name", relic_id))
        added = grant_relic_to_party(campaign, relic_id)
        if added:
            campaign.boons.append(option_id)
            return f"The team secures {relic_name}. Its combat trigger is now active for this run.", True
        return f"{relic_name} was already equipped by the current team.", False

    raise ValueError(f"Unsupported reward effect_type: {option.effect_type}")


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def render_party(
    campaign: CampaignState,
    rules_visibility: str = qr.DEFAULT_RULES_VISIBILITY,
) -> None:
    visibility = qr.normalize_rules_visibility(rules_visibility)
    print(f"\n{emoji_label('party', 'PARTY STATUS')}")
    print("-" * 84)
    selected_names = [
        str(qr.CHARACTER_BLUEPRINTS.get(party_id, {}).get("display_name", party_id))
        for party_id in campaign.selected_party_ids
    ]
    print(emoji_label("route", "Selected for next expedition: ") + ", ".join(selected_names))
    for idx, player in enumerate(campaign.players, start=1):
        weapon_name = str(player.metadata.get("weapon_name", "Unknown Weapon"))
        equipment_names = [str(name) for name in player.metadata.get("equipment_names", [])]
        equipment_text = ", ".join(equipment_names) if equipment_names else weapon_name
        relic_names = [str(name) for name in player.metadata.get("relic_names", [])]
        extra_bits = [f"weapon={weapon_name}", f"equipment={equipment_text}"]
        if relic_names:
            extra_bits.append(f"{emoji_label('relic', 'relics')}=" + ", ".join(relic_names))
        character_icon = emoji_for_character_id(player.entity_id)
        line_prefix = f"{idx}. {character_icon} " if character_icon else f"{idx}. "
        print(f"{line_prefix}{player.summary_line()} | " + " | ".join(extra_bits))
    print("-" * 84)
    print(
        f"{emoji_label('recovery', 'Recovery Charges')}: {campaign.recovery_charges}/{campaign.max_recovery_charges} | "
        f"{emoji_label('spotlight', 'Start Spotlight')}: {campaign.starting_spotlight} | "
        f"{emoji_label('barrier', 'Prebattle Barrier')}: {campaign.prebattle_barrier} | "
        f"{emoji_label('boss', 'Boss Guard Penalty')}: {campaign.boss_guard_penalty}"
    )
    print(f"{emoji_label('shards', 'Echo Shards')}: {campaign.run_shards}")
    if campaign.expedition_active:
        axes = normalize_axis_scores(campaign.current_node_axis_scores)
        if visibility == qr.RULES_VISIBILITY_DEBUG:
            print(
                f"Current Node Axis: Power {axes['power']}, "
                f"Precision {axes['precision']}, Composure {axes['composure']}"
            )
        elif visibility == qr.RULES_VISIBILITY_FUZZY:
            print("Current route pressure: readable.")
        else:
            print("Current route pressure: settled.")
    print(f"{emoji_label('load', 'Content Pack')}: {qr.CONTENT.base_dir}")
    if campaign.boons:
        print(emoji_label("event", "Run Boons:"))
        for boon_id in campaign.boons:
            if boon_id in REWARD_OPTIONS:
                option = REWARD_OPTIONS[boon_id]
                print(f"  - {option.name}: {option.description}")
    else:
        print(f"{emoji_label('event', 'Run Boons')}: none")
    print()


def format_character_option(character_id: str) -> str:
    raw = qr.CHARACTER_BLUEPRINTS[character_id]
    weapon_id = str(raw.get("weapon", ""))
    weapon_name = str(qr.WEAPON_DATA.get(weapon_id, {}).get("display_name", weapon_id))
    role = str(raw.get("role", ""))
    affinity = str(raw.get("default_affinity", "neutral"))
    return f"{raw.get('display_name', character_id)} [{character_id}] - {role}, {affinity}, {weapon_name}"


def configure_party(campaign: CampaignState) -> None:
    print("\nChoose one solo character for the next expedition.")
    print("Current: " + campaign.solo_character_id)
    for idx, character_id in enumerate(SUPPORTED_PARTY_IDS, start=1):
        print(f"  {idx}. {format_character_option(character_id)}")
    print("Enter a number or id. Press Enter to keep the current character.")

    while True:
        raw = input("> ").strip()
        if raw == "":
            print("Solo character unchanged.")
            return

        chosen = raw
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(SUPPORTED_PARTY_IDS):
                chosen = SUPPORTED_PARTY_IDS[idx - 1]

        try:
            apply_selected_party(campaign, [chosen])
        except ValueError as exc:
            print(f"Solo character error: {exc}")
            continue
        names = [str(qr.CHARACTER_BLUEPRINTS[party_id]["display_name"]) for party_id in campaign.selected_party_ids]
        print("Next expedition solo character: " + ", ".join(names))
        return


def render_hub(
    campaign: CampaignState,
    save_file: str,
    rules_visibility: str = qr.DEFAULT_RULES_VISIBILITY,
) -> None:
    clear_screen()
    district = get_district(campaign.district_id)
    hub_event = get_event(district.hub_event_id)
    print(emoji_label("hub", f"Quiet Relay: 2026 - {hub_event.title} [Fully Data-Driven]"))
    print("-" * 84)
    print(wrap(hub_event.text))
    print()
    print(f"{emoji_label('route', 'District')}: {district.display_name}")
    print(f"Last result: {campaign.last_result}")
    print(f"Record: {campaign.wins} wins / {campaign.losses} losses | Best nodes cleared: {campaign.best_nodes_cleared}")
    print(f"{emoji_label('save', 'Save file')}: {save_file}")
    print(current_progress_text(campaign))
    render_party(campaign, rules_visibility)


def render_node_banner(
    node: DistrictNode,
    campaign: CampaignState,
    rules_visibility: str = qr.DEFAULT_RULES_VISIBILITY,
) -> None:
    clear_screen()
    district = get_district(campaign.district_id)
    event = get_event(node.event_id)
    current_step = campaign.nodes_cleared() + 1
    print(emoji_label("route", district.display_name))
    print(f"{route_preview_header(node, rules_visibility=rules_visibility)}")
    print(f"Route Step {current_step}")
    print(f"{emoji_label('shards', 'Echo Shards on hand')}: {campaign.run_shards}")
    print("-" * 84)
    print(wrap(event.text))
    print()


# ---------------------------------------------------------------------------
# Expedition flow
# ---------------------------------------------------------------------------


def infer_route_bias(campaign: CampaignState) -> str:
    maintenance_nodes = {"flooded_arcade", "service_niche", "drainage_switchback"}
    chapel_nodes = {"witness_chapel", "signal_vestry", "glass_choir_loft"}
    cleared_nodes = set(campaign.cleared_node_ids)
    if cleared_nodes & maintenance_nodes and not cleared_nodes & chapel_nodes:
        return "maintenance"
    if cleared_nodes & chapel_nodes and not cleared_nodes & maintenance_nodes:
        return "chapel"
    return "neutral"


def _variant_matches_node(variant: EncounterVariant, node: DistrictNode, route_bias: str) -> bool:
    if variant.route_families_any and node.route_family not in variant.route_families_any:
        return False
    if variant.risk_tiers_any and node.risk_tier not in variant.risk_tiers_any:
        return False
    if variant.route_bias_any and route_bias not in variant.route_bias_any:
        return False
    return True


def encounter_variants_for_node(campaign: CampaignState, node: DistrictNode) -> List[EncounterVariant]:
    district = get_district(campaign.district_id)
    variants = list(node.encounter_variants)
    if not variants and node.encounter_pool_id:
        variants = list(district.encounter_pools.get(node.encounter_pool_id, ()))
    route_bias = infer_route_bias(campaign)
    return [
        variant
        for variant in variants
        if _variant_matches_node(variant, node, route_bias)
    ]


def choose_weighted_encounter_variant(
    rng: random.Random,
    variants: Sequence[EncounterVariant],
) -> EncounterVariant:
    if not variants:
        raise ValueError("No encounter variants are available.")
    total_weight = sum(max(1, variant.weight) for variant in variants)
    roll = rng.randrange(total_weight)
    running = 0
    for variant in variants:
        running += max(1, variant.weight)
        if roll < running:
            return variant
    return variants[-1]


def resolve_node_encounter(campaign: CampaignState, node: DistrictNode) -> Dict[str, object]:
    cached = campaign.resolved_node_encounters.get(node.node_id)
    if cached:
        return {
            "variant_id": str(cached.get("variant_id", "fixed")),
            "encounter_ids": [str(enc_id) for enc_id in list(cached.get("encounter_ids", []))],
        }

    variants = encounter_variants_for_node(campaign, node)
    if variants:
        variant = choose_weighted_encounter_variant(campaign.rng, variants)
        resolved = {
            "variant_id": variant.variant_id,
            "encounter_ids": list(variant.encounter_ids),
        }
    else:
        resolved = {
            "variant_id": "fixed",
            "encounter_ids": list(node.encounter_ids),
        }

    campaign.resolved_node_encounters[node.node_id] = resolved
    return resolved


def create_slice_enemies(node: DistrictNode, encounter_ids: Optional[Sequence[str]] = None) -> List[qr.Combatant]:
    enemies: List[qr.Combatant] = []
    ids_to_spawn = list(encounter_ids) if encounter_ids is not None else list(node.encounter_ids)
    for idx, encounter_id in enumerate(ids_to_spawn, start=1):
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
    if node.node_id == "bell_tower":
        route_bias = "neutral"
        maintenance_nodes = {"flooded_arcade", "service_niche", "drainage_switchback"}
        chapel_nodes = {"witness_chapel", "signal_vestry", "glass_choir_loft"}
        cleared_nodes = set(campaign.cleared_node_ids)
        if cleared_nodes & maintenance_nodes:
            route_bias = "maintenance"
        elif cleared_nodes & chapel_nodes:
            route_bias = "chapel"
        for enemy in enemies:
            if enemy.entity_id == "orison_last_toll":
                enemy.metadata["orison_route_bias"] = route_bias


def battle_log_to_payload(logger: qr.BattleLogger, limit: int = 80) -> List[Dict[str, object]]:
    return [
        {"round_number": entry.round_number, "text": entry.text}
        for entry in logger.entries[-limit:]
    ]


def battle_log_from_payload(entries: Sequence[object]) -> List[qr.LogEntry]:
    restored: List[qr.LogEntry] = []
    for entry in entries:
        if isinstance(entry, dict):
            restored.append(
                qr.LogEntry(
                    round_number=int(entry.get("round_number", 1)),
                    text=str(entry.get("text", "")),
                )
            )
        else:
            restored.append(qr.LogEntry(round_number=1, text=str(entry)))
    return restored


def create_battle_snapshot(
    campaign: CampaignState,
    node: DistrictNode,
    state: qr.BattleState,
) -> Dict[str, object]:
    return {
        "district_id": campaign.district_id,
        "node_id": node.node_id,
        "node_kind": node.kind,
        "players": [qr.combatant_to_payload(player) for player in state.players],
        "enemies": [qr.combatant_to_payload(enemy) for enemy in state.enemies],
        "battle_state": qr.battle_state_to_payload(state),
        "cursor": qr.battle_cursor_to_payload(state.cursor),
        "rng_state": encode_rng_state(state.rng),
        "recent_log_lines": battle_log_to_payload(state.logger),
    }


def validate_battle_snapshot_for_node(
    campaign: CampaignState,
    node: DistrictNode,
    snapshot: Dict[str, object],
) -> None:
    snapshot_district = str(snapshot.get("district_id", ""))
    snapshot_node = str(snapshot.get("node_id", ""))
    snapshot_kind = str(snapshot.get("node_kind", ""))
    if snapshot_district != campaign.district_id or snapshot_node != node.node_id or snapshot_kind != node.kind:
        raise ValueError(
            "Battle snapshot points to "
            f"{snapshot_district}/{snapshot_node}/{snapshot_kind}, "
            f"but campaign is at {campaign.district_id}/{node.node_id}/{node.kind}."
        )


def resume_battle_from_snapshot(
    campaign: CampaignState,
    node: DistrictNode,
    auto: bool,
    rules_visibility: str = qr.DEFAULT_RULES_VISIBILITY,
) -> Optional[qr.BattleState]:
    snapshot = campaign.battle_snapshot
    if snapshot is None:
        return None
    validate_battle_snapshot_for_node(campaign, node, snapshot)

    logger = qr.BattleLogger(echo=True)
    logger.entries = battle_log_from_payload(list(snapshot.get("recent_log_lines", [])))
    players = [qr.combatant_from_payload(dict(item)) for item in list(snapshot["players"])]
    enemies = [qr.combatant_from_payload(dict(item)) for item in list(snapshot["enemies"])]
    rng = decode_rng_state(snapshot["rng_state"])
    state = qr.battle_state_from_payload(
        dict(snapshot["battle_state"]),
        players=players,
        enemies=enemies,
        rng=rng,
        logger=logger,
        interactive=not auto,
        rules_visibility=rules_visibility,
        recovery_charges=campaign.recovery_charges,
    )
    state.cursor = qr.battle_cursor_from_payload(dict(snapshot["cursor"]))
    campaign.players = state.players
    campaign.rng = state.rng
    campaign.recovery_charges = state.recovery_charges
    return state


def save_battle_snapshot(
    campaign: CampaignState,
    node: DistrictNode,
    state: qr.BattleState,
    save_file: str,
) -> None:
    campaign.players = state.players
    campaign.rng = state.rng
    campaign.recovery_charges = state.recovery_charges
    campaign.current_node_axis_scores = normalize_axis_scores(state.node_axis_scores)
    campaign.node_axis_history[node.node_id] = normalize_axis_scores(state.node_axis_scores)
    campaign.battle_snapshot = create_battle_snapshot(campaign, node, state)
    save_campaign(campaign, save_file)


def auto_choose_option(campaign: CampaignState, option_ids: Sequence[str]) -> str:
    # Practical priorities for auto test runs.
    total_missing_hp = sum(max(0, player.max_hp - player.hp) for player in campaign.players)
    relic_priorities = [
        "maintenance_harness_kit",
        "floodgate_loop_kit",
        "bellglass_notch_kit",
        "applause_knot_kit",
        "choir_hook_kit",
        "slip_ledger_kit",
    ]
    for option_id in relic_priorities:
        if option_id in option_ids:
            return option_id
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


def shop_option_unavailable_reason(
    campaign: CampaignState,
    option: RewardOptionDef,
    bought_option_ids: Sequence[str] = (),
) -> Optional[str]:
    if option.option_id in bought_option_ids:
        return "already bought here"
    if option.effect_type == "grant_relic":
        relic_id = str(option.params["relic_id"])
        if party_has_relic(campaign, relic_id):
            return "already carried"
    cost = option_cost(option)
    if cost > campaign.run_shards:
        missing = cost - campaign.run_shards
        shard_word = "shard" if missing == 1 else "shards"
        return f"need {missing} more {shard_word}"
    return None


def format_shop_option(campaign: CampaignState, option: RewardOptionDef, bought_option_ids: Sequence[str]) -> str:
    label = f"{option.name} ({option_cost(option)}) - {option.description}"
    reason = shop_option_unavailable_reason(campaign, option, bought_option_ids)
    if reason:
        label += f" [{reason}]"
    return label


def purchase_shop_option(
    campaign: CampaignState,
    option_id: str,
    bought_option_ids: Sequence[str],
) -> bool:
    option = REWARD_OPTIONS[option_id]
    reason = shop_option_unavailable_reason(campaign, option, bought_option_ids)
    if reason:
        if reason.startswith("need "):
            print("Not enough Echo Shards.")
        else:
            print(f"{option.name} is unavailable: {reason}.")
        return False

    cost = option_cost(option)
    result, applied = apply_option(campaign, option_id)
    print(wrap(result))
    if not applied:
        campaign.record(f"Shop purchase blocked: {option.name}.")
        return False

    campaign.run_shards -= cost
    campaign.record(f"Shop purchase: {option.name} for {cost} Echo Shards. Balance: {campaign.run_shards}.")
    print(f"Echo Shards remaining: {campaign.run_shards}")
    return True


def option_is_shop_available(campaign: CampaignState, option_id: str, bought_option_ids: Sequence[str]) -> bool:
    return shop_option_unavailable_reason(campaign, REWARD_OPTIONS[option_id], bought_option_ids) is None


def auto_choose_shop_purchase(
    campaign: CampaignState,
    table: RewardTableDef,
    bought_option_ids: Sequence[str],
) -> Optional[str]:
    option_ids = set(table.option_ids)
    total_missing_hp = sum(max(0, player.max_hp - player.hp) for player in campaign.players)

    def available(option_id: str) -> bool:
        return option_id in option_ids and option_is_shop_available(campaign, option_id, bought_option_ids)

    if table.table_id == "service_niche_rewards":
        if available("maintenance_harness_kit"):
            return "maintenance_harness_kit"
        if available("slip_ledger_kit"):
            return "slip_ledger_kit"
        if campaign.prebattle_barrier == 0 and available("ward_flares"):
            return "ward_flares"
        return None

    if table.table_id == "signal_vestry_rewards":
        if available("bellglass_notch_kit"):
            return "bellglass_notch_kit"
        if available("applause_knot_kit"):
            return "applause_knot_kit"
        if campaign.starting_spotlight < 2 and available("stage_light"):
            return "stage_light"
        return None

    if table.table_id == "toll_plaza_rewards":
        if total_missing_hp >= 24 and available("field_dressing"):
            return "field_dressing"
        if campaign.boss_guard_penalty == 0 and available("bellbreaker_oil"):
            return "bellbreaker_oil"
        if available("bellglass_notch_kit"):
            return "bellglass_notch_kit"
        return None

    for option_id in table.option_ids:
        if available(option_id):
            return option_id
    return None


def resolve_choice_table(campaign: CampaignState, table: RewardTableDef, auto: bool) -> None:
    remaining = list(table.option_ids)
    picks_to_make = min(table.pick_count, len(remaining))
    reward_word = "reward" if picks_to_make == 1 else "rewards"
    print(f"Choose {picks_to_make} {reward_word} from {table.name}:")

    for pick_index in range(1, picks_to_make + 1):
        picks_left = picks_to_make - pick_index + 1
        plural = "pick" if picks_left == 1 else "picks"
        if picks_to_make > 1:
            print(f"Pick {pick_index}/{picks_to_make} ({picks_left} {plural} remaining):")
        menu = [(option_id, f"{REWARD_OPTIONS[option_id].name} - {REWARD_OPTIONS[option_id].description}") for option_id in remaining]
        choice = prompt_menu(
            title="",
            options=menu,
            auto=auto,
            auto_choice=auto_choose_option(campaign, remaining) if auto else None,
        )
        remaining.remove(choice)
        result, applied = apply_option(campaign, choice)
        print(wrap(result))
        if applied:
            campaign.record(f"Reward chosen: {REWARD_OPTIONS[choice].name}.")
        else:
            campaign.record(f"Reward had no effect: {REWARD_OPTIONS[choice].name}.")


def resolve_shop_table(campaign: CampaignState, table: RewardTableDef, auto: bool) -> None:
    max_purchases = min(table.max_purchases, len(table.option_ids))
    purchases = 0
    bought_option_ids: List[str] = []
    purchase_word = "purchase" if max_purchases == 1 else "purchases"

    while purchases < max_purchases:
        print(f"\n{table.name}. Echo Shards on hand: {campaign.run_shards}")
        if table.table_id == "toll_plaza_rewards":
            print(f"Spend up to {max_purchases} {purchase_word} before the bell tower.")
        else:
            print(f"Spend up to {max_purchases} {purchase_word} here, or press Enter to leave.")

        options = [
            (option_id, format_shop_option(campaign, REWARD_OPTIONS[option_id], bought_option_ids))
            for option_id in table.option_ids
        ]

        if auto:
            choice = auto_choose_shop_purchase(campaign, table, bought_option_ids)
            if choice is None:
                print("The team keeps the remaining Echo Shards for the route ahead.")
                campaign.record(f"Shop skipped: {table.name}. Balance: {campaign.run_shards}.")
                return
            print(f"Auto shop choice: {REWARD_OPTIONS[choice].name}")
        else:
            for idx, (_, label) in enumerate(options, start=1):
                print(f"  {idx}. {label}")
            print("  Enter: leave")
            raw = input("> ").strip()
            if raw == "":
                print("The team keeps the remaining Echo Shards for the route ahead.")
                campaign.record(f"Shop left: {table.name}. Balance: {campaign.run_shards}.")
                return
            try:
                choice_index = int(raw)
            except ValueError:
                print("Choose a number from the shop, or press Enter to leave.")
                continue
            if not 1 <= choice_index <= len(options):
                print("That number is out of range.")
                continue
            choice = options[choice_index - 1][0]

        if purchase_shop_option(campaign, choice, bought_option_ids):
            bought_option_ids.append(choice)
            purchases += 1

    print("The team closes the route kit and moves on.")


def offer_rewards(campaign: CampaignState, reward_table_id: Optional[str], auto: bool) -> None:
    if not reward_table_id:
        return
    table = REWARD_TABLES[reward_table_id]
    if table.table_type == "shop":
        resolve_shop_table(campaign, table, auto=auto)
        return
    resolve_choice_table(campaign, table, auto=auto)


def choose_recovery_target(campaign: CampaignState, auto: bool) -> Optional[qr.Combatant]:
    candidates = [
        player
        for player in campaign.players
        if player.alive()
        and (player.hp < player.max_hp or player.guard < player.max_guard or player.break_meter < player.max_break)
    ]
    if not candidates:
        return None
    if auto:
        return min(
            candidates,
            key=lambda unit: (
                unit.hp / max(1, unit.max_hp),
                unit.guard / max(1, unit.max_guard),
                unit.break_meter / max(1, unit.max_break),
            ),
        )

    options = [
        (
            str(idx),
            f"{player.name} - heal 45 HP, restore Guard/Break "
            f"(HP {player.hp}/{player.max_hp}, Guard {player.guard}/{player.max_guard}, Break {player.break_meter}/{player.max_break})",
        )
        for idx, player in enumerate(candidates, start=1)
    ]
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
        if 1 <= idx <= len(candidates):
            return candidates[idx - 1]
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
    print(f"{target.name} restores {healed} HP, Guard, and Break.")
    campaign.record(f"Used a recovery charge on {target.name}, restoring HP, Guard, and Break.")


def maybe_interstitial_menu(
    campaign: CampaignState,
    save_file: str,
    auto: bool,
    rules_visibility: str = qr.DEFAULT_RULES_VISIBILITY,
) -> bool:
    """Return True if expedition should continue, False if the player returned to hub."""
    if auto:
        low_hp_count = sum(1 for player in campaign.players if player.hp <= player.max_hp * 0.45)
        if campaign.recovery_charges > 0 and low_hp_count >= 1:
            use_recovery_charge(campaign, auto=True)
        save_campaign(campaign, save_file)
        return True

    while True:
        print(f"\n{emoji_label('continue', 'Expedition menu')}")
        print(f"  1. {emoji_label('continue', 'Continue')}")
        print(f"  2. {emoji_label('inspect', 'Inspect party')}")
        print(f"  3. {emoji_label('recovery', 'Use recovery charge')}")
        print(f"  4. {emoji_label('save', 'Save')}")
        print(f"  5. {emoji_label('back', 'Return to hub')}")
        raw = input("> ").strip()
        if raw in {"", "1"}:
            return True
        if raw == "2":
            render_party(campaign, rules_visibility)
            continue
        if raw == "3":
            use_recovery_charge(campaign, auto=False)
            continue
        if raw == "4":
            save_campaign(campaign, save_file)
            print(f"{emoji_label('save', 'Saved to')}: {save_file}")
            continue
        if raw == "5":
            save_campaign(campaign, save_file)
            print(emoji_label("back", "Returning to hub."))
            return False
        print("Choose a number from the menu.")


def choose_next_node(
    campaign: CampaignState,
    next_node_ids: Sequence[str],
    auto: bool,
    auto_route: str = "first",
    rules_visibility: str = qr.DEFAULT_RULES_VISIBILITY,
) -> Optional[str]:
    if not next_node_ids:
        return None
    if len(next_node_ids) == 1:
        return next_node_ids[0]

    district = get_district(campaign.district_id)
    print(emoji_label("route", "Choose the next route:"))
    for idx, node_id in enumerate(next_node_ids, start=1):
        node = district.nodes[node_id]
        print(f"  {idx}. {route_preview_header(node, rules_visibility=rules_visibility)}")
        detail = route_preview_detail(node, rules_visibility)
        if detail:
            print(indented_wrap(detail))

    if auto:
        if auto_route == "last":
            choice = next_node_ids[-1]
        else:
            choice = next_node_ids[0]
        print(emoji_label("continue", f"Auto route choice: {district.nodes[choice].title}"))
        campaign.record(f"Route chosen: {route_choice_log_text(district.nodes[choice], rules_visibility)}")
        return choice

    while True:
        raw = input("> ").strip()
        try:
            idx = int(raw)
        except ValueError:
            print("Choose a number from the route options.")
            continue
        if 1 <= idx <= len(next_node_ids):
            choice = next_node_ids[idx - 1]
            break
        print("That number is out of range.")

    campaign.record(f"Route chosen: {route_choice_log_text(district.nodes[choice], rules_visibility)}")
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
    save_file: str,
    rules_visibility: str = qr.DEFAULT_RULES_VISIBILITY,
    node_axis_override: Optional[Dict[str, int]] = None,
    axis_file_data: Optional[Dict[str, object]] = None,
) -> bool:
    visibility = qr.normalize_rules_visibility(rules_visibility)
    state = resume_battle_from_snapshot(campaign, node, auto=auto, rules_visibility=visibility)
    if state is None:
        prepare_players_for_battle(campaign)
        axis_scores = prompt_node_axis_scores(
            campaign,
            node,
            auto=auto,
            node_axis_override=node_axis_override,
            axis_file_data=axis_file_data,
        )
        campaign.current_node_axis_scores = axis_scores
        campaign.node_axis_history[node.node_id] = axis_scores
        encounter_info = resolve_node_encounter(campaign, node)
        encounter_ids = [str(enc_id) for enc_id in list(encounter_info["encounter_ids"])]
        save_campaign(campaign, save_file)
        enemies = create_slice_enemies(node, encounter_ids)
        prepare_enemies_for_battle(campaign, node, enemies)

        logger = qr.BattleLogger(echo=True)
        state = qr.BattleState(
            players=campaign.players,
            enemies=enemies,
            rng=campaign.rng,
            logger=logger,
            interactive=not auto,
            rules_visibility=visibility,
            spotlight=campaign.starting_spotlight,
            recovery_charges=campaign.recovery_charges,
            recovery_heal_amount=35,
            node_axis_scores=axis_scores,
        )
        print(f"Battle setup: starting Spotlight {campaign.starting_spotlight}, prebattle barrier {campaign.prebattle_barrier}.")
        if visibility == qr.RULES_VISIBILITY_DEBUG:
            print(
                f"Node axis scores: Power {axis_scores['power']}, "
                f"Precision {axis_scores['precision']}, Composure {axis_scores['composure']}."
            )
        elif visibility == qr.RULES_VISIBILITY_FUZZY:
            print("Node pressure: readable.")
        else:
            print("Node pressure settles over the fight.")
        if str(encounter_info.get("variant_id", "fixed")) != "fixed":
            print(f"Encounter variant: {encounter_info['variant_id']} ({', '.join(encounter_ids)})")
    else:
        campaign.current_node_axis_scores = normalize_axis_scores(state.node_axis_scores)
        campaign.node_axis_history[node.node_id] = normalize_axis_scores(state.node_axis_scores)
        next_actor = None
        if state.cursor.next_actor_index < len(state.cursor.turn_order_ids):
            next_actor_id = state.cursor.turn_order_ids[state.cursor.next_actor_index]
            next_actor = next((unit.name for unit in state.everyone() if unit.entity_id == next_actor_id), next_actor_id)
        print(f"Resuming battle at {node.title}: round {state.round_number}, next actor {next_actor or 'next round'}.")

    def autosave_after_actor(active_state: qr.BattleState) -> None:
        save_battle_snapshot(campaign, node, active_state, save_file)

    winner = qr.run_battle(state, after_actor_turn=autosave_after_actor)
    campaign.battle_snapshot = None
    campaign.players = state.players
    campaign.rng = state.rng
    campaign.recovery_charges = state.recovery_charges

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
        campaign.battle_snapshot = None
        campaign.record(campaign.last_result)
        return False

    campaign.run_shards += node.shards
    print(f"Victory. Echo shards gained: {node.shards}. Echo shards on hand: {campaign.run_shards}")
    campaign.record(f"Cleared {node.title}. Echo Shards balance: {campaign.run_shards}.")
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
    campaign.battle_snapshot = None
    campaign.wins += 1
    campaign.best_nodes_cleared = max(campaign.best_nodes_cleared, campaign.nodes_cleared())
    campaign.last_result = f"Victory in {district.display_name}. Echo shards carried out: {campaign.run_shards}."
    campaign.record(campaign.last_result)


def run_expedition(
    campaign: CampaignState,
    auto: bool,
    save_file: str,
    log_dir: str,
    auto_route: str = "first",
    rules_visibility: str = qr.DEFAULT_RULES_VISIBILITY,
    node_axis_override: Optional[Dict[str, int]] = None,
    axis_file_data: Optional[Dict[str, object]] = None,
) -> None:
    visibility = qr.normalize_rules_visibility(rules_visibility)
    district = get_district(campaign.district_id)
    report_file = report_path_for_save(save_file)
    while campaign.expedition_active and campaign.current_node_id is not None:
        node = district.nodes[campaign.current_node_id]
        render_node_banner(node, campaign, visibility)

        if node.kind in {"battle", "boss"}:
            success = resolve_battle_node(
                campaign,
                node,
                auto=auto,
                log_dir=log_dir,
                save_file=save_file,
                rules_visibility=visibility,
                node_axis_override=node_axis_override,
                axis_file_data=axis_file_data,
            )
            if not success:
                save_campaign(campaign, save_file)
                write_run_report(campaign, report_file)
                return
        elif node.kind == "event":
            resolve_event_node(campaign, node, auto=auto)
            save_campaign(campaign, save_file)
        else:
            raise ValueError(f"Unknown node kind: {node.kind}")

        if node.node_id not in campaign.cleared_node_ids:
            campaign.cleared_node_ids.append(node.node_id)
        campaign.best_nodes_cleared = max(campaign.best_nodes_cleared, campaign.nodes_cleared())

        next_node_id = choose_next_node(
            campaign,
            node.next_node_ids,
            auto=auto,
            auto_route=auto_route,
            rules_visibility=visibility,
        )
        campaign.current_node_id = next_node_id
        save_campaign(campaign, save_file)

        if campaign.current_node_id is None:
            finish_victory(campaign)
            save_campaign(campaign, save_file)
            write_run_report(campaign, report_file)
            return

        if not maybe_interstitial_menu(campaign, save_file=save_file, auto=auto, rules_visibility=visibility):
            write_run_report(campaign, report_file)
            return

    write_run_report(campaign, report_file)


# ---------------------------------------------------------------------------
# Hub flow
# ---------------------------------------------------------------------------


def hub_menu(
    campaign: CampaignState,
    save_file: str,
    auto: bool,
    log_dir: str,
    auto_route: str = "first",
    rules_visibility: str = qr.DEFAULT_RULES_VISIBILITY,
    node_axis_override: Optional[Dict[str, int]] = None,
    axis_file_data: Optional[Dict[str, object]] = None,
) -> None:
    visibility = qr.normalize_rules_visibility(rules_visibility)
    report_file = report_path_for_save(save_file)
    while True:
        render_hub(campaign, save_file, visibility)

        if auto:
            if campaign.expedition_active:
                run_expedition(
                    campaign,
                    auto=True,
                    save_file=save_file,
                    log_dir=log_dir,
                    auto_route=auto_route,
                    rules_visibility=visibility,
                    node_axis_override=node_axis_override,
                    axis_file_data=axis_file_data,
                )
            else:
                reset_party_for_new_expedition(campaign, district_id=campaign.district_id)
                run_expedition(
                    campaign,
                    auto=True,
                    save_file=save_file,
                    log_dir=log_dir,
                    auto_route=auto_route,
                    rules_visibility=visibility,
                    node_axis_override=node_axis_override,
                    axis_file_data=axis_file_data,
                )
            save_campaign(campaign, save_file)
            write_run_report(campaign, report_file)
            return

        options: List[Tuple[str, str]] = []
        if campaign.expedition_active:
            options.append(("resume", menu_label("resume", "Resume expedition")))
        else:
            options.append(("start", menu_label("start", "Start new expedition")))
            options.append(("party", menu_label("party", "Configure solo character")))
        options.extend(
            [
                ("inspect", menu_label("inspect", "Inspect party")),
                ("save", menu_label("save", "Save")),
                ("load", menu_label("load", "Load")),
                ("quit", menu_label("quit", "Quit")),
            ]
        )

        choice = prompt_menu(emoji_label("hub", "Hub menu"), options)

        if choice == "resume":
            run_expedition(
                campaign,
                auto=False,
                save_file=save_file,
                log_dir=log_dir,
                auto_route=auto_route,
                rules_visibility=visibility,
                node_axis_override=node_axis_override,
                axis_file_data=axis_file_data,
            )
            save_campaign(campaign, save_file)
            continue
        if choice == "start":
            reset_party_for_new_expedition(campaign, district_id=campaign.district_id)
            save_campaign(campaign, save_file)
            run_expedition(
                campaign,
                auto=False,
                save_file=save_file,
                log_dir=log_dir,
                auto_route=auto_route,
                rules_visibility=visibility,
                node_axis_override=node_axis_override,
                axis_file_data=axis_file_data,
            )
            save_campaign(campaign, save_file)
            continue
        if choice == "inspect":
            render_party(campaign, visibility)
            input("Press Enter to return to the hub.")
            continue
        if choice == "party":
            configure_party(campaign)
            save_campaign(campaign, save_file)
            input("Press Enter to return to the hub.")
            continue
        if choice == "save":
            save_campaign(campaign, save_file)
            write_run_report(campaign, report_file)
            print(f"{emoji_label('save', 'Saved to')}: {save_file}")
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
            campaign.battle_snapshot = loaded.battle_snapshot
            campaign.selected_party_ids = loaded.selected_party_ids
            campaign.solo_character_id = loaded.solo_character_id
            campaign.current_node_axis_scores = loaded.current_node_axis_scores
            campaign.node_axis_history = loaded.node_axis_history
            campaign.resolved_node_encounters = loaded.resolved_node_encounters
            print(f"{emoji_label('load', 'Loaded')}: {save_file}")
            input("Press Enter to continue.")
            continue
        if choice == "quit":
            save_campaign(campaign, save_file)
            write_run_report(campaign, report_file)
            print(emoji_label("back", "Session ended."))
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
    parser.add_argument(
        "--solo-character",
        default=DEFAULT_PARTY[0],
        choices=sorted(qr.CHARACTER_BLUEPRINTS.keys()),
        help="Solo character id for the hardmode vertical slice.",
    )
    parser.add_argument(
        "--party",
        default=None,
        help="Legacy comma-separated character ids. Solo mode uses the first id.",
    )
    parser.add_argument(
        "--node-axis",
        nargs=3,
        type=int,
        metavar=("POWER", "PRECISION", "COMPOSURE"),
        help="Use fixed node-axis scores for every node.",
    )
    parser.add_argument(
        "--axis-file",
        default=None,
        help="JSON file containing default and per-node axis scores.",
    )
    parser.add_argument(
        "--auto-route",
        default="first",
        choices=AUTO_ROUTE_CHOICES,
        help="Auto route choice when a node branches (first or last option).",
    )
    parser.add_argument(
        "--rules-visibility",
        default=qr.DEFAULT_RULES_VISIBILITY,
        choices=qr.RULES_VISIBILITY_CHOICES,
        help="How explicit combat rules should be in player-facing logs and previews.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = parse_args(raw_argv)
    rules_visibility = qr.normalize_rules_visibility(args.rules_visibility)
    explicit_solo = any(item == "--solo-character" or item.startswith("--solo-character=") for item in raw_argv)
    try:
        if args.party:
            selected_party_ids = [validate_selected_party_ids(args.party)[0]]
        elif args.load and not args.fresh and not explicit_solo:
            selected_party_ids = None
        else:
            selected_party_ids = [validate_solo_character_id(args.solo_character)]
    except ValueError as exc:
        print(f"Solo character error: {exc}")
        return 2

    node_axis_override = None
    if args.node_axis is not None:
        node_axis_override = normalize_axis_scores(
            {"power": args.node_axis[0], "precision": args.node_axis[1], "composure": args.node_axis[2]}
        )

    axis_file_data = None
    if args.axis_file:
        try:
            axis_file_data = load_axis_file(args.axis_file)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"Axis file error: {exc}")
            return 2

    if args.load and not os.path.exists(args.save_file):
        print(f"No save file found at {args.save_file}")
        return 2

    if args.load and not args.fresh:
        campaign = load_campaign(args.save_file)
        if selected_party_ids is not None:
            solo_character = validate_solo_character_id(selected_party_ids[0])
            campaign.solo_character_id = solo_character
            campaign.selected_party_ids = [solo_character]
            if not campaign.expedition_active:
                campaign.players = qr.build_party([solo_character])
    else:
        district_id = args.district if args.district in DISTRICTS else DEFAULT_DISTRICT_ID
        campaign = new_campaign(args.seed, district_id=district_id, selected_party_ids=selected_party_ids)
        if os.path.exists(args.save_file) and not args.fresh and not args.auto:
            print(f"Existing save found at {args.save_file}. You can load it from the hub menu.")

    hub_menu(
        campaign,
        save_file=args.save_file,
        auto=args.auto,
        log_dir=args.log_dir,
        auto_route=args.auto_route,
        rules_visibility=rules_visibility,
        node_axis_override=node_axis_override,
        axis_file_data=axis_file_data,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
