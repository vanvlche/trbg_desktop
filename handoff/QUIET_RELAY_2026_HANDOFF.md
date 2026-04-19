# Quiet Relay: 2026 — Comprehensive Handoff

## 1) What this project is

**Working title:** Quiet Relay: 2026

This is a **small, replayable, single-player expedition RPG** with:
- turn-based combat
- timed-reaction-inspired defense represented in terminal form as **Guard / Dodge / Parry**
- strong build identity through weapons, relics, and skill loadouts
- readable affinity matchups and status synergies
- **manual per-action input** of three external performance values:
  - `power`
  - `precision`
  - `composure`

Primary inspiration blend:
- **Claire Obscur** feel: theatrical reactive turn-based combat
- **Elden Ring** feel: dangerous bosses, loadout identity, punishing-but-learnable encounters
- **Pokémon** feel: affinity logic, team composition, swap/value planning

---

## 2) Locked design pillars

### Player fantasy
> I turn real-world performance into stylish combat decisions.

### Fun promise
> Every fight feels tactical, reactive, and a little theatrical.

### Scope rule
> Small, replayable, systemic RPG — not a giant open-world epic.

### Input contract
- Source: **manual entry**
- Cadence: **per action**
- Raw scale: **0–100** for each input dimension
- Dimensions:
  - Power
  - Precision
  - Composure

Important design intent:
- the player enters raw values each action
- the engine converts those raw values into **bands**
- combat is balanced around bands, not around arbitrary raw numbers

---

## 3) Core rules currently agreed

### Band thresholds
- `0–19` = `frayed`
- `20–39` = `set`
- `40–59` = `keen`
- `60–79` = `fierce`
- `80–100` = `exalted`

### Posture system
Each action resolves into a temporary posture until the actor’s next turn.

- `ravage` = power-dominant
  - more damage
  - more break
  - weaker guard recovery
- `focus` = precision-dominant
  - more crit / reveal / weak-point / status reliability
  - lower break contribution
- `bastion` = composure-dominant
  - safer reactions
  - stronger guard recovery
  - slightly lower damage
- `flow` = balanced spread
  - small Spotlight gain
  - self-risk reduction
  - minor debuff cleanup

Tie logic:
1. higher band wins
2. if tied, higher raw value wins
3. if still tied, favor the skill’s primary scale if relevant
4. if still tied, priority = `power > precision > composure`

### Affinity wheel
Order:
- `ash > bloom > tide > spark > shade > halo > ash`

Statuses:
- `ash` -> `scorch`
- `bloom` -> `snare`
- `tide` -> `soak`
- `spark` -> `jolt`
- `shade` -> `hex`
- `halo` -> `reveal`

### Resource model
Combatants have:
- HP
- Guard
- Break
- Affinity
- Status conditions / barrier / misc conditions

Party shared / run-level resources:
- Spotlight
- Recovery Charges

### Reactions
Enemy attacks can be answered with:
- Guard
- Dodge
- Parry

In the terminal prototype, these are turn-prompt reactions rather than real-time timing windows.

### Break / stagger
When Break is depleted:
- target becomes `staggered`
- target loses its next action
- break meter later resets

---

## 4) Content designed so far

### Intended full roster
5 playable characters were designed:
- Vanguard
- Duelist
- Cantor
- Ranger
- Penitent

### Starting skill set
18 starting skills were defined across shared + character-specific skills.

### Enemy catalog
12 enemy types / elites were defined in the design layer.

### Boss catalog
4 bosses were defined in the design layer:
- Bell Warden
- Flood Archivist
- Glass Hound Matriarch
- Quiet Magistrate

---

## 5) What has actually been implemented in code

## A. Terminal combat core
File:
- `quiet_relay_terminal.py`

This is the earlier non-data-driven pure Python terminal combat core.

Capabilities:
- battle state
- turn order
- skill resolution
- band conversion
- posture resolution
- break / stagger
- Guard / Dodge / Parry
- Spotlight
- logging
- manual per-action input
- auto mode for smoke tests

Also generated:
- `quiet_relay_last_battle_log.txt`
- `quiet_relay_terminal_runner.ipynb`

---

## B. Vertical slice (earlier, mostly hardcoded)
Files:
- `quiet_relay_vertical_slice.py`
- `quiet_relay_vertical_slice_runner.ipynb`
- `quiet_relay_vertical_slice_save.json`
- `quiet_relay_vertical_slice_last_run.txt`
- `quiet_relay_vertical_slice_logs/06_bell_tower.txt`

This version includes:
- 3 playable characters
  - Vanguard
  - Duelist
  - Cantor
- 1 district
- 6 regular enemies
- 1 elite
- 1 boss
- 1 hub screen
- save/load

This is the first playable slice.

---

## C. Data-driven combat core
Files:
- `quiet_relay_terminal_datadriven.py`
- `quiet_relay_content_loader.py`
- `quiet_relay_content/`

The combat core was refactored to load content from JSON.

Content currently present in `quiet_relay_content/`:
- `rules.json`
- `affinities.json`
- `characters.json`
- `skills.json`
- `enemies.json`
- `bosses.json`
- `weapons.json`
- `relics.json`
- `districts.json`
- `reward_tables.json`
- `events.json`
- `README.txt`

Important: the **data folder contains the newer district/event/reward JSON files**.

---

## D. Data-driven vertical slice
Files:
- `quiet_relay_vertical_slice_datadriven.py`
- `quiet_relay_vertical_slice_datadriven_save.json`
- `quiet_relay_vertical_slice_datadriven_last_run.txt`
- `quiet_relay_vertical_slice_datadriven_logs/06_bell_tower.txt`

Intent:
- same vertical slice gameplay
- but backed by JSON content instead of Python constants

---

## 6) Current file map

### Design / original context
- `game design.txt`  
  User-provided design context / source spec

### Runtime code
- `quiet_relay_terminal.py`
- `quiet_relay_terminal_datadriven.py`
- `quiet_relay_vertical_slice.py`
- `quiet_relay_vertical_slice_datadriven.py`
- `quiet_relay_content_loader.py`

### Notebooks
- `quiet_relay_terminal_runner.ipynb`
- `quiet_relay_vertical_slice_runner.ipynb`

### Content JSON
- `quiet_relay_content/rules.json`
- `quiet_relay_content/affinities.json`
- `quiet_relay_content/characters.json`
- `quiet_relay_content/skills.json`
- `quiet_relay_content/enemies.json`
- `quiet_relay_content/bosses.json`
- `quiet_relay_content/weapons.json`
- `quiet_relay_content/relics.json`
- `quiet_relay_content/districts.json`
- `quiet_relay_content/reward_tables.json`
- `quiet_relay_content/events.json`
- `quiet_relay_content/README.txt`

### Saves / outputs / logs
- `quiet_relay_last_battle_log.txt`
- `quiet_relay_vertical_slice_save.json`
- `quiet_relay_vertical_slice_last_run.txt`
- `quiet_relay_vertical_slice_logs/06_bell_tower.txt`
- `quiet_relay_vertical_slice_datadriven_save.json`
- `quiet_relay_vertical_slice_datadriven_last_run.txt`
- `quiet_relay_vertical_slice_datadriven_logs/06_bell_tower.txt`

### Existing zip
- `quiet_relay_content_pack.zip`

---

## 7) Critical reality check / inconsistencies discovered in the sandbox

This is important. The next LLM should not assume the latest stated refactor is fully reflected in the runtime files.

### Inconsistency 1: code vs. content folder
The content folder contains:
- `districts.json`
- `reward_tables.json`
- `events.json`

However, the current `quiet_relay_vertical_slice_datadriven.py` file in the sandbox still appears to define:
- `DISTRICT_NODES`
- reward option defs
- event/node text

directly in Python, rather than reading those new JSON files.

### Inconsistency 2: loader scope
The current `quiet_relay_content_loader.py` file visibly validates and loads:
- rules
- affinities
- characters
- skills
- enemies
- bosses
- weapons
- relics

But it does **not visibly include** the new district / reward-table / event JSONs in its required file list.

### Inconsistency 3: stale content zip
`quiet_relay_content_pack.zip` appears to be an older archive and may **not** include:
- `districts.json`
- `reward_tables.json`
- `events.json`

So do **not** trust that zip as the sole source of truth.

### Inconsistency 4: save version
`quiet_relay_vertical_slice_datadriven.py` currently shows `SAVE_VERSION = 1`, even though a later message claimed legacy handling for a newer save version. The actual file should be treated as authoritative.

### Practical conclusion
The project is in a **partially completed refactor state**:
- the JSON content exists
- the runtime migration to consume all of it may not be fully finished or may have regressed / not been saved

The very next technical step should be:
1. verify what the runtime actually reads
2. complete the migration so district graph, reward tables, and event text are truly loaded from JSON
3. re-run the slice and refresh bundle artifacts

---

## 8) What the next LLM should do first

Recommended first actions in a new chat:

1. Inspect:
   - `quiet_relay_vertical_slice_datadriven.py`
   - `quiet_relay_content_loader.py`
   - `quiet_relay_content/`

2. Confirm whether:
   - district nodes are loaded from `districts.json`
   - reward menus are loaded from `reward_tables.json`
   - prose/event text is loaded from `events.json`

3. If not:
   - patch the loader to include those JSON files
   - patch the vertical slice runtime to read them
   - remove the hardcoded district/reward/event constants from Python
   - validate all cross-references
   - regenerate logs / run report / bundle zip

4. Then continue with the next planned phase:
   - more districts
   - more relics / weapons
   - cleaner content schema
   - balancing tools / simulations
   - save migration cleanup

---

## 9) Recommended immediate next milestone after reconciliation

After the JSON migration is truly complete, best next steps are:

- add **branching district routes** using the graph model
- externalize **reward option effects** into a more systematic schema
- add **encounter tables** so district nodes can vary without hardcoding enemy IDs
- add **content validation CLI** for all new JSON files
- improve save format with:
  - stable schema versioning
  - migration helpers
- create a **single project bundle zip** as the canonical transfer artifact

---

## 10) Suggested prompt for the next LLM

Use something like this at the top of the new chat:

> I’m continuing work on Quiet Relay: 2026.  
> Please read the attached handoff file first, then inspect the attached Python and JSON files.  
> The project is a terminal-first, pure-Python, data-driven RPG prototype with manual per-action input for power / precision / composure.  
> First, verify whether the data-driven slice truly loads districts.json, reward_tables.json, and events.json.  
> If the runtime still hardcodes those structures, finish the refactor so the vertical slice is fully data-driven, validate the content, and regenerate the save/log/report artifacts.

---

## 11) Minimum files to re-upload in a new chat

### Best option (recommended)
Re-upload these **2 files only**:
1. this handoff file
2. `quiet_relay_project_bundle_for_handoff.zip`

That is the cleanest handoff path.

### If uploading individually instead of a zip
At minimum, re-upload:
1. `QUIET_RELAY_2026_HANDOFF.md`
2. `game design.txt`
3. `quiet_relay_vertical_slice_datadriven.py`
4. `quiet_relay_terminal_datadriven.py`
5. `quiet_relay_content_loader.py`
6. the **entire** `quiet_relay_content/` folder contents:
   - rules.json
   - affinities.json
   - characters.json
   - skills.json
   - enemies.json
   - bosses.json
   - weapons.json
   - relics.json
   - districts.json
   - reward_tables.json
   - events.json
   - README.txt

### Optional but useful to re-upload
- `quiet_relay_vertical_slice_datadriven_save.json`
- `quiet_relay_vertical_slice_datadriven_last_run.txt`
- `quiet_relay_vertical_slice_datadriven_logs/06_bell_tower.txt`
- `quiet_relay_terminal.py`
- `quiet_relay_vertical_slice.py`
- the notebook runners

---

## 12) Canonical working assumption for the next chat

Treat the **data-driven path** as the primary branch:
- `quiet_relay_terminal_datadriven.py`
- `quiet_relay_vertical_slice_datadriven.py`
- `quiet_relay_content_loader.py`
- `quiet_relay_content/`

Treat the older non-data-driven files as fallback reference / legacy prototypes, not as the preferred future base.

---

## 13) Short status summary

Current state in one sentence:

> Quiet Relay: 2026 already has a playable terminal combat core and vertical slice, plus a mostly data-driven content structure, but the final migration of district graph / reward tables / event text into the live runtime likely still needs to be finished and verified.

