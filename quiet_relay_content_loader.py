#!/usr/bin/env python3
"""
Quiet Relay content loader.

Loads data-driven JSON content files and validates cross-file references so the
combat engine and vertical slice can keep runtime code simple.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Set


REQUIRED_FILES = {
    "rules": "rules.json",
    "affinities": "affinities.json",
    "characters": "characters.json",
    "skills": "skills.json",
    "enemies": "enemies.json",
    "bosses": "bosses.json",
    "weapons": "weapons.json",
    "relics": "relics.json",
    "events": "events.json",
    "reward_tables": "reward_tables.json",
    "districts": "districts.json",
}
ALLOWED_RELIC_TRIGGERS = {"reaction_success", "before_offense", "after_offense"}
ALLOWED_RISK_TIERS = {"low", "medium", "high"}
ALLOWED_PACING_STAGES = {"opener", "build", "pressure", "boss_prep", "finale"}
ALLOWED_INPUT_DIMENSIONS = {"power", "precision", "composure"}
ALLOWED_REACTIONS = {"guard", "dodge", "parry"}
ALLOWED_DEFENSIVE_READ_TAGS = {"heavy", "channel", "burst_start"}
ALLOWED_REWARD_TABLE_TYPES = {"choice", "shop"}
ALLOWED_RELIC_EFFECTS = {
    "apply_status_to_attacker",
    "apply_status_to_self",
    "gain_spotlight",
    "apply_break_to_attacker",
    "restore_guard_self",
    "gain_barrier_self",
    "cleanse_minor_self",
    "set_next_self_risk_reduction",
    "store_charge_bonus",
    "consume_stored_charge_bonus",
}
ALLOWED_EQUIPMENT_HANDEDNESS = {"one_handed", "two_handed", "paired"}
ALLOWED_EQUIPMENT_SLOTS = {"main_hand", "off_hand", "both_hands"}


class ContentError(ValueError):
    """Raised when content files are missing or internally inconsistent."""


def _is_short_slug(value: str, max_len: int = 32) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= max_len
        and all(ch.islower() or ch.isdigit() or ch in {"_", "-"} for ch in value)
    )


def _validate_short_text(owner: str, field_name: str, value: Any, max_len: int = 100) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"{owner} {field_name} must be a non-empty string when present.")
    if "\n" in value or "\r" in value:
        raise ContentError(f"{owner} {field_name} must be a single terminal-readable line.")
    if len(value) > max_len:
        raise ContentError(f"{owner} {field_name} must be {max_len} characters or fewer.")


def _validate_preview_tags(owner: str, field_name: str, value: Any, max_items: int = 3) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise ContentError(f"{owner} {field_name} must be a list when present.")
    if len(value) > max_items:
        raise ContentError(f"{owner} {field_name} must contain at most {max_items} tags.")
    for tag in value:
        if not isinstance(tag, str) or not _is_short_slug(tag, max_len=24):
            raise ContentError(
                f"{owner} {field_name} tags must be lowercase short slugs such as sustain or boss_prep."
            )


def _validate_slug_list(
    owner: str,
    field_name: str,
    value: Any,
    *,
    allowed: Optional[Set[str]] = None,
    max_items: int = 8,
) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise ContentError(f"{owner} {field_name} must be a list when present.")
    if len(value) > max_items:
        raise ContentError(f"{owner} {field_name} must contain at most {max_items} entries.")
    for item in value:
        if not isinstance(item, str) or not _is_short_slug(item, max_len=48):
            raise ContentError(f"{owner} {field_name} entries must be lowercase short slugs.")
        if allowed is not None and item not in allowed:
            raise ContentError(f"{owner} {field_name} contains unsupported value '{item}'.")


def _validate_encounter_variant(owner: str, raw: Any, valid_encounters: Set[str]) -> None:
    if not isinstance(raw, dict):
        raise ContentError(f"{owner} encounter variant must be an object.")
    variant_id = raw.get("variant_id")
    if not isinstance(variant_id, str) or not _is_short_slug(variant_id, max_len=48):
        raise ContentError(f"{owner} encounter variant must define a short slug variant_id.")
    encounter_ids = raw.get("encounter_ids")
    if not isinstance(encounter_ids, list) or not encounter_ids:
        raise ContentError(f"{owner} variant '{variant_id}' must define a non-empty encounter_ids list.")
    unknown_encounters = [str(item) for item in encounter_ids if item not in valid_encounters]
    if unknown_encounters:
        raise ContentError(f"{owner} variant '{variant_id}' references unknown encounters: {unknown_encounters}")
    weight = raw.get("weight", 1)
    if not isinstance(weight, int) or isinstance(weight, bool) or weight < 1:
        raise ContentError(f"{owner} variant '{variant_id}' weight must be an integer >= 1.")
    _validate_slug_list(owner, "route_families_any", raw.get("route_families_any"))
    _validate_slug_list(owner, "risk_tiers_any", raw.get("risk_tiers_any"), allowed=ALLOWED_RISK_TIERS)
    _validate_slug_list(
        owner,
        "route_bias_any",
        raw.get("route_bias_any"),
        allowed={"maintenance", "chapel", "neutral"},
    )
    _validate_preview_tags(owner, "flavor_tags", raw.get("flavor_tags"), max_items=5)


def _validate_encounter_variants(owner: str, raw_variants: Any, valid_encounters: Set[str]) -> bool:
    if raw_variants is None:
        return False
    if not isinstance(raw_variants, list):
        raise ContentError(f"{owner} encounter_variants must be a list when present.")
    if not raw_variants:
        return False
    seen: Set[str] = set()
    for raw_variant in raw_variants:
        _validate_encounter_variant(owner, raw_variant, valid_encounters)
        variant_id = str(raw_variant["variant_id"])
        if variant_id in seen:
            raise ContentError(f"{owner} duplicate encounter variant_id '{variant_id}'.")
        seen.add(variant_id)
    return True


def _encounter_variants_contain_boss(raw_variants: Any, bosses: Mapping[str, Any]) -> bool:
    if not isinstance(raw_variants, list):
        return False
    for raw_variant in raw_variants:
        if not isinstance(raw_variant, dict):
            continue
        for encounter_id in raw_variant.get("encounter_ids", []):
            if encounter_id in bosses:
                return True
    return False


@dataclass
class ContentBundle:
    base_dir: Path
    rules: Dict[str, Any]
    affinities: Dict[str, Any]
    characters: Dict[str, Any]
    skills: Dict[str, Any]
    enemies: Dict[str, Any]
    bosses: Dict[str, Any]
    weapons: Dict[str, Any]
    relics: Dict[str, Any]
    events: Dict[str, Any]
    reward_tables: Dict[str, Any]
    reward_options: Dict[str, Any]
    districts: Dict[str, Any]
    default_district_id: str
    character_blueprints: Dict[str, Any]
    affinity_order: List[str]
    affinity_strong_vs: Dict[str, str]
    affinity_status: Dict[str, str]

    @property
    def skill_data(self) -> Dict[str, Any]:
        return self.skills

    @property
    def enemy_data(self) -> Dict[str, Any]:
        return self.enemies

    @property
    def boss_data(self) -> Dict[str, Any]:
        return self.bosses

    @property
    def weapon_data(self) -> Dict[str, Any]:
        return self.weapons

    @property
    def relic_data(self) -> Dict[str, Any]:
        return self.relics


def resolve_content_dir(reference_file: Optional[str] = None, explicit_dir: Optional[str | Path] = None) -> Path:
    if explicit_dir is not None:
        return Path(explicit_dir)
    env_dir = os.environ.get("QR_CONTENT_DIR")
    if env_dir:
        return Path(env_dir)
    if reference_file is not None:
        return Path(reference_file).resolve().with_name("quiet_relay_content")
    return Path.cwd() / "quiet_relay_content"


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise ContentError(f"Missing content file: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ContentError(f"Top-level JSON must be an object: {path}")
    return data


def _unwrap_map(doc: Mapping[str, Any], key: str) -> Dict[str, Any]:
    raw = doc.get(key) if isinstance(doc, dict) else None
    if isinstance(raw, dict):
        return dict(raw)
    return dict(doc)


def _materialize_character_blueprints(rules: Mapping[str, Any], characters: Mapping[str, Any]) -> Dict[str, Any]:
    shared_skills = list(rules.get("shared_start_skills", []))
    out: Dict[str, Any] = {}
    for char_id, raw in characters.items():
        if not isinstance(raw, dict):
            raise ContentError(f"Character '{char_id}' must be an object.")
        merged = dict(raw)
        explicit_skills = raw.get("skills")
        if isinstance(explicit_skills, list) and explicit_skills:
            merged_skills = [str(skill_id) for skill_id in explicit_skills]
        else:
            unique_skills = list(raw.get("unique_start_skills", []))
            merged_skills = []
            for skill_id in shared_skills + unique_skills:
                if skill_id not in merged_skills:
                    merged_skills.append(skill_id)
        merged["skills"] = merged_skills
        merged.setdefault("starting_relics", [])
        out[char_id] = merged
    return out


def _validate_profiles(rules: Mapping[str, Any]) -> None:
    stat_profiles = rules.get("stat_profiles")
    if not isinstance(stat_profiles, dict):
        raise ContentError("rules.json must define stat_profiles.")
    for group_name in ("hp", "guard", "break", "speed"):
        mapping = stat_profiles.get(group_name)
        if not isinstance(mapping, dict):
            raise ContentError(f"rules.json stat_profiles.{group_name} must be an object.")
        for key in ("low", "medium", "high"):
            if key not in mapping:
                raise ContentError(f"rules.json stat_profiles.{group_name} missing '{key}'.")


def _validate_defensive_reads(rules: Mapping[str, Any]) -> None:
    defensive_reads = rules.get("defensive_reads")
    if defensive_reads is None:
        return
    if not isinstance(defensive_reads, dict):
        raise ContentError("rules.json defensive_reads must be an object when present.")
    resolution = defensive_reads.get("profile_resolution")
    if resolution is not None and resolution != "first_matching_incoming_tag":
        raise ContentError("rules.json defensive_reads.profile_resolution must be first_matching_incoming_tag.")
    profiles = defensive_reads.get("profiles")
    if not isinstance(profiles, dict):
        raise ContentError("rules.json defensive_reads.profiles must be an object when present.")
    for tag, profile in profiles.items():
        if not isinstance(tag, str) or not tag.strip():
            raise ContentError("rules.json defensive_reads profile keys must be non-empty strings.")
        if tag not in ALLOWED_DEFENSIVE_READ_TAGS:
            raise ContentError(
                f"rules.json defensive_reads profile '{tag}' is not supported in phase 1; "
                f"use one of {sorted(ALLOWED_DEFENSIVE_READ_TAGS)}."
            )
        if not isinstance(profile, dict):
            raise ContentError(f"rules.json defensive_reads.profiles.{tag} must be an object.")
        primary = profile.get("primary")
        secondary = profile.get("secondary")
        if primary not in ALLOWED_INPUT_DIMENSIONS:
            raise ContentError(
                f"rules.json defensive_reads.profiles.{tag}.primary must be one of "
                f"{sorted(ALLOWED_INPUT_DIMENSIONS)}."
            )
        if secondary not in ALLOWED_INPUT_DIMENSIONS:
            raise ContentError(
                f"rules.json defensive_reads.profiles.{tag}.secondary must be one of "
                f"{sorted(ALLOWED_INPUT_DIMENSIONS)}."
            )
        preferred_reactions = profile.get("preferred_reactions")
        if not isinstance(preferred_reactions, list) or not preferred_reactions:
            raise ContentError(
                f"rules.json defensive_reads.profiles.{tag}.preferred_reactions must be a non-empty list."
            )
        invalid_reactions = [item for item in preferred_reactions if item not in ALLOWED_REACTIONS]
        if invalid_reactions:
            raise ContentError(
                f"rules.json defensive_reads.profiles.{tag}.preferred_reactions contains invalid reactions: "
                f"{invalid_reactions}"
            )


def _validate_affinities(affinities_doc: Mapping[str, Any]) -> tuple[list[str], dict[str, str], dict[str, str]]:
    order = list(affinities_doc.get("order", []))
    affinity_map = affinities_doc.get("affinities")
    if not order or not isinstance(affinity_map, dict):
        raise ContentError("affinities.json must define 'order' and 'affinities'.")

    if set(order) != set(affinity_map.keys()):
        missing_in_order = set(affinity_map.keys()) - set(order)
        missing_in_map = set(order) - set(affinity_map.keys())
        raise ContentError(
            "Affinity ids in order and affinities map do not match: "
            f"missing_in_order={sorted(missing_in_order)}, missing_in_map={sorted(missing_in_map)}"
        )

    strong_vs: Dict[str, str] = {}
    status_map: Dict[str, str] = {}
    for affinity_id in order:
        raw = affinity_map[affinity_id]
        if not isinstance(raw, dict):
            raise ContentError(f"Affinity '{affinity_id}' must be an object.")
        target = raw.get("strong_vs")
        status = raw.get("status")
        if target not in affinity_map:
            raise ContentError(f"Affinity '{affinity_id}' strong_vs references unknown affinity '{target}'.")
        if not isinstance(status, str) or not status:
            raise ContentError(f"Affinity '{affinity_id}' must define a non-empty status.")
        strong_vs[affinity_id] = target
        status_map[affinity_id] = status
    return order, strong_vs, status_map


def _validate_skills(skills: Mapping[str, Any], valid_affinities: Set[str], characters: Set[str]) -> None:
    for skill_id, raw in skills.items():
        if not isinstance(raw, dict):
            raise ContentError(f"Skill '{skill_id}' must be an object.")
        owner = raw.get("owner")
        if owner != "shared" and owner not in characters:
            raise ContentError(f"Skill '{skill_id}' owner '{owner}' is not shared and not a known character.")
        affinity = raw.get("affinity")
        if affinity != "neutral" and affinity not in valid_affinities:
            raise ContentError(f"Skill '{skill_id}' uses unknown affinity '{affinity}'.")
        scale = raw.get("scale")
        output = raw.get("output")
        if not isinstance(scale, dict) or not isinstance(output, dict):
            raise ContentError(f"Skill '{skill_id}' must define scale and output objects.")
        for field_name in ("primary", "secondary"):
            if field_name not in scale:
                raise ContentError(f"Skill '{skill_id}' scale missing '{field_name}'.")
        for field_name in ("damage", "break"):
            if field_name not in output:
                raise ContentError(f"Skill '{skill_id}' output missing '{field_name}'.")
        if "effect_id" not in raw:
            raise ContentError(f"Skill '{skill_id}' is missing effect_id.")
        tags = raw.get("tags", [])
        if tags is not None:
            if not isinstance(tags, list) or not all(isinstance(tag, str) and tag for tag in tags):
                raise ContentError(f"Skill '{skill_id}' tags must be a list of non-empty strings when present.")


def _validate_characters(
    rules: Mapping[str, Any],
    characters: Mapping[str, Any],
    skills: Mapping[str, Any],
    weapons: Mapping[str, Any],
    relics: Mapping[str, Any],
    valid_affinities: Set[str],
) -> None:
    shared_skills = list(rules.get("shared_start_skills", []))
    for skill_id in shared_skills:
        if skill_id not in skills:
            raise ContentError(f"Shared starting skill '{skill_id}' does not exist in skills.json.")

    for char_id, raw in characters.items():
        affinity = raw.get("default_affinity")
        if affinity not in valid_affinities:
            raise ContentError(f"Character '{char_id}' uses unknown affinity '{affinity}'.")
        weapon_id = raw.get("weapon")
        if weapon_id not in weapons:
            raise ContentError(f"Character '{char_id}' references unknown weapon '{weapon_id}'.")
        stat_profile = raw.get("stat_profile")
        if not isinstance(stat_profile, dict):
            raise ContentError(f"Character '{char_id}' must define stat_profile.")
        for key in ("hp", "guard", "break", "speed"):
            if key not in stat_profile:
                raise ContentError(f"Character '{char_id}' stat_profile missing '{key}'.")
            value = stat_profile[key]
            if value not in rules["stat_profiles"][key]:
                raise ContentError(
                    f"Character '{char_id}' stat_profile.{key}='{value}' is not valid for rules.json.")
        skill_ids = raw.get("skills") if isinstance(raw.get("skills"), list) else raw.get("unique_start_skills", [])
        for skill_id in skill_ids:
            if skill_id not in skills:
                raise ContentError(f"Character '{char_id}' references unknown skill '{skill_id}'.")
        for relic_id in raw.get("starting_relics", []):
            if relic_id not in relics:
                raise ContentError(f"Character '{char_id}' references unknown relic '{relic_id}'.")
        starting_equipment = raw.get("starting_equipment")
        if starting_equipment is not None:
            if not isinstance(starting_equipment, dict) or not starting_equipment:
                raise ContentError(f"Character '{char_id}' starting_equipment must be a non-empty object when present.")
            unknown_slots = [slot for slot in starting_equipment.keys() if slot not in ALLOWED_EQUIPMENT_SLOTS]
            if unknown_slots:
                raise ContentError(f"Character '{char_id}' uses invalid starting equipment slots: {unknown_slots}")
            if "both_hands" in starting_equipment and ("main_hand" in starting_equipment or "off_hand" in starting_equipment):
                raise ContentError(f"Character '{char_id}' cannot mix both_hands with main_hand/off_hand in starting_equipment.")
            for slot_name, item_id in starting_equipment.items():
                if item_id not in weapons:
                    raise ContentError(f"Character '{char_id}' references unknown starting equipment '{item_id}'.")
                item_raw = weapons[item_id]
                item_slot = str(item_raw.get("slot", ""))
                if item_slot != slot_name:
                    raise ContentError(
                        f"Character '{char_id}' equips '{item_id}' in {slot_name}, "
                        f"but the item declares slot '{item_slot}'."
                    )
            if "both_hands" in starting_equipment and str(raw.get("weapon", "")) != str(starting_equipment["both_hands"]):
                raise ContentError(f"Character '{char_id}' weapon must match both_hands starting equipment.")
            if "both_hands" not in starting_equipment and "main_hand" in starting_equipment and str(raw.get("weapon", "")) != str(starting_equipment["main_hand"]):
                raise ContentError(f"Character '{char_id}' weapon must match main_hand starting equipment.")


def _validate_enemies(enemies: Mapping[str, Any], valid_affinities: Set[str], rules: Mapping[str, Any]) -> None:
    for enemy_id, raw in enemies.items():
        affinity = raw.get("affinity")
        if affinity not in valid_affinities:
            raise ContentError(f"Enemy '{enemy_id}' uses unknown affinity '{affinity}'.")
        stat_profile = raw.get("stat_profile")
        if not isinstance(stat_profile, dict):
            raise ContentError(f"Enemy '{enemy_id}' must define stat_profile.")
        for key in ("hp", "guard", "break", "speed"):
            if key not in stat_profile:
                raise ContentError(f"Enemy '{enemy_id}' stat_profile missing '{key}'.")
            value = stat_profile[key]
            if value not in rules["stat_profiles"][key]:
                raise ContentError(f"Enemy '{enemy_id}' stat_profile.{key}='{value}' is invalid.")
        action_tags = raw.get("action_tags")
        if action_tags is not None:
            if not isinstance(action_tags, dict):
                raise ContentError(f"Enemy '{enemy_id}' action_tags must be an object when present.")
            for action_name, tags in action_tags.items():
                if not isinstance(action_name, str) or not action_name:
                    raise ContentError(f"Enemy '{enemy_id}' has an invalid action_tags key.")
                if not isinstance(tags, list) or not all(isinstance(tag, str) and tag for tag in tags):
                    raise ContentError(f"Enemy '{enemy_id}' action_tags.{action_name} must be a list of non-empty strings.")


def _validate_bosses(bosses: Mapping[str, Any], valid_affinities: Set[str]) -> None:
    for boss_id, raw in bosses.items():
        primary = raw.get("primary_affinity")
        if primary not in valid_affinities:
            raise ContentError(f"Boss '{boss_id}' uses unknown primary_affinity '{primary}'.")
        secondary = raw.get("secondary_affinity")
        if secondary is not None and secondary not in valid_affinities:
            raise ContentError(f"Boss '{boss_id}' uses unknown secondary_affinity '{secondary}'.")
        base_stats = raw.get("base_stats")
        if not isinstance(base_stats, dict):
            raise ContentError(f"Boss '{boss_id}' must define base_stats.")
        for key in ("hp", "guard", "break", "speed"):
            if key not in base_stats:
                raise ContentError(f"Boss '{boss_id}' base_stats missing '{key}'.")
        action_tags = raw.get("action_tags")
        if action_tags is not None:
            if not isinstance(action_tags, dict):
                raise ContentError(f"Boss '{boss_id}' action_tags must be an object when present.")
            for action_name, tags in action_tags.items():
                if not isinstance(action_name, str) or not action_name:
                    raise ContentError(f"Boss '{boss_id}' has an invalid action_tags key.")
                if not isinstance(tags, list) or not all(isinstance(tag, str) and tag for tag in tags):
                    raise ContentError(f"Boss '{boss_id}' action_tags.{action_name} must be a list of non-empty strings.")


def _validate_weapons(weapons: Mapping[str, Any], valid_affinities: Set[str]) -> None:
    for weapon_id, raw in weapons.items():
        if not isinstance(raw, dict):
            raise ContentError(f"Weapon '{weapon_id}' must be an object.")
        affinity_hint = raw.get("affinity_hint")
        if affinity_hint is not None and affinity_hint not in valid_affinities:
            raise ContentError(f"Weapon '{weapon_id}' has invalid affinity_hint '{affinity_hint}'.")
        if "display_name" not in raw:
            raise ContentError(f"Weapon '{weapon_id}' is missing display_name.")
        type_name = raw.get("type")
        if not isinstance(type_name, str) or not type_name.strip():
            raise ContentError(f"Weapon '{weapon_id}' must define a non-empty type.")
        handedness = raw.get("handedness")
        if handedness not in ALLOWED_EQUIPMENT_HANDEDNESS:
            raise ContentError(f"Weapon '{weapon_id}' has invalid handedness '{handedness}'.")
        slot_name = raw.get("slot")
        if slot_name not in ALLOWED_EQUIPMENT_SLOTS:
            raise ContentError(f"Weapon '{weapon_id}' has invalid slot '{slot_name}'.")
        if handedness in {"two_handed", "paired"} and slot_name != "both_hands":
            raise ContentError(f"Weapon '{weapon_id}' must use both_hands for handedness '{handedness}'.")
        if handedness == "one_handed" and slot_name == "both_hands":
            raise ContentError(f"Weapon '{weapon_id}' cannot be one_handed and both_hands.")
        tags = raw.get("tags")
        if not isinstance(tags, list) or not all(isinstance(tag, str) and tag for tag in tags):
            raise ContentError(f"Weapon '{weapon_id}' tags must be a list of non-empty strings.")
        description = raw.get("description")
        if not isinstance(description, str) or not description.strip():
            raise ContentError(f"Weapon '{weapon_id}' must define a non-empty description.")
        for field_name in (
            "base_damage_bonus",
            "damage_multiplier",
            "break_multiplier",
            "hit_bonus",
            "crit_bonus",
            "guard_bonus",
            "evasion_bonus",
            "ap_bonus",
            "healing_multiplier",
            "status_success_bonus",
            "reaction_bonus",
        ):
            value = raw.get(field_name)
            if value is None:
                continue
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ContentError(f"Weapon '{weapon_id}' field '{field_name}' must be numeric when present.")
        action_modifiers = raw.get("action_modifiers")
        if action_modifiers is not None:
            if not isinstance(action_modifiers, dict):
                raise ContentError(f"Weapon '{weapon_id}' action_modifiers must be an object when present.")
            for action_id, modifier_payload in action_modifiers.items():
                if not isinstance(action_id, str) or not action_id:
                    raise ContentError(f"Weapon '{weapon_id}' action_modifiers keys must be non-empty strings.")
                if not isinstance(modifier_payload, dict):
                    raise ContentError(f"Weapon '{weapon_id}' action_modifiers.{action_id} must be an object.")
        class_bonuses = raw.get("class_bonuses")
        if class_bonuses is not None:
            if not isinstance(class_bonuses, dict):
                raise ContentError(f"Weapon '{weapon_id}' class_bonuses must be an object when present.")
            for class_id, modifier_payload in class_bonuses.items():
                if not isinstance(class_id, str) or not class_id:
                    raise ContentError(f"Weapon '{weapon_id}' class_bonuses keys must be non-empty strings.")
                if not isinstance(modifier_payload, dict):
                    raise ContentError(f"Weapon '{weapon_id}' class_bonuses.{class_id} must be an object.")


def _validate_relics(relics: Mapping[str, Any]) -> None:
    for relic_id, raw in relics.items():
        if not isinstance(raw, dict):
            raise ContentError(f"Relic '{relic_id}' must be an object.")
        if "display_name" not in raw:
            raise ContentError(f"Relic '{relic_id}' is missing 'display_name'.")
        if "effect_id" not in raw and "effect" not in raw:
            raise ContentError(f"Relic '{relic_id}' must define either effect_id or effect.")
        if "summary" not in raw and "effect" not in raw:
            raise ContentError(f"Relic '{relic_id}' must define either summary or effect text.")
        trigger_rules = raw.get("trigger_rules")
        if trigger_rules is None:
            continue
        if not isinstance(trigger_rules, list):
            raise ContentError(f"Relic '{relic_id}' trigger_rules must be a list when present.")
        for idx, rule in enumerate(trigger_rules):
            if not isinstance(rule, dict):
                raise ContentError(f"Relic '{relic_id}' trigger rule #{idx + 1} must be an object.")
            trigger = rule.get("trigger")
            if trigger not in ALLOWED_RELIC_TRIGGERS:
                raise ContentError(
                    f"Relic '{relic_id}' trigger rule #{idx + 1} has invalid trigger '{trigger}'.")
            reaction = rule.get("reaction")
            if reaction is not None and reaction not in {"guard", "dodge", "parry"}:
                raise ContentError(
                    f"Relic '{relic_id}' trigger rule #{idx + 1} has invalid reaction '{reaction}'.")
            incoming_tags_any = rule.get("incoming_tags_any")
            if incoming_tags_any is not None:
                if not isinstance(incoming_tags_any, list) or not all(isinstance(tag, str) and tag for tag in incoming_tags_any):
                    raise ContentError(
                        f"Relic '{relic_id}' trigger rule #{idx + 1} incoming_tags_any must be a list of non-empty strings.")
            effects = rule.get("effects")
            if not isinstance(effects, list) or not effects:
                raise ContentError(f"Relic '{relic_id}' trigger rule #{idx + 1} must define a non-empty effects list.")
            for effect_idx, effect in enumerate(effects):
                if not isinstance(effect, dict):
                    raise ContentError(
                        f"Relic '{relic_id}' trigger rule #{idx + 1} effect #{effect_idx + 1} must be an object.")
                effect_type = effect.get("type")
                if effect_type not in ALLOWED_RELIC_EFFECTS:
                    raise ContentError(
                        f"Relic '{relic_id}' trigger rule #{idx + 1} effect #{effect_idx + 1} has invalid type '{effect_type}'.")


def _validate_events(events_doc: Mapping[str, Any]) -> Dict[str, Any]:
    events = _unwrap_map(events_doc, "events")
    if not events:
        raise ContentError("events.json contains no events.")
    for event_id, raw in events.items():
        if not isinstance(raw, dict):
            raise ContentError(f"Event '{event_id}' must be an object.")
        text = raw.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ContentError(f"Event '{event_id}' must define non-empty text.")
        title = raw.get("title", "")
        if title is not None and not isinstance(title, str):
            raise ContentError(f"Event '{event_id}' title must be a string when present.")
    return events


def _validate_reward_tables(reward_doc: Mapping[str, Any], relics: Mapping[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    options = _unwrap_map(reward_doc, "options")
    tables = _unwrap_map(reward_doc, "tables")
    if not options:
        raise ContentError("reward_tables.json contains no options.")
    if not tables:
        raise ContentError("reward_tables.json contains no tables.")

    for option_id, raw in options.items():
        if not isinstance(raw, dict):
            raise ContentError(f"Reward option '{option_id}' must be an object.")
        for field_name in ("display_name", "description", "effect_type"):
            value = raw.get(field_name)
            if not isinstance(value, str) or not value:
                raise ContentError(f"Reward option '{option_id}' missing non-empty '{field_name}'.")
        cost = raw.get("cost", 0)
        if not isinstance(cost, int) or isinstance(cost, bool) or cost < 0:
            raise ContentError(f"Reward option '{option_id}' cost must be an integer >= 0 when present.")
        if raw.get("effect_type") == "grant_relic":
            relic_id = raw.get("relic_id")
            if not isinstance(relic_id, str) or not relic_id:
                raise ContentError(f"Reward option '{option_id}' with effect_type grant_relic must define relic_id.")
            if relic_id not in relics:
                raise ContentError(f"Reward option '{option_id}' references unknown relic_id '{relic_id}'.")

    for table_id, raw in tables.items():
        if not isinstance(raw, dict):
            raise ContentError(f"Reward table '{table_id}' must be an object.")
        owner = f"Reward table '{table_id}'"
        option_ids = raw.get("options")
        if not isinstance(option_ids, list) or not option_ids:
            raise ContentError(f"Reward table '{table_id}' must define a non-empty options list.")
        unknown = [str(option_id) for option_id in option_ids if option_id not in options]
        if unknown:
            raise ContentError(f"Reward table '{table_id}' references unknown options: {unknown}")
        pick_count = int(raw.get("pick_count", 1))
        if pick_count < 1 or pick_count > len(option_ids):
            raise ContentError(
                f"Reward table '{table_id}' pick_count must be between 1 and number of options.")
        table_type = raw.get("table_type", "choice")
        if table_type not in ALLOWED_REWARD_TABLE_TYPES:
            raise ContentError(
                f"Reward table '{table_id}' table_type must be one of {sorted(ALLOWED_REWARD_TABLE_TYPES)}."
            )
        max_purchases = raw.get("max_purchases", 1)
        if not isinstance(max_purchases, int) or isinstance(max_purchases, bool) or max_purchases < 1:
            raise ContentError(f"Reward table '{table_id}' max_purchases must be an integer >= 1 when present.")
        if table_type == "shop" and max_purchases > len(option_ids):
            raise ContentError(
                f"Reward table '{table_id}' shop max_purchases must be between 1 and number of options."
            )
        _validate_preview_tags(owner, "identity_tags", raw.get("identity_tags"), max_items=4)
        _validate_short_text(owner, "preview_text", raw.get("preview_text"))
    return options, tables


def _reachable_nodes(nodes: Mapping[str, Any], start_node_id: str) -> Set[str]:
    stack = [start_node_id]
    seen: Set[str] = set()
    while stack:
        node_id = stack.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        raw = nodes[node_id]
        for next_id in raw.get("next_node_ids", []):
            if next_id not in seen:
                stack.append(str(next_id))
    return seen


def _detect_cycle(nodes: Mapping[str, Any], node_id: str, visited: Set[str], active: Set[str]) -> bool:
    if node_id in active:
        return True
    if node_id in visited:
        return False
    visited.add(node_id)
    active.add(node_id)
    raw = nodes[node_id]
    for next_id in raw.get("next_node_ids", []):
        next_str = str(next_id)
        if _detect_cycle(nodes, next_str, visited, active):
            return True
    active.remove(node_id)
    return False


def _node_has_route_semantics(node_raw: Mapping[str, Any]) -> bool:
    semantic_fields = {"route_family", "risk_tier", "pacing_stage", "preview_tags", "preview_text"}
    return any(field_name in node_raw for field_name in semantic_fields)


def _validate_branch_semantics(district_id: str, nodes: Mapping[str, Any]) -> None:
    for node_id, node_raw in nodes.items():
        next_node_ids = [str(next_id) for next_id in node_raw.get("next_node_ids", [])]
        if len(next_node_ids) < 2:
            continue

        children = [nodes[next_id] for next_id in next_node_ids]
        semantic_children = [_node_has_route_semantics(child) for child in children]
        if not any(semantic_children):
            continue
        if not all(semantic_children):
            raise ContentError(
                f"District '{district_id}' branch from '{node_id}' mixes semantic and non-semantic child nodes."
            )

        signatures = set()
        for child_id, child in zip(next_node_ids, children):
            missing = [
                field_name
                for field_name in ("route_family", "risk_tier", "preview_tags", "preview_text")
                if field_name not in child
            ]
            if missing:
                raise ContentError(
                    f"District '{district_id}' branch child '{child_id}' is missing semantic fields: {missing}"
                )
            route_family = str(child.get("route_family", ""))
            preview_tags = tuple(sorted(str(tag) for tag in child.get("preview_tags", [])))
            signatures.add((route_family, preview_tags))
        if len(signatures) == 1:
            raise ContentError(
                f"District '{district_id}' branch from '{node_id}' has semantically identical child previews."
            )


def _validate_boss_prep_semantics(district_id: str, nodes: Mapping[str, Any]) -> None:
    if not any(_node_has_route_semantics(node_raw) for node_raw in nodes.values()):
        return

    predecessors: Dict[str, List[str]] = {str(node_id): [] for node_id in nodes.keys()}
    for node_id, node_raw in nodes.items():
        for next_id in node_raw.get("next_node_ids", []):
            predecessors[str(next_id)].append(str(node_id))

    for node_id, node_raw in nodes.items():
        if node_raw.get("kind") != "boss" or node_raw.get("next_node_ids"):
            continue
        direct_predecessors = predecessors.get(str(node_id), [])
        if not direct_predecessors:
            continue
        has_boss_prep = False
        for predecessor_id in direct_predecessors:
            predecessor = nodes[predecessor_id]
            tags = {str(tag) for tag in predecessor.get("preview_tags", [])}
            if predecessor.get("pacing_stage") == "boss_prep" or "boss_prep" in tags:
                has_boss_prep = True
                break
        if not has_boss_prep:
            raise ContentError(
                f"District '{district_id}' finale boss '{node_id}' needs a direct boss_prep predecessor "
                "when route semantics are authored."
            )


def _validate_districts(
    districts_doc: Mapping[str, Any],
    events: Mapping[str, Any],
    reward_tables: Mapping[str, Any],
    enemies: Mapping[str, Any],
    bosses: Mapping[str, Any],
) -> tuple[Dict[str, Any], str]:
    default_district_id = districts_doc.get("default_district_id")
    districts = _unwrap_map(districts_doc, "districts")
    if not isinstance(default_district_id, str) or not default_district_id:
        raise ContentError("districts.json must define default_district_id.")
    if not districts:
        raise ContentError("districts.json contains no districts.")
    if default_district_id not in districts:
        raise ContentError(f"default_district_id '{default_district_id}' is not present in districts.json.")

    valid_encounters = set(enemies.keys()) | set(bosses.keys())

    for district_id, raw in districts.items():
        if not isinstance(raw, dict):
            raise ContentError(f"District '{district_id}' must be an object.")
        display_name = raw.get("display_name")
        hub_event_id = raw.get("hub_event_id")
        start_node_id = raw.get("start_node_id")
        node_order = raw.get("node_order")
        nodes = raw.get("nodes")
        if not isinstance(display_name, str) or not display_name:
            raise ContentError(f"District '{district_id}' must define display_name.")
        if hub_event_id not in events:
            raise ContentError(f"District '{district_id}' references unknown hub_event_id '{hub_event_id}'.")
        if not isinstance(node_order, list) or not node_order:
            raise ContentError(f"District '{district_id}' must define a non-empty node_order list.")
        if not isinstance(nodes, dict) or not nodes:
            raise ContentError(f"District '{district_id}' must define a non-empty nodes object.")
        if start_node_id not in nodes:
            raise ContentError(f"District '{district_id}' start_node_id '{start_node_id}' is not a node.")

        encounter_pools = raw.get("encounter_pools", {})
        if encounter_pools is None:
            encounter_pools = {}
        if not isinstance(encounter_pools, dict):
            raise ContentError(f"District '{district_id}' encounter_pools must be an object when present.")
        for pool_id, pool_variants in encounter_pools.items():
            if not isinstance(pool_id, str) or not _is_short_slug(pool_id, max_len=48):
                raise ContentError(f"District '{district_id}' encounter_pools keys must be short slugs.")
            has_variants = _validate_encounter_variants(
                f"District '{district_id}' encounter pool '{pool_id}'",
                pool_variants,
                valid_encounters,
            )
            if not has_variants:
                raise ContentError(f"District '{district_id}' encounter pool '{pool_id}' must not be empty.")

        node_ids = set(nodes.keys())
        order_ids = [str(node_id) for node_id in node_order]
        if set(order_ids) != node_ids:
            missing_in_order = sorted(node_ids - set(order_ids))
            missing_in_nodes = sorted(set(order_ids) - node_ids)
            raise ContentError(
                f"District '{district_id}' node_order does not match nodes. "
                f"missing_in_order={missing_in_order}, missing_in_nodes={missing_in_nodes}"
            )

        for node_id, node_raw in nodes.items():
            if not isinstance(node_raw, dict):
                raise ContentError(f"District '{district_id}' node '{node_id}' must be an object.")
            owner = f"District '{district_id}' node '{node_id}'"
            kind = node_raw.get("kind")
            event_id = node_raw.get("event_id")
            encounter_ids = node_raw.get("encounter_ids", [])
            encounter_pool_id = node_raw.get("encounter_pool_id")
            reward_table_id = node_raw.get("reward_table_id")
            next_node_ids = node_raw.get("next_node_ids", [])
            if kind not in {"battle", "boss", "event"}:
                raise ContentError(f"District '{district_id}' node '{node_id}' has invalid kind '{kind}'.")
            if event_id not in events:
                raise ContentError(f"District '{district_id}' node '{node_id}' references unknown event_id '{event_id}'.")
            if reward_table_id is not None and reward_table_id not in reward_tables:
                raise ContentError(
                    f"District '{district_id}' node '{node_id}' references unknown reward_table_id '{reward_table_id}'.")
            if not isinstance(next_node_ids, list):
                raise ContentError(f"District '{district_id}' node '{node_id}' next_node_ids must be a list.")
            for next_node_id in next_node_ids:
                next_str = str(next_node_id)
                if next_str not in nodes:
                    raise ContentError(
                        f"District '{district_id}' node '{node_id}' points to unknown next node '{next_str}'.")
            has_node_variants = _validate_encounter_variants(
                owner,
                node_raw.get("encounter_variants"),
                valid_encounters,
            )
            if encounter_pool_id is not None:
                if not isinstance(encounter_pool_id, str) or not _is_short_slug(encounter_pool_id, max_len=48):
                    raise ContentError(f"{owner} encounter_pool_id must be a lowercase short slug when present.")
                if encounter_pool_id not in encounter_pools:
                    raise ContentError(f"{owner} references unknown encounter_pool_id '{encounter_pool_id}'.")
            if kind == "event":
                if encounter_ids:
                    raise ContentError(
                        f"District '{district_id}' node '{node_id}' is an event but still defines encounter_ids.")
                if encounter_pool_id is not None or has_node_variants:
                    raise ContentError(
                        f"District '{district_id}' node '{node_id}' is an event but still defines encounter variants.")
            else:
                has_fixed_encounters = isinstance(encounter_ids, list) and bool(encounter_ids)
                if not isinstance(encounter_ids, list):
                    raise ContentError(
                        f"District '{district_id}' node '{node_id}' encounter_ids must be a list when present.")
                if encounter_ids:
                    unknown_encounters = [str(item) for item in encounter_ids if item not in valid_encounters]
                    if unknown_encounters:
                        raise ContentError(
                            f"District '{district_id}' node '{node_id}' references unknown encounters: {unknown_encounters}")
                if not has_fixed_encounters and not has_node_variants and encounter_pool_id is None:
                    raise ContentError(
                        f"District '{district_id}' node '{node_id}' must define encounter_ids, "
                        "encounter_variants, or encounter_pool_id."
                    )
                if kind == "battle" and any(item in bosses for item in encounter_ids):
                    raise ContentError(
                        f"District '{district_id}' node '{node_id}' is a battle node but references a boss encounter.")
                if kind == "battle" and _encounter_variants_contain_boss(node_raw.get("encounter_variants"), bosses):
                    raise ContentError(
                        f"District '{district_id}' node '{node_id}' battle variants must not reference boss encounters.")
                if kind == "battle" and encounter_pool_id is not None:
                    pool_variants = encounter_pools.get(encounter_pool_id, [])
                    if _encounter_variants_contain_boss(pool_variants, bosses):
                        raise ContentError(
                            f"District '{district_id}' node '{node_id}' encounter pool must not reference boss encounters.")
                if kind == "boss" and (has_node_variants or encounter_pool_id is not None):
                    raise ContentError(
                        f"District '{district_id}' node '{node_id}' is a boss node and must use fixed encounter_ids.")
                if kind == "boss" and not has_fixed_encounters:
                    raise ContentError(
                        f"District '{district_id}' node '{node_id}' is a boss node and must define fixed encounter_ids.")
                if kind == "boss" and not any(item in bosses for item in encounter_ids):
                    raise ContentError(
                        f"District '{district_id}' node '{node_id}' is a boss node but contains no boss encounter.")
            shards = node_raw.get("shards", 0)
            if int(shards) < 0:
                raise ContentError(f"District '{district_id}' node '{node_id}' shards must be >= 0.")
            route_family = node_raw.get("route_family")
            if route_family is not None and (not isinstance(route_family, str) or not _is_short_slug(route_family)):
                raise ContentError(f"{owner} route_family must be a lowercase short slug when present.")
            risk_tier = node_raw.get("risk_tier")
            if risk_tier is not None and risk_tier not in ALLOWED_RISK_TIERS:
                raise ContentError(
                    f"{owner} risk_tier must be one of {sorted(ALLOWED_RISK_TIERS)} when present."
                )
            pacing_stage = node_raw.get("pacing_stage")
            if pacing_stage is not None and pacing_stage not in ALLOWED_PACING_STAGES:
                raise ContentError(
                    f"{owner} pacing_stage must be one of {sorted(ALLOWED_PACING_STAGES)} when present."
                )
            _validate_preview_tags(owner, "preview_tags", node_raw.get("preview_tags"))
            _validate_short_text(owner, "preview_text", node_raw.get("preview_text"))

        _validate_branch_semantics(district_id, nodes)
        _validate_boss_prep_semantics(district_id, nodes)

        reachable = _reachable_nodes(nodes, str(start_node_id))
        if reachable != node_ids:
            unreachable = sorted(node_ids - reachable)
            raise ContentError(f"District '{district_id}' has unreachable nodes: {unreachable}")
        if _detect_cycle(nodes, str(start_node_id), set(), set()):
            raise ContentError(f"District '{district_id}' contains a cycle. Vertical slice routes must be acyclic.")

    return districts, str(default_district_id)


def load_content(base_dir: Optional[str | Path] = None, reference_file: Optional[str] = None) -> ContentBundle:
    resolved_dir = resolve_content_dir(reference_file=reference_file, explicit_dir=base_dir)
    rules_doc = _load_json(resolved_dir / REQUIRED_FILES["rules"])
    affinities_doc = _load_json(resolved_dir / REQUIRED_FILES["affinities"])
    characters_doc = _load_json(resolved_dir / REQUIRED_FILES["characters"])
    skills_doc = _load_json(resolved_dir / REQUIRED_FILES["skills"])
    enemies_doc = _load_json(resolved_dir / REQUIRED_FILES["enemies"])
    bosses_doc = _load_json(resolved_dir / REQUIRED_FILES["bosses"])
    weapons_doc = _load_json(resolved_dir / REQUIRED_FILES["weapons"])
    relics_doc = _load_json(resolved_dir / REQUIRED_FILES["relics"])
    events_doc = _load_json(resolved_dir / REQUIRED_FILES["events"])
    reward_doc = _load_json(resolved_dir / REQUIRED_FILES["reward_tables"])
    districts_doc = _load_json(resolved_dir / REQUIRED_FILES["districts"])

    _validate_profiles(rules_doc)
    _validate_defensive_reads(rules_doc)
    affinity_order, affinity_strong_vs, affinity_status = _validate_affinities(affinities_doc)

    characters = _unwrap_map(characters_doc, "characters")
    skills = _unwrap_map(skills_doc, "skills")
    enemies = _unwrap_map(enemies_doc, "enemies")
    bosses = _unwrap_map(bosses_doc, "bosses")
    weapons = _unwrap_map(weapons_doc, "weapons")
    relics = _unwrap_map(relics_doc, "relics")
    events = _validate_events(events_doc)
    reward_options, reward_tables = _validate_reward_tables(reward_doc, relics)
    if not characters:
        raise ContentError("characters.json contains no characters.")
    if not skills:
        raise ContentError("skills.json contains no skills.")

    valid_affinities = set(affinity_order)
    _validate_weapons(weapons, valid_affinities)
    _validate_relics(relics)
    _validate_skills(skills, valid_affinities, set(characters.keys()))
    _validate_characters(rules_doc, characters, skills, weapons, relics, valid_affinities)
    _validate_enemies(enemies, valid_affinities, rules_doc)
    _validate_bosses(bosses, valid_affinities)
    districts, default_district_id = _validate_districts(districts_doc, events, reward_tables, enemies, bosses)

    character_blueprints = _materialize_character_blueprints(rules_doc, characters)

    return ContentBundle(
        base_dir=resolved_dir,
        rules=rules_doc,
        affinities=affinities_doc,
        characters=characters,
        skills=skills,
        enemies=enemies,
        bosses=bosses,
        weapons=weapons,
        relics=relics,
        events=events,
        reward_tables=reward_tables,
        reward_options=reward_options,
        districts=districts,
        default_district_id=default_district_id,
        character_blueprints=character_blueprints,
        affinity_order=affinity_order,
        affinity_strong_vs=affinity_strong_vs,
        affinity_status=affinity_status,
    )


def summarize_content(bundle: ContentBundle) -> Dict[str, int]:
    return {
        "bands": len(bundle.rules.get("bands", [])),
        "affinities": len(bundle.affinity_order),
        "characters": len(bundle.characters),
        "skills": len(bundle.skills),
        "enemies": len(bundle.enemies),
        "bosses": len(bundle.bosses),
        "weapons": len(bundle.weapons),
        "relics": len(bundle.relics),
        "events": len(bundle.events),
        "reward_options": len(bundle.reward_options),
        "reward_tables": len(bundle.reward_tables),
        "districts": len(bundle.districts),
    }


if __name__ == "__main__":
    bundle = load_content(reference_file=__file__)
    summary = summarize_content(bundle)
    print("Loaded content from", bundle.base_dir)
    print("Default district:", bundle.default_district_id)
    for key, value in summary.items():
        print(f"- {key}: {value}")
