Quiet Relay content pack

This folder is the data-driven runtime content for the terminal combat core and
the vertical slice.

Primary files
- rules.json
- affinities.json
- characters.json
- skills.json
- enemies.json
- bosses.json
- weapons.json
- relics.json
- events.json
- reward_tables.json
- districts.json

What moved out of Python
- combat content: skills, enemies, weapons, relics, bosses, affinities
- expedition content: district graph, reward tables, reward option metadata,
  hub text, node intro text, and event prose

Reference links
- characters.weapon -> weapons.json
- characters.skills -> skills.json
- characters.starting_relics -> relics.json
- skill.affinity -> affinities.json or neutral
- enemy.affinity -> affinities.json
- boss.primary_affinity / secondary_affinity -> affinities.json
- districts.default_district_id -> districts.districts
- districts.*.hub_event_id -> events.events
- districts.*.nodes.*.event_id -> events.events
- districts.*.nodes.*.reward_table_id -> reward_tables.tables
- districts.*.nodes.*.encounter_ids -> enemies.json or bosses.json
- reward_tables.tables.*.options -> reward_tables.options

Notes
- Reward option mechanical effects are applied by Python using effect_type and
  the numeric fields inside reward_tables.json.
- Districts are graph-based via next_node_ids; Rain Toll Corridor now uses a
  small branching/merge route.
- skills.json optionally supports tags (list of strings) for lightweight
  combat classification.
- enemies.json and bosses.json optionally support action_tags as:
  action_tags.<action_id> -> list of strings such as heavy, channel,
  burst_start, defensive, mode_shift.
- relics.json optionally supports trigger_rules:
  - trigger: reaction_success | before_offense | after_offense
  - reaction (optional): guard | dodge | parry
  - incoming_tags_any (optional): list of tags that must match the incoming
    action tags for reaction_success rules
  - once_per_battle (optional): true/false
  - effects: list of effect objects
  Supported trigger effect types:
  - apply_status_to_attacker
  - apply_status_to_self
  - gain_spotlight
  - apply_break_to_attacker
  - restore_guard_self
  - gain_barrier_self
  - cleanse_minor_self
  - set_next_self_risk_reduction
  - store_charge_bonus
  - consume_stored_charge_bonus
- reward_tables.json supports effect_type=grant_relic with relic_id.
