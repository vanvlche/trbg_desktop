# Quiet Relay Web Prototype

This is the standalone vanilla HTML/CSS/JavaScript browser prototype for
Quiet Relay. It does not replace the Python terminal game and does not require
external packages, npm, React, Phaser, a backend server, CDN assets, or network
access after the app has been cached once.

## Phase 3 Turn Axis Patch

- Manual browser battles now require a per-player-turn Power / Precision /
  Composure confirmation before battle actions unlock.
- The confirmed triplet is stored as the current actor's Turn Axis for that
  turn and is used by browser damage scaling, posture, skill preview, and crit
  approximation.
- The previous confirmed player Turn Axis becomes the default for the next
  player turn. If no prior value exists, the browser uses `60 / 60 / 60`.
- Node or route axis values remain visible as route baseline metadata and as a
  deterministic fallback for old saves and automation; they are no longer the
  default manual combat input in the web UI.
- Combat log wording now records `Turn input: Power ...` once per confirmed
  player turn and labels node-axis values as route baseline information.
- Browser saves now use schema v3 and the `quiet-relay-web-save-v3` key.
  Schema v1/v2 saves are migrated on load; missing Turn Axis fields fall back
  to `60 / 60 / 60`.
- Semantic emoji labels were added across the battle HUD, map, save/load,
  offline status, rewards, unit bars, posture labels, and Turn Axis panel.

## Phase 2 Baseline UI Changes

- Darker RPG interface with layered panels, route progress, stronger title and
  result screens, reward cards, status cards, and clearer battle state.
- Improved HP, Guard, Break, Barrier, Spotlight, enemy threat, and selected
  skill preview presentation.
- Visual feedback for damage, guard and break pressure, reward recovery,
  Spotlight spend/gain, defeated units, save/load status, and online/offline
  state.
- Responsive layout with touch-sized buttons, wrapping action buttons,
  scrollable combat log, mobile-safe spacing, and a sticky small-screen action
  panel.
- Baseline PWA support through `web/manifest.json`, `web/service-worker.js`,
  `web/offline.html`, and local generated SVG icons.
- Offline app-shell and JSON data caching after the first successful visit.
- Schema-v2 browser save envelope, legacy v1 migration, corrupt save
  quarantine, visible save/load feedback, manual save, autosave, and reset.
- Lightweight stdlib web smoke checker at `scripts/smoke_web.py`.

## Run Locally

From the repository root:

```sh
cd ~/projects/trbg
source .venv/bin/activate
python -m http.server 8765 --directory web
```

Open:

```text
http://localhost:8765/
```

Service workers require `http://localhost` or HTTPS. Opening
`web/index.html` through `file://` can show the app shell, but installability,
offline caching, and service worker update behavior will not work correctly.

## Reused Content

The browser loads copied JSON content from `web/data/`. These files are copied
from the Python loader's default content pack and should stay data-driven:

- `quiet_relay_content/rules.json` -> `web/data/rules.json`
- `quiet_relay_content/affinities.json` -> `web/data/affinities.json`
- `quiet_relay_content/characters.json` -> `web/data/characters.json`
- `quiet_relay_content/skills.json` -> `web/data/skills.json`
- `quiet_relay_content/enemies.json` -> `web/data/enemies.json`
- `quiet_relay_content/bosses.json` -> `web/data/bosses.json`
- `quiet_relay_content/weapons.json` -> `web/data/weapons.json`
- `quiet_relay_content/relics.json` -> `web/data/relics.json`
- `quiet_relay_content/events.json` -> `web/data/events.json`
- `quiet_relay_content/reward_tables.json` -> `web/data/reward_tables.json`
- `quiet_relay_content/districts.json` -> `web/data/districts.json`

Do not change source JSON balance numbers for web-only tuning. If the browser
adapter needs a different rule, document it here instead.

## Turn Axis Gameplay Flow

At the start of each manual player turn in the browser, the battle screen shows
`Tune This Turn` before the action list is usable. Enter Power, Precision, and
Composure values from 0 to 100, review the live band/posture/AP preview, then
confirm the Turn Axis.

Power affects browser-side damage and break pressure. Precision affects the
hit/crit approximation. Composure determines the displayed AP preview and
defensive-flow posture pressure. The confirmed values stay locked for the
active player actor's current turn.

The route baseline axis is separate. It describes node/route pressure and is
kept for deterministic fallback behavior, old save migration, and Python CLI
compatibility. In manual browser combat, the route baseline is reference data,
not the fixed player combat input.

Defaults come from the previous confirmed player Turn Axis. A fresh game or a
save that lacks Turn Axis data falls back to `60 / 60 / 60`. If an in-progress
turn is saved after confirmation, schema v3 saves keep the current actor's
locked Turn Axis where practical; older saves simply ask for input again.

Auto mode remains a Python CLI behavior. The web prototype does not add a
manual prompt to Python auto runs, and existing `--node-axis` / `--axis-file`
support remains available for deterministic smoke tests.

## PWA Files

- `web/manifest.json`: install metadata, theme colors, start URL, scope, and
  local icon entries.
- `web/service-worker.js`: named cache version, app-shell precache, required
  JSON precache, old-cache cleanup, navigation fallback, and update message
  handling.
- `web/offline.html`: fallback page if a navigation request cannot load the app.
- `web/icons/icon-192.svg` and `web/icons/icon-512.svg`: generated local SVG
  placeholder icons.

## Test PWA Installability

1. Start the local server with the command above.
2. Open `http://localhost:8765/`.
3. Open browser DevTools and inspect Application or Storage.
4. Confirm the manifest is detected and the service worker is registered.
5. Use the browser install prompt or install button if your browser exposes one.
6. Keep the app open until the status strip reports the offline cache is ready.

## Test Offline Behavior

1. Visit `http://localhost:8765/` once while online or while the local server is
   running.
2. Confirm the app status strip reports offline cache readiness.
3. In DevTools, enable offline mode, or stop the local server after the first
   successful visit.
4. Reload the app.
5. Confirm the menu and required JSON-driven screens still load from cache.

If the app does not load offline, clear the service worker/cache, restart the
server, and visit the app once online again.

## Clear Service Worker And Cache During Development

Chrome or Edge:

1. Open DevTools.
2. Go to Application.
3. Use Service Workers -> Unregister.
4. Use Storage -> Clear site data.
5. Reload `http://localhost:8765/`.

Firefox:

1. Open DevTools.
2. Go to Storage.
3. Clear Cache Storage and Local Storage for `localhost:8765`.
4. Open `about:debugging#/runtime/this-firefox` if you need to unregister the
   service worker.

The app also shows a "Reload Update" button when a waiting service worker is
detected.

## Test Browser Save And Load

1. Start a new expedition.
2. Enter a node, take at least one combat action, or choose a reward.
3. Confirm the status strip reports an autosave.
4. Reload the page.
5. Choose "Load Browser Save".
6. Confirm route state, party stats, rewards, shards, potions, and battle state
   restore.
7. Choose "Clear Browser Save" and confirm loading becomes unavailable.

Browser saves use `localStorage` and are separate from Python save files. The
current key is `quiet-relay-web-save-v3`. Legacy
`quiet-relay-web-save-v2` and `quiet-relay-web-save-v1` saves are migrated on
load. Missing Turn Axis defaults or current-turn locks are recreated from
`60 / 60 / 60`, so older saves can continue without manual repair. Corrupt
saves are moved to `quiet-relay-web-corrupt-save` when possible.

## Smoke Checks

Run the requested checks from the repository root:

```sh
cd ~/projects/trbg
source .venv/bin/activate
.venv/bin/python -m compileall .
.venv/bin/python quiet_relay_vertical_slice_datadriven.py --help
.venv/bin/python quiet_relay_terminal_datadriven.py --help
.venv/bin/python quiet_relay_vertical_slice_datadriven.py --auto --fresh --seed 2026 --save-file /tmp/quiet_relay_turn_axis_smoke_save.json --log-dir /tmp/quiet_relay_turn_axis_smoke_logs
.venv/bin/python scripts/smoke_web.py
```

The web smoke script checks:

- Required web shell files exist.
- `manifest.json` parses and has installability baseline fields.
- Manifest icons exist.
- `service-worker.js` defines cache entries for core shell and JSON data.
- Required `web/data/*.json` files exist and parse.
- `index.html` references expected app assets.
- No obvious CDN or external runtime dependency references are present.

## Manual Turn Axis Verification Checklist

1. Start the local server:

```sh
cd ~/projects/trbg
source .venv/bin/activate
python -m http.server 8765 --directory web
```

2. Open `http://localhost:8765/`.
3. Start or load a game.
4. Enter battle.
5. Confirm that at the start of each player turn:
   - Turn Axis Input appears before action selection.
   - Power / Precision / Composure can be edited.
   - Values are validated or clamped between 0 and 100.
   - The preview updates with bands, posture, and AP.
   - Confirming the triplet unlocks action selection.
   - The combat log records the Turn input once.
   - Actions use the confirmed values for that actor turn.
   - The next player turn asks again, using previous values as defaults.
   - Route baseline axis is visible only as reference/fallback metadata.
6. Confirm mobile/narrow layout remains usable.
7. Confirm PWA still registers:
   - manifest loads
   - service worker registers
   - app still works after reload
   - cache version is `quiet-relay-turn-axis-2026-04-25`

The broader browser smoke path is still useful: select enemies with mouse,
touch, and keyboard focus; use Standard Strike and Brace; verify HP, Guard,
Break, Barrier, Spotlight, reward, save/load, reduced-motion, and offline-cache
feedback.

## Current Browser Combat Differences

The web battle layer is still an adapter/simulation, not full Python combat
parity. The Python data-driven CLI remains the source of truth for exact combat
math and campaign behavior.

Known differences:

- No seeded browser RNG parity with the Python vertical slice.
- Simplified AP/loadout action economy. The browser now previews AP from
  Composure, but still resolves one selected action per actor turn in this
  patch.
- Simplified enemy AI based on broad tier pressure and a small browser-side
  special table.
- Simplified defensive reaction prompts, pattern reads, parry/dodge/guard math,
  and equipment timing.
- Simplified relic trigger timing and once-per-battle flags.
- Browser-side party balance multipliers adapt solo play for usability.
- Event nodes record route prose and rewards but do not yet show a full
  narrative event screen.
- Browser saves do not share the Python save schema.
- Turn Axis math is centralized in the browser adapter and follows the same
  broad bands/posture concepts as Python, but it is still an approximation
  rather than a full port of `quiet_relay_terminal_datadriven.py`.

## Current Limitations

- Mobile Safari is targeted as reasonably usable, not final-polished.
- Icons are local generated SVG placeholders rather than final brand assets.
- Offline support caches static files only. It does not sync saves or logs.
- Service worker update UI is intentionally simple.
- The web prototype does not currently export battle logs.
- Data validation catches required top-level fields and core references, but it
  is not a full schema validator.
- Manual browser battles ask for Turn Axis every player actor turn, but exact
  Python-style multi-AP action chaining is still a future browser parity task.

## Recommended Next Patch

1. Bring the browser action economy closer to the Python AP loop while keeping
   this Turn Axis lock as the first step of each player turn.
2. Add a Python-backed optional adapter that can run the real combat core while
   preserving the static offline web fallback.
3. Add deterministic browser seed controls or a shared RNG fixture for web
   smoke replay.
4. Build dedicated event-node and camp/shop screens instead of routing all
   non-battle nodes through reward panels.
5. Expand schema validation for `web/data/*.json`.
6. Add export/import for browser saves.
7. Add richer keyboard shortcuts after final action layout stabilizes.
8. Replace placeholder icons with final local brand art.
