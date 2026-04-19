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


class ContentError(ValueError):
    """Raised when content files are missing or internally inconsistent."""


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


def _validate_weapons(weapons: Mapping[str, Any], valid_affinities: Set[str]) -> None:
    for weapon_id, raw in weapons.items():
        if not isinstance(raw, dict):
            raise ContentError(f"Weapon '{weapon_id}' must be an object.")
        affinity_hint = raw.get("affinity_hint")
        if affinity_hint is not None and affinity_hint not in valid_affinities:
            raise ContentError(f"Weapon '{weapon_id}' has invalid affinity_hint '{affinity_hint}'.")
        if "display_name" not in raw:
            raise ContentError(f"Weapon '{weapon_id}' is missing display_name.")


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


def _validate_reward_tables(reward_doc: Mapping[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
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

    for table_id, raw in tables.items():
        if not isinstance(raw, dict):
            raise ContentError(f"Reward table '{table_id}' must be an object.")
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
            kind = node_raw.get("kind")
            event_id = node_raw.get("event_id")
            encounter_ids = node_raw.get("encounter_ids", [])
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
            if kind == "event":
                if encounter_ids:
                    raise ContentError(
                        f"District '{district_id}' node '{node_id}' is an event but still defines encounter_ids.")
            else:
                if not isinstance(encounter_ids, list) or not encounter_ids:
                    raise ContentError(
                        f"District '{district_id}' node '{node_id}' must define a non-empty encounter_ids list.")
                unknown_encounters = [str(item) for item in encounter_ids if item not in valid_encounters]
                if unknown_encounters:
                    raise ContentError(
                        f"District '{district_id}' node '{node_id}' references unknown encounters: {unknown_encounters}")
                if kind == "boss" and not any(item in bosses for item in encounter_ids):
                    raise ContentError(
                        f"District '{district_id}' node '{node_id}' is a boss node but contains no boss encounter.")
            shards = node_raw.get("shards", 0)
            if int(shards) < 0:
                raise ContentError(f"District '{district_id}' node '{node_id}' shards must be >= 0.")

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
    affinity_order, affinity_strong_vs, affinity_status = _validate_affinities(affinities_doc)

    characters = _unwrap_map(characters_doc, "characters")
    skills = _unwrap_map(skills_doc, "skills")
    enemies = _unwrap_map(enemies_doc, "enemies")
    bosses = _unwrap_map(bosses_doc, "bosses")
    weapons = _unwrap_map(weapons_doc, "weapons")
    relics = _unwrap_map(relics_doc, "relics")
    events = _validate_events(events_doc)
    reward_options, reward_tables = _validate_reward_tables(reward_doc)
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
