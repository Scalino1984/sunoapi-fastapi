export class ApiError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload;
  }
}

async function parseResponse(response) {
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    return response.json();
  }
  return response.text();
}

function apiUiLanguage() {
  try {
    return String(document?.documentElement?.lang || navigator?.language || 'de').toLowerCase().startsWith('en') ? 'en' : 'de';
  } catch (_) {
    return 'de';
  }
}

function apiTimeoutMessage(path) {
  return apiUiLanguage() === 'en' ? `API request timed out: ${path}` : `Zeitüberschreitung bei API-Aufruf: ${path}`;
}

export function getStoredAccessToken() {
  try {
    return window.localStorage.getItem('suno_access_token') || '';
  } catch (_) {
    return '';
  }
}

export function setStoredAccessToken(token) {
  try {
    if (token) window.localStorage.setItem('suno_access_token', token);
    else window.localStorage.removeItem('suno_access_token');
  } catch (_) {
    // LocalStorage ist optional. Die HttpOnly-Cookie-Session bleibt der Hauptweg.
  }
}


function stringifyApiErrorDetail(value) {
  if (value === null || value === undefined || value === '') return '';
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) {
    return value.map((item) => stringifyApiErrorDetail(item)).filter(Boolean).join(' | ');
  }
  if (typeof value === 'object') {
    const loc = Array.isArray(value.loc) ? value.loc.join('.') : '';
    const msg = value.msg || value.message || value.detail || value.error || '';
    const type = value.type || '';
    const combined = [loc, msg, type && !String(msg).includes(String(type)) ? `(${type})` : ''].filter(Boolean).join(': ');
    if (combined) return combined;
    try { return JSON.stringify(value); } catch (_) { return String(value); }
  }
  return String(value);
}

function apiErrorMessageFromPayload(payload, fallback) {
  if (payload && typeof payload === 'object') {
    const detail = stringifyApiErrorDetail(payload.detail);
    if (detail) return detail;
    const error = stringifyApiErrorDetail(payload.error);
    if (error) return error;
    const message = stringifyApiErrorDetail(payload.message);
    if (message) return message;
  }
  if (typeof payload === 'string' && payload.trim()) return payload.trim();
  return fallback;
}

export async function apiFetch(path, options = {}) {
  const storedToken = getStoredAccessToken();
  const { timeoutMs = 0, signal: callerSignal, ...fetchOptions } = options || {};
  const userHeaders = fetchOptions.headers || {};
  const hasExplicitAuth = Object.keys(userHeaders).some((key) => key.toLowerCase() === 'authorization');
  const headers = {
    Accept: 'application/json',
    ...(fetchOptions.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
    ...(storedToken && !hasExplicitAuth ? { Authorization: `Bearer ${storedToken}` } : {}),
    ...userHeaders
  };

  let timeoutId = null;
  const controller = timeoutMs ? new AbortController() : null;
  if (controller && callerSignal) {
    if (callerSignal.aborted) controller.abort(callerSignal.reason);
    else callerSignal.addEventListener('abort', () => controller.abort(callerSignal.reason), { once: true });
  }
  if (controller && timeoutMs) {
    timeoutId = window.setTimeout(() => controller.abort(new DOMException('Request timeout', 'TimeoutError')), Number(timeoutMs));
  }

  let response;
  try {
    response = await fetch(path, {
      ...fetchOptions,
      credentials: 'include',
      headers,
      signal: controller?.signal || callerSignal
    });
  } catch (err) {
    if (err?.name === 'AbortError' || err?.name === 'TimeoutError') {
      throw new ApiError(apiTimeoutMessage(path), 408, { path, timeoutMs });
    }
    throw err;
  } finally {
    if (timeoutId) window.clearTimeout(timeoutId);
  }

  const payload = await parseResponse(response);

  if (!response.ok) {
    if (response.status === 401) setStoredAccessToken('');
    const message = apiErrorMessageFromPayload(payload, `HTTP ${response.status}`);
    throw new ApiError(message, response.status, payload);
  }

  return payload;
}

export async function apiFetchBlob(path, options = {}) {
  const storedToken = getStoredAccessToken();
  const userHeaders = options.headers || {};
  const hasExplicitAuth = Object.keys(userHeaders).some((key) => key.toLowerCase() === 'authorization');
  const headers = {
    Accept: 'application/zip,application/octet-stream,*/*',
    ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
    ...(storedToken && !hasExplicitAuth ? { Authorization: `Bearer ${storedToken}` } : {}),
    ...userHeaders
  };
  const response = await fetch(path, { ...options, credentials: 'include', headers });
  if (!response.ok) {
    let payload = null;
    try { payload = await response.json(); } catch (_) { payload = await response.text().catch(() => null); }
    if (response.status === 401) setStoredAccessToken('');
    const message = apiErrorMessageFromPayload(payload, `HTTP ${response.status}`);
    throw new ApiError(message, response.status, payload);
  }
  const disposition = response.headers.get('content-disposition') || '';
  const match = disposition.match(/filename\*?=(?:UTF-8''|\")?([^\";]+)/i);
  const filename = match ? decodeURIComponent(match[1].replace(/\"/g, '').trim()) : 'download.zip';
  return { blob: await response.blob(), filename };
}

export const api = {
  auth: {
    me: () => apiFetch('/auth/me', { timeoutMs: 8000 }),
    refresh: async () => {
      const tokenPayload = await apiFetch('/auth/refresh', { method: 'POST' });
      setStoredAccessToken(tokenPayload?.access_token || '');
      return tokenPayload;
    },
    login: async (email, password) => {
      const tokenPayload = await apiFetch('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) });
      setStoredAccessToken(tokenPayload?.access_token || '');
      return tokenPayload;
    },
    updateProfile: (payload) => apiFetch('/auth/profile', { method: 'PUT', body: JSON.stringify(payload) }),
    changePassword: (payload) => apiFetch('/auth/change-password', { method: 'POST', body: JSON.stringify(payload) }),
    logout: async () => {
      try {
        return await apiFetch('/auth/logout', { method: 'POST' });
      } finally {
        setStoredAccessToken('');
      }
    },
    register: (email, password) => apiFetch('/auth/register', { method: 'POST', body: JSON.stringify({ email, password }) })
  },
  credits: () => apiFetch('/api/credits', { timeoutMs: 8000 }),
  runtimeConfig: () => apiFetch('/api/music/runtime-config', { timeoutMs: 8000 }),
  archive: {
    audio: () => apiFetch(`/api/archive/audio?v=${Date.now()}`, { cache: 'no-store', timeoutMs: 15000 }),
    importManualAudio: (formData) => apiFetch('/api/audio-assets/manual-import', { method: 'POST', body: formData }),
    updateLyrics: (id, payload = {}) => apiFetch(`/api/audio-assets/${id}/lyrics`, { method: 'PATCH', body: JSON.stringify(payload) }),
    convertToWav: (id, payload = {}) => apiFetch(`/api/audio-assets/${id}/wav/convert`, { method: 'POST', body: JSON.stringify(payload) }),
    setFavorite: (id, isFavorite = true) => apiFetch(`/api/audio-assets/${id}/favorite`, { method: 'PATCH', body: JSON.stringify({ is_favorite: Boolean(isFavorite) }) }),
    favorites: () => apiFetch(`/api/audio-assets/favorites?v=${Date.now()}`, { cache: 'no-store' }),
    wavDownloadUrl: (id) => `/api/audio-assets/${id}/wav/download`,
    cacheMissingCovers: () => apiFetch('/api/archive/covers/cache-missing', { method: 'POST' }),
    cacheMissingContent: () => apiFetch('/api/archive/content/cache-missing', { method: 'POST' }),
    materializeFromTasks: (limit = 80) => apiFetch(`/api/archive/audio/materialize-from-tasks?limit=${encodeURIComponent(limit)}`, { method: 'POST' }),
    preparePlayback: (id) => apiFetch(`/api/archive/audio/${id}/prepare-playback`, { method: 'POST', timeoutMs: 30000 }),
    streamUrl: (id) => `/api/archive/audio/${id}/stream`,
    downloadUrl: (id) => `/api/archive/audio/${id}/download`,
    waveform: (id) => apiFetch(`/api/archive/audio/${id}/waveform?points=180`),
    rebuildWaveform: (id) => apiFetch(`/api/archive/audio/${id}/waveform/rebuild?points=180`, { method: 'POST' }),
    getTimestampedLyrics: (id) => apiFetch(`/api/archive/audio/${id}/timestamped-lyrics`),
    timestampedLyrics: (id) => apiFetch(`/api/archive/audio/${id}/timestamped-lyrics`, { method: 'POST' }),
    getSrt: (id) => apiFetch(`/api/audio-assets/${id}/srt?v=${Date.now()}`, { cache: 'no-store' }),
    generateSrt: (id, payload = {}) => apiFetch(`/api/audio-assets/${id}/srt/generate`, { method: 'POST', body: JSON.stringify(payload) }),
    bulkGenerateSrt: (ids = [], payload = {}) => apiFetch('/api/audio-assets/bulk/srt/generate', { method: 'POST', body: JSON.stringify({ ...payload, ids }) }),
    bulkGenerateStems: (ids = []) => apiFetch('/api/audio-assets/bulk/stems/generate', { method: 'POST', body: JSON.stringify({ ids }) }),
    updateSrt: (id, payload = {}) => apiFetch(`/api/audio-assets/${id}/srt`, { method: 'PUT', body: JSON.stringify(payload) }),
    deleteAssetContent: (id, kind) => apiFetch(`/api/audio-assets/${id}/content/${encodeURIComponent(kind)}`, { method: 'DELETE', body: JSON.stringify({ confirm: true }) }),
    getStems: (id) => apiFetch(`/api/audio-assets/${id}/stems`),
    generateStems: (id) => apiFetch(`/api/audio-assets/${id}/stems/generate`, { method: 'POST' }),
    stemsDownloadUrl: (id) => `/api/audio-assets/${id}/stems/download`,
    stemDownloadUrl: (id, kind) => `/api/audio-assets/${id}/stems/${encodeURIComponent(kind)}/download`,
    stemStreamUrl: (id, kind) => `/api/audio-assets/${id}/stems/${encodeURIComponent(kind)}/stream`,
    getAudioAiAnalysis: (id) => apiFetch(`/api/audio-assets/${id}/analysis?v=${Date.now()}`, { cache: 'no-store' }),
    generateAudioAiAnalysis: (id, payload = {}) => apiFetch(`/api/audio-assets/${id}/analysis/generate`, { method: 'POST', body: JSON.stringify(payload) }),
    audioAiAnalysisExportUrl: (id, kind) => `/api/audio-assets/${id}/analysis/export/${encodeURIComponent(kind)}`,
    getAiTags: (id) => apiFetch(`/api/audio-assets/${id}/ai-tags?v=${Date.now()}`, { cache: 'no-store' }),
    generateAiTags: (id, payload = {}) => apiFetch(`/api/audio-assets/${id}/ai-tags/generate`, { method: 'POST', body: JSON.stringify(payload) }),
    bulkGenerateAiTags: (ids = [], payload = {}) => apiFetch('/api/audio-assets/bulk/ai-tags/generate', { method: 'POST', body: JSON.stringify({ ...payload, ids }) }),
    srtDownloadUrl: (id) => `/api/audio-assets/${id}/srt/download`,
    srtHalfDownloadUrl: (id) => `/api/audio-assets/${id}/srt/half/download`,
    videos: (id) => apiFetch(`/api/audio-assets/${id}/videos?v=${Date.now()}`, { cache: 'no-store' }),
    video: (id, videoId) => apiFetch(`/api/audio-assets/${id}/videos/${videoId}?v=${Date.now()}`, { cache: 'no-store' }),
    cacheVideo: (id, videoId) => apiFetch(`/api/audio-assets/${id}/videos/${videoId}/cache`, { method: 'POST', timeoutMs: 300000 }),
    videoStreamUrl: (id, videoId) => `/api/audio-assets/${id}/videos/${videoId}/stream`,
    videoDownloadUrl: (id, videoId) => `/api/audio-assets/${id}/videos/${videoId}/download`,
    assetBundleUrl: (id, include = null) => {
      const selected = Array.isArray(include) ? include.filter(Boolean).join(',') : String(include || '').trim();
      return `/api/audio-assets/${id}/bundle/download${selected ? `?include=${encodeURIComponent(selected)}` : ''}`;
    },
    bulkAssetBundleUrl: (ids = [], include = null) => {
      const selectedIds = (Array.isArray(ids) ? ids : String(ids || '').split(',')).map((id) => String(id || '').trim()).filter(Boolean).join(',');
      const selected = Array.isArray(include) ? include.filter(Boolean).join(',') : String(include || '').trim();
      const params = new URLSearchParams();
      params.set('ids', selectedIds);
      if (selected) params.set('include', selected);
      return `/api/audio-assets/bulk/bundle/download?${params.toString()}`;
    },
    extend: (id, payload) => apiFetch(`/api/archive/audio/${id}/extend`, { method: 'POST', body: JSON.stringify(payload) }),
    analyzeExtendContinueAt: (id) => apiFetch(`/api/archive/audio/${id}/extend/analyze-continue-at`, { method: 'POST', timeoutMs: 300000 }),
    coverSong: (id, payload) => apiFetch(`/api/archive/audio/${id}/cover-song`, { method: 'POST', body: JSON.stringify(payload) }),
    addVocals: (id, payload) => apiFetch(`/api/archive/audio/${id}/add-vocals`, { method: 'POST', body: JSON.stringify(payload) }),
    addInstrumental: (id, payload) => apiFetch(`/api/archive/audio/${id}/add-instrumental`, { method: 'POST', body: JSON.stringify(payload) }),
    createPersona: (id, payload) => apiFetch(`/api/archive/audio/${id}/create-persona`, { method: 'POST', body: JSON.stringify(payload) }),
    createCoverImage: (id, payload) => apiFetch(`/api/archive/audio/${id}/create-cover-image`, { method: 'POST', body: JSON.stringify(payload) }),
    generateAiCover: (id, formData) => apiFetch(`/api/archive/audio/${id}/generate-ai-cover`, { method: 'POST', body: formData })
  },
  music: {
    generate: (payload) => apiFetch('/api/music/generate', { method: 'POST', body: JSON.stringify(payload) }),
    generateOpenCli: (payload) => apiFetch('/api/music/generate-opencli', { method: 'POST', body: JSON.stringify(payload) }),
    extend: (payload) => apiFetch('/api/music/extend', { method: 'POST', body: JSON.stringify(payload) }),
    uploadAndExtend: (payload) => apiFetch('/api/music/upload-and-extend', { method: 'POST', body: JSON.stringify(payload) }),
    uploadAndCover: (payload) => apiFetch('/api/music/upload-and-cover', { method: 'POST', body: JSON.stringify(payload) }),
    addInstrumental: (payload) => apiFetch('/api/music/add-instrumental', { method: 'POST', body: JSON.stringify(payload) }),
    addVocals: (payload) => apiFetch('/api/music/add-vocals', { method: 'POST', body: JSON.stringify(payload) }),
    sounds: (payload) => apiFetch('/api/music/sounds', { method: 'POST', body: JSON.stringify(payload) }),
    cover: (payload) => apiFetch('/api/music/cover', { method: 'POST', body: JSON.stringify(payload) }),
    replaceSection: (payload) => apiFetch('/api/music/replace-section', { method: 'POST', body: JSON.stringify(payload) }),
    persona: (payload) => apiFetch('/api/music/persona', { method: 'POST', body: JSON.stringify(payload) }),
    boostStyle: (payload) => apiFetch('/api/music/boost-style', { method: 'POST', body: JSON.stringify(payload) }),
    mashup: (payload) => apiFetch('/api/music/mashup', { method: 'POST', body: JSON.stringify(payload) }),
    video: (payload) => apiFetch('/api/music/video', { method: 'POST', body: JSON.stringify(payload) }),
    voiceValidate: (payload) => apiFetch('/api/music/voice/validate', { method: 'POST', body: JSON.stringify(payload) }),
    voiceValidateInfo: (taskId) => apiFetch(`/api/music/voice/validate-info?task_id=${encodeURIComponent(taskId)}`),
    voiceRegenerate: (payload) => apiFetch('/api/music/voice/regenerate', { method: 'POST', body: JSON.stringify(payload) }),
    voiceGenerate: (payload) => apiFetch('/api/music/voice/generate', { method: 'POST', body: JSON.stringify(payload) }),
    voiceRecordInfo: (taskId) => apiFetch(`/api/music/voice/record-info?task_id=${encodeURIComponent(taskId)}`),
    voiceCheckAvailability: (payload) => apiFetch('/api/music/voice/check-availability', { method: 'POST', body: JSON.stringify(payload) }),
    songs: (limit = 250) => apiFetch(`/api/music/songs?limit=${encodeURIComponent(limit)}&v=${Date.now()}`, { cache: 'no-store' }),
    syncSongsToLibrary: (payload = {}) => apiFetch('/api/music/songs/sync-library', { method: 'POST', body: JSON.stringify(payload || {}), timeoutMs: 120000 }),
    voices: () => apiFetch('/api/music/voices'),
    createVoice: (payload) => apiFetch('/api/music/voices', { method: 'POST', body: JSON.stringify(payload) }),
    updateVoice: (id, payload) => apiFetch(`/api/music/voices/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
    deleteVoice: (id) => apiFetch(`/api/music/voices/${id}`, { method: 'DELETE' }),
    tasks: () => apiFetch(`/api/music/tasks?v=${Date.now()}`, { cache: 'no-store', timeoutMs: 8000 }),
    getTask: (id) => apiFetch(`/api/music/tasks/${id}?v=${Date.now()}`, { cache: 'no-store', timeoutMs: 8000 }),
    refreshPending: () => apiFetch('/api/music/tasks/refresh-pending', { method: 'POST', timeoutMs: 25000 }),
    importFromSuno: (payload) => apiFetch('/api/music/tasks/import-from-suno', { method: 'POST', body: JSON.stringify(payload) }),
    importSongFromSuno: (payload) => apiFetch('/api/music/songs/import-from-suno', { method: 'POST', body: JSON.stringify(payload) }),
    importSongBatchFromSuno: (payload) => apiFetch('/api/music/songs/import-from-suno/batch', { method: 'POST', body: JSON.stringify(payload) }),
    importBatchFromSuno: (payload) => apiFetch('/api/music/tasks/import-from-suno/batch', { method: 'POST', body: JSON.stringify(payload) }),
    safeCheck: (payload) => apiFetch('/api/music/safe-check', { method: 'POST', body: JSON.stringify(payload) }),
    refreshTask: (id) => apiFetch(`/api/music/tasks/${id}/refresh`, { method: 'POST', timeoutMs: 25000 }),
    cancelTask: (id) => apiFetch(`/api/music/tasks/${id}/cancel`, { method: 'POST', timeoutMs: 8000 }),
    markTaskDone: (id) => apiFetch(`/api/music/tasks/${id}/mark-done`, { method: 'POST' }),
    deleteTask: (id) => apiFetch(`/api/music/tasks/${id}`, { method: 'DELETE' })
  },
  lyrics: {
    generate: (payload) => apiFetch('/api/lyrics/generate', { method: 'POST', body: JSON.stringify(payload) })
  },
  audio: {
    separate: (payload) => apiFetch('/api/audio/separate', { method: 'POST', body: JSON.stringify(payload) }),
    wav: (payload) => apiFetch('/api/audio/wav', { method: 'POST', body: JSON.stringify(payload) }),
    midi: (payload) => apiFetch('/api/audio/midi', { method: 'POST', body: JSON.stringify(payload) }),
    timestampedLyrics: (payload) => apiFetch('/api/audio/timestamped-lyrics', { method: 'POST', body: JSON.stringify(payload) })
  },

  files: {
    list: () => apiFetch('/api/files'),
    uploadUrl: (url) => apiFetch('/api/files/url', { method: 'POST', body: JSON.stringify({ url }) }),
    uploadBase64: (file, originalName = '') => apiFetch('/api/files/base64', { method: 'POST', body: JSON.stringify({ file, original_name: originalName || null }) }),
    uploadStream: (file) => {
      const formData = new FormData();
      formData.append('upload', file);
      return apiFetch('/api/files/stream', { method: 'POST', body: formData });
    }
  },
  library: {
    playlists: () => apiFetch('/api/library/playlists'),
    createPlaylist: (payload) => apiFetch('/api/library/playlists', { method: 'POST', body: JSON.stringify(payload) }),
    addPlaylistItem: (playlistId, payload) => apiFetch(`/api/library/playlists/${playlistId}/items`, { method: 'POST', body: JSON.stringify(payload) }),
    lyrics: () => apiFetch('/api/library/lyrics'),
    createLyric: (payload) => apiFetch('/api/library/lyrics', { method: 'POST', body: JSON.stringify(payload) }),
    updateLyric: (id, payload) => apiFetch(`/api/library/lyrics/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
    styles: () => apiFetch('/api/library/styles'),
    createStyle: (payload) => apiFetch('/api/library/styles', { method: 'POST', body: JSON.stringify(payload) }),
    updateStyle: (id, payload) => apiFetch(`/api/library/styles/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
    useStyle: (id) => apiFetch(`/api/library/styles/${id}/use`, { method: 'POST' }),
    vocalTags: () => apiFetch('/api/library/vocal-tags'),
    // Aktive Library-Import/Export-Kette: diese Wrapper spiegeln app/routers/library.py.
    // Nicht über alte Direktrouten oder lokale CSV-Helfer umgehen, sonst laufen aktive Seiten ins Leere.
    exportLyrics: (format = 'csv', mode = 'extended') => apiFetchBlob(`/api/library/export/lyrics?format=${encodeURIComponent(format)}&mode=${encodeURIComponent(mode)}`, { method: 'GET' }),
    importLyrics: (file, format = 'auto') => {
      const formData = new FormData();
      formData.append('file', file);
      return apiFetch(`/api/library/import/lyrics?format=${encodeURIComponent(format)}`, { method: 'POST', body: formData });
    },
    exportPlaylists: (format = 'csv', mode = 'extended') => apiFetchBlob(`/api/library/export/playlists?format=${encodeURIComponent(format)}&mode=${encodeURIComponent(mode)}`, { method: 'GET' }),
    importPlaylists: (file, format = 'auto') => {
      const formData = new FormData();
      formData.append('file', file);
      return apiFetch(`/api/library/import/playlists?format=${encodeURIComponent(format)}`, { method: 'POST', body: formData });
    },
    exportStyles: (format = 'csv', mode = 'extended') => apiFetchBlob(`/api/library/export/styles?format=${encodeURIComponent(format)}&mode=${encodeURIComponent(mode)}`, { method: 'GET' }),
    importStyles: (file, format = 'auto') => {
      const formData = new FormData();
      formData.append('file', file);
      return apiFetch(`/api/library/import/styles?format=${encodeURIComponent(format)}`, { method: 'POST', body: formData });
    },
    exportVocalTags: (format = 'csv', mode = 'extended') => apiFetchBlob(`/api/library/export/vocal-tags?format=${encodeURIComponent(format)}&mode=${encodeURIComponent(mode)}`, { method: 'GET' }),
    importVocalTags: (file, format = 'auto') => {
      const formData = new FormData();
      formData.append('file', file);
      return apiFetch(`/api/library/import/vocal-tags?format=${encodeURIComponent(format)}`, { method: 'POST', body: formData });
    },
    updateTitle: (type, id, title) => apiFetch(`/api/library/content/${type}/${id}/title`, { method: 'PATCH', body: JSON.stringify({ title }) }),
    updateCover: (type, id, formData) => apiFetch(`/api/library/content/${type}/${id}/cover`, { method: 'POST', body: formData }),
    deleteContent: (type, id) => apiFetch(`/api/library/content/${type}/${id}`, { method: 'DELETE' }),
    bulkDeleteContent: (payload) => apiFetch('/api/library/content/bulk-delete', { method: 'POST', body: JSON.stringify(payload) }),
    trash: ({ q = '', contentType = 'all', limit = 300 } = {}) => apiFetch(`/api/library/content/trash?q=${encodeURIComponent(q)}&content_type=${encodeURIComponent(contentType)}&limit=${encodeURIComponent(limit)}`),
    restoreContent: (type, id) => apiFetch(`/api/library/content/${type}/${id}/restore`, { method: 'POST' }),
    bulkRestoreContent: (payload) => apiFetch('/api/library/content/bulk-restore', { method: 'POST', body: JSON.stringify(payload) }),
    purgeContent: (type, id, deleteFiles = true) => apiFetch(`/api/library/content/${type}/${id}/purge?delete_files=${deleteFiles ? 'true' : 'false'}`, { method: 'DELETE' })
  },

  assistant: {
    chat: (payload) => apiFetch('/api/assistant/chat', { method: 'POST', body: JSON.stringify(payload) }),
    previewAction: (payload) => apiFetch('/api/assistant/actions/preview', { method: 'POST', body: JSON.stringify(payload) }),
    styleSuggestions: (payload) => apiFetch('/api/assistant/style-suggestions', { method: 'POST', body: JSON.stringify(payload) }),
    styleTaggedLyrics: (payload) => apiFetch('/api/assistant/style-tagged-lyrics', { method: 'POST', body: JSON.stringify(payload) }),
    styleConsultation: (payload) => apiFetch('/api/assistant/style-consultation', { method: 'POST', body: JSON.stringify(payload) }),
    runtime: (profileId = null) => apiFetch(`/api/assistant/runtime${profileId ? `?profile_id=${encodeURIComponent(profileId)}` : ''}`),
    actions: (activeTab = '') => apiFetch(`/api/assistant/actions?active_tab=${encodeURIComponent(activeTab)}`)
  },
  ai: {
    config: () => apiFetch('/api/ai-chat/config'),
    sessions: () => apiFetch('/api/ai-chat/sessions'),
    createSession: (payload) => apiFetch('/api/ai-chat/sessions', { method: 'POST', body: JSON.stringify(payload) }),
    getSession: (id) => apiFetch(`/api/ai-chat/sessions/${id}`),
    updateCanvas: (id, content, meta = {}) => apiFetch(`/api/ai-chat/sessions/${id}/canvas`, { method: 'POST', body: JSON.stringify({ canvas_content: content, source: meta.source || 'manual', change_summary: meta.change_summary || null }) }),
    updateSession: (id, payload) => apiFetch(`/api/ai-chat/sessions/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
    sendMessage: (id, message, options = {}) => apiFetch(`/api/ai-chat/sessions/${id}/messages`, { method: 'POST', body: JSON.stringify({ message, canvas_content: options.canvas_content || '', apply_to_canvas: Boolean(options.apply_to_canvas), work_mode: options.work_mode || null }) }),
    clearMessages: (id) => apiFetch(`/api/ai-chat/sessions/${id}/messages/clear`, { method: 'POST' }),
    undo: (id) => apiFetch(`/api/ai-chat/sessions/${id}/undo`, { method: 'POST' }),
    redo: (id) => apiFetch(`/api/ai-chat/sessions/${id}/redo`, { method: 'POST' })
  },
  admin: {
    users: () => apiFetch('/api/admin/users'),
    updateUser: (id, payload) => apiFetch(`/api/admin/users/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
    aiSettings: () => apiFetch('/api/admin/ai-settings'),
    saveAiSettings: (payload) => apiFetch('/api/admin/ai-settings', { method: 'PUT', body: JSON.stringify(payload) }),
    testAi: (payload) => apiFetch('/api/admin/ai-settings/test', { method: 'POST', body: JSON.stringify(payload) }),
    vocalTags: () => apiFetch('/api/admin/vocal-tags'),
    createVocalTag: (payload) => apiFetch('/api/admin/vocal-tags', { method: 'POST', body: JSON.stringify(payload) }),
    updateVocalTag: (id, payload) => apiFetch(`/api/admin/vocal-tags/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
    deleteVocalTag: (id) => apiFetch(`/api/admin/vocal-tags/${id}`, { method: 'DELETE' }),
    profiles: () => apiFetch('/api/admin/ai-profiles'),
    createProfile: (payload) => apiFetch('/api/admin/ai-profiles', { method: 'POST', body: JSON.stringify(payload) }),
    updateProfile: (id, payload) => apiFetch(`/api/admin/ai-profiles/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
    deleteProfile: (id) => apiFetch(`/api/admin/ai-profiles/${id}`, { method: 'DELETE' }),
    instructionFiles: () => apiFetch('/api/admin/instruction-files'),
    createInstructionFile: (payload) => apiFetch('/api/admin/instruction-files', { method: 'POST', body: JSON.stringify(payload) }),
    deleteInstructionFile: (id) => apiFetch(`/api/admin/instruction-files/${id}`, { method: 'DELETE' }),
    dawPromptHooks: (includeInactive = true) => apiFetch(`/api/admin/daw-prompt-hooks?include_inactive=${includeInactive ? 'true' : 'false'}`),
    createDawPromptHook: (payload) => apiFetch('/api/admin/daw-prompt-hooks', { method: 'POST', body: JSON.stringify(payload) }),
    updateDawPromptHook: (id, payload) => apiFetch(`/api/admin/daw-prompt-hooks/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
    duplicateDawPromptHook: (id) => apiFetch(`/api/admin/daw-prompt-hooks/${id}/duplicate`, { method: 'POST' }),
    deleteDawPromptHook: (id) => apiFetch(`/api/admin/daw-prompt-hooks/${id}`, { method: 'DELETE' }),
    librarySearchIndex: ({ page = 1, pageSize = 50, search = '', status = 'all' } = {}) => {
      const params = new URLSearchParams();
      params.set('page', String(page));
      params.set('page_size', String(pageSize));
      params.set('search', String(search || ''));
      params.set('status', String(status || 'all'));
      return apiFetch(`/api/admin/library-search-index?${params.toString()}`, { cache: 'no-store' });
    },
    updateLibrarySearchIndex: (id, payload) => apiFetch(`/api/admin/library-search-index/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
    deleteLibrarySearchIndex: (id) => apiFetch(`/api/admin/library-search-index/${id}`, { method: 'DELETE' })
  },

  daw: {
    project: (id) => apiFetch(`/api/daw/assets/${id}`),
    render: (payload) => apiFetch('/api/daw/render', { method: 'POST', body: JSON.stringify(payload) }),
    preview: (payload) => apiFetchBlob('/api/daw/preview', { method: 'POST', body: JSON.stringify(payload) }),
    getArrangement: (id, sessionId = null) => apiFetch(`/api/daw/assets/${id}/arrangement${sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ''}`),
    saveArrangement: (id, arrangement, options = {}) => apiFetch(`/api/daw/assets/${id}/arrangement`, { method: 'PUT', body: JSON.stringify({ arrangement, session_id: options.sessionId || null, title: options.title || null, create_new_session: Boolean(options.createNewSession) }) }),
    arrangementSessions: (id) => apiFetch(`/api/daw/assets/${id}/arrangement/sessions`),
    createArrangementSession: (id, arrangement, title = '') => apiFetch(`/api/daw/assets/${id}/arrangement/sessions`, { method: 'POST', body: JSON.stringify({ arrangement, title, create_new_session: true }) }),
    deleteArrangementSession: (id, sessionId) => apiFetch(`/api/daw/assets/${id}/arrangement/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' }),
    getBeatgrid: (id) => apiFetch(`/api/daw/assets/${id}/beatgrid?v=${Date.now()}`, { cache: 'no-store', timeoutMs: 900000 }),
    rebuildBeatgrid: (id) => apiFetch(`/api/daw/assets/${id}/beatgrid/rebuild`, { method: 'POST', timeoutMs: 900000 }),
    previewArrangement: (id, payload) => apiFetchBlob(`/api/daw/assets/${id}/arrangement/preview`, { method: 'POST', body: JSON.stringify(payload) }),
    renderArrangement: (id, payload) => apiFetch(`/api/daw/assets/${id}/arrangement/render`, { method: 'POST', body: JSON.stringify(payload) }),
    renderArrangementTask: (id, payload) => apiFetch(`/api/daw/assets/${id}/arrangement/render-task`, { method: 'POST', body: JSON.stringify(payload), timeoutMs: 12000 }),
    addMarker: (id, payload) => apiFetch(`/api/daw/assets/${id}/markers`, { method: 'POST', body: JSON.stringify(payload) }),
    deleteMarker: (id, markerIndex) => apiFetch(`/api/daw/assets/${id}/markers/${encodeURIComponent(markerIndex)}`, { method: 'DELETE' }),
    analyze: (payload) => apiFetch('/api/daw/analyze', { method: 'POST', body: JSON.stringify(payload) }),
    chat: (payload) => apiFetch('/api/daw/chat', { method: 'POST', body: JSON.stringify(payload) }),
    resolveCommand: (payload) => apiFetch('/api/daw/commands/resolve', { method: 'POST', body: JSON.stringify(payload) }),
    arrangementAiCommand: (id, payload) => apiFetch(`/api/daw/assets/${id}/arrangement/ai-command`, { method: 'POST', body: JSON.stringify(payload), timeoutMs: 180000 }),
    promptHooks: () => apiFetch('/api/daw/prompt-hooks')
  },

  audit: {
    checks: () => apiFetch('/api/audit/checks', { cache: 'no-store' }),
    runs: (limit = 30) => apiFetch(`/api/audit/runs?limit=${encodeURIComponent(limit)}&v=${Date.now()}`, { cache: 'no-store' }),
    start: (payload = {}) => apiFetch('/api/audit/runs', { method: 'POST', body: JSON.stringify(payload || {}) }),
    run: (id) => apiFetch(`/api/audit/runs/${encodeURIComponent(id)}?v=${Date.now()}`, { cache: 'no-store' }),
    report: (id) => apiFetch(`/api/audit/runs/${encodeURIComponent(id)}/report`, { cache: 'no-store' }),
    apply: (id, confirmText, repairActions = []) => apiFetch(`/api/audit/runs/${encodeURIComponent(id)}/apply`, { method: 'POST', body: JSON.stringify({ confirm: confirmText, repair_actions: repairActions }) }),
    cancel: (id) => apiFetch(`/api/audit/runs/${encodeURIComponent(id)}/cancel`, { method: 'POST' })
  },
  notifications: {
    list: (includeDone = true) => apiFetch(`/api/notifications?include_done=${includeDone ? 'true' : 'false'}&v=${Date.now()}`, { cache: 'no-store', timeoutMs: 8000 }),
    markDone: (id) => apiFetch(`/api/notifications/${id}/done`, { method: 'POST' }),
    bulkDone: (ids) => apiFetch('/api/notifications/bulk-done', { method: 'POST', body: JSON.stringify({ ids }) }),
    cleanupStale: (payload = {}) => apiFetch('/api/notifications/cleanup-stale', { method: 'POST', body: JSON.stringify(payload) }),
    delete: (id) => apiFetch(`/api/notifications/${id}`, { method: 'DELETE' }),
    bulkDelete: (ids) => apiFetch('/api/notifications/bulk-delete', { method: 'POST', body: JSON.stringify({ ids }) })
  },
  production: {
    dashboard: () => apiFetch('/api/production/dashboard'),
    roadmap: () => apiFetch('/api/production/roadmap'),
    cockpit: (limit = 40) => apiFetch(`/api/production/cockpit?limit=${encodeURIComponent(limit)}`),
    projects: () => apiFetch('/api/production/projects'),
    workflow: (id) => apiFetch(`/api/production/audio/${id}/workflow`),
    updateWorkflow: (id, payload) => apiFetch(`/api/production/audio/${id}/workflow`, { method: 'PATCH', body: JSON.stringify(payload) }),
    duplicateVersion: (id, payload) => apiFetch(`/api/production/audio/${id}/duplicate-version`, { method: 'POST', body: JSON.stringify(payload || {}) }),
    youtubePackage: (id) => apiFetch(`/api/production/audio/${id}/youtube-package`),
    youtubePackageTextUrl: (id) => `/api/production/audio/${id}/youtube-package?format=txt`,
    videoPlan: (id) => apiFetch(`/api/production/audio/${id}/video-plan`),
    events: (id) => apiFetch(`/api/production/audio/${id}/events`),
    seedStylePresets: () => apiFetch('/api/production/styles/seed-presets', { method: 'POST' }),
    projectReport: (id) => apiFetch(`/api/production/projects/${id}/production-report`),
    projectExportUrl: (id, format = 'json') => `/api/production/projects/${id}/export?format=${encodeURIComponent(format)}`
  },
  system: {
    diagnostics: () => apiFetch('/api/system/diagnostics'),
    portableBackupStatus: () => apiFetch('/api/system/portable-backup/status'),
    portableBackupSchedule: () => apiFetch('/api/system/portable-backup/schedule', { cache: 'no-store' }),
    updatePortableBackupSchedule: (payload = {}) => apiFetch('/api/system/portable-backup/schedule', { method: 'PUT', body: JSON.stringify(payload || {}) }),
    runPortableBackupScheduleNow: () => apiFetch('/api/system/portable-backup/schedule/run-now', { method: 'POST', timeoutMs: 120000 }),
    databaseMaintenanceStatus: () => apiFetch(`/api/system/maintenance/database/status?v=${Date.now()}`, { cache: 'no-store' }),
    runDatabaseMaintenance: (payload = {}) => apiFetch('/api/system/maintenance/database/run', { method: 'POST', body: JSON.stringify(payload || {}), timeoutMs: 120000 }),
    syncSongsToLibrary: (payload = {}) => apiFetch('/api/music/songs/sync-library', { method: 'POST', body: JSON.stringify(payload || {}), timeoutMs: 120000 }),
    normalizePortablePaths: (dryRun = true) => apiFetch('/api/system/maintenance/normalize-portable-paths', { method: 'POST', body: JSON.stringify({ dry_run: dryRun }) }),
    exportPortableBackup: (payload = {}) => apiFetchBlob('/api/system/portable-backup/export', { method: 'POST', body: JSON.stringify(payload || {}) }),
    startPortableBackupExport: (payload = {}) => apiFetch('/api/system/portable-backup/export/start', { method: 'POST', body: JSON.stringify(payload || {}) }),
    portableBackupJob: (jobId) => apiFetch(`/api/system/portable-backup/jobs/${encodeURIComponent(jobId)}`, { cache: 'no-store' }),
    downloadPortableBackupJob: (jobId) => apiFetchBlob(`/api/system/portable-backup/export/${encodeURIComponent(jobId)}/download`, { method: 'GET' }),
    importPortableBackup: (file) => {
      const formData = new FormData();
      formData.append('backup', file);
      return apiFetch('/api/system/portable-backup/import?confirm=true', { method: 'POST', body: formData, timeoutMs: 120000 });
    },
    startPortableBackupImport: (file, onUploadProgress) => new Promise((resolve, reject) => {
      const formData = new FormData();
      formData.append('backup', file);
      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/system/portable-backup/import/start?confirm=true');
      xhr.withCredentials = true;
      const storedToken = getStoredAccessToken();
      if (storedToken) xhr.setRequestHeader('Authorization', `Bearer ${storedToken}`);
      xhr.setRequestHeader('Accept', 'application/json');
      xhr.upload.onprogress = (event) => {
        if (!event.lengthComputable || typeof onUploadProgress !== 'function') return;
        onUploadProgress(Math.round((event.loaded / event.total) * 100), event.loaded, event.total);
      };
      xhr.onload = () => {
        let payload = null;
        try { payload = JSON.parse(xhr.responseText || '{}'); } catch (_) { payload = xhr.responseText; }
        if (xhr.status >= 200 && xhr.status < 300) return resolve(payload);
        if (xhr.status === 401) setStoredAccessToken('');
        const message = typeof payload === 'object' && payload?.detail
          ? payload.detail
          : typeof payload === 'object' && payload?.error
            ? payload.error
            : typeof payload === 'string' && payload
              ? payload
              : `HTTP ${xhr.status}`;
        reject(new ApiError(message, xhr.status, payload));
      };
      xhr.onerror = () => reject(new ApiError('Upload des Portable Backups fehlgeschlagen.', 0, null));
      xhr.send(formData);
    }),
    // System-Cover-Cache ist bewusst getrennt von api.archive.cacheMissingCovers():
    // Dry-Run, Limit und Ergebnisformat folgen app/routers/system.py.
    cacheExternalCovers: (payload = {}) => apiFetch('/api/system/maintenance/cache-external-covers', { method: 'POST', body: JSON.stringify(payload || {}), timeoutMs: 120000 })
  }
};
