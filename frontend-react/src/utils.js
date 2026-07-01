
function metadataCandidate(asset) {
  const meta = asset?.metadata_json || {};
  return meta?.candidate && typeof meta.candidate === 'object' ? meta.candidate : {};
}

function metadataRequestPayload(asset) {
  const meta = asset?.metadata_json || {};
  return meta?.request_payload && typeof meta.request_payload === 'object' ? meta.request_payload : {};
}

export function pickPrompt(asset) {
  const candidate = metadataCandidate(asset);
  const request = metadataRequestPayload(asset);
  return asset?.prompt || candidate.prompt || candidate.lyrics || candidate.text || request.prompt || request.lyrics || '';
}

export function pickLyrics(asset) {
  const candidate = metadataCandidate(asset);
  const request = metadataRequestPayload(asset);
  return asset?.lyrics || candidate.lyrics || candidate.text || request.lyrics || '';
}

export function pickStyle(asset) {
  const candidate = metadataCandidate(asset);
  const request = metadataRequestPayload(asset);
  return asset?.tags || asset?.style || candidate.tags || candidate.style || request.style || request.tags || '';
}

export function pickModel(asset) {
  const candidate = metadataCandidate(asset);
  const request = metadataRequestPayload(asset);
  return asset?.model_name || candidate.modelName || candidate.model || request.model || '';
}


function metadataRequestPayloadDeep(asset) {
  const meta = asset?.metadata_json && typeof asset.metadata_json === 'object' ? asset.metadata_json : {};
  const candidate = metadataCandidate(asset);
  const parseJsonObject = (value) => {
    if (!value || typeof value !== 'string') return null;
    try {
      const parsed = JSON.parse(value);
      return parsed && typeof parsed === 'object' ? parsed : null;
    } catch {
      return null;
    }
  };
  return [
    meta.request_payload,
    meta.requestPayload,
    parseJsonObject(meta.task_request_payload?.param),
    parseJsonObject(meta.taskRequestPayload?.param),
    meta.task_request_payload,
    meta.taskRequestPayload,
    meta.suno_response?.request_payload,
    meta.suno_response?.requestPayload,
    meta.response_payload?.request_payload,
    meta.result_payload?.request_payload,
    candidate.request_payload,
    candidate.requestPayload,
    parseJsonObject(meta.param),
    parseJsonObject(meta.suno_response?.param),
    parseJsonObject(meta.response_payload?.param),
    parseJsonObject(meta.result_payload?.param),
    parseJsonObject(candidate.param),
  ].find((item) => item && typeof item === 'object') || metadataRequestPayload(asset) || {};
}

function firstDefined(...values) {
  return values.find((value) => value !== undefined && value !== null && value !== '');
}

function deepFindByKeys(source, keys, seen = new Set()) {
  if (!source || typeof source !== 'object' || seen.has(source)) return undefined;
  seen.add(source);
  for (const key of keys) {
    if (Object.prototype.hasOwnProperty.call(source, key)) {
      const value = source[key];
      if (value !== undefined && value !== null && value !== '') return value;
    }
  }
  for (const value of Object.values(source)) {
    if (value && typeof value === 'object') {
      const found = deepFindByKeys(value, keys, seen);
      if (found !== undefined && found !== null && found !== '') return found;
    }
  }
  return undefined;
}

function normalizeGenerationNumber(value) {
  if (value === undefined || value === null || value === '') return '';
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  return String(Math.max(0, Math.min(1, number)));
}

function normalizeVocalGenderValue(value) {
  const text = String(value ?? '').trim().toLowerCase();
  if (!text) return '';
  if (['m', 'male', 'man', 'masculine', 'masc', 'männlich'].includes(text)) return 'm';
  if (['f', 'female', 'woman', 'feminine', 'fem', 'weiblich'].includes(text)) return 'f';
  return String(value).trim();
}

function translateFormatter(translate, key, fallback, values) {
  return typeof translate === 'function' ? translate(key, fallback, values) : fallback;
}

export function formatBoolean(value, translate = null) {
  const tr = (key, fallback, values) => translateFormatter(translate, key, fallback, values);
  if (value === true || String(value).toLowerCase() === 'true') return tr('common.yes', 'Ja');
  if (value === false || String(value).toLowerCase() === 'false') return tr('common.no', 'Nein');
  return '—';
}

export function formatVocalGender(value, translate = null) {
  const tr = (key, fallback, values) => translateFormatter(translate, key, fallback, values);
  const normalized = String(value ?? '').trim().toLowerCase();
  if (!normalized) return '—';
  if (['m', 'male', 'man', 'masculine', 'masc'].includes(normalized)) return tr('common.male', 'Male');
  if (['f', 'female', 'woman', 'feminine', 'fem'].includes(normalized)) return tr('common.female', 'Female');
  return String(value);
}

export function getGenerationOptions(asset) {
  const request = metadataRequestPayloadDeep(asset);
  const candidate = metadataCandidate(asset);
  const meta = asset?.metadata_json && typeof asset.metadata_json === 'object' ? asset.metadata_json : {};
  const optionKeys = {
    negativeTags: ['negative_tags', 'negativeTags', 'negativePrompt', 'negative_prompt'],
    vocalGender: ['vocal_gender', 'vocalGender', 'gender', 'voice_gender', 'voiceGender'],
    styleWeight: ['styleWeight', 'style_weight', 'styleStrength', 'style_strength'],
    weirdness: ['weirdnessConstraint', 'weirdness_constraint', 'weirdness', 'weirdnessWeight', 'weirdness_weight'],
    audioWeight: ['audioWeight', 'audio_weight', 'audioStrength', 'audio_strength'],
    customMode: ['customMode', 'custom_mode'],
    instrumental: ['instrumental', 'makeInstrumental', 'make_instrumental'],
    personaId: ['personaId', 'persona_id', 'voiceId', 'voice_id'],
    personaModel: ['personaModel', 'persona_model'],
  };
  const sources = [asset, request, candidate, meta, meta.task_request_payload, meta.taskRequestPayload];
  const findOption = (keys) => firstDefined(
    ...sources.flatMap((source) => source ? keys.map((key) => source[key]) : []),
    ...sources.map((source) => deepFindByKeys(source, keys))
  );

  const negativeTags = findOption(optionKeys.negativeTags);
  const vocalGender = findOption(optionKeys.vocalGender);
  const styleWeight = findOption(optionKeys.styleWeight);
  const weirdness = findOption(optionKeys.weirdness);
  const audioWeight = findOption(optionKeys.audioWeight);
  const personaId = findOption(optionKeys.personaId);
  const personaModel = findOption(optionKeys.personaModel);

  return {
    negative_tags: negativeTags || '',
    negativeTags: negativeTags || '',
    vocal_gender: normalizeVocalGenderValue(vocalGender),
    vocalGender: normalizeVocalGenderValue(vocalGender),
    styleWeight: normalizeGenerationNumber(styleWeight),
    style_weight: normalizeGenerationNumber(styleWeight),
    weirdnessConstraint: normalizeGenerationNumber(weirdness),
    weirdness_constraint: normalizeGenerationNumber(weirdness),
    weirdness: normalizeGenerationNumber(weirdness),
    audioWeight: normalizeGenerationNumber(audioWeight),
    audio_weight: normalizeGenerationNumber(audioWeight),
    customMode: findOption(optionKeys.customMode),
    instrumental: findOption(optionKeys.instrumental),
    personaId: personaId || '',
    persona_id: personaId || '',
    personaModel: personaModel || '',
    persona_model: personaModel || '',
  };
}

export function hasGenerationOptions(asset) {
  const options = getGenerationOptions(asset);
  return Boolean(
    options.negative_tags ||
    options.vocal_gender ||
    options.styleWeight !== '' ||
    options.weirdnessConstraint !== '' ||
    options.audioWeight !== '' ||
    options.customMode !== undefined ||
    options.instrumental !== undefined ||
    options.personaId ||
    options.personaModel
  );
}

export function formatDuration(seconds) {
  const value = Number(seconds || 0);
  if (!Number.isFinite(value) || value <= 0) return '—';
  const min = Math.floor(value / 60);
  const sec = Math.floor(value % 60).toString().padStart(2, '0');
  return `${min}:${sec}`;
}

export function parseBackendDate(value) {
  if (!value) return null;
  if (value instanceof Date) return value;
  const text = String(value).trim();
  if (!text) return null;

  // SQLAlchemy/FastAPI liefert UTC-Zeitstempel in diesem Projekt oft ohne
  // Zeitzonen-Suffix, z. B. 2026-06-20T04:19:00. Ohne Suffix interpretiert
  // der Browser den Wert als lokale Zeit und zeigt dadurch in Deutschland
  // zwei Stunden zu früh an. Naive ISO-Zeitstempel werden daher als UTC gelesen.
  const normalized = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?$/.test(text)
    ? `${text.replace(' ', 'T')}Z`
    : text;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

function currentUiLocale(locale = null) {
  if (locale) return locale;
  try {
    const language = document?.documentElement?.lang || navigator?.language || 'de';
    return String(language).toLowerCase().startsWith('en') ? 'en-US' : 'de-DE';
  } catch {
    return 'de-DE';
  }
}

export function formatDate(value, locale = null) {
  if (!value) return '—';
  const date = parseBackendDate(value);
  if (!date) return String(value);
  return new Intl.DateTimeFormat(currentUiLocale(locale), {
    timeZone: 'Europe/Berlin', day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit'
  }).format(date);
}

export function sortTimestamp(value) {
  const date = parseBackendDate(value);
  return date ? date.getTime() : 0;
}

export function newestTimestamp(...values) {
  return Math.max(0, ...values.map(sortTimestamp));
}

export function shortId(value, length = 8) {
  if (!value) return '—';
  const text = String(value);
  return text.length <= length ? text : `${text.slice(0, length)}…`;
}

export function copyToClipboard(value) {
  if (!value) return Promise.resolve(false);
  return navigator.clipboard.writeText(String(value)).then(() => true).catch(() => false);
}

export function operationLabel(value, translate = null) {
  const tr = (key, fallback, values) => translateFormatter(translate, key, fallback, values);
  const normalized = String(value || '').toLowerCase();
  const map = {
    generate: tr('library.typeFilters.generate', 'Generiert'),
    generated: tr('library.typeFilters.generate', 'Generiert'),
    generate_music: tr('library.typeFilters.generate', 'Generiert'),
    extend: 'Extended',
    extended: 'Extended',
    extend_music: 'Extended',
    upload_cover: 'Cover Song',
    cover: 'Cover Song',
    cover_song: 'Cover Song',
    add_vocals: 'Add Vocals',
    vocals: 'Add Vocals',
    add_instrumental: 'Add Instrumental',
    instrumental: 'Add Instrumental',
    mashup: 'Mashup',
    generate_mashup: 'Mashup',
    sounds: 'Sounds',
    generate_sounds: 'Sounds',
    lyrics: 'Lyrics',
    generate_lyrics: 'Lyrics',
    manual: tr('library.operation.manualImport', 'Manuell importiert'),
    manual_import: tr('library.operation.manualImport', 'Manuell importiert'),
    'manual import': tr('library.operation.manualImport', 'Manuell importiert'),
    'manuell importiert': tr('library.operation.manualImport', 'Manuell importiert')
  };
  return map[normalized] || value || 'Track';
}

export function operationKey(value) {
  const normalized = String(value || '').toLowerCase();
  if (normalized.includes('manual') || normalized.includes('manuell') || normalized.includes('import')) return 'manual';
  if (normalized.includes('extend')) return 'extend';
  if (normalized.includes('cover')) return 'cover';
  if (normalized.includes('vocal')) return 'vocals';
  if (normalized.includes('instrument')) return 'instrumental';
  if (normalized.includes('mashup')) return 'mashup';
  if (normalized.includes('sound')) return 'sounds';
  if (normalized.includes('lyric')) return 'lyrics';
  return 'generate';
}

export function pickTitle(asset) {
  return asset?.display_title || asset?.title || asset?.song_title || asset?.song?.title || metadataCandidate(asset).title || asset?.filename || `Audio #${asset?.id}`;
}

export const FALLBACK_COVER_URL = '/static/favicon.ico';

const API_MEDIA_BASE_URL = String(import.meta.env?.VITE_API_BASE_URL || '').replace(/\/+$/, '');

export function resolveMediaUrl(url) {
  if (!url) return url;
  const value = String(url);
  if (/^(data:|blob:|https?:|\/\/)/i.test(value)) return value;
  if (value.startsWith('/media/') && API_MEDIA_BASE_URL) return `${API_MEDIA_BASE_URL}${value}`;
  return value;
}

export function pickCover(asset) {
  const cover = asset?.cover_local_url
    || asset?.image_url
    || asset?.cover_image_url
    || asset?.song?.cover_local_url
    || asset?.song?.cover_image_url
    || asset?.source_image_url
    || metadataCandidate(asset).sourceImageUrl
    || metadataCandidate(asset).imageUrl
    || FALLBACK_COVER_URL;
  return resolveMediaUrl(cover);
}

export function handleCoverImageError(event) {
  const image = event?.currentTarget;
  if (!image) return;
  image.onerror = null;
  if (!String(image.getAttribute('src') || '').endsWith(FALLBACK_COVER_URL)) {
    image.src = FALLBACK_COVER_URL;
  }
}

export function isCoverCached(asset) {
  if (!asset) return false;
  if (asset.cover_cached || asset.song?.cover_cached) return true;
  const cover = asset.cover_local_url || asset.image_url || asset.cover_image_url || asset.song?.cover_local_url || asset.song?.cover_image_url || '';
  return String(cover).startsWith('/media/covers/');
}


export function variantOrder(asset) {
  const candidate = metadataCandidate(asset);
  const raw = asset?.variant_index ?? asset?.variant_order ?? candidate.index ?? candidate.variantIndex ?? candidate.variant_index;
  const numeric = Number(raw);
  if (Number.isFinite(numeric)) return numeric;
  return Number(asset?.id || 0);
}

function firstValidDateValue(...values) {
  for (const value of values) {
    if (!value) continue;
    if (sortTimestamp(value) > 0) return value;
  }
  return '';
}

export function sourceCreatedValue(asset) {
  const meta = asset?.metadata_json && typeof asset.metadata_json === 'object' ? asset.metadata_json : {};
  const candidate = metadataCandidate(asset);
  const request = metadataRequestPayloadDeep(asset);
  const deepSourceDate = deepFindByKeys(meta, ['source_created_at', 'sourceCreatedAt', 'createTime', 'createdAt']);
  return firstValidDateValue(
    asset?.library_sort_at,
    asset?.source_created_at,
    asset?.sourceCreatedAt,
    meta.source_created_at,
    meta.sourceCreatedAt,
    candidate.source_created_at,
    candidate.sourceCreatedAt,
    candidate.createTime,
    candidate.createdAt,
    request.source_created_at,
    request.sourceCreatedAt,
    request.createTime,
    request.createdAt,
    deepSourceDate,
    asset?.task_created_at,
    asset?.taskCreatedAt,
    asset?.created_at,
    asset?.create_time,
    asset?.createTime
  );
}

export function taskCreatedValue(asset) {
  // Historischer Name, aber bewusst externe/originale Zeit bevorzugen.
  // Sonst sortiert die Library wieder nach lokalen Import-/Repair-Zeiten.
  return sourceCreatedValue(asset);
}

export function newestValue(asset) {
  return sourceCreatedValue(asset);
}

export function stableLibrarySortValue(row) {
  const primary = row?.sort_at || row?.newest_asset_created_at || row?.created_at;
  return sortTimestamp(primary);
}

export function updatedLibrarySortValue(row) {
  const primary = row?.updated_at || row?.newest_asset_updated_at || row?.sort_at || row?.newest_asset_created_at || row?.created_at;
  return sortTimestamp(primary);
}

export function isPlayable(asset) {
  if (!asset || !asset.id || asset.is_deleted) return false;
  if (String(asset.status || '').toLowerCase() === 'failed') return false;
  return Boolean(asset.public_url || asset.source_url || asset.filename || asset.audio_id);
}

export function assetSearchText(asset) {
  const aiTags = asset?.metadata_json?.ai_tags && typeof asset.metadata_json.ai_tags === 'object' ? asset.metadata_json.ai_tags : {};
  return [
    pickTitle(asset), pickStyle(asset), pickPrompt(asset), pickLyrics(asset), asset.audio_id,
    asset.suno_task_id, asset.task_id, asset.filename, asset.source_url, asset.operation_type, asset.task_type, asset.operation_label,
    ...(Array.isArray(aiTags.tags) ? aiTags.tags : []),
    ...(Array.isArray(aiTags.moods) ? aiTags.moods : []),
    ...(Array.isArray(aiTags.genres) ? aiTags.genres : []),
    aiTags.language
  ].filter(Boolean).join(' ').toLowerCase();
}

export function dedupeAssets(assets) {
  const score = (asset) => {
    let value = 0;
    if (asset.status === 'cached') value += 100;
    if (asset.public_url) value += 40;
    if (asset.local_path) value += 30;
    if (asset.audio_id) value += 20;
    if (asset.duration_seconds) value += 10;
    if (asset.image_url || asset.source_image_url) value += 5;
    if (String(asset.status || '').toLowerCase() === 'failed') value -= 200;
    return value;
  };
  const map = new Map();
  for (const asset of assets || []) {
    if (!asset || asset.is_deleted) continue;
    const key = asset.audio_id || asset.checksum_sha256 || asset.source_url || asset.public_url || `asset-${asset.id}`;
    const current = map.get(key);
    if (!current || score(asset) > score(current)) map.set(key, asset);
  }
  return [...map.values()];
}

function projectGroupingKey(asset) {
  if (asset?.project_id !== undefined && asset?.project_id !== null && asset?.project_id !== '') return `project-${asset.project_id}`;
  if (asset?.song_id !== undefined && asset?.song_id !== null && asset?.song_id !== '') return `song-${asset.song_id}`;
  if (asset?.suno_task_id) return `task-${asset.suno_task_id}`;
  if (asset?.task_id) return `task-${asset.task_id}`;
  return `audio-${asset?.id}`;
}

export function groupAssetsByProject(assets) {
  const groups = new Map();
  for (const asset of dedupeAssets(assets)) {
    const key = projectGroupingKey(asset);
    if (!groups.has(key)) {
      const createdAt = taskCreatedValue(asset);
      groups.set(key, {
        id: key,
        title: asset.project_title || asset.song_title || asset.display_title || asset.title || 'Unbenanntes Projekt',
        cover: pickCover(asset),
        created_at: createdAt,
        updated_at: asset.updated_at || createdAt,
        newest_asset_created_at: createdAt,
        newest_asset_updated_at: asset.updated_at || createdAt,
        sort_at: createdAt,
        assets: []
      });
    }
    const group = groups.get(key);
    group.assets.push(asset);
    if (!group.cover || group.cover === '/static/favicon.ico') group.cover = pickCover(asset);
    const createdAt = taskCreatedValue(asset);
    const updatedAt = asset.updated_at || createdAt;
    if (sortTimestamp(updatedAt) > sortTimestamp(group.updated_at)) group.updated_at = updatedAt;
    if (sortTimestamp(updatedAt) > sortTimestamp(group.newest_asset_updated_at)) group.newest_asset_updated_at = updatedAt;
    if (sortTimestamp(createdAt) > sortTimestamp(group.newest_asset_created_at)) {
      group.newest_asset_created_at = createdAt;
      group.sort_at = createdAt;
    }
    if ((!group.title || group.title === 'Unbenanntes Projekt') && pickTitle(asset)) group.title = pickTitle(asset);
  }
  return [...groups.values()].map((group) => {
    const sortedAssets = group.assets.sort((a, b) => {
      const byOperationTime = sortTimestamp(taskCreatedValue(a)) - sortTimestamp(taskCreatedValue(b));
      if (byOperationTime !== 0) return byOperationTime;
      return variantOrder(a) - variantOrder(b);
    });
    const annotatedAssets = sortedAssets.map((asset, index) => ({
      ...asset,
      project_variant_index: index + 1,
      project_variant_total: sortedAssets.length,
      project_variant_title: `${pickTitle(asset)} ${index + 1}/${sortedAssets.length}`,
      project_display_title: group.title,
    }));
    return {
      ...group,
      assets: annotatedAssets,
      operations: groupAssetsByOperation(annotatedAssets),
      playable: annotatedAssets.filter(isPlayable),
      duration: annotatedAssets.reduce((sum, item) => sum + Number(item.duration_seconds || 0), 0)
    };
  }).sort((a, b) => stableLibrarySortValue(b) - stableLibrarySortValue(a));
}

export function groupAssetsByOperation(assets) {
  const groups = new Map();
  for (const asset of assets || []) {
    const operationValue = asset.operation_type || asset.task_type || asset.operation_label;
    const key = asset.suno_task_id || asset.task_id || `${operationKey(operationValue)}-${asset.id}`;
    if (!groups.has(key)) {
      groups.set(key, {
        id: key,
        label: operationLabel(operationValue),
        type: operationKey(operationValue),
        taskId: asset.suno_task_id || asset.task_id,
        created_at: taskCreatedValue(asset),
        assets: []
      });
    }
    groups.get(key).assets.push(asset);
  }
  return [...groups.values()]
    .map((group) => ({
      ...group,
      assets: group.assets.sort((a, b) => {
        const byCreated = sortTimestamp(taskCreatedValue(a)) - sortTimestamp(taskCreatedValue(b));
        if (byCreated !== 0) return byCreated;
        return variantOrder(a) - variantOrder(b);
      })
    }))
    .sort((a, b) => sortTimestamp(a.created_at) - sortTimestamp(b.created_at));
}

export function summarizeStyle(value, max = 140, translate = null) {
  const tr = (key, fallback, values) => translateFormatter(translate, key, fallback, values);
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (!text) return tr('library.noStyleStored', 'Kein Style gespeichert');
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

export function lineCount(value) {
  if (!value) return 0;
  return String(value).split(/\r?\n/).length;
}

export function downloadTextFile(filename, content, mime = 'text/plain;charset=utf-8') {
  const blob = new Blob([String(content || '')], { type: mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function safeFilename(value, fallback = 'export') {
  const text = String(value || fallback).trim().replace(/[\\/:*?"<>|]+/g, '_').replace(/\s+/g, ' ');
  return (text || fallback).slice(0, 120);
}

export function friendlyNotification(notification, translate = null) {
  const tr = (key, fallback, values) => translateFormatter(translate, key, fallback, values);
  const title = notification?.title || '';
  const message = notification?.message || '';
  const combined = `${title} ${message}`.toLowerCase();
  if (combined.includes('prompt') && combined.includes('long')) {
    return { title: tr('status.friendly.promptTooLongTitle', 'Der Text ist zu lang.'), message: tr('status.friendly.promptTooLongMessage', 'Kürze den Text oder nutze den Custom-Modus.') };
  }
  if (combined.includes('invalid audio') || combined.includes('audio id')) {
    return { title: tr('status.friendly.invalidAudioTitle', 'Dieser Song kann nicht weiterbearbeitet werden.'), message: tr('status.friendly.invalidAudioMessage', 'Es fehlt eine gültige Song-ID. Öffne die Library und wähle eine andere Variante.') };
  }
  if (combined.includes('credit')) {
    return { title: tr('status.friendly.creditsTitle', 'Credits prüfen.'), message: tr('status.friendly.creditsMessage', 'Deine Suno-Credits reichen eventuell nicht aus.') };
  }
  if (combined.includes('success') || combined.includes('fertig')) {
    return { title: title || tr('status.friendly.successTitle', 'Dein Ergebnis ist fertig.'), message: message || tr('status.friendly.successMessage', 'Öffnen, anhören und weiterbearbeiten.') };
  }
  return { title: title || tr('status.friendly.newNotification', 'Neue Benachrichtigung'), message };
}


export function safeArray(value, preferredKeys = []) {
  if (Array.isArray(value)) return value;
  if (!value || typeof value !== 'object') return [];
  for (const key of preferredKeys) {
    if (Array.isArray(value[key])) return value[key];
  }
  for (const key of ['items', 'results', 'data', 'records', 'rows', 'assets', 'lyrics', 'styles', 'playlists', 'tasks', 'notifications']) {
    if (Array.isArray(value[key])) return value[key];
  }
  return [];
}
