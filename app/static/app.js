const output = document.querySelector("#output");
const tasks = document.querySelector("#tasks");
const creditsValue = document.querySelector("#creditsValue");
const toast = document.querySelector("#toast");
const nextSteps = document.querySelector("#nextSteps");
const workflowModalContent = document.querySelector("#workflowModalContent");
const helpModalContent = document.querySelector("#helpModalContent");
const systemModalContent = document.querySelector("#systemModalContent");
const archiveList = document.querySelector("#archiveList");
const archiveDetail = document.querySelector("#archiveDetail");
const archiveSearch = document.querySelector("#archiveSearch");
const archiveType = document.querySelector("#archiveType");
const archiveStatus = document.querySelector("#archiveStatus");
const archiveSort = document.querySelector("#archiveSort");
const archiveBulkBar = document.querySelector("#archiveBulkBar");
const archiveSelectedCount = document.querySelector("#archiveSelectedCount");

let runtimeConfig = { models: {}, lyrics_prompt_max_length: 200, polling_interval_seconds: 10, notifications: { badge_auto_close_enabled: true, badge_auto_close_seconds: 8, badge_auto_close_ms: 8000, badge_auto_mark_done: false } };
let cachedTasks = [];
let cachedSongs = [];
let cachedAudioAssets = [];
let cachedPersonas = [];
let cachedPlaylists = [];
let cachedLyricDrafts = [];
let cachedMusicStyles = [];
let cachedVocalTags = [];
let cachedProjects = [];
let cachedProductionProfiles = [];
let cachedAiConfig = null;
let cachedAiSessions = [];
let currentAiSession = null;
let cachedAdminUsers = [];
let cachedAdminAiSettings = null;
let cachedAdminVocalTags = [];
let cachedAdminAiProfiles = [];
let cachedAdminInstructionFiles = [];
let authUser = null;
let cachedTrashItems = [];
let currentMiniPlayerAsset = null;
let currentMiniPlayerLoop = false;
let currentMiniPlayerScope = "project";
let currentArchiveProjectKey = null;
const persistedOpenProjects = new Set();
const persistedOpenTracks = new Set();
let selectedArchiveItems = new Set();
let lastVisibleArchiveRefs = [];
let autoRefreshTimer = null;
let knownTaskStatusMap = new Map();
let cachedNotifications = [];
let selectedNotifications = new Set();
let seenNotificationIds = new Set(JSON.parse(localStorage.getItem("seenStatusNotificationIds") || "[]"));
let isAutoRefreshing = false;


const AUTH_TOKEN_KEY = "sunoAccessToken";

function getAuthToken() {
  return localStorage.getItem(AUTH_TOKEN_KEY) || "";
}

function setAuthToken(token) {
  if (token) localStorage.setItem(AUTH_TOKEN_KEY, token);
  else localStorage.removeItem(AUTH_TOKEN_KEY);
}

function ensureAuthOverlay() {
  if (document.querySelector("#authOverlay")) return;
  const overlay = document.createElement("div");
  overlay.id = "authOverlay";
  overlay.className = "auth-overlay hidden";
  overlay.innerHTML = `
    <div class="auth-card">
      <div class="auth-card-header">
        <div>
          <p class="eyebrow">Geschützter Zugriff</p>
          <h2>Anmelden</h2>
          <p class="muted">Bitte melde dich an, um die Suno FastAPI App zu verwenden.</p>
        </div>
      </div>
      <form id="authLoginForm" class="auth-form">
        <label>E-Mail / Benutzername
          <input name="email" type="email" autocomplete="username" required placeholder="name@example.com">
        </label>
        <label>Passwort
          <input name="password" type="password" autocomplete="current-password" required placeholder="Passwort">
        </label>
        <p id="authMessage" class="auth-message"></p>
        <button type="submit" class="primary-button">Einloggen</button>
      </form>
    </div>
  `;
  document.body.appendChild(overlay);
  const form = overlay.querySelector("#authLoginForm");
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const message = overlay.querySelector("#authMessage");
    message.textContent = "Anmeldung läuft...";
    const payload = formToObject(form);
    try {
      const response = await fetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(payload)
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(formatApiErrorPayload(data) || "Login fehlgeschlagen.");
      setAuthToken(data.access_token);
      message.textContent = "Login erfolgreich.";
      hideAuthOverlay();
      window.location.reload();
    } catch (error) {
      message.textContent = error.message || "Login fehlgeschlagen.";
    }
  });
}

function showAuthOverlay(message = "Bitte anmelden.") {
  ensureAuthOverlay();
  const overlay = document.querySelector("#authOverlay");
  const messageElement = document.querySelector("#authMessage");
  if (messageElement) messageElement.textContent = message;
  overlay.classList.remove("hidden");
}

function hideAuthOverlay() {
  const overlay = document.querySelector("#authOverlay");
  if (overlay) overlay.classList.add("hidden");
}

async function logoutUser() {
  try {
    await fetch("/auth/logout", { method: "POST", credentials: "same-origin", headers: getAuthToken() ? { Authorization: `Bearer ${getAuthToken()}` } : {} });
  } catch (error) {
    console.warn("Logout konnte serverseitig nicht bestätigt werden", error);
  }
  setAuthToken("");
  window.location.reload();
}

function userDisplayName(user = authUser) {
  if (!user) return "Benutzer";
  return (user.nickname || user.email || "Benutzer").trim();
}

function injectUserMenu() {
  document.querySelector("#logoutButton")?.remove();

  const existing = document.querySelector("#userMenuWrapper");
  if (existing) existing.remove();

  if (!authUser) return;

  const headerActions = document.querySelector(".header-actions") || document.querySelector("header") || document.body;
  const wrapper = document.createElement("div");
  wrapper.id = "userMenuWrapper";
  wrapper.className = "user-menu-wrapper";
  wrapper.innerHTML = `
    <button id="userMenuButton" class="user-menu-button" type="button" aria-haspopup="true" aria-expanded="false">
      <span class="user-avatar">${escapeHtml(userDisplayName().slice(0, 1).toUpperCase())}</span>
      <span class="user-name">${escapeHtml(userDisplayName())}</span>
      <span class="user-chevron">▾</span>
    </button>
    <div id="userMenuDropdown" class="user-menu-dropdown hidden" role="menu">
      <div class="user-menu-head">
        <strong>${escapeHtml(userDisplayName())}</strong>
        <span>${escapeHtml(authUser.email || "")}</span>
      </div>
      <button type="button" data-open-profile-modal="profile">Profil bearbeiten</button>
      <button type="button" data-open-profile-modal="password">Passwort ändern</button>
      <button type="button" data-user-logout>Logout</button>
    </div>
  `;
  headerActions.appendChild(wrapper);
}

function toggleUserMenu(forceState = null) {
  const dropdown = document.querySelector("#userMenuDropdown");
  const button = document.querySelector("#userMenuButton");
  if (!dropdown || !button) return;
  const shouldOpen = forceState === null ? dropdown.classList.contains("hidden") : Boolean(forceState);
  dropdown.classList.toggle("hidden", !shouldOpen);
  button.setAttribute("aria-expanded", String(shouldOpen));
}

function ensureProfileModal() {
  if (document.querySelector("#profileModal")) return;
  const modal = document.createElement("div");
  modal.id = "profileModal";
  modal.className = "app-modal profile-modal";
  modal.innerHTML = `
    <div class="modal-backdrop" data-close-modal="profileModal"></div>
    <div class="modal-panel profile-modal-panel">
      <div class="modal-head">
        <div>
          <p class="eyebrow">Benutzerprofil</p>
          <h2>Profil & Passwort</h2>
          <p class="muted">Spitzname für die Anzeige im Header ändern oder Passwort aktualisieren.</p>
        </div>
        <button class="icon-btn" type="button" data-close-modal="profileModal">✕</button>
      </div>
      <div class="profile-modal-grid">
        <form id="vanillaProfileForm" class="profile-form-card">
          <h3>Profil</h3>
          <label>E-Mail
            <input name="email" type="email" disabled>
          </label>
          <label>Spitzname
            <input name="nickname" maxlength="120" autocomplete="nickname" placeholder="z. B. Andy">
          </label>
          <p class="form-note">Der Spitzname wird oben im Header angezeigt.</p>
          <button class="primary-button" type="submit">Profil speichern</button>
          <p id="profileMessage" class="form-message"></p>
        </form>
        <form id="vanillaPasswordForm" class="profile-form-card">
          <h3>Passwort ändern</h3>
          <label>Aktuelles Passwort
            <input name="current_password" type="password" autocomplete="current-password" required>
          </label>
          <label>Neues Passwort
            <input name="new_password" type="password" autocomplete="new-password" minlength="12" required>
          </label>
          <p class="form-note">Mindestens 12 Zeichen. Das Passwort wird niemals im Klartext gespeichert.</p>
          <button class="primary-button" type="submit">Passwort ändern</button>
          <p id="passwordMessage" class="form-message"></p>
        </form>
      </div>
    </div>
  `;
  document.body.appendChild(modal);

  modal.querySelector("#vanillaProfileForm")?.addEventListener("submit", saveOwnProfile);
  modal.querySelector("#vanillaPasswordForm")?.addEventListener("submit", changeOwnPassword);
}

function openProfileModal(section = "profile") {
  ensureProfileModal();
  const modal = document.querySelector("#profileModal");
  const profileForm = document.querySelector("#vanillaProfileForm");
  if (profileForm && authUser) {
    setFormField(profileForm, "email", authUser.email || "");
    setFormField(profileForm, "nickname", authUser.nickname || "");
  }
  document.querySelector("#profileMessage").textContent = "";
  document.querySelector("#passwordMessage").textContent = "";
  modal.classList.add("visible");
  setTimeout(() => {
    const selector = section === "password" ? "#vanillaPasswordForm input[name='current_password']" : "#vanillaProfileForm input[name='nickname']";
    document.querySelector(selector)?.focus();
  }, 50);
}

async function saveOwnProfile(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const message = document.querySelector("#profileMessage");
  if (message) message.textContent = "Speichere Profil...";
  try {
    const payload = { nickname: (new FormData(form).get("nickname") || "").toString().trim() };
    authUser = await api("/auth/profile", { method: "PUT", body: JSON.stringify(payload) });
    injectUserMenu();
    if (message) {
      message.textContent = "Profil gespeichert.";
      message.className = "form-message success";
    }
    notify("Profil aktualisiert");
  } catch (error) {
    if (message) {
      message.textContent = error.message || "Profil konnte nicht gespeichert werden.";
      message.className = "form-message error";
    }
  }
}

async function changeOwnPassword(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const message = document.querySelector("#passwordMessage");
  if (message) message.textContent = "Ändere Passwort...";
  try {
    const payload = formToObject(form);
    await api("/auth/change-password", { method: "POST", body: JSON.stringify(payload) });
    form.reset();
    if (message) {
      message.textContent = "Passwort geändert.";
      message.className = "form-message success";
    }
    notify("Passwort geändert");
  } catch (error) {
    if (message) {
      message.textContent = error.message || "Passwort konnte nicht geändert werden.";
      message.className = "form-message error";
    }
  }
}

const STEP_CONTENT = {
  "tab-home": [
    ["Workflow wählen", "Starte mit Song, Songtext, Library oder Status."],
    ["Geführt arbeiten", "Nutze die großen Karten statt technische Tabs zu suchen."],
    ["Ergebnis öffnen", "Fertige Tasks landen über Benachrichtigung direkt im Archiv."]
  ],
  "tab-music": [
    ["Eingaben setzen", "Modell, Modus, Style und Prompt eintragen."],
    ["Generierung starten", "Der Job erscheint anschließend im Statusbereich."],
    ["Archiv prüfen", "Fertige Inhalte werden im Archiv geöffnet und kopiert."]
  ],
  "tab-lyrics": [
    ["Kurzen Prompt schreiben", "Das Limit wird automatisch aus der .env geladen."],
    ["Task starten", "Nach dem Start zum Status oder Archiv wechseln."],
    ["Weiterverwenden", "Lyrics aus dem Archiv kopieren und in Musik Custom einfügen."]
  ],
  "tab-extend": [
    ["Audio-ID wählen", "Audio-ID aus einem fertigen Track im Archiv kopieren."],
    ["Standard oder Custom", "Standard übernimmt die Quellparameter, Custom erlaubt Prompt, Style, Titel und Persona."],
    ["Status prüfen", "Nach Abschluss landet die Extension im Archiv." ]
  ],
  "tab-personas": [
    ["Fertigen Track wählen", "Task-ID und Audio-ID aus dem Archiv übernehmen."],
    ["Persona beschreiben", "Name, Stil und Charakter möglichst eindeutig formulieren."],
    ["Wiederverwenden", "Gespeicherte Persona in Musik oder Extend auswählen." ]
  ],
  "tab-playlists": [
    ["Playlist anlegen", "Projektbezogene Sammlungen für Varianten und finale Songs erstellen."],
    ["Audio aus Archiv hinzufügen", "Bei Audio-Dateien über Playlist-Auswahl direkt zuordnen."],
    ["Weiterverarbeiten", "Aus Playlist heraus Tracks erneut öffnen oder im Archiv nutzen."]
  ],
  "tab-lyric-editor": [
    ["Text schreiben", "Vocal-Tags und Strukturbausteine direkt in den Editor einfügen."],
    ["Entwurf speichern", "Songtexte bleiben getrennt vom API-Verlauf erhalten."],
    ["In Musik übernehmen", "Fertigen Text in Musik → Custom einfügen und Style wählen."]
  ],
  "tab-styles": [
    ["Style speichern", "Genre, BPM, Tags und vollständigen Suno-Style ablegen."],
    ["Style verwenden", "Per Klick in Musik, Extend, Cover oder Vocals übernehmen."],
    ["Bibliothek pflegen", "Favoriten und wiederverwendbare Soundprofile standardisieren."]
  ],
  "tab-vocals-style": [
    ["Audio-URL eintragen", "Für Vocals ein Instrumental, für Instrumental eine Vocal-/Melodie-Spur verwenden."],
    ["Pflichtfelder setzen", "Titel, Style/Tags und Negative Tags sind laut Doku erforderlich."],
    ["Style optimieren", "Boost Music Style kann Style-Beschreibungen vorbereiten." ]
  ],
  "tab-audio": [
    ["Audio-URL eintragen", "Upload-URL oder externe Datei verwenden."],
    ["Verarbeitung wählen", "Stem-Trennung, MIDI oder WAV starten."],
    ["Ergebnis archivieren", "Links und Details erscheinen nach Statusprüfung im Archiv."]
  ],
  "tab-files": [
    ["Upload wählen", "URL-Upload oder lokalen Stream-Upload nutzen."],
    ["URL kopieren", "Upload-Ergebnis kopieren."],
    ["Audio verarbeiten", "Upload-URL im Audio-Tab weiterverwenden."]
  ],
  "tab-status": [
    ["Jobs prüfen", "Laufende Tasks aktualisieren."],
    ["Nur Überblick", "Lange Inhalte werden hier nicht vollständig angezeigt."],
    ["Archiv öffnen", "Generierte Inhalte dort sauber auswählen."]
  ],
  "tab-archive": [
    ["Eintrag wählen", "Links steht die kompakte Liste aller Tasks und Songs."],
    ["Inhalt prüfen", "Rechts werden Lyrics, Links und Details angezeigt."],
    ["Kopieren", "Jeder relevante Inhalt hat einen eigenen Kopieren-Button."]
  ]
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function getToastAutoCloseMs(options = {}) {
  if (options.durationMs !== undefined && options.durationMs !== null) {
    return Math.max(0, Number(options.durationMs) || 0);
  }

  const config = runtimeConfig?.notifications || {};
  const enabled = options.autoClose !== false && config.badge_auto_close_enabled !== false;
  if (!enabled) return 0;

  const configuredMs = Number(config.badge_auto_close_ms || 0);
  if (Number.isFinite(configuredMs) && configuredMs > 0) return configuredMs;

  const configuredSeconds = Number(config.badge_auto_close_seconds || 0);
  if (Number.isFinite(configuredSeconds) && configuredSeconds > 0) return configuredSeconds * 1000;

  return 8000;
}

function notify(message, typeOrSuccess = "info", options = {}) {
  const type = typeof typeOrSuccess === "boolean" ? (typeOrSuccess ? "success" : "error") : String(typeOrSuccess || "info");
  if (!toast) return;
  clearTimeout(notify.timeoutId);
  toast.className = `toast visible toast-${type}`;
  toast.innerHTML = `
    <button class="toast-main" type="button" ${options.notificationId ? `data-open-notification="${escapeHtml(options.notificationId)}"` : ""}>${escapeHtml(message)}</button>
    <button class="toast-close" type="button" ${options.notificationId ? `data-notification-done="${escapeHtml(options.notificationId)}"` : ""} title="Erledigt">×</button>`;

  const autoCloseMs = getToastAutoCloseMs(options);
  if (autoCloseMs > 0) {
    notify.timeoutId = setTimeout(() => {
      toast.classList.remove("visible");
      if (options.notificationId && runtimeConfig?.notifications?.badge_auto_mark_done === true) {
        markNotificationDone(options.notificationId).catch(() => null);
      }
    }, autoCloseMs);
  }
}

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("de-DE");
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = bytes;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatApiErrorPayload(data) {
  if (typeof data?.detail === "string") return data.detail;
  if (Array.isArray(data?.detail)) {
    return data.detail.map(item => {
      const loc = Array.isArray(item.loc) ? item.loc.join(".") : "Feld";
      return `${loc}: ${item.msg}`;
    }).join("\n");
  }
  return data?.error || data?.message || JSON.stringify(data, null, 2);
}

async function api(path, options = {}) {
  const token = getAuthToken();
  const baseHeaders = options.body instanceof FormData
    ? { ...(options.headers || {}) }
    : { "Content-Type": "application/json", ...(options.headers || {}) };
  const headers = token ? { ...baseHeaders, Authorization: `Bearer ${token}` } : baseHeaders;
  const response = await fetch(path, { credentials: "same-origin", ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) {
    setAuthToken("");
    showAuthOverlay("Sitzung abgelaufen oder Anmeldung erforderlich.");
    throw new Error("Anmeldung erforderlich.");
  }
  if (!response.ok) throw new Error(formatApiErrorPayload(data));
  return data;
}

function formToObject(form) {
  const data = new FormData(form);
  const obj = {};
  for (const [key, value] of data.entries()) {
    if (value === "") continue;
    if (value === "true") obj[key] = true;
    else if (value === "false") obj[key] = false;
    else obj[key] = value;
  }
  return obj;
}

function renderSteps(tabId) {
  if (!nextSteps) return;
  const steps = STEP_CONTENT[tabId] || STEP_CONTENT["tab-music"];
  nextSteps.innerHTML = steps.map((step, index) => `
    <div class="step-item"><span class="step-number">${index + 1}</span><span><strong>${escapeHtml(step[0])}</strong>${escapeHtml(step[1])}</span></div>
  `).join("");
}

function renderHelpModal(tabId = localStorage.getItem("activeSunoTab") || "tab-home") {
  if (!helpModalContent) return;
  const steps = STEP_CONTENT[tabId] || STEP_CONTENT["tab-music"];
  helpModalContent.innerHTML = steps.map((step, index) => `
    <div class="step-item"><span class="step-number">${index + 1}</span><span><strong>${escapeHtml(step[0])}</strong>${escapeHtml(step[1])}</span></div>
  `).join("");
}

function renderWorkflowModal() {
  if (!workflowModalContent) return;
  const workflows = [
    ["Song bauen", "Songtext Studio → Style wählen → Musik Custom → Status → Archiv" , "tab-lyric-editor"],
    ["Varianten prüfen", "Archiv → Audio abspielen → Playlist hinzufügen → beste Version markieren", "tab-archive"],
    ["Track erweitern", "Archiv-Audio → Extend oder Upload & Extend → Status → Archiv", "tab-extend"],
    ["Cover/Remix", "Archiv-Audio → Cover Song → Style übernehmen → neue Version archivieren", "tab-extend"],
    ["Persona bauen", "Fertiger Track → Persona erstellen → in neuer Generierung verwenden", "tab-personas"],
    ["Postproduktion", "Stem-Trennung → MIDI/WAV/Video → lokale Assets sichern", "tab-audio"],
    ["Styles pflegen", "Styles speichern → Boost Music Style → in Formulare übernehmen", "tab-styles"],
    ["Playlists", "Projekt-Playlist anlegen → Audio-Assets aus Archiv zuordnen", "tab-playlists"]
  ];
  workflowModalContent.innerHTML = workflows.map((item, index) => `
    <button class="workflow-tile" type="button" data-switch-tab="${escapeHtml(item[2])}" data-close-modal="workflowModal">
      <span>${index + 1}</span><strong>${escapeHtml(item[0])}</strong><small>${escapeHtml(item[1])}</small>
    </button>
  `).join("");
}

function openModal(id) {
  const modal = document.getElementById(id);
  if (!modal) return;
  if (id === "workflowModal") renderWorkflowModal();
  if (id === "helpModal") renderHelpModal();
  if (id === "systemModal") renderSystemModal().catch(error => { if (systemModalContent) systemModalContent.innerHTML = `<div class="notice-box error">${escapeHtml(error.message)}</div>`; });
  modal.classList.add("visible");
  modal.setAttribute("aria-hidden", "false");
}


async function renderSystemModal() {
  if (!systemModalContent) return;
  systemModalContent.innerHTML = `<div class="empty-state">Systemdiagnose wird geladen...</div>`;
  const [data, readiness, activity] = await Promise.all([
    api("/api/system/diagnostics"),
    api("/api/system/enterprise-readiness").catch(() => null),
    api("/api/system/activity?limit=10").catch(() => [])
  ]);
  const counts = data.counts || {};
  const audio = data.config?.audio_cache || {};
  const warnings = data.warnings || [];
  const readinessChecks = readiness?.checks || [];
  systemModalContent.innerHTML = `
    <div class="system-summary-grid">
      <div class="system-box"><span>Readiness</span><strong>${readiness?.readiness_score ?? "-"}%</strong></div>
      <div class="system-box"><span>Tasks</span><strong>${counts.tasks ?? 0}</strong></div>
      <div class="system-box"><span>Songs</span><strong>${counts.songs ?? 0}</strong></div>
      <div class="system-box"><span>Audio</span><strong>${counts.audio_assets ?? 0}</strong></div>
      <div class="system-box"><span>Projekte</span><strong>${counts.projects ?? 0}</strong></div>
      <div class="system-box"><span>Styles</span><strong>${counts.music_styles ?? 0}</strong></div>
      <div class="system-box"><span>Profile</span><strong>${counts.production_profiles ?? 0}</strong></div>
      <div class="system-box"><span>Storage</span><strong>${formatBytes(counts.storage_bytes || 0)}</strong></div>
    </div>
    ${warnings.length ? `<div class="notice-box error"><strong>Hinweise</strong><ul>${warnings.map(w => `<li>${escapeHtml(w)}</li>`).join("")}</ul></div>` : `<div class="notice-box success">Keine kritischen Konfigurationshinweise gefunden.</div>`}
    <div class="system-detail-grid">
      <div class="system-detail-card"><strong>API</strong><span>Base URL</span><code>${escapeHtml(data.config?.suno_base_url || "-")}</code><span>API-Key</span><code>${data.config?.suno_api_key_configured ? "konfiguriert" : "fehlt"}</code><span>Callback</span><code>${escapeHtml(data.config?.callback_url || "-")}</code></div>
      <div class="system-detail-card"><strong>Audio-Cache</strong><span>Modus</span><code>${escapeHtml(audio.mode || "off")}</code><span>Speicherpfad</span><code>${escapeHtml(audio.storage_path || "-")}</code><span>Webpfad</span><code>${escapeHtml(audio.public_route || "-")}</code></div>
      <div class="system-detail-card"><strong>Limits</strong><span>Lyrics Prompt</span><code>${escapeHtml(data.config?.lyrics_prompt_max_length ?? "-")} Zeichen</code><span>Polling</span><code>${escapeHtml(data.config?.polling_interval_seconds ?? "-")} s</code><span>Audio Max</span><code>${escapeHtml(audio.max_download_mb ?? "-")} MB</code></div>
    </div>
    <div class="system-detail-grid">
      <div class="system-detail-card system-detail-card-wide"><strong>Enterprise-Checks</strong>${readinessChecks.length ? readinessChecks.map(check => `<span>${check.ok ? "✅" : "⚠️"} ${escapeHtml(check.name)}</span><code>${escapeHtml(check.message)}</code>`).join("") : `<span>Keine Readiness-Daten verfügbar.</span>`}</div>
      <div class="system-detail-card system-detail-card-wide"><strong>Letzte Änderungen</strong>${Array.isArray(activity) && activity.length ? activity.map(row => `<span>${escapeHtml(formatDate(row.created_at))} · ${escapeHtml(row.action)} · ${escapeHtml(row.content_type)} #${escapeHtml(row.content_id ?? "-")}</span>`).join("") : `<span>Keine Audit-Einträge vorhanden.</span>`}</div>
    </div>
    <div class="notice-box">
      <strong>Empfohlene Wartungsreihenfolge</strong><br>
      1. Backup-ZIP erstellen → 2. Library reparieren → 3. Duplikate entfernen → 4. Verwaiste Dateien löschen → 5. Audit-Log bereinigen.
    </div>
    <details class="technical-details"><summary>Rohdaten anzeigen</summary><pre>${escapeHtml(JSON.stringify({ diagnostics: data, readiness, activity }, null, 2))}</pre></details>
  `;
}

function closeModal(id) {
  const modal = document.getElementById(id);
  if (!modal) return;
  modal.classList.remove("visible");
  modal.setAttribute("aria-hidden", "true");
}

function switchTab(tabId) {
  document.querySelectorAll(".tab-button").forEach(button => button.classList.toggle("active", button.dataset.tab === tabId));
  document.querySelectorAll(".tab-panel").forEach(panel => panel.classList.toggle("active", panel.id === tabId));
  const mobileMenuButton = document.getElementById("btnMobileTabMenu");
  const tabNav = document.getElementById("mainTabNav");
  if (mobileMenuButton && tabNav) {
    mobileMenuButton.setAttribute("aria-expanded", "false");
    mobileMenuButton.textContent = "☰ Menü öffnen";
    tabNav.classList.remove("is-open");
  }
  document.querySelectorAll(".tab-group").forEach(group => {
    const hasActive = Boolean(group.querySelector(`.tab-button[data-tab="${tabId}"]`));
    group.classList.toggle("is-open", hasActive);
    const trigger = group.querySelector(".tab-group-trigger");
    if (trigger) trigger.setAttribute("aria-expanded", String(hasActive));
  });
  renderSteps(tabId);
  localStorage.setItem("activeSunoTab", tabId);
  if (tabId === "tab-archive") renderArchive();
  if (tabId === "tab-admin") refreshAdminPanel().catch(error => showCompact({ error: error.message }, true, "Admin"));
}

function taskIdFromPayload(data) {
  const queue = [data];
  const keys = ["task_id", "taskId", "taskID", "id"];
  const seen = new Set();
  while (queue.length) {
    const current = queue.shift();
    if (!current || typeof current !== "object" || seen.has(current)) continue;
    seen.add(current);
    for (const key of keys) {
      if (current[key]) return String(current[key]);
    }
    Object.values(current).forEach(value => {
      if (value && typeof value === "object") queue.push(value);
    });
  }
  return null;
}

function collectUrls(source) {
  const urls = [];
  const seen = new Set();
  const queue = [source];
  const visited = new Set();
  while (queue.length) {
    const current = queue.shift();
    if (!current || visited.has(current)) continue;
    if (typeof current === "string") {
      const matches = current.match(/https?:\/\/[^\s"'<>]+/g) || [];
      for (const url of matches) {
        if (!seen.has(url)) {
          seen.add(url);
          urls.push(url);
        }
      }
      continue;
    }
    if (typeof current !== "object") continue;
    visited.add(current);
    Object.values(current).forEach(value => queue.push(value));
  }
  return urls;
}

function looksLikeJson(value) {
  const trimmed = String(value || "").trim();
  return (trimmed.startsWith("{") && trimmed.endsWith("}")) || (trimmed.startsWith("[") && trimmed.endsWith("]"));
}

function collectGeneratedTexts(source) {
  const allowedKeys = new Set(["lyrics", "lyric", "songtext", "text", "content", "response", "result", "output"]);
  const ignoredKeys = new Set(["prompt", "request_payload", "callback_url", "callBackUrl", "url", "audio_url", "audioUrl", "task_id", "taskId", "id", "status", "msg", "code", "error", "error_message"]);
  const texts = [];
  const seen = new Set();

  function pushText(key, value) {
    const text = String(value || "").trim();
    if (!text || text.length < 20 || looksLikeJson(text)) return;
    const normalized = text.replace(/\s+/g, " ").slice(0, 500);
    if (seen.has(normalized)) return;
    seen.add(normalized);
    texts.push({ label: ["lyrics", "lyric", "songtext"].includes(key) ? "Lyrics" : "Text", value: text });
  }

  function walk(value, key = "") {
    if (value === null || value === undefined || ignoredKeys.has(key)) return;
    if (typeof value === "string") {
      const trimmed = value.trim();
      if (looksLikeJson(trimmed)) {
        try { walk(JSON.parse(trimmed), key); } catch { return; }
        return;
      }
      if (allowedKeys.has(key)) pushText(key, trimmed);
      return;
    }
    if (Array.isArray(value)) {
      value.forEach(item => walk(item, key));
      return;
    }
    if (typeof value === "object") {
      Object.entries(value).forEach(([childKey, childValue]) => walk(childValue, childKey));
    }
  }

  walk(source);
  return texts;
}

function statusClass(status) {
  const normalized = String(status || "").toLowerCase();
  if (["success", "completed", "complete", "finished", "done"].includes(normalized)) return "success";
  if (["submitted", "processing", "pending", "running", "created", "queued"].includes(normalized)) return "warning";
  if (["failed", "error"].includes(normalized)) return "error";
  return "";
}

function isRunningStatus(status) {
  return ["submitted", "processing", "pending", "running", "queued", "created"].includes(String(status || "").toLowerCase());
}

function renderPersonaOptions() {
  const selects = [document.querySelector("#musicPersonaSelect"), document.querySelector("#extendPersonaSelect"), document.querySelector("#coverPersonaSelect")];
  for (const select of selects) {
    if (!select) continue;
    const previous = select.value;
    select.innerHTML = `<option value="">Keine Persona verwenden</option>` + cachedPersonas.map(persona => `<option value="${escapeHtml(persona.persona_id)}">${escapeHtml(persona.name)}${persona.style ? ` · ${escapeHtml(persona.style)}` : ""}</option>`).join("");
    if (previous) select.value = previous;
  }
}

function renderPersonaList() {
  const container = document.querySelector("#personaList");
  if (!container) return;
  container.innerHTML = cachedPersonas.length ? cachedPersonas.map(persona => `
    <article class="result-card compact-result success">
      <div class="result-header">
        <div class="result-title"><strong>${escapeHtml(persona.name)}</strong><div class="result-meta"><span class="badge">${escapeHtml(persona.style || "Persona")}</span><span class="badge">${escapeHtml(persona.persona_id)}</span></div></div>
        <div class="result-actions"><button class="copy-btn" type="button" data-copy="${escapeHtml(persona.persona_id)}">ID kopieren</button><button class="small-btn" type="button" data-open-archive="persona:${escapeHtml(persona.id)}" data-switch-tab="tab-archive">Archiv</button></div>
      </div>
      ${persona.description ? `<div class="result-body compact-body"><div class="summary-line">${escapeHtml(persona.description.slice(0, 180))}${persona.description.length > 180 ? "…" : ""}</div></div>` : ""}
    </article>`).join("") : `<div class="empty-state">Noch keine Personas gespeichert.</div>`;
}

function showCompact(data, isError = false, title = "Antwort") {
  const taskId = data?.task_id || taskIdFromPayload(data);
  const status = data?.status || data?.msg || (isError ? "Fehler" : "OK");
  output.innerHTML = `
    <article class="result-card ${isError ? "error" : statusClass(status)}">
      <div class="result-header">
        <div class="result-title"><strong>${escapeHtml(title)}</strong><div class="result-meta"><span class="badge ${statusClass(status)}">${escapeHtml(status)}</span>${taskId ? `<span class="badge">Task ${escapeHtml(taskId)}</span>` : ""}</div></div>
        <div class="result-actions">${taskId ? `<button class="copy-btn" type="button" data-copy="${escapeHtml(taskId)}">Task-ID kopieren</button>` : ""}<button class="copy-btn" type="button" data-copy="${escapeHtml(JSON.stringify(data, null, 2))}">Details kopieren</button></div>
      </div>
      <div class="result-body">
        <p>${isError ? "Die Anfrage konnte nicht verarbeitet werden." : "Die Anfrage wurde angenommen. Vollständige Inhalte findest du im Archiv."}</p>
        <div class="next-actions"><button class="secondary small-btn" type="button" data-switch-tab="tab-status">Status prüfen</button><button class="secondary small-btn" type="button" data-switch-tab="tab-archive">Archiv öffnen</button></div>
        <details class="details"><summary>Technische Details anzeigen</summary><pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre></details>
      </div>
    </article>`;
}

function renderTaskCompact(task) {
  const responseTaskId = task.task_id || taskIdFromPayload(task.response_payload) || taskIdFromPayload(task.result_payload);
  const prompt = task.request_payload?.prompt || "";
  return `
    <article class="result-card compact-result ${statusClass(task.status)}">
      <div class="result-header">
        <div class="result-title">
          <strong>${escapeHtml(task.task_type || "Task")}</strong>
          <div class="result-meta"><span class="badge">#${escapeHtml(task.id)}</span><span class="badge ${statusClass(task.status)}">${escapeHtml(task.status)}</span>${responseTaskId ? `<span class="badge">Task ${escapeHtml(responseTaskId)}</span>` : ""}</div>
        </div>
        <div class="result-actions">
          ${responseTaskId ? `<button class="small-btn" type="button" data-refresh-task="${escapeHtml(task.id)}">Status prüfen</button><button class="copy-btn" type="button" data-copy="${escapeHtml(responseTaskId)}">Task-ID kopieren</button>` : ""}
          <button class="small-btn" type="button" data-open-archive="task:${escapeHtml(task.id)}" data-switch-tab="tab-archive">Archiv öffnen</button>
          <button class="small-btn danger-btn" type="button" data-delete-task="${escapeHtml(task.id)}">Löschen</button>
        </div>
      </div>
      <div class="result-body compact-body">
        ${prompt ? `<div class="summary-line"><strong>Prompt:</strong> ${escapeHtml(prompt.slice(0, 220))}${prompt.length > 220 ? "…" : ""}</div>` : ""}
        ${task.error_message ? `<div class="summary-line error-text"><strong>Fehler:</strong> ${escapeHtml(task.error_message)}</div>` : ""}
      </div>
    </article>`;
}

function renderLinks(urls) {
  const uniqueUrls = [...new Set((urls || []).filter(Boolean))];
  if (!uniqueUrls.length) return "";
  return `<div class="archive-section compact-section"><h4>Externe Links / Dateien</h4>${uniqueUrls.map(url => `<div class="link-row"><a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(shortUrl(url))}</a><button class="copy-btn" type="button" data-copy="${escapeHtml(url)}">Kopieren</button></div>`).join("")}</div>`;
}

const TASK_TYPE_META = {
  generate_music: { label: "Generiert", group: "Musik", className: "success", icon: "🎵", description: "Neu erzeugter Song" },
  extend_music: { label: "Extended", group: "Extend", className: "info", icon: "🔁", description: "Aus bestehender Audio-ID verlängert" },
  upload_and_cover: { label: "Cover Song", group: "Cover", className: "accent", icon: "🎭", description: "Aus vorhandener Audio-URL neu interpretiert" },
  add_vocals: { label: "Add Vocals", group: "Vocals", className: "accent", icon: "🎤", description: "Vocals auf vorhandenes Audio erzeugt" },
  add_instrumental: { label: "Add Instrumental", group: "Instrumental", className: "accent", icon: "🎹", description: "Instrumental zu vorhandenem Audio erzeugt" },
  generate_lyrics: { label: "Lyrics", group: "Lyrics", className: "warning", icon: "📝", description: "Songtext erzeugt" },
  generate_persona: { label: "Persona", group: "Persona", className: "persona", icon: "🧬", description: "Persona aus bestehendem Track erzeugt" },
  create_cover: { label: "Cover-Bild", group: "Cover", className: "image", icon: "🖼", description: "Bild-Cover zu Track erzeugt" },
  add_instrumental_music: { label: "Add Instrumental", group: "Instrumental", className: "accent", icon: "🎹", description: "Instrumental erzeugt" },
  boost_music_style: { label: "Style Boost", group: "Style", className: "info", icon: "✨", description: "Style-Beschreibung optimiert" },
  separate: { label: "Stem Split", group: "Audio", className: "info", icon: "✂", description: "Audio getrennt" },
  convert_to_wav: { label: "WAV", group: "Audio", className: "info", icon: "🌊", description: "WAV-Konvertierung" },
  generate_midi: { label: "MIDI", group: "Audio", className: "info", icon: "🎼", description: "MIDI erzeugt" },
  create_video: { label: "Video", group: "Video", className: "info", icon: "🎬", description: "Video erzeugt" }
};

function shortUrl(url, maxLength = 72) {
  const value = String(url || "");
  if (value.length <= maxLength) return value;
  try {
    const parsed = new URL(value);
    const name = parsed.pathname.split("/").filter(Boolean).pop() || parsed.hostname;
    return `${parsed.hostname}/…/${name}`;
  } catch {
    return `${value.slice(0, maxLength - 1)}…`;
  }
}

function looksLikeTechnicalName(value) {
  const text = String(value || "").trim();
  if (!text) return true;
  if (/^audio_\d+_[a-f0-9]{8,}\.(mp3|wav|m4a|aac|ogg|flac)$/i.test(text)) return true;
  if (/^[a-f0-9]{24,}$/i.test(text)) return true;
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(text)) return true;
  if (/^Task\s+[a-f0-9-]+$/i.test(text)) return true;
  return false;
}

function taskForItem(type, item) {
  if (!item) return null;
  if (type === "task") return item;
  const taskId = item.task_id || item.suno_task_id;
  const localTaskId = item.task_local_id;
  return cachedTasks.find(task =>
    (localTaskId && task.id === localTaskId) ||
    (taskId && (task.task_id === taskId || taskIdFromPayload(task.response_payload) === taskId || taskIdFromPayload(task.result_payload) === taskId))
  ) || null;
}

function metaForTaskType(taskType) {
  return TASK_TYPE_META[taskType] || { label: taskType || "Archiv", group: "Archiv", className: "", icon: "📦", description: "Archivierter Eintrag" };
}

function metaForEntry(type, item) {
  if (type === "audio") return metaForTaskType(taskForItem(type, item)?.task_type || "generate_music");
  if (type === "song") return metaForTaskType(taskForItem(type, item)?.task_type || item.metadata_json?.result_payload?.data?.operationType || "generate_music");
  if (type === "persona") return metaForTaskType("generate_persona");
  return metaForTaskType(item.task_type);
}

function statusLabel(status) {
  const value = String(status || "-");
  const map = {
    submitted: "Gestartet",
    pending: "Wartet",
    processing: "In Arbeit",
    running: "In Arbeit",
    queued: "Warteschlange",
    created: "Angelegt",
    SUCCESS: "Fertig",
    success: "Fertig",
    completed: "Fertig",
    complete: "Fertig",
    FIRST_SUCCESS: "Teilfertig",
    TEXT_SUCCESS: "Text fertig",
    failed: "Fehler",
    error: "Fehler",
    cached: "Lokal gespeichert",
    remote: "Remote verfügbar"
  };
  return map[value] || value;
}

function statusBadge(status) {
  const value = String(status || "").toLowerCase();
  let cls = "";
  if (["success", "completed", "complete", "cached", "done"].includes(value) || String(status) === "SUCCESS") cls = "success";
  else if (["failed", "error"].includes(value) || value.includes("failed") || value.includes("error")) cls = "error";
  else if (["submitted", "pending", "processing", "running", "queued", "created"].includes(value)) cls = "warning";
  return `<span class="badge ${cls}">${escapeHtml(statusLabel(status))}</span>`;
}

function extractRequestPayload(type, item) {
  if (type === "task") return item.request_payload || {};
  if (type === "song") return item.metadata_json?.request_payload || item.metadata_json?.suno_response?.request_payload || {};
  if (type === "audio") return taskForItem(type, item)?.request_payload || item.metadata_json?.candidate || {};
  return {};
}

function bestTitle(type, item) {
  if (!item) return "Archiv-Eintrag";
  const task = taskForItem(type, item);
  const request = extractRequestPayload(type, item);
  const candidate = item.metadata_json?.candidate || {};
  const relatedSong = type === "audio"
    ? cachedSongs.find(song => (item.song_id && song.id === item.song_id) || (item.suno_task_id && song.task_id === item.suno_task_id))
    : null;
  const titleCandidates = [
    item.title,
    relatedSong?.title,
    request.title,
    candidate.title,
    task?.request_payload?.title,
    item.name,
    item.filename
  ].filter(Boolean);
  const usable = titleCandidates.find(value => !looksLikeTechnicalName(value));
  if (usable) return String(usable).trim();
  const meta = metaForEntry(type, item);
  return `${meta.label} #${item.id}`;
}

function archiveItemSubtitle(type, item) {
  const meta = metaForEntry(type, item);
  const task = taskForItem(type, item);
  const status = item.status || task?.status;
  const parts = [meta.label, `#${item.id}`];
  if (status) parts.push(statusLabel(status));
  if (item.duration_seconds) parts.push(`${formatDuration(item.duration_seconds)}`);
  parts.push(formatDate(item.created_at));
  return parts.filter(Boolean).join(" · ");
}

function durationSecondsFromAsset(asset) {
  if (!asset) return 0;
  const candidates = [
    asset.duration_seconds,
    asset.duration,
    asset.metadata_json?.candidate?.duration,
    asset.metadata_json?.candidate?.duration_seconds,
    asset.metadata_json?.candidate?.durationSeconds,
    asset.metadata_json?.sunoData?.duration
  ];
  for (const candidate of candidates) {
    const value = Number(candidate);
    if (Number.isFinite(value) && value > 0) return value;
  }
  return 0;
}

function formatDuration(seconds) {
  const value = Number(seconds || 0);
  if (!Number.isFinite(value) || value <= 0) return "-";
  const min = Math.floor(value / 60);
  const sec = Math.round(value % 60).toString().padStart(2, "0");
  return `${min}:${sec}`;
}

function promptForEntry(type, item) {
  if (type === "song") return item.prompt || item.metadata_json?.request_payload?.prompt || "";
  if (type === "task") return item.request_payload?.prompt || item.request_payload?.content || "";
  if (type === "audio") return taskForItem(type, item)?.request_payload?.prompt || item.metadata_json?.candidate?.prompt || "";
  if (type === "persona") return item.description || "";
  return "";
}

function tagsForEntry(type, item) {
  const task = taskForItem(type, item);
  const candidate = item.metadata_json?.candidate || {};
  return item.tags || candidate.tags || task?.request_payload?.style || task?.request_payload?.tags || "";
}

function parentInfoFor(type, item) {
  const task = taskForItem(type, item);
  const request = extractRequestPayload(type, item);
  const parentTask = request.task_id || request.taskId || item.suno_task_id || item.task_id || task?.task_id;
  const audioId = item.audio_id || request.audio_id || request.audioId || "";
  return { task, request, parentTask, audioId };
}

function audioAssetsFor(type, item) {
  if (!Array.isArray(cachedAudioAssets)) return [];
  return cachedAudioAssets.filter(asset => {
    if (type === "song") {
      return (asset.song_id && asset.song_id === item.id) || (item.task_id && asset.suno_task_id === item.task_id);
    }
    if (type === "task") {
      return asset.task_local_id === item.id || (item.task_id && asset.suno_task_id === item.task_id);
    }
    if (type === "audio") return asset.id === item.id;
    return false;
  }).sort((a, b) => a.id - b.id);
}

function formatFileSize(bytes) {
  const value = Number(bytes || 0);
  if (!value) return "-";
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function coverUrlFor(type, item) {
  if (!item) return "";
  if (type === "song") return item.cover_image_url || audioAssetsFor(type, item).find(asset => asset.image_url)?.image_url || "";
  if (type === "audio") return item.image_url || "";
  const assets = audioAssetsFor(type, item);
  const assetWithImage = assets.find(asset => asset.image_url);
  return assetWithImage?.image_url || "";
}

function renderCoverImage(imageUrl, title = "Cover") {
  if (!imageUrl) return `<div class="cover-placeholder"><span>Kein Cover</span></div>`;
  return `<div class="cover-image-wrap"><img class="cover-image" src="${escapeHtml(imageUrl)}" alt="${escapeHtml(title)}" loading="lazy"><div class="cover-actions"><a href="${escapeHtml(imageUrl)}" target="_blank" rel="noopener noreferrer">Cover öffnen</a><button class="copy-btn" type="button" data-copy="${escapeHtml(imageUrl)}">URL kopieren</button></div></div>`;
}

function renderAudioActionButtons(asset) {
  const hasAudioId = Boolean(asset.audio_id);
  const hasTaskId = Boolean(asset.suno_task_id);
  const hasSourceUrl = Boolean(asset.source_url || asset.public_url);
  const task = taskForItem("audio", asset);
  const isExtended = task?.task_type === "extend_music";
  const extendLabel = isExtended ? "🔁 Nochmal extenden" : "🔁 Extend";
  const extendTitle = isExtended ? "Diese Extended-Version erneut verlängern" : "Diesen Track verlängern";
  return `<div class="audio-workflow-actions" aria-label="Workflow-Aktionen">
    <button class="small-btn primary-action" type="button" data-audio-action="extend" data-asset-id="${escapeHtml(asset.id)}" ${hasAudioId ? `title="${escapeHtml(extendTitle)}"` : "disabled title='Keine Audio-ID gespeichert'"}>${extendLabel}</button>
    <button class="small-btn" type="button" data-audio-action="cover-song" data-asset-id="${escapeHtml(asset.id)}" ${hasSourceUrl ? "" : "disabled title='Keine Audio-URL gespeichert'"}>🎭 Cover Song</button>
    <button class="small-btn" type="button" data-audio-action="add-vocals" data-asset-id="${escapeHtml(asset.id)}" ${hasSourceUrl ? "" : "disabled title='Keine Audio-URL gespeichert'"}>🎤 Add Vocals</button>
    <button class="small-btn" type="button" data-audio-action="add-instrumental" data-asset-id="${escapeHtml(asset.id)}" ${hasSourceUrl ? "" : "disabled title='Keine Audio-URL gespeichert'"}>🎹 Add Instrumental</button>
    <button class="small-btn" type="button" data-audio-action="persona" data-asset-id="${escapeHtml(asset.id)}" ${hasAudioId && hasTaskId ? "" : "disabled title='Audio-ID oder Task-ID fehlt'"}>🧬 Persona</button>
    <button class="small-btn" type="button" data-audio-action="cover-image" data-asset-id="${escapeHtml(asset.id)}" ${hasTaskId ? "" : "disabled title='Keine Task-ID gespeichert'"}>🖼 Cover</button>
    ${hasAudioId ? `<button class="copy-btn" type="button" data-copy="${escapeHtml(asset.audio_id)}">Audio-ID kopieren</button>` : ""}
    ${renderPlaylistSelectForAsset(asset)}
  </div>`;
}

function parentAudioInfoForAsset(asset) {
  const task = taskForItem("audio", asset);
  const request = task?.request_payload || {};
  const parentAudioId = request.audio_id || request.audioId || "";
  const parentUrl = request.audio_url || request.uploadUrl || request.upload_url || "";
  return { task, request, parentAudioId, parentUrl };
}

function renderAudioLineage(asset) {
  const { task, parentAudioId, parentUrl } = parentAudioInfoForAsset(asset);
  if (!task || task.task_type !== "extend_music") return "";
  return `<div class="lineage-box">
    <span class="lineage-label">Extended aus</span>
    ${parentAudioId ? `<code>${escapeHtml(parentAudioId)}</code><button class="copy-btn mini-copy" type="button" data-copy="${escapeHtml(parentAudioId)}">kopieren</button>` : parentUrl ? `<a href="${escapeHtml(parentUrl)}" target="_blank" rel="noopener noreferrer">Quell-Audio öffnen</a>` : `<span>unbekannter Quelle</span>`}
  </div>`;
}

function newestUsableAudioAsset(assets) {
  return [...(assets || [])].filter(asset => asset.audio_id).sort((a, b) => new Date(b.updated_at || b.created_at || 0) - new Date(a.updated_at || a.created_at || 0))[0] || null;
}

function renderArchiveNextProductionActions(type, item, assets) {
  const usable = newestUsableAudioAsset(assets);
  if (!usable) return "";
  const meta = metaForEntry(type, item);
  const title = bestTitle("audio", usable);
  const isExtended = taskForItem("audio", usable)?.task_type === "extend_music";
  return `<section class="archive-section production-actions-section">
    <div class="archive-section-head"><h4>Nächster Produktionsschritt</h4><span class="badge ${escapeHtml(meta.className)}">${escapeHtml(meta.label)}</span></div>
    <div class="production-action-card">
      <div>
        <strong>${escapeHtml(isExtended ? "Extended-Version weiter verlängern" : "Track weiterverarbeiten")}</strong>
        <p>${escapeHtml(title)} kann direkt erneut extended oder für weitere Workflows genutzt werden.</p>
      </div>
      <div class="audio-workflow-actions inline-actions">
        <button class="small-btn primary-action" type="button" data-audio-action="extend" data-asset-id="${escapeHtml(usable.id)}">🔁 ${escapeHtml(isExtended ? "Nochmal extenden" : "Extend")}</button>
        <button class="small-btn" type="button" data-audio-action="cover-song" data-asset-id="${escapeHtml(usable.id)}">🎭 Cover Song</button>
        <button class="small-btn" type="button" data-audio-action="add-vocals" data-asset-id="${escapeHtml(usable.id)}">🎤 Add Vocals</button>
        <button class="small-btn" type="button" data-audio-action="add-instrumental" data-asset-id="${escapeHtml(usable.id)}">🎹 Add Instrumental</button>
      </div>
    </div>
  </section>`;
}

function renderAudioAssets(assets, parentTitle = "") {
  if (!assets.length) return "";
  return `<div class="archive-section audio-section"><div class="archive-section-head"><h4>Audio-Versionen</h4><span class="badge success">${assets.length} Datei${assets.length === 1 ? "" : "en"}</span></div>${assets.map((asset, index) => {
    const playableUrl = asset.public_url || asset.source_url;
    const downloadUrl = asset.status === "cached" ? `/api/archive/audio/${asset.id}/download` : asset.source_url;
    const title = bestTitle("audio", asset);
    const displayTitle = `${title}${assets.length > 1 ? ` · Variante ${index + 1}` : ""}`;
    const tags = tagsForEntry("audio", asset);
    return `<article class="audio-asset-card ${asset.status === "failed" ? "error" : ""}">
      <div class="audio-asset-layout">
        ${renderCoverImage(asset.image_url, displayTitle)}
        <div class="audio-asset-content">
          <div class="audio-asset-head">
            <div class="audio-title-block"><strong>${escapeHtml(displayTitle)}</strong><div class="result-meta">${statusBadge(asset.status)}<span class="badge">${escapeHtml(formatFileSize(asset.file_size_bytes))}</span>${asset.duration_seconds ? `<span class="badge">${escapeHtml(formatDuration(durationSecondsFromAsset(asset)))}</span>` : ""}${asset.content_type ? `<span class="badge">${escapeHtml(asset.content_type)}</span>` : ""}</div></div>
            <div class="result-actions"><button class="copy-btn" type="button" data-copy="${escapeHtml(playableUrl)}">URL kopieren</button><a class="button-link" href="${escapeHtml(downloadUrl)}" download>Download</a></div>
          </div>
          ${assetPlaybackUrl(asset) ? `<audio class="audio-player" controls preload="metadata" src="${escapeHtml(assetPlaybackUrl(asset))}"></audio>` : ""}
          ${renderAudioLineage(asset)}
          <div class="audio-info-grid">
            ${asset.audio_id ? `<div class="mini-info"><span>Audio-ID</span><code>${escapeHtml(asset.audio_id)}</code></div>` : ""}
            ${asset.suno_task_id ? `<div class="mini-info"><span>Task-ID</span><code>${escapeHtml(asset.suno_task_id)}</code></div>` : ""}
          </div>
          ${tags ? `<div class="style-preview"><strong>Style</strong><span>${escapeHtml(String(tags).slice(0, 260))}${String(tags).length > 260 ? "…" : ""}</span></div>` : ""}
          ${asset.error_message ? `<div class="summary-line error-text"><strong>Fehler:</strong> ${escapeHtml(asset.error_message)}</div>` : ""}
          ${renderAudioActionButtons(asset)}
          <div class="link-row"><a href="${escapeHtml(asset.source_url)}" target="_blank" rel="noopener noreferrer">Externe Suno-Quelle öffnen</a><button class="copy-btn" type="button" data-copy="${escapeHtml(asset.source_url)}">Kopieren</button></div>
        </div>
      </div>
    </article>`;
  }).join("")}</div>`;
}

function renderTexts(texts) {
  const usableTexts = (texts || []).filter(entry => entry.value && String(entry.value).trim());
  if (!usableTexts.length) return "";
  return usableTexts.map((entry, index) => `
    <div class="archive-section">
      <div class="archive-section-head"><h4>${escapeHtml(entry.label)}${usableTexts.length > 1 ? ` ${index + 1}` : ""}</h4><button class="copy-btn" type="button" data-copy="${escapeHtml(entry.value)}">Kopieren</button></div>
      <div class="generated-text">${escapeHtml(entry.value)}</div>
    </div>`).join("");
}

function renderWorkflowPanel(type, item, assets) {
  const meta = metaForEntry(type, item);
  const { task, request, parentTask, audioId } = parentInfoFor(type, item);
  const sourceAudio = request.audio_url || request.uploadUrl || request.upload_url || request.audioId || audioId || "";
  return `<div class="archive-workflow-card ${escapeHtml(meta.className)}">
    <div class="workflow-icon">${escapeHtml(meta.icon)}</div>
    <div>
      <h3>${escapeHtml(meta.label)}</h3>
      <p>${escapeHtml(meta.description)}</p>
      <div class="result-meta">
        ${task?.task_type ? `<span class="badge">${escapeHtml(task.task_type)}</span>` : ""}
        ${task?.status ? statusBadge(task.status) : item.status ? statusBadge(item.status) : ""}
        ${assets.length ? `<span class="badge success">${assets.length} Audio-Version${assets.length === 1 ? "" : "en"}</span>` : ""}
      </div>
    </div>
    <div class="workflow-ids">
      ${parentTask ? `<button class="copy-btn" type="button" data-copy="${escapeHtml(parentTask)}">Task-ID kopieren</button>` : ""}
      ${audioId ? `<button class="copy-btn" type="button" data-copy="${escapeHtml(audioId)}">Audio-ID kopieren</button>` : ""}
    </div>
  </div>`;
}

function renderArchiveDetail(type, item) {
  const source = type === "song" ? item : type === "audio" ? item : type === "persona" ? item : { response_payload: item.response_payload, result_payload: item.result_payload };
  const texts = type === "song" ? collectGeneratedTexts({ lyrics: item.lyrics, metadata_json: item.metadata_json }) : type === "audio" ? [] : type === "persona" ? [{ label: "Beschreibung", value: item.description || "" }].filter(x => x.value) : collectGeneratedTexts(source);
  const urls = type === "song" ? [item.audio_url, item.video_url, item.midi_url, item.wav_url].filter(Boolean) : type === "audio" ? [item.source_url, item.public_url].filter(Boolean) : type === "persona" ? [] : collectUrls(source);
  const relatedAudioAssets = type === "audio" ? [item] : type === "persona" ? [] : audioAssetsFor(type, item);
  const prompt = promptForEntry(type, item);
  const title = bestTitle(type, item);
  const coverImageUrl = coverUrlFor(type, item);
  const task = taskForItem(type, item);
  const request = extractRequestPayload(type, item);
  const model = item.model || request.model || task?.request_payload?.model || item.metadata_json?.candidate?.modelName || "-";
  archiveDetail.classList.remove("empty-state");
  archiveDetail.innerHTML = `
    <article class="archive-detail-card upgraded-archive-detail">
      <div class="archive-hero">
        ${renderCoverImage(coverImageUrl, title)}
        <div class="archive-hero-main">
          ${renderWorkflowPanel(type, item, relatedAudioAssets)}
          <div class="archive-title-row">
            <div><span class="eyebrow">${escapeHtml(metaForEntry(type, item).group)}</span><h2>${escapeHtml(title)}</h2></div>
            <div class="result-actions">
              ${prompt ? `<button class="copy-btn" type="button" data-copy="${escapeHtml(prompt)}">Prompt kopieren</button>` : ""}
              <button class="copy-btn" type="button" data-copy="${escapeHtml(JSON.stringify(item, null, 2))}">Alles kopieren</button>
            </div>
          </div>
          <div class="field-grid dense-grid">
            <div class="info-field"><span class="info-label">Status</span><span class="info-value">${escapeHtml(statusLabel(item.status || task?.status || "-"))}</span></div>
            <div class="info-field"><span class="info-label">Modell</span><span class="info-value">${escapeHtml(model)}</span></div>
            <div class="info-field"><span class="info-label">Erstellt</span><span class="info-value">${escapeHtml(formatDate(item.created_at))}</span></div>
            <div class="info-field"><span class="info-label">Archiv-ID</span><span class="info-value">${escapeHtml(type)} #${escapeHtml(item.id)}</span></div>
          </div>
        </div>
      </div>
      ${renderArchiveNextProductionActions(type, item, relatedAudioAssets)}
      ${renderAudioAssets(relatedAudioAssets, title)}
      ${prompt ? `<div class="archive-section"><div class="archive-section-head"><h4>Prompt / Lyrics-Vorgabe</h4><button class="copy-btn" type="button" data-copy="${escapeHtml(prompt)}">Kopieren</button></div><div class="generated-text compact-text">${escapeHtml(prompt)}</div></div>` : ""}
      ${renderTexts(texts)}
      ${renderLinks(urls)}
      <details class="details"><summary>Technische Details anzeigen</summary><pre>${escapeHtml(JSON.stringify(item, null, 2))}</pre></details>
    </article>`;
}

function archiveItemText(type, item) {
  const prompt = promptForEntry(type, item);
  const title = bestTitle(type, item);
  const meta = metaForEntry(type, item);
  return `${title || ""} ${prompt || ""} ${meta.label} ${meta.group} ${item.status || ""} ${item.task_id || ""} ${item.suno_task_id || ""} ${item.source_url || ""} ${item.persona_id || ""} ${item.style || ""}`.toLowerCase();
}

function archiveOperationKey(type, item) {
  const task = taskForItem(type, item);
  const taskType = task?.task_type || item.task_type || item.metadata_json?.result_payload?.data?.operationType || "";
  const value = String(taskType).toLowerCase();
  if (value.includes("extend")) return "extended";
  if (value.includes("cover") || value.includes("upload_and_cover")) return "cover";
  if (value.includes("add_vocals")) return "vocals";
  if (value.includes("add_instrumental")) return "instrumental";
  if (value.includes("lyrics") || type === "song" && item.lyrics && !item.audio_url) return "lyrics";
  if (value.includes("persona") || type === "persona") return "personas";
  if (type === "task") return "tasks";
  return "generated";
}

function libraryGroupLabel(key) {
  const labels = {
    generated: "Generiert",
    extended: "Extended",
    cover: "Cover Song",
    vocals: "Add Vocals",
    instrumental: "Add Instrumental",
    lyrics: "Lyrics",
    personas: "Persona",
    tasks: "Task"
  };
  return labels[key] || "Song";
}

function libraryFilterMatches(filter, entry) {
  if (!filter || filter === "all") return entry.kind !== "task";
  if (filter === "tasks") return entry.kind === "task";
  return entry.operation === filter;
}

function buildArchiveItems(filter) {
  const items = [];
  const representedSongIds = new Set();
  const representedTaskIds = new Set();

  cachedAudioAssets.forEach(asset => {
    const task = taskForItem("audio", asset);
    const operation = archiveOperationKey("audio", asset);
    if (asset.song_id) representedSongIds.add(asset.song_id);
    if (asset.task_local_id) representedTaskIds.add(asset.task_local_id);
    items.push({
      kind: "audio",
      type: "audio",
      operation,
      item: asset,
      task,
      sortDate: asset.updated_at || asset.created_at,
      title: bestTitle("audio", asset)
    });
  });

  cachedSongs.forEach(song => {
    if (representedSongIds.has(song.id)) return;
    const assets = audioAssetsFor("song", song);
    if (assets.length) return;
    const operation = archiveOperationKey("song", song);
    items.push({
      kind: operation === "lyrics" ? "lyrics" : "song",
      type: "song",
      operation,
      item: song,
      task: taskForItem("song", song),
      sortDate: song.updated_at || song.created_at,
      title: bestTitle("song", song)
    });
  });

  cachedPersonas.forEach(persona => items.push({
    kind: "persona",
    type: "persona",
    operation: "personas",
    item: persona,
    task: null,
    sortDate: persona.updated_at || persona.created_at,
    title: bestTitle("persona", persona)
  }));

  cachedTasks.forEach(task => {
    const hasAudio = representedTaskIds.has(task.id) || cachedAudioAssets.some(asset => (asset.task_local_id && asset.task_local_id === task.id) || (task.task_id && asset.suno_task_id === task.task_id));
    const hasSong = cachedSongs.some(song => song.task_id && task.task_id && song.task_id === task.task_id);
    const isTechnicalOnly = !hasAudio && !hasSong;
    const operation = archiveOperationKey("task", task);
    if (filter === "tasks" || (isTechnicalOnly && ["lyrics", "personas"].includes(operation))) {
      items.push({ kind: "task", type: "task", operation, item: task, task, sortDate: task.updated_at || task.created_at, title: bestTitle("task", task) });
    }
  });

  return items
    .filter(entry => libraryFilterMatches(filter, entry))
    .sort((a, b) => new Date(b.sortDate || 0) - new Date(a.sortDate || 0));
}

function renderArchiveStats(items) {
  const counts = items.reduce((acc, entry) => {
    const key = libraryGroupLabel(entry.operation);
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
  const badges = Object.entries(counts).map(([key, value]) => `<span class="archive-stat-badge">${escapeHtml(key)} <strong>${escapeHtml(value)}</strong></span>`).join("");
  return badges ? `<div class="archive-stats library-stats">${badges}</div>` : "";
}

function assetPlaybackUrl(asset) {
  if (!asset) return "";

  // Stabiler Enterprise-Playback-Pfad:
  // Für lokal gecachte Dateien wird der kontrollierte Backend-Stream genutzt.
  // Der Backend-Endpunkt repariert veraltete local_path/public_url-Werte automatisch
  // anhand von filename + SUNO_AUDIO_STORAGE_DIR.
  if (String(asset.status || "").toLowerCase() === "cached" && asset.id) {
    const version = asset.file_size_bytes || asset.updated_at || Date.now();
    return `/api/archive/audio/${encodeURIComponent(asset.id)}/stream?v=${encodeURIComponent(version)}`;
  }

  if (asset.public_url) return normalizeMediaUrl(asset.public_url);
  if (asset.source_url) return normalizeMediaUrl(asset.source_url);

  return "";
}



function firstDefinedValue(...values) {
  return values.find(value => value !== undefined && value !== null && value !== "");
}

function formatBooleanLabel(value) {
  if (value === true || String(value).toLowerCase() === "true") return "Ja";
  if (value === false || String(value).toLowerCase() === "false") return "Nein";
  return "-";
}

function formatVocalGenderLabel(value) {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (!normalized) return "-";
  if (["m", "male", "man", "masculine", "masc"].includes(normalized)) return "Male";
  if (["f", "female", "woman", "feminine", "fem"].includes(normalized)) return "Female";
  return String(value);
}

function generationOptionsForAsset(asset) {
  const meta = asset?.metadata_json || {};
  const task = taskForItem("audio", asset);
  const request = task?.request_payload || meta.request_payload || meta.requestPayload || meta.suno_response?.request_payload || meta.suno_response?.requestPayload || {};
  const candidate = meta.candidate || {};
  return {
    negative_tags: firstDefinedValue(asset?.negative_tags, request.negative_tags, request.negativeTags, candidate.negative_tags, candidate.negativeTags, meta.negative_tags, meta.negativeTags) || "",
    vocal_gender: firstDefinedValue(asset?.vocal_gender, request.vocal_gender, request.vocalGender, candidate.vocal_gender, candidate.vocalGender, meta.vocal_gender, meta.vocalGender) || "",
    styleWeight: firstDefinedValue(asset?.styleWeight, request.styleWeight, request.style_weight, candidate.styleWeight, candidate.style_weight, meta.styleWeight),
    weirdnessConstraint: firstDefinedValue(asset?.weirdnessConstraint, request.weirdnessConstraint, request.weirdness_constraint, candidate.weirdnessConstraint, candidate.weirdness_constraint, meta.weirdnessConstraint),
    audioWeight: firstDefinedValue(asset?.audioWeight, request.audioWeight, request.audio_weight, candidate.audioWeight, candidate.audio_weight, meta.audioWeight),
    customMode: firstDefinedValue(asset?.customMode, request.customMode, request.custom_mode, candidate.customMode, candidate.custom_mode, meta.customMode),
    instrumental: firstDefinedValue(asset?.instrumental, request.instrumental, candidate.instrumental, meta.instrumental),
  };
}

function hasGenerationOptionsForAsset(asset) {
  const options = generationOptionsForAsset(asset);
  return Boolean(
    options.negative_tags ||
    options.vocal_gender ||
    options.styleWeight !== undefined ||
    options.weirdnessConstraint !== undefined ||
    options.audioWeight !== undefined ||
    options.customMode !== undefined ||
    options.instrumental !== undefined
  );
}

function renderGenerationOptionsPanel(asset) {
  if (!hasGenerationOptionsForAsset(asset)) return "";
  const options = generationOptionsForAsset(asset);
  const rows = [
    ["Negative Tags", options.negative_tags || "-"],
    ["Vocal Gender", formatVocalGenderLabel(options.vocal_gender)],
    ["Style Weight", options.styleWeight ?? "-"],
    ["Weirdness", options.weirdnessConstraint ?? "-"],
    ["Audio Weight", options.audioWeight ?? "-"],
    ["Custom Mode", formatBooleanLabel(options.customMode)],
    ["Instrumental", formatBooleanLabel(options.instrumental)],
  ];
  const copyText = rows.map(([label, value]) => `${label}: ${value}`).join("\n");
  return `<section class="song-detail-panel wide-panel generation-options-panel"><div class="archive-section-head"><h4>Verwendete Optionen</h4><button class="copy-btn" type="button" data-copy="${escapeHtml(copyText)}">Kopieren</button></div><div class="workflow-mini-grid options-mini-grid">${rows.map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("")}</div></section>`;
}



function relatedSongForAsset(asset) {
  return cachedSongs.find(song => (asset.song_id && song.id === asset.song_id) || (asset.suno_task_id && song.task_id === asset.suno_task_id)) || null;
}

function libraryPromptForAudio(asset) {
  const song = relatedSongForAsset(asset);
  const task = taskForItem("audio", asset);
  return asset.metadata_json?.candidate?.prompt || song?.prompt || task?.request_payload?.prompt || "";
}

function libraryLyricsForAudio(asset) {
  const song = relatedSongForAsset(asset);
  const candidate = asset.metadata_json?.candidate || {};
  return song?.lyrics || candidate.lyric || candidate.lyrics || "";
}

function renderLibraryAudioRow(entry) {
  const asset = entry.item;
  const task = entry.task || taskForItem("audio", asset);
  const title = bestTitle("audio", asset);
  const operation = archiveOperationKey("audio", asset);
  const label = libraryGroupLabel(operation);
  const playerUrl = assetPlaybackUrl(asset);
  const downloadUrl = asset.status === "cached" ? `/api/archive/audio/${asset.id}/download` : asset.source_url;
  const prompt = libraryPromptForAudio(asset);
  const lyrics = libraryLyricsForAudio(asset);
  const tags = tagsForEntry("audio", asset);
  const cover = coverUrlFor("audio", asset);
  const parent = parentAudioInfoForAsset(asset);
  const ref = `audio:${asset.id}`;
  const duration = asset.duration_seconds ? formatDuration(durationSecondsFromAsset(asset)) : "";
  const status = asset.status || task?.status || "-";

  return `<article class="suno-song-row" data-open-archive="${escapeHtml(ref)}" data-operation="${escapeHtml(operation)}">
    <div class="song-mainline">
      <div class="song-cover-slot">${cover ? `<img src="${escapeHtml(cover)}" alt="${escapeHtml(title)}" loading="lazy">` : `<span>${escapeHtml(metaForEntry("audio", asset).icon)}</span>`}</div>
      <div class="song-title-area">
        <div class="song-title-line"><h3>${escapeHtml(title)}</h3><span class="badge operation-${escapeHtml(operation)}">${escapeHtml(label)}</span>${statusBadge(status)}</div>
        <div class="song-meta-line">
          ${duration ? `<span>${escapeHtml(duration)}</span>` : ""}
          ${asset.audio_id ? `<span title="Audio-ID">Audio-ID ${escapeHtml(shortId(asset.audio_id))}</span>` : ""}
          ${task?.task_id ? `<span title="Task-ID">Task ${escapeHtml(shortId(task.task_id))}</span>` : ""}
          <span>${escapeHtml(formatDate(asset.created_at))}</span>
        </div>
        ${tags ? `<div class="song-style-line">${escapeHtml(String(tags).slice(0, 180))}${String(tags).length > 180 ? "…" : ""}</div>` : ""}
      </div>
      <div class="song-player-area">
        ${playerUrl ? `<audio controls preload="metadata" src="${escapeHtml(playerUrl)}"></audio>` : ""}
      </div>
      <div class="song-actions-menu">
        <button class="small-btn" type="button" data-reuse-prompt-asset="${escapeHtml(asset.id)}">Reuse Prompt</button>
        <button class="small-btn" type="button" data-edit-title-type="audio" data-edit-title-id="${escapeHtml(asset.id)}" data-current-title="${escapeHtml(title)}">Titel</button>
        <button class="small-btn primary-action" type="button" data-audio-action="extend" data-asset-id="${escapeHtml(asset.id)}" ${asset.audio_id ? "" : "disabled"}>Extend</button>
        <button class="small-btn" type="button" data-audio-action="cover-song" data-asset-id="${escapeHtml(asset.id)}" ${playerUrl ? "" : "disabled"}>Cover</button>
        <button class="small-btn" type="button" data-audio-action="add-vocals" data-asset-id="${escapeHtml(asset.id)}" ${playerUrl ? "" : "disabled"}>Vocals</button>
        <button class="small-btn" type="button" data-audio-action="add-instrumental" data-asset-id="${escapeHtml(asset.id)}" ${playerUrl ? "" : "disabled"}>Instrumental</button>
        <button class="small-btn" type="button" data-audio-action="persona" data-asset-id="${escapeHtml(asset.id)}" ${asset.audio_id && asset.suno_task_id ? "" : "disabled"}>Persona</button>
      </div>
    </div>
    <details class="song-details">
      <summary>Details, Lyrics und weitere Aktionen</summary>
      <div class="song-detail-grid">
        <section class="song-detail-panel">
          <h4>Workflow</h4>
          <div class="workflow-mini-grid">
            <div><span>Typ</span><strong>${escapeHtml(label)}</strong></div>
            <div><span>Status</span><strong>${escapeHtml(statusLabel(status))}</strong></div>
            <div><span>Audio-ID</span><code>${escapeHtml(asset.audio_id || "-")}</code></div>
            <div><span>Task-ID</span><code>${escapeHtml(asset.suno_task_id || task?.task_id || "-")}</code></div>
          </div>
          ${operation === "extended" ? `<div class="lineage-box"><span class="lineage-label">Extended aus</span>${parent.parentAudioId ? `<code>${escapeHtml(parent.parentAudioId)}</code>` : `<span>Quelle nicht gespeichert</span>`}</div>` : ""}
          ${renderAudioActionButtons(asset)}
        </section>
        ${renderGenerationOptionsPanel(asset)}
        ${prompt ? `<section class="song-detail-panel"><div class="archive-section-head"><h4>Prompt / Lyrics-Vorgabe</h4><button class="copy-btn" type="button" data-copy="${escapeHtml(prompt)}">Kopieren</button></div><div class="generated-text compact-text">${escapeHtml(prompt)}</div></section>` : ""}
        ${lyrics ? `<section class="song-detail-panel"><div class="archive-section-head"><h4>Lyrics</h4><button class="copy-btn" type="button" data-copy="${escapeHtml(lyrics)}">Kopieren</button></div><div class="generated-text compact-text">${escapeHtml(lyrics)}</div></section>` : ""}
        <section class="song-detail-panel"><h4>Links</h4>
          <div class="link-row"><a href="${escapeHtml(asset.source_url)}" target="_blank" rel="noopener noreferrer">Suno-Quelle</a><button class="copy-btn" type="button" data-copy="${escapeHtml(asset.source_url)}">Kopieren</button></div>
          ${asset.public_url ? `<div class="link-row"><a href="${escapeHtml(asset.public_url)}" target="_blank" rel="noopener noreferrer">Lokale Datei</a><button class="copy-btn" type="button" data-copy="${escapeHtml(asset.public_url)}">Kopieren</button></div>` : ""}
          <a class="button-link" href="${escapeHtml(downloadUrl)}" download>Download</a>
        </section>
        <details class="details technical-details"><summary>Technische Details anzeigen</summary><pre>${escapeHtml(JSON.stringify(asset, null, 2))}</pre></details>
      </div>
    </details>
  </article>`;
}

function renderLibraryNonAudioRow(entry) {
  const { type, item, operation } = entry;
  const title = bestTitle(type, item);
  const label = libraryGroupLabel(operation);
  const prompt = promptForEntry(type, item);
  const texts = type === "song" ? collectGeneratedTexts({ lyrics: item.lyrics, metadata_json: item.metadata_json }) : type === "persona" ? [{ label: "Beschreibung", value: item.description || "" }] : collectGeneratedTexts({ response_payload: item.response_payload, result_payload: item.result_payload });
  const status = item.status || entry.task?.status || "-";
  const ref = `${type}:${item.id}`;
  const icon = metaForEntry(type, item).icon;
  return `<article class="suno-song-row non-audio-row" data-open-archive="${escapeHtml(ref)}" data-operation="${escapeHtml(operation)}">
    <div class="song-mainline">
      <div class="song-cover-slot no-cover"><span>${escapeHtml(icon)}</span></div>
      <div class="song-title-area">
        <div class="song-title-line"><h3>${escapeHtml(title)}</h3><span class="badge operation-${escapeHtml(operation)}">${escapeHtml(label)}</span>${statusBadge(status)}</div>
        <div class="song-meta-line"><span>${escapeHtml(formatDate(item.created_at))}</span>${item.persona_id ? `<span>Persona ${escapeHtml(shortId(item.persona_id))}</span>` : ""}${item.task_id ? `<span>Task ${escapeHtml(shortId(item.task_id))}</span>` : ""}</div>
        ${prompt ? `<div class="song-style-line">${escapeHtml(String(prompt).slice(0, 180))}${String(prompt).length > 180 ? "…" : ""}</div>` : ""}
      </div>
      <div class="song-player-area empty-player">${escapeHtml(label)}</div>
      <div class="song-actions-menu">
        <button class="small-btn" type="button" data-edit-title-type="${escapeHtml(type)}" data-edit-title-id="${escapeHtml(item.id)}" data-current-title="${escapeHtml(title)}">Titel</button>
        ${prompt ? `<button class="copy-btn" type="button" data-copy="${escapeHtml(prompt)}">Prompt</button>` : ""}
        <button class="copy-btn" type="button" data-copy="${escapeHtml(JSON.stringify(item, null, 2))}">Kopieren</button>
      </div>
    </div>
    <details class="song-details">
      <summary>Details anzeigen</summary>
      <div class="song-detail-grid">
        ${prompt ? `<section class="song-detail-panel"><div class="archive-section-head"><h4>Prompt</h4><button class="copy-btn" type="button" data-copy="${escapeHtml(prompt)}">Kopieren</button></div><div class="generated-text compact-text">${escapeHtml(prompt)}</div></section>` : ""}
        ${renderTexts(texts)}
        <details class="details technical-details"><summary>Technische Details anzeigen</summary><pre>${escapeHtml(JSON.stringify(item, null, 2))}</pre></details>
      </div>
    </details>
  </article>`;
}

function shortId(value) {
  const text = String(value || "");
  if (text.length <= 12) return text;
  return `${text.slice(0, 8)}…${text.slice(-4)}`;
}

function renderLyricsArchiveOnly() {
  const query = (archiveSearch?.value || "").toLowerCase().trim();
  const drafts = cachedLyricDrafts.filter(draft => {
    const haystack = [draft.title, draft.status, draft.language, draft.tags, draft.content].filter(Boolean).join(" ").toLowerCase();
    return !query || haystack.includes(query);
  });
  lastVisibleArchiveRefs = drafts.map(draft => archiveRef("lyric", draft.id));
  archiveList.innerHTML = `
    ${renderWorkflowStepper()}
    <div class="library-command-bar">
      <div class="library-summary-bar final-summary">
        <div><strong>${drafts.length}</strong><span>Songtexte</span></div>
        <div><strong>${drafts.filter(d => d.status === "ready").length}</strong><span>Bereit</span></div>
        <div><strong>${drafts.filter(d => d.status === "draft").length}</strong><span>Entwürfe</span></div>
        <div><strong>${drafts.filter(d => d.status === "archived").length}</strong><span>Archiviert</span></div>
      </div>
      <div class="library-command-actions">
        <button class="secondary small-btn" type="button" data-switch-tab="tab-lyric-editor">Neuen Songtext erstellen</button>
      </div>
    </div>
    <div class="lyrics-library-grid">
      ${drafts.map(draft => `<article class="library-project-card lyric-only-card" data-load-lyric-draft="${escapeHtml(draft.id)}" data-switch-tab="tab-lyric-editor">
        <div class="project-main">
          <div class="project-cover placeholder-cover">📝</div>
          <div class="project-info">
            <h3>${escapeHtml(draft.title)}</h3>
            <div class="project-meta"><span>${escapeHtml(draft.status || "draft")}</span><span>${escapeHtml(draft.language || "-")}</span><span>${escapeHtml(formatDate(draft.updated_at))}</span></div>
            <p>${escapeHtml(String(draft.content || "").slice(0, 220))}${String(draft.content || "").length > 220 ? "…" : ""}</p>
          </div>
        </div>
        <div class="project-actions"><button class="small-btn" type="button" data-load-lyric-draft="${escapeHtml(draft.id)}" data-switch-tab="tab-lyric-editor">Bearbeiten</button><button class="small-btn" type="button" data-send-lyric-to-music="${escapeHtml(draft.id)}">Musik erzeugen</button><button class="small-btn danger" type="button" data-delete-lyric-draft="${escapeHtml(draft.id)}">Löschen</button></div>
      </article>`).join("") || `<div class="empty-state">Keine Songtexte gefunden.</div>`}
    </div>`;
  updateArchiveSelectionBar();
  if (archiveDetail) archiveDetail.classList.add("visually-hidden");
}

function sendLyricDraftByIdToMusic(id) {
  const draft = cachedLyricDrafts.find(item => String(item.id) === String(id));
  if (!draft) return;
  const form = document.querySelector("#generateForm");
  setFormField(form, "customMode", "true");
  setFormField(form, "title", draft.title || "Neuer Song");
  setFormField(form, "prompt", draft.content || "");
  switchTab("tab-music");
  notify("Songtext in Musik Custom übernommen");
}

function renderArchive() {
  if (!archiveList) return;
  const openState = captureLibraryOpenState();
  const query = (archiveSearch?.value || "").toLowerCase().trim();
  const filter = archiveType?.value || "all";
  document.querySelectorAll(".library-filter").forEach(button => button.classList.toggle("active", button.dataset.archiveFilter === filter));
  const items = buildArchiveItems(filter);
  const filtered = items.filter(entry => !query || archiveItemText(entry.type, entry.item).includes(query));
  const rows = filtered.map(entry => entry.kind === "audio" ? renderLibraryAudioRow(entry) : renderLibraryNonAudioRow(entry)).join("");
  archiveList.innerHTML = `
    <div class="library-summary-bar">
      <div><strong>${filtered.length}</strong><span>Einträge</span></div>
      <div><strong>${filtered.filter(entry => entry.kind === "audio").length}</strong><span>Songs</span></div>
      <div><strong>${cachedAudioAssets.filter(asset => asset.status === "cached").length}</strong><span>Lokal</span></div>
      <div><strong>${cachedPlaylists.length}</strong><span>Playlists</span></div>
    </div>
    ${renderArchiveStats(filtered)}
    ${rows || `<div class="empty-state">Keine passenden Library-Einträge gefunden.</div>`}`;
  if (archiveDetail) archiveDetail.classList.add("visually-hidden");
}

function openArchiveEntry(ref) {
  if (!ref) return;
  if (archiveType && archiveType.value === "tasks" && !String(ref).startsWith("task:")) archiveType.value = "all";
  renderArchive();
  const row = document.querySelector(`[data-open-archive="${CSS.escape(String(ref))}"]`);
  if (!row) return;
  row.classList.add("active");
  const details = row.querySelector("details.song-details");
  if (details) details.open = true;
  row.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function loadRuntimeConfig() {
  runtimeConfig = await api("/api/music/runtime-config");
  for (const modelSelect of [document.querySelector("#musicModel"), document.querySelector("#extendModel"), document.querySelector("#coverAudioModel"), document.querySelector("#addVocalsModel"), document.querySelector("#addInstrumentalModel"), document.querySelector("#uploadExtendModel"), document.querySelector("#mashupModel"), document.querySelector("#soundsModel")]) {
    if (!modelSelect) continue;
    const previous = modelSelect.value;
    modelSelect.innerHTML = Object.keys(runtimeConfig.models || {}).map(model => `<option value="${escapeHtml(model)}">${escapeHtml(model)}</option>`).join("");
    if (previous && runtimeConfig.models?.[previous]) modelSelect.value = previous;
  }
  applyConfiguredLimits();
}

function setMaxAndCounter(element, counter, max) {
  if (!element || !counter) return;
  if (max > 0) element.setAttribute("maxlength", String(max));
  else element.removeAttribute("maxlength");
  const update = () => {
    const length = element.value.length;
    counter.textContent = max > 0 ? `${length} / ${max}` : `${length}`;
    counter.classList.toggle("warning", max > 0 && length >= Math.floor(max * 0.9));
    counter.classList.toggle("error", max > 0 && length > max);
  };
  element.removeEventListener("input", element._counterUpdate || (() => {}));
  element._counterUpdate = update;
  element.addEventListener("input", update);
  update();
}

function applyConfiguredLimits() {
  const model = document.querySelector("#musicModel")?.value;
  const isCustom = document.querySelector("#musicCustomMode")?.value === "true";
  const limits = runtimeConfig.models?.[model] || Object.values(runtimeConfig.models || {})[0] || {};
  setMaxAndCounter(document.querySelector("#musicPrompt"), document.querySelector("#musicPromptCounter"), isCustom ? Number(limits.custom_prompt || 0) : Number(limits.simple_prompt || 0));
  setMaxAndCounter(document.querySelector("#musicStyle"), document.querySelector("#musicStyleCounter"), Number(limits.style || 0));
  setMaxAndCounter(document.querySelector("#musicTitle"), document.querySelector("#musicTitleCounter"), Number(limits.title || 0));
  setMaxAndCounter(document.querySelector("#lyricsPrompt"), document.querySelector("#lyricsPromptCounter"), Number(runtimeConfig.lyrics_prompt_max_length || 0));
  const extendModel = document.querySelector("#extendModel")?.value || model;
  const extendLimits = runtimeConfig.models?.[extendModel] || limits;
  setMaxAndCounter(document.querySelector("#extendPrompt"), document.querySelector("#extendPromptCounter"), Number(extendLimits.custom_prompt || 0));
  setMaxAndCounter(document.querySelector("#extendStyle"), document.querySelector("#extendStyleCounter"), Number(extendLimits.style || 0));
  setMaxAndCounter(document.querySelector("#extendTitle"), document.querySelector("#extendTitleCounter"), Number(extendLimits.title || 0));

  const vocalsModel = document.querySelector("#addVocalsModel")?.value || model;
  const vocalsLimits = runtimeConfig.models?.[vocalsModel] || limits;
  setMaxAndCounter(document.querySelector("#addVocalsPrompt"), document.querySelector("#addVocalsPromptCounter"), Number(vocalsLimits.custom_prompt || 0));
  setMaxAndCounter(document.querySelector("#addVocalsStyle"), document.querySelector("#addVocalsStyleCounter"), Number(vocalsLimits.style || 0));
  setMaxAndCounter(document.querySelector("#addVocalsTitle"), document.querySelector("#addVocalsTitleCounter"), Number(vocalsLimits.title || 100));

  const instrumentalModel = document.querySelector("#addInstrumentalModel")?.value || model;
  const instrumentalLimits = runtimeConfig.models?.[instrumentalModel] || limits;
  setMaxAndCounter(document.querySelector("#addInstrumentalTags"), document.querySelector("#addInstrumentalTagsCounter"), Number(instrumentalLimits.style || 0));
  setMaxAndCounter(document.querySelector("#addInstrumentalTitle"), document.querySelector("#addInstrumentalTitleCounter"), Number(instrumentalLimits.title || 100));

  const maxStyleLimit = Math.max(0, ...Object.values(runtimeConfig.models || {}).map(item => Number(item.style || 0)));
  setMaxAndCounter(document.querySelector("#boostStyleContent"), document.querySelector("#boostStyleCounter"), maxStyleLimit);
}

function validateWithRuntimeConfig(form) {
  if (form.id === "generateForm") {
    const payload = formToObject(form);
    const limits = runtimeConfig.models?.[payload.model] || {};
    const promptLimit = payload.customMode ? Number(limits.custom_prompt || 0) : Number(limits.simple_prompt || 0);
    const styleLimit = Number(limits.style || 0);
    const titleLimit = Number(limits.title || 0);
    if (promptLimit > 0 && String(payload.prompt || "").length > promptLimit) throw new Error(`Prompt zu lang. Erlaubt: ${promptLimit}, aktuell: ${String(payload.prompt || "").length}.`);
    if (styleLimit > 0 && String(payload.style || "").length > styleLimit) throw new Error(`Style zu lang. Erlaubt: ${styleLimit}, aktuell: ${String(payload.style || "").length}.`);
    if (titleLimit > 0 && String(payload.title || "").length > titleLimit) throw new Error(`Titel zu lang. Erlaubt: ${titleLimit}, aktuell: ${String(payload.title || "").length}.`);
    if (payload.customMode && (!payload.style || !payload.title)) throw new Error("Im Custom-Modus sind Titel und Style erforderlich.");
  }
  if (form.id === "lyricsForm") {
    const limit = Number(runtimeConfig.lyrics_prompt_max_length || 0);
    const prompt = form.querySelector("textarea[name='prompt']")?.value || "";
    if (limit > 0 && prompt.length > limit) throw new Error(`Lyrics-Prompt zu lang. Erlaubt: ${limit}, aktuell: ${prompt.length}.`);
  }
  if (form.id === "extendForm") {
    const payload = formToObject(form);
    if (payload.defaultParamFlag) {
      if (!payload.prompt || !payload.style || !payload.title || !payload.continueAt) throw new Error("Custom-Extension benötigt Prompt, Style, Titel und continueAt.");
    }
  }
  if (form.id === "addVocalsForm") {
    const payload = formToObject(form);
    const limits = runtimeConfig.models?.[payload.model] || {};
    const promptLimit = Number(limits.custom_prompt || 0);
    const styleLimit = Number(limits.style || 0);
    const titleLimit = Number(limits.title || 100);
    if (promptLimit > 0 && String(payload.prompt || "").length > promptLimit) throw new Error(`Prompt zu lang. Erlaubt: ${promptLimit}, aktuell: ${String(payload.prompt || "").length}.`);
    if (styleLimit > 0 && String(payload.style || "").length > styleLimit) throw new Error(`Style zu lang. Erlaubt: ${styleLimit}, aktuell: ${String(payload.style || "").length}.`);
    if (titleLimit > 0 && String(payload.title || "").length > titleLimit) throw new Error(`Titel zu lang. Erlaubt: ${titleLimit}, aktuell: ${String(payload.title || "").length}.`);
  }
  if (form.id === "addInstrumentalForm") {
    const payload = formToObject(form);
    const limits = runtimeConfig.models?.[payload.model] || {};
    const tagsLimit = Number(limits.style || 0);
    const titleLimit = Number(limits.title || 100);
    if (tagsLimit > 0 && String(payload.tags || "").length > tagsLimit) throw new Error(`Tags zu lang. Erlaubt: ${tagsLimit}, aktuell: ${String(payload.tags || "").length}.`);
    if (titleLimit > 0 && String(payload.title || "").length > titleLimit) throw new Error(`Titel zu lang. Erlaubt: ${titleLimit}, aktuell: ${String(payload.title || "").length}.`);
  }
  if (form.id === "boostStyleForm") {
    const maxStyleLimit = Math.max(0, ...Object.values(runtimeConfig.models || {}).map(item => Number(item.style || 0)));
    const content = form.querySelector("textarea[name='content']")?.value || "";
    if (maxStyleLimit > 0 && content.length > maxStyleLimit) throw new Error(`Style-Beschreibung zu lang. Erlaubt: ${maxStyleLimit}, aktuell: ${content.length}.`);
  }
  if (form.id === "personaForm") {
    const payload = formToObject(form);
    if (payload.vocalStart !== undefined && payload.vocalEnd !== undefined) {
      const diff = Number(payload.vocalEnd) - Number(payload.vocalStart);
      if (diff < 10 || diff > 30) throw new Error("Persona-Analysebereich muss zwischen 10 und 30 Sekunden lang sein.");
    }
  }
}

async function loadCredits(renderToOutput = false) {
  const data = await api("/api/credits");
  let credits = null;
  if (typeof data.data === "number") credits = data.data;
  else if (data.data && typeof data.data.remaining_credits === "number") credits = data.data.remaining_credits;
  else if (data.data && typeof data.data.credits === "number") credits = data.data.credits;
  else if (typeof data.remaining_credits === "number") credits = data.remaining_credits;
  else if (typeof data.credits === "number") credits = data.credits;
  if (creditsValue) creditsValue.textContent = credits === null ? "Unbekannt" : credits.toLocaleString("de-DE", { maximumFractionDigits: 2 });
  if (renderToOutput) showCompact({ ...data, credits }, false, "Credits");
}

function setSubmitting(form, submitting) {
  const button = form.querySelector("button[type='submit']");
  if (!button) return;
  button.disabled = submitting;
  button.dataset.originalText ||= button.textContent;
  button.textContent = submitting ? "Bitte warten..." : button.dataset.originalText;
}

async function handleJsonForm(event, path, title) {
  event.preventDefault();
  const form = event.target;
  setSubmitting(form, true);
  try {
    validateWithRuntimeConfig(form);
    const payload = formToObject(form);
    if (form.id === "mashupForm" && typeof payload.upload_url_list === "string") {
      payload.upload_url_list = payload.upload_url_list.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
    }
    const data = await api(path, { method: "POST", body: JSON.stringify(payload) });
    const displayTitle = data?.import_message || title;
    showCompact(data, false, displayTitle);
    switchTab("tab-status");
    await refreshAll(true);
  } catch (error) {
    showCompact({ error: error.message }, true, title);
  } finally {
    setSubmitting(form, false);
  }
}


function saveSeenNotificationIds() {
  localStorage.setItem("seenStatusNotificationIds", JSON.stringify([...seenNotificationIds].slice(-1000)));
}

function notificationTargetPayload(notification) {
  return notification?.target_payload && typeof notification.target_payload === "object" ? notification.target_payload : {};
}

function openNotificationTargetById(notificationId) {
  const notification = cachedNotifications.find(item => String(item.id) === String(notificationId));
  if (!notification) return;
  openNotificationTarget(notification);
}

function openNotificationTarget(notification) {
  const payload = notificationTargetPayload(notification);
  switchTab("tab-archive");
  if (payload.audio_asset_id) {
    const asset = findAudioAsset(payload.audio_asset_id);
    if (asset) {
      const groups = groupedAssetsByProject(sortArchiveAssets(uniqueLibraryAssets(cachedAudioAssets)));
      const group = groups.find(item => item.assets.some(audio => String(audio.id) === String(asset.id)));
      if (group) {
        currentArchiveProjectKey = group.key;
        renderArchive();
        setTimeout(() => document.querySelector(`[data-asset-row="${CSS.escape(String(asset.id))}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 120);
        return;
      }
    }
  }
  if (payload.song_id) {
    openArchiveEntry(`song:${payload.song_id}`);
    return;
  }
  if (notification.task_local_id) {
    switchTab("tab-status");
    document.querySelector(`[data-task-row="${CSS.escape(String(notification.task_local_id))}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

function renderStatusNotifications() {
  const container = document.querySelector("#statusNotifications");
  if (!container) return;
  const rows = cachedNotifications.filter(item => !item.is_deleted);
  if (!rows.length) {
    container.innerHTML = `<div class="empty-state compact-empty">Keine Status-Benachrichtigungen vorhanden.</div>`;
    return;
  }
  container.innerHTML = rows.map(item => {
    const checked = selectedNotifications.has(String(item.id)) ? "checked" : "";
    const done = item.status === "done";
    return `<article class="notification-row ${done ? "done" : "unread"}" data-notification-row="${escapeHtml(item.id)}">
      <label class="notification-check"><input type="checkbox" data-notification-select="${escapeHtml(item.id)}" ${checked}></label>
      <button class="notification-open" type="button" data-open-notification="${escapeHtml(item.id)}">
        <strong>${escapeHtml(item.title)}</strong>
        <span>${escapeHtml(item.message || "")}</span>
        <small>${escapeHtml(formatDate(item.created_at))}${done ? " · erledigt" : ""}</small>
      </button>
      <div class="notification-actions">
        <button class="small-btn" type="button" data-notification-done="${escapeHtml(item.id)}">✓</button>
        <button class="small-btn danger-btn" type="button" data-notification-delete="${escapeHtml(item.id)}">Löschen</button>
      </div>
    </article>`;
  }).join("");
}

async function refreshNotifications() {
  cachedNotifications = await api("/api/notifications?include_done=true").catch(() => []);
  for (const item of cachedNotifications) {
    if (item.status === "unread" && !seenNotificationIds.has(item.id)) {
      seenNotificationIds.add(item.id);
      notify(item.title || "Task fertig", item.severity || "info", { notificationId: item.id });
    }
  }
  saveSeenNotificationIds();
  renderStatusNotifications();
}

async function markNotificationDone(notificationId) {
  await api(`/api/notifications/${encodeURIComponent(notificationId)}/done`, { method: "POST" });
  await refreshNotifications();
}

async function deleteNotification(notificationId) {
  await api(`/api/notifications/${encodeURIComponent(notificationId)}`, { method: "DELETE" });
  selectedNotifications.delete(String(notificationId));
  await refreshNotifications();
}

async function refreshAll(refreshPending = false) {
  if (refreshPending) await api("/api/music/tasks/refresh-pending", { method: "POST" }).catch(error => console.warn(error));
  await Promise.all([refreshTasks(), refreshSongs(), refreshAudioAssets(), refreshPersonas(), refreshLibrary(), refreshProjects(), refreshProductionProfiles(), refreshTrashItems(), refreshNotifications(), loadCredits(false).catch(() => null)]);
  renderArchive();
}

async function refreshTasks() {
  const data = await api("/api/music/tasks");
  for (const task of data || []) {
    const oldStatus = knownTaskStatusMap.get(task.id);
    const newStatus = String(task.status || "").toUpperCase();
    knownTaskStatusMap.set(task.id, newStatus);
  }
  cachedTasks = data;
  tasks.innerHTML = data.length ? data.map(renderTaskCompact).join("") : `<div class="empty-state">Noch keine Tasks vorhanden.</div>`;
  const shouldPoll = data.some(task => isRunningStatus(task.status) && (task.task_id || taskIdFromPayload(task.response_payload)));
  configureAutoRefresh(shouldPoll);
}

async function refreshSongs() {
  cachedSongs = await api("/api/music/songs");
}

async function refreshAudioAssets() {
  cachedAudioAssets = await api("/api/archive/audio");
}

async function refreshProjects() {
  cachedProjects = await api("/api/production/projects").catch(() => []);
}

async function refreshProductionProfiles() {
  cachedProductionProfiles = await api("/api/production/profiles").catch(() => []);
}

async function refreshPersonas() {
  cachedPersonas = await api("/api/music/personas");
  renderPersonaOptions();
  renderPersonaList();
}

function configureAutoRefresh(enabled) {
  if (!enabled && autoRefreshTimer) {
    clearInterval(autoRefreshTimer);
    autoRefreshTimer = null;
    return;
  }
  if (enabled && !autoRefreshTimer) {
    const intervalMs = Math.max(5, Number(runtimeConfig.polling_interval_seconds || 10)) * 1000;
    autoRefreshTimer = setInterval(async () => {
      if (isAutoRefreshing) return;
      isAutoRefreshing = true;
      try { await refreshAll(true); } finally { isAutoRefreshing = false; }
    }, intervalMs);
  }
}

function findAudioAsset(assetId) {
  return cachedAudioAssets.find(asset => String(asset.id) === String(assetId));
}

function setFormField(form, name, value) {
  if (!form || value === null || value === undefined || value === "") return;
  const field = form.querySelector(`[name="${name}"]`);
  if (!field) return;
  field.value = value;
  field.dispatchEvent(new Event("input", { bubbles: true }));
  field.dispatchEvent(new Event("change", { bubbles: true }));
}

function assetAudioUrl(asset) {
  return asset?.source_url || asset?.public_url || "";
}

function prefillArchiveAudioWorkflow(asset, action) {
  const title = asset.title || asset.filename || `Audio ${asset.id}`;
  const audioUrl = assetAudioUrl(asset);

  if (action === "extend") {
    const form = document.querySelector("#extendForm");
    setFormField(form, "audio_id", asset.audio_id || "");
    const alreadyExtended = taskForItem("audio", asset)?.task_type === "extend_music";
    setFormField(form, "title", alreadyExtended ? `${title} Extended Again` : `${title} Extended`);
    if (durationSecondsFromAsset(asset)) setFormField(form, "continueAt", Math.max(1, Math.floor(durationSecondsFromAsset(asset) * 0.75)));
    switchTab("tab-extend");
    notify(alreadyExtended ? "Extended-Version für erneutes Extend übernommen" : "Audio-ID für Extend übernommen");
    return;
  }

  if (action === "cover-song") {
    const form = document.querySelector("#uploadCoverForm");
    setFormField(form, "audio_url", audioUrl);
    setFormField(form, "title", `${title} Cover`);
    switchTab("tab-extend");
    notify("Audio-URL für Cover Song übernommen");
    return;
  }

  if (action === "add-vocals") {
    const form = document.querySelector("#addVocalsForm");
    setFormField(form, "audio_url", audioUrl);
    setFormField(form, "title", `${title} Vocals`);
    switchTab("tab-vocals-style");
    notify("Audio-URL für Add Vocals übernommen");
    return;
  }

  if (action === "add-instrumental") {
    const form = document.querySelector("#addInstrumentalForm");
    setFormField(form, "audio_url", audioUrl);
    setFormField(form, "title", `${title} Instrumental`);
    switchTab("tab-vocals-style");
    notify("Audio-URL für Add Instrumental übernommen");
    return;
  }

  if (action === "persona") {
    const form = document.querySelector("#personaForm");
    setFormField(form, "task_id", asset.suno_task_id || "");
    setFormField(form, "audio_id", asset.audio_id || "");
    setFormField(form, "name", `${title} Persona`);
    setFormField(form, "description", `Persona basierend auf ${title}. Stimme, Stil, Artikulation und musikalische Identität konsistent übernehmen.`);
    switchTab("tab-personas");
    notify("Task-ID und Audio-ID für Persona übernommen");
    return;
  }
}

async function runArchiveAudioQuickAction(assetId, action) {
  const asset = findAudioAsset(assetId);
  if (!asset) {
    showCompact({ error: "Audio-Asset wurde nicht gefunden." }, true, "Archiv-Aktion");
    return;
  }

  if (["extend", "cover-song", "add-vocals", "add-instrumental", "persona"].includes(action)) {
    prefillArchiveAudioWorkflow(asset, action);
    return;
  }

  if (action === "cover-image") {
    const data = await api(`/api/archive/audio/${asset.id}/create-cover-image`, {
      method: "POST",
      body: JSON.stringify({})
    });
    showCompact(data, false, "Cover-Bild-Erstellung gestartet");
    switchTab("tab-status");
    await refreshAll(true);
    return;
  }
}

function getBasicSongStructure() {
  return `[Intro | spoken male vocal | Low Energy]\n\n[Verse 1 | German Male Rap | powerful / dramatic / emotional | Energy: High]\n\n[Chorus | German Male Sung | powerful / emotional | Energy: High]\n\n[Verse 2 | Jamaican Patois Toasting | gritty / rhythmic / confident | Energy: High]\n\n[Bridge | German Male Vocal | atmospheric / melancholic / rising tension | Energy: Medium]\n\n[Final Chorus | German Male Sung | explosive / emotional / wide | Energy: High]\n\n[Outro | spoken male vocal | fading / reflective | Energy: Low]\n`;
}

function activeLyricDraftId() {
  return document.querySelector("#lyricDraftId")?.value || "";
}

function renderVocalTags() {
  const box = document.querySelector("#vocalTagList");
  if (!box) return;
  const grouped = cachedVocalTags.reduce((acc, item) => {
    const key = item.category || "Tags";
    acc[key] ||= [];
    acc[key].push(item);
    return acc;
  }, {});
  box.innerHTML = Object.entries(grouped).map(([category, items]) => `
    <div class="tag-group"><h4>${escapeHtml(category)}</h4>${items.map(item => `
      <button class="tag-pill" type="button" data-insert-vocal-tag="${escapeHtml(item.tag)}">${escapeHtml(item.label)}</button>
    `).join("")}</div>
  `).join("");
}

function renderLyricDrafts() {
  const list = document.querySelector("#lyricDraftList");
  if (!list) return;
  list.innerHTML = cachedLyricDrafts.length ? cachedLyricDrafts.map(draft => `
    <button class="mini-list-item" type="button" data-load-lyric-draft="${escapeHtml(draft.id)}">
      <strong>${escapeHtml(draft.title)}</strong>
      <span>${escapeHtml(draft.status || "draft")} · ${escapeHtml(formatDate(draft.updated_at))}</span>
      <small>${escapeHtml(String(draft.content || "").slice(0, 120))}${String(draft.content || "").length > 120 ? "…" : ""}</small>
    </button>
  `).join("") : `<div class="empty-state">Noch keine Songtexte gespeichert.</div>`;
}

function loadLyricDraftToEditor(id) {
  const draft = cachedLyricDrafts.find(item => String(item.id) === String(id));
  if (!draft) return;
  setFormField(document.querySelector("#lyricDraftForm"), "id", draft.id);
  setFormField(document.querySelector("#lyricDraftForm"), "title", draft.title);
  setFormField(document.querySelector("#lyricDraftForm"), "status", draft.status || "draft");
  setFormField(document.querySelector("#lyricDraftForm"), "language", draft.language || "de");
  setFormField(document.querySelector("#lyricDraftForm"), "tags", draft.tags || "");
  setFormField(document.querySelector("#lyricDraftForm"), "content", draft.content || "");
  renderLyricChapterMap();
  notify("Songtext geladen");
}

function clearLyricDraftEditor() {
  const form = document.querySelector("#lyricDraftForm");
  form?.reset();
  setFormField(form, "id", "");
  setFormField(form, "status", "draft");
  setFormField(form, "language", "de");
  renderLyricChapterMap();
}

async function saveLyricDraft(event) {
  event.preventDefault();
  const form = event.target;
  const payload = formToObject(form);
  const id = payload.id;
  delete payload.id;
  const data = await api(id ? `/api/library/lyrics/${id}` : "/api/library/lyrics", {
    method: id ? "PUT" : "POST",
    body: JSON.stringify(payload)
  });
  setFormField(form, "id", data.id);
  await refreshLyricDrafts();
  notify("Songtext gespeichert");
}

function sendDraftToMusic() {
  const title = document.querySelector("#lyricDraftTitle")?.value || "";
  const content = document.querySelector("#lyricDraftContent")?.value || "";
  if (!content.trim()) {
    notify("Kein Songtext im Editor");
    return;
  }
  const form = document.querySelector("#generateForm");
  setFormField(form, "customMode", "true");
  setFormField(form, "title", title || "Neuer Song");
  setFormField(form, "prompt", content);
  switchTab("tab-music");
  notify("Songtext in Musik Custom übernommen");
}



function detectLyricSectionType(rawLabel = "") {
  const value = String(rawLabel || "").toLowerCase().replace(/[^a-z0-9äöüß\s-]/g, " ").trim();
  if (value.startsWith("intro")) return "intro";
  if (value.startsWith("verse") || value.startsWith("vers") || value.startsWith("strophe")) return "verse";
  if (value.startsWith("hook")) return "hook";
  if (value.startsWith("chorus") || value.startsWith("refrain")) return "chorus";
  if (value.startsWith("pre chorus") || value.startsWith("pre-chorus") || value.startsWith("prehook") || value.startsWith("pre hook")) return "prechorus";
  if (value.startsWith("bridge")) return "bridge";
  if (value.startsWith("outro")) return "outro";
  if (value.startsWith("break") || value.startsWith("drop")) return "breakdown";
  if (value.startsWith("adlib") || value.startsWith("ad-lib") || value.startsWith("ad libs")) return "adlib";
  return "other";
}

function getLyricSectionLabel(type = "other") {
  return {
    intro: "Intro",
    verse: "Verse",
    hook: "Hook",
    chorus: "Chorus",
    prechorus: "Pre-Chorus",
    bridge: "Bridge",
    outro: "Outro",
    breakdown: "Break",
    adlib: "Adlibs",
    other: "Part"
  }[type] || "Part";
}

function extractLyricEnergy(tagText = "") {
  const match = String(tagText || "").match(/energy\s*:\s*([^|\]]+)/i);
  return match ? match[1].trim() : "";
}

function parseLyricChapters(text = "") {
  const source = String(text || "");
  if (!source.trim()) return [];
  const lines = source.split("\n");
  const chapters = [];
  let charIndex = 0;
  lines.forEach((line, index) => {
    const match = line.match(/^\s*\[([^\]\n]{2,260})\]\s*$/);
    if (match) {
      const parts = match[1].split("|").map(part => part.trim()).filter(Boolean);
      const baseLabel = parts[0] || "Part";
      const type = detectLyricSectionType(baseLabel);
      const detail = parts.slice(1).filter(part => !/^energy\s*:/i.test(part)).join(" · ");
      chapters.push({
        id: `${index}-${charIndex}`,
        index: chapters.length + 1,
        line: index,
        charIndex,
        fullTag: `[${match[1].trim()}]`,
        baseLabel,
        type,
        detail,
        energy: extractLyricEnergy(match[1]),
        contentLines: 0,
      });
    }
    charIndex += line.length + 1;
  });
  return chapters.map((chapter, index) => {
    const next = chapters[index + 1];
    const endLine = next ? next.line : lines.length;
    return { ...chapter, contentLines: Math.max(0, endLine - chapter.line - 1) };
  });
}

function jumpToLyricChapter(charIndex = 0, line = 0) {
  const field = document.querySelector("#lyricDraftContent");
  if (!field) return;
  field.focus();
  const position = Math.max(0, Number(charIndex) || 0);
  try { field.setSelectionRange(position, position); } catch { }
  const computed = window.getComputedStyle(field);
  const parsedLineHeight = Number.parseFloat(computed.lineHeight || "");
  const fontSize = Number.parseFloat(computed.fontSize || "16");
  const lineHeight = Number.isFinite(parsedLineHeight) ? parsedLineHeight : fontSize * 1.5;
  field.scrollTop = Math.max(0, (Number(line) || 0) * lineHeight - 80);
}

function renderLyricChapterMap() {
  const box = document.querySelector("#lyricChapterMap");
  const field = document.querySelector("#lyricDraftContent");
  if (!box || !field) return;
  const chapters = parseLyricChapters(field.value || "");
  if (!chapters.length) {
    box.className = "lyric-chapter-map empty";
    box.innerHTML = `<strong>Kapitel-Miniansicht</strong><p class="section-subtitle">Vocal Tags wie [Verse], [Hook], [Chorus] oder [Bridge] werden hier automatisch als Sprungmarken angezeigt.</p>`;
    return;
  }
  box.className = "lyric-chapter-map";
  box.innerHTML = `
    <div class="lyric-chapter-head">
      <div><strong>Kapitel-Miniansicht</strong><p class="section-subtitle">${chapters.length} erkannte Vocal-Tag-Kapitel · Klick springt in den Canvas.</p></div>
      <div class="lyric-chapter-legend">
        ${["intro", "verse", "hook", "chorus", "bridge", "outro"].map(type => `<span class="lyric-chapter-legend-dot lyric-section-${type}">${escapeHtml(getLyricSectionLabel(type))}</span>`).join("")}
      </div>
    </div>
    <div class="lyric-chapter-grid">
      ${chapters.map(chapter => `
        <button class="lyric-chapter-chip lyric-section-${escapeHtml(chapter.type)}" type="button" data-char="${escapeHtml(chapter.charIndex)}" data-line="${escapeHtml(chapter.line)}" title="${escapeHtml(chapter.fullTag)} · Zeile ${chapter.line + 1}">
          <span class="chapter-index">${String(chapter.index).padStart(2, "0")}</span>
          <span class="chapter-main"><span class="chapter-title">${escapeHtml(chapter.baseLabel)}</span>${chapter.detail ? `<span class="chapter-detail">${escapeHtml(chapter.detail)}</span>` : ""}</span>
          <span class="chapter-meta">${chapter.energy ? `<span>${escapeHtml(chapter.energy)}</span>` : ""}<span>Z${chapter.line + 1}</span><span>${chapter.contentLines}L</span></span>
        </button>`).join("")}
    </div>`;
  box.querySelectorAll(".lyric-chapter-chip").forEach(button => {
    button.addEventListener("click", () => jumpToLyricChapter(button.dataset.char, button.dataset.line));
  });
}

function setLyricStudioView(view = "studio") {
  const normalized = view === "focus" ? "focus" : "studio";
  const layout = document.querySelector("#lyricStudioLayout");
  if (!layout) return;
  layout.dataset.view = normalized;
  document.querySelectorAll("[data-lyric-view]").forEach(button => {
    button.classList.toggle("active", button.dataset.lyricView === normalized);
  });
  try { localStorage.setItem("lyricStudioView", normalized); } catch { }
}

function restoreLyricStudioView() {
  let saved = "studio";
  try { saved = localStorage.getItem("lyricStudioView") || "studio"; } catch { }
  setLyricStudioView(saved);
}

async function loadAiConfig() {
  cachedAiConfig = await api("/api/ai-chat/config");
  renderAiProviderModelControls();
}

function renderAiProviderModelControls() {
  const providerSelect = document.querySelector("#aiProviderSelect");
  const modelSelect = document.querySelector("#aiModelSelect");
  if (!providerSelect || !modelSelect || !cachedAiConfig) return;
  const providers = cachedAiConfig.allowed_models || {};
  providerSelect.innerHTML = Object.keys(providers).map(provider => {
    const configured = cachedAiConfig.providers?.[provider]?.configured;
    return `<option value="${escapeHtml(provider)}" ${provider === cachedAiConfig.default_provider ? "selected" : ""}>${escapeHtml(provider)}${configured ? "" : " (kein Key)"}</option>`;
  }).join("");
  renderAiModelOptions();
  renderAiAssistantProfileOptions();
}

function renderAiAssistantProfileOptions() {
  const select = document.querySelector("#aiAssistantProfileSelect");
  if (!select || !cachedAiConfig) return;
  const profiles = cachedAiConfig.assistant_profiles || [];
  const defaultId = cachedAiConfig.default_assistant_profile_id || "";
  select.innerHTML = `<option value="">Standard-Instructions</option>` + profiles.map(profile => `<option value="${escapeHtml(profile.id)}" ${String(profile.id) === String(defaultId) ? "selected" : ""}>${escapeHtml(profile.name)} · ${escapeHtml(profile.provider)} / ${escapeHtml(profile.model)}</option>`).join("");
}

function renderAiModelOptions() {
  const providerSelect = document.querySelector("#aiProviderSelect");
  const modelSelect = document.querySelector("#aiModelSelect");
  if (!providerSelect || !modelSelect || !cachedAiConfig) return;
  const provider = providerSelect.value || cachedAiConfig.default_provider;
  const models = cachedAiConfig.allowed_models?.[provider] || [];
  modelSelect.innerHTML = models.map(model => `<option value="${escapeHtml(model)}" ${model === cachedAiConfig.default_model ? "selected" : ""}>${escapeHtml(model)}</option>`).join("");
}

async function loadAiSessions() {
  cachedAiSessions = await api("/api/ai-chat/sessions");
  renderAiSessionSelect();
}

function renderAiSessionSelect() {
  const select = document.querySelector("#aiSessionSelect");
  if (!select) return;
  select.innerHTML = `<option value="">Keine Session gewählt</option>` + cachedAiSessions.map(session => `<option value="${escapeHtml(session.id)}" ${currentAiSession && Number(currentAiSession.id) === Number(session.id) ? "selected" : ""}>${escapeHtml(session.title)} · ${escapeHtml(session.provider)} / ${escapeHtml(session.model)}</option>`).join("");
}

async function createAiSessionFromEditor() {
  const title = document.querySelector("#lyricDraftTitle")?.value || "Neue KI-Session";
  const content = document.querySelector("#lyricDraftContent")?.value || "";
  const provider = document.querySelector("#aiProviderSelect")?.value || cachedAiConfig?.default_provider || "openai";
  const model = document.querySelector("#aiModelSelect")?.value || cachedAiConfig?.default_model || "GPT-5.4-mini";
  const lyricDraftId = document.querySelector("#lyricDraftId")?.value || null;
  const profileId = document.querySelector("#aiAssistantProfileSelect")?.value || null;
  currentAiSession = await api("/api/ai-chat/sessions", {
    method: "POST",
    body: JSON.stringify({ title, provider, model, assistant_profile_id: profileId ? Number(profileId) : null, lyric_draft_id: lyricDraftId ? Number(lyricDraftId) : null, canvas_content: content })
  });
  await loadAiSessions();
  renderAiChatMessages();
  notify("KI-Session erstellt");
}

async function openAiSession(sessionId) {
  if (!sessionId) {
    currentAiSession = null;
    renderAiChatMessages();
    return;
  }
  currentAiSession = await api(`/api/ai-chat/sessions/${sessionId}`);
  const field = document.querySelector("#lyricDraftContent");
  if (field && currentAiSession.canvas_content !== null && currentAiSession.canvas_content !== undefined) {
    field.value = currentAiSession.canvas_content;
    field.dispatchEvent(new Event("input", { bubbles: true }));
  }
  const providerSelect = document.querySelector("#aiProviderSelect");
  const modelSelect = document.querySelector("#aiModelSelect");
  const profileSelect = document.querySelector("#aiAssistantProfileSelect");
  if (providerSelect) providerSelect.value = currentAiSession.provider;
  renderAiModelOptions();
  if (modelSelect) modelSelect.value = currentAiSession.model;
  if (profileSelect) profileSelect.value = currentAiSession.assistant_profile_id || "";
  renderAiSessionSelect();
  renderAiChatMessages();
}

function renderAiChatMessages() {
  const box = document.querySelector("#aiChatMessages");
  if (!box) return;
  if (!currentAiSession) {
    box.innerHTML = `<div class="empty-state">Keine KI-Session geöffnet.</div>`;
    return;
  }
  const messages = currentAiSession.messages || [];
  box.innerHTML = messages.length ? messages.map(message => `<div class="ai-chat-message ${escapeHtml(message.role)}"><strong>${escapeHtml(message.role === "user" ? "Du" : "KI")}</strong><p>${escapeHtml(message.content)}</p>${message.change_summary ? `<small>${escapeHtml(message.change_summary)}</small>` : ""}</div>`).join("") : `<div class="empty-state">Noch keine Nachrichten in dieser Session.</div>`;
  box.scrollTop = box.scrollHeight;
}

async function sendAiChatMessage(message) {
  if (!currentAiSession) await createAiSessionFromEditor();
  const field = document.querySelector("#lyricDraftContent");
  const canvas = field?.value || "";
  const response = await api(`/api/ai-chat/sessions/${currentAiSession.id}/messages`, {
    method: "POST",
    body: JSON.stringify({ message, canvas_content: canvas, apply_to_canvas: true })
  });
  currentAiSession = response.session;
  if (field && response.canvas_changed) {
    field.value = response.canvas_content || "";
    field.dispatchEvent(new Event("input", { bubbles: true }));
  }
  await loadAiSessions();
  renderAiChatMessages();
  notify(response.canvas_changed ? "KI-Änderung angewendet" : "KI-Antwort erhalten");
}

async function saveAiCanvas(source = "manual") {
  if (!currentAiSession) await createAiSessionFromEditor();
  const content = document.querySelector("#lyricDraftContent")?.value || "";
  currentAiSession = await api(`/api/ai-chat/sessions/${currentAiSession.id}/canvas`, {
    method: "POST",
    body: JSON.stringify({ canvas_content: content, source, change_summary: "Canvas gespeichert" })
  });
  await loadAiSessions();
  renderAiChatMessages();
  notify("Canvas-Stand gespeichert");
}

async function aiCanvasHistory(direction) {
  if (!currentAiSession) {
    notify("Keine KI-Session geöffnet", true);
    return;
  }
  currentAiSession = await api(`/api/ai-chat/sessions/${currentAiSession.id}/${direction}`, { method: "POST" });
  const field = document.querySelector("#lyricDraftContent");
  if (field) {
    field.value = currentAiSession.canvas_content || "";
    field.dispatchEvent(new Event("input", { bubbles: true }));
  }
  renderAiChatMessages();
  notify(direction === "undo" ? "Undo ausgeführt" : "Redo ausgeführt");
}

function renderMusicStyles() {
  const list = document.querySelector("#musicStyleList");
  if (!list) return;
  const query = (document.querySelector("#styleSearch")?.value || "").toLowerCase().trim();
  const styles = cachedMusicStyles.filter(style => !query || [style.name, style.genre, style.tags, style.style_text].join(" ").toLowerCase().includes(query));
  list.innerHTML = styles.length ? styles.map(style => `
    <article class="style-card ${style.is_favorite ? "favorite" : ""}">
      <div class="style-card-head">
        <div><strong>${escapeHtml(style.name)}</strong><div class="result-meta">${style.is_favorite ? `<span class="badge success">Favorit</span>` : ""}${style.genre ? `<span class="badge">${escapeHtml(style.genre)}</span>` : ""}${style.bpm ? `<span class="badge">${escapeHtml(style.bpm)} BPM</span>` : ""}<span class="badge">${escapeHtml(style.usage_count || 0)}x genutzt</span></div></div>
        <div class="result-actions"><button class="small-btn" type="button" data-edit-style="${escapeHtml(style.id)}">Bearbeiten</button><button class="small-btn primary-action" type="button" data-use-style="${escapeHtml(style.id)}" data-target="music">In Musik</button></div>
      </div>
      <div class="style-text-preview">${escapeHtml(style.style_text)}</div>
      <div class="audio-workflow-actions"><button class="small-btn" type="button" data-use-style="${escapeHtml(style.id)}" data-target="extend">In Extend</button><button class="small-btn" type="button" data-use-style="${escapeHtml(style.id)}" data-target="cover">In Cover</button><button class="small-btn" type="button" data-use-style="${escapeHtml(style.id)}" data-target="vocals">In Add Vocals</button><button class="copy-btn" type="button" data-copy="${escapeHtml(style.style_text)}">Kopieren</button><button class="small-btn danger" type="button" data-delete-style="${escapeHtml(style.id)}">Löschen</button></div>
    </article>
  `).join("") : `<div class="empty-state">Noch keine Styles gespeichert.</div>`;
  renderProductionProfiles();
}

function renderProductionProfiles() {
  const list = document.querySelector("#productionProfileList");
  if (!list) return;
  list.innerHTML = cachedProductionProfiles.length ? cachedProductionProfiles.map(profile => `
    <article class="style-card profile-card ${profile.is_favorite ? "favorite" : ""}">
      <div class="style-card-head">
        <div><strong>${escapeHtml(profile.name)}</strong><div class="result-meta">${profile.model ? `<span class="badge">${escapeHtml(profile.model)}</span>` : ""}${profile.is_favorite ? `<span class="badge success">Favorit</span>` : ""}${profile.persona_id ? `<span class="badge">Persona</span>` : ""}</div></div>
        <div class="result-actions"><button class="small-btn primary-action" type="button" data-apply-production-profile="${escapeHtml(profile.id)}">Profil verwenden</button><button class="small-btn danger" type="button" data-delete-production-profile="${escapeHtml(profile.id)}">Löschen</button></div>
      </div>
      ${profile.description ? `<p>${escapeHtml(profile.description)}</p>` : ""}
      ${profile.style ? `<div class="style-text-preview">${escapeHtml(profile.style)}</div>` : ""}
    </article>`).join("") : `<div class="empty-state">Noch keine Produktionsprofile vorhanden.</div>`;
}

function clearStyleEditor() {
  document.querySelector("#musicStyleForm")?.reset();
  setFormField(document.querySelector("#musicStyleForm"), "id", "");
  setFormField(document.querySelector("#musicStyleForm"), "is_favorite", "false");
}

function loadStyleToEditor(id) {
  const style = cachedMusicStyles.find(item => String(item.id) === String(id));
  if (!style) return;
  const form = document.querySelector("#musicStyleForm");
  setFormField(form, "id", style.id);
  setFormField(form, "name", style.name);
  setFormField(form, "genre", style.genre || "");
  setFormField(form, "bpm", style.bpm || "");
  setFormField(form, "style_text", style.style_text || "");
  setFormField(form, "tags", style.tags || "");
  setFormField(form, "description", style.description || "");
  setFormField(form, "is_favorite", style.is_favorite ? "true" : "false");
}

async function saveMusicStyle(event) {
  event.preventDefault();
  const form = event.target;
  const payload = formToObject(form);
  if (payload.bpm !== undefined) payload.bpm = Number(payload.bpm);
  const id = payload.id;
  delete payload.id;
  const data = await api(id ? `/api/library/styles/${id}` : "/api/library/styles", {
    method: id ? "PUT" : "POST",
    body: JSON.stringify(payload)
  });
  setFormField(form, "id", data.id);
  await refreshMusicStyles();
  notify("Style gespeichert");
}

async function useMusicStyle(id, target) {
  const style = cachedMusicStyles.find(item => String(item.id) === String(id));
  if (!style) return;
  await api(`/api/library/styles/${id}/use`, { method: "POST" }).catch(() => null);
  const text = style.style_text || "";
  if (target === "music") { setFormField(document.querySelector("#generateForm"), "style", text); switchTab("tab-music"); }
  if (target === "extend") { setFormField(document.querySelector("#extendForm"), "style", text); switchTab("tab-extend"); }
  if (target === "cover") { setFormField(document.querySelector("#uploadCoverForm"), "style", text); switchTab("tab-extend"); }
  if (target === "vocals") { setFormField(document.querySelector("#addVocalsForm"), "style", text); switchTab("tab-vocals-style"); }
  notify("Style übernommen");
  await refreshMusicStyles();
}

function renderPlaylists() {
  const board = document.querySelector("#playlistBoard");
  if (!board) return;
  board.innerHTML = cachedPlaylists.length ? cachedPlaylists.map(playlist => {
    const items = playlist.items || [];
    return `<article class="playlist-card">
      <div class="playlist-head">
        ${playlist.cover_image_url ? `<img src="${escapeHtml(playlist.cover_image_url)}" alt="Cover" loading="lazy">` : `<span class="playlist-icon">▦</span>`}
        <div><strong>${escapeHtml(playlist.name)}</strong><span>${escapeHtml(playlist.description || "Keine Beschreibung")}</span><small>${items.length} Eintrag${items.length === 1 ? "" : "e"}</small></div>
        <button class="small-btn primary-action" type="button" data-open-playlist-player="${escapeHtml(playlist.id)}">Player</button><button class="small-btn danger" type="button" data-delete-playlist="${escapeHtml(playlist.id)}">Löschen</button>
      </div>
      <div class="playlist-items">${items.length ? items.map(item => renderPlaylistItem(item)).join("") : `<div class="empty-state small-empty">Noch keine Tracks in dieser Playlist.</div>`}</div>
    </article>`;
  }).join("") : `<div class="empty-state">Noch keine Playlists vorhanden.</div>`;
}


let playlistModalState = { playlistId: null, index: 0, loopMode: "none" };

function ensurePlaylistPlayerModal() {
  let modal = document.querySelector("#playlistPlayerModal");
  if (modal) return modal;
  modal = document.createElement("div");
  modal.id = "playlistPlayerModal";
  modal.className = "modal hidden";
  document.body.appendChild(modal);
  return modal;
}

function playlistTracksForModal(playlist) {
  return (playlist?.items || []).map(item => item.audio_asset).filter(asset => asset && assetPlaybackUrl(asset));
}

function renderPlaylistPlayerModal() {
  const modal = ensurePlaylistPlayerModal();
  const playlist = cachedPlaylists.find(item => String(item.id) === String(playlistModalState.playlistId));
  if (!playlist) {
    modal.classList.add("hidden");
    return;
  }
  const tracks = playlistTracksForModal(playlist);
  const current = tracks[playlistModalState.index] || tracks[0];
  if (!tracks.length) {
    modal.innerHTML = `<div class="modal-card"><button class="modal-close" type="button" data-close-playlist-player>×</button><h3>${escapeHtml(playlist.name)}</h3><div class="empty-state small-empty">Keine abspielbaren Tracks.</div></div>`;
    modal.classList.remove("hidden");
    return;
  }
  playlistModalState.index = Math.max(0, Math.min(playlistModalState.index, tracks.length - 1));
  const index = playlistModalState.index;
  const url = assetPlaybackUrl(current);
  modal.innerHTML = `<div class="modal-card playlist-player-modal-card">
    <button class="modal-close" type="button" data-close-playlist-player>×</button>
    <h3>Playlist Player: ${escapeHtml(playlist.name)}</h3>
    <div class="playlist-now-playing">${current.image_url ? `<img src="${escapeHtml(current.image_url)}" alt="Cover">` : '<span>♪</span>'}<div><strong>${escapeHtml(getAssetDisplayTitle(current))}</strong><p>${index + 1}/${tracks.length} · ${escapeHtml(formatDuration(durationSecondsFromAsset(current)))}</p></div></div>
    <audio controls autoplay preload="metadata" src="${escapeHtml(url)}"></audio>
    <div class="button-row wrap"><button class="small-btn" type="button" data-playlist-prev ${index <= 0 ? 'disabled' : ''}>⏮ Zurück</button><button class="small-btn" type="button" data-playlist-next ${index >= tracks.length - 1 ? 'disabled' : ''}>Vor ⏭</button><button class="small-btn ${playlistModalState.loopMode === 'one' ? 'active' : ''}" type="button" data-playlist-loop-one>🔂 Song loop</button><button class="small-btn ${playlistModalState.loopMode === 'all' ? 'active' : ''}" type="button" data-playlist-loop-all>🔁 Playlist loop</button><a class="button-link" href="/api/archive/audio/${escapeHtml(current.id)}/download" download>Download</a></div>
    <div class="playlist-track-list modal-list">${tracks.map((track, trackIndex) => `<button class="playlist-track ${trackIndex === index ? 'active' : ''}" type="button" data-playlist-jump="${escapeHtml(trackIndex)}"><span>${escapeHtml(getAssetDisplayTitle(track))}</span><small>${escapeHtml(formatDuration(durationSecondsFromAsset(track)))}</small></button>`).join('')}</div>
  </div>`;
  const audio = modal.querySelector("audio");
  if (audio) {
    audio.addEventListener("ended", () => {
      if (playlistModalState.loopMode === "one") { audio.currentTime = 0; audio.play().catch(() => null); return; }
      if (playlistModalState.index < tracks.length - 1) { playlistModalState.index += 1; renderPlaylistPlayerModal(); return; }
      if (playlistModalState.loopMode === "all") { playlistModalState.index = 0; renderPlaylistPlayerModal(); }
    });
    audio.play().catch(() => null);
  }
  modal.classList.remove("hidden");
}

function openPlaylistPlayer(playlistId) {
  playlistModalState = { playlistId, index: 0, loopMode: "none" };
  renderPlaylistPlayerModal();
}

function closePlaylistPlayer() {
  const modal = ensurePlaylistPlayerModal();
  const audio = modal.querySelector("audio");
  if (audio) { audio.pause(); audio.removeAttribute("src"); audio.load(); }
  modal.classList.add("hidden");
  modal.innerHTML = "";
}

function renderPlaylistItem(item) {
  const audio = item.audio_asset;
  const song = item.song;
  const title = audio?.title || song?.title || audio?.filename || `Eintrag #${item.id}`;
  const cover = audio?.image_url || song?.cover_image_url || "";
  const url = audio?.public_url || audio?.source_url || song?.audio_url || "";
  return `<div class="playlist-track">
    ${cover ? `<img src="${escapeHtml(cover)}" alt="Cover" loading="lazy">` : `<span class="playlist-track-icon">♪</span>`}
    <div><strong>${escapeHtml(title)}</strong><span>${durationSecondsFromAsset(audio) ? escapeHtml(formatDuration(durationSecondsFromAsset(audio))) : ""}${audio?.audio_id ? ` · ${escapeHtml(audio.audio_id)}` : ""}</span>${url ? `<audio controls preload="metadata" src="${escapeHtml(url)}"></audio>` : ""}</div>
    <button class="small-btn danger" type="button" data-delete-playlist-item="${escapeHtml(item.id)}" data-playlist-id="${escapeHtml(item.playlist_id)}">Entfernen</button>
  </div>`;
}

function renderPlaylistSelectForAsset(asset) {
  if (!cachedPlaylists.length) return `<button class="small-btn" type="button" data-switch-tab="tab-playlists">Playlist anlegen</button>`;
  return `<select class="inline-select" data-playlist-add-select="${escapeHtml(asset.id)}"><option value="">Zur Playlist...</option>${cachedPlaylists.map(playlist => `<option value="${escapeHtml(playlist.id)}">${escapeHtml(playlist.name)}</option>`).join("")}</select>`;
}

async function refreshPlaylists() {
  cachedPlaylists = await api("/api/library/playlists");
  renderPlaylists();
}

async function refreshLyricDrafts() {
  cachedLyricDrafts = await api("/api/library/lyrics");
  renderLyricDrafts();
}

async function refreshMusicStyles() {
  cachedMusicStyles = await api("/api/library/styles");
  renderMusicStyles();
}

async function refreshVocalTags() {
  cachedVocalTags = await api("/api/library/vocal-tags");
  renderVocalTags();
}

async function refreshLibrary() {
  await Promise.all([refreshPlaylists(), refreshLyricDrafts(), refreshMusicStyles(), refreshVocalTags()]);
}

async function refreshTrashItems() {
  cachedTrashItems = await api("/api/library/content/trash").catch(() => []);
}


/* === Finalisierte Produktions-UX: Projekte, Library, Mini-Player, Favoriten === */
function getAssetDisplayTitle(asset) {
  const relatedSong = cachedSongs.find(song => (asset.song_id && song.id === asset.song_id) || (asset.suno_task_id && song.task_id === asset.suno_task_id));
  const task = cachedTasks.find(t => (asset.task_local_id && t.id === asset.task_local_id) || (asset.suno_task_id && t.task_id === asset.suno_task_id));
  const candidate = asset.metadata_json?.candidate || {};
  const title = asset.display_title || asset.title || relatedSong?.title || task?.request_payload?.title || candidate.title;
  if (title && !looksLikeTechnicalName(title)) return title;
  return `Unbenannter Track #${asset.id}`;
}

function operationFromAsset(asset) {
  if (asset.operation_label) return asset.operation_label;
  const task = cachedTasks.find(t => (asset.task_local_id && t.id === asset.task_local_id) || (asset.suno_task_id && t.task_id === asset.suno_task_id));
  const type = task?.task_type || "audio";
  return {
    generate_music: "Generiert",
    extend_music: "Extended",
    upload_and_extend: "Extended",
    upload_and_cover: "Cover Song",
    add_vocals: "Add Vocals",
    add_instrumental: "Add Instrumental",
    generate_mashup: "Mashup",
    generate_sounds: "Sound",
  }[type] || type;
}

function operationFilterKeyFromLabel(label) {
  const value = String(label || "").toLowerCase();
  if (value.includes("extend")) return "extended";
  if (value.includes("cover")) return "cover";
  if (value.includes("vocal")) return "vocals";
  if (value.includes("instrumental")) return "instrumental";
  if (value.includes("mashup")) return "mashup";
  if (value.includes("sound")) return "sounds";
  if (value.includes("gener")) return "generated";
  return "generated";
}

function projectForAsset(asset) {
  return cachedProjects.find(project => String(project.id) === String(asset.project_id));
}

function getAssetProjectTitle(asset) {
  return projectForAsset(asset)?.title || getAssetDisplayTitle(asset).replace(/\s+(Extended|Cover|Final|Remix).*/i, "");
}

function assetSearchText(asset) {
  const task = cachedTasks.find(t => (asset.task_local_id && t.id === asset.task_local_id) || (asset.suno_task_id && t.task_id === asset.suno_task_id));
  return [
    getAssetDisplayTitle(asset), getAssetProjectTitle(asset), operationFromAsset(asset), asset.audio_id, asset.suno_task_id,
    asset.source_url, asset.metadata_json?.candidate?.tags, asset.metadata_json?.candidate?.prompt, task?.request_payload?.prompt, task?.request_payload?.style
  ].filter(Boolean).join(" ").toLowerCase();
}

function archiveRef(type, id) {
  return `${type}:${id}`;
}

function parseArchiveRef(ref) {
  const [type, id] = String(ref || "").split(":");
  return { type, id: Number(id) };
}

function updateArchiveSelectionBar() {
  if (!archiveBulkBar) return;
  const count = selectedArchiveItems.size;
  archiveBulkBar.classList.toggle("hidden", count === 0);
  if (archiveSelectedCount) archiveSelectedCount.textContent = String(count);
  document.querySelectorAll("[data-archive-select]").forEach(input => {
    input.checked = selectedArchiveItems.has(input.dataset.archiveSelect);
  });
}

function statusFilterMatches(asset) {
  const filter = archiveStatus?.value || "all";
  if (filter === "all") return true;
  if (filter === "favorite") return Boolean(asset.is_favorite);
  if (filter === "final") return Boolean(asset.is_final);
  return String(asset.status || "").toLowerCase() === filter;
}

function sortArchiveAssets(assets) {
  const sort = archiveSort?.value || "newest";
  return assets.slice().sort((a, b) => {
    if (sort === "oldest") return new Date(a.created_at || 0) - new Date(b.created_at || 0);
    if (sort === "title") return getAssetDisplayTitle(a).localeCompare(getAssetDisplayTitle(b), "de");
    if (sort === "duration") return durationSecondsFromAsset(b) - durationSecondsFromAsset(a);
    return new Date(b.created_at || 0) - new Date(a.created_at || 0);
  });
}

function renderArchiveSelectionCheckbox(type, id, label = "Inhalt auswählen") {
  const ref = archiveRef(type, id);
  return `<label class="archive-select-wrap" title="${escapeHtml(label)}"><input type="checkbox" data-archive-select="${escapeHtml(ref)}" ${selectedArchiveItems.has(ref) ? "checked" : ""}><span></span></label>`;
}

function filteredLibraryAssets() {
  const query = (archiveSearch?.value || "").toLowerCase().trim();
  const filter = archiveType?.value || "all";
  document.querySelectorAll(".library-filter").forEach(button => button.classList.toggle("active", button.dataset.archiveFilter === filter));
  const filtered = cachedAudioAssets
    .filter(asset => {
      if (filter !== "all" && filter !== "tasks" && operationFilterKeyFromLabel(operationFromAsset(asset)) !== filter) return false;
      if (filter === "tasks") return false;
      if (!statusFilterMatches(asset)) return false;
      return !query || assetSearchText(asset).includes(query);
    });
  return sortArchiveAssets(uniqueLibraryAssets(filtered));
}

function renderWorkflowStepper() {
  return `<div class="workflow-stepper" aria-label="Produktionsfluss">
    <div class="workflow-step done"><span>1</span><strong>Idee</strong></div>
    <div class="workflow-step done"><span>2</span><strong>Lyrics</strong></div>
    <div class="workflow-step active"><span>3</span><strong>Generieren</strong></div>
    <div class="workflow-step"><span>4</span><strong>Auswählen</strong></div>
    <div class="workflow-step"><span>5</span><strong>Bearbeiten</strong></div>
    <div class="workflow-step"><span>6</span><strong>Export</strong></div>
  </div>`;
}

function assetQualityScore(asset) {
  const status = String(asset?.status || "").toLowerCase();
  const source = String(asset?.source_url || "").toLowerCase();
  const contentType = String(asset?.content_type || "").toLowerCase();
  const error = String(asset?.error_message || "").toLowerCase();
  let score = 0;
  if (status === "cached") score += 1000;
  if (status === "remote" || status === "created") score += 500;
  if (status === "failed") score -= 500;
  if (asset?.public_url) score += 100;
  if (asset?.local_path) score += 100;
  if (asset?.source_url) score += 50;
  if (asset?.audio_id) score += 50;
  if (asset?.duration_seconds) score += 25;
  if (asset?.image_url) score += 10;
  if (source.match(/\.(jpg|jpeg|png|webp|gif|avif)(\?|$)/) || contentType.startsWith("image/") || error.includes("image/")) score -= 2000;
  return score;
}

function uniqueLibraryAssets(assets) {
  const bestByKey = new Map();
  for (const asset of assets || []) {
    const source = String(asset?.source_url || "").toLowerCase();
    const contentType = String(asset?.content_type || "").toLowerCase();
    const error = String(asset?.error_message || "").toLowerCase();
    if (source.match(/\.(jpg|jpeg|png|webp|gif|avif)(\?|$)/) || contentType.startsWith("image/") || error.includes("image/")) {
      continue;
    }
    const key = asset.audio_id ? `audio:${asset.audio_id}` : asset.checksum_sha256 ? `sha:${asset.checksum_sha256}` : asset.source_url ? `url:${asset.source_url}` : `id:${asset.id}`;
    const previous = bestByKey.get(key);
    if (!previous || assetQualityScore(asset) > assetQualityScore(previous)) {
      bestByKey.set(key, asset);
    }
  }
  return Array.from(bestByKey.values());
}


function operationSortWeight(label) {
  const key = operationFilterKeyFromLabel(label);
  return { generated: 10, extended: 20, cover: 30, vocals: 40, instrumental: 50, mashup: 60, sounds: 70 }[key] || 90;
}

function operationGroupKey(asset) {
  const task = cachedTasks.find(t => (asset.task_local_id && t.id === asset.task_local_id) || (asset.suno_task_id && t.task_id === asset.suno_task_id));
  const operation = operationFromAsset(asset);
  const taskKey = asset.suno_task_id || asset.task_local_id || task?.id || "manual";
  return `${operationFilterKeyFromLabel(operation)}:${taskKey}`;
}

function groupedAssetsByProject(assets) {
  const groups = new Map();
  for (const asset of uniqueLibraryAssets(assets)) {
    const key = asset.project_id ? `project:${asset.project_id}` : `loose:${getAssetProjectTitle(asset)}`;
    if (!groups.has(key)) {
      const project = projectForAsset(asset);
      groups.set(key, {
        key,
        project,
        title: project?.title || getAssetProjectTitle(asset),
        assets: [],
        latestDate: asset.updated_at || asset.created_at
      });
    }
    const group = groups.get(key);
    group.assets.push(asset);
    if (new Date(asset.updated_at || asset.created_at || 0) > new Date(group.latestDate || 0)) {
      group.latestDate = asset.updated_at || asset.created_at;
    }
  }
  return Array.from(groups.values()).sort((a, b) => new Date(b.latestDate || 0) - new Date(a.latestDate || 0));
}

function groupedAssetsByOperation(assets) {
  const groups = new Map();
  for (const asset of uniqueLibraryAssets(assets)) {
    const key = operationGroupKey(asset);
    const operation = operationFromAsset(asset);
    const task = cachedTasks.find(t => (asset.task_local_id && t.id === asset.task_local_id) || (asset.suno_task_id && t.task_id === asset.suno_task_id));
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        operation,
        operationKey: operationFilterKeyFromLabel(operation),
        task,
        assets: [],
        createdAt: asset.created_at || task?.created_at
      });
    }
    groups.get(key).assets.push(asset);
  }
  return Array.from(groups.values()).sort((a, b) => {
    const opDiff = operationSortWeight(a.operation) - operationSortWeight(b.operation);
    if (opDiff !== 0) return opDiff;
    return new Date(a.createdAt || 0) - new Date(b.createdAt || 0);
  });
}

function variantLabel(index) {
  const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  return `Variante ${letters[index] || index + 1}`;
}

function renderProjectGroup(group) {
  const assets = uniqueLibraryAssets(group.assets);
  const operationGroups = groupedAssetsByOperation(assets);
  const finalAsset = assets.find(a => a.is_final) || assets.find(a => a.is_favorite) || assets[0];
  const cover = group.project?.cover_image_url || finalAsset?.image_url;
  const operationCounts = operationGroups.reduce((acc, op) => {
    const label = libraryGroupLabel(op.operationKey);
    acc[label] = (acc[label] || 0) + op.assets.length;
    return acc;
  }, {});
  const countsText = Object.entries(operationCounts).map(([label, count]) => `${count} ${label}`).join(" · ");
  const finalBadge = assets.some(a => a.is_final) ? '<span class="badge success">Final</span>' : assets.some(a => a.is_favorite) ? '<span class="badge success">Favorit</span>' : '<span class="badge warning">offen</span>';
  const playAssetId = finalAsset?.id || "";
  const key = group.key;
  const durationTotal = assets.reduce((sum, asset) => sum + (durationSecondsFromAsset(asset) || 0), 0);

  return `<article class="library-project-card" data-project-key="${escapeHtml(key)}">
    <div class="project-card-main" title="Cover anklicken zum Abspielen, Titel anklicken für Details">
      <button class="project-cover compact-cover clickable-cover" type="button" data-mini-play="${escapeHtml(playAssetId)}" data-mini-play-scope="library" ${playAssetId ? '' : 'disabled'} title="Archiv ab hier abspielen">
        ${cover ? `<img src="${escapeHtml(cover)}" alt="Cover">` : '<span>▶</span>'}
      </button>
      <div class="project-title-block">
        <div class="song-title-line">
          <button class="project-title-button" type="button" data-open-project-detail="${escapeHtml(key)}" title="Details öffnen">${escapeHtml(group.title)}</button>
          ${finalBadge}
        </div>
        <div class="song-meta-line">
          <span>${assets.length} Variante${assets.length === 1 ? '' : 'n'}</span>
          <span>${operationGroups.length} Vorgang${operationGroups.length === 1 ? '' : 'e'}</span>
          <span>${escapeHtml(countsText || 'Audio')}</span>
          <span>${escapeHtml(formatDate(group.latestDate))}</span>
        </div>
        <div class="project-chip-line">
          ${operationGroups.map(op => `<span class="library-mini-chip operation-${escapeHtml(op.operationKey)}">${escapeHtml(libraryGroupLabel(op.operationKey))}: ${op.assets.length}</span>`).join('')}
          ${durationTotal ? `<span class="library-mini-chip">Gesamt ${escapeHtml(formatDuration(durationTotal))}</span>` : ''}
        </div>
      </div>
    </div>
    <div class="project-preview-actions">
      ${playAssetId ? `<button class="small-btn primary-action" type="button" data-mini-play="${escapeHtml(playAssetId)}" data-mini-play-scope="library">▶ Abspielen</button>` : ''}
      ${group.project?.id ? `<button class="small-btn" type="button" data-edit-title-type="project" data-edit-title-id="${escapeHtml(group.project.id)}" data-current-title="${escapeHtml(group.title)}">Titel</button>` : ''}
      <button class="small-btn" type="button" data-create-project-from-asset="${escapeHtml(finalAsset?.id || '')}">Projekt</button>
    </div>
  </article>`;
}

function findProjectGroupByKey(projectKey, useFiltered = false) {
  const assets = useFiltered ? filteredLibraryAssets() : sortArchiveAssets(uniqueLibraryAssets(cachedAudioAssets));
  return groupedAssetsByProject(assets).find(group => String(group.key) === String(projectKey)) || null;
}

function projectDetailNeighborKey(projectKey, direction) {
  let groups = groupedAssetsByProject(filteredLibraryAssets());
  let index = groups.findIndex(group => String(group.key) === String(projectKey));
  if (index < 0) {
    groups = groupedAssetsByProject(sortArchiveAssets(uniqueLibraryAssets(cachedAudioAssets)));
    index = groups.findIndex(group => String(group.key) === String(projectKey));
  }
  if (index < 0) return null;
  return groups[index + direction]?.key || null;
}

function renderProjectDetailHeader(group, assets, operationGroups, finalAsset, projectKey) {
  const cover = group.project?.cover_image_url || finalAsset?.image_url;
  const countFinal = assets.filter(a => a.is_final).length;
  const countFav = assets.filter(a => a.is_favorite).length;
  const previousKey = projectDetailNeighborKey(projectKey, -1);
  const nextKey = projectDetailNeighborKey(projectKey, 1);
  return `<div class="project-detail-hero">
    <div class="project-detail-nav-row">
      <button class="small-btn secondary" type="button" data-back-to-library>← Zur Library</button>
      <div class="project-detail-nav-actions">
        <button class="small-btn" type="button" data-project-detail-nav="${escapeHtml(previousKey || '')}" ${previousKey ? '' : 'disabled'}>← Vorheriger Song</button>
        <button class="small-btn" type="button" data-project-detail-nav="${escapeHtml(nextKey || '')}" ${nextKey ? '' : 'disabled'}>Nächster Song →</button>
      </div>
    </div>
    <div class="project-detail-top">
      <div class="project-detail-cover">${cover ? `<img src="${escapeHtml(cover)}" alt="Cover">` : '<span>♪</span>'}</div>
      <div class="project-detail-title-block">
        <span class="eyebrow">Projekt / Song</span>
        <h2>${escapeHtml(group.title)}</h2>
        <div class="song-meta-line">
          <span>${assets.length} Variante${assets.length === 1 ? '' : 'n'}</span>
          <span>${operationGroups.length} Vorgang${operationGroups.length === 1 ? '' : 'e'}</span>
          <span>${countFav} Favorit</span>
          <span>${countFinal} Final</span>
          <span>Zuletzt ${escapeHtml(formatDate(group.latestDate))}</span>
        </div>
        <div class="project-detail-actions">
          ${finalAsset ? `<button class="small-btn primary-action" type="button" data-mini-play="${escapeHtml(finalAsset.id)}">▶ Beste Version abspielen</button>` : ''}
          ${finalAsset ? `<button class="small-btn" type="button" data-reuse-prompt-asset="${escapeHtml(finalAsset.id)}">Reuse Prompt</button>` : ''}
          ${group.project?.id ? `<button class="small-btn" type="button" data-edit-title-type="project" data-edit-title-id="${escapeHtml(group.project.id)}" data-current-title="${escapeHtml(group.title)}">Projekttitel bearbeiten</button>` : ''}
        </div>
      </div>
    </div>
  </div>`;
}

function renderVariantCompare(assets) {
  const variants = assets.slice(0, 4);
  if (variants.length < 2) return '';
  return `<section class="project-detail-section variant-compare-section">
    <div class="section-heading-row"><h3>Variantenvergleich</h3><span>${variants.length} Varianten</span></div>
    <div class="variant-compare-grid">
      ${variants.map((asset, index) => {
        const title = getAssetDisplayTitle(asset);
        return `<article class="variant-compare-card">
          <div class="variant-compare-cover">${asset.image_url ? `<img src="${escapeHtml(asset.image_url)}" alt="Cover">` : '<span>♪</span>'}</div>
          <div class="variant-compare-info">
            <strong>${escapeHtml(asset.version_label || variantLabel(index))}</strong>
            <span>${escapeHtml(title)}</span>
            <small>${escapeHtml(formatDuration(durationSecondsFromAsset(asset)))} · ${escapeHtml(operationFromAsset(asset))}</small>
          </div>
          <div class="variant-compare-actions">
            <button class="small-btn primary-action" type="button" data-mini-play="${escapeHtml(asset.id)}">▶</button>
            <button class="small-btn icon-btn ${asset.is_favorite ? 'active' : ''}" type="button" data-mark-favorite="${escapeHtml(asset.id)}">⭐</button>
            <button class="small-btn icon-btn ${asset.is_final ? 'active' : ''}" type="button" data-mark-final="${escapeHtml(asset.id)}">✅</button>
          </div>
        </article>`;
      }).join('')}
    </div>
  </section>`;
}

function renderProjectDetailOperationGroup(group) {
  const label = libraryGroupLabel(group.operationKey);
  const taskId = group.task?.task_id || group.assets[0]?.suno_task_id || "";
  const created = group.createdAt || group.assets[0]?.created_at;
  return `<section class="project-detail-section operation-detail-block operation-${escapeHtml(group.operationKey)}">
    <div class="section-heading-row">
      <div><h3>${escapeHtml(label)}</h3><p>${group.assets.length} Variante${group.assets.length === 1 ? '' : 'n'} aus diesem Vorgang</p></div>
      <div class="song-meta-line">${taskId ? `<span>Task ${escapeHtml(shortId(taskId))}</span>` : ''}<span>${escapeHtml(formatDate(created))}</span></div>
    </div>
    <div class="detail-variant-list">
      ${group.assets.map((asset, index) => renderProjectDetailVariant(asset, index, group)).join('')}
    </div>
  </section>`;
}

function renderProjectDetailVariant(asset, index = 0, group = null) {
  const title = getAssetDisplayTitle(asset);
  const operation = operationFromAsset(asset);
  const operationKey = operationFilterKeyFromLabel(operation);
  const task = cachedTasks.find(t => (asset.task_local_id && t.id === asset.task_local_id) || (asset.suno_task_id && t.task_id === asset.suno_task_id));
  const prompt = task?.request_payload?.prompt || asset.metadata_json?.candidate?.prompt || "";
  const tags = asset.metadata_json?.candidate?.tags || task?.request_payload?.style || "";
  const lyrics = libraryLyricsForAudio(asset);
  const downloadUrl = asset.status === "cached" ? `/api/archive/audio/${asset.id}/download` : asset.source_url;
  const label = asset.version_label || variantLabel(index);
  const parent = parentAudioInfoForAsset(asset);

  return `<article class="detail-variant-card" data-asset-row="${escapeHtml(asset.id)}">
    <header class="detail-variant-header">
      <div class="detail-variant-cover">${asset.image_url ? `<img src="${escapeHtml(asset.image_url)}" alt="Cover">` : '<span>♪</span>'}</div>
      <div class="detail-variant-title">
        <div class="track-title-line"><strong>${escapeHtml(label)}</strong><h4>${escapeHtml(title)}</h4>${asset.is_favorite ? '<span class="badge success">Favorit</span>' : ''}${asset.is_final ? '<span class="badge success">Final</span>' : ''}</div>
        <div class="song-meta-line"><span>${escapeHtml(operation)}</span><span>${escapeHtml(formatDuration(durationSecondsFromAsset(asset)))}</span><span>${escapeHtml(statusLabel(asset.status))}</span><span>${escapeHtml(formatDate(asset.created_at))}</span></div>
      </div>
      <div class="detail-variant-actions">
        <button class="small-btn primary-action" type="button" data-mini-play="${escapeHtml(asset.id)}">▶ Abspielen</button>
        <button class="small-btn icon-btn ${asset.is_favorite ? 'active' : ''}" type="button" data-mark-favorite="${escapeHtml(asset.id)}" title="Favorit">⭐</button>
        <button class="small-btn icon-btn ${asset.is_final ? 'active' : ''}" type="button" data-mark-final="${escapeHtml(asset.id)}" title="Final">✅</button>
        <button class="small-btn" type="button" data-reuse-prompt-asset="${escapeHtml(asset.id)}">Reuse Prompt</button>
        <button class="small-btn" type="button" data-edit-title-type="audio" data-edit-title-id="${escapeHtml(asset.id)}" data-current-title="${escapeHtml(title)}">Titel</button>
      </div>
    </header>

    <div class="variant-detail-grid always-visible-details">
      <section class="song-detail-panel"><h4>Workflow</h4><div class="workflow-mini-grid"><div><span>Typ</span><strong>${escapeHtml(operation)}</strong></div><div><span>Status</span><strong>${escapeHtml(statusLabel(asset.status))}</strong></div><div><span>Audio-ID</span><code>${escapeHtml(asset.audio_id || '-')}</code></div><div><span>Task-ID</span><code>${escapeHtml(asset.suno_task_id || task?.task_id || '-')}</code></div></div>${operationKey === 'extended' || parent.parentAudioId ? `<div class="lineage-box"><span class="lineage-label">Entstanden aus</span>${parent.parentAudioId ? `<code>${escapeHtml(parent.parentAudioId)}</code>` : '<span>Quelle nicht gespeichert</span>'}</div>` : ''}</section>
      <section class="song-detail-panel"><h4>Aktionen</h4><div class="context-action-grid">${renderAudioActionButtons(asset)}</div><div class="detail-link-actions"><a class="button-link" href="${escapeHtml(downloadUrl)}" download>Download</a>${asset.source_url ? `<a class="button-link" href="${escapeHtml(asset.source_url)}" target="_blank" rel="noopener noreferrer">Suno-Quelle</a>` : ''}<button class="copy-btn" type="button" data-copy="${escapeHtml(asset.audio_id || '')}">Audio-ID kopieren</button></div></section>
      ${renderGenerationOptionsPanel(asset)}
      ${tags ? `<section class="song-detail-panel wide-panel"><div class="archive-section-head"><h4>Style</h4><button class="copy-btn" type="button" data-copy="${escapeHtml(tags)}">Kopieren</button></div><div class="generated-text compact-text">${escapeHtml(tags)}</div></section>` : ''}
      ${prompt ? `<section class="song-detail-panel wide-panel"><div class="archive-section-head"><h4>Prompt / Lyrics-Vorgabe</h4><div class="button-row compact-row"><button class="copy-btn" type="button" data-copy="${escapeHtml(prompt)}">Kopieren</button><button class="small-btn" type="button" data-save-lyrics-from-asset="${escapeHtml(asset.id)}">Unter Songtexte speichern</button></div></div><div class="generated-text compact-text">${escapeHtml(prompt)}</div></section>` : ''}
      ${lyrics ? `<section class="song-detail-panel wide-panel"><div class="archive-section-head"><h4>Lyrics</h4><div class="button-row compact-row"><button class="copy-btn" type="button" data-copy="${escapeHtml(lyrics)}">Kopieren</button><button class="small-btn" type="button" data-save-lyrics-from-asset="${escapeHtml(asset.id)}">Unter Songtexte speichern</button></div></div><div class="generated-text compact-text">${escapeHtml(lyrics)}</div></section>` : ''}
      <details class="details technical-details wide-panel"><summary>Technische Rohdaten</summary><pre>${escapeHtml(JSON.stringify(asset, null, 2))}</pre></details>
    </div>
  </article>`;
}


function reusePromptFromAsset(assetId) {
  const asset = cachedAudioAssets.find(item => String(item.id) === String(assetId));
  if (!asset) {
    notify("Audio wurde nicht gefunden.", true);
    return;
  }
  const task = cachedTasks.find(t => (asset.task_local_id && t.id === asset.task_local_id) || (asset.suno_task_id && t.task_id === asset.suno_task_id));
  const prompt = task?.request_payload?.prompt || asset.metadata_json?.candidate?.prompt || libraryLyricsForAudio(asset) || "";
  const style = asset.metadata_json?.candidate?.tags || task?.request_payload?.style || "";
  const title = getAssetDisplayTitle(asset) || task?.request_payload?.title || "";
  const form = document.querySelector("#generateForm");
  if (!form) return;
  setFormField(form, "title", title);
  setFormField(form, "prompt", prompt);
  setFormField(form, "style", style);
  setFormField(form, "customMode", "true");
  applyConfiguredLimits();
  switchTab("tab-music");
  notify("Prompt und Style wurden in Musik übernommen.");
}

function renderProjectDetailPage(projectKey) {
  const group = findProjectGroupByKey(projectKey, false);
  if (!group) {
    currentArchiveProjectKey = null;
    renderArchive();
    notify("Projekt wurde nicht gefunden.", true);
    return;
  }
  const assets = uniqueLibraryAssets(group.assets);
  const operationGroups = groupedAssetsByOperation(assets);
  const finalAsset = assets.find(a => a.is_final) || assets.find(a => a.is_favorite) || assets[0];
  archiveList.innerHTML = `<div class="project-detail-page">
    ${renderProjectDetailHeader(group, assets, operationGroups, finalAsset, projectKey)}
    ${renderVariantCompare(assets)}
    <div class="project-operation-detail-list">${operationGroups.map(renderProjectDetailOperationGroup).join('')}</div>
  </div>`;
  lastVisibleArchiveRefs = assets.map(asset => archiveRef("audio", asset.id));
  updateArchiveSelectionBar();
  if (archiveDetail) archiveDetail.classList.add("visually-hidden");
}

function renderOperationGroup(group) {
  const label = libraryGroupLabel(group.operationKey);
  const taskId = group.task?.task_id || group.assets[0]?.suno_task_id || "";
  const created = group.createdAt || group.assets[0]?.created_at;
  return `<section class="operation-block operation-${escapeHtml(group.operationKey)}">
    <header class="operation-header">
      <div><strong>${escapeHtml(label)}</strong><span>${group.assets.length} Variante${group.assets.length === 1 ? '' : 'n'}</span></div>
      <div class="song-meta-line">${taskId ? `<span>Task ${escapeHtml(shortId(taskId))}</span>` : ''}<span>${escapeHtml(formatDate(created))}</span></div>
    </header>
    <div class="operation-track-list">
      ${group.assets.map((asset, index) => renderFinalLibraryTrack(asset, index)).join("")}
    </div>
  </section>`;
}

function renderFinalLibraryTrack(asset, index = 0) {
  const title = getAssetDisplayTitle(asset);
  const operation = operationFromAsset(asset);
  const operationKey = operationFilterKeyFromLabel(operation);
  const label = asset.version_label || variantLabel(index);
  return `<article class="suno-track-row compact-track operation-${escapeHtml(operationKey)}" data-asset-row="${escapeHtml(asset.id)}">
    <div class="track-left">
      ${renderArchiveSelectionCheckbox("audio", asset.id, "Audio auswählen")}
      <button class="play-cover tiny-cover" type="button" data-mini-play="${escapeHtml(asset.id)}">${asset.image_url ? `<img src="${escapeHtml(asset.image_url)}" alt="Cover">` : '<span>▶</span>'}</button>
      <div class="track-title-wrap">
        <div class="track-title-line"><strong>${escapeHtml(label)}</strong><span>${escapeHtml(title)}</span>${asset.is_favorite ? '<span class="badge success">Favorit</span>' : ''}${asset.is_final ? '<span class="badge success">Final</span>' : ''}</div>
        <div class="song-meta-line"><span>${escapeHtml(operation)}</span><span>${escapeHtml(formatDuration(durationSecondsFromAsset(asset)))}</span><span>${asset.audio_id ? `Audio ${escapeHtml(shortId(asset.audio_id))}` : 'Audio-ID fehlt'}</span></div>
      </div>
    </div>
    <div class="track-center-actions">
      <button class="small-btn primary-action" type="button" data-mini-play="${escapeHtml(asset.id)}">▶</button>
      <button class="small-btn icon-btn ${asset.is_favorite ? 'active' : ''}" type="button" data-mark-favorite="${escapeHtml(asset.id)}" title="Favorit">⭐</button>
      <button class="small-btn icon-btn ${asset.is_final ? 'active' : ''}" type="button" data-mark-final="${escapeHtml(asset.id)}" title="Als final markieren">✅</button>
      <button class="small-btn" type="button" data-audio-action="extend" data-asset-id="${escapeHtml(asset.id)}" ${asset.audio_id ? '' : 'disabled'}>${operationKey === 'extended' ? 'Nochmal extenden' : 'Extend'}</button>
      <button class="small-btn" type="button" data-audio-action="cover-song" data-asset-id="${escapeHtml(asset.id)}">Cover</button>
    </div>
  </article>`;
}

function renderTaskLibraryFallback() {
  const query = (archiveSearch?.value || "").toLowerCase().trim();
  const rows = cachedTasks
    .slice()
    .filter(task => !query || [task.task_type, task.status, task.task_id, JSON.stringify(task.request_payload || {})].join(" ").toLowerCase().includes(query))
    .sort((a,b)=>new Date(b.created_at||0)-new Date(a.created_at||0))
    .map(task => `<article class="suno-track-row task-row"><div class="track-left">${renderArchiveSelectionCheckbox("task", task.id, "Task auswählen")}<div class="song-cover-slot no-cover"><span>⚙</span></div><div><strong>${escapeHtml(task.task_type)}</strong><div class="song-meta-line"><span>${escapeHtml(statusLabel(task.status))}</span><span>${escapeHtml(formatDate(task.created_at))}</span><span>${escapeHtml(shortId(task.task_id || ''))}</span></div></div></div><div class="track-player empty-player">Task</div><div class="track-actions"><button class="small-btn" type="button" data-refresh-task="${escapeHtml(task.id)}">Status</button><button class="small-btn" type="button" data-edit-title-type="task" data-edit-title-id="${escapeHtml(task.id)}" data-current-title="${escapeHtml(task.request_payload?.title || task.task_type || 'Task')}">Titel</button><button class="copy-btn" type="button" data-copy="${escapeHtml(JSON.stringify(task, null, 2))}">Kopieren</button><button class="small-btn danger-btn" type="button" data-delete-content-type="task" data-delete-content-id="${escapeHtml(task.id)}">Löschen</button></div></article>`).join("");
  return rows || '<div class="empty-state">Keine Tasks vorhanden.</div>';
}


function renderTrashLibrary() {
  const query = (archiveSearch?.value || "").toLowerCase().trim();
  const rows = cachedTrashItems
    .filter(item => !query || [item.title, item.type, item.deleted_reason].join(" ").toLowerCase().includes(query))
    .map(item => {
      const ref = archiveRef(item.type, item.id);
      return `<article class="suno-track-row trash-row">
        <div class="track-left">
          ${renderArchiveSelectionCheckbox(item.type, item.id, "Papierkorb-Eintrag auswählen")}
          <div class="song-cover-slot no-cover"><span>🗑️</span></div>
          <div>
            <strong>${escapeHtml(item.title || `${item.type} #${item.id}`)}</strong>
            <div class="song-meta-line"><span>${escapeHtml(item.type)}</span><span>gelöscht: ${escapeHtml(formatDate(item.deleted_at))}</span>${item.deleted_reason ? `<span>${escapeHtml(item.deleted_reason)}</span>` : ""}</div>
          </div>
        </div>
        <div class="track-player empty-player">Papierkorb</div>
        <div class="track-actions">
          <button class="small-btn secondary" type="button" data-restore-content-type="${escapeHtml(item.type)}" data-restore-content-id="${escapeHtml(item.id)}">Wiederherstellen</button>
          <button class="small-btn danger-btn" type="button" data-purge-content-type="${escapeHtml(item.type)}" data-purge-content-id="${escapeHtml(item.id)}">Endgültig löschen</button>
        </div>
      </article>`;
    }).join("");
  lastVisibleArchiveRefs = cachedTrashItems.map(item => archiveRef(item.type, item.id));
  archiveList.innerHTML = renderWorkflowStepper() + `
    <div class="library-command-bar">
      <div class="library-summary-bar final-summary"><div><strong>${cachedTrashItems.length}</strong><span>im Papierkorb</span></div></div>
      <div class="library-command-actions"><button class="secondary small-btn" type="button" id="btnArchiveRefreshTrash">Papierkorb aktualisieren</button></div>
    </div>
    ${rows || '<div class="empty-state">Papierkorb ist leer.</div>'}`;
  updateArchiveSelectionBar();
}


function cssEscapeValue(value) {
  if (window.CSS && typeof window.CSS.escape === "function") return CSS.escape(String(value));
  return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
}

function captureLibraryOpenState() {
  const openProjects = Array.from(document.querySelectorAll("details.library-project[open]")).map(item => item.dataset.projectKey).filter(Boolean);
  const openTracks = Array.from(document.querySelectorAll("details.track-details[open]")).map(item => item.closest("[data-asset-row]")?.dataset.assetRow).filter(Boolean);
  for (const key of openProjects) persistedOpenProjects.add(String(key));
  for (const id of openTracks) persistedOpenTracks.add(String(id));
  return {
    openProjects: new Set([...persistedOpenProjects, ...openProjects]),
    openTracks: new Set([...persistedOpenTracks, ...openTracks]),
  };
}

function restoreLibraryOpenState(state) {
  const mergedProjects = new Set([...(state?.openProjects || []), ...persistedOpenProjects]);
  const mergedTracks = new Set([...(state?.openTracks || []), ...persistedOpenTracks]);

  for (const key of mergedProjects) {
    const project = document.querySelector(`details.library-project[data-project-key="${cssEscapeValue(key)}"]`);
    if (project) project.open = true;
  }
  for (const id of mergedTracks) {
    const row = document.querySelector(`[data-asset-row="${cssEscapeValue(id)}"]`);
    const project = row?.closest("details.library-project");
    const details = row?.querySelector("details.track-details");
    if (project) project.open = true;
    if (details) details.open = true;
  }
}

function rememberLibraryToggle(target) {
  if (!target || !(target instanceof HTMLDetailsElement)) return;

  if (target.classList.contains("library-project")) {
    const key = target.dataset.projectKey;
    if (!key) return;
    if (target.open) persistedOpenProjects.add(String(key));
    else persistedOpenProjects.delete(String(key));
    return;
  }

  if (target.classList.contains("track-details")) {
    const id = target.closest("[data-asset-row]")?.dataset.assetRow;
    if (!id) return;
    if (target.open) persistedOpenTracks.add(String(id));
    else persistedOpenTracks.delete(String(id));
  }
}

function normalizeMediaUrl(url) {
  const value = String(url || "").trim();
  if (!value) return "";
  if (value.startsWith("http://") || value.startsWith("https://") || value.startsWith("/")) return value;
  return `/${value}`;
}

function isControlClick(event) {
  return Boolean(event.target.closest("button, a, input, select, textarea, label, audio, summary"));
}

function renderLyricsArchiveOnly() {
  const query = (archiveSearch?.value || "").toLowerCase().trim();
  const drafts = cachedLyricDrafts.filter(draft => {
    const haystack = [draft.title, draft.status, draft.language, draft.tags, draft.content].filter(Boolean).join(" ").toLowerCase();
    return !query || haystack.includes(query);
  });
  lastVisibleArchiveRefs = drafts.map(draft => archiveRef("lyric", draft.id));
  archiveList.innerHTML = `
    ${renderWorkflowStepper()}
    <div class="library-command-bar">
      <div class="library-summary-bar final-summary">
        <div><strong>${drafts.length}</strong><span>Songtexte</span></div>
        <div><strong>${drafts.filter(d => d.status === "ready").length}</strong><span>Bereit</span></div>
        <div><strong>${drafts.filter(d => d.status === "draft").length}</strong><span>Entwürfe</span></div>
        <div><strong>${drafts.filter(d => d.status === "archived").length}</strong><span>Archiviert</span></div>
      </div>
      <div class="library-command-actions">
        <button class="secondary small-btn" type="button" data-switch-tab="tab-lyric-editor">Neuen Songtext erstellen</button>
      </div>
    </div>
    <div class="lyrics-library-grid">
      ${drafts.map(draft => `<article class="library-project-card lyric-only-card" data-load-lyric-draft="${escapeHtml(draft.id)}" data-switch-tab="tab-lyric-editor">
        <div class="project-main">
          <div class="project-cover placeholder-cover">📝</div>
          <div class="project-info">
            <h3>${escapeHtml(draft.title)}</h3>
            <div class="project-meta"><span>${escapeHtml(draft.status || "draft")}</span><span>${escapeHtml(draft.language || "-")}</span><span>${escapeHtml(formatDate(draft.updated_at))}</span></div>
            <p>${escapeHtml(String(draft.content || "").slice(0, 220))}${String(draft.content || "").length > 220 ? "…" : ""}</p>
          </div>
        </div>
        <div class="project-actions"><button class="small-btn" type="button" data-load-lyric-draft="${escapeHtml(draft.id)}" data-switch-tab="tab-lyric-editor">Bearbeiten</button><button class="small-btn" type="button" data-send-lyric-to-music="${escapeHtml(draft.id)}">Musik erzeugen</button><button class="small-btn danger" type="button" data-delete-lyric-draft="${escapeHtml(draft.id)}">Löschen</button></div>
      </article>`).join("") || `<div class="empty-state">Keine Songtexte gefunden.</div>`}
    </div>`;
  updateArchiveSelectionBar();
  if (archiveDetail) archiveDetail.classList.add("visually-hidden");
}

function sendLyricDraftByIdToMusic(id) {
  const draft = cachedLyricDrafts.find(item => String(item.id) === String(id));
  if (!draft) return;
  const form = document.querySelector("#generateForm");
  setFormField(form, "customMode", "true");
  setFormField(form, "title", draft.title || "Neuer Song");
  setFormField(form, "prompt", draft.content || "");
  switchTab("tab-music");
  notify("Songtext in Musik Custom übernommen");
}

function renderArchive() {
  if (!archiveList) return;
  const openState = captureLibraryOpenState();
  const filter = archiveType?.value || "all";
  if (filter === "trash") {
    currentArchiveProjectKey = null;
    renderTrashLibrary();
    restoreLibraryOpenState(openState);
    return;
  }
  if (filter === "lyrics") {
    currentArchiveProjectKey = null;
    renderLyricsArchiveOnly();
    restoreLibraryOpenState(openState);
    return;
  }
  if (filter === "tasks") {
    currentArchiveProjectKey = null;
    const visibleTasks = cachedTasks
      .filter(task => {
        const query = (archiveSearch?.value || "").toLowerCase().trim();
        return !query || [task.task_type, task.status, task.task_id, JSON.stringify(task.request_payload || {})].join(" ").toLowerCase().includes(query);
      })
      .map(task => archiveRef("task", task.id));
    lastVisibleArchiveRefs = visibleTasks;
    archiveList.innerHTML = renderWorkflowStepper() + renderTaskLibraryFallback();
    updateArchiveSelectionBar();
    restoreLibraryOpenState(openState);
    return;
  }
  if (currentArchiveProjectKey) {
    renderProjectDetailPage(currentArchiveProjectKey);
    return;
  }
  const assets = filteredLibraryAssets();
  lastVisibleArchiveRefs = assets.map(asset => archiveRef("audio", asset.id));
  const groups = groupedAssetsByProject(assets);
  const countFinal = assets.filter(a => a.is_final).length;
  const countFav = assets.filter(a => a.is_favorite).length;
  archiveList.innerHTML = `
    ${renderWorkflowStepper()}
    <div class="library-command-bar">
      <div class="library-summary-bar final-summary">
        <div><strong>${assets.length}</strong><span>Tracks</span></div>
        <div><strong>${groups.length}</strong><span>Projekte</span></div>
        <div><strong>${countFav}</strong><span>Favoriten</span></div>
        <div><strong>${countFinal}</strong><span>Final</span></div>
      </div>
      <div class="library-command-actions">
        <button class="secondary small-btn" type="button" data-auto-group-projects>Auto-Projekte</button>
        <button class="secondary small-btn" type="button" data-switch-tab="tab-lyric-editor">Lyrics schreiben</button>
        <button class="secondary small-btn" type="button" data-switch-tab="tab-styles">Profile/Styles</button>
      </div>
    </div>
    ${groups.map(renderProjectGroup).join("") || '<div class="empty-state">Keine passenden Tracks gefunden.</div>'}`;
  updateArchiveSelectionBar();
  restoreLibraryOpenState(openState);
  if (archiveDetail) archiveDetail.classList.add("visually-hidden");
}

function openArchiveEntry(ref) {
  if (!ref) return;
  const id = String(ref).split(":").pop();
  let row = document.querySelector(`[data-asset-row="${cssEscapeValue(id)}"]`) || document.querySelector(`[data-open-archive="${cssEscapeValue(String(ref))}"]`);
  if (!row) {
    renderArchive();
    row = document.querySelector(`[data-asset-row="${cssEscapeValue(id)}"]`) || document.querySelector(`[data-open-archive="${cssEscapeValue(String(ref))}"]`);
  }
  if (!row) return;
  row.classList.add("active");
  const project = row.closest("details.library-project");
  if (project) project.open = true;
  const details = row.querySelector("details.track-details") || row.querySelector("details");
  if (details) details.open = true;
  row.scrollIntoView({ behavior: "smooth", block: "center" });
}

function ensureMiniPlayer() {
  let player = document.querySelector("#globalMiniPlayer");
  if (player) return player;
  player = document.createElement("aside");
  player.id = "globalMiniPlayer";
  player.className = "global-mini-player hidden";
  document.body.appendChild(player);
  return player;
}

function miniPlayerQueueFor(asset) {
  const playableAssets = sortArchiveAssets(uniqueLibraryAssets(cachedAudioAssets)).filter(item => Boolean(assetPlaybackUrl(item)));
  if (!asset) return playableAssets;
  if (currentMiniPlayerScope === "library") return playableAssets;

  const projectGroup = groupedAssetsByProject(playableAssets).find(group =>
    group.assets.some(item => String(item.id) === String(asset.id))
  );

  const queue = projectGroup?.assets?.length ? projectGroup.assets : playableAssets;
  return sortArchiveAssets(uniqueLibraryAssets(queue)).filter(item => Boolean(assetPlaybackUrl(item)));
}

function playRelativeMiniPlayer(direction) {
  if (!currentMiniPlayerAsset) return;
  const queue = miniPlayerQueueFor(currentMiniPlayerAsset);
  if (!queue.length) return;

  const currentIndex = queue.findIndex(asset => String(asset.id) === String(currentMiniPlayerAsset.id));
  const safeIndex = currentIndex >= 0 ? currentIndex : 0;
  const nextIndex = (safeIndex + direction + queue.length) % queue.length;
  openMiniPlayer(queue[nextIndex].id);
}

function closeMiniPlayer() {
  const player = ensureMiniPlayer();
  const audio = player.querySelector("audio");

  if (audio) {
    audio.pause();
    audio.removeAttribute("src");
    audio.load();
  }

  currentMiniPlayerAsset = null;
  player.classList.add("hidden");
  player.innerHTML = "";
}

function toggleMiniPlayerLoop() {
  currentMiniPlayerLoop = !currentMiniPlayerLoop;
  const player = ensureMiniPlayer();
  const audio = player.querySelector("audio");
  const button = player.querySelector("[data-mini-loop]");

  if (audio) audio.loop = currentMiniPlayerLoop;
  if (button) {
    button.classList.toggle("active", currentMiniPlayerLoop);
    button.setAttribute("aria-pressed", currentMiniPlayerLoop ? "true" : "false");
    button.title = currentMiniPlayerLoop ? "Loop aktiv" : "Loop aktivieren";
  }
}

function openMiniPlayer(assetId) {
  const asset = findAudioAsset(assetId);
  if (!asset) return;
  currentMiniPlayerAsset = asset;
  const player = ensureMiniPlayer();
  const url = assetPlaybackUrl(asset);
  if (!url) {
    notify("Für diesen Track ist keine abspielbare Audio-URL gespeichert.", true);
    return;
  }

  const queue = miniPlayerQueueFor(asset);
  const queueIndex = queue.findIndex(item => String(item.id) === String(asset.id));
  const hasMultipleTracks = queue.length > 1;

  player.classList.remove("hidden");
  player.innerHTML = `<div class="mini-player-cover">${asset.image_url ? `<img src="${escapeHtml(asset.image_url)}" alt="Cover">` : '<span>♪</span>'}</div><div class="mini-player-title"><strong>${escapeHtml(getAssetDisplayTitle(asset))}</strong><span>${escapeHtml(operationFromAsset(asset))}${hasMultipleTracks ? ` · ${queueIndex + 1}/${queue.length}` : ''}</span></div><div class="mini-player-controls"><button class="small-btn icon-btn" type="button" data-mini-prev ${hasMultipleTracks ? '' : 'disabled'} title="Vorheriger Track">⏮</button><button class="small-btn icon-btn ${currentMiniPlayerLoop ? 'active' : ''}" type="button" data-mini-loop aria-pressed="${currentMiniPlayerLoop ? 'true' : 'false'}" title="${currentMiniPlayerLoop ? 'Loop aktiv' : 'Loop aktivieren'}">🔁</button><button class="small-btn icon-btn" type="button" data-mini-next ${hasMultipleTracks ? '' : 'disabled'} title="Nächster Track">⏭</button></div><div class="mini-player-audio-stack"><audio controls autoplay preload="metadata" src="${escapeHtml(url)}"></audio><div class="mini-waveform-mount" data-mini-waveform-mount="${escapeHtml(asset.id)}">${renderWaveformMarkup(asset, asset.waveform_json)}</div></div><button class="small-btn" type="button" data-audio-action="extend" data-asset-id="${escapeHtml(asset.id)}" ${asset.audio_id ? '' : 'disabled'}>Extend</button><a class="button-link" href="${escapeHtml(asset.status === 'cached' ? `/api/archive/audio/${asset.id}/download` : url)}" download>Download</a><button class="small-btn icon-btn danger-mini" type="button" data-close-mini-player title="Player schließen">×</button>`;
  const audio = player.querySelector("audio");
  if (audio) {
    audio.loop = currentMiniPlayerLoop;
    audio.addEventListener("ended", () => {
      if (!currentMiniPlayerLoop && hasMultipleTracks) playRelativeMiniPlayer(1);
    }, { once: true });
    audio.play().catch(() => null);
    hydrateMiniPlayerWaveform(asset, audio);
  }
}


function waveformSegmentClass(type) {
  const normalized = String(type || 'section').toLowerCase().replace(/[^a-z0-9_ -]/g, '').replace(/\s+/g, '_');
  return `wave-segment-${normalized || 'section'}`;
}

function renderWaveformMarkup(asset, waveform = null) {
  const peaks = Array.isArray(waveform?.peaks) && waveform.peaks.length ? waveform.peaks : Array.from({ length: 96 }, (_, index) => 0.18 + Math.abs(Math.sin(index / 7)) * 0.45);
  const duration = Number(waveform?.duration_seconds || durationSecondsFromAsset(asset) || 0);
  const segments = Array.isArray(waveform?.segments) ? waveform.segments : [];
  return `<div class="waveform-shell" data-waveform-for="${escapeHtml(asset?.id || '')}">
    <div class="waveform-segments">${segments.map(segment => {
      const start = Number(segment.start || 0);
      const end = Number(segment.end || start);
      const left = duration > 0 ? Math.max(0, Math.min(100, (start / duration) * 100)) : 0;
      const width = duration > 0 ? Math.max(1.5, Math.min(100 - left, ((end - start) / duration) * 100)) : 0;
      return `<button class="waveform-segment ${escapeHtml(waveformSegmentClass(segment.type))}" type="button" data-waveform-seek="${escapeHtml(start)}" style="left:${left.toFixed(3)}%;width:${width.toFixed(3)}%" title="${escapeHtml(segment.label || segment.type || 'Segment')}"><span>${escapeHtml(segment.label || '')}</span></button>`;
    }).join('')}</div>
    <button class="waveform-bars" type="button" data-waveform-click="${escapeHtml(asset?.id || '')}" aria-label="Waveform Navigation">
      ${peaks.map(value => `<span style="height:${Math.max(5, Math.min(100, Number(value || 0.05) * 100)).toFixed(2)}%"></span>`).join('')}
    </button>
  </div>`;
}

async function hydrateMiniPlayerWaveform(asset, audio) {
  if (!asset?.id) return;
  const mount = document.querySelector(`[data-mini-waveform-mount="${CSS.escape(String(asset.id))}"]`);
  if (!mount) return;
  try {
    const waveform = await api(`/api/archive/audio/${encodeURIComponent(asset.id)}/waveform?points=180`);
    if (!currentMiniPlayerAsset || String(currentMiniPlayerAsset.id) !== String(asset.id)) return;
    mount.innerHTML = renderWaveformMarkup(asset, waveform);
  } catch (error) {
    mount.innerHTML = renderWaveformMarkup(asset, null);
  }
}

function seekMiniPlayerTo(seconds) {
  const player = ensureMiniPlayer();
  const audio = player.querySelector('audio');
  const target = Number(seconds);
  if (!audio || Number.isNaN(target)) return;
  audio.currentTime = Math.max(0, target);
  audio.play().catch(() => null);
}

function seekMiniPlayerByRatio(ratio) {
  const player = ensureMiniPlayer();
  const audio = player.querySelector('audio');
  if (!audio || !Number.isFinite(audio.duration) || audio.duration <= 0) return;
  audio.currentTime = Math.max(0, Math.min(audio.duration, audio.duration * ratio));
  audio.play().catch(() => null);
}

function applyProductionProfile(profileId) {
  const profile = cachedProductionProfiles.find(p => String(p.id) === String(profileId));
  if (!profile) return;
  switchTab("tab-music");
  const form = document.querySelector("#generateForm");
  setFormField(form, "model", profile.model || "V5_5");
  setFormField(form, "style", profile.style || "");
  setFormField(form, "vocal_gender", profile.vocal_gender || "");
  setFormField(form, "negative_tags", profile.negative_tags || "");
  setFormField(form, "persona_id", profile.persona_id || "");
  setFormField(form, "persona_model", profile.persona_model || "");
  setFormField(form, "instrumental", String(Boolean(profile.instrumental)));
  setFormField(form, "customMode", String(profile.custom_mode !== false));
  notify("Produktionsprofil übernommen");
}

/* === Admin: Benutzer, KI-Defaults, Systemanweisung, Vocal Tags === */

function currentUserIsAdmin() {
  return Boolean(authUser);
}

async function loadCurrentUser() {
  if (!getAuthToken()) return null;
  try {
    authUser = await api("/auth/me");
    document.querySelectorAll(".admin-tab-button").forEach(button => button.classList.toggle("hidden", !authUser));
    injectUserMenu();
    return authUser;
  } catch (error) {
    authUser = null;
    injectUserMenu();
    return null;
  }
}

async function refreshAdminPanel() {
  if (!document.querySelector("#tab-admin")) return;
  const status = document.querySelector("#adminStatus");
  if (!authUser) {
    if (status) status.textContent = "Bitte anmelden, um die Verwaltung zu öffnen.";
    renderAdminUsers([]);
    renderAdminVocalTags([]);
    return;
  }
  const [users, aiSettings, vocalTags, aiProfiles, instructionFiles] = await Promise.all([
    api("/api/admin/users"),
    api("/api/admin/ai-settings"),
    api("/api/admin/vocal-tags"),
    api("/api/admin/ai-profiles"),
    api("/api/admin/instruction-files?include_content=true"),
  ]);
  cachedAdminUsers = users;
  cachedAdminAiSettings = aiSettings;
  cachedAdminVocalTags = vocalTags;
  cachedAdminAiProfiles = aiProfiles;
  cachedAdminInstructionFiles = instructionFiles;
  if (status) status.textContent = "Admin-Daten geladen.";
  renderAdminUsers(users);
  renderAdminAiSettings(aiSettings);
  renderAdminAiProfiles(aiProfiles);
  renderAdminInstructionFiles(instructionFiles);
  renderAdminVocalTags(vocalTags);
}

function renderAdminUsers(users) {
  const box = document.querySelector("#adminUserList");
  if (!box) return;
  if (!users.length) {
    box.innerHTML = `<div class="empty-state">Keine Benutzer geladen.</div>`;
    return;
  }
  box.innerHTML = `<table class="admin-data-table"><thead><tr><th>ID</th><th>E-Mail</th><th>Status</th><th>Erstellt</th><th>Aktion</th></tr></thead><tbody>${users.map(user => `
    <tr>
      <td>${escapeHtml(user.id)}</td>
      <td>${escapeHtml(user.email)}</td>
      <td><select data-admin-user-active="${escapeHtml(user.id)}"><option value="true" ${user.is_active ? "selected" : ""}>aktiv</option><option value="false" ${!user.is_active ? "selected" : ""}>deaktiviert</option></select></td>
      <td>${escapeHtml(formatDate(user.created_at))}</td>
      <td><button class="small-btn" type="button" data-save-admin-user="${escapeHtml(user.id)}">Speichern</button></td>
    </tr>`).join("")}</tbody></table>`;
}

function renderAdminAiSettings(settings) {
  const providerSelect = document.querySelector("#adminDefaultProvider");
  const modelSelect = document.querySelector("#adminDefaultModel");
  const instruction = document.querySelector("#adminSystemInstruction");
  if (!providerSelect || !modelSelect || !settings) return;
  const providers = settings.allowed_models || {};
  providerSelect.innerHTML = Object.keys(providers).map(provider => {
    const configured = settings.providers?.[provider]?.configured;
    return `<option value="${escapeHtml(provider)}" ${provider === settings.default_provider ? "selected" : ""}>${escapeHtml(provider)}${configured ? "" : " (kein Key)"}</option>`;
  }).join("");
  renderAdminAiModelOptions();
  if (modelSelect) modelSelect.value = settings.default_model || modelSelect.value;
  if (instruction) instruction.value = settings.system_instruction || "";
  const profileSelect = document.querySelector("#adminDefaultAssistantProfile");
  if (profileSelect) profileSelect.value = settings.default_assistant_profile_id || "";
}

function renderAdminAiModelOptions() {
  const providerSelect = document.querySelector("#adminDefaultProvider");
  const modelSelect = document.querySelector("#adminDefaultModel");
  if (!providerSelect || !modelSelect || !cachedAdminAiSettings) return;
  const provider = providerSelect.value || cachedAdminAiSettings.default_provider;
  const models = cachedAdminAiSettings.allowed_models?.[provider] || [];
  modelSelect.innerHTML = models.map(model => `<option value="${escapeHtml(model)}">${escapeHtml(model)}</option>`).join("");
  if (models.includes(cachedAdminAiSettings.default_model)) modelSelect.value = cachedAdminAiSettings.default_model;
}

function renderAdminVocalTags(tags) {
  const box = document.querySelector("#adminVocalTagList");
  if (!box) return;
  if (!tags.length) {
    box.innerHTML = `<div class="empty-state">Noch keine Vocal Tags vorhanden.</div>`;
    return;
  }
  box.innerHTML = tags.map(tag => `<article class="style-card vocal-admin-card ${tag.is_active ? "" : "muted"}">
    <div class="style-card-head">
      <div><strong>${escapeHtml(tag.label)}</strong><div class="result-meta"><span class="badge">${escapeHtml(tag.category)}</span>${tag.is_active ? `<span class="badge success">aktiv</span>` : `<span class="badge warning">inaktiv</span>`}</div></div>
      <div class="result-actions"><button class="small-btn" type="button" data-edit-admin-vocal-tag="${escapeHtml(tag.id)}">Bearbeiten</button><button class="small-btn danger" type="button" data-delete-admin-vocal-tag="${escapeHtml(tag.id)}">Löschen</button></div>
    </div>
    <div class="style-text-preview">${escapeHtml(tag.tag)}</div>
    ${tag.description ? `<p>${escapeHtml(tag.description)}</p>` : ""}
  </article>`).join("");
}

function clearAdminVocalTagForm() {
  const form = document.querySelector("#adminVocalTagForm");
  form?.reset();
  setFormField(form, "id", "");
  setFormField(form, "is_active", "true");
  setFormField(form, "sort_order", "0");
}

function loadAdminVocalTagToForm(id) {
  const tag = cachedAdminVocalTags.find(item => String(item.id) === String(id));
  if (!tag) return;
  const form = document.querySelector("#adminVocalTagForm");
  setFormField(form, "id", tag.id);
  setFormField(form, "label", tag.label || "");
  setFormField(form, "category", tag.category || "Tags");
  setFormField(form, "tag", tag.tag || "");
  setFormField(form, "description", tag.description || "");
  setFormField(form, "sort_order", tag.sort_order ?? 0);
  setFormField(form, "is_active", tag.is_active ? "true" : "false");
}

async function saveAdminAiSettings(event) {
  event.preventDefault();
  const payload = formToObject(event.target);
  cachedAdminAiSettings = await api("/api/admin/ai-settings", { method: "PUT", body: JSON.stringify(payload) });
  await loadAiConfig();
  renderAdminAiSettings(cachedAdminAiSettings);
  notify("KI-Einstellungen gespeichert");
}

async function testAdminAiProvider() {
  const provider = document.querySelector("#adminDefaultProvider")?.value;
  const model = document.querySelector("#adminDefaultModel")?.value;
  const box = document.querySelector("#adminAiTestResult");
  if (box) box.innerHTML = `<div class="notice-box">Provider-Test läuft...</div>`;
  const data = await api("/api/admin/ai-settings/test", { method: "POST", body: JSON.stringify({ provider, model, message: "Kurzer Verbindungstest. Antworte knapp." }) });
  if (box) box.innerHTML = `<div class="result-card"><strong>Test erfolgreich</strong><p>${escapeHtml(data.message || "OK")}</p></div>`;
}

async function saveAdminVocalTag(event) {
  event.preventDefault();
  const payload = formToObject(event.target);
  if (payload.sort_order !== undefined) payload.sort_order = Number(payload.sort_order || 0);
  const id = payload.id;
  delete payload.id;
  await api(id ? `/api/admin/vocal-tags/${id}` : "/api/admin/vocal-tags", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) });
  clearAdminVocalTagForm();
  cachedAdminVocalTags = await api("/api/admin/vocal-tags");
  renderAdminVocalTags(cachedAdminVocalTags);
  await refreshVocalTags();
  notify("Vocal Tag gespeichert");
}

async function saveAdminUser(userId) {
  const isActive = document.querySelector(`[data-admin-user-active="${CSS.escape(String(userId))}"]`)?.value === "true";
  await api(`/api/admin/users/${userId}`, { method: "PATCH", body: JSON.stringify({ is_active: isActive }) });
  await refreshAdminPanel();
  notify("Benutzer gespeichert");
}

function renderAdminAiProfileProviderModelOptions() {
  const providerSelect = document.querySelector("#adminAiProfileProvider");
  const modelSelect = document.querySelector("#adminAiProfileModel");
  if (!providerSelect || !modelSelect || !cachedAdminAiSettings) return;
  const providers = cachedAdminAiSettings.allowed_models || {};
  const currentProvider = providerSelect.value || cachedAdminAiSettings.default_provider || Object.keys(providers)[0] || "openai";
  providerSelect.innerHTML = Object.keys(providers).map(provider => `<option value="${escapeHtml(provider)}" ${provider === currentProvider ? "selected" : ""}>${escapeHtml(provider)}</option>`).join("");
  const models = providers[currentProvider] || [];
  const currentModel = modelSelect.value || cachedAdminAiSettings.default_model || models[0] || "";
  modelSelect.innerHTML = models.map(model => `<option value="${escapeHtml(model)}" ${model === currentModel ? "selected" : ""}>${escapeHtml(model)}</option>`).join("");
}

function renderInstructionFileMultiSelect(selectedIds = []) {
  const select = document.querySelector("#adminAiProfileFiles");
  if (!select) return;
  const selected = new Set((selectedIds || []).map(String));
  select.innerHTML = cachedAdminInstructionFiles.map(file => `<option value="${escapeHtml(file.id)}" ${selected.has(String(file.id)) ? "selected" : ""}>${escapeHtml(file.title)}${file.is_active ? "" : " (inaktiv)"}</option>`).join("");
}

function renderAdminAiProfiles(profiles) {
  renderAdminAiProfileProviderModelOptions();
  renderInstructionFileMultiSelect();
  const defaultSelect = document.querySelector("#adminDefaultAssistantProfile");
  if (defaultSelect) {
    defaultSelect.innerHTML = `<option value="">Kein Profil</option>` + profiles.map(profile => `<option value="${escapeHtml(profile.id)}" ${cachedAdminAiSettings && String(cachedAdminAiSettings.default_assistant_profile_id || "") === String(profile.id) ? "selected" : ""}>${escapeHtml(profile.name)} · ${escapeHtml(profile.provider)} / ${escapeHtml(profile.model)}</option>`).join("");
  }
  const box = document.querySelector("#adminAiProfileList");
  if (!box) return;
  if (!profiles.length) {
    box.innerHTML = `<div class="empty-state">Noch keine KI-Profile vorhanden.</div>`;
    return;
  }
  box.innerHTML = profiles.map(profile => `<article class="style-card ${profile.is_active ? "" : "muted"}">
    <div class="style-card-head">
      <div><strong>${escapeHtml(profile.name)}</strong><div class="result-meta"><span class="badge">${escapeHtml(profile.provider)} / ${escapeHtml(profile.model)}</span>${profile.is_default ? `<span class="badge success">Default</span>` : ""}${profile.linked_file_ids?.length ? `<span class="badge">${profile.linked_file_ids.length} Datei(en)</span>` : ""}</div></div>
      <div class="result-actions"><button class="small-btn" type="button" data-edit-admin-ai-profile="${escapeHtml(profile.id)}">Bearbeiten</button><button class="small-btn danger" type="button" data-delete-admin-ai-profile="${escapeHtml(profile.id)}">Löschen</button></div>
    </div>
    ${profile.description ? `<p>${escapeHtml(profile.description)}</p>` : ""}
    ${profile.system_instruction ? `<div class="style-text-preview">${escapeHtml(profile.system_instruction.slice(0, 600))}</div>` : ""}
  </article>`).join("");
}

function clearAdminAiProfileForm() {
  const form = document.querySelector("#adminAiProfileForm");
  form?.reset();
  setFormField(form, "id", "");
  setFormField(form, "is_active", "true");
  setFormField(form, "is_default", "false");
  renderAdminAiProfileProviderModelOptions();
  renderInstructionFileMultiSelect();
}

function loadAdminAiProfileToForm(id) {
  const profile = cachedAdminAiProfiles.find(item => String(item.id) === String(id));
  if (!profile) return;
  const form = document.querySelector("#adminAiProfileForm");
  setFormField(form, "id", profile.id);
  setFormField(form, "name", profile.name || "");
  setFormField(form, "description", profile.description || "");
  setFormField(form, "provider", profile.provider || "openai");
  renderAdminAiProfileProviderModelOptions();
  setFormField(form, "model", profile.model || "");
  setFormField(form, "system_instruction", profile.system_instruction || "");
  setFormField(form, "response_format_instruction", profile.response_format_instruction || "");
  setFormField(form, "temperature", profile.temperature ?? "");
  setFormField(form, "max_output_tokens", profile.max_output_tokens ?? "");
  setFormField(form, "is_active", profile.is_active ? "true" : "false");
  setFormField(form, "is_default", profile.is_default ? "true" : "false");
  renderInstructionFileMultiSelect(profile.linked_file_ids || []);
}

async function saveAdminAiProfile(event) {
  event.preventDefault();
  const payload = formToObject(event.target);
  const id = payload.id;
  delete payload.id;
  payload.is_active = String(payload.is_active) === "true";
  payload.is_default = String(payload.is_default) === "true";
  payload.linked_file_ids = Array.from(document.querySelector("#adminAiProfileFiles")?.selectedOptions || []).map(option => Number(option.value));
  if (payload.temperature === "") delete payload.temperature; else payload.temperature = Number(payload.temperature);
  if (payload.max_output_tokens === "") delete payload.max_output_tokens; else payload.max_output_tokens = Number(payload.max_output_tokens);
  await api(id ? `/api/admin/ai-profiles/${id}` : "/api/admin/ai-profiles", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) });
  clearAdminAiProfileForm();
  await refreshAdminPanel();
  await loadAiConfig();
  notify("KI-Profil gespeichert");
}

function renderAdminInstructionFiles(files) {
  renderInstructionFileMultiSelect();
  const box = document.querySelector("#adminInstructionFileList");
  if (!box) return;
  if (!files.length) {
    box.innerHTML = `<div class="empty-state">Noch keine Instruction-Dateien vorhanden.</div>`;
    return;
  }
  box.innerHTML = files.map(file => `<article class="style-card ${file.is_active ? "" : "muted"}">
    <div class="style-card-head">
      <div><strong>${escapeHtml(file.title)}</strong><div class="result-meta"><span class="badge">${escapeHtml(file.filename || "manuell")}</span>${file.is_active ? `<span class="badge success">aktiv</span>` : `<span class="badge warning">inaktiv</span>`}</div></div>
      <div class="result-actions"><button class="small-btn" type="button" data-edit-admin-instruction="${escapeHtml(file.id)}">Bearbeiten</button><button class="small-btn danger" type="button" data-delete-admin-instruction="${escapeHtml(file.id)}">Löschen</button></div>
    </div>
    ${file.description ? `<p>${escapeHtml(file.description)}</p>` : ""}
    ${file.content ? `<div class="style-text-preview">${escapeHtml(file.content.slice(0, 800))}</div>` : ""}
  </article>`).join("");
}

function clearAdminInstructionForm() {
  const form = document.querySelector("#adminInstructionTextForm");
  form?.reset();
  setFormField(form, "id", "");
  setFormField(form, "is_active", "true");
}

function loadAdminInstructionToForm(id) {
  const file = cachedAdminInstructionFiles.find(item => String(item.id) === String(id));
  if (!file) return;
  const form = document.querySelector("#adminInstructionTextForm");
  setFormField(form, "id", file.id);
  setFormField(form, "title", file.title || "");
  setFormField(form, "description", file.description || "");
  setFormField(form, "content", file.content || "");
  setFormField(form, "is_active", file.is_active ? "true" : "false");
}

async function saveAdminInstruction(event) {
  event.preventDefault();
  const payload = formToObject(event.target);
  const id = payload.id;
  delete payload.id;
  payload.is_active = String(payload.is_active) === "true";
  await api(id ? `/api/admin/instruction-files/${id}` : "/api/admin/instruction-files", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) });
  clearAdminInstructionForm();
  await refreshAdminPanel();
  notify("Instruction gespeichert");
}

async function uploadAdminInstruction(event) {
  event.preventDefault();
  const form = event.target;
  const fileInput = form.querySelector("input[type=file]");
  if (!fileInput?.files?.length) {
    notify("Bitte eine Datei auswählen", true);
    return;
  }
  const formData = new FormData(form);
  await api("/api/admin/instruction-files/upload", { method: "POST", body: formData, headers: {} });
  form.reset();
  await refreshAdminPanel();
  notify("Instruction-Datei hochgeladen");
}

function bindEvents() {
  document.querySelector("#playlistForm")?.addEventListener("submit", async event => {
    event.preventDefault();
    const data = await api("/api/library/playlists", { method: "POST", body: JSON.stringify(formToObject(event.target)) });
    event.target.reset();
    await refreshPlaylists();
    notify(`Playlist ${data.name} angelegt`);
  });
  document.querySelector("#lyricDraftForm")?.addEventListener("submit", saveLyricDraft);
  document.querySelectorAll("[data-lyric-view]").forEach(button => {
    button.addEventListener("click", () => setLyricStudioView(button.dataset.lyricView));
  });
  document.querySelector("#musicStyleForm")?.addEventListener("submit", saveMusicStyle);
  document.querySelector("#generateForm").addEventListener("submit", event => handleJsonForm(event, "/api/music/generate", "Musikgenerierung gestartet"));
  document.querySelector("#lyricsForm").addEventListener("submit", event => handleJsonForm(event, "/api/lyrics/generate", "Lyrics-Generierung gestartet"));
  document.querySelector("#extendForm").addEventListener("submit", event => handleJsonForm(event, "/api/music/extend", "Musik-Extension gestartet"));
  document.querySelector("#coverForm").addEventListener("submit", event => handleJsonForm(event, "/api/music/cover", "Cover-Erstellung gestartet"));
  document.querySelector("#uploadCoverForm").addEventListener("submit", event => handleJsonForm(event, "/api/music/upload-and-cover", "Audio-Cover gestartet"));
  document.querySelector("#uploadExtendForm")?.addEventListener("submit", event => handleJsonForm(event, "/api/music/upload-and-extend", "Upload-Extend gestartet"));
  document.querySelector("#replaceSectionForm")?.addEventListener("submit", event => handleJsonForm(event, "/api/music/replace-section", "Abschnitt ersetzen gestartet"));
  document.querySelector("#mashupForm")?.addEventListener("submit", event => handleJsonForm(event, "/api/music/mashup", "Mashup gestartet"));
  document.querySelector("#addVocalsForm").addEventListener("submit", event => handleJsonForm(event, "/api/music/add-vocals", "Vocals-Generierung gestartet"));
  document.querySelector("#addInstrumentalForm").addEventListener("submit", event => handleJsonForm(event, "/api/music/add-instrumental", "Instrumental-Generierung gestartet"));
  document.querySelector("#boostStyleForm").addEventListener("submit", event => handleJsonForm(event, "/api/music/boost-style", "Style-Optimierung abgeschlossen"));
  document.querySelector("#personaForm").addEventListener("submit", event => handleJsonForm(event, "/api/music/persona", "Persona erstellt"));
  document.querySelector("#wavForm").addEventListener("submit", event => handleJsonForm(event, "/api/audio/wav", "WAV-Konvertierung gestartet"));
  document.querySelector("#midiForm")?.addEventListener("submit", event => handleJsonForm(event, "/api/audio/midi", "MIDI-Erzeugung gestartet"));
  document.querySelector("#timestampedLyricsForm")?.addEventListener("submit", event => handleJsonForm(event, "/api/audio/timestamped-lyrics", "Timestamped Lyrics gestartet"));
  document.querySelector("#videoForm")?.addEventListener("submit", event => handleJsonForm(event, "/api/music/video", "Music Video gestartet"));
  document.querySelector("#soundsForm")?.addEventListener("submit", event => handleJsonForm(event, "/api/music/sounds", "Sound-Generierung gestartet"));
  document.querySelector("#urlUploadForm").addEventListener("submit", event => handleJsonForm(event, "/api/files/url", "URL-Upload abgeschlossen"));
  document.querySelector("#importSunoTaskForm")?.addEventListener("submit", event => handleJsonForm(event, "/api/music/tasks/import-from-suno", "Suno-Task importiert"));
  document.querySelector("#voiceValidateForm")?.addEventListener("submit", event => handleJsonForm(event, "/api/music/voice/validate", "Voice Validation gestartet"));
  document.querySelector("#voiceGenerateForm")?.addEventListener("submit", event => handleJsonForm(event, "/api/music/voice/generate", "Custom Voice gestartet"));
  document.querySelector("#btnVoiceValidateInfo")?.addEventListener("click", async () => {
    const taskId = document.querySelector("#voiceValidationTaskId")?.value?.trim();
    if (!taskId) return notify("Bitte Validation Task-ID eintragen", "error");
    const data = await api(`/api/music/voice/validate-info?task_id=${encodeURIComponent(taskId)}`);
    showCompact(data, false, "Validation Phrase");
  });
  document.querySelector("#btnVoiceRegenerate")?.addEventListener("click", async () => {
    const taskId = document.querySelector("#voiceValidationTaskId")?.value?.trim();
    if (!taskId) return notify("Bitte Validation Task-ID eintragen", "error");
    const data = await api("/api/music/voice/regenerate", { method: "POST", body: JSON.stringify({ task_id: taskId }) });
    showCompact(data, false, "Validation Phrase neu erzeugt");
  });
  document.querySelector("#btnVoiceRecordInfo")?.addEventListener("click", async () => {
    const taskId = document.querySelector("#voiceCustomTaskId")?.value?.trim();
    if (!taskId) return notify("Bitte Custom Voice Task-ID eintragen", "error");
    const data = await api(`/api/music/voice/record-info?task_id=${encodeURIComponent(taskId)}`);
    showCompact(data, false, "Custom Voice Record");
  });
  document.querySelector("#btnVoiceCheckAvailability")?.addEventListener("click", async () => {
    const taskId = document.querySelector("#voiceCustomTaskId")?.value?.trim();
    if (!taskId) return notify("Bitte Custom Voice Task-ID eintragen", "error");
    const data = await api("/api/music/voice/check-availability", { method: "POST", body: JSON.stringify({ task_id: taskId }) });
    showCompact(data, false, "Voice-Verfügbarkeit");
  });

  document.querySelector("#audioForm").addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.target;
    setSubmitting(form, true);
    try {
      const payload = formToObject(form);
      const action = payload.action;
      delete payload.action;
      const data = await api(`/api/audio/${action}`, { method: "POST", body: JSON.stringify(payload) });
      showCompact(data, false, "Audio-Verarbeitung gestartet");
      switchTab("tab-status");
      await refreshAll(true);
    } catch (error) {
      showCompact({ error: error.message }, true, "Audio-Verarbeitung");
    } finally {
      setSubmitting(form, false);
    }
  });

  document.querySelector("#streamUploadForm").addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.target;
    setSubmitting(form, true);
    try {
      const data = await api("/api/files/stream", { method: "POST", body: new FormData(form) });
      showCompact(data, false, "Stream-Upload abgeschlossen");
      switchTab("tab-status");
    } catch (error) {
      showCompact({ error: error.message }, true, "Stream-Upload");
    } finally {
      setSubmitting(form, false);
    }
  });

  document.querySelector("#btnReloadPlaylists")?.addEventListener("click", refreshPlaylists);
  document.querySelector("#btnReloadStyles")?.addEventListener("click", refreshMusicStyles);
  document.querySelector("#btnNewLyricDraft")?.addEventListener("click", clearLyricDraftEditor);
  document.querySelector("#btnNewStyle")?.addEventListener("click", clearStyleEditor);
  document.querySelector("#btnCreateProfileFromStyle")?.addEventListener("click", async () => {
    const form = document.querySelector("#musicStyleForm");
    const payload = formToObject(form);
    const name = payload.name || prompt("Profilname", "Neues Produktionsprofil");
    if (!name) return;
    const profile = {
      name,
      description: payload.description || "Aus Music Style erstellt",
      model: document.querySelector("#musicModel")?.value || "V5_5",
      style: payload.style_text || "",
      custom_mode: true,
      instrumental: false,
      is_favorite: payload.is_favorite === true || payload.is_favorite === "true"
    };
    await api("/api/production/profiles", { method: "POST", body: JSON.stringify(profile) });
    await refreshProductionProfiles();
    renderProductionProfiles();
    notify("Produktionsprofil erstellt");
  });
  document.querySelector("#btnInsertBasicStructure")?.addEventListener("click", () => {
    const field = document.querySelector("#lyricDraftContent");
    if (!field) return;
    field.value = field.value.trim() ? `${field.value.trim()}\n\n${getBasicSongStructure()}` : getBasicSongStructure();
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
  document.querySelector("#lyricDraftContent")?.addEventListener("input", renderLyricChapterMap);
  renderLyricChapterMap();
  document.querySelector("#btnSendDraftToMusic")?.addEventListener("click", sendDraftToMusic);
  document.querySelector("#styleSearch")?.addEventListener("input", renderMusicStyles);
  document.querySelector("#btnCredits").addEventListener("click", () => loadCredits(true).catch(error => showCompact({ error: error.message }, true, "Credits")));
  document.querySelector("#btnWorkflowModal")?.addEventListener("click", () => openModal("workflowModal"));
  document.querySelector("#btnHelpModal")?.addEventListener("click", () => openModal("helpModal"));
  document.querySelector("#btnSystemModal")?.addEventListener("click", () => openModal("systemModal"));

  document.querySelector("#btnSystemDiagnostics")?.addEventListener("click", () => renderSystemModal().catch(error => showCompact({ error: error.message }, true, "Systemdiagnose")));
  document.querySelector("#btnSystemExport")?.addEventListener("click", () => { window.location.href = "/api/system/export"; });
  document.querySelector("#btnSystemExportZip")?.addEventListener("click", () => { window.location.href = "/api/system/export-zip"; });
  document.querySelector("#btnSystemFixMetadata")?.addEventListener("click", async () => {
    const data = await api("/api/system/maintenance/fix-library-metadata", { method: "POST" });
    notify(`Library repariert: ${data.updated_audio_assets || 0} Audios`);
    await refreshAll(false);
    await renderSystemModal();
  });
  document.querySelector("#btnSystemDeduplicateAudio")?.addEventListener("click", async () => {
    if (!confirm("Doppelte Audio-Einträge zusammenführen? Vorher wird ein Backup-ZIP empfohlen.")) return;
    const data = await api("/api/system/maintenance/deduplicate-audio", { method: "POST" });
    notify(`Duplikate entfernt: ${data.deleted_duplicate_rows || 0}`);
    await refreshAll(false);
    await renderSystemModal();
  });
  document.querySelector("#btnSystemRemoveOrphanFiles")?.addEventListener("click", async () => {
    if (!confirm("Verwaiste Audiodateien löschen, die nicht mehr in der Datenbank referenziert sind?")) return;
    const data = await api("/api/system/maintenance/remove-orphan-audio-files", { method: "POST" });
    notify(`Dateien gelöscht: ${data.deleted_files || 0}`);
    await refreshAll(false);
    await renderSystemModal();
  });
  document.querySelector("#btnSystemRebuildProjects")?.addEventListener("click", async () => {
    const data = await api("/api/system/maintenance/rebuild-projects", { method: "POST" });
    notify("Projekte wurden neu gruppiert");
    await refreshAll(false);
    await renderSystemModal();
  });
  document.querySelector("#btnSystemCleanupFailedAudio")?.addEventListener("click", async () => {
    if (!confirm("Fehlerhafte lokale Audio-Einträge entfernen? Erfolgreich gespeicherte Audios bleiben erhalten.")) return;
    const data = await api("/api/system/maintenance/cleanup-failed-audio", { method: "POST" });
    notify(`Bereinigt: ${data.deleted_audio_rows || 0} Einträge`);
    await refreshAll(false);
    await renderSystemModal();
  });
  document.querySelector("#btnSystemCleanupAudit")?.addEventListener("click", async () => {
    if (!confirm("Alte Audit-Log-Einträge gemäß Aufbewahrungsfrist entfernen?")) return;
    const data = await api("/api/system/maintenance/cleanup-audit-log", { method: "POST" });
    notify(`Audit bereinigt: ${data.deleted_activity_rows || 0} Einträge`);
    await renderSystemModal();
  });
  document.querySelector("#btnAdminRefresh")?.addEventListener("click", () => refreshAdminPanel().catch(error => showCompact({ error: error.message }, true, "Admin")));
  document.querySelector("#adminAiSettingsForm")?.addEventListener("submit", event => saveAdminAiSettings(event).catch(error => showCompact({ error: error.message }, true, "KI Admin")));
  document.querySelector("#btnAdminAiTest")?.addEventListener("click", () => testAdminAiProvider().catch(error => showCompact({ error: error.message }, true, "Provider-Test")));
  document.querySelector("#adminDefaultProvider")?.addEventListener("change", renderAdminAiModelOptions);
  document.querySelector("#adminVocalTagForm")?.addEventListener("submit", event => saveAdminVocalTag(event).catch(error => showCompact({ error: error.message }, true, "Vocal Tag")));
  document.querySelector("#btnAdminNewVocalTag")?.addEventListener("click", clearAdminVocalTagForm);
  document.querySelector("#adminAiProfileForm")?.addEventListener("submit", event => saveAdminAiProfile(event).catch(error => showCompact({ error: error.message }, true, "KI-Profil")));
  document.querySelector("#btnAdminNewAiProfile")?.addEventListener("click", clearAdminAiProfileForm);
  document.querySelector("#adminAiProfileProvider")?.addEventListener("change", renderAdminAiProfileProviderModelOptions);
  document.querySelector("#adminInstructionTextForm")?.addEventListener("submit", event => saveAdminInstruction(event).catch(error => showCompact({ error: error.message }, true, "Instruction")));
  document.querySelector("#adminInstructionUploadForm")?.addEventListener("submit", event => uploadAdminInstruction(event).catch(error => showCompact({ error: error.message }, true, "Instruction Upload")));
  document.querySelector("#btnAdminNewInstruction")?.addEventListener("click", clearAdminInstructionForm);
  document.querySelector("#btnRefresh").addEventListener("click", () => refreshAll(true));
  document.querySelector("#btnArchiveRefresh").addEventListener("click", () => refreshAll(true));
  document.querySelector("#btnClearHistory").addEventListener("click", async () => {
    if (!confirm("Alle lokalen Tasks und gespeicherten Inhalte löschen?")) return;
    const data = await api("/api/music/history", { method: "DELETE" });
    showCompact(data, false, "Lokaler Verlauf wurde geleert");
    archiveDetail.className = "archive-detail empty-state";
    archiveDetail.textContent = "Wähle links einen Eintrag aus.";
    await refreshAll(false);
  });

  ["#musicModel", "#musicCustomMode", "#extendModel", "#extendCustomMode", "#addVocalsModel", "#addInstrumentalModel"].forEach(selector => document.querySelector(selector)?.addEventListener("change", applyConfiguredLimits));
  archiveSearch?.addEventListener("input", renderArchive);
  archiveType?.addEventListener("change", renderArchive);
  archiveStatus?.addEventListener("change", renderArchive);
  archiveSort?.addEventListener("change", renderArchive);
  document.querySelector("#btnArchiveSelectAllVisible")?.addEventListener("click", () => {
    lastVisibleArchiveRefs.forEach(ref => selectedArchiveItems.add(ref));
    updateArchiveSelectionBar();
  });
  document.querySelector("#btnArchiveClearSelection")?.addEventListener("click", () => {
    selectedArchiveItems.clear();
    updateArchiveSelectionBar();
  });
  document.querySelector("#btnArchiveDeleteSelected")?.addEventListener("click", async () => {
    const items = Array.from(selectedArchiveItems).map(parseArchiveRef).filter(item => item.type && Number.isFinite(item.id));
    if (!items.length) return;
    if (!confirm(`${items.length} ausgewählte Inhalte in den Papierkorb verschieben? Sie können später wiederhergestellt oder endgültig gelöscht werden.`)) return;
    const data = await api("/api/library/content/bulk-delete", {
      method: "POST",
      body: JSON.stringify({ items, delete_files: true })
    });
    selectedArchiveItems.clear();
    await refreshAll(false);
    notify(`In Papierkorb verschoben: ${data.deleted_count || 0}`);
  });
  document.querySelector("#btnArchiveRestoreSelected")?.addEventListener("click", async () => {
    const items = Array.from(selectedArchiveItems).map(parseArchiveRef).filter(item => item.type && Number.isFinite(item.id));
    if (!items.length) return;
    const data = await api("/api/library/content/bulk-restore", { method: "POST", body: JSON.stringify({ items }) });
    selectedArchiveItems.clear();
    await refreshAll(false);
    notify(`Wiederhergestellt: ${data.restored_count || 0}`);
  });
  document.querySelector("#btnArchivePurgeSelected")?.addEventListener("click", async () => {
    const items = Array.from(selectedArchiveItems).map(parseArchiveRef).filter(item => item.type && Number.isFinite(item.id));
    if (!items.length) return;
    if (!confirm(`${items.length} ausgewählte Papierkorb-Inhalte endgültig löschen? Diese Aktion kann nicht rückgängig gemacht werden.`)) return;
    const data = await api("/api/library/content/bulk-purge", { method: "POST", body: JSON.stringify({ items, delete_files: true }) });
    selectedArchiveItems.clear();
    await refreshAll(false);
    notify(`Endgültig gelöscht: ${data.purged_count || 0}`);
  });
  document.querySelectorAll(".library-filter").forEach(button => button.addEventListener("click", () => {
    if (archiveType) archiveType.value = button.dataset.archiveFilter || "all";
    renderArchive();
  }));

  
async function editContentTitle(type, id, currentTitle = "") {
  const normalizedType = String(type || "").trim();
  const normalizedId = String(id || "").trim();
  if (!normalizedType || !normalizedId) return;

  const oldTitle = String(currentTitle || "").trim();
  const newTitle = prompt("Neuen Titel eingeben", oldTitle);
  if (newTitle === null) return;

  const cleanedTitle = newTitle.trim();
  if (!cleanedTitle) {
    notify("Titel darf nicht leer sein", true);
    return;
  }

  if (cleanedTitle.length > 255) {
    notify(`Titel ist zu lang. Erlaubt: 255 Zeichen, aktuell: ${cleanedTitle.length}.`, true);
    return;
  }

  await api(`/api/library/content/${encodeURIComponent(normalizedType)}/${encodeURIComponent(normalizedId)}/title`, {
    method: "PATCH",
    body: JSON.stringify({ title: cleanedTitle })
  });

  await refreshAll(false);
  notify("Titel aktualisiert");
}


document.addEventListener("toggle", event => {
  rememberLibraryToggle(event.target);
}, true);

document.addEventListener("click", event => {
  const summaryControl = event.target.closest("summary button, summary a, summary input, summary select, summary label");
  if (summaryControl) {
    event.preventDefault();
  }
}, true);

document.addEventListener("click", async event => {
    const closeModalButton = event.target.closest("[data-close-modal]");
    if (closeModalButton) closeModal(closeModalButton.dataset.closeModal);

    const openNotificationButton = event.target.closest("[data-open-notification]");
    if (openNotificationButton) {
      event.preventDefault();
      event.stopPropagation();
      openNotificationTargetById(openNotificationButton.dataset.openNotification);
      return;
    }

    const doneNotificationButton = event.target.closest("[data-notification-done]");
    if (doneNotificationButton) {
      event.preventDefault();
      event.stopPropagation();
      await markNotificationDone(doneNotificationButton.dataset.notificationDone);
      toast?.classList.remove("visible");
      return;
    }

    const deleteNotificationButton = event.target.closest("[data-notification-delete]");
    if (deleteNotificationButton) {
      event.preventDefault();
      event.stopPropagation();
      await deleteNotification(deleteNotificationButton.dataset.notificationDelete);
      return;
    }

    if (event.target.closest("#btnNotificationsSelectAll")) {
      selectedNotifications = new Set(cachedNotifications.filter(item => !item.is_deleted).map(item => String(item.id)));
      renderStatusNotifications();
      return;
    }

    if (event.target.closest("#btnNotificationsClearSelection")) {
      selectedNotifications.clear();
      renderStatusNotifications();
      return;
    }

    if (event.target.closest("#btnNotificationsMarkDone")) {
      await api("/api/notifications/bulk-done", { method: "POST", body: JSON.stringify({ ids: [...selectedNotifications] }) });
      selectedNotifications.clear();
      await refreshNotifications();
      notify("Benachrichtigungen erledigt", "success");
      return;
    }

    if (event.target.closest("#btnNotificationsDelete")) {
      if (!selectedNotifications.size) return;
      if (!confirm(`${selectedNotifications.size} Benachrichtigungen endgültig ausblenden?`)) return;
      await api("/api/notifications/bulk-delete", { method: "POST", body: JSON.stringify({ ids: [...selectedNotifications] }) });
      selectedNotifications.clear();
      await refreshNotifications();
      notify("Benachrichtigungen gelöscht", "success");
      return;
    }

    const userMenuButton = event.target.closest("#userMenuButton");
    if (userMenuButton) {
      event.preventDefault();
      event.stopPropagation();
      toggleUserMenu();
      return;
    }

    if (!event.target.closest("#userMenuWrapper")) {
      toggleUserMenu(false);
    }

    const profileModalButton = event.target.closest("[data-open-profile-modal]");
    if (profileModalButton) {
      event.preventDefault();
      event.stopPropagation();
      toggleUserMenu(false);
      openProfileModal(profileModalButton.dataset.openProfileModal || "profile");
      return;
    }

    const userLogoutButton = event.target.closest("[data-user-logout]");
    if (userLogoutButton) {
      event.preventDefault();
      event.stopPropagation();
      toggleUserMenu(false);
      await logoutUser();
      return;
    }

    const switchButton = event.target.closest("[data-switch-tab]");
    if (switchButton) switchTab(switchButton.dataset.switchTab);

    const copyButton = event.target.closest("[data-copy]");
    if (copyButton) {
      try { await navigator.clipboard.writeText(copyButton.dataset.copy || ""); }
      catch {
        const textarea = document.createElement("textarea");
        textarea.value = copyButton.dataset.copy || "";
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand("copy");
        textarea.remove();
      }
      notify("In Zwischenablage kopiert");
    }

    const refreshButton = event.target.closest("[data-refresh-task]");
    if (refreshButton) {
      refreshButton.disabled = true;
      try {
        const data = await api(`/api/music/tasks/${refreshButton.dataset.refreshTask}/refresh`, { method: "POST" });
        showCompact(data, false, "Task aktualisiert");
        await refreshAll(false);
      } catch (error) {
        showCompact({ error: error.message }, true, "Task aktualisieren");
      } finally {
        refreshButton.disabled = false;
      }
    }

    const deleteButton = event.target.closest("[data-delete-task]");
    if (deleteButton) {
      if (!confirm("Diesen lokalen Task löschen?")) return;
      await api(`/api/music/tasks/${deleteButton.dataset.deleteTask}`, { method: "DELETE" });
      selectedArchiveItems.delete(archiveRef("task", deleteButton.dataset.deleteTask));
      await refreshAll(false);
      notify("Task gelöscht");
    }

    const editTitleButton = event.target.closest("[data-edit-title-type][data-edit-title-id]");
    if (editTitleButton) {
      event.preventDefault();
      event.stopPropagation();
      await editContentTitle(
        editTitleButton.dataset.editTitleType,
        editTitleButton.dataset.editTitleId,
        editTitleButton.dataset.currentTitle || ""
      );
      return;
    }

    const deleteContentButton = event.target.closest("[data-delete-content-type][data-delete-content-id]");
    if (deleteContentButton) {
      const type = deleteContentButton.dataset.deleteContentType;
      const id = deleteContentButton.dataset.deleteContentId;
      if (!confirm("Diesen Inhalt in den Papierkorb verschieben? Er kann später wiederhergestellt werden.")) return;
      await api(`/api/library/content/${encodeURIComponent(type)}/${encodeURIComponent(id)}?delete_files=true`, { method: "DELETE" });
      selectedArchiveItems.delete(archiveRef(type, id));
      await refreshAll(false);
      notify("Inhalt in Papierkorb verschoben");
      return;
    }

    const restoreContentButton = event.target.closest("[data-restore-content-type][data-restore-content-id]");
    if (restoreContentButton) {
      const type = restoreContentButton.dataset.restoreContentType;
      const id = restoreContentButton.dataset.restoreContentId;
      await api(`/api/library/content/${encodeURIComponent(type)}/${encodeURIComponent(id)}/restore`, { method: "POST" });
      selectedArchiveItems.delete(archiveRef(type, id));
      await refreshAll(false);
      notify("Inhalt wiederhergestellt");
      return;
    }

    const purgeContentButton = event.target.closest("[data-purge-content-type][data-purge-content-id]");
    if (purgeContentButton) {
      const type = purgeContentButton.dataset.purgeContentType;
      const id = purgeContentButton.dataset.purgeContentId;
      if (!confirm("Diesen Inhalt endgültig löschen? Diese Aktion kann nicht rückgängig gemacht werden.")) return;
      await api(`/api/library/content/${encodeURIComponent(type)}/${encodeURIComponent(id)}/purge?delete_files=true`, { method: "DELETE" });
      selectedArchiveItems.delete(archiveRef(type, id));
      await refreshAll(false);
      notify("Inhalt endgültig gelöscht");
      return;
    }

    const trashRefreshButton = event.target.closest("#btnArchiveRefreshTrash");
    if (trashRefreshButton) {
      await refreshTrashItems();
      renderArchive();
      notify("Papierkorb aktualisiert");
      return;
    }

    const backToLibraryButton = event.target.closest("[data-back-to-library]");
    if (backToLibraryButton) {
      event.preventDefault();
      event.stopPropagation();
      currentArchiveProjectKey = null;
      renderArchive();
      return;
    }

    const projectDetailNavButton = event.target.closest("[data-project-detail-nav]");
    if (projectDetailNavButton) {
      event.preventDefault();
      event.stopPropagation();
      const targetKey = projectDetailNavButton.dataset.projectDetailNav;
      if (targetKey) {
        currentArchiveProjectKey = targetKey;
        renderArchive();
        archiveList?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
      return;
    }


    const saveLyricsButton = event.target.closest("[data-save-lyrics-from-asset]");
    if (saveLyricsButton) {
      event.preventDefault();
      event.stopPropagation();
      const asset = findAudioAsset(saveLyricsButton.dataset.saveLyricsFromAsset);
      if (!asset) return;
      const task = taskForItem("audio", asset);
      const text = libraryPromptForAudio(asset) || libraryLyricsForAudio(asset);
      if (!text) { notify("Kein Songtext/Prompt zum Speichern gefunden", true); return; }
      await api("/api/library/lyrics", { method: "POST", body: JSON.stringify({ title: getAssetDisplayTitle(asset), content: text, tags: tagsForEntry("audio", asset) || "" }) });
      await refreshLyrics();
      notify("Songtext wurde unter Songtexte gespeichert");
      return;
    }

    const miniPlayButton = event.target.closest("[data-mini-play]");
    if (miniPlayButton) {
      event.preventDefault();
      event.stopPropagation();
      currentMiniPlayerScope = miniPlayButton.dataset.miniPlayScope || "project";
      openMiniPlayer(miniPlayButton.dataset.miniPlay);
      return;
    }

    const openProjectDetailButton = event.target.closest("[data-open-project-detail]");
    if (openProjectDetailButton) {
      event.preventDefault();
      event.stopPropagation();
      currentArchiveProjectKey = openProjectDetailButton.dataset.openProjectDetail;
      renderArchive();
      return;
    }

    if (event.target.closest("[data-mini-prev]")) {
      event.preventDefault();
      event.stopPropagation();
      playRelativeMiniPlayer(-1);
      return;
    }

    if (event.target.closest("[data-mini-next]")) {
      event.preventDefault();
      event.stopPropagation();
      playRelativeMiniPlayer(1);
      return;
    }

    if (event.target.closest("[data-mini-loop]")) {
      event.preventDefault();
      event.stopPropagation();
      toggleMiniPlayerLoop();
      return;
    }

    if (event.target.closest("[data-close-mini-player]")) {
      event.preventDefault();
      event.stopPropagation();
      closeMiniPlayer();
      return;
    }

    const favoriteButton = event.target.closest("[data-mark-favorite]");
    if (favoriteButton) {
      event.preventDefault();
      event.stopPropagation();
      await api(`/api/production/audio/${favoriteButton.dataset.markFavorite}/favorite`, { method: "POST" });
      await refreshAll(false);
      notify("Favorit aktualisiert");
      return;
    }

    const finalButton = event.target.closest("[data-mark-final]");
    if (finalButton) {
      event.preventDefault();
      event.stopPropagation();
      await api(`/api/production/audio/${finalButton.dataset.markFinal}/final`, { method: "POST" });
      await refreshAll(false);
      notify("Finale Version markiert");
      return;
    }

    const autoGroupButton = event.target.closest("[data-auto-group-projects]");
    if (autoGroupButton) {
      const data = await api("/api/production/auto-group", { method: "POST" });
      await refreshAll(false);
      notify(`Projekte aktualisiert: ${data.updated_audio_assets || 0}`);
      return;
    }

    const createProjectButton = event.target.closest("[data-create-project-from-asset]");
    if (createProjectButton && createProjectButton.dataset.createProjectFromAsset) {
      event.preventDefault();
      event.stopPropagation();
      const asset = findAudioAsset(createProjectButton.dataset.createProjectFromAsset);
      if (!asset) return;
      const title = prompt("Projektname", getAssetProjectTitle(asset));
      if (!title) return;
      const project = await api("/api/production/projects", { method: "POST", body: JSON.stringify({ title, cover_image_url: asset.image_url || null }) });
      await api(`/api/production/projects/${project.id}/assets/${asset.id}`, { method: "POST" });
      await refreshAll(false);
      notify("Projekt erstellt");
      return;
    }

    const profileButton = event.target.closest("[data-apply-production-profile]");
    if (profileButton) {
      applyProductionProfile(profileButton.dataset.applyProductionProfile);
      return;
    }

    const audioActionButton = event.target.closest("[data-audio-action]");
    if (audioActionButton) {
      event.preventDefault();
      event.stopPropagation();
      audioActionButton.disabled = true;
      try {
        await runArchiveAudioQuickAction(audioActionButton.dataset.assetId, audioActionButton.dataset.audioAction);
      } catch (error) {
        showCompact({ error: error.message }, true, "Archiv-Audio-Aktion");
      } finally {
        audioActionButton.disabled = false;
      }
      return;
    }

    const vocalTagButton = event.target.closest("[data-insert-vocal-tag]");
    if (vocalTagButton) {
      const field = document.querySelector("#lyricDraftContent");
      if (field) {
        const tag = vocalTagButton.dataset.insertVocalTag || "";
        const start = field.selectionStart || field.value.length;
        const end = field.selectionEnd || field.value.length;
        const before = field.value.slice(0, start);
        const after = field.value.slice(end);
        field.value = `${before}${before && !before.endsWith("\n") ? "\n" : ""}${tag}\n${after}`;
        field.focus();
        field.dispatchEvent(new Event("input", { bubbles: true }));
      }
      return;
    }

    const loadDraftButton = event.target.closest("[data-load-lyric-draft]");
    if (loadDraftButton) {
      loadLyricDraftToEditor(loadDraftButton.dataset.loadLyricDraft);
      return;
    }

    const sendLyricToMusicButton = event.target.closest("[data-send-lyric-to-music]");
    if (sendLyricToMusicButton) {
      event.preventDefault();
      event.stopPropagation();
      sendLyricDraftByIdToMusic(sendLyricToMusicButton.dataset.sendLyricToMusic);
      return;
    }

    const deleteLyricDraftButton = event.target.closest("[data-delete-lyric-draft]");
    if (deleteLyricDraftButton) {
      event.preventDefault();
      event.stopPropagation();
      if (!confirm("Diesen Songtext in den Papierkorb verschieben?")) return;
      await api(`/api/library/lyrics/${deleteLyricDraftButton.dataset.deleteLyricDraft}`, { method: "DELETE" });
      await refreshLyricDrafts();
      renderArchive();
      notify("Songtext gelöscht");
      return;
    }

    const editStyleButton = event.target.closest("[data-edit-style]");
    if (editStyleButton) {
      loadStyleToEditor(editStyleButton.dataset.editStyle);
      return;
    }

    const saveAdminUserButton = event.target.closest("[data-save-admin-user]");
    if (saveAdminUserButton) {
      await saveAdminUser(saveAdminUserButton.dataset.saveAdminUser);
      return;
    }

    const editAdminAiProfileButton = event.target.closest("[data-edit-admin-ai-profile]");
    if (editAdminAiProfileButton) {
      loadAdminAiProfileToForm(editAdminAiProfileButton.dataset.editAdminAiProfile);
      return;
    }

    const deleteAdminAiProfileButton = event.target.closest("[data-delete-admin-ai-profile]");
    if (deleteAdminAiProfileButton) {
      if (!confirm("KI-Profil wirklich löschen?")) return;
      await api(`/api/admin/ai-profiles/${deleteAdminAiProfileButton.dataset.deleteAdminAiProfile}`, { method: "DELETE" });
      await refreshAdminPanel();
      await loadAiConfig();
      return;
    }

    const editAdminInstructionButton = event.target.closest("[data-edit-admin-instruction]");
    if (editAdminInstructionButton) {
      loadAdminInstructionToForm(editAdminInstructionButton.dataset.editAdminInstruction);
      return;
    }

    const deleteAdminInstructionButton = event.target.closest("[data-delete-admin-instruction]");
    if (deleteAdminInstructionButton) {
      if (!confirm("Instruction-Datei wirklich löschen?")) return;
      await api(`/api/admin/instruction-files/${deleteAdminInstructionButton.dataset.deleteAdminInstruction}`, { method: "DELETE" });
      await refreshAdminPanel();
      return;
    }

    const editAdminVocalTagButton = event.target.closest("[data-edit-admin-vocal-tag]");
    if (editAdminVocalTagButton) {
      loadAdminVocalTagToForm(editAdminVocalTagButton.dataset.editAdminVocalTag);
      return;
    }

    const deleteAdminVocalTagButton = event.target.closest("[data-delete-admin-vocal-tag]");
    if (deleteAdminVocalTagButton) {
      if (!confirm("Diesen Vocal Tag löschen?")) return;
      await api(`/api/admin/vocal-tags/${deleteAdminVocalTagButton.dataset.deleteAdminVocalTag}`, { method: "DELETE" });
      cachedAdminVocalTags = await api("/api/admin/vocal-tags");
      renderAdminVocalTags(cachedAdminVocalTags);
      await refreshVocalTags();
      notify("Vocal Tag gelöscht");
      return;
    }

    const reusePromptButton = event.target.closest("[data-reuse-prompt-asset]");
    if (reusePromptButton) {
      reusePromptFromAsset(reusePromptButton.dataset.reusePromptAsset);
      return;
    }

    const useStyleButton = event.target.closest("[data-use-style]");
    if (useStyleButton) {
      await useMusicStyle(useStyleButton.dataset.useStyle, useStyleButton.dataset.target || "music");
      return;
    }

    const deleteProductionProfileButton = event.target.closest("[data-delete-production-profile]");
    if (deleteProductionProfileButton) {
      if (!confirm("Dieses Produktionsprofil löschen?")) return;
      await api(`/api/production/profiles/${deleteProductionProfileButton.dataset.deleteProductionProfile}`, { method: "DELETE" });
      await refreshProductionProfiles();
      renderProductionProfiles();
      notify("Produktionsprofil gelöscht");
      return;
    }

    const deleteStyleButton = event.target.closest("[data-delete-style]");
    if (deleteStyleButton) {
      if (!confirm("Diesen Music Style löschen?")) return;
      await api(`/api/library/styles/${deleteStyleButton.dataset.deleteStyle}`, { method: "DELETE" });
      await refreshMusicStyles();
      notify("Style gelöscht");
      return;
    }


    const openPlaylistPlayerButton = event.target.closest("[data-open-playlist-player]");
    if (openPlaylistPlayerButton) {
      event.preventDefault();
      openPlaylistPlayer(openPlaylistPlayerButton.dataset.openPlaylistPlayer);
      return;
    }

    if (event.target.closest("[data-close-playlist-player]")) {
      event.preventDefault();
      closePlaylistPlayer();
      return;
    }

    if (event.target.closest("[data-playlist-prev]")) { playlistModalState.index = Math.max(0, playlistModalState.index - 1); renderPlaylistPlayerModal(); return; }
    if (event.target.closest("[data-playlist-next]")) { playlistModalState.index += 1; renderPlaylistPlayerModal(); return; }
    if (event.target.closest("[data-playlist-loop-one]")) { playlistModalState.loopMode = playlistModalState.loopMode === "one" ? "none" : "one"; renderPlaylistPlayerModal(); return; }
    if (event.target.closest("[data-playlist-loop-all]")) { playlistModalState.loopMode = playlistModalState.loopMode === "all" ? "none" : "all"; renderPlaylistPlayerModal(); return; }
    const playlistJumpButton = event.target.closest("[data-playlist-jump]");
    if (playlistJumpButton) { playlistModalState.index = Number(playlistJumpButton.dataset.playlistJump || 0); renderPlaylistPlayerModal(); return; }

    const deletePlaylistButton = event.target.closest("[data-delete-playlist]");
    if (deletePlaylistButton) {
      if (!confirm("Diese Playlist löschen?")) return;
      await api(`/api/library/playlists/${deletePlaylistButton.dataset.deletePlaylist}`, { method: "DELETE" });
      await refreshPlaylists();
      notify("Playlist gelöscht");
      return;
    }

    const deletePlaylistItemButton = event.target.closest("[data-delete-playlist-item]");
    if (deletePlaylistItemButton) {
      await api(`/api/library/playlists/${deletePlaylistItemButton.dataset.playlistId}/items/${deletePlaylistItemButton.dataset.deletePlaylistItem}`, { method: "DELETE" });
      await refreshPlaylists();
      notify("Track aus Playlist entfernt");
      return;
    }

    const archiveButton = event.target.closest("button[data-open-archive], a[data-open-archive], [role='button'][data-open-archive]");
    if (archiveButton) {
      event.preventDefault();
      event.stopPropagation();
      switchTab("tab-archive");
      openArchiveEntry(archiveButton.dataset.openArchive);
      return;
    }
  });

  document.addEventListener("change", async event => {
    const notificationCheckbox = event.target.closest("[data-notification-select]");
    if (notificationCheckbox) {
      const id = String(notificationCheckbox.dataset.notificationSelect);
      if (notificationCheckbox.checked) selectedNotifications.add(id);
      else selectedNotifications.delete(id);
      renderStatusNotifications();
      return;
    }

    const archiveCheckbox = event.target.closest("[data-archive-select]");
    if (archiveCheckbox) {
      const ref = archiveCheckbox.dataset.archiveSelect;
      if (archiveCheckbox.checked) selectedArchiveItems.add(ref);
      else selectedArchiveItems.delete(ref);
      updateArchiveSelectionBar();
      return;
    }

    const select = event.target.closest("[data-playlist-add-select]");
    if (!select || !select.value) return;
    const assetId = select.dataset.playlistAddSelect;
    const playlistId = select.value;
    await api(`/api/library/playlists/${playlistId}/items`, {
      method: "POST",
      body: JSON.stringify({ audio_asset_id: Number(assetId) })
    });
    select.value = "";
    await refreshPlaylists();
    notify("Audio zur Playlist hinzugefügt");
  });

  const mobileMenuButton = document.getElementById("btnMobileTabMenu");
  const tabNav = document.getElementById("mainTabNav");
  if (mobileMenuButton && tabNav) {
    mobileMenuButton.addEventListener("click", () => {
      const willOpen = !tabNav.classList.contains("is-open");
      tabNav.classList.toggle("is-open", willOpen);
      mobileMenuButton.setAttribute("aria-expanded", String(willOpen));
      mobileMenuButton.textContent = willOpen ? "✕ Menü schließen" : "☰ Menü öffnen";
    });
  }

  document.querySelectorAll(".tab-group-trigger").forEach(trigger => trigger.addEventListener("click", () => {
    const group = trigger.closest(".tab-group");
    if (!group) return;
    const willOpen = !group.classList.contains("is-open");
    document.querySelectorAll(".tab-group").forEach(item => {
      item.classList.remove("is-open");
      item.querySelector(".tab-group-trigger")?.setAttribute("aria-expanded", "false");
    });
    group.classList.toggle("is-open", willOpen);
    trigger.setAttribute("aria-expanded", String(willOpen));
  }));

  document.querySelectorAll(".tab-button").forEach(button => button.addEventListener("click", () => {
    if (button.dataset.tab === "tab-archive") currentArchiveProjectKey = null;
    switchTab(button.dataset.tab);
  }));
}

async function init() {
  ensureAuthOverlay();
  await loadCurrentUser();
  bindEvents();
  restoreLyricStudioView();
  try { await loadRuntimeConfig(); } catch (error) { showCompact({ error: error.message }, true, "Konfiguration laden"); }
  try { await loadAiConfig(); await loadAiSessions(); } catch (error) { console.warn("KI-Chat-Konfiguration konnte nicht geladen werden", error); }
  const savedTab = localStorage.getItem("activeSunoTab") || "tab-home";
  switchTab(document.getElementById(savedTab) ? savedTab : "tab-music");
  await refreshAll(false).catch(error => showCompact({ error: error.message }, true, "Initialisierung"));
}

init();
