"use strict";

const APP_VERSION = "phase4-art-assets-2026-04-26";
const SAVE_SCHEMA_VERSION = 3;
const SAVE_KEY = "quiet-relay-web-save-v3";
const LEGACY_SAVE_KEYS = ["quiet-relay-web-save-v2", "quiet-relay-web-save-v1"];
const CORRUPT_SAVE_KEY = "quiet-relay-web-corrupt-save";
const SERVICE_WORKER_URL = "./service-worker.js";
const API_BASE = "/api";
const ART = {
  title: "/assets/images/kazier_ring_title_screen.png",
  entities: {
    Vanguard: "/assets/images/vangard.png",
    Vangard: "/assets/images/vangard.png",
    vanguard: "/assets/images/vangard.png",
    Rustbound_Pilgrim: "/assets/images/Rustbound_Pilgrim.png",
    "Rustbound Pilgrim": "/assets/images/Rustbound_Pilgrim.png",
    rustbound_pilgrim: "/assets/images/Rustbound_Pilgrim.png",
  },
};
const ART_ERROR_HANDLER = "if(this.parentElement)this.parentElement.classList.add('art-missing');this.remove();";

const DATA_FILES = [
  { name: "rules", required: ["stat_profiles", "damage_tiers", "break_tiers", "bands"] },
  { name: "affinities", required: ["affinities"] },
  { name: "characters", required: [] },
  { name: "skills", required: [] },
  { name: "enemies", required: [] },
  { name: "bosses", required: [] },
  { name: "weapons", required: [] },
  { name: "relics", required: [] },
  { name: "events", required: ["events"] },
  { name: "reward_tables", required: ["options", "tables"] },
  { name: "districts", required: ["default_district_id", "districts"] },
];

const DEFAULT_AXIS = { power: 60, precision: 60, composure: 60 };
const AXIS_KEYS = ["power", "precision", "composure"];
const AXIS_META = {
  power: {
    label: "Power",
    icon: "power",
    hint: "Damage and break pressure",
  },
  precision: {
    label: "Precision",
    icon: "precision",
    hint: "Hit quality and crit pressure",
  },
  composure: {
    label: "Composure",
    icon: "composure",
    hint: "AP and defensive flow",
  },
};
const UI_ICONS = {
  power: "💥",
  precision: "🎯",
  composure: "🧘",
  flow: "🌊",
  ravage: "🔥",
  focus: "🎯",
  bastion: "🛡️",
  spotlight: "☀️",
  guard: "🛡️",
  break: "⚡",
  barrier: "✨",
  hp: "❤",
  playerTurn: "▶️",
  enemyTurn: "⚠️",
  victory: "🏆",
  defeat: "💀",
  save: "💾",
  load: "📂",
  continue: "▶️",
  hub: "🕯️",
  online: "📡",
  offline: "📴",
  relic: "🧿",
  shards: "💠",
  route: "🧭",
  event: "✦",
  battle: "⚔️",
  boss: "👑",
  potion: "🩹",
  recovery: "🩹",
  party: "⛭",
  target: "◎",
  lock: "🔒",
};
const DEFAULT_PARTY = ["vanguard"];
const DEFAULT_HEALING_POTIONS = 1;
const BOSS_STAT_MULTIPLIER = 1.5;
const NEGATIVE_STATUSES = new Set(["scorch", "snare", "soak", "jolt", "hex", "reveal"]);
const STATUS_DISPLAY_ORDER = [
  "staggered",
  "reveal",
  "hex",
  "snare",
  "soak",
  "jolt",
  "scorch",
  "taunt",
  "brace_guard",
  "rain_mark",
  "airborne",
];

const app = {
  content: null,
  screen: "loading",
  selectedCharacterId: "vanguard",
  campaign: null,
  battle: null,
  error: "",
  status: null,
  server: {
    available: null,
    sessionId: null,
    saves: [],
    lastSavedAt: null,
    message: "Server save not checked",
  },
  presentation: {
    queue: [],
    current: null,
  },
  lastBattleLog: [],
  online: typeof navigator === "undefined" ? true : navigator.onLine,
  pwa: {
    supported: false,
    ready: false,
    updateAvailable: false,
    message: "Offline cache not checked yet",
  },
};

let statusTimer = null;
let waitingServiceWorker = null;

document.addEventListener("DOMContentLoaded", init);
document.addEventListener("click", handleClick);
document.addEventListener("input", handleInput);
document.addEventListener("mouseover", handleHover);
document.addEventListener("focusin", handleHover);
window.addEventListener("online", () => updateOnlineState(true));
window.addEventListener("offline", () => updateOnlineState(false));
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (app.pwa.updateAvailable) {
      window.location.reload();
    }
  });
}

async function init() {
  registerServiceWorker();
  try {
    app.content = await loadContent();
    app.selectedCharacterId = DEFAULT_PARTY[0];
    app.campaign = newCampaign();
    app.screen = "menu";
    setStatus("Content loaded. Server saves are used when the API is available.", "success");
    checkServerSaves();
  } catch (error) {
    app.error = String(error && error.message ? error.message : error);
    app.screen = "error";
  }
  render();
}

async function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) {
    app.pwa.supported = false;
    app.pwa.message = "Service workers unavailable in this browser";
    return;
  }
  app.pwa.supported = true;
  app.pwa.message = "Preparing offline cache";
  try {
    const registration = await navigator.serviceWorker.register(SERVICE_WORKER_URL);
    if (registration.waiting && navigator.serviceWorker.controller) {
      waitingServiceWorker = registration.waiting;
      app.pwa.updateAvailable = true;
      app.pwa.message = "Update ready";
    }
    registration.addEventListener("updatefound", () => {
      const worker = registration.installing;
      if (!worker) return;
      worker.addEventListener("statechange", () => {
        if (worker.state === "installed" && navigator.serviceWorker.controller) {
          waitingServiceWorker = worker;
          app.pwa.updateAvailable = true;
          app.pwa.message = "Update ready";
          setStatus("A cached app update is ready. Use Reload Update when convenient.", "info", true);
        }
      });
    });
    await navigator.serviceWorker.ready;
    app.pwa.ready = true;
    app.pwa.message = app.pwa.updateAvailable
      ? "Update ready"
      : navigator.serviceWorker.controller
        ? "Offline cache ready"
        : "Offline cache installed; reload once for full offline control";
    setStatus(app.pwa.message, "success", true);
  } catch (error) {
    app.pwa.supported = false;
    app.pwa.ready = false;
    app.pwa.message = "Offline cache unavailable";
    setStatus(`Service worker registration failed: ${error.message || error}`, "warning", true);
  }
}

function updateOnlineState(isOnline) {
  app.online = isOnline;
  setStatus(isOnline ? "Back online." : "Offline mode. Cached app/data remain available after first visit.", isOnline ? "success" : "warning", true);
}

function setStatus(text, tone = "info", rerender = false) {
  app.status = {
    text,
    tone,
    timestamp: new Date().toISOString(),
  };
  window.clearTimeout(statusTimer);
  statusTimer = window.setTimeout(() => {
    app.status = null;
    render();
  }, 4200);
  if (rerender) {
    render();
  }
}

async function loadContent() {
  const entries = await Promise.all(
    DATA_FILES.map(loadDataFile),
  );
  const raw = Object.fromEntries(entries);
  const content = {
    rules: raw.rules,
    affinities: raw.affinities,
    characters: raw.characters.characters || raw.characters,
    skills: raw.skills.skills || raw.skills,
    enemies: raw.enemies.enemies || raw.enemies,
    bosses: raw.bosses.bosses || raw.bosses,
    weapons: raw.weapons.weapons || raw.weapons,
    relics: raw.relics.relics || raw.relics,
    events: raw.events.events || raw.events,
    rewardOptions: raw.reward_tables.options || {},
    rewardTables: raw.reward_tables.tables || {},
    districts: raw.districts.districts || {},
    defaultDistrictId: raw.districts.default_district_id,
  };
  validateContent(content);
  return content;
}

async function loadDataFile(file) {
  let response;
  try {
    response = await fetch(`./data/${file.name}.json`, { cache: "default" });
  } catch (error) {
    throw new Error(`Could not request web/data/${file.name}.json. If offline, visit once online first.`);
  }
  if (!response.ok) {
    throw new Error(`Could not load web/data/${file.name}.json (${response.status})`);
  }
  let data;
  try {
    data = await response.json();
  } catch (error) {
    throw new Error(`web/data/${file.name}.json is not valid JSON.`);
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new Error(`web/data/${file.name}.json must contain a JSON object.`);
  }
  file.required.forEach((key) => {
    if (!(key in data)) {
      throw new Error(`web/data/${file.name}.json is missing required field "${key}".`);
    }
  });
  return [file.name, data];
}

function validateContent(content) {
  const requiredCharacter = content.characters[DEFAULT_PARTY[0]];
  const district = content.districts[content.defaultDistrictId];
  if (!requiredCharacter) {
    throw new Error(`Default character "${DEFAULT_PARTY[0]}" is missing from web/data/characters.json.`);
  }
  if (!district || !district.start_node_id || !district.nodes) {
    throw new Error("Default district is missing start_node_id or nodes.");
  }
  requiredCharacter.skills.forEach((skillId) => {
    if (!content.skills[skillId]) {
      throw new Error(`Default character skill "${skillId}" is missing from web/data/skills.json.`);
    }
  });
}

function newCampaign(characterId = app.selectedCharacterId || DEFAULT_PARTY[0]) {
  const districtId = app.content ? app.content.defaultDistrictId : "district_03_rain_toll_corridor";
  return {
    saveVersion: "quiet-relay-web-3",
    saveSchemaVersion: SAVE_SCHEMA_VERSION,
    createdAt: new Date().toISOString(),
    lastLoadedAt: null,
    loadSource: "new",
    selectedPartyIds: [characterId],
    soloCharacterId: characterId,
    players: app.content ? [createPlayer(characterId)] : [],
    districtId,
    expeditionActive: false,
    currentNodeId: null,
    availableNodeIds: [],
    clearedNodeIds: [],
    recoveryCharges: 3,
    maxRecoveryCharges: 3,
    healingPotions: DEFAULT_HEALING_POTIONS,
    potionUpgradeIds: [],
    bossRefillUsed: false,
    startingSpotlight: 0,
    prebattleBarrier: 0,
    bossGuardPenalty: 0,
    runShards: 0,
    boons: [],
    bestNodesCleared: 0,
    wins: 0,
    losses: 0,
    lastOutcome: "none",
    lastResult: "No expeditions yet.",
    reportLines: [],
    currentNodeAxisScores: { ...DEFAULT_AXIS },
    nodeAxisHistory: {},
    lastTurnAxisDefaults: { ...DEFAULT_AXIS },
    resolvedNodeEncounters: {},
    pendingReward: null,
    pendingResolvedNodeId: null,
  };
}

function startExpedition() {
  const characterId = app.selectedCharacterId || DEFAULT_PARTY[0];
  const district = getDistrict(app.campaign.districtId);
  clearEventQueue(false);
  app.lastBattleLog = [];
  ensureServerSession(true);
  app.campaign = newCampaign(characterId);
  app.campaign.expeditionActive = true;
  app.campaign.lastOutcome = "active";
  app.campaign.loadSource = "new";
  app.campaign.currentNodeId = district.start_node_id;
  app.campaign.availableNodeIds = [district.start_node_id];
  record(`Started a new expedition in ${district.display_name}.`);
  app.screen = "map";
  app.battle = null;
  saveLocal("Autosaved new expedition.");
  render();
}

function resetLocal() {
  [SAVE_KEY, ...LEGACY_SAVE_KEYS].forEach((key) => localStorage.removeItem(key));
  app.campaign = newCampaign(app.selectedCharacterId);
  app.battle = null;
  app.lastBattleLog = [];
  clearEventQueue(false);
  app.screen = "menu";
  setStatus("Browser save cleared. Python save files were not touched.", "warning");
  render();
}

function buildClientSavePayload() {
  return {
    schemaVersion: SAVE_SCHEMA_VERSION,
    appVersion: APP_VERSION,
    savedAt: new Date().toISOString(),
    screen: app.screen,
    selectedCharacterId: app.selectedCharacterId,
    campaign: app.campaign,
    battle: app.battle,
    lastBattleLog: app.lastBattleLog,
  };
}

function saveLocal(message = "Browser save complete.") {
  try {
    const payload = buildClientSavePayload();
    localStorage.setItem(SAVE_KEY, JSON.stringify(payload));
    setStatus(message, "success");
    return true;
  } catch (error) {
    setStatus(`Save failed: ${error.message || error}`, "danger");
    return false;
  }
}

async function apiRequest(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch (error) {
    payload = null;
  }
  if (!response.ok || (payload && payload.ok === false)) {
    const message = payload && payload.error ? payload.error : `API request failed (${response.status})`;
    throw new Error(message);
  }
  return payload;
}

async function ensureServerSession(forceNew = false) {
  if (!forceNew && app.server.sessionId) return app.server.sessionId;
  try {
    const payload = await apiRequest("/sessions", {
      method: "POST",
      body: JSON.stringify({}),
    });
    app.server.available = true;
    app.server.sessionId = payload.session_id;
    app.server.message = `Session ${payload.session_id.slice(0, 8)}`;
    return app.server.sessionId;
  } catch (error) {
    app.server.available = false;
    app.server.message = "Server save API unavailable";
    return null;
  }
}

async function checkServerSaves(rerender = true) {
  try {
    const payload = await apiRequest("/saves");
    app.server.available = true;
    app.server.saves = Array.isArray(payload.saves) ? payload.saves : [];
    app.server.message = app.server.sessionId ? `Session ${app.server.sessionId.slice(0, 8)}` : "Server save API ready";
    if (rerender) render();
  } catch (error) {
    app.server.available = false;
    app.server.message = "Server save API unavailable";
    if (rerender) render();
  }
}

async function saveGame() {
  saveLocal("Browser fallback save updated.");
  const sessionId = await ensureServerSession(false);
  if (!sessionId) {
    setStatus("Saved in this browser. Server save API is unavailable.", "warning", true);
    return false;
  }
  try {
    const payload = await apiRequest(`/sessions/${encodeURIComponent(sessionId)}/save`, {
      method: "POST",
      body: JSON.stringify({ client_state: buildClientSavePayload() }),
    });
    app.server.lastSavedAt = payload.saved_at;
    setStatus(`Server save complete: ${formatTime(payload.saved_at)}.`, "success", true);
    checkServerSaves(false);
    return true;
  } catch (error) {
    setStatus(`Server save failed; browser fallback remains: ${error.message || error}`, "danger", true);
    return false;
  }
}

async function loadGame(sessionId = app.server.sessionId) {
  if (sessionId) {
    try {
      const payload = await apiRequest(`/sessions/${encodeURIComponent(sessionId)}/load`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      if (applyServerLoadPayload(payload)) {
        app.server.available = true;
        app.server.sessionId = payload.session_id;
        app.server.message = `Session ${payload.session_id.slice(0, 8)}`;
        setStatus("Loaded server save.", "success", true);
        return true;
      }
    } catch (error) {
      setStatus(`Server load failed: ${error.message || error}`, "warning", true);
    }
  }
  const loaded = loadLocal();
  if (loaded) render();
  return loaded;
}

function applyServerLoadPayload(payload) {
  const state = payload && payload.state;
  const clientState = state && state.client_state;
  if (!clientState) return false;
  return applyLoadedSavePayload(clientState, "server");
}

function loadLocal() {
  const found = readSaveRecord();
  if (!found) {
    setStatus("No browser save was found.", "warning");
    return false;
  }
  try {
    const payload = migrateSavePayload(JSON.parse(found.raw), found.key);
    applyLoadedSavePayload(payload, found.key === SAVE_KEY ? "browser" : "migrated");
    if (found.key !== SAVE_KEY) {
      saveLocal("Migrated legacy browser save to schema v3.");
    } else {
      setStatus(`Loaded browser save from ${formatTime(payload.savedAt)}.`, "success");
    }
    return true;
  } catch (error) {
    try {
      localStorage.setItem(CORRUPT_SAVE_KEY, found.raw);
    } catch (storageError) {
      // If quota is exhausted, clearing the broken active save is still safer.
    }
    localStorage.removeItem(found.key);
    setStatus(`Browser save was corrupt and has been quarantined: ${error.message || error}`, "danger");
    app.campaign = newCampaign(app.selectedCharacterId);
    app.battle = null;
    app.screen = "menu";
    return false;
  }
}

function applyLoadedSavePayload(payload, source) {
  const migrated = migrateSavePayload(payload, source);
  app.selectedCharacterId = migrated.selectedCharacterId || DEFAULT_PARTY[0];
  app.campaign = normalizeLoadedCampaign(migrated.campaign || newCampaign(app.selectedCharacterId));
  app.campaign.lastLoadedAt = new Date().toISOString();
  app.campaign.loadSource = source;
  app.battle = normalizeLoadedBattle(migrated.battle || null);
  app.lastBattleLog = Array.isArray(migrated.lastBattleLog) ? migrated.lastBattleLog.slice(-120) : [];
  app.screen = migrated.screen || (app.campaign.expeditionActive ? "map" : "menu");
  if (app.battle && !app.battle.battleOver) {
    app.screen = "battle";
  }
  clearEventQueue(false);
  return true;
}

function readSaveRecord() {
  const keys = [SAVE_KEY, ...LEGACY_SAVE_KEYS];
  for (const key of keys) {
    const raw = localStorage.getItem(key);
    if (raw) return { key, raw };
  }
  return null;
}

function hasSaveRecord() {
  return Boolean(readSaveRecord());
}

function migrateSavePayload(payload, sourceKey) {
  if (!payload || typeof payload !== "object") {
    throw new Error("save root is not an object");
  }
  if (payload.schemaVersion === SAVE_SCHEMA_VERSION) {
    return payload;
  }
  if (payload.schemaVersion && payload.schemaVersion > SAVE_SCHEMA_VERSION) {
    throw new Error(`save schema ${payload.schemaVersion} is newer than this app supports`);
  }
  if (LEGACY_SAVE_KEYS.includes(sourceKey) || payload.campaign) {
    return {
      ...payload,
      schemaVersion: SAVE_SCHEMA_VERSION,
      migratedFrom: payload.schemaVersion || sourceKey || "legacy",
      migratedAt: new Date().toISOString(),
    };
  }
  throw new Error("unrecognized save schema");
}

function normalizeLoadedCampaign(campaign) {
  const fresh = newCampaign(app.selectedCharacterId);
  const merged = { ...fresh, ...campaign };
  merged.saveSchemaVersion = SAVE_SCHEMA_VERSION;
  merged.saveVersion = "quiet-relay-web-3";
  merged.players = Array.isArray(merged.players) && merged.players.length
    ? merged.players
    : [createPlayer(merged.soloCharacterId || app.selectedCharacterId)];
  merged.selectedPartyIds = Array.isArray(merged.selectedPartyIds) && merged.selectedPartyIds.length
    ? merged.selectedPartyIds
    : [merged.soloCharacterId || app.selectedCharacterId];
  merged.availableNodeIds = Array.isArray(merged.availableNodeIds) ? merged.availableNodeIds : [];
  merged.clearedNodeIds = Array.isArray(merged.clearedNodeIds) ? merged.clearedNodeIds : [];
  merged.boons = Array.isArray(merged.boons) ? merged.boons : [];
  merged.potionUpgradeIds = Array.isArray(merged.potionUpgradeIds) ? merged.potionUpgradeIds : [];
  merged.reportLines = Array.isArray(merged.reportLines) ? merged.reportLines : [];
  merged.currentNodeAxisScores = normalizeAxis(merged.currentNodeAxisScores);
  merged.nodeAxisHistory = merged.nodeAxisHistory || {};
  merged.lastTurnAxisDefaults = normalizeAxis(merged.lastTurnAxisDefaults);
  merged.resolvedNodeEncounters = merged.resolvedNodeEncounters || {};
  merged.lastOutcome = merged.lastOutcome || "none";
  merged.loadSource = merged.loadSource || "loaded";
  return merged;
}

function normalizeLoadedBattle(battle) {
  if (!battle || typeof battle !== "object") return null;
  const merged = { ...battle };
  merged.players = Array.isArray(merged.players) ? merged.players : [];
  merged.enemies = Array.isArray(merged.enemies) ? merged.enemies : [];
  merged.turnOrderIds = Array.isArray(merged.turnOrderIds) ? merged.turnOrderIds : [];
  merged.log = Array.isArray(merged.log) ? merged.log.slice(-120) : [];
  merged.effects = {};
  merged.nodeAxisScores = normalizeAxis(merged.nodeAxisScores);
  merged.lastTurnAxisDefaults = normalizeAxis(merged.lastTurnAxisDefaults || app.campaign.lastTurnAxisDefaults);
  merged.currentTurnAxis = normalizeCurrentTurnAxis(merged.currentTurnAxis);
  merged.spotlight = clampInt(Number(merged.spotlight), 0, Number(merged.spotlightMax || 5), 0);
  merged.enemySpotlight = clampInt(Number(merged.enemySpotlight), 0, Number(merged.enemySpotlightMax || 5), 0);
  merged.round = Math.max(1, Number(merged.round || 1));
  return merged;
}

function getDistrict(districtId = app.campaign.districtId) {
  return app.content.districts[districtId] || app.content.districts[app.content.defaultDistrictId];
}

function getNode(nodeId) {
  return getDistrict().nodes[nodeId];
}

function getEvent(eventId) {
  return app.content.events[eventId] || { title: eventId, text: "" };
}

function normalizeAxis(raw) {
  return {
    power: clampInt(Number(raw && raw.power), 0, 100, DEFAULT_AXIS.power),
    precision: clampInt(Number(raw && raw.precision), 0, 100, DEFAULT_AXIS.precision),
    composure: clampInt(Number(raw && raw.composure), 0, 100, DEFAULT_AXIS.composure),
  };
}

function normalizeCurrentTurnAxis(raw) {
  if (!raw || typeof raw !== "object") return null;
  const actorId = String(raw.actorId || "");
  if (!actorId) return null;
  const resolved = resolveTurnAxis(normalizeAxis(raw.values || raw), null);
  return {
    actorId,
    values: resolved.values,
    bands: resolved.bands,
    posture: String(raw.posture || resolved.posture),
    postureReason: String(raw.postureReason || resolved.postureReason),
    ap: Math.max(1, Number(raw.ap || resolved.ap)),
    round: Math.max(1, Number(raw.round || 1)),
    confirmedAt: raw.confirmedAt || null,
  };
}

function statValue(group, key) {
  return Number(app.content.rules.stat_profiles[group][key]);
}

function createPlayer(characterId) {
  const raw = app.content.characters[characterId];
  const stats = raw.stat_profile;
  const unit = {
    entityId: characterId,
    instanceId: characterId,
    name: raw.display_name,
    team: "player",
    affinity: raw.default_affinity,
    maxHp: statValue("hp", stats.hp),
    hp: statValue("hp", stats.hp),
    maxGuard: statValue("guard", stats.guard),
    guard: statValue("guard", stats.guard),
    maxBreak: statValue("break", stats.break),
    breakMeter: statValue("break", stats.break),
    speed: statValue("speed", stats.speed),
    skills: [...raw.skills],
    role: raw.role,
    isBoss: false,
    posture: "flow",
    position: "set",
    barrier: 0,
    conditions: {},
    nextAttackPowerBonus: 0,
    metadata: {
      relicIds: [...(raw.starting_relics || [])],
      relicNames: (raw.starting_relics || []).map((id) => relicName(id)),
      startingEquipment: raw.starting_equipment || {},
    },
  };
  return unit;
}

function createEnemy(enemyId, index = 1) {
  const raw = app.content.enemies[enemyId];
  const stats = raw.stat_profile;
  let hp = statValue("hp", stats.hp);
  let guard = statValue("guard", stats.guard);
  let breakValue = statValue("break", stats.break);
  let speed = statValue("speed", stats.speed);
  if (raw.tier === "elite") {
    hp = Math.floor(hp * 1.35);
    guard = Math.floor(guard * 1.25);
    breakValue = Math.floor(breakValue * 1.25);
    speed = Math.max(speed, 10);
  }
  const instanceId = `${enemyId}_${index}`;
  const unit = {
    entityId: enemyId,
    instanceId,
    name: index === 1 ? raw.display_name : `${raw.display_name} #${index}`,
    team: "enemy",
    affinity: raw.affinity,
    maxHp: hp,
    hp,
    maxGuard: guard,
    guard,
    maxBreak: breakValue,
    breakMeter: breakValue,
    speed,
    skills: [],
    role: raw.role,
    isBoss: false,
    posture: "flow",
    position: "set",
    barrier: 0,
    conditions: enemyId === "canal_seraph" ? { airborne: 99 } : {},
    nextAttackPowerBonus: 0,
    metadata: { blueprintId: enemyId, tier: raw.tier, gimmick: raw.gimmick },
  };
  return unit;
}

function createBoss(bossId) {
  const raw = app.content.bosses[bossId];
  const stats = raw.base_stats;
  const hp = ceil(Number(stats.hp) * BOSS_STAT_MULTIPLIER);
  const guard = ceil(Number(stats.guard) * BOSS_STAT_MULTIPLIER);
  const breakValue = ceil(Number(stats.break) * BOSS_STAT_MULTIPLIER);
  return {
    entityId: bossId,
    instanceId: bossId,
    name: raw.display_name,
    team: "enemy",
    affinity: raw.primary_affinity,
    maxHp: hp,
    hp,
    maxGuard: guard,
    guard,
    maxBreak: breakValue,
    breakMeter: breakValue,
    speed: Number(stats.speed),
    skills: [],
    role: raw.role,
    isBoss: true,
    posture: "flow",
    position: "set",
    barrier: 0,
    conditions: {},
    nextAttackPowerBonus: 0,
    metadata: { blueprintId: bossId, gimmick: raw.gimmick || raw.phase_rule || "" },
  };
}

function startBattle(nodeId) {
  const node = getNode(nodeId);
  const encounterInfo = resolveNodeEncounter(node);
  const enemies = encounterInfo.encounterIds.map((id, index) => (
    app.content.bosses[id] ? createBoss(id) : createEnemy(id, index + 1)
  ));
  const players = app.campaign.players.map((unit) => clearBattleOnlyState(clone(unit)));
  players.forEach((unit) => {
    unit.barrier += app.campaign.prebattleBarrier;
  });
  if (node.kind === "boss" && app.campaign.bossGuardPenalty > 0) {
    enemies.forEach((enemy) => {
      enemy.guard = Math.max(0, enemy.guard - app.campaign.bossGuardPenalty);
      enemy.maxGuard = Math.max(enemy.guard, enemy.maxGuard - app.campaign.bossGuardPenalty);
    });
  }
  applyEnemyBalance(enemies, players.length);
  if (
    enemies.some((enemy) => enemy.isBoss)
    && app.campaign.potionUpgradeIds.includes("boss_refill")
    && !app.campaign.bossRefillUsed
    && app.campaign.healingPotions < 1
  ) {
    app.campaign.healingPotions = 1;
    app.campaign.bossRefillUsed = true;
  }

  app.battle = {
    nodeId,
    nodeKind: node.kind,
    round: 1,
    started: false,
    spotlight: app.campaign.startingSpotlight,
    spotlightMax: 5,
    enemySpotlight: 0,
    enemySpotlightMax: 5,
    healingPotions: app.campaign.healingPotions,
    potionUpgradeIds: [...app.campaign.potionUpgradeIds],
    nodeAxisScores: normalizeAxis(app.campaign.currentNodeAxisScores),
    lastTurnAxisDefaults: normalizeAxis(app.campaign.lastTurnAxisDefaults),
    currentTurnAxis: null,
    players,
    enemies,
    turnOrderIds: [],
    nextActorIndex: 0,
    awaitingPlayerId: null,
    selectedTargetId: firstLiving(enemies).instanceId,
    selectedSkillId: players[0].skills[0],
    battleOver: false,
    winner: null,
    log: [],
    effects: {},
  };
  log(`Battle begins at ${node.title}.`);
  log(`Encounter: ${encounterInfo.encounterIds.map((id) => encounterName(id)).join(", ")}.`);
  if (encounterInfo.variantId !== "fixed") {
    log(`Encounter variant: ${encounterInfo.variantId}.`);
  }
  log(
    `Route baseline: Power ${app.battle.nodeAxisScores.power}, Precision ${app.battle.nodeAxisScores.precision}, Composure ${app.battle.nodeAxisScores.composure}.`,
  );
  app.screen = "battle";
  const events = advanceUntilPlayerOrEnd();
  saveLocal("Autosaved battle start.");
  if (events.length) {
    enqueueEvents(events);
  } else {
    render();
  }
}

function resolveNodeEncounter(node) {
  const cached = app.campaign.resolvedNodeEncounters[node.node_id];
  if (cached) {
    return { variantId: cached.variantId, encounterIds: [...cached.encounterIds] };
  }
  const variants = encounterVariantsForNode(node);
  let resolved;
  if (variants.length) {
    const variant = weightedChoice(variants, (item) => Math.max(1, Number(item.weight || 1)));
    resolved = {
      variantId: variant.variant_id,
      encounterIds: [...variant.encounter_ids],
    };
  } else {
    resolved = {
      variantId: "fixed",
      encounterIds: [...(node.encounter_ids || [])],
    };
  }
  app.campaign.resolvedNodeEncounters[node.node_id] = resolved;
  return resolved;
}

function encounterVariantsForNode(node) {
  const district = getDistrict();
  let variants = Array.isArray(node.encounter_variants) ? [...node.encounter_variants] : [];
  if (!variants.length && node.encounter_pool_id) {
    variants = [...((district.encounter_pools || {})[node.encounter_pool_id] || [])];
  }
  const routeBias = inferRouteBias();
  return variants.filter((variant) => {
    if (variant.route_families_any && variant.route_families_any.length && !variant.route_families_any.includes(node.route_family)) {
      return false;
    }
    if (variant.risk_tiers_any && variant.risk_tiers_any.length && !variant.risk_tiers_any.includes(node.risk_tier)) {
      return false;
    }
    if (variant.route_bias_any && variant.route_bias_any.length && !variant.route_bias_any.includes(routeBias)) {
      return false;
    }
    return true;
  });
}

function inferRouteBias() {
  const maintenanceNodes = new Set(["flooded_arcade", "service_niche", "drainage_switchback"]);
  const chapelNodes = new Set(["witness_chapel", "signal_vestry", "glass_choir_loft"]);
  const cleared = new Set(app.campaign.clearedNodeIds);
  const hasMaintenance = [...maintenanceNodes].some((id) => cleared.has(id));
  const hasChapel = [...chapelNodes].some((id) => cleared.has(id));
  if (hasMaintenance && !hasChapel) return "maintenance";
  if (hasChapel && !hasMaintenance) return "chapel";
  return "neutral";
}

function partyBalanceProfile(partySize) {
  const size = Math.max(1, Number(partySize || 1));
  if (size <= 1) {
    return {
      enemyHpMult: 0.82,
      enemyGuardMult: 0.86,
      enemyBreakMult: 0.84,
      enemyDamageMult: 0.90,
      bossHpMult: 0.92,
      bossGuardMult: 0.92,
      bossBreakMult: 0.90,
      bossPressureMult: 0.92,
      recoveryHealMult: 1.30,
      healingRewardMult: 1.28,
    };
  }
  if (size === 2) {
    return {
      enemyHpMult: 0.97,
      enemyGuardMult: 0.98,
      enemyBreakMult: 0.98,
      enemyDamageMult: 1.0,
      bossHpMult: 1.0,
      bossGuardMult: 1.0,
      bossBreakMult: 1.0,
      bossPressureMult: 1.0,
      recoveryHealMult: 1.10,
      healingRewardMult: 1.08,
    };
  }
  return {
    enemyHpMult: 1.12,
    enemyGuardMult: 1.08,
    enemyBreakMult: 1.10,
    enemyDamageMult: 1.0,
    bossHpMult: 1.08,
    bossGuardMult: 1.08,
    bossBreakMult: 1.10,
    bossPressureMult: 1.06,
    recoveryHealMult: 1.0,
    healingRewardMult: 1.0,
  };
}

function applyEnemyBalance(enemies, partySize) {
  const profile = partyBalanceProfile(partySize);
  enemies.forEach((enemy) => {
    const hpMult = profile.enemyHpMult * (enemy.isBoss ? profile.bossHpMult : 1);
    const guardMult = profile.enemyGuardMult * (enemy.isBoss ? profile.bossGuardMult : 1);
    const breakMult = profile.enemyBreakMult * (enemy.isBoss ? profile.bossBreakMult : 1);
    enemy.maxHp = scaledAmount(enemy.maxHp, hpMult);
    enemy.hp = Math.min(enemy.maxHp, scaledAmount(enemy.hp, hpMult));
    enemy.maxGuard = enemy.maxGuard > 0 ? scaledAmount(enemy.maxGuard, guardMult) : 0;
    enemy.guard = enemy.maxGuard > 0 ? Math.min(enemy.maxGuard, scaledAmount(enemy.guard, guardMult)) : 0;
    enemy.maxBreak = enemy.maxBreak > 0 ? scaledAmount(enemy.maxBreak, breakMult) : 0;
    enemy.breakMeter = enemy.maxBreak > 0 ? Math.min(enemy.maxBreak, scaledAmount(enemy.breakMeter, breakMult)) : 0;
  });
}

function scaledAmount(value, multiplier, minimum = 1) {
  if (value <= 0) return 0;
  return Math.max(minimum, ceil(value * multiplier));
}

function clearBattleOnlyState(unit) {
  unit.barrier = 0;
  unit.posture = "flow";
  unit.position = "set";
  unit.conditions = Object.fromEntries(
    Object.entries(unit.conditions || {}).filter(([name]) => !NEGATIVE_STATUSES.has(name)),
  );
  unit.nextAttackPowerBonus = 0;
  delete unit.currentAp;
  delete unit.startingAp;
  unit.guard = clampInt(unit.guard, 0, unit.maxGuard, unit.maxGuard);
  unit.breakMeter = clampInt(unit.breakMeter, 0, unit.maxBreak, unit.maxBreak);
  return unit;
}

function ensureTurnOrder() {
  const battle = app.battle;
  if (!battle || battle.battleOver) return;
  if (battle.turnOrderIds.length && battle.nextActorIndex < battle.turnOrderIds.length) return;
  if (battle.started) {
    battle.round += 1;
    log("------------------------------------------------------------");
  }
  battle.started = true;
  const order = [...battle.players, ...battle.enemies]
    .filter((unit) => alive(unit))
    .sort((a, b) => (b.speed + Math.random() * 2) - (a.speed + Math.random() * 2));
  battle.turnOrderIds = order.map((unit) => unit.instanceId);
  battle.nextActorIndex = 0;
  battle.awaitingPlayerId = null;
  battle.currentTurnAxis = null;
  log(`Turn order: ${order.map((unit) => unit.name).join(", ")}.`);
}

function advanceUntilPlayerOrEnd() {
  const battle = app.battle;
  const events = [];
  if (!battle) return events;
  while (!battle.battleOver) {
    checkBattleEnd();
    if (battle.battleOver) break;
    ensureTurnOrder();
    const actor = getActiveActor();
    if (!actor) {
      battle.nextActorIndex = battle.turnOrderIds.length;
      continue;
    }
    if (!alive(actor)) {
      battle.nextActorIndex += 1;
      battle.awaitingPlayerId = null;
      clearTurnAxisForNextActor();
      continue;
    }
    if (actor.team === "player") {
      if (battle.awaitingPlayerId !== actor.instanceId) {
        clearTurnAxisForNextActor();
        const canAct = startTurn(actor);
        if (!canAct) {
          battle.nextActorIndex += 1;
          battle.awaitingPlayerId = null;
          clearTurnAxisForNextActor();
          continue;
        }
        battle.awaitingPlayerId = actor.instanceId;
        if (!battle.selectedSkillId || !actor.skills.includes(battle.selectedSkillId)) {
          battle.selectedSkillId = actor.skills[0];
        }
      }
      return events;
    }
    const enemyLogStart = battle.log.length;
    startTurn(actor);
    if (alive(actor)) {
      processEnemyTurn(actor);
    }
    events.push(...enemyEventsFromEntries(actor, battleEntriesSince(battle, enemyLogStart)));
    battle.nextActorIndex += 1;
    battle.awaitingPlayerId = null;
    clearTurnAxisForNextActor();
    checkBattleEnd();
  }
  events.push(...finishBattleIfNeeded());
  return events;
}

function startTurn(actor) {
  const battle = app.battle;
  if (!alive(actor)) return false;
  if (actor.conditions && actor.conditions.scorch > 0) {
    const damage = Math.max(4, Math.floor(actor.maxHp * 0.05));
    actor.hp = Math.max(0, actor.hp - damage);
    flash(actor.instanceId, "damage-flash");
    log(`${actor.name} is scorched for ${damage} HP.`);
  }
  if (actor.conditions && actor.conditions.jolt > 0) {
    const loss = Math.min(actor.guard, 8);
    actor.guard -= loss;
    flash(actor.instanceId, "break-flash");
    log(`${actor.name} crackles with jolt and loses ${loss} guard.`);
  }
  if (!alive(actor)) {
    log(`${actor.name} falls.`);
    checkBattleEnd();
    return false;
  }
  if (actor.conditions && actor.conditions.staggered > 0) {
    actor.breakMeter = actor.maxBreak;
    delete actor.conditions.staggered;
    log(`${actor.name} is staggered and loses the turn.`);
    decrementConditions(actor);
    return false;
  }
  decrementConditions(actor);
  return true;
}

function decrementConditions(actor) {
  Object.keys(actor.conditions || {}).forEach((name) => {
    if (name === "staggered" || name === "airborne") return;
    actor.conditions[name] -= 1;
    if (actor.conditions[name] <= 0) {
      delete actor.conditions[name];
      log(`${actor.name} is no longer affected by ${name}.`);
    }
  });
}

function processEnemyTurn(actor) {
  const battle = app.battle;
  const target = chooseEnemyTarget();
  if (!target) return;
  const blueprint = actor.isBoss ? app.content.bosses[actor.entityId] : app.content.enemies[actor.entityId];
  const tier = actor.isBoss ? "boss" : blueprint.tier;
  const damageTier = tier === "boss" ? "high" : tier === "elite" ? "medium" : "low";
  const breakTier = tier === "boss" ? "medium" : tier === "elite" ? "medium" : "low";
  const pressure = partyBalanceProfile(battle.players.length);
  const bossPressure = actor.isBoss ? pressure.bossPressureMult : 1;
  const pseudoSkill = {
    display_name: actor.isBoss ? "Boss Pressure" : "Enemy Pressure",
    affinity: actor.affinity,
    effect_id: "enemy_pressure",
    kind: "attack",
  };
  let damage = ceil(app.content.rules.damage_tiers[damageTier] * pressure.enemyDamageMult * bossPressure);
  let breakDamage = ceil(app.content.rules.break_tiers[breakTier] * pressure.enemyDamageMult * bossPressure);
  const special = enemySpecial(actor, target);
  damage = ceil(damage * special.damageMult);
  breakDamage = ceil(breakDamage * special.breakMult);
  log(`${actor.name} uses ${special.name} on ${target.name}.`);
  applyDamage(actor, target, damage, breakDamage, pseudoSkill, { canCrit: false });
  if (special.status && alive(target)) {
    addCondition(target, special.status, special.duration || 1);
    log(`${target.name} gains ${special.status} (${special.duration || 1}).`);
  }
  if (special.guardDrain && target.guard > 0) {
    const drained = Math.min(target.guard, special.guardDrain);
    target.guard -= drained;
    actor.barrier += drained;
    log(`${actor.name} steals ${drained} guard and turns it into barrier.`);
    flash(target.instanceId, "break-flash");
  }
}

function enemySpecial(actor) {
  const id = actor.entityId;
  if (id === "rustbound_pilgrim") return { name: "Charged Overhead", damageMult: 1.25, breakMult: 1.25, status: "scorch", duration: 2 };
  if (id === "ivy_strangler") return { name: "Bramble Snare", damageMult: 0.9, breakMult: 0.8, status: "snare", duration: 2 };
  if (id === "flood_acolyte") return { name: "Soaking Cant", damageMult: 0.85, breakMult: 1.0, status: "soak", duration: 2 };
  if (id === "switchblade_drone") return { name: "Switchblade Flurry", damageMult: 1.15, breakMult: 0.9, status: "jolt", duration: 1 };
  if (id === "veil_leech") return { name: "Veil Siphon", damageMult: 0.9, breakMult: 0.8, guardDrain: 10 };
  if (id === "lamp_witness") return { name: "Lamp Verdict", damageMult: 0.8, breakMult: 0.8, status: "reveal", duration: 2 };
  if (id === "toll_knight") return { name: "Halberd Toll", damageMult: 1.35, breakMult: 1.25 };
  if (actor.isBoss) return { name: "Bell Pressure", damageMult: 1.35, breakMult: 1.25, status: "reveal", duration: 1 };
  return { name: "Pressure", damageMult: 1, breakMult: 1 };
}

function chooseEnemyTarget() {
  const candidates = app.battle.players.filter(alive);
  if (!candidates.length) return null;
  return candidates.sort((a, b) => (a.guard + a.hp * 0.5) - (b.guard + b.hp * 0.5))[0];
}

function useSelectedSkill() {
  const battle = app.battle;
  const actor = getActiveActor();
  if (!battle || !actor || actor.team !== "player") return;
  if (!isTurnAxisConfirmedForActor(actor)) {
    setStatus("Confirm Turn Axis before choosing battle actions.", "warning", true);
    return;
  }
  const actionLogStart = battle.log.length;
  const skillId = battle.selectedSkillId;
  if (skillId === "__potion") {
    useHealingPotion(actor);
  } else {
    const skill = app.content.skills[skillId];
    if (!skill) return;
    const spotlightCost = Number(skill.spotlight_cost || 0);
    if (battle.spotlight < spotlightCost) {
      log(`Not enough Spotlight for ${skill.display_name}.`);
      render();
      return;
    }
    battle.spotlight -= spotlightCost;
    if (spotlightCost > 0) {
      flashMarker("__spotlight", "spend-flash");
      log(`Player Spotlight -${spotlightCost} for ${skill.display_name} -> ${battle.spotlight}/${battle.spotlightMax}.`);
    }
    resolvePlayerSkill(actor, skillId, skill);
  }
  const events = playerEventsFromEntries(actor, battleEntriesSince(battle, actionLogStart));
  actor.timesActed = Number(actor.timesActed || 0) + 1;
  battle.nextActorIndex += 1;
  battle.awaitingPlayerId = null;
  clearTurnAxisForNextActor();
  checkBattleEnd();
  if (!battle.battleOver) {
    events.push(...advanceUntilPlayerOrEnd());
  } else {
    events.push(...finishBattleIfNeeded());
  }
  saveLocal("Autosaved turn result.");
  enqueueEvents(events);
}

function resolvePlayerSkill(actor, skillId, skill) {
  const turnAxis = getConfirmedTurnAxisForActor(actor);
  actor.posture = turnAxis ? turnAxis.posture : resolvePosture(getAxisValuesForActor(actor), primaryScaleForSkill(skill)).posture;
  const target = resolveSkillTarget(skill);
  const output = skill.output || {};
  const baseDamage = Number(app.content.rules.damage_tiers[output.damage || "none"] || 0);
  const baseBreak = Number(app.content.rules.break_tiers[output.break || "none"] || 0);
  const multiplier = computeScaleMultiplier(actor, skill);
  let damage = ceil(baseDamage * multiplier);
  let breakDamage = ceil(baseBreak * multiplier);
  if (actor.nextAttackPowerBonus && !["support", "defense", "utility", "stance", "self_buff"].includes(skill.kind)) {
    damage = ceil(damage * (1 + actor.nextAttackPowerBonus * 0.14));
    breakDamage = ceil(breakDamage * (1 + actor.nextAttackPowerBonus * 0.08));
    actor.nextAttackPowerBonus = 0;
  }
  log(`${actor.name} uses ${skill.display_name}.`);

  if (skill.target === "self") {
    applySelfSkill(actor, skill);
    return;
  }
  if (skill.target === "all_allies") {
    applyAllySkill(actor, skill);
    return;
  }
  if (!target) {
    log("No valid target remains.");
    return;
  }

  const effectId = skill.effect_id || "none";
  if (effectId === "execution_drop" && hasCondition(target, "staggered")) damage = ceil(damage * 1.5);
  if (effectId === "final_verse" && (hasCondition(target, "reveal") || hasCondition(target, "staggered"))) damage = ceil(damage * 1.35);
  if (effectId === "last_rite" && (hasCondition(target, "staggered") || hasCondition(target, "hex"))) damage = ceil(damage * 1.35);
  if (effectId === "linebreaker_shot" && target.guard > 0) breakDamage = ceil(breakDamage * 1.35);
  if (effectId === "tuning_fork_cut" && (hasCondition(target, "reveal") || hasCondition(target, "staggered"))) breakDamage = ceil(breakDamage * 1.35);
  if (effectId === "hex_burst" && Object.keys(target.conditions || {}).length) {
    damage = ceil(damage * 1.25);
    const consumed = Object.keys(target.conditions).find((name) => name !== "airborne");
    if (consumed) {
      delete target.conditions[consumed];
      log(`${skill.display_name} consumes ${consumed} on ${target.name}.`);
    }
  }
  if (effectId === "thorn_spiral" && actor.hp <= actor.maxHp / 2) damage = ceil(damage * 1.25);

  const result = applyDamage(actor, target, damage, breakDamage, skill);
  if (!alive(target)) return;

  if (effectId === "read_opening") {
    addCondition(target, "reveal", 1);
    log(`${target.name} is revealed.`);
    if (isAffinityAdvantage(skill.affinity, target.affinity)) changeSpotlight(1, `${actor.name} exploited affinity`);
  }
  if (effectId === "mark_lunge" || effectId === "pinning_round") {
    addCondition(target, "reveal", 2);
    log(`${target.name} is revealed.`);
  }
  if (effectId === "pinning_round") {
    addCondition(target, "snare", 1);
    log(`${target.name} is snared.`);
  }
  if (effectId === "salt_psalm" || effectId === "blood_oath") {
    addCondition(target, "hex", 2);
    log(`${target.name} is hexed.`);
    grantBarrierToLowestGuardAlly(8, actor.name);
  }
  if (effectId === "rain_mark" || effectId === "relay_beacon") {
    addCondition(target, "rain_mark", 2);
    addCondition(target, "reveal", 1);
    log(`${target.name} is marked by relay pressure.`);
  }
  if (effectId === "hex_burst") {
    app.battle.enemies.filter((enemy) => enemy.instanceId !== target.instanceId && alive(enemy)).forEach((enemy) => {
      applyBreakDamage(enemy, ceil(breakDamage * 0.45));
    });
  }
  if (effectId === "anchor_cleave") {
    const loss = ceil(actor.guard * 0.1);
    actor.guard = Math.max(0, actor.guard - loss);
    log(`${actor.name} loses ${loss} guard from Anchor Cleave.`);
  }
  if (effectId === "blood_oath") {
    actor.hp = Math.max(1, actor.hp - 8);
    actor.nextAttackPowerBonus = Math.max(actor.nextAttackPowerBonus || 0, 1);
    changeSpotlight(1, `${actor.name} Blood Oath`);
  }
  if (result.crit && actor.entityId === "duelist") {
    changeSpotlight(1, `${actor.name} passive crit`);
  }
}

function applySelfSkill(actor, skill) {
  const effectId = skill.effect_id || "none";
  if (effectId === "brace") {
    const gained = restoreGuard(actor, ceil(actor.maxGuard * 0.35));
    addCondition(actor, "brace_guard", 1);
    log(`${actor.name} restores ${gained} guard and braces.`);
    flash(actor.instanceId, "reward-flash");
    return;
  }
  if (effectId === "feint_circuit") {
    addCondition(actor, "brace_guard", 1);
    changeSpotlight(1, `${actor.name} Feint Circuit`);
    log(`${actor.name} sets a counter rhythm.`);
    flash(actor.instanceId, "reward-flash");
    return;
  }
  if (effectId === "blood_oath") {
    actor.hp = Math.max(1, actor.hp - 8);
    actor.nextAttackPowerBonus = Math.max(actor.nextAttackPowerBonus || 0, 1);
    changeSpotlight(1, `${actor.name} Blood Oath`);
    log(`${actor.name} primes the next attack with Blood Oath.`);
    flash(actor.instanceId, "reward-flash");
    return;
  }
  const gained = restoreGuard(actor, 8);
  log(`${actor.name} steadies and restores ${gained} guard.`);
  flash(actor.instanceId, "reward-flash");
}

function applyAllySkill(actor, skill) {
  const effectId = skill.effect_id || "none";
  if (effectId === "ward_bell") {
    app.battle.players.filter(alive).forEach((ally) => {
      const gained = restoreGuard(ally, ceil(ally.maxGuard * 0.2));
      if (gained) log(`${ally.name} restores ${gained} guard from Ward Bell.`);
      flash(ally.instanceId, "reward-flash");
    });
    addCondition(actor, "taunt", 1);
    return;
  }
  if (effectId === "undertow_litany") {
    app.battle.players.filter(alive).forEach((ally) => {
      cleanseOneDebuff(ally);
      ally.barrier += 10;
      log(`${ally.name} gains 10 barrier from Undertow Litany.`);
      flash(ally.instanceId, "reward-flash");
    });
    return;
  }
  app.battle.players.filter(alive).forEach((ally) => {
    const gained = restoreGuard(ally, 8);
    if (gained) log(`${ally.name} restores ${gained} guard.`);
  });
}

function useHealingPotion(actor) {
  const battle = app.battle;
  if (battle.healingPotions <= 0) {
    log("No healing potions remain.");
    return;
  }
  let amount = ceil(actor.maxHp * 0.35);
  if (battle.potionUpgradeIds.includes("stronger_potions")) amount = ceil(amount * 1.2);
  const before = actor.hp;
  actor.hp = Math.min(actor.maxHp, actor.hp + amount);
  const healed = actor.hp - before;
  battle.healingPotions -= 1;
  log(`${actor.name} drinks a healing potion and restores ${healed} HP.`);
  if (battle.potionUpgradeIds.includes("guarding_draught")) {
    const gained = restoreGuard(actor, ceil(actor.maxGuard * 0.18));
    log(`${actor.name} restores ${gained} guard from Guarding Draught.`);
  }
  if (battle.potionUpgradeIds.includes("spotlight_tonic")) {
    changeSpotlight(1, `${actor.name} Spotlight Tonic`);
  }
  flash(actor.instanceId, "reward-flash");
}

function resolveSkillTarget(skill) {
  if (skill.target !== "single_enemy") return null;
  const selected = app.battle.enemies.find((enemy) => enemy.instanceId === app.battle.selectedTargetId && alive(enemy));
  return selected || firstLiving(app.battle.enemies);
}

function applyDamage(source, target, damage, breakDamage, skill, options = {}) {
  if (!alive(source) || !alive(target)) {
    return { damageToHp: 0, damageToGuard: 0, breakDamage: 0, crit: false, killed: false };
  }
  const canCrit = options.canCrit !== false;
  let finalDamage = Math.max(0, ceil(damage));
  let finalBreak = Math.max(0, ceil(breakDamage));
  const affinity = affinityModifier(skill.affinity, target.affinity);
  finalDamage = ceil(finalDamage * affinity);
  finalBreak = ceil(finalBreak * (affinity > 1 ? 1.1 : 1));
  if (hasCondition(target, "staggered")) finalDamage = ceil(finalDamage * 1.3);
  if (hasCondition(target, "reveal")) finalDamage = ceil(finalDamage * 1.1);
  if (hasCondition(target, "hex")) finalDamage = ceil(finalDamage * 1.1);

  let crit = false;
  if (canCrit && finalDamage > 0 && Math.random() * 100 < critChance(source, skill, target)) {
    crit = true;
    finalDamage = ceil(finalDamage * 1.5);
    finalBreak = ceil(finalBreak * 1.1);
  }

  let barrierDamage = 0;
  if (target.barrier > 0 && finalDamage > 0) {
    barrierDamage = Math.min(target.barrier, finalDamage);
    target.barrier -= barrierDamage;
    finalDamage -= barrierDamage;
    if (barrierDamage) log(`${target.name}'s barrier absorbs ${barrierDamage} damage.`);
  }

  let guardDamage = 0;
  if (target.guard > 0 && finalDamage > 0) {
    guardDamage = Math.min(target.guard, finalDamage);
    target.guard -= guardDamage;
    finalDamage -= guardDamage;
  }
  let hpDamage = 0;
  if (finalDamage > 0) {
    hpDamage = finalDamage;
    target.hp = Math.max(0, target.hp - hpDamage);
  }
  const dealtBreak = finalBreak > 0 ? applyBreakDamage(target, finalBreak) : 0;
  if (barrierDamage || guardDamage || hpDamage) {
    const chunks = [];
    if (barrierDamage) chunks.push(`${barrierDamage} barrier`);
    if (guardDamage) chunks.push(`${guardDamage} guard`);
    if (hpDamage) chunks.push(`${hpDamage} HP`);
    log(`${source.name} hits ${target.name} for ${chunks.join(", ")}.${crit ? " CRIT." : ""}`);
    flash(target.instanceId, hpDamage ? "damage-flash" : "break-flash");
  }
  if (hpDamage <= 0 && guardDamage <= 0 && dealtBreak > 0) {
    flash(target.instanceId, "break-flash");
  }
  if (target.hp <= 0) {
    target.hp = 0;
    log(`${target.name} falls.`);
    flash(target.instanceId, "damage-flash");
  }
  if (isAffinityAdvantage(skill.affinity, target.affinity) && source.team === "player") {
    changeSpotlight(1, `${source.name} exploited affinity`);
  }
  checkBattleEnd();
  return {
    damageToHp: hpDamage,
    damageToGuard: guardDamage + barrierDamage,
    breakDamage: dealtBreak,
    crit,
    killed: target.hp <= 0,
  };
}

function applyBreakDamage(target, amount) {
  if (amount <= 0 || !alive(target)) return 0;
  const before = target.breakMeter;
  target.breakMeter = Math.max(0, target.breakMeter - ceil(amount));
  const dealt = before - target.breakMeter;
  if (dealt > 0) log(`${target.name} loses ${dealt} break.`);
  if (target.breakMeter <= 0 && !hasCondition(target, "staggered")) {
    addCondition(target, "staggered", 1);
    target.position = "withdrawn";
    log(`${target.name} is staggered.`);
  }
  return dealt;
}

function checkBattleEnd() {
  const battle = app.battle;
  if (!battle || battle.battleOver) return;
  if (!battle.players.some(alive)) {
    battle.battleOver = true;
    battle.winner = "enemy";
  } else if (!battle.enemies.some(alive)) {
    battle.battleOver = true;
    battle.winner = "player";
  }
}

function finishBattleIfNeeded() {
  const battle = app.battle;
  if (!battle || !battle.battleOver) return [];
  const node = getNode(battle.nodeId);
  app.campaign.players = battle.players.map((unit) => clearBattleOnlyState(clone(unit)));
  app.campaign.healingPotions = battle.healingPotions;
  if (battle.winner === "player") {
    log("Players win the battle.");
    app.lastBattleLog = battle.log.slice(-120);
    app.campaign.runShards += Number(node.shards || 0);
    app.campaign.lastOutcome = "node_cleared";
    record(`Cleared ${node.title}. Echo Shards balance: ${app.campaign.runShards}.`);
    app.campaign.pendingResolvedNodeId = node.node_id;
    app.campaign.pendingReward = buildPendingReward(node.reward_table_id);
    const events = [
      {
        type: "battle_victory",
        title: "전투 성공",
        lines: [`${node.title} 전투에서 승리했습니다.`, `Echo Shards +${Number(node.shards || 0)}.`],
      },
    ];
    app.battle = null;
    app.screen = app.campaign.pendingReward ? "reward" : "map";
    if (app.campaign.pendingReward) {
      events.push({
        type: "reward",
        title: "보상/귀환",
        lines: ["보상 선택 화면으로 이동합니다.", `현재 Echo Shards: ${app.campaign.runShards}.`],
      });
    } else {
      completeResolvedNode();
      events.push({
        type: "reward",
        title: "보상/귀환",
        lines: ["다음 이동 지점으로 복귀합니다.", `현재 Echo Shards: ${app.campaign.runShards}.`],
      });
    }
    return events;
  } else {
    log("Enemies win the battle.");
    app.lastBattleLog = battle.log.slice(-120);
    app.campaign.losses += 1;
    app.campaign.bestNodesCleared = Math.max(app.campaign.bestNodesCleared, app.campaign.clearedNodeIds.length);
    app.campaign.lastResult = `Defeat at ${node.title} after clearing ${app.campaign.clearedNodeIds.length} nodes.`;
    app.campaign.lastOutcome = "defeat";
    app.campaign.expeditionActive = false;
    app.campaign.currentNodeId = null;
    app.campaign.availableNodeIds = [];
    app.battle = null;
    app.screen = "result";
    return [
      {
        type: "battle_defeat",
        title: "전투 실패",
        lines: [app.campaign.lastResult],
      },
    ];
  }
}

function buildPendingReward(tableId) {
  if (!tableId) return null;
  const table = app.content.rewardTables[tableId];
  if (!table) return null;
  return {
    tableId,
    tableType: table.table_type || "choice",
    remainingOptionIds: [...(table.options || [])],
    picksLeft: Math.min(Number(table.pick_count || 1), (table.options || []).length),
    purchasesLeft: Number(table.max_purchases || 1),
    boughtOptionIds: [],
  };
}

function chooseReward(optionId) {
  const pending = app.campaign.pendingReward;
  if (!pending) return;
  const option = app.content.rewardOptions[optionId];
  if (!option) return;
  if (pending.tableType === "shop") {
    const reason = rewardUnavailable(optionId);
    if (reason) {
      record(`${option.display_name} unavailable: ${reason}.`);
      render();
      return;
    }
    const result = applyRewardOption(optionId);
    if (result.applied) {
      app.campaign.runShards -= optionCost(option);
      pending.boughtOptionIds.push(optionId);
      pending.purchasesLeft -= 1;
      record(`Shop purchase: ${option.display_name}. ${result.text}`);
    }
    if (pending.purchasesLeft <= 0) {
      completeResolvedNode();
    }
  } else {
    const result = applyRewardOption(optionId);
    pending.remainingOptionIds = pending.remainingOptionIds.filter((id) => id !== optionId);
    pending.picksLeft -= 1;
    record(result.text);
    if (pending.picksLeft <= 0) {
      completeResolvedNode();
    }
  }
  setStatus(`Reward selected: ${option.display_name}.`, "success");
  saveLocal("Autosaved reward choice.");
  render();
}

function skipReward() {
  completeResolvedNode();
  saveLocal("Autosaved after leaving rewards.");
  render();
}

function completeResolvedNode() {
  const nodeId = app.campaign.pendingResolvedNodeId;
  if (!nodeId) return;
  const node = getNode(nodeId);
  if (!app.campaign.clearedNodeIds.includes(nodeId)) {
    app.campaign.clearedNodeIds.push(nodeId);
  }
  app.campaign.bestNodesCleared = Math.max(app.campaign.bestNodesCleared, app.campaign.clearedNodeIds.length);
  app.campaign.pendingReward = null;
  app.campaign.pendingResolvedNodeId = null;
  const next = [...(node.next_node_ids || [])];
  if (!next.length) {
    const district = getDistrict();
    app.campaign.expeditionActive = false;
    app.campaign.currentNodeId = null;
    app.campaign.availableNodeIds = [];
    app.campaign.wins += 1;
    app.campaign.lastResult = `Victory in ${district.display_name}. Echo shards carried out: ${app.campaign.runShards}.`;
    app.campaign.lastOutcome = "victory";
    record(app.campaign.lastResult);
    app.screen = "result";
    return;
  }
  app.campaign.availableNodeIds = next;
  app.campaign.currentNodeId = next[0];
  app.screen = "map";
}

function applyRewardOption(optionId) {
  const option = app.content.rewardOptions[optionId];
  const params = option;
  if (option.effect_type === "party_stat_boost") {
    const amount = Number(params.amount || 0);
    if (params.stat === "max_guard") {
      app.campaign.players.forEach((unit) => {
        unit.maxGuard += amount;
        if (params.restore_current_on_gain) unit.guard = Math.min(unit.maxGuard, unit.guard + amount);
      });
      app.campaign.boons.push(optionId);
      return { applied: true, text: "The team threads bellwire mesh through their armor. Max guard rises." };
    }
    if (params.stat === "speed") {
      app.campaign.players.forEach((unit) => { unit.speed += amount; });
      app.campaign.boons.push(optionId);
      return { applied: true, text: "Signal wire tuning sharpens reflexes. Speed rises." };
    }
    if (params.stat === "max_hp") {
      const healAmount = scaledHealingReward(Number(params.heal_amount || 0));
      let healed = 0;
      app.campaign.players.forEach((unit) => {
        unit.maxHp += amount;
        const before = unit.hp;
        unit.hp = Math.min(unit.maxHp, unit.hp + healAmount);
        healed += unit.hp - before;
      });
      app.campaign.boons.push(optionId);
      return { applied: true, text: `Max HP rises and the party restores ${healed} HP.` };
    }
    if (params.stat === "max_break") {
      app.campaign.players.forEach((unit) => {
        unit.maxBreak += amount;
        if (params.refill_to_max) unit.breakMeter = unit.maxBreak;
      });
      app.campaign.boons.push(optionId);
      return { applied: true, text: "All allies gain max Break." };
    }
  }
  if (option.effect_type === "campaign_counter_boost") {
    const counter = params.counter;
    const before = Number(app.campaign[counter] || 0);
    let after = before + Number(params.amount || 0);
    if (params.max_value !== undefined) after = Math.min(after, Number(params.max_value));
    app.campaign[counter] = after;
    const gained = after - before;
    if (gained <= 0) return { applied: false, text: `${option.display_name} is already capped.` };
    app.campaign.boons.push(optionId);
    return { applied: true, text: `${option.display_name} improves ${counter} by ${gained}.` };
  }
  if (option.effect_type === "party_heal") {
    const amount = scaledHealingReward(Number(params.amount || 0));
    let healed = 0;
    app.campaign.players.forEach((unit) => {
      const before = unit.hp;
      unit.hp = Math.min(unit.maxHp, unit.hp + amount);
      healed += unit.hp - before;
    });
    if (healed <= 0) return { applied: false, text: "No one needs healing right now." };
    app.campaign.boons.push(optionId);
    return { applied: true, text: `Field dressings restore ${healed} total HP.` };
  }
  if (option.effect_type === "recovery_charge_boost") {
    const before = app.campaign.recoveryCharges;
    app.campaign.maxRecoveryCharges = Math.min(Number(params.max_cap || 5), app.campaign.maxRecoveryCharges + Number(params.amount || 0));
    app.campaign.recoveryCharges = Math.min(app.campaign.maxRecoveryCharges, app.campaign.recoveryCharges + Number(params.amount || 0));
    const gained = app.campaign.recoveryCharges - before;
    if (gained <= 0) return { applied: false, text: "The team cannot carry more recovery supplies." };
    app.campaign.boons.push(optionId);
    return { applied: true, text: `Recovery charges increase by ${gained}.` };
  }
  if (option.effect_type === "grant_relic") {
    const relicId = params.relic_id;
    let added = false;
    app.campaign.players.forEach((unit) => {
      unit.metadata.relicIds = unit.metadata.relicIds || [];
      unit.metadata.relicNames = unit.metadata.relicNames || [];
      if (!unit.metadata.relicIds.includes(relicId)) {
        unit.metadata.relicIds.push(relicId);
        unit.metadata.relicNames.push(relicName(relicId));
        added = true;
      }
    });
    if (!added) return { applied: false, text: `${relicName(relicId)} was already carried.` };
    app.campaign.boons.push(optionId);
    return { applied: true, text: `The team secures ${relicName(relicId)}.` };
  }
  if (option.effect_type === "grant_potion_upgrade") {
    const upgradeId = params.upgrade_id;
    if (app.campaign.potionUpgradeIds.includes(upgradeId)) {
      return { applied: false, text: "The route kit already carries that potion upgrade." };
    }
    app.campaign.potionUpgradeIds.push(upgradeId);
    app.campaign.boons.push(optionId);
    if (upgradeId === "potion_capacity_plus_one") {
      app.campaign.healingPotions = Math.min(potionCapacity(), app.campaign.healingPotions + 1);
    }
    return { applied: true, text: `${option.display_name} is added to the route kit.` };
  }
  return { applied: false, text: `${option.display_name} has no web adapter effect yet.` };
}

function useRecoveryCharge() {
  if (!app.campaign.expeditionActive || app.campaign.recoveryCharges <= 0) return;
  const candidates = app.campaign.players.filter((unit) => (
    alive(unit) && (unit.hp < unit.maxHp || unit.guard < unit.maxGuard || unit.breakMeter < unit.maxBreak)
  ));
  if (!candidates.length) return;
  const target = candidates.sort((a, b) => (a.hp / a.maxHp) - (b.hp / b.maxHp))[0];
  const amount = scaledRecoveryHeal(45);
  const before = target.hp;
  target.hp = Math.min(target.maxHp, target.hp + amount);
  target.guard = target.maxGuard;
  target.breakMeter = target.maxBreak;
  app.campaign.recoveryCharges -= 1;
  record(`Used a recovery charge on ${target.name}, restoring ${target.hp - before} HP, Guard, and Break.`);
  saveLocal("Autosaved recovery use.");
  render();
}

function rewardUnavailable(optionId) {
  const pending = app.campaign.pendingReward;
  const option = app.content.rewardOptions[optionId];
  if (!pending || !option) return "unavailable";
  if (pending.boughtOptionIds.includes(optionId)) return "already bought here";
  if (option.effect_type === "grant_relic" && partyHasRelic(option.relic_id)) return "already carried";
  if (option.effect_type === "grant_potion_upgrade" && app.campaign.potionUpgradeIds.includes(option.upgrade_id)) return "already carried";
  if (option.effect_type === "campaign_counter_boost" && option.max_value !== undefined) {
    if (Number(app.campaign[option.counter] || 0) >= Number(option.max_value)) return "at cap";
  }
  if (optionCost(option) > app.campaign.runShards) {
    return `need ${optionCost(option) - app.campaign.runShards} more shards`;
  }
  return "";
}

function optionCost(option) {
  return Math.max(0, Number(option.cost || 0));
}

function scaledHealingReward(amount) {
  return scaledAmount(amount, partyBalanceProfile(app.campaign.players.length).healingRewardMult);
}

function scaledRecoveryHeal(amount) {
  return scaledAmount(amount, partyBalanceProfile(app.campaign.players.length).recoveryHealMult);
}

function potionCapacity() {
  return DEFAULT_HEALING_POTIONS + (app.campaign.potionUpgradeIds.includes("potion_capacity_plus_one") ? 1 : 0);
}

function partyHasRelic(relicId) {
  return app.campaign.players.length > 0 && app.campaign.players.every((unit) => (
    (unit.metadata.relicIds || []).includes(relicId)
  ));
}

function getActiveActor() {
  const battle = app.battle;
  if (!battle || !battle.turnOrderIds.length) return null;
  const id = battle.turnOrderIds[battle.nextActorIndex];
  return [...battle.players, ...battle.enemies].find((unit) => unit.instanceId === id) || null;
}

function firstLiving(units) {
  return units.find(alive) || null;
}

function alive(unit) {
  return unit && unit.hp > 0;
}

function addCondition(unit, name, duration) {
  unit.conditions = unit.conditions || {};
  unit.conditions[name] = Math.max(Number(duration), Number(unit.conditions[name] || 0));
}

function hasCondition(unit, name) {
  return Number(unit.conditions && unit.conditions[name] || 0) > 0;
}

function cleanseOneDebuff(unit) {
  const found = Object.keys(unit.conditions || {}).find((name) => NEGATIVE_STATUSES.has(name));
  if (found) {
    delete unit.conditions[found];
    log(`${unit.name} is cleansed of ${found}.`);
    return true;
  }
  return false;
}

function restoreGuard(unit, amount) {
  const before = unit.guard;
  unit.guard = Math.min(unit.maxGuard, unit.guard + Math.max(0, amount));
  return unit.guard - before;
}

function grantBarrierToLowestGuardAlly(amount, sourceName) {
  const allies = app.battle.players.filter(alive);
  if (!allies.length) return;
  const target = allies.sort((a, b) => (a.guard / a.maxGuard) - (b.guard / b.maxGuard))[0];
  target.barrier += amount;
  log(`${target.name} gains ${amount} barrier from ${sourceName}.`);
  flash(target.instanceId, "reward-flash");
}

function clampAxisValue(value) {
  return clampInt(Number(value), 0, 100, DEFAULT_AXIS.power);
}

function bandForAxisValue(value) {
  const axisValue = clampAxisValue(value);
  const bands = app.content.rules.bands || [];
  const band = bands.find((item) => axisValue >= Number(item.min) && axisValue <= Number(item.max));
  if (!band) return { index: 0, name: "frayed", min: 0, max: 19 };
  return {
    index: Number(band.index),
    name: String(band.name || "unknown"),
    min: Number(band.min),
    max: Number(band.max),
  };
}

function bandIndexForValue(value) {
  return bandForAxisValue(value).index;
}

function apFromComposure(composure) {
  const value = clampAxisValue(composure);
  if (value < 40) return 1;
  if (value < 60) return 2;
  if (value < 80) return 3;
  if (value < 95) return 4;
  return 5;
}

function resolvePosture(axisValues, primaryScale = "power") {
  const axes = normalizeAxis(axisValues);
  const indices = {
    power: bandIndexForValue(axes.power),
    precision: bandIndexForValue(axes.precision),
    composure: bandIndexForValue(axes.composure),
  };
  const values = Object.values(indices);
  if (Math.max(...values) - Math.min(...values) <= 1) {
    return { posture: "flow", reason: "balanced spread", indices };
  }
  const highest = Math.max(...values);
  const tied = Object.keys(indices).filter((key) => indices[key] === highest);
  const highestRaw = Math.max(...tied.map((key) => axes[key]));
  const rawTied = tied.filter((key) => axes[key] === highestRaw);
  const dominant = rawTied.includes(primaryScale)
    ? primaryScale
    : rawTied.find((key) => AXIS_KEYS.includes(key)) || "power";
  return {
    posture: { power: "ravage", precision: "focus", composure: "bastion" }[dominant] || "flow",
    reason: `${dominant} dominant`,
    indices,
  };
}

function resolveTurnAxis(values, actor) {
  const normalized = normalizeAxis(values);
  const defaultSkill = actor ? defaultTurnSkillForActor(actor) : null;
  const resolvedPosture = resolvePosture(normalized, primaryScaleForSkill(defaultSkill));
  const bands = Object.fromEntries(AXIS_KEYS.map((key) => [key, bandForAxisValue(normalized[key])]));
  return {
    values: normalized,
    bands,
    posture: resolvedPosture.posture,
    postureReason: resolvedPosture.reason,
    ap: apFromComposure(normalized.composure),
  };
}

function defaultTurnSkillForActor(actor) {
  if (!actor || !Array.isArray(actor.skills)) return null;
  const skills = actor.skills.map((skillId) => app.content.skills[skillId]).filter(Boolean);
  return skills.find((skill) => ["attack", "spell", "ranged_attack", "finisher"].includes(skill.kind)) || skills[0] || null;
}

function primaryScaleForSkill(skill) {
  return String(skill && skill.scale && skill.scale.primary || "power");
}

function getDefaultTurnAxis(battle = app.battle) {
  if (battle && battle.lastTurnAxisDefaults) {
    return normalizeAxis(battle.lastTurnAxisDefaults);
  }
  if (app.campaign && app.campaign.lastTurnAxisDefaults) {
    return normalizeAxis(app.campaign.lastTurnAxisDefaults);
  }
  return { ...DEFAULT_AXIS };
}

function getConfirmedTurnAxisForActor(actor) {
  const battle = app.battle;
  if (!battle || !actor || !battle.currentTurnAxis) return null;
  return battle.currentTurnAxis.actorId === actor.instanceId ? battle.currentTurnAxis : null;
}

function isTurnAxisConfirmedForActor(actor) {
  return Boolean(getConfirmedTurnAxisForActor(actor));
}

function getAxisValuesForActor(actor) {
  const confirmed = getConfirmedTurnAxisForActor(actor);
  if (confirmed) return confirmed.values;
  return app.battle ? app.battle.nodeAxisScores : DEFAULT_AXIS;
}

function confirmTurnAxisInput(actor, values) {
  const battle = app.battle;
  if (!battle || !actor || actor.team !== "player") return;
  const resolved = resolveTurnAxis(values, actor);
  battle.currentTurnAxis = {
    actorId: actor.instanceId,
    values: resolved.values,
    bands: resolved.bands,
    posture: resolved.posture,
    postureReason: resolved.postureReason,
    ap: resolved.ap,
    round: battle.round,
    confirmedAt: new Date().toISOString(),
  };
  battle.lastTurnAxisDefaults = { ...resolved.values };
  app.campaign.lastTurnAxisDefaults = { ...resolved.values };
  actor.posture = resolved.posture;
  actor.currentAp = resolved.ap;
  actor.startingAp = resolved.ap;
  log(
    `Turn input: Power ${resolved.values.power} / Precision ${resolved.values.precision} / Composure ${resolved.values.composure} -> ${titleFromSlug(resolved.posture)}, ${resolved.ap} AP`,
    "system",
  );
  saveLocal("Autosaved turn input.");
  render();
}

function clearTurnAxisForNextActor() {
  if (app.battle) {
    app.battle.currentTurnAxis = null;
  }
}

function computeScaleMultiplier(actor, skill) {
  const axes = getAxisValuesForActor(actor);
  let primaryIdx = bandIndexForValue(axes[skill.scale.primary]);
  let secondaryIdx = bandIndexForValue(axes[skill.scale.secondary]);
  if (actor.entityId === "penitent" && skill.kind === "finisher" && actor.hp <= actor.maxHp / 2) {
    if (skill.scale.primary === "power") primaryIdx = Math.min(4, primaryIdx + 1);
    if (skill.scale.secondary === "power") secondaryIdx = Math.min(4, secondaryIdx + 1);
  }
  return 0.78 + 0.17 * primaryIdx + 0.07 * secondaryIdx;
}

function affinityModifier(skillAffinity, targetAffinity) {
  if (!skillAffinity || skillAffinity === "neutral") return 1;
  const affinities = app.content.affinities.affinities || {};
  if (affinities[skillAffinity] && affinities[skillAffinity].strong_vs === targetAffinity) return 1.25;
  if (affinities[targetAffinity] && affinities[targetAffinity].strong_vs === skillAffinity) return 0.8;
  return 1;
}

function isAffinityAdvantage(skillAffinity, targetAffinity) {
  const affinities = app.content.affinities.affinities || {};
  return Boolean(skillAffinity && affinities[skillAffinity] && affinities[skillAffinity].strong_vs === targetAffinity);
}

function critChance(actor, skill, target) {
  const precision = getAxisValuesForActor(actor).precision;
  let chance = 5 + bandIndexForValue(precision) * 5;
  if (actor.entityId === "duelist") chance += 8;
  if (hasCondition(target, "reveal")) chance += 8;
  if (hasCondition(target, "staggered")) chance += 10;
  if (skill.kind === "finisher") chance += 5;
  return Math.min(60, chance);
}

function changeSpotlight(amount, reason) {
  const battle = app.battle;
  if (!battle) return;
  const old = battle.spotlight;
  battle.spotlight = clampInt(battle.spotlight + amount, 0, battle.spotlightMax, old);
  const delta = battle.spotlight - old;
  if (delta) {
    log(`Player Spotlight ${delta > 0 ? "+" : ""}${delta} (${reason}) -> ${battle.spotlight}/${battle.spotlightMax}.`);
    flashMarker("__spotlight", delta > 0 ? "reward-flash" : "spend-flash");
  }
}

function log(text, kind = "") {
  if (!app.battle) return;
  app.battle.log.push({ round: app.battle.round, text, kind: kind || logKind(text) });
  app.battle.log = app.battle.log.slice(-120);
}

function logKind(text) {
  const value = String(text || "").toLowerCase();
  if (value.includes("wins") || value.includes("restores") || value.includes("gains") || value.includes("ready")) return "gain";
  if (value.includes("falls") || value.includes("defeat") || value.includes("hits") || value.includes("damage") || value.includes("scorched")) return "danger";
  if (value.includes("spotlight")) return "spotlight";
  if (value.includes("turn input") || value.includes("route baseline")) return "system";
  if (value.includes("break") || value.includes("staggered") || value.includes("guard")) return "break";
  if (value.includes("turn order") || value.includes("battle begins") || value.includes("encounter")) return "system";
  return "info";
}

function record(text) {
  app.campaign.reportLines.push(text);
  app.campaign.reportLines = app.campaign.reportLines.slice(-200);
}

function clearEventQueue(rerender = true) {
  app.presentation.queue = [];
  app.presentation.current = null;
  if (rerender) render();
}

function enqueueEvents(events) {
  const normalized = (events || []).filter((event) => event && Array.isArray(event.lines) && event.lines.length);
  if (!normalized.length) {
    render();
    return;
  }
  app.presentation.queue.push(...normalized);
  if (!app.presentation.current) {
    app.presentation.current = app.presentation.queue.shift();
  }
  render();
}

function nextPresentationEvent() {
  if (app.presentation.queue.length) {
    app.presentation.current = app.presentation.queue.shift();
  } else {
    app.presentation.current = null;
  }
  render();
}

function battleEntriesSince(battle, startIndex) {
  if (!battle || !Array.isArray(battle.log)) return [];
  return battle.log.slice(startIndex);
}

function eventFromEntries(type, title, entries, extra = {}) {
  return {
    type,
    title,
    lines: entries.map((entry) => entry.text || String(entry)).filter(Boolean),
    ...extra,
  };
}

function playerEventsFromEntries(actor, entries) {
  if (!entries.length) return [];
  const actionEntries = entries.filter((entry) => {
    const text = entry.text || "";
    return text.includes(actor.name) && (text.includes("uses ") || text.includes("drinks "));
  });
  const resultEntries = entries.filter((entry) => !actionEntries.includes(entry));
  const events = [eventFromEntries("player_action", "플레이어 행동", actionEntries.length ? actionEntries : entries.slice(0, 1), { actor: actor.name })];
  if (resultEntries.length) {
    events.push(eventFromEntries("player_result", "행동 결과", resultEntries, { actor: actor.name }));
  }
  return events;
}

function enemyEventsFromEntries(actor, entries) {
  if (!entries.length) return [];
  const attackEntries = entries.filter((entry) => {
    const text = entry.text || "";
    return text.includes(actor.name) && text.includes("uses ");
  });
  const resultEntries = entries.filter((entry) => !attackEntries.includes(entry));
  const events = [eventFromEntries("enemy_attack", "적의 공격", attackEntries.length ? attackEntries : entries.slice(0, 1), { actor: actor.name })];
  if (resultEntries.length) {
    events.push(eventFromEntries("enemy_result", "피해 결과", resultEntries, { actor: actor.name }));
  }
  return events;
}

function flash(unitId, className) {
  flashMarker(unitId, className);
}

function flashMarker(key, className) {
  if (!app.battle) return;
  app.battle.effects[key] = className;
  window.setTimeout(() => {
    if (app.battle && app.battle.effects) {
      delete app.battle.effects[key];
      render();
    }
  }, 760);
}

function encounterName(id) {
  return (app.content.enemies[id] && app.content.enemies[id].display_name)
    || (app.content.bosses[id] && app.content.bosses[id].display_name)
    || id;
}

function relicName(id) {
  return (app.content.relics[id] && app.content.relics[id].display_name) || id;
}

function weightedChoice(items, weightFn) {
  const total = items.reduce((sum, item) => sum + weightFn(item), 0);
  let roll = Math.random() * total;
  for (const item of items) {
    roll -= weightFn(item);
    if (roll <= 0) return item;
  }
  return items[items.length - 1];
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function ceil(value) {
  return Math.ceil(Number(value) || 0);
}

function clampInt(value, low, high, fallback = 0) {
  const parsed = Number.isFinite(value) ? Math.trunc(value) : fallback;
  return Math.max(low, Math.min(high, parsed));
}

function pct(value, max) {
  if (!max || max <= 0) return "0%";
  return `${Math.max(0, Math.min(100, Math.round((value / max) * 100)))}%`;
}

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function artLookupKey(value) {
  return String(value || "")
    .replace(/\s+#\d+$/, "")
    .trim();
}

function entityArtSource(entity) {
  const candidates = [];
  if (entity && typeof entity === "object") {
    candidates.push(entity.entityId, entity.name, entity.displayName);
    if (entity.metadata) candidates.push(entity.metadata.blueprintId);
  } else {
    candidates.push(entity);
  }
  for (const candidate of candidates) {
    const key = artLookupKey(candidate);
    if (key && ART.entities[key]) return ART.entities[key];
    const titleKey = titleFromSlug(key);
    if (titleKey && ART.entities[titleKey]) return ART.entities[titleKey];
  }
  return "";
}

function entityArtLabel(entity) {
  if (entity && typeof entity === "object") {
    return artLookupKey(entity.name || entity.displayName || titleFromSlug(entity.entityId));
  }
  return artLookupKey(entity);
}

function entityInitials(label) {
  const words = String(label || "QR").replaceAll("_", " ").split(/\s+/).filter(Boolean);
  return words.slice(0, 2).map((word) => word[0].toUpperCase()).join("") || "QR";
}

function renderTitleArt() {
  return `
    <div class="hero-art" data-art-frame>
      <img class="hero-art-image" src="${esc(ART.title)}" alt="Quiet Relay title screen artwork" decoding="async" fetchpriority="high" onerror="${ART_ERROR_HANDLER}">
      <div class="hero-art-fallback" aria-hidden="true">Quiet Relay</div>
    </div>
  `;
}

function renderEntityArt(entity, className = "") {
  const src = entityArtSource(entity);
  if (!src) return "";
  const label = entityArtLabel(entity);
  return `
    <div class="entity-art-frame ${esc(className)}" data-art-frame>
      <img class="entity-art-image" src="${esc(src)}" alt="${esc(label)} artwork" loading="lazy" decoding="async" onerror="${ART_ERROR_HANDLER}">
      <span class="entity-art-fallback" aria-hidden="true">${esc(entityInitials(label))}</span>
    </div>
  `;
}

function renderEventEntityArt(event) {
  const seen = new Set();
  const pieces = [event && event.actor, event && event.target, event && event.targetName]
    .map((name) => {
      const src = entityArtSource(name);
      const label = entityArtLabel(name);
      const key = `${src}|${label}`;
      if (!src || seen.has(key)) return "";
      seen.add(key);
      return renderEntityArt(label, "event-entity-art");
    })
    .filter(Boolean);
  return pieces.length ? `<div class="event-art-row">${pieces.join("")}</div>` : "";
}

function iconSpan(key) {
  const icon = UI_ICONS[key] || "";
  return icon ? `<span class="emoji" aria-hidden="true">${esc(icon)}</span>` : "";
}

function axisTripletLabel(values) {
  const axes = normalizeAxis(values);
  return `${UI_ICONS.power} ${axes.power} / ${UI_ICONS.precision} ${axes.precision} / ${UI_ICONS.composure} ${axes.composure}`;
}

function renderPostureLabel(posture) {
  const key = String(posture || "flow");
  return `${iconSpan(key)} ${esc(titleFromSlug(key))}`;
}

function skillIconKey(skill) {
  if (!skill) return "battle";
  if (skill.kind === "defense" || skill.effect_id === "brace") return "guard";
  if (skill.kind === "support" || skill.target === "all_allies") return "barrier";
  if (skill.kind === "finisher") return "spotlight";
  if (skill.scale && skill.scale.primary === "precision") return "precision";
  if (skill.scale && skill.scale.primary === "composure") return "composure";
  return "power";
}

function formatTime(value) {
  if (!value) return "unknown time";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "unknown time";
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function titleFromSlug(value) {
  return String(value || "")
    .replaceAll("-", "_")
    .split("_")
    .filter(Boolean)
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(" ");
}

function render() {
  const root = document.getElementById("app");
  if (app.screen === "loading") {
    root.innerHTML = `
      <main class="layout screen menu">
        <section class="empty-state">
          <div class="sigil" aria-hidden="true"></div>
          <p class="eyebrow">Loading content</p>
          <h1>Quiet Relay</h1>
          <p>Preparing local data, save hooks, and offline cache status.</p>
        </section>
      </main>
    `;
    return;
  }
  if (app.screen === "error") {
    root.innerHTML = renderError();
    return;
  }
  if (app.presentation.current) {
    root.innerHTML = renderPresentationEvent(app.presentation.current);
    return;
  }
  if (app.screen === "menu") root.innerHTML = renderMenu();
  if (app.screen === "party") root.innerHTML = renderPartyScreen();
  if (app.screen === "map") root.innerHTML = renderMapScreen();
  if (app.screen === "battle") {
    root.innerHTML = renderBattleScreen();
    scrollCombatLogToBottom();
  }
  if (app.screen === "reward") root.innerHTML = renderRewardScreen();
  if (app.screen === "result") root.innerHTML = renderResultScreen();
}

function renderPresentationEvent(event) {
  const tone = event.type === "battle_victory"
    ? "victory"
    : event.type === "battle_defeat"
      ? "defeat"
      : event.type && event.type.startsWith("enemy")
        ? "enemy"
        : event.type === "reward"
          ? "reward"
          : "player";
  const remaining = app.presentation.queue.length;
  const logEntries = app.battle ? combatLogEntries(app.battle, 40) : app.lastBattleLog.slice(-40);
  return `
    <main class="layout screen event-screen-wrap">
      ${renderStatusStrip()}
      <section class="event-screen ${tone}">
        <p class="eyebrow">${esc(titleFromSlug(event.type || "event"))}</p>
        <h1>${esc(event.title || "전투 진행")}</h1>
        ${renderEventEntityArt(event)}
        ${event.actor ? `<p class="meta">${esc(event.actor)}</p>` : ""}
        <div class="event-lines" role="log" aria-live="polite">
          ${event.lines.map((line) => `<div class="event-line">${esc(line)}</div>`).join("")}
        </div>
        <div class="button-row center event-actions">
          <button class="primary" data-action="next-event">${remaining ? `${iconSpan("continue")} 다음 (${remaining})` : `${iconSpan("continue")} 계속`}</button>
        </div>
      </section>
      <section class="log-panel event-log-panel">
        <div class="panel-title"><h3>${iconSpan("battle")} 전체 로그</h3></div>
        <div class="combat-log">
          ${logEntries.length ? logEntries.map(renderCombatLogEntry).join("") : `<p class="meta">No combat events yet.</p>`}
        </div>
      </section>
    </main>
  `;
}

function renderError() {
  return `
    <main class="layout">
      ${renderStatusStrip()}
      <section class="empty-state error-state">
        <div class="sigil" aria-hidden="true"></div>
        <p class="eyebrow">Content load failed</p>
        <h1>Quiet Relay</h1>
        <p>${esc(app.error)}</p>
        <p class="meta">Serve the folder with: <code>python3 -m http.server 8765 --directory web</code></p>
      </section>
    </main>
  `;
}

function renderStatusStrip() {
  const save = readSaveRecord();
  const saveText = save ? `Save ${save.key === SAVE_KEY ? "v3" : "legacy"} found` : "No browser save";
  const networkText = app.online ? "Online" : "Offline";
  const serverTone = app.server.available === false ? "offline" : "online";
  const serverText = app.server.available === false ? app.server.message : app.server.message || "Server save not checked";
  const toast = app.status ? `<span class="toast ${esc(app.status.tone)}">${esc(app.status.text)}</span>` : "";
  return `
    <aside class="status-strip" role="status" aria-live="polite">
      <span class="status-chip ${app.online ? "online" : "offline"}">${iconSpan(app.online ? "online" : "offline")} ${networkText}</span>
      <span class="status-chip">${iconSpan("save")} ${esc(saveText)}</span>
      <span class="status-chip ${serverTone}">${iconSpan("online")} ${esc(serverText)}</span>
      <span class="status-chip">${iconSpan(app.online ? "online" : "offline")} ${esc(app.pwa.message)}</span>
      ${app.pwa.updateAvailable ? `<button class="mini-button" data-action="refresh-app">${iconSpan("load")} Reload Update</button>` : ""}
      ${toast}
    </aside>
  `;
}

function renderMenu() {
  const hasSave = hasSaveRecord();
  const district = getDistrict();
  const resultTone = app.campaign.lastOutcome === "victory" ? "victory" : app.campaign.lastOutcome === "defeat" ? "defeat" : "neutral";
  return `
    <main class="layout screen menu">
      ${renderStatusStrip()}
      <section class="menu-grid">
        <div class="hero-panel">
          ${renderTitleArt()}
          <div>
            <div class="hero-kicker">${iconSpan("battle")} Phase 3 turn-axis web prototype</div>
            <h1 class="hero-title">Quiet Relay</h1>
            <p class="hero-copy">
              A darker browser front end for ${esc(district.display_name)} with route pressure,
              guard breaks, barrier spikes, Spotlight turns, and local-first saves.
            </p>
          </div>
          <div class="hero-stat-grid">
            <span><strong>${iconSpan("party")} ${Object.keys(app.content.characters).length}</strong> Operatives</span>
            <span><strong>${iconSpan("route")} ${district.node_order.length}</strong> Route Nodes</span>
            <span><strong>${iconSpan("shards")} ${Object.keys(app.content.rewardOptions).length}</strong> Rewards</span>
            <span><strong>${iconSpan("offline")} Offline</strong> App Shell</span>
          </div>
        </div>
        <div class="menu-actions">
          <button class="primary" data-action="go-party">${iconSpan("route")} New Expedition</button>
          <button class="secondary" data-action="load-game" ${hasSave || app.server.sessionId ? "" : "disabled"}>${iconSpan("load")} Load Current Save</button>
          <button class="secondary" data-action="refresh-saves">${iconSpan("online")} Refresh Server Saves</button>
          <button class="secondary" data-action="go-map" ${app.campaign.expeditionActive ? "" : "disabled"}>${iconSpan("playerTurn")} Resume Current Run</button>
          <button class="danger" data-action="reset-local" ${hasSave ? "" : "disabled"}>${iconSpan("save")} Clear Browser Save</button>
          ${renderServerSaveList()}
          <div class="panel result-banner ${resultTone}">
            <div class="panel-title"><h3>Last Result</h3></div>
            <p class="meta">${esc(app.campaign.lastResult)}</p>
            <div class="pill-row">
              <span class="pill">${iconSpan("victory")} Wins ${app.campaign.wins}</span>
              <span class="pill">${iconSpan("defeat")} Losses ${app.campaign.losses}</span>
              <span class="pill">${iconSpan("route")} Best ${app.campaign.bestNodesCleared}</span>
              <span class="pill">${iconSpan("save")} Save ${esc(app.campaign.loadSource || "new")}</span>
            </div>
          </div>
        </div>
      </section>
    </main>
  `;
}

function renderServerSaveList() {
  if (app.server.available === false) {
    return `
      <div class="panel save-list">
        <div class="panel-title"><h3>${iconSpan("save")} Server Saves</h3></div>
        <p class="meta">Server save API is unavailable. Browser save still works on this device.</p>
      </div>
    `;
  }
  const saves = app.server.saves || [];
  return `
    <div class="panel save-list">
      <div class="panel-title"><h3>${iconSpan("save")} Server Saves</h3><span class="meta">${saves.length} found</span></div>
      ${saves.length ? saves.slice(-6).reverse().map((save) => {
        const summary = save.summary || {};
        const progress = summary.progress || {};
        return `
          <button class="save-card" data-action="load-server-save" data-id="${esc(save.session_id)}">
            <span class="save-name">${iconSpan("load")} ${esc(summary.party || "Quiet Relay Save")}<span class="pill">${esc(formatTime(save.saved_at))}</span></span>
            <span class="meta">${esc(progress.node_title || progress.node_id || "Hub")} | Shards ${esc(progress.run_shards ?? 0)} | Cleared ${esc(progress.nodes_cleared ?? 0)}</span>
            <span class="fine">${summary.in_battle ? "Battle in progress" : "Campaign state"}</span>
          </button>
        `;
      }).join("") : `<p class="meta">No server saves yet.</p>`}
    </div>
  `;
}

function renderShell(title, subtitle, body) {
  return `
    <main class="layout screen">
      ${renderStatusStrip()}
      <header class="topbar">
        <div class="brand">
          <h2>${esc(title)}</h2>
          <div class="subtitle">${esc(subtitle)}</div>
        </div>
        <div class="top-actions">
          <button data-action="go-menu">${iconSpan("hub")} Menu</button>
          <button data-action="save-game">${iconSpan("save")} Save</button>
          <button data-action="load-game">${iconSpan("load")} Load</button>
        </div>
      </header>
      ${body}
    </main>
  `;
}

function renderPartyScreen() {
  const selected = app.content.characters[app.selectedCharacterId];
  const statUnit = createPlayer(app.selectedCharacterId);
  const body = `
    <section class="grid-2">
      <div class="panel">
        <div class="panel-title"><h3>${iconSpan("party")} Start Screen</h3><span class="meta">Solo expedition baseline</span></div>
        <div class="character-list">
          ${Object.entries(app.content.characters).map(([id, character]) => `
            <button class="character-button ${id === app.selectedCharacterId ? "selected" : ""}" data-action="select-character" data-id="${esc(id)}">
              ${renderEntityArt({ entityId: id, name: character.display_name }, "character-thumb")}
              <span class="character-copy">
                <span class="character-name">${iconSpan("party")} ${esc(character.display_name)}<span class="pill">${esc(character.default_affinity)}</span></span>
                <span class="meta">${esc(character.role)}</span>
                <span class="fine">${esc(character.passive || "")}</span>
              </span>
            </button>
          `).join("")}
        </div>
      </div>
      <div class="panel">
        <div class="panel-title"><h3>${esc(selected.display_name)}</h3><span class="meta">${esc(selected.role)}</span></div>
        ${renderUnitCard(statUnit, "player", false)}
        <div class="subpanel">
          <div class="panel-title"><h3>Skills</h3></div>
          <div class="pill-row">
            ${selected.skills.map((skillId) => `<span class="pill">${esc(app.content.skills[skillId].display_name)}</span>`).join("")}
          </div>
        </div>
        <div class="button-row">
          <button class="primary" data-action="start-expedition">${iconSpan("route")} Start Expedition</button>
          <button class="secondary" data-action="go-menu">Back</button>
        </div>
      </div>
    </section>
  `;
  return renderShell("Party Selection", "Choose the active relay operative for this browser baseline.", body);
}

function renderMapScreen() {
  const district = getDistrict();
  const hub = getEvent(district.hub_event_id);
  const available = new Set(app.campaign.availableNodeIds || []);
  const cleared = new Set(app.campaign.clearedNodeIds || []);
  const body = `
    <section class="panel">
      <div class="panel-title"><h3>${esc(district.display_name)}</h3><span class="meta">${esc(hub.title)}</span></div>
      <p class="meta">${esc(hub.text)}</p>
      <div class="pill-row">
        <span class="pill">${iconSpan("shards")} Echo Shards ${app.campaign.runShards}</span>
        <span class="pill">${iconSpan("recovery")} Recovery ${app.campaign.recoveryCharges}/${app.campaign.maxRecoveryCharges}</span>
        <span class="pill">${iconSpan("potion")} Potions ${app.campaign.healingPotions}/${potionCapacity()}</span>
        <span class="pill">${iconSpan("spotlight")} Start Spotlight ${app.campaign.startingSpotlight}</span>
        <span class="pill">${iconSpan("barrier")} Prebattle Barrier ${app.campaign.prebattleBarrier}</span>
        <span class="pill">${iconSpan("boss")} Boss Guard Penalty ${app.campaign.bossGuardPenalty}</span>
      </div>
      <div class="button-row" style="margin-top:12px">
        <button class="secondary" data-action="use-recovery" ${app.campaign.recoveryCharges > 0 ? "" : "disabled"}>${iconSpan("recovery")} Use Recovery Charge</button>
      </div>
    </section>
    ${renderRouteProgress(district, available, cleared)}
    <section class="map-band">
      ${district.node_order.map((nodeId) => {
        const node = district.nodes[nodeId];
        const isAvailable = available.has(nodeId);
        const isCleared = cleared.has(nodeId);
        const className = isCleared ? "cleared" : isAvailable ? "available" : "locked";
        return `
          <button class="node-card ${className}" data-action="${isAvailable ? "enter-node" : "noop"}" data-id="${esc(nodeId)}">
            <span class="node-name">${iconSpan(node.kind === "boss" ? "boss" : node.kind === "battle" ? "battle" : "route")} ${esc(node.title)}<span class="pill">${esc(titleFromSlug(node.kind))}</span></span>
            <span class="meta">${esc(titleFromSlug(node.route_family || "shared"))} route, ${esc(titleFromSlug(node.risk_tier || "medium"))} risk</span>
            <span class="fine">${esc(node.preview_text || rewardPreview(node) || "Route node")}</span>
            ${isCleared ? `<span class="pill">${iconSpan("victory")} Cleared</span>` : isAvailable ? `<span class="pill">${iconSpan("playerTurn")} Available</span>` : `<span class="pill">${iconSpan("lock")} Locked</span>`}
          </button>
        `;
      }).join("")}
    </section>
    <section class="grid-2">
      <div class="panel">${renderCampaignParty()}</div>
      <div class="panel">${renderRecentReport()}</div>
    </section>
  `;
  return renderShell("District Map", "Select the next available node in the Rain Toll Corridor.", body);
}

function renderRouteProgress(district, available, cleared) {
  return `
    <section class="route-track" aria-label="Route progression">
      ${district.node_order.map((nodeId, index) => {
        const node = district.nodes[nodeId];
        const state = cleared.has(nodeId) ? "cleared" : available.has(nodeId) ? "available" : "locked";
        return `
          <div class="route-step ${state}">
            <span class="route-dot">${state === "cleared" ? UI_ICONS.victory : state === "available" ? UI_ICONS.playerTurn : index + 1}</span>
            <span class="route-label">${esc(node.title)}</span>
          </div>
        `;
      }).join("")}
    </section>
  `;
}

function rewardPreview(node) {
  const table = app.content.rewardTables[node.reward_table_id];
  if (!table) return "";
  if (table.identity_tags && table.identity_tags.length) return `Likely rewards: ${table.identity_tags.slice(0, 3).join(", ")}.`;
  return table.preview_text || "";
}

function renderBattleScreen() {
  const battle = app.battle;
  if (!battle) return renderMapScreen();
  const node = getNode(battle.nodeId);
  const active = getActiveActor();
  const skill = battle.selectedSkillId === "__potion" ? null : app.content.skills[battle.selectedSkillId];
  const body = `
    <section class="panel">
      <div class="panel-title"><h3>${iconSpan(node.kind === "boss" ? "boss" : "battle")} ${esc(node.title)}</h3><span class="meta">Round ${battle.round}</span></div>
      ${renderBattleMeters(battle)}
    </section>
    ${renderCombatLog(battle)}
    <section class="battle-grid">
      <div class="panel">
        <div class="panel-title"><h3>${iconSpan("party")} Party</h3></div>
        <div class="unit-list">${battle.players.map((unit) => renderUnitCard(unit, "player", false)).join("")}</div>
      </div>
      <div class="battle-center">
        <div class="turn-card">
          <h3>${active ? `${active.team === "player" ? iconSpan("playerTurn") : iconSpan("enemyTurn")} Active: ${esc(active.name)}` : "Resolving..."}</h3>
          <div class="meta">${active ? esc(active.team === "player" ? (isTurnAxisConfirmedForActor(active) ? "Turn input locked. Choose a skill and target." : "Tune this turn before actions unlock.") : "Enemy action resolving.") : ""}</div>
        </div>
        ${active && active.team === "player" ? renderTurnAxisInputPanel(active) : ""}
        <div class="panel action-panel">
          <div class="panel-title"><h3>${iconSpan("battle")} Actions</h3><span class="meta">${active && active.team === "player" ? renderPostureLabel(active.posture || "flow") : ""}</span></div>
          <div class="action-list">${active && active.team === "player" ? renderActionButtons(active) : ""}</div>
        </div>
        <div class="panel skill-detail">
          ${renderSkillDetail(skill)}
        </div>
      </div>
      <div class="panel">
        <div class="panel-title"><h3>${iconSpan("enemyTurn")} Enemies</h3><span class="meta">Click to target</span></div>
        <div class="unit-list">${battle.enemies.map((unit) => renderUnitCard(unit, "enemy", true)).join("")}</div>
      </div>
    </section>
  `;
  return renderShell("Battle", "Guard absorbs damage, Break creates stagger, Barrier absorbs first, and Spotlight powers finishers.", body);
}

function renderCombatLog(battle) {
  const entries = combatLogEntries(battle);
  return `
    <section class="log-panel battle-log-panel">
      <div class="panel-title"><h3>${iconSpan("battle")} Combat Log</h3></div>
      <div id="combat-log" class="combat-log" role="log" aria-label="Combat events" aria-live="polite" aria-relevant="additions text" aria-atomic="false">
        ${entries.length ? entries.map(renderCombatLogEntry).join("") : `<p class="meta">No combat events yet.</p>`}
      </div>
    </section>
  `;
}

function combatLogEntries(battle, limit = 80) {
  const entries = battle && Array.isArray(battle.log) ? battle.log : [];
  return entries.slice(-limit);
}

function renderCombatLogEntry(entry) {
  const round = Number(entry.round || 0);
  const label = round > 0 ? `R${String(round).padStart(2, "0")}` : "R--";
  return `
    <div class="log-entry ${esc(entry.kind || logKind(entry.text))}">
      <strong>${label}</strong> ${esc(entry.text)}
    </div>
  `;
}

function scrollCombatLogToBottom() {
  window.requestAnimationFrame(() => {
    const logEl = document.getElementById("combat-log");
    if (logEl) {
      logEl.scrollTop = logEl.scrollHeight;
    }
  });
}

function renderBattleMeters(battle) {
  const spotlightEffect = battle.effects && battle.effects.__spotlight ? battle.effects.__spotlight : "";
  const active = getActiveActor();
  const turnAxis = active && active.team === "player" ? getConfirmedTurnAxisForActor(active) : null;
  return `
    <div class="battle-meter-grid">
      ${meterCard("Player Spotlight", battle.spotlight, battle.spotlightMax, "spotlight", spotlightEffect)}
      ${meterCard("Enemy Spotlight", battle.enemySpotlight, battle.enemySpotlightMax, "threat", "")}
      ${meterCard("Potions", battle.healingPotions, potionCapacity(), "potion", "")}
      <div class="axis-card ${turnAxis ? "locked" : "pending"}">
        <span>${turnAxis ? `${iconSpan("lock")} Turn Input` : `${iconSpan("playerTurn")} Turn Input`}</span>
        <strong>${turnAxis ? axisTripletLabel(turnAxis.values) : "Awaiting confirm"}</strong>
        <span class="fine">${turnAxis ? `${renderPostureLabel(turnAxis.posture)}, ${turnAxis.ap} AP` : "Defaults come from the previous player turn."}</span>
      </div>
      <div class="axis-card">
        <span>${iconSpan("route")} Route Baseline</span>
        <strong>${axisTripletLabel(battle.nodeAxisScores)}</strong>
        <span class="fine">Route flavor and fallback for automation.</span>
      </div>
    </div>
  `;
}

function meterCard(label, value, max, className, effectClass) {
  const iconKey = className === "threat" ? "enemyTurn" : className;
  return `
    <div class="meter-card ${className} ${effectClass}">
      <span>${iconSpan(iconKey)} ${esc(label)}</span>
      <strong>${Math.max(0, value)}/${max}</strong>
      <span class="bar ${className}" role="progressbar" aria-label="${esc(label)}" aria-valuemin="0" aria-valuemax="${max}" aria-valuenow="${Math.max(0, value)}">
        <span style="--pct:${pct(value, max)}"></span>
      </span>
    </div>
  `;
}

function renderTurnAxisInputPanel(actor) {
  const locked = getConfirmedTurnAxisForActor(actor);
  if (locked) {
    return `
      <section class="panel turn-axis-panel locked" aria-label="Confirmed turn axis">
        <div class="panel-title"><h3>${iconSpan("lock")} Turn Axis Locked</h3><span class="meta">${esc(actor.name)}</span></div>
        <div class="axis-locked-grid">
          ${AXIS_KEYS.map((key) => axisSummaryCard(key, locked.values[key], locked.bands[key])).join("")}
        </div>
        <div class="turn-axis-result">
          <span class="pill">${renderPostureLabel(locked.posture)} posture</span>
          <span class="pill">${iconSpan("composure")} ${locked.ap} AP from Composure</span>
        </div>
      </section>
    `;
  }

  const defaults = getDefaultTurnAxis();
  return `
    <section class="panel turn-axis-panel pending" data-turn-axis-panel aria-label="Turn Axis Input">
      <div class="panel-title"><h3>${iconSpan("battle")} Tune This Turn</h3><span class="meta">${esc(actor.name)}</span></div>
      <p class="meta">Power drives damage and break pressure. Precision improves hit and crit pressure. Composure improves AP and defensive flow.</p>
      <div class="axis-input-grid">
        ${AXIS_KEYS.map((key) => {
          const meta = AXIS_META[key];
          return `
            <label class="axis-input-card">
              <span>${iconSpan(meta.icon)} ${esc(meta.label)}</span>
              <input data-axis-input="${esc(key)}" type="number" inputmode="numeric" min="0" max="100" value="${defaults[key]}" aria-label="${esc(meta.label)}">
              <small>${esc(meta.hint)}</small>
            </label>
          `;
        }).join("")}
      </div>
      <div id="turn-axis-preview" class="turn-axis-preview">
        ${renderTurnAxisPreview(defaults, actor)}
      </div>
      <button class="primary axis-confirm-button" data-action="confirm-turn-axis">${iconSpan("playerTurn")} Confirm Turn Axis</button>
    </section>
  `;
}

function renderTurnAxisPreview(values, actor) {
  const resolved = resolveTurnAxis(values, actor);
  return `
    <div class="axis-preview-grid">
      ${AXIS_KEYS.map((key) => axisSummaryCard(key, resolved.values[key], resolved.bands[key])).join("")}
    </div>
    <div class="turn-axis-result">
      <span class="pill">${renderPostureLabel(resolved.posture)} posture</span>
      <span class="pill">${iconSpan("composure")} ${resolved.ap} AP from Composure</span>
      <span class="pill">${esc(resolved.postureReason)}</span>
    </div>
  `;
}

function axisSummaryCard(key, value, band) {
  const meta = AXIS_META[key];
  return `
    <span class="axis-summary ${esc(key)}">
      <strong>${iconSpan(meta.icon)} ${esc(meta.label)} ${value}</strong>
      <small>${esc(titleFromSlug(band.name || "unknown"))} band</small>
    </span>
  `;
}

function renderActionButtons(active) {
  const locked = !isTurnAxisConfirmedForActor(active);
  const skills = active.skills.map((skillId) => app.content.skills[skillId] ? skillId : null).filter(Boolean);
  const potionButton = `
    <button class="action-button ${app.battle.selectedSkillId === "__potion" ? "selected" : ""}" data-action="select-skill" data-id="__potion" ${locked ? "disabled" : ""}>
      <span class="action-name">${iconSpan("potion")} Healing Potion<span class="cost">${app.battle.healingPotions} left</span></span>
      <span class="meta">Restore 35% max HP. Upgrades may add Guard or Spotlight.</span>
    </button>
  `;
  return `
    ${locked ? `<p class="notice">${iconSpan("lock")} Confirm Turn Axis to unlock battle actions.</p>` : ""}
    ${skills.map((skillId) => {
      const skill = app.content.skills[skillId];
      const selected = app.battle.selectedSkillId === skillId;
      const disabled = locked || app.battle.spotlight < Number(skill.spotlight_cost || 0);
      return `
        <button class="action-button ${selected ? "selected" : ""}" data-action="select-skill" data-id="${esc(skillId)}" ${disabled ? "disabled" : ""}>
          <span class="action-name">${iconSpan(skillIconKey(skill))} ${esc(skill.display_name)}<span class="cost">${iconSpan("spotlight")} SP ${Number(skill.spotlight_cost || 0)}</span></span>
          <span class="meta">${esc(titleFromSlug(skill.kind))} | ${esc(skill.affinity)} | ${esc(skill.target)}</span>
          <span class="fine">${esc(skill.effect)}</span>
        </button>
      `;
    }).join("")}
    ${potionButton}
  `;
}

function renderSkillDetail(skill) {
  const actor = getActiveActor();
  if (actor && actor.team === "player" && !isTurnAxisConfirmedForActor(actor)) {
    return `
      <h4>${iconSpan("lock")} Actions Locked</h4>
      <p class="meta">Confirm Power / Precision / Composure for ${esc(actor.name)} before resolving actions.</p>
      <p class="fine">The confirmed triplet applies to this actor's whole current turn.</p>
    `;
  }
  if (app.battle.selectedSkillId === "__potion") {
    return `
      <h4>${iconSpan("potion")} Healing Potion</h4>
      <p class="meta">Restores 35% max HP. Current route kit upgrades are applied.</p>
      <button class="primary" data-action="use-skill" ${app.battle.healingPotions > 0 ? "" : "disabled"}>${iconSpan("potion")} Use Potion</button>
    `;
  }
  if (!skill) return `<p class="meta">Select a skill.</p>`;
  const output = skill.output || {};
  const target = skill.target === "single_enemy"
    ? app.battle.enemies.find((unit) => unit.instanceId === app.battle.selectedTargetId)
    : null;
  const preview = actor && actor.team === "player" ? previewSkillImpact(actor, skill, target) : null;
  return `
    <h4>${iconSpan(skillIconKey(skill))} ${esc(skill.display_name)}</h4>
    <p class="meta">${esc(titleFromSlug(skill.kind))} | ${esc(skill.affinity)} | Target: ${esc(skill.target)}</p>
    <div class="pill-row">
      <span class="pill">${iconSpan("power")} Damage ${esc(output.damage || "none")}</span>
      <span class="pill">${iconSpan("break")} Break ${esc(output.break || "none")}</span>
      <span class="pill">${iconSpan("spotlight")} Spotlight ${Number(skill.spotlight_cost || 0)}</span>
      ${target ? `<span class="pill">${iconSpan("target")} Target ${esc(target.name)}</span>` : ""}
    </div>
    ${preview ? `
      <div class="preview-grid">
        <span><strong>${preview.damage}</strong> est. damage</span>
        <span><strong>${preview.breakDamage}</strong> est. break</span>
        <span><strong>${esc(preview.affinity)}</strong> affinity</span>
      </div>
    ` : ""}
    <p class="fine">${esc(skill.effect)}</p>
    <button class="primary" data-action="use-skill">${iconSpan("battle")} Use Selected Skill</button>
  `;
}

function previewSkillImpact(actor, skill, target) {
  const output = skill.output || {};
  const baseDamage = Number(app.content.rules.damage_tiers[output.damage || "none"] || 0);
  const baseBreak = Number(app.content.rules.break_tiers[output.break || "none"] || 0);
  const multiplier = computeScaleMultiplier(actor, skill);
  let damage = ceil(baseDamage * multiplier);
  let breakDamage = ceil(baseBreak * multiplier);
  if (actor.nextAttackPowerBonus && !["support", "defense", "utility", "stance", "self_buff"].includes(skill.kind)) {
    damage = ceil(damage * (1 + actor.nextAttackPowerBonus * 0.14));
    breakDamage = ceil(breakDamage * (1 + actor.nextAttackPowerBonus * 0.08));
  }
  let affinity = "neutral";
  if (target) {
    const mod = affinityModifier(skill.affinity, target.affinity);
    damage = ceil(damage * mod);
    breakDamage = ceil(breakDamage * (mod > 1 ? 1.1 : 1));
    affinity = mod > 1 ? "advantage" : mod < 1 ? "resisted" : "neutral";
    if (hasCondition(target, "staggered")) damage = ceil(damage * 1.3);
    if (hasCondition(target, "reveal")) damage = ceil(damage * 1.1);
    if (hasCondition(target, "hex")) damage = ceil(damage * 1.1);
  }
  return { damage, breakDamage, affinity };
}

function renderRewardScreen() {
  const pending = app.campaign.pendingReward;
  if (!pending) return renderMapScreen();
  const table = app.content.rewardTables[pending.tableId];
  const isShop = pending.tableType === "shop";
  const resolvedNode = app.campaign.pendingResolvedNodeId ? getNode(app.campaign.pendingResolvedNodeId) : null;
  const body = `
    <section class="panel reward-intro">
      <div class="panel-title"><h3>${esc(resolvedNode ? `${resolvedNode.title} Cleared` : "Route Reward")}</h3><span class="meta">${isShop ? "Shop" : "Reward choice"}</span></div>
      <p class="meta">${esc(table.display_name || pending.tableId)}: ${esc(table.preview_text || "Choose a route reward.")}</p>
      <div class="victory-ribbon">${iconSpan("victory")} Battle state resolved. Rewards are saved after selection.</div>
    </section>
    <section class="panel">
      <div class="panel-title"><h3>Available Rewards</h3><span class="meta">${isShop ? "Spend shards" : "Pick one"}</span></div>
      <p class="meta">${esc(table.preview_text || "Choose a route reward.")}</p>
      <div class="pill-row">
        <span class="pill">${iconSpan("shards")} Echo Shards ${app.campaign.runShards}</span>
        <span class="pill">${isShop ? `Purchases left ${pending.purchasesLeft}` : `Picks left ${pending.picksLeft}`}</span>
      </div>
    </section>
    <section class="reward-list">
      ${pending.remainingOptionIds.map((optionId) => renderRewardCard(optionId, isShop)).join("")}
    </section>
    ${isShop ? `<button class="secondary" data-action="skip-reward">${iconSpan("route")} Leave Shop</button>` : ""}
    <section class="grid-2">
      <div class="panel">${renderCampaignParty()}</div>
      <div class="panel">${renderRecentReport()}</div>
    </section>
  `;
  return renderShell("Rewards", "Route rewards mutate the campaign state and are saved to localStorage.", body);
}

function renderResultScreen() {
  const victory = app.campaign.lastOutcome === "victory";
  const defeat = app.campaign.lastOutcome === "defeat";
  const title = victory ? "District Cleared" : defeat ? "Expedition Lost" : "Run Result";
  const body = `
    <section class="result-screen ${victory ? "victory" : defeat ? "defeat" : "neutral"}">
      <div class="sigil" aria-hidden="true"></div>
      <p class="eyebrow">${victory ? `${iconSpan("victory")} Victory` : defeat ? `${iconSpan("defeat")} Defeat` : "Result"}</p>
      <h1>${esc(title)}</h1>
      <p>${esc(app.campaign.lastResult)}</p>
      <div class="hero-stat-grid compact">
        <span><strong>${iconSpan("shards")} ${app.campaign.runShards}</strong> Echo Shards</span>
        <span><strong>${iconSpan("route")} ${app.campaign.clearedNodeIds.length}</strong> Nodes Cleared</span>
        <span><strong>${iconSpan("battle")} ${app.campaign.bestNodesCleared}</strong> Best Route</span>
        <span><strong>${iconSpan("victory")} ${app.campaign.wins}/${app.campaign.losses}</strong> W/L</span>
      </div>
      <div class="button-row center">
        <button class="primary" data-action="go-party">${iconSpan("route")} Start New Expedition</button>
        <button class="secondary" data-action="go-menu">Return To Menu</button>
      </div>
    </section>
    <section class="grid-2">
      <div class="panel">${renderCampaignParty()}</div>
      <div class="panel">${renderRecentReport()}</div>
    </section>
  `;
  return renderShell(title, "Browser run result. Python CLI saves and logs are separate.", body);
}

function renderRewardCard(optionId, isShop) {
  const option = app.content.rewardOptions[optionId];
  const reason = isShop ? rewardUnavailable(optionId) : "";
  const relic = option.relic_id ? app.content.relics[option.relic_id] : null;
  return `
    <button class="reward-card" data-action="choose-reward" data-id="${esc(optionId)}" ${reason ? "disabled" : ""}>
      <span class="reward-name">${iconSpan(relic ? "relic" : "shards")} ${esc(option.display_name)}<span class="cost">${optionCost(option) ? `${iconSpan("shards")} ${optionCost(option)} shards` : "free"}</span></span>
      <span class="meta">${esc(option.description)}</span>
      ${relic ? `<span class="fine">${esc(relic.summary || relic.effect || "")}</span>` : ""}
      ${reason ? `<span class="pill">${esc(reason)}</span>` : ""}
    </button>
  `;
}

function renderCampaignParty() {
  return `
    <div class="panel-title"><h3>${iconSpan("party")} Party Status</h3><span class="meta">${esc(app.campaign.soloCharacterId)}</span></div>
    <div class="unit-list">${app.campaign.players.map((unit) => renderUnitCard(unit, "player", false)).join("")}</div>
    ${app.campaign.boons.length ? `
      <div class="pill-row" style="margin-top:12px">
        ${app.campaign.boons.slice(-12).map((id) => `<span class="pill">${esc((app.content.rewardOptions[id] || {}).display_name || id)}</span>`).join("")}
      </div>
    ` : `<p class="meta">${iconSpan("relic")} Run Boons: none</p>`}
  `;
}

function renderRecentReport() {
  const lines = app.campaign.reportLines.slice(-8).reverse();
  return `
    <div class="panel-title"><h3>${iconSpan("route")} Recent Events</h3></div>
    ${lines.length ? lines.map((line) => `<div class="log-entry">${esc(line)}</div>`).join("") : `<p class="meta">No route events yet.</p>`}
  `;
}

function renderUnitCard(unit, side, selectable) {
  const statuses = STATUS_DISPLAY_ORDER
    .filter((name) => Number(unit.conditions && unit.conditions[name] || 0) > 0)
    .map((name) => `${name}:${unit.conditions[name]}`);
  if (unit.barrier > 0) statuses.push(`barrier:${unit.barrier}`);
  const selected = app.battle && app.battle.selectedTargetId === unit.instanceId;
  const effect = app.battle && app.battle.effects ? app.battle.effects[unit.instanceId] || "" : "";
  const canSelect = selectable && alive(unit);
  const tag = canSelect ? "button" : "article";
  const action = canSelect ? `type="button" data-action="select-target" data-id="${esc(unit.instanceId)}" aria-pressed="${selected ? "true" : "false"}"` : "";
  const intent = side === "enemy" && alive(unit) ? renderEnemyIntent(unit) : "";
  return `
    <${tag} class="unit-card ${side} ${selected ? "selected" : ""} ${alive(unit) ? "" : "defeated"} ${effect}" ${action}>
      ${renderEntityArt(unit, "unit-art")}
      <div class="unit-name">
        <span>${iconSpan(unit.isBoss ? "boss" : side === "enemy" ? "enemyTurn" : "playerTurn")} ${esc(unit.name)}</span>
        <span class="pill">${esc(unit.affinity)}${unit.isBoss ? ` ${UI_ICONS.boss} boss` : ""}</span>
      </div>
      <div class="meta">${esc(unit.role || "")} | posture ${renderPostureLabel(unit.posture || "flow")} | speed ${unit.speed}</div>
      <div class="stat-bars">
        ${barRow("HP", "hp", unit.hp, unit.maxHp)}
        ${barRow("Guard", "guard", unit.guard, unit.maxGuard)}
        ${barRow("Break", "break", unit.breakMeter, unit.maxBreak)}
        ${unit.barrier > 0 ? barRow("Barrier", "barrier", unit.barrier, Math.max(unit.barrier, unit.maxGuard)) : ""}
      </div>
      <div class="status-line">${statuses.length ? esc(statuses.join(", ")) : "No status"}</div>
      ${intent}
      ${unit.metadata && unit.metadata.relicNames && unit.metadata.relicNames.length ? `
        <div class="fine">${esc(unit.metadata.relicNames.join(", "))}</div>
      ` : ""}
    </${tag}>
  `;
}

function barRow(label, className, value, max) {
  const iconKey = className === "hp" ? "hp" : className;
  return `
    <div class="bar-row">
      <span>${iconSpan(iconKey)} ${esc(label)}</span>
      <span class="bar ${className}" role="progressbar" aria-label="${esc(label)}" aria-valuemin="0" aria-valuemax="${max}" aria-valuenow="${Math.max(0, value)}"><span style="--pct:${pct(value, max)}"></span></span>
      <span>${Math.max(0, value)}/${max}</span>
    </div>
  `;
}

function renderEnemyIntent(unit) {
  const special = enemySpecial(unit);
  const pressure = partyBalanceProfile(app.battle.players.length);
  const blueprint = unit.isBoss ? app.content.bosses[unit.entityId] : app.content.enemies[unit.entityId];
  const tier = unit.isBoss ? "boss" : blueprint.tier;
  const damageTier = tier === "boss" ? "high" : tier === "elite" ? "medium" : "low";
  const breakTier = tier === "boss" ? "medium" : tier === "elite" ? "medium" : "low";
  const bossPressure = unit.isBoss ? pressure.bossPressureMult : 1;
  const damage = ceil(app.content.rules.damage_tiers[damageTier] * pressure.enemyDamageMult * bossPressure * special.damageMult);
  const breakDamage = ceil(app.content.rules.break_tiers[breakTier] * pressure.enemyDamageMult * bossPressure * special.breakMult);
  const rider = special.status ? ` + ${special.status}` : special.guardDrain ? ` + steals ${special.guardDrain} guard` : "";
  return `
    <div class="intent-card">
      <span>${iconSpan(unit.isBoss ? "boss" : "enemyTurn")} Threat</span>
      <strong>${esc(special.name)}</strong>
      <span>${iconSpan("power")} ${damage} damage / ${iconSpan("break")} ${breakDamage} break${esc(rider)}</span>
    </div>
  `;
}

function handleClick(event) {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  const action = target.dataset.action;
  const id = target.dataset.id;
  if (action === "noop") return;
  if (action === "next-event") {
    nextPresentationEvent();
    return;
  }
  if (action === "go-menu") {
    clearEventQueue(false);
    app.screen = "menu";
    render();
  }
  if (action === "go-party") {
    app.screen = "party";
    render();
  }
  if (action === "go-map" && app.campaign.expeditionActive) {
    app.screen = "map";
    render();
  }
  if (action === "select-character") {
    app.selectedCharacterId = id;
    render();
  }
  if (action === "start-expedition") startExpedition();
  if (action === "enter-node") enterNode(id);
  if (action === "select-target" && app.battle) {
    app.battle.selectedTargetId = id;
    render();
  }
  if (action === "select-skill" && app.battle) {
    const actor = getActiveActor();
    if (actor && actor.team === "player" && !isTurnAxisConfirmedForActor(actor)) {
      setStatus("Confirm Turn Axis to unlock actions.", "warning", true);
      return;
    }
    app.battle.selectedSkillId = id;
    render();
  }
  if (action === "confirm-turn-axis") confirmTurnAxisFromPanel();
  if (action === "use-skill") useSelectedSkill();
  if (action === "choose-reward") chooseReward(id);
  if (action === "skip-reward") skipReward();
  if (action === "save-local") {
    saveLocal();
    render();
  }
  if (action === "load-local") {
    loadLocal();
    render();
  }
  if (action === "save-game") saveGame();
  if (action === "load-game") loadGame();
  if (action === "refresh-saves") checkServerSaves(true);
  if (action === "load-server-save") loadGame(id);
  if (action === "reset-local") resetLocal();
  if (action === "use-recovery") useRecoveryCharge();
  if (action === "refresh-app") {
    if (waitingServiceWorker) {
      waitingServiceWorker.postMessage({ type: "SKIP_WAITING" });
    } else {
      window.location.reload();
    }
  }
}

function handleInput(event) {
  if (!event.target.closest("[data-axis-input]")) return;
  updateTurnAxisPreview();
}

function handleHover(event) {
  const target = event.target.closest('[data-action="select-skill"]');
  if (!target || !app.battle) return;
  const actor = getActiveActor();
  if (actor && actor.team === "player" && !isTurnAxisConfirmedForActor(actor)) return;
  app.battle.selectedSkillId = target.dataset.id;
  const detail = document.querySelector(".skill-detail");
  if (detail) {
    const skill = app.battle.selectedSkillId === "__potion" ? null : app.content.skills[app.battle.selectedSkillId];
    detail.innerHTML = renderSkillDetail(skill);
  }
}

function readTurnAxisPanelValues() {
  const panel = document.querySelector("[data-turn-axis-panel]");
  if (!panel) return getDefaultTurnAxis();
  return Object.fromEntries(AXIS_KEYS.map((key) => {
    const input = panel.querySelector(`[data-axis-input="${key}"]`);
    return [key, clampAxisValue(input ? input.value : DEFAULT_AXIS[key])];
  }));
}

function updateTurnAxisPreview() {
  const preview = document.getElementById("turn-axis-preview");
  if (!preview) return;
  const actor = getActiveActor();
  preview.innerHTML = renderTurnAxisPreview(readTurnAxisPanelValues(), actor);
}

function confirmTurnAxisFromPanel() {
  const actor = getActiveActor();
  if (!actor || actor.team !== "player") return;
  const values = readTurnAxisPanelValues();
  confirmTurnAxisInput(actor, values);
}

function enterNode(nodeId) {
  if (!app.campaign.availableNodeIds.includes(nodeId)) return;
  app.campaign.currentNodeId = nodeId;
  app.campaign.currentNodeAxisScores = { ...DEFAULT_AXIS };
  app.campaign.nodeAxisHistory[nodeId] = { ...DEFAULT_AXIS };
  const node = getNode(nodeId);
  const event = getEvent(node.event_id);
  record(`${node.title}: ${event.title}`);
  if (node.kind === "battle" || node.kind === "boss") {
    startBattle(nodeId);
    return;
  }
  if (node.kind === "event") {
    app.campaign.pendingResolvedNodeId = nodeId;
    app.campaign.pendingReward = buildPendingReward(node.reward_table_id);
    app.screen = app.campaign.pendingReward ? "reward" : "map";
    if (!app.campaign.pendingReward) completeResolvedNode();
    saveLocal("Autosaved route event.");
    render();
  }
}
