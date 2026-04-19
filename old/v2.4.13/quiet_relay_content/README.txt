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
- The current district graph is linear, but districts.json already supports
  next_node_ids for future branching routes.
