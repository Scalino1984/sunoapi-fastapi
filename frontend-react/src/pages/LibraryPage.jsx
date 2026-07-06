import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowLeft, ArrowRight, ChevronDown, ChevronRight, Clock3, Copy, Download, Edit3, ExternalLink, FileText, Film, Filter, Headphones, ListMusic, Maximize2, Minimize2, MoreHorizontal, Pause, Play, Plus, Scissors, Star, Tag, ThumbsUp, Trash2, ZoomIn, ZoomOut } from 'lucide-react';
import { api } from '../api/client.js';
import { EmptyState } from '../components/EmptyState.jsx';
import { Modal } from '../components/Modal.jsx';
import { SectionHeader } from '../components/SectionHeader.jsx';
import { Waveform } from '../components/Waveform.jsx';
import { useI18n } from '../i18n/I18nContext.jsx';
import { assetSearchText, copyToClipboard, downloadTextFile, formatBoolean, formatDate, parseBackendDate, formatDuration, formatVocalGender, getGenerationOptions, groupAssetsByProject, handleCoverImageError, hasGenerationOptions, isPlayable, operationKey, operationLabel, pickCover, isCoverCached, pickLyrics, pickModel, pickPrompt, pickStyle, pickTitle, safeFilename, shortId, stableLibrarySortValue, updatedLibrarySortValue, summarizeStyle } from '../utils.js';


const srtLiveColorOptions = [
  { key: 'cyan', label: 'Cyan', value: '#22d3ee' },
  { key: 'blue', label: 'Blau', value: '#60a5fa' },
  { key: 'violet', label: 'Violett', value: '#a78bfa' },
  { key: 'pink', label: 'Pink', value: '#f472b6' },
  { key: 'green', label: 'Grün', value: '#34d399' },
  { key: 'gold', label: 'Gold', value: '#fbbf24' },
  { key: 'white', label: 'Weiß', value: '#f8fafc' }
];

const wizardCaptureOptions = [
  { key: 'timestampedLyrics', label: 'Timestamped Lyrics abrufen', description: 'Suno-synchronisierte Lyrics zur Audio-ID speichern.' },
  { key: 'srt', label: 'SRT erzeugen', description: 'Lyrics-basiertes SRT erzeugen und speichern.' },
  { key: 'stems', label: 'Stems erzeugen', description: 'Vocals und Instrumental lokal trennen.' },
  { key: 'waveform', label: 'Waveform neu berechnen', description: 'Wellenformdaten für Player/Timeline aktualisieren.' },
];

const bundleContentOptions = [
  { key: 'audio', label: 'Audio', description: 'lokale Audiodatei' },
  { key: 'wav', label: 'WAV', description: 'konvertierte WAV-Datei' },
  { key: 'cover', label: 'Cover', description: 'lokaler Cover-Cache' },
  { key: 'video', label: 'MP4', description: 'lokal gespeicherte Musikvideos' },
  { key: 'srt', label: 'SRT', description: 'Untertiteldatei' },
  { key: 'timestamped_lyrics', label: 'Timestamped Lyrics', description: 'Suno-Timingdaten als JSON' },
  { key: 'stems', label: 'Stems', description: 'Vocals und Instrumental' },
  { key: 'lyrics', label: 'Songtext', description: 'lyrics.txt' },
  { key: 'prompt', label: 'Prompt', description: 'prompt.txt' },
  { key: 'style', label: 'Style', description: 'style.txt' },
  { key: 'metadata', label: 'Metadaten', description: 'metadata.json' },
  { key: 'waveform', label: 'Waveform', description: 'waveform.json' },
  { key: 'structure', label: 'Songstruktur', description: 'structure_segments.json' },
];

const defaultWizardCaptureState = {
  timestampedLyrics: false,
  srt: true,
  stems: false,
  waveform: false,
};

const defaultBundleContentState = Object.fromEntries(bundleContentOptions.map((item) => [item.key, ['audio', 'cover', 'srt', 'lyrics', 'prompt', 'style', 'metadata'].includes(item.key)]));

const sunoModelOptions = ['V5_5', 'V5', 'V4_5ALL', 'V4_5', 'V4_5PLUS', 'V4'];
const extendContinueAtStorageKey = 'react-library-extend-continue-at-overrides';
const libraryViewStorageKey = 'react-library-view-mode';
const libraryGalleryModeStorageKey = 'react-library-gallery-mode';
const libraryFlatListModeStorageKey = 'react-library-flat-list-mode';
const libraryViewModes = ['list', 'flat-list', 'gallery'];
const librarySubModes = ['simple', 'advanced'];


function translateFallback(translate, key, fallback, values) {
  return typeof translate === 'function' ? translate(key, fallback, values) : fallback;
}

function ResponsiveLabel({ full, short }) {
  return (
    <>
      <span className="responsive-label-full">{full}</span>
      <span className="responsive-label-short">{short || full}</span>
    </>
  );
}


function readStoredChoice(key, allowed, fallback) {
  try {
    const value = localStorage.getItem(key);
    return allowed.includes(value) ? value : fallback;
  } catch {
    return fallback;
  }
}


function writeStoredChoice(key, value, allowed) {
  if (!allowed.includes(value)) return;
  try {
    localStorage.setItem(key, value);
  } catch {
    // localStorage kann in restriktiven Browser-Kontexten blockiert sein.
  }
}


function readExtendContinueAtOverrides() {
  try {
    const parsed = JSON.parse(localStorage.getItem(extendContinueAtStorageKey) || '{}');
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}


function writeExtendContinueAtOverride(assetId, value) {
  const key = String(assetId || '').trim();
  const text = String(value || '').trim();
  if (!key || !text) return;
  try {
    const current = readExtendContinueAtOverrides();
    current[key] = text;
    localStorage.setItem(extendContinueAtStorageKey, JSON.stringify(current));
  } catch {
    // localStorage kann in restriktiven Browser-Kontexten blockiert sein.
  }
}


function optionalGenerationNumber(value) {
  if (value === undefined || value === null || value === '') return undefined;
  const number = Number(value);
  return Number.isFinite(number) ? number : undefined;
}


function songDatabaseId(asset) {
  return asset?.song_id ?? asset?.song?.id ?? asset?.metadata_json?.song_id ?? null;
}

function assetDatabaseSummary(asset) {
  const songId = songDatabaseId(asset);
  return [
    `songs.id: ${songId ?? '—'}`,
    `audio_assets.id: ${asset?.id ?? '—'}`,
    `audio_id: ${asset?.audio_id || '—'}`,
    `task_id: ${asset?.suno_task_id || asset?.task_id || '—'}`
  ].join('\n');
}

function isFallbackCoverUrl(url) {
  return !url || String(url).includes('/static/favicon.ico');
}

function coverFileExtension(url) {
  try {
    const base = typeof window !== 'undefined' ? window.location.origin : 'http://localhost';
    const pathname = new URL(String(url || ''), base).pathname || '';
    const match = pathname.match(/\.([a-z0-9]{2,5})$/i);
    const ext = match ? match[1].toLowerCase() : '';
    return ['jpg', 'jpeg', 'png', 'webp', 'gif', 'avif'].includes(ext) ? ext : 'jpg';
  } catch {
    return 'jpg';
  }
}

function coverDownloadFilename(asset, url) {
  return `${safeFilename(pickTitle(asset) || `cover-${asset?.id || 'image'}`)}-cover.${coverFileExtension(url)}`;
}

function readAudioAiAnalysis(asset) {
  const metadata = asset?.metadata_json && typeof asset.metadata_json === 'object' ? asset.metadata_json : {};
  const analysis = metadata.audio_ai_analysis;
  return analysis && typeof analysis === 'object' ? analysis : null;
}

function readLibraryAiTags(asset) {
  const metadata = asset?.metadata_json && typeof asset.metadata_json === 'object' ? asset.metadata_json : {};
  const tags = metadata.ai_tags;
  return tags && typeof tags === 'object' ? tags : null;
}

function libraryAiTagList(asset) {
  const tags = readLibraryAiTags(asset);
  return Array.isArray(tags?.tags) ? tags.tags.filter(Boolean) : [];
}

function audioAiAnalysisBlocks(analysis, translate = null) {
  const tr = (key, fallback, values) => translateFallback(translate, key, fallback, values);
  const blocks = analysis?.ai_report?.blocks;
  if (Array.isArray(blocks) && blocks.length) {
    return blocks
      .filter((block) => block && typeof block === 'object')
      .map((block) => ({ title: String(block.title || tr('library.audioAnalysis.section', 'Abschnitt')), text: String(block.text || '').trim() }))
      .filter((block) => block.text);
  }
  const summary = analysis?.summary || {};
  const signal = analysis?.signal_analysis || {};
  const tempo = analysis?.tempo_analysis || {};
  return [
    {
      title: tr('library.audioAnalysis.quickOverview', 'Kurzüberblick'),
      text: [
        `${tr('common.title', 'Titel')}: ${analysis?.title || summary.title || '—'}`,
        `${tr('common.duration', 'Dauer')}: ${summary.duration_label || '—'}`,
        `BPM: ${summary.bpm || tempo.bpm || '—'}`,
        `${tr('library.audioAnalysis.loudness', 'Lautheit')}: ${summary.loudness || signal.estimated_loudness || '—'}`,
      ].join('\n')
    },
    {
      title: 'Tempo & Signal',
      text: [
        `${tr('library.audioAnalysis.beatConfidence', 'Beat-Konfidenz')}: ${tempo.confidence ?? '—'}`,
        `Beats: ${tempo.beat_count || 0}`,
        `${tr('library.audioAnalysis.rmsMean', 'RMS Mittel')}: ${signal.rms_mean ?? '—'}`,
        `Quiet Ratio: ${signal.quiet_ratio ?? '—'}`,
      ].join('\n')
    }
  ];
}

function audioAiAnalysisRiskClass(value) {
  const text = String(value || '').toLowerCase();
  if (['high', 'bad', 'error'].some((item) => text.includes(item))) return 'danger';
  if (['medium', 'warning', 'unknown'].some((item) => text.includes(item))) return 'warning';
  if (['low', 'good', 'success', 'cached'].some((item) => text.includes(item))) return 'success';
  return 'neutral';
}

function audioAiAnalysisTopLabel(section) {
  if (!section || typeof section !== 'object') return '—';
  const top = section.top && typeof section.top === 'object' ? section.top : null;
  if (top?.label) return `${top.label}${top.score !== undefined ? ` · ${top.score}` : ''}`;
  if (section.verdict) return section.verdict;
  if (section.dominant) return section.dominant;
  return '—';
}

function audioAiAnalysisMethodLabel(value, translate = null) {
  const tr = (key, fallback, values) => translateFallback(translate, key, fallback, values);
  const text = String(value || '').trim();
  const map = {
    local_audio_feature_heuristic: tr('library.audioAnalysis.methods.localAudioFeatureHeuristic', 'Lokale Audio-Heuristik'),
    transformers_audio_classification: tr('library.audioAnalysis.methods.transformersAudioClassification', 'Internes Audio-Modell'),
    transformers_ast_audioset: tr('library.audioAnalysis.methods.transformersAstAudioset', 'AST / AudioSet Modell'),
    acoustid_chromaprint: 'AcoustID / Chromaprint',
    internal_models: tr('library.audioAnalysis.methods.internalModels', 'Interne Modelle'),
    ai_report: tr('library.audioAnalysis.methods.aiReport', 'KI-Bericht')
  };
  return map[text] || text || tr('library.audioAnalysis.notDetermined', 'nicht bestimmt');
}

function audioAiCopyrightSummary(copyright = {}, translate = null) {
  const tr = (key, fallback, values) => translateFallback(translate, key, fallback, values);
  const matches = Array.isArray(copyright.db_matches) ? copyright.db_matches : [];
  if (matches.length > 0) {
    const first = matches[0] || {};
    return {
      value: tr('library.audioAnalysis.databaseMatch', 'Datenbanktreffer'),
      detail: `${first.title || tr('library.audioAnalysis.unknownTitle', 'Unbekannter Titel')}${first.artist ? ` - ${first.artist}` : ''}${first.score !== undefined ? ` (${first.score})` : ''}`,
      tone: 'danger'
    };
  }
  if (copyright.ok && copyright.db_lookup_performed) {
    return {
      value: tr('library.audioAnalysis.noAcoustIdMatch', 'Kein AcoustID-Treffer'),
      detail: tr('library.audioAnalysis.fingerprintCheckedHint', 'Fingerprint geprüft. Das ist ein Hinweis, aber keine Rechtsfreigabe.'),
      tone: 'success'
    };
  }
  if (copyright.ok && !copyright.db_lookup_performed) {
    return {
      value: tr('library.audioAnalysis.fingerprintCreated', 'Fingerprint erstellt'),
      detail: tr('library.audioAnalysis.noAcoustIdConfigured', 'Keine AcoustID-Abfrage konfiguriert. API-Key im Adminbereich hinterlegen.'),
      tone: 'warning'
    };
  }
  return {
    value: tr('library.audioAnalysis.notReliable', 'Nicht belastbar'),
    detail: copyright.error || copyright.verdict || tr('library.audioAnalysis.copyrightIncomplete', 'Copyright-Prüfung nicht abgeschlossen.'),
    tone: 'warning'
  };
}

function audioAiBlockTone(title) {
  const text = String(title || '').toLowerCase();
  if (text.includes('copyright') || text.includes('recht')) return 'copyright';
  if (text.includes('vocal') || text.includes('gesang')) return 'vocals';
  if (text.includes('genre') || text.includes('stimmung') || text.includes('mood')) return 'mood';
  if (text.includes('tempo') || text.includes('beat')) return 'tempo';
  if (text.includes('signal') || text.includes('lautheit')) return 'signal';
  return 'default';
}

function audioAiReportLead(blocks, analysis, translate = null) {
  const tr = (key, fallback, values) => translateFallback(translate, key, fallback, values);
  const preferred = blocks.find((block) => /ueberblick|überblick|summary|einschaetzung|einschätzung|kurz/i.test(block.title));
  const source = preferred || blocks[0] || null;
  if (source?.text) return source.text.split('\n').filter(Boolean).slice(0, 3).join(' ');
  const summary = analysis?.summary || {};
  return [
    summary.duration_label ? `${tr('common.duration', 'Dauer')} ${summary.duration_label}` : '',
    summary.bpm ? `${summary.bpm} BPM` : '',
    summary.loudness ? `${tr('library.audioAnalysis.loudness', 'Lautheit')} ${summary.loudness}` : ''
  ].filter(Boolean).join(' · ') || tr('library.audioAnalysis.savedLocally', 'Analyse lokal gespeichert.');
}

function audioAiReportLines(text) {
  return String(text || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
}

function audioAiAnalysisMetricCards(analysis, translate = null) {
  const tr = (key, fallback, values) => translateFallback(translate, key, fallback, values);
  const summary = analysis?.summary || {};
  const copyright = analysis?.copyright_analysis || {};
  const content = analysis?.content_analysis || {};
  const genre = content.genre || {};
  const mood = content.mood || {};
  const vocals = content.vocals || {};
  const authenticity = content.authenticity || {};
  const copyrightSummary = audioAiCopyrightSummary(copyright, translate);
  return [
    { label: 'Copyright', value: copyrightSummary.value, detail: copyrightSummary.detail, tone: copyrightSummary.tone },
    { label: 'Genre', value: audioAiAnalysisTopLabel(genre), detail: audioAiAnalysisMethodLabel(genre.method, translate), tone: genre.ok ? 'success' : 'warning' },
    { label: tr('library.audioAnalysis.mood', 'Stimmung'), value: audioAiAnalysisTopLabel(mood), detail: audioAiAnalysisMethodLabel(mood.method, translate), tone: mood.ok ? 'success' : 'neutral' },
    { label: 'Vocals', value: audioAiAnalysisTopLabel(vocals), detail: audioAiAnalysisMethodLabel(vocals.method, translate), tone: vocals.ok ? 'success' : 'neutral' },
    { label: tr('library.audioAnalysis.aiEvidence', 'KI-Indiz'), value: authenticity.verdict || tr('library.audioAnalysis.notChecked', 'nicht geprüft'), detail: authenticity.model || audioAiAnalysisMethodLabel(authenticity.method, translate), tone: audioAiAnalysisRiskClass(authenticity.verdict) },
    { label: 'Tempo', value: summary.bpm ? `${summary.bpm} BPM` : '—', detail: summary.tempo_confidence !== undefined ? `${tr('common.confidence', 'Sicherheit')} ${summary.tempo_confidence}` : '—', tone: 'success' },
  ];
}


const typeFilters = [
  ['all', 'Alle'],
  ['generate', 'Generiert'],
  ['manual', 'Importiert'],
  ['extend', 'Extended'],
  ['cover', 'Cover'],
  ['vocals', 'Vocals'],
  ['instrumental', 'Instrumental'],
  ['mashup', 'Mashup'],
  ['sounds', 'Sounds']
];

const primaryTypeFilters = typeFilters.filter(([key]) => ['all', 'generate'].includes(key));
const secondaryTypeFilters = typeFilters.filter(([key]) => !['all', 'generate'].includes(key));



function isAudioLocal(asset) {
  if (asset && Object.prototype.hasOwnProperty.call(asset, 'audio_local')) return Boolean(asset.audio_local);
  return String(asset?.audio_availability_status || asset?.status || '').toLowerCase() === 'cached';
}

function audioStatusClass(asset) {
  if (isAudioLocal(asset)) return 'cached';
  const status = String(asset?.audio_availability_status || asset?.status || 'remote').toLowerCase();
  return status || 'remote';
}

function audioStatusLabel(asset, translate = null) {
  const tr = (key, fallback, values) => translateFallback(translate, key, fallback, values);
  if (isAudioLocal(asset)) return tr('library.localFilter.audioLocal', 'Audio lokal');
  const status = String(asset?.audio_availability_status || asset?.status || 'remote').toLowerCase();
  if (status === 'missing') return tr('library.status.audioMissing', 'Audio fehlt');
  if (asset?.audio_local_reason) return tr('library.status.remoteStale', 'Remote / lokal veraltet');
  return asset?.status || status || 'remote';
}

function isAssetFullyLocal(asset) {
  return Boolean(isAudioLocal(asset) && isCoverCached(asset));
}

function fullLocalLabel(translate = null) {
  return translateFallback(translate, 'library.localFilter.local', 'Lokal');
}

function storageStatusLabel(asset, translate = null) {
  return isAssetFullyLocal(asset) ? fullLocalLabel(translate) : audioStatusLabel(asset, translate);
}

function assetMetadata(asset) {
  return asset?.metadata_json && typeof asset.metadata_json === 'object' ? asset.metadata_json : {};
}

function parseMetadataJsonObject(value) {
  if (!value || typeof value !== 'string') return null;
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch {
    return null;
  }
}

function deepFindFirstValue(source, keys, seen = new Set()) {
  if (!source || typeof source !== 'object' || seen.has(source)) return '';
  seen.add(source);
  for (const key of keys) {
    if (Object.prototype.hasOwnProperty.call(source, key)) {
      const value = source[key];
      if (value !== undefined && value !== null && value !== '') return value;
    }
  }
  for (const value of Object.values(source)) {
    if (value && typeof value === 'object') {
      const found = deepFindFirstValue(value, keys, seen);
      if (found !== undefined && found !== null && found !== '') return found;
    }
  }
  return '';
}

function metadataRequestPayloadCandidates(asset) {
  const metadata = assetMetadata(asset);
  const candidate = metadata.candidate && typeof metadata.candidate === 'object' ? metadata.candidate : {};
  return [
    metadata.request_payload,
    metadata.requestPayload,
    parseMetadataJsonObject(metadata.task_request_payload?.param),
    parseMetadataJsonObject(metadata.taskRequestPayload?.param),
    metadata.task_request_payload,
    metadata.taskRequestPayload,
    candidate.request_payload,
    candidate.requestPayload,
    parseMetadataJsonObject(metadata.param),
    parseMetadataJsonObject(candidate.param),
  ].filter((item) => item && typeof item === 'object');
}

function isExtendedAsset(asset) {
  const metadata = assetMetadata(asset);
  const requestCandidates = metadataRequestPayloadCandidates(asset);
  return [
    asset?.operation_type,
    asset?.task_type,
    asset?.operation_label,
    metadata.operation_type,
    metadata.task_type,
    ...requestCandidates.flatMap((request) => [request.operation_type, request.task_type, request.type]),
  ].some((value) => operationKey(value) === 'extend');
}

function extendSourceAudioId(asset) {
  const metadata = assetMetadata(asset);
  const direct = [
    asset?.source_audio_id,
    asset?.sourceAudioId,
    asset?.original_audio_id,
    asset?.originalAudioId,
    asset?.parent_audio_id,
    asset?.parentAudioId,
    metadata.source_audio_id,
    metadata.sourceAudioId,
    metadata.original_audio_id,
    metadata.originalAudioId,
    metadata.parent_audio_id,
    metadata.parentAudioId,
  ].find((value) => value !== undefined && value !== null && value !== '');
  if (direct) return String(direct);

  const sourceKeys = ['sourceAudioId', 'source_audio_id', 'originalAudioId', 'original_audio_id', 'parentAudioId', 'parent_audio_id', 'audioId', 'audio_id'];
  const fromRequest = metadataRequestPayloadCandidates(asset)
    .map((request) => deepFindFirstValue(request, sourceKeys))
    .find((value) => value !== undefined && value !== null && value !== '');
  return fromRequest ? String(fromRequest) : '';
}

function assetCapabilities(asset) {
  const metadata = assetMetadata(asset);
  return metadata.capabilities && typeof metadata.capabilities === 'object' ? metadata.capabilities : asset?.capabilities || {};
}

function isLocalOnlyAsset(asset) {
  const metadata = assetMetadata(asset);
  return Boolean(
    asset?.is_suno_clip_import || metadata.is_suno_clip_import || metadata.import_source === 'suno_public_clip' ||
    asset?.is_opencli_generation || metadata.is_opencli_generation || metadata.generation_source === 'opencli' || metadata.provider === 'opencli'
  );
}

function canUseSunoApiCapability(asset, key) {
  const caps = assetCapabilities(asset);
  if (caps && caps[key] === false) return false;
  if (isLocalOnlyAsset(asset) && String(key || '').startsWith('sunoapi_')) return false;
  return true;
}

function canUseSunoApiFollowups(asset) {
  return ['sunoapi_extend', 'sunoapi_cover_song', 'sunoapi_add_vocals', 'sunoapi_add_instrumental', 'sunoapi_create_cover', 'sunoapi_persona'].some((key) => canUseSunoApiCapability(asset, key));
}

function actionCapabilityKey(typeName) {
  return {
    Extend: 'sunoapi_extend',
    'Cover Song': 'sunoapi_cover_song',
    'Add Vocals': 'sunoapi_add_vocals',
    'Add Instrumental': 'sunoapi_add_instrumental',
    Persona: 'sunoapi_persona',
    'Cover-Bild': 'sunoapi_create_cover'
  }[typeName] || '';
}

function canRunSunoApiAction(asset, typeName) {
  const key = actionCapabilityKey(typeName);
  return !key || canUseSunoApiCapability(asset, key);
}

function localOnlyHint(asset, translate = null) {
  const tr = (key, fallback, values) => translateFallback(translate, key, fallback, values);
  if (!isLocalOnlyAsset(asset)) return '';
  const metadata = assetMetadata(asset);
  if (metadata.import_source === 'suno_public_clip' || metadata.is_suno_clip_import) return tr('library.messages.publicSunoImportLocalOnly', 'Öffentlicher Suno-Import: lokale Funktionen verfügbar, SunoAPI.org-Folgeaktionen deaktiviert.');
  if (metadata.generation_source === 'opencli' || metadata.provider === 'opencli' || metadata.is_opencli_generation) return tr('library.messages.openCliAssetLocalOnly', 'OpenCLI-Asset: lokale Funktionen verfügbar, SunoAPI.org-Folgeaktionen deaktiviert.');
  return tr('library.messages.localAssetSunoDisabled', 'Lokales Asset: SunoAPI.org-Folgeaktionen deaktiviert.');
}

function isProjectFullyLocal(project) {
  const rows = project?.assets || [];
  return Boolean(rows.length && rows.every(isAssetFullyLocal));
}

function assetSrtState(asset, srtByAsset = {}) {
  return asset?.id ? (srtByAsset[asset.id] || {}) : {};
}

function hasAssetSrt(asset, srtByAsset = {}) {
  const state = assetSrtState(asset, srtByAsset);
  return Boolean(asset?.srt_cached || state.exists || state.srt_text || state.srt_path || state.download_url);
}

function hasAssetHalfSrt(asset, srtByAsset = {}) {
  const state = assetSrtState(asset, srtByAsset);
  return Boolean(asset?.half_srt_cached || state.half_srt_exists || state.half_srt_text || state.half_download_url);
}

function hasAssetVideo(asset) {
  return Boolean(asset?.has_video || Number(asset?.video_count || 0) > 0 || asset?.latest_video?.id);
}

function latestAssetVideo(asset) {
  return asset?.latest_video && asset.latest_video.id ? asset.latest_video : null;
}

function videoIsLocallyPlayable(video) {
  const status = String(video?.status || '').toLowerCase();
  return Boolean(video?.video_local || video?.public_url || video?.local_path || video?.filename || status === 'cached');
}

function videoPlaybackUrl(asset, video) {
  if (!asset?.id || !video?.id) return '';
  // Lokale /media/videos-URLs bevorzugen: sie sind fuer <video> stabiler als
  // geschuetzte API-Fetches, weil Browser-Media-Elemente keine Bearer-Header
  // setzen koennen. Die API-Stream-Route bleibt Fallback und kann Remote-URLs
  // serverseitig sicher weiterleiten, wenn noch keine lokale Datei existiert.
  return video.public_url || video.stream_url || api.archive.videoStreamUrl(asset.id, video.id);
}

function videoDownloadUrl(asset, video) {
  if (!asset?.id || !video?.id) return '';
  return video.download_url || api.archive.videoDownloadUrl(asset.id, video.id);
}

function assetVideoSummary(asset) {
  const latest = latestAssetVideo(asset);
  const count = Math.max(Number(asset?.video_count || 0), latest?.id ? 1 : 0);
  return { latest, count, isLocal: videoIsLocallyPlayable(latest) };
}

function assetContentBadges(asset, srtByAsset = {}) {
  const badges = [];
  const metadata = asset?.metadata_json && typeof asset.metadata_json === 'object' ? asset.metadata_json : {};
  const stems = metadata.stems && typeof metadata.stems === 'object' ? metadata.stems : {};
  const stemFiles = stems.files && typeof stems.files === 'object' ? stems.files : {};
  const wav = metadata.wav_conversion && typeof metadata.wav_conversion === 'object' ? metadata.wav_conversion : {};
  if (hasAssetSrt(asset, srtByAsset)) badges.push({ key: 'srt', label: 'SRT', className: 'cached' });
  if (hasAssetVideo(asset)) badges.push({ key: 'mp4', label: 'MP4', className: 'cached' });
  if (stemFiles.vocals || stemFiles.instrumental) badges.push({ key: 'stems', label: 'STEMS', className: 'cached' });
  if (wav.available || wav.public_url || wav.download_url || wav.path) badges.push({ key: 'wav', label: 'WAV', className: 'cached' });
  if (metadata.timestamped_lyrics || metadata.timestampedLyrics) badges.push({ key: 'timestamped', label: 'TIMESTAMPED', className: 'cached' });
  return badges;
}

function projectContentBadgeLabel(project, predicate, label) {
  const rows = project?.assets || [];
  const total = rows.length;
  const count = rows.filter(predicate).length;
  if (!count) return '';
  return count === total ? label : `${count}/${total} ${label}`;
}

function normalizeRouteSlug(value) {
  const decoded = (() => {
    try { return decodeURIComponent(String(value || '')); } catch { return String(value || ''); }
  })();
  return decoded
    .trim()
    .toLowerCase()
    .replace(/[\/\?#]+/g, ' ')
    .replace(/[._]+/g, ' ')
    .replace(/[-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function routeTitleSlug(value, maxLength = 88) {
  const clean = String(value || '')
    .trim()
    .replace(/[\/\?#]+/g, ' ')
    .replace(/[._]+/g, ' ')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '');
  const limited = clean ? clean.slice(0, Math.max(24, maxLength)).replace(/-+$/g, '') : 'Projekt';
  return limited || 'Projekt';
}

function projectRouteNumericId(project) {
  const direct = String(project?.id || '').match(/^project-(\d+)$/i)?.[1];
  if (direct) return direct;
  const fromAsset = (project?.assets || []).map((asset) => asset?.project_id).find((value) => value !== undefined && value !== null && value !== '');
  return fromAsset !== undefined && fromAsset !== null && fromAsset !== '' ? String(fromAsset) : '';
}

function projectRouteDetail(project) {
  const numericId = projectRouteNumericId(project);
  const suffix = numericId ? `-${numericId}` : '';
  const title = project?.title || pickTitle(project?.assets?.[0]) || 'Projekt';
  return `${routeTitleSlug(title, 96 - suffix.length)}${suffix}`;
}

function parseRouteProjectHint(value) {
  const decoded = (() => {
    try { return decodeURIComponent(String(value || '')); } catch { return String(value || ''); }
  })().trim();
  const match = decoded.match(/^(.*?)-(\d+)$/);
  if (!match) return { decoded, normalized: normalizeRouteSlug(decoded), projectKey: '', titleSlug: '' };
  return {
    decoded,
    normalized: normalizeRouteSlug(decoded),
    projectKey: `project-${match[2]}`,
    numericId: match[2],
    titleSlug: normalizeRouteSlug(match[1]),
  };
}

function projectMatchesPrettyRoute(project, routeSlug) {
  const requested = normalizeRouteSlug(routeSlug);
  if (!requested || !project) return false;
  return normalizeRouteSlug(projectRouteDetail(project)) === requested;
}

function projectMatchesLegacyTitleRoute(project, routeSlug) {
  const requested = normalizeRouteSlug(routeSlug);
  if (!requested || !project) return false;
  const candidates = [
    project?.title,
    ...(project?.assets || []).map((asset) => pickTitle(asset)),
    ...(project?.assets || []).map((asset) => asset.display_title),
  ];
  return candidates.some((value) => normalizeRouteSlug(value) === requested);
}

function findProjectForRoute(projects, routeSlug, activeProject = null) {
  const parsed = parseRouteProjectHint(routeSlug);
  if (!parsed.normalized) return null;

  const exactPretty = projects.find((project) => projectMatchesPrettyRoute(project, routeSlug));
  if (exactPretty) return exactPretty;

  if (parsed.projectKey && parsed.titleSlug) {
    const byProjectIdAndTitle = projects.find((project) => {
      if (String(project?.id || '') !== parsed.projectKey) return false;
      return normalizeRouteSlug(project?.title || pickTitle(project?.assets?.[0]) || '') === parsed.titleSlug;
    });
    if (byProjectIdAndTitle) return byProjectIdAndTitle;
  }

  if (activeProject && projectMatchesLegacyTitleRoute(activeProject, routeSlug)) return activeProject;

  const legacyMatches = projects.filter((project) => projectMatchesLegacyTitleRoute(project, routeSlug));
  return legacyMatches.length === 1 ? legacyMatches[0] : null;
}

function variantPosition(asset, project) {
  const assets = project?.assets || [];
  const total = Number(asset?.project_variant_total || assets.length || 1);
  const explicit = Number(asset?.project_variant_index || 0);
  if (Number.isFinite(explicit) && explicit > 0) return { index: explicit, total: Math.max(total, explicit) };
  const index = Math.max(0, assets.findIndex((item) => String(item.id) === String(asset?.id))) + 1;
  return { index: index || 1, total: Math.max(total, assets.length || 1) };
}

function variantTitle(asset, project) {
  const { index, total } = variantPosition(asset, project);
  const title = pickTitle(asset);
  return total > 1 ? `${title} ${index}/${total}` : title;
}

function variantEyebrow(asset, project, translate = null) {
  const { index, total } = variantPosition(asset, project);
  const tr = (key, fallback, values) => translateFallback(translate, key, fallback, values);
  return `${tr('library.variant', 'Variante')} ${index}/${total} · ${operationLabel(asset?.operation_type || asset?.task_type || asset?.operation_label, translate)}`;
}

function withVariantPlaybackMeta(asset, project) {
  const { index, total } = variantPosition(asset, project);
  return {
    ...asset,
    project_variant_index: index,
    project_variant_total: total,
    project_variant_title: total > 1 ? `${pickTitle(asset)} ${index}/${total}` : pickTitle(asset),
    project_display_title: project?.title || asset?.project_display_title || pickTitle(asset),
  };
}

function normalizeSrtSegment(segment, index = 0) {
  const start = Math.max(0, Number(segment?.start ?? 0));
  const rawEnd = Number(segment?.end ?? start + 2);
  const end = Math.max(start + 0.25, Number.isFinite(rawEnd) ? rawEnd : start + 2);
  return {
    index: index + 1,
    start: Number(start.toFixed(3)),
    end: Number(end.toFixed(3)),
    text: String(segment?.text || '').trim()
  };
}

function parseSrtTimestamp(value) {
  const match = String(value || '').trim().replace('.', ',').match(/^(\d{1,2}):(\d{2}):(\d{2}),(\d{1,3})$/);
  if (!match) return 0;
  const [, h, m, s, ms] = match;
  return Number(h) * 3600 + Number(m) * 60 + Number(s) + Number(ms.padEnd(3, '0').slice(0, 3)) / 1000;
}

function parseSrtText(text) {
  const raw = String(text || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
  if (!raw) return [];
  const blocks = raw.split(/\n\s*\n+/);
  const timeRe = /(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})/;
  const rows = [];
  blocks.forEach((block) => {
    const lines = String(block || '').split('\n').map((line) => line.trim()).filter(Boolean);
    const timeIndex = lines.findIndex((line) => timeRe.test(line));
    if (timeIndex < 0) return;
    const match = lines[timeIndex].match(timeRe);
    const body = lines.slice(timeIndex + 1).join('\n').trim();
    if (!match || !body) return;
    rows.push(normalizeSrtSegment({ start: parseSrtTimestamp(match[1]), end: parseSrtTimestamp(match[2]), text: body }, rows.length));
  });
  return rows;
}

function srtSegmentsFromState(state) {
  const fileSegments = parseSrtText(state?.srt_text || '');
  if (fileSegments.length) return fileSegments;
  if (Array.isArray(state?.segments) && state.segments.length) {
    return state.segments.map(normalizeSrtSegment).filter((row) => row.text).sort((a, b) => a.start - b.start).map(normalizeSrtSegment);
  }
  return [];
}

function findActiveSrtSegment(segments, currentTime) {
  const t = Number(currentTime || 0);
  let active = null;
  for (const segment of segments || []) {
    const start = Number(segment.start || 0);
    const end = Number(segment.end || 0);
    if (t < start || t >= end) continue;
    if (!active || start > Number(active.start || 0)) active = segment;
  }
  return active;
}


function isFrontendInteractionActive() {
  if (typeof document === 'undefined') return false;
  const activeElement = document.activeElement;
  const tagName = String(activeElement?.tagName || '').toLowerCase();
  if (['input', 'textarea', 'select'].includes(tagName)) return true;
  if (activeElement?.isContentEditable) return true;
  try {
    const selection = typeof window !== 'undefined' && typeof window.getSelection === 'function' ? window.getSelection() : null;
    if (selection && !selection.isCollapsed && String(selection.toString() || '').trim()) return true;
  } catch {
    // Selection-Abfrage ist nur ein Schutz gegen UI-Störungen; bei Browserfehlern ignorieren.
  }
  return Boolean(
    document.querySelector('.audio-action-menu.is-open, .audio-action-menu-portal, .modal-backdrop, .modal, [role="dialog"], details[open]')
  );
}

export function LibraryPage({ assets, loadError = '', voices = [], playlists = [], onReload, onPlay, notify, onUseLyric, onReusePrompt, openAssetId, openAssetRequestKey = 0, onOpenAssetHandled, resetSignal = 0, onOpenDaw, playbackState = {}, onToggleCurrentPlayback, onDetailTitleChange, routeDetailSlug = '', searchQuery = '', onTrashChanged }) {
  const { t } = useI18n();
  const query = String(searchQuery || '');
  const [type, setType] = useState('all');
  const [sort, setSort] = useState('newest');
  const [localFilter, setLocalFilter] = useState('all');
  const [selectedProjectId, setSelectedProjectId] = useState(null);
  const [selectedProjectSnapshot, setSelectedProjectSnapshot] = useState(null);
  const handledOpenAssetIdRef = useRef('');
  const [actionAsset, setActionAsset] = useState(null);
  const [openAudioMenuId, setOpenAudioMenuId] = useState(null);
  const [openAudioMenuPosition, setOpenAudioMenuPosition] = useState(null);
  const audioMenuScrollRef = useRef({ key: '', scrollTop: 0 });
  const scrollRestoreTimerRef = useRef(null);
  const suppressRouteDetailOpenRef = useRef(false);
  const localDetailOpenGuardRef = useRef({ projectId: '', route: '', until: 0 });
  const detailScrollInteractionUntilRef = useRef(0);
  const detailScrollIdleTimerRef = useRef(null);
  const srtTaskWatchersRef = useRef({});
  const srtFetchInFlightRef = useRef({});
  const [playlistAsset, setPlaylistAsset] = useState(null);
  const [selectedPlaylistOpen, setSelectedPlaylistOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const [timestampAsset, setTimestampAsset] = useState(null);
  const [timestampLoading, setTimestampLoading] = useState(false);
  const [videoModal, setVideoModal] = useState({ asset: null, videos: [], loading: false, error: '' });
  const [manualImportOpen, setManualImportOpen] = useState(false);
  const [manualImportBusy, setManualImportBusy] = useState(false);
  const [lyricsEditorAssetId, setLyricsEditorAssetId] = useState(null);
  const [lyricsEditorAssetSnapshot, setLyricsEditorAssetSnapshot] = useState(null);
  const [lyricsEditorDraft, setLyricsEditorDraft] = useState('');
  const [lyricsEditorBusy, setLyricsEditorBusy] = useState(false);
  const [stemLoadingIds, setStemLoadingIds] = useState(() => new Set());
  const [wavLoadingIds, setWavLoadingIds] = useState(() => new Set());
  const [stemPreviewAsset, setStemPreviewAsset] = useState(null);
  const [audioAnalysisLoadingIds, setAudioAnalysisLoadingIds] = useState(() => new Set());
  const [audioAnalysisModal, setAudioAnalysisModal] = useState({ asset: null, analysis: null });
  const [workflowWizardAsset, setWorkflowWizardAsset] = useState(null);
  const [workflowWizardBusy, setWorkflowWizardBusy] = useState(false);
  const [aiCoverAsset, setAiCoverAsset] = useState(null);
  const [aiCoverBusy, setAiCoverBusy] = useState(false);
  const [aiCoverForm, setAiCoverForm] = useState({ model: 'pro', note: '', referenceFile: null });
  const [coverReplaceAsset, setCoverReplaceAsset] = useState(null);
  const [coverReplaceFile, setCoverReplaceFile] = useState(null);
  const [coverReplacePreviewUrl, setCoverReplacePreviewUrl] = useState('');
  const [coverReplaceBusy, setCoverReplaceBusy] = useState(false);
  const [pictureViewerAsset, setPictureViewerAsset] = useState(null);
  const [pictureViewerZoom, setPictureViewerZoom] = useState(1);
  const [pictureViewerMaximized, setPictureViewerMaximized] = useState(false);
  const [audioOperationModal, setAudioOperationModal] = useState({ type: '', asset: null });
  const [audioOperationForm, setAudioOperationForm] = useState({ model: 'V5_5', title: '', prompt: '', style: '', continueAt: '', customMode: true, instrumental: false, negative_tags: '' });
  const [audioOperationBusy, setAudioOperationBusy] = useState(false);
  const [continueAtAnalysisBusy, setContinueAtAnalysisBusy] = useState(false);
  const [contentCacheBusy, setContentCacheBusy] = useState(false);
  const [workflowCaptureState, setWorkflowCaptureState] = useState(defaultWizardCaptureState);
  const [bundleContentState, setBundleContentState] = useState(defaultBundleContentState);
  const [libraryViewMode, setLibraryViewModeState] = useState(() => readStoredChoice(libraryViewStorageKey, libraryViewModes, 'list'));
  const [libraryGalleryMode, setLibraryGalleryModeState] = useState(() => readStoredChoice(libraryGalleryModeStorageKey, librarySubModes, 'advanced'));
  const [libraryFlatListMode, setLibraryFlatListModeState] = useState(() => readStoredChoice(libraryFlatListModeStorageKey, librarySubModes, 'advanced'));
  const [libraryFlatListScale, setLibraryFlatListScale] = useState(() => {
    try {
      const value = Number(localStorage.getItem('react-library-flat-list-scale') || 1);
      return Number.isFinite(value) ? Math.max(0, Math.min(2, value)) : 1;
    } catch { return 1; }
  });
  const [libraryGalleryColumns, setLibraryGalleryColumns] = useState(() => {
    try { return localStorage.getItem('react-library-gallery-columns') || '5'; } catch { return '5'; }
  });
  const [libraryPageSize, setLibraryPageSize] = useState(() => {
    try { return localStorage.getItem('react-library-page-size') || '25'; } catch { return '25'; }
  });
  const [libraryPage, setLibraryPage] = useState(1);
  const [srtByAsset, setSrtByAsset] = useState({});
  const [srtLoadingIds, setSrtLoadingIds] = useState(() => new Set());
  const [srtSavingIds, setSrtSavingIds] = useState(() => new Set());
  const [srtEditorAssetId, setSrtEditorAssetId] = useState(null);
  const [srtRawOpenIds, setSrtRawOpenIds] = useState(() => new Set());
  const [srtDraftByAsset, setSrtDraftByAsset] = useState({});
  const [variantAccordionState, setVariantAccordionState] = useState({});
  const [srtLiveColor, setSrtLiveColor] = useState(() => {
    try {
      return localStorage.getItem('react-srt-live-color') || 'cyan';
    } catch {
      return 'cyan';
    }
  });
  const [locallyDeletedAssetIds, setLocallyDeletedAssetIds] = useState(() => new Set());
  const [bulkActionBusy, setBulkActionBusy] = useState('');
  const localizedTypeFilters = useMemo(() => typeFilters.map(([key, label]) => [key, t(`library.typeFilters.${key}`, label)]), [t]);
  const localizedPrimaryTypeFilters = useMemo(() => localizedTypeFilters.filter(([key]) => ['all', 'generate'].includes(key)), [localizedTypeFilters]);
  const localizedSecondaryTypeFilters = useMemo(() => localizedTypeFilters.filter(([key]) => !['all', 'generate'].includes(key)), [localizedTypeFilters]);
  const [favoriteSavingIds, setFavoriteSavingIds] = useState(() => new Set());
  const [favoriteOverrides, setFavoriteOverrides] = useState({});
  const [coverOverrides, setCoverOverrides] = useState({});

  function setLibraryViewMode(value) {
    if (!libraryViewModes.includes(value)) return;
    writeStoredChoice(libraryViewStorageKey, value, libraryViewModes);
    setLibraryViewModeState(value);
  }

  function setLibraryGalleryMode(value) {
    if (!librarySubModes.includes(value)) return;
    writeStoredChoice(libraryGalleryModeStorageKey, value, librarySubModes);
    setLibraryGalleryModeState(value);
  }

  function setLibraryFlatListMode(value) {
    if (!librarySubModes.includes(value)) return;
    writeStoredChoice(libraryFlatListModeStorageKey, value, librarySubModes);
    setLibraryFlatListModeState(value);
  }

  const visibleAssets = useMemo(() => {
    if (!locallyDeletedAssetIds.size) return assets || [];
    return (assets || []).filter((asset) => !locallyDeletedAssetIds.has(String(asset.id)));
  }, [assets, locallyDeletedAssetIds]);

  const effectiveAssets = useMemo(() => (visibleAssets || []).map((asset) => {
    const key = String(asset?.id || '');
    let nextAsset = asset;
    if (key && Object.prototype.hasOwnProperty.call(favoriteOverrides, key)) {
      nextAsset = { ...nextAsset, is_favorite: Boolean(favoriteOverrides[key]) };
    }
    if (key && Object.prototype.hasOwnProperty.call(coverOverrides, key)) {
      const coverUrl = coverOverrides[key];
      const metadata = nextAsset?.metadata_json && typeof nextAsset.metadata_json === 'object' ? { ...nextAsset.metadata_json } : {};
      const coverCache = metadata.cover_cache && typeof metadata.cover_cache === 'object' ? { ...metadata.cover_cache } : {};
      coverCache.public_url = coverUrl;
      coverCache.status = coverCache.status || 'cached';
      metadata.cover_cache = coverCache;
      nextAsset = { ...nextAsset, image_url: coverUrl, cover_local_url: coverUrl, cover_cached: true, metadata_json: metadata };
    }
    return nextAsset;
  }), [visibleAssets, favoriteOverrides, coverOverrides]);
  const selectedAssets = useMemo(() => {
    if (!selectedIds.size) return [];
    const selectedKeys = new Set([...selectedIds].map((id) => String(id)));
    return effectiveAssets.filter((asset) => selectedKeys.has(String(asset.id)));
  }, [effectiveAssets, selectedIds]);

  const projects = useMemo(() => groupAssetsByProject(effectiveAssets), [effectiveAssets]);
  const assetByAudioId = useMemo(() => {
    const rows = new Map();
    effectiveAssets.forEach((asset) => {
      if (asset?.audio_id) rows.set(String(asset.audio_id), asset);
    });
    return rows;
  }, [effectiveAssets]);
  const projectByAssetId = useMemo(() => {
    const rows = new Map();
    projects.forEach((project) => {
      (project.assets || []).forEach((asset) => rows.set(String(asset.id), project));
    });
    return rows;
  }, [projects]);
  const filteredProjects = useMemo(() => {
    const needle = query.trim().toLowerCase();
    let rows = projects.filter((project) => {
      const matchesQuery = !needle || [project.title, ...project.assets.map(assetSearchText)].join(' ').toLowerCase().includes(needle);
      const matchesType = type === 'all' || project.assets.some((asset) => operationKey(asset.operation_type || asset.task_type || asset.operation_label) === type);
      const matchesLocal = localFilter === 'all'
        || (localFilter === 'audio-local' && project.assets.some(isAudioLocal))
        || (localFilter === 'cover-local' && project.assets.some(isCoverCached))
        || (localFilter === 'missing-backup' && project.assets.some((asset) => !isAudioLocal(asset) || !isCoverCached(asset)))
        || (localFilter === 'favorites' && project.assets.some((asset) => isAssetFavorite(asset) || asset.is_final));
      return matchesQuery && matchesType && matchesLocal;
    });
    rows = [...rows].sort((a, b) => {
      if (sort === 'title') return String(a.title || '').localeCompare(String(b.title || ''), 'de', { sensitivity: 'base' });
      if (sort === 'oldest') return stableLibrarySortValue(a) - stableLibrarySortValue(b);
      if (sort === 'updated') return updatedLibrarySortValue(b) - updatedLibrarySortValue(a);
      if (sort === 'variants') {
        const byVariants = b.assets.length - a.assets.length;
        return byVariants !== 0 ? byVariants : stableLibrarySortValue(b) - stableLibrarySortValue(a);
      }
      return stableLibrarySortValue(b) - stableLibrarySortValue(a);
    });
    return rows;
  }, [projects, query, sort, type, localFilter]);

  const filteredGalleryAssets = useMemo(() => filteredProjects.flatMap((project) => project.assets.map((asset, index) => ({
    project,
    asset,
    index,
    label: `Variante ${index + 1}/${project.assets.length || 1}`
  }))), [filteredProjects]);
  const isFlatAssetView = libraryViewMode === 'flat-list' || (libraryViewMode === 'gallery' && libraryGalleryMode === 'simple');
  const libraryPaginationTotal = isFlatAssetView ? filteredGalleryAssets.length : filteredProjects.length;
  const libraryStats = useMemo(() => {
    const variants = filteredProjects.reduce((sum, project) => sum + (project.assets?.length || 0), 0);
    const playable = filteredProjects.reduce((sum, project) => sum + (project.playable?.length || 0), 0);
    const favorites = filteredProjects.reduce((sum, project) => sum + (project.assets || []).filter((asset) => isAssetFavorite(asset) || asset.is_final).length, 0);
    return {
      groups: filteredProjects.length,
      variants,
      playable,
      favorites,
      totalGroups: projects.length,
      totalVariants: effectiveAssets.length,
    };
  }, [filteredProjects, projects.length, effectiveAssets.length, favoriteOverrides]);
  const libraryPageSizeNumber = libraryPageSize === 'all' ? libraryPaginationTotal || 1 : Number(libraryPageSize || 25);
  const libraryTotalPages = libraryPageSize === 'all' ? 1 : Math.max(1, Math.ceil(libraryPaginationTotal / Math.max(1, libraryPageSizeNumber)));
  const safeLibraryPage = Math.min(Math.max(1, libraryPage), libraryTotalPages);
  const pagedProjects = libraryPageSize === 'all' ? filteredProjects : filteredProjects.slice((safeLibraryPage - 1) * libraryPageSizeNumber, safeLibraryPage * libraryPageSizeNumber);
  const pagedGalleryAssets = libraryPageSize === 'all' ? filteredGalleryAssets : filteredGalleryAssets.slice((safeLibraryPage - 1) * libraryPageSizeNumber, safeLibraryPage * libraryPageSizeNumber);
  const galleryGridStyle = { '--gallery-columns': String(libraryGalleryColumns || '5') };
  const flatListScaleLabel = ['Kompakt', 'Normal', 'Breit'][libraryFlatListScale] || 'Normal';
  const flatListScaleShortLabel = ['Komp.', 'Normal', 'Breit'][libraryFlatListScale] || 'Normal';

  useEffect(() => { setLibraryPage(1); }, [query, type, sort, localFilter, libraryPageSize, libraryViewMode, libraryGalleryMode, libraryFlatListMode, libraryGalleryColumns]);
  useEffect(() => {
    writeStoredChoice(libraryViewStorageKey, libraryViewMode, libraryViewModes);
  }, [libraryViewMode]);
  useEffect(() => {
    writeStoredChoice(libraryGalleryModeStorageKey, libraryGalleryMode, librarySubModes);
  }, [libraryGalleryMode]);
  useEffect(() => {
    writeStoredChoice(libraryFlatListModeStorageKey, libraryFlatListMode, librarySubModes);
  }, [libraryFlatListMode]);
  useEffect(() => {
    try { localStorage.setItem('react-library-flat-list-scale', String(libraryFlatListScale)); } catch {}
  }, [libraryFlatListScale]);
  useEffect(() => {
    try { localStorage.setItem('react-library-gallery-columns', libraryGalleryColumns); } catch {}
  }, [libraryGalleryColumns]);
  useEffect(() => {
    try { localStorage.setItem('react-library-page-size', libraryPageSize); } catch {}
  }, [libraryPageSize]);

  const activeProject = selectedProjectId
    ? (projects.find((project) => String(project.id) === String(selectedProjectId))
      || (String(selectedProjectSnapshot?.id || '') === String(selectedProjectId) ? selectedProjectSnapshot : null))
    : null;
  const srtEditorAsset = useMemo(() => effectiveAssets.find((item) => String(item.id) === String(srtEditorAssetId)) || null, [effectiveAssets, srtEditorAssetId]);
  const lyricsEditorAsset = useMemo(() => {
    if (!lyricsEditorAssetId) return null;
    const resolved = effectiveAssets.find((item) => String(item.id) === String(lyricsEditorAssetId));
    return resolved || lyricsEditorAssetSnapshot || null;
  }, [effectiveAssets, lyricsEditorAssetId, lyricsEditorAssetSnapshot]);
  const activeProjectFilteredIndex = activeProject ? filteredProjects.findIndex((project) => String(project.id) === String(activeProject.id)) : -1;
  const navigationProjects = activeProjectFilteredIndex >= 0 ? filteredProjects : projects;
  const activeProjectIndex = activeProject ? navigationProjects.findIndex((project) => String(project.id) === String(activeProject.id)) : -1;
  const previousProject = activeProjectIndex > 0 ? navigationProjects[activeProjectIndex - 1] : null;
  const nextProject = activeProjectIndex >= 0 && activeProjectIndex < navigationProjects.length - 1 ? navigationProjects[activeProjectIndex + 1] : null;
  const srtLiveColorOption = srtLiveColorOptions.find((item) => item.key === srtLiveColor) || srtLiveColorOptions[0];
  const srtLiveColorStyle = { '--srt-live-color': srtLiveColorOption.value };

  function windowScrollSnapshot() {
    if (typeof window === 'undefined') return null;
    return { x: window.scrollX || 0, y: window.scrollY || 0 };
  }

  function restoreWindowScrollSoon(snapshot) {
    if (!snapshot || typeof window === 'undefined') return;
    const restore = () => window.scrollTo(snapshot.x || 0, snapshot.y || 0);
    window.requestAnimationFrame?.(restore);
    if (scrollRestoreTimerRef.current) window.clearTimeout(scrollRestoreTimerRef.current);
    scrollRestoreTimerRef.current = window.setTimeout(restore, 80);
  }

  function preserveWindowScroll(action) {
    const snapshot = windowScrollSnapshot();
    const result = action?.();
    restoreWindowScrollSoon(snapshot);
    return result;
  }

  async function preserveWindowScrollAsync(action) {
    const snapshot = windowScrollSnapshot();
    try {
      return await action?.();
    } finally {
      restoreWindowScrollSoon(snapshot);
    }
  }

  useEffect(() => () => {
    if (scrollRestoreTimerRef.current) window.clearTimeout(scrollRestoreTimerRef.current);
  }, []);

  function closeProjectDetails() {
    suppressRouteDetailOpenRef.current = true;
    localDetailOpenGuardRef.current = { projectId: '', route: '', until: 0 };
    setSelectedProjectId(null);
    setSelectedProjectSnapshot(null);
    setSelectedIds(new Set());
    onDetailTitleChange?.('');
    try {
      const base = window.location.pathname.startsWith('/react/library') ? '/react/library' : '/library';
      if (window.location.pathname.replace(/\/+$/, '') !== base) {
        window.history.pushState({ activeTab: 'library' }, '', base);
      }
    } catch {
      // Routing-Fallback läuft über App.jsx / onDetailTitleChange.
    }
  }

  function openProjectDetails(project, event = null, options = {}) {
    suppressRouteDetailOpenRef.current = false;
    event?.preventDefault?.();
    event?.stopPropagation?.();
    if (!project?.id) return;
    const route = projectRouteDetail(project);
    const alreadyActiveProject = String(selectedProjectId || '') === String(project.id);
    const publishRoute = options?.publishRoute !== false;
    const guardMs = Number(options?.guardMs || 3000);
    if (publishRoute) {
      localDetailOpenGuardRef.current = { projectId: String(project.id), route, until: Date.now() + guardMs };
    }
    setSelectedProjectSnapshot(project);
    setSelectedProjectId(project.id);
    setSelectedIds(new Set());
    collapseAllVariants(project);
    if (publishRoute) onDetailTitleChange?.(route);
    const shouldScrollToTop = options?.scrollToTop !== false && (!alreadyActiveProject || Boolean(event));
    if (shouldScrollToTop) {
      try {
        window.scrollTo({ top: 0, behavior: 'smooth' });
      } catch {
        window.scrollTo(0, 0);
      }
    }
  }

  useEffect(() => {
    if (!selectedProjectId) return;
    const refreshed = projects.find((project) => String(project.id) === String(selectedProjectId));
    if (refreshed && refreshed !== selectedProjectSnapshot) {
      setSelectedProjectSnapshot(refreshed);
    }
  }, [projects, selectedProjectId]);

  useEffect(() => {
    if (activeProject?.id) {
      const currentRoute = projectRouteDetail(activeProject);
      const guardedProjectId = localDetailOpenGuardRef.current?.projectId || '';
      const guardActive = guardedProjectId
        && String(activeProject.id) === String(guardedProjectId)
        && Date.now() < Number(localDetailOpenGuardRef.current?.until || 0);
      if (guardActive || !routeDetailSlug || !projectMatchesPrettyRoute(activeProject, routeDetailSlug)) {
        onDetailTitleChange?.(currentRoute);
      }
    } else if (!routeDetailSlug) {
      onDetailTitleChange?.('');
    }
  }, [activeProject?.id, activeProject?.title, routeDetailSlug, onDetailTitleChange]);

  useEffect(() => () => {
    if (!routeDetailSlug) onDetailTitleChange?.('');
  }, [onDetailTitleChange, routeDetailSlug]);

  useEffect(() => {
    if (!activeProject?.id || typeof window === 'undefined') return undefined;
    const markDetailScrollInteraction = () => {
      detailScrollInteractionUntilRef.current = Date.now() + 900;
      if (detailScrollIdleTimerRef.current) window.clearTimeout(detailScrollIdleTimerRef.current);
      detailScrollIdleTimerRef.current = window.setTimeout(() => {
        if (Date.now() >= Number(detailScrollInteractionUntilRef.current || 0)) detailScrollInteractionUntilRef.current = 0;
        detailScrollIdleTimerRef.current = null;
      }, 950);
    };
    window.addEventListener('wheel', markDetailScrollInteraction, { passive: true });
    window.addEventListener('touchmove', markDetailScrollInteraction, { passive: true });
    window.addEventListener('scroll', markDetailScrollInteraction, { passive: true });
    return () => {
      window.removeEventListener('wheel', markDetailScrollInteraction);
      window.removeEventListener('touchmove', markDetailScrollInteraction);
      window.removeEventListener('scroll', markDetailScrollInteraction);
      if (detailScrollIdleTimerRef.current) window.clearTimeout(detailScrollIdleTimerRef.current);
      detailScrollIdleTimerRef.current = null;
      detailScrollInteractionUntilRef.current = 0;
    };
  }, [activeProject?.id]);

  // WICHTIGER STABILITAETS-CONTRACT:
  // Inhaltsseiten duerfen nicht mehr auf Live-SRT-Zeilenwechsel reagieren.
  // Die aktive SRT-Zeile wird ausschliesslich im MiniPlayer live aktualisiert.
  // Library/Editoren bleiben dadurch bei Wiedergabe stabil: keine Re-Renders bei
  // Zeilenwechseln, keine springenden Dropdowns, keine zerstoerte Textauswahl.


  useEffect(() => () => {
    Object.values(srtTaskWatchersRef.current || {}).forEach((watcher) => {
      if (watcher?.timer) window.clearTimeout(watcher.timer);
    });
    srtTaskWatchersRef.current = {};
  }, []);

  useEffect(() => {
    if (!coverReplaceFile || typeof URL === 'undefined' || typeof URL.createObjectURL !== 'function') {
      setCoverReplacePreviewUrl('');
      return undefined;
    }
    const nextUrl = URL.createObjectURL(coverReplaceFile);
    setCoverReplacePreviewUrl(nextUrl);
    return () => URL.revokeObjectURL(nextUrl);
  }, [coverReplaceFile]);

  function liveSrtLineForAsset(asset) {
    if (!asset?.id) return null;
    const assetId = String(asset.id);
    const currentAssetId = String(playbackState?.currentAssetId || '');
    if (!currentAssetId || currentAssetId !== assetId) return null;

    // Nur Snapshot-Anzeige fuer Detail-/Editorbereiche: Die Live-Zeit wird nicht
    // per globalem SRT-Zeilenwechsel nachgefuehrt. Echte Live-Untertitel bleiben
    // ausschliesslich im MiniPlayer, damit alle anderen Seitenbereiche bedienbar
    // bleiben (Textauswahl, Dropdowns, Scrollen, Modals).
    const snapshotTime = Number(playbackState?.currentTime || 0);
    const state = srtByAsset[asset.id] || {};
    const segments = srtSegmentsFromState(state);
    if (!segments.length) return null;
    const visible = findActiveSrtSegment(segments, snapshotTime);
    if (!visible?.text) return null;
    return {
      assetId: asset.id,
      text: String(visible.text || '').trim(),
      start: Number(visible.start || 0),
      end: Number(visible.end || 0),
      currentTime: snapshotTime,
      isPlaying: Boolean(playbackState?.isPlaying),
      hasSrt: true,
    };
  }

  useEffect(() => {
    if (!locallyDeletedAssetIds.size) return;
    const stillReturned = new Set((assets || []).map((asset) => String(asset.id)));
    setLocallyDeletedAssetIds((current) => {
      const next = new Set();
      current.forEach((id) => {
        if (stillReturned.has(String(id))) next.add(String(id));
      });
      return next.size === current.size ? current : next;
    });
  }, [assets, locallyDeletedAssetIds.size]);

  useEffect(() => {
    setSelectedIds((current) => {
      if (!current.size) return current;
      const allowed = new Set(visibleAssets.map((asset) => asset.id));
      const next = new Set([...current].filter((id) => allowed.has(id)));
      return next.size === current.size ? current : next;
    });
    if (selectedProjectId && !projects.some((project) => String(project.id) === String(selectedProjectId)) && !selectedProjectSnapshot) {
      closeProjectDetails();
    }
  }, [visibleAssets, projects, selectedProjectId, selectedProjectSnapshot]);

  function variantAccordionKey(asset, index = 0) {
    return String(asset?.id ?? `${activeProject?.id || 'project'}-${index}`);
  }

  function isVariantAccordionOpen(asset, index = 0) {
    const key = variantAccordionKey(asset, index);
    if (Object.prototype.hasOwnProperty.call(variantAccordionState, key)) {
      return Boolean(variantAccordionState[key]);
    }
    return false;
  }

  function toggleVariantAccordion(asset, index = 0) {
    const key = variantAccordionKey(asset, index);
    setVariantAccordionState((current) => ({
      ...current,
      [key]: !isVariantAccordionOpen(asset, index)
    }));
  }

  function openAllVariants(project) {
    if (!project?.assets?.length) return;
    setVariantAccordionState((current) => {
      const next = { ...current };
      project.assets.forEach((asset, index) => {
        next[variantAccordionKey(asset, index)] = true;
      });
      return next;
    });
  }

  function collapseAllVariants(project) {
    if (!project?.assets?.length) return;
    setVariantAccordionState((current) => {
      const next = { ...current };
      project.assets.forEach((asset, index) => {
        next[variantAccordionKey(asset, index)] = false;
      });
      return next;
    });
  }

  useEffect(() => {
    try {
      localStorage.setItem('react-srt-live-color', srtLiveColor);
    } catch {
      // localStorage kann in restriktiven Browser-Kontexten blockiert sein.
    }
  }, [srtLiveColor]);

  function SrtLiveColorSelect({ compact = false } = {}) {
    return (
      <label className={`srt-live-color-select ${compact ? 'compact' : ''}`}>
        <span>{t('library.srt.subtitleColor', 'Untertitelfarbe')}</span>
        <select value={srtLiveColor} onChange={(event) => setSrtLiveColor(event.target.value)}>
          {srtLiveColorOptions.map((option) => <option key={option.key} value={option.key}>{t(`library.srtLiveColors.${option.key}`, option.label)}</option>)}
        </select>
      </label>
    );
  }

  function resolveSrtTargetAssetId(detail = {}) {
    const explicit = detail.audio_asset_id || detail.asset_id || detail.id;
    if (explicit) return explicit;
    if (playbackState?.currentAssetId) return playbackState.currentAssetId;
    const playable = activeProject?.assets?.find(isPlayable) || activeProject?.assets?.[0];
    if (playable?.id) return playable.id;
    return visibleAssets.find(isPlayable)?.id || visibleAssets[0]?.id || null;
  }

  function ensureSrtEditorDraft(assetId, stateOverride = null) {
    const source = stateOverride || srtByAsset[assetId] || {};
    const segments = srtSegmentsFromState(source);
    setSrtDraftByAsset((current) => ({ ...current, [assetId]: current[assetId]?.length ? current[assetId] : segments }));
    return segments;
  }

  function setSrtEditorOpen(assetId, open = true) {
    if (open && assetId) {
      setSrtEditorAssetId(String(assetId));
      return;
    }
    setSrtEditorAssetId(null);
  }

  function setSrtRawOpen(assetId, open = true) {
    setSrtRawOpenIds((current) => {
      const next = new Set(current);
      if (open) next.add(assetId); else next.delete(assetId);
      return next;
    });
  }

  useEffect(() => {
    function focusEditor(event) {
      const assetId = resolveSrtTargetAssetId(event.detail || {});
      if (!assetId) return notify?.(t('library.messages.noSrtEditorAsset', 'Kein AudioAsset für den SRT-Editor gefunden.'), 'error');
      ensureSrtEditorDraft(assetId);
      setSrtEditorOpen(assetId, true);
      window.setTimeout(() => document.querySelector(`[data-react-asset-row="${CSS.escape(String(assetId))}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 100);
      notify?.(t('library.messages.srtEditorOpened', 'SRT-Editor geöffnet.'), 'info');
    }
    function addSegmentFromAssistant(event) {
      const assetId = resolveSrtTargetAssetId(event.detail || {});
      const asset = visibleAssets.find((item) => String(item.id) === String(assetId));
      if (!asset) return notify?.(t('library.messages.noSrtSegmentAsset', 'Kein AudioAsset für das neue SRT-Segment gefunden.'), 'error');
      addSrtSegment(asset, null, Number(event.detail?.start ?? playbackState?.currentTime ?? 0), event.detail?.text || t('library.srt.newSubtitleLine', 'Neue Untertitel-Zeile'));
      setSrtEditorOpen(asset.id, true);
    }
    window.addEventListener('assistant:srt-focus-editor', focusEditor);
    window.addEventListener('assistant:srt-add-segment', addSegmentFromAssistant);
    return () => {
      window.removeEventListener('assistant:srt-focus-editor', focusEditor);
      window.removeEventListener('assistant:srt-add-segment', addSegmentFromAssistant);
    };
  }, [visibleAssets, activeProject?.id, playbackState?.currentAssetId, srtByAsset]);

  useEffect(() => {
    const requestedAssetId = String(openAssetId || '').trim();
    if (!requestedAssetId) {
      handledOpenAssetIdRef.current = '';
      return;
    }
    const requestKey = `${requestedAssetId}:${openAssetRequestKey || 0}`;
    if (handledOpenAssetIdRef.current === requestKey) return;
    const project = projects.find((row) => row.assets.some((asset) => String(asset.id) === requestedAssetId));
    if (!project) return;
    handledOpenAssetIdRef.current = requestKey;
    openProjectDetails(project);
    window.setTimeout(() => document.querySelector(`[data-react-asset-row="${CSS.escape(requestedAssetId)}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 150);
    onOpenAssetHandled?.();
  }, [openAssetId, openAssetRequestKey, projects, onOpenAssetHandled]);

  useEffect(() => {
    const requested = normalizeRouteSlug(routeDetailSlug);
    if (!requested) {
      suppressRouteDetailOpenRef.current = false;
      return;
    }
    if (suppressRouteDetailOpenRef.current) return;
    if (!projects.length) return;

    const guardedProjectId = localDetailOpenGuardRef.current?.projectId || '';
    const guardActive = guardedProjectId && Date.now() < Number(localDetailOpenGuardRef.current?.until || 0);
    if (guardActive && activeProject && String(activeProject.id) === String(guardedProjectId)) {
      // Ein lokaler Klick ist die Quelle der Wahrheit, bis App.jsx die neue URL synchronisiert hat.
      // Alte routeDetailSlug-Werte dürfen die frisch geöffnete Detailseite in diesem Fenster nicht überschreiben.
      return;
    }

    if (activeProject && projectMatchesPrettyRoute(activeProject, routeDetailSlug)) return;
    const project = findProjectForRoute(projects, routeDetailSlug, activeProject);
    if (project && String(project.id) !== String(activeProject?.id || '')) openProjectDetails(project, null, { publishRoute: false });
  }, [routeDetailSlug, projects, activeProject?.id]);

  useEffect(() => {
    const requested = normalizeRouteSlug(routeDetailSlug);
    if (requested === 'favorites' || requested === 'favoriten') {
      setLocalFilter('favorites');
      setSelectedProjectId(null);
      setSelectedProjectSnapshot(null);
      onDetailTitleChange?.('Favoriten');
    }
  }, [routeDetailSlug]);

  useEffect(() => {
    if (!resetSignal) return;
    closeProjectDetails();
  }, [resetSignal]);

  useEffect(() => {
    if (!openAudioMenuId) return undefined;
    function closeOnPointerDown(event) {
      if (!event.target?.closest?.('.audio-action-menu-shell, .audio-action-menu-portal')) {
        setOpenAudioMenuId(null);
        setOpenAudioMenuPosition(null);
      }
    }
    function closeOnEscape(event) {
      if (event.key === 'Escape') {
        setOpenAudioMenuId(null);
        setOpenAudioMenuPosition(null);
      }
    }
    document.addEventListener('pointerdown', closeOnPointerDown);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('pointerdown', closeOnPointerDown);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [openAudioMenuId]);

  function fetchSrtStateOnce(assetId) {
    const key = String(assetId || '').trim();
    if (!key) return Promise.resolve([assetId, { audio_asset_id: assetId, exists: false, status: 'missing' }]);
    if (srtFetchInFlightRef.current[key]) return srtFetchInFlightRef.current[key];
    const request = api.archive.getSrt(key)
      .then((data) => [key, data])
      .catch((err) => [key, { audio_asset_id: key, exists: false, status: 'error', error_message: err?.message || 'SRT-Status konnte nicht geladen werden.' }])
      .finally(() => {
        if (srtFetchInFlightRef.current[key] === request) delete srtFetchInFlightRef.current[key];
      });
    srtFetchInFlightRef.current[key] = request;
    return request;
  }

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    let cancelled = false;

    function normalizeIncomingSrt(assetId, incoming) {
      if (!incoming || typeof incoming !== 'object') return null;
      return {
        ...incoming,
        audio_asset_id: Number(assetId) || assetId,
      };
    }

    async function reloadSrtState(assetId) {
      const [id, data] = await fetchSrtStateOnce(assetId);
      if (cancelled) return;
      setSrtByAsset((current) => ({ ...current, [id]: data }));
    }

    function handleExternalSrtUpdated(event) {
      const detail = event?.detail || {};
      const assetId = String(detail.audio_asset_id || detail.asset_id || detail.id || '').trim();
      if (!assetId) return;

      const incoming = detail.srt || detail.transcript || detail.result || null;
      const normalized = normalizeIncomingSrt(assetId, incoming);
      if (normalized) {
        setSrtByAsset((current) => ({
          ...current,
          [assetId]: { ...(current[assetId] || {}), ...normalized },
        }));
      }

      // Der MiniPlayer feuert das Event teils sofort mit RUNNING-Status und
      // später mit fertigem SRT-State. Falls nur ein generisches Event kommt
      // oder der State noch keinen Roh-SRT enthält, zieht die Detailansicht den
      // finalen Status selbst nach. Dadurch werden neu erzeugte SRTs ohne
      // Browser-Refresh in den Songdetails sichtbar.
      if (!normalized || normalized.status === 'running' || (!normalized.srt_text && !normalized.exists && !normalized.srt_url && !normalized.srt_path)) {
        window.setTimeout(() => { void reloadSrtState(assetId); }, 800);
        window.setTimeout(() => { void reloadSrtState(assetId); }, 3000);
      }
    }

    window.addEventListener('srt:updated', handleExternalSrtUpdated);
    return () => {
      cancelled = true;
      window.removeEventListener('srt:updated', handleExternalSrtUpdated);
    };
  }, []);

  useEffect(() => {
    if (!activeProject?.assets?.length) return;
    const missing = activeProject.assets
      .filter((asset) => asset?.id && !srtByAsset[asset.id] && !srtFetchInFlightRef.current[String(asset.id)])
      .map((asset) => asset.id);
    if (!missing.length) return;
    let cancelled = false;
    Promise.all(missing.map((id) => fetchSrtStateOnce(id))).then((rows) => {
      if (cancelled) return;
      setSrtByAsset((current) => {
        const next = { ...current };
        rows.forEach(([id, data]) => { next[id] = data; });
        return next;
      });
    });
    return () => { cancelled = true; };
  }, [activeProject?.id, activeProject?.assets, srtByAsset]);


  function visiblePlayableQueue() {
    const rows = filteredProjects.flatMap((project) => (project.playable.length ? project.playable : project.assets.filter(isPlayable)).map((asset) => withVariantPlaybackMeta(asset, project)));
    const seen = new Set();
    const unique = [];
    for (const item of rows) {
      if (!item?.id || seen.has(String(item.id))) continue;
      seen.add(String(item.id));
      unique.push(item);
    }
    return unique;
  }

  function visibleGalleryPlayableQueue() {
    const rows = filteredGalleryAssets.map((item) => withVariantPlaybackMeta(item.asset, item.project)).filter(isPlayable);
    return rows.length ? rows : visiblePlayableQueue();
  }

  function isCurrentAsset(asset) {
    return Boolean(asset?.id && playbackState?.currentAssetId && String(asset.id) === String(playbackState.currentAssetId));
  }

  function currentAssetForProject(project) {
    if (!project?.assets?.length || !playbackState?.currentAssetId) return null;
    return project.assets.find((asset) => String(asset.id) === String(playbackState.currentAssetId)) || null;
  }

  function isCurrentProject(project) {
    return Boolean(currentAssetForProject(project));
  }

  function isPlayingAsset(asset) {
    return isCurrentAsset(asset) && Boolean(playbackState?.isPlaying);
  }

  function isPlayingProject(project) {
    return isCurrentProject(project) && Boolean(playbackState?.isPlaying);
  }

  function playProject(project) {
    if (isCurrentProject(project)) {
      onToggleCurrentPlayback?.();
      return;
    }
    const list = visiblePlayableQueue();
    const firstId = (project.playable[0] || project.assets.find(isPlayable))?.id;
    const startIndex = Math.max(0, list.findIndex((item) => item.id === firstId));
    const fallbackQueue = project.assets.filter(isPlayable).map((asset) => withVariantPlaybackMeta(asset, project));
    onPlay(list.length ? list : fallbackQueue, startIndex);
  }

  function playAsset(asset, queue = null, index = 0, project = activeProject) {
    if (isCurrentAsset(asset)) {
      onToggleCurrentPlayback?.();
      return;
    }
    const playbackAsset = project ? withVariantPlaybackMeta(asset, project) : asset;
  const explicitQueue = Array.isArray(queue) ? queue.filter(isPlayable) : [];
  const libraryQueue = visiblePlayableQueue();
  const preferredQueue = explicitQueue.length ? explicitQueue : libraryQueue;
    const safeQueue = (preferredQueue.length ? preferredQueue : [playbackAsset]).filter(isPlayable);
    const safeIndex = Math.max(0, safeQueue.findIndex((item) => String(item.id) === String(asset.id)));
    onPlay(safeQueue, safeIndex >= 0 ? safeIndex : Math.max(0, index));
  }

  async function addToPlaylist(asset, playlistId) {
    if (!playlistId) return;
    await api.library.addPlaylistItem(playlistId, { audio_asset_id: Number(asset.id) });
    notify(t('library.messages.trackAddedToPlaylist', 'Track wurde zur Playlist hinzugefügt.'), 'success');
    setPlaylistAsset(null);
    await onReload();
  }

  async function addSelectedToPlaylist(playlistId) {
    if (!playlistId) return;
    const rows = selectedAssets.filter((asset) => asset?.id);
    if (!rows.length) return notify(t('library.messages.noSelectedTracks', 'Keine ausgewählten Tracks gefunden.'), 'error');
    try {
      await Promise.all(rows.map((asset) => api.library.addPlaylistItem(playlistId, { audio_asset_id: Number(asset.id) })));
      notify(t('library.messages.tracksAddedToPlaylist', '{{count}} Track(s) wurden zur Playlist hinzugefügt.', { count: rows.length }), 'success');
      setSelectedPlaylistOpen(false);
      await onReload?.();
    } catch (err) {
      notify(err?.message || t('library.messages.selectionPlaylistFailed', 'Auswahl konnte nicht zur Playlist hinzugefügt werden.'), 'error');
    }
  }

  async function renameAsset(asset) {
    const title = prompt(t('library.messages.newTitlePrompt', 'Neuer Titel'), pickTitle(asset));
    if (!title?.trim()) return;
    await api.library.updateTitle('audio', asset.id, title.trim());
    notify(t('library.messages.titleSaved', 'Titel wurde gespeichert.'), 'success');
    await onReload();
  }

  function stopPlaybackForDeletedAssets(assetIds = []) {
    const ids = new Set(assetIds.map((id) => String(id)));
    if (!ids.size) return;
    if (ids.has(String(playbackState?.currentAssetId || ''))) {
      window.dispatchEvent(new CustomEvent('player:command', { detail: { action: 'stop' } }));
    }
  }

  function hideDeletedAssetsLocally(assetIds = []) {
    const ids = assetIds.filter((id) => id !== undefined && id !== null).map((id) => String(id));
    if (!ids.length) return;
    setLocallyDeletedAssetIds((current) => {
      const next = new Set(current);
      ids.forEach((id) => next.add(String(id)));
      return next;
    });
    setSelectedIds((current) => {
      if (!current.size) return current;
      const next = new Set(current);
      ids.forEach((id) => { next.delete(id); next.delete(Number(id)); next.delete(String(id)); });
      return next;
    });
  }

  async function reloadAfterLibraryMutation() {
    await onReload?.({ forceContentRefresh: true });
  }

  async function deleteAsset(asset) {
    if (!asset?.id) return;
    if (!confirm(t('library.messages.moveAssetToTrashConfirm', '„{{title}}“ in den Papierkorb verschieben?', { title: pickTitle(asset) }))) return;
    await api.library.deleteContent('audio', asset.id);
    stopPlaybackForDeletedAssets([asset.id]);
    hideDeletedAssetsLocally([asset.id]);
    notify(t('library.messages.audioMovedToTrash', 'Audio wurde in den Papierkorb verschoben.'), 'success');
    onTrashChanged?.();
    setActionAsset(null);
    closeAudioMenu();
    await reloadAfterLibraryMutation();
  }

  function isAssetFavorite(asset) {
    const key = String(asset?.id || '');
    if (key && Object.prototype.hasOwnProperty.call(favoriteOverrides, key)) return Boolean(favoriteOverrides[key]);
    return Boolean(asset?.is_favorite);
  }

  async function toggleAssetFavorite(asset, desired = null) {
    if (!asset?.id) return;
    const nextValue = desired === null ? !isAssetFavorite(asset) : Boolean(desired);
    const key = String(asset.id);
    preserveWindowScroll(() => {
      setFavoriteSavingIds((current) => new Set([...current, asset.id]));
      setFavoriteOverrides((current) => ({ ...current, [key]: nextValue }));
    });
    try {
      await api.archive.setFavorite(asset.id, nextValue);
      notify(nextValue ? t('library.messages.favoriteAdded', 'Song wurde zu den Favoriten hinzugefügt.') : t('library.messages.favoriteRemoved', 'Song wurde aus den Favoriten entfernt.'), 'success');
      await preserveWindowScrollAsync(() => onReload?.());
    } catch (err) {
      preserveWindowScroll(() => setFavoriteOverrides((current) => ({ ...current, [key]: Boolean(asset.is_favorite) })));
      notify(err?.message || t('library.messages.favoriteSaveFailed', 'Favorit konnte nicht gespeichert werden.'), 'error');
    } finally {
      preserveWindowScroll(() => {
        setFavoriteSavingIds((current) => {
          const next = new Set(current);
          next.delete(asset.id);
          return next;
        });
      });
    }
  }

  function canConvertAssetToWav(asset) {
    if (!asset?.id) return false;
    if (isAudioLocal(asset)) return true;
    const metadata = asset?.metadata_json && typeof asset.metadata_json === 'object' ? asset.metadata_json : {};
    const candidate = metadata.candidate && typeof metadata.candidate === 'object' ? metadata.candidate : {};
    const requestPayload = metadata.request_payload && typeof metadata.request_payload === 'object' ? metadata.request_payload : {};
    const urls = [asset.source_url, asset.public_url, candidate.audioUrl, candidate.sourceAudioUrl, candidate.streamAudioUrl, requestPayload.audioUrl, metadata.audio_url, metadata.sourceAudioUrl];
    return urls.some((value) => /^https?:\/\//i.test(String(value || '')));
  }

  function readAssetStems(asset) {
    const metadata = asset?.metadata_json && typeof asset.metadata_json === 'object' ? asset.metadata_json : {};
    const stems = metadata.stems && typeof metadata.stems === 'object' ? metadata.stems : {};
    const files = stems.files && typeof stems.files === 'object' ? stems.files : {};
    const available = Boolean(files.vocals || files.instrumental);
    return { ...stems, files, available };
  }

  function readAssetWavConversion(asset) {
    const metadata = asset?.metadata_json && typeof asset.metadata_json === 'object' ? asset.metadata_json : {};
    const wav = metadata.wav_conversion && typeof metadata.wav_conversion === 'object' ? metadata.wav_conversion : {};
    const available = Boolean(wav.public_url || wav.local_path || wav.filename || String(asset?.content_type || '').toLowerCase().includes('wav') || String(asset?.filename || '').toLowerCase().endsWith('.wav'));
    return { ...wav, available };
  }

  function openWorkflowWizard(asset) {
    if (!asset?.id) return;
    const metadata = asset?.metadata_json && typeof asset.metadata_json === 'object' ? asset.metadata_json : {};
    const hasTimestamped = Boolean(metadata.timestamped_lyrics || metadata.timestampedLyrics);
    const hasSrt = Boolean(srtByAsset[asset.id]?.exists && srtByAsset[asset.id]?.srt_text);
    const stems = readAssetStems(asset);
    setWorkflowCaptureState({
      ...defaultWizardCaptureState,
      timestampedLyrics: Boolean(asset.audio_id && !hasTimestamped),
      srt: !hasSrt,
      stems: Boolean(isAudioLocal(asset) && !stems.available),
      waveform: !asset.waveform_json,
    });
    setBundleContentState({
      ...defaultBundleContentState,
      audio: Boolean(asset.local_path || asset.public_url),
      wav: readAssetWavConversion(asset).available,
      cover: Boolean(isCoverCached(asset) || asset.image_url),
      srt: hasSrt,
      timestamped_lyrics: hasTimestamped,
      stems: stems.available,
      lyrics: Boolean(pickPrompt(asset) || pickLyrics(asset)),
      prompt: Boolean(pickPrompt(asset)),
      style: Boolean(pickStyle(asset)),
      metadata: true,
      waveform: Boolean(asset.waveform_json),
      structure: Boolean(asset.structure_segments_json),
    });
    setWorkflowWizardAsset(asset);
  }

  function selectedBundleContentKeys() {
    return bundleContentOptions.filter((item) => bundleContentState[item.key]).map((item) => item.key);
  }

  function toggleWizardCapture(key) {
    setWorkflowCaptureState((current) => ({ ...current, [key]: !current[key] }));
  }

  function toggleBundleContent(key) {
    setBundleContentState((current) => ({ ...current, [key]: !current[key] }));
  }

  async function runWorkflowWizard(asset) {
    if (!asset?.id) return;
    const selected = Object.entries(workflowCaptureState).filter(([, enabled]) => enabled).map(([key]) => key);
    if (!selected.length) return notify(t('library.messages.noWorkflowCaptureSelected', 'Keine Erfassungsfunktion im Wizard aktiviert.'), 'error');
    setWorkflowWizardBusy(true);
    const results = [];
    try {
      if (workflowCaptureState.timestampedLyrics) {
        if (!asset.audio_id) {
          results.push(t('library.workflow.timestampedSkippedNoAudioId', 'Timestamped Lyrics übersprungen: keine Audio-ID vorhanden.'));
        } else {
          await api.archive.timestampedLyrics(asset.id);
          results.push(t('library.workflow.timestampedSaved', 'Timestamped Lyrics gespeichert'));
        }
      }
      if (workflowCaptureState.srt) {
        const srt = await api.archive.generateSrt(asset.id, { force: true });
        if (srt?.queued || srt?.task_local_id) {
          results.push(t('library.workflow.srtStarted', 'SRT gestartet (#{{task}})', { task: srt.task_local_id || '—' }));
        } else {
          setSrtByAsset((current) => ({ ...current, [asset.id]: srt }));
          notifySrtUpdated(asset.id, srt);
          results.push(t('library.workflow.srtCreated', 'SRT erzeugt'));
        }
      }
      if (workflowCaptureState.stems) {
        await api.archive.generateStems(asset.id);
        results.push(t('library.workflow.stemsCreated', 'Stems erzeugt'));
      }
      if (workflowCaptureState.waveform) {
        await api.archive.rebuildWaveform(asset.id);
        results.push(t('library.workflow.waveformRebuilt', 'Waveform neu berechnet'));
      }
      notify(t('library.messages.workflowDone', 'Wizard abgeschlossen: {{result}}', { result: results.join(' · ') || t('library.messages.noChange', 'keine Änderung') }), 'success');
      await onReload?.();
      setWorkflowWizardAsset((current) => current?.id === asset.id ? { ...current } : current);
    } catch (err) {
      notify(err?.message || t('library.messages.workflowFailed', 'Wizard-Ausführung fehlgeschlagen.'), 'error');
      await onReload?.();
    } finally {
      setWorkflowWizardBusy(false);
    }
  }

  async function generateAssetStems(asset) {
    if (!asset?.id) return;
    if (!confirm(t('library.messages.generateStemsConfirm', 'Stem-Dateien für „{{title}}“ erzeugen?\n\nDies kann je nach Songlänge und Hardware mehrere Minuten dauern.', { title: pickTitle(asset) }))) return;
    setStemLoadingIds((current) => new Set([...current, asset.id]));
    try {
      const result = await api.archive.generateStems(asset.id);
      notify(result?.exists ? t('library.messages.stemsCreated', 'Stem-Dateien wurden erzeugt.') : t('library.messages.stemsDone', 'Stem-Erzeugung wurde abgeschlossen.'), 'success');
      await onReload?.();
    } catch (err) {
      notify(err?.message || t('library.messages.stemsFailed', 'Stem-Erzeugung fehlgeschlagen.'), 'error');
    } finally {
      setStemLoadingIds((current) => {
        const next = new Set(current);
        next.delete(asset.id);
        return next;
      });
    }
  }

  function projectBulkAssets(project) {
    return (project?.assets || []).filter((asset) => asset?.id);
  }

  async function generateProjectSrt(project) {
    const rows = projectBulkAssets(project);
    if (!rows.length) return notify(t('library.messages.noProjectSrtRows', 'Keine Varianten für SRT-Erzeugung gefunden.'), 'error');
    if (!confirm(t('library.messages.projectSrtConfirm', 'SRT für alle {{count}} Varianten von „{{title}}“ erzeugen?\n\nDer Sammellauf wird im Hintergrund gestartet und ist im Status-Frontend als aktiver Task sichtbar.', { count: rows.length, title: project.title }))) return;
    const ids = rows.map((asset) => asset.id);
    setBulkActionBusy('srt');
    setSrtLoadingIds((current) => new Set([...current, ...ids]));
    try {
      const result = await api.archive.bulkGenerateSrt(ids, { force: true });
      notify(t('library.messages.projectSrtStarted', 'SRT-Sammellauf gestartet: Task #{{task}} · {{count}} Varianten.', { task: result?.task_local_id || '—', count: rows.length }), 'success');
      await onReload?.();
      window.setTimeout(() => onReload?.(), 1200);
    } catch (err) {
      notify(err?.message || t('library.messages.bulkSrtFailed', 'SRT-Sammellauf konnte nicht gestartet werden.'), 'error');
    } finally {
      setBulkActionBusy('');
      setSrtLoadingIds((current) => {
        const next = new Set(current);
        ids.forEach((id) => next.delete(id));
        return next;
      });
    }
  }

  async function generateProjectStems(project) {
    const allRows = projectBulkAssets(project);
    const rows = allRows.filter(isAudioLocal);
    const skipped = allRows.length - rows.length;
    if (!rows.length) return notify(t('library.messages.noProjectLocalStems', 'Keine lokal gespeicherten Audios für Stem-Erzeugung gefunden.'), 'error');
    if (!confirm(t('library.messages.projectStemsConfirm', 'Stems für {{count}} lokale Varianten von „{{title}}“ erzeugen?{{skipped}}\n\nDer Sammellauf wird im Hintergrund gestartet und ist im Status-Frontend als aktiver Task sichtbar.', { count: rows.length, title: project.title, skipped: skipped ? t('library.messages.projectStemsSkipped', '\n\n{{count}} nicht lokale Varianten werden übersprungen.', { count: skipped }) : '' }))) return;
    const ids = rows.map((asset) => asset.id);
    setBulkActionBusy('stems');
    setStemLoadingIds((current) => new Set([...current, ...ids]));
    try {
      const result = await api.archive.bulkGenerateStems(ids);
      notify(t('library.messages.projectStemsStarted', 'Stem-Sammellauf gestartet: Task #{{task}} · {{count}} Varianten{{skipped}}.', { task: result?.task_local_id || '—', count: rows.length, skipped: skipped ? t('library.messages.bulkSkippedSuffix', ' · {{count}} übersprungen', { count: skipped }) : '' }), 'success');
      await onReload?.();
      window.setTimeout(() => onReload?.(), 1200);
    } catch (err) {
      notify(err?.message || t('library.messages.bulkStemsFailed', 'Stem-Sammellauf konnte nicht gestartet werden.'), 'error');
    } finally {
      setBulkActionBusy('');
      setStemLoadingIds((current) => {
        const next = new Set(current);
        ids.forEach((id) => next.delete(id));
        return next;
      });
    }
  }

  async function convertAssetToWav(asset, { force = false, download = false } = {}) {
    if (!asset?.id) return;
    const wav = readAssetWavConversion(asset);
    const shouldForce = Boolean(force || (wav.available && confirm(t('library.messages.wavExistsConfirm', 'Für „{{title}}“ existiert bereits eine WAV-Datei. Neu erzeugen?', { title: pickTitle(asset) }))));
    if (!wav.available && !confirm(t('library.messages.wavConvertConfirm', '„{{title}}“ lokal nach WAV konvertieren?\n\nDie Originaldatei bleibt unverändert. Die WAV-Datei wird als zusätzlicher Inhalt gespeichert.', { title: pickTitle(asset) }))) return;
    setWavLoadingIds((current) => new Set([...current, asset.id]));
    try {
      const result = await api.archive.convertToWav(asset.id, { force: shouldForce });
      notify(result?.already_wav ? t('library.messages.alreadyWav', 'Audio liegt bereits als WAV vor.') : result?.created ? t('library.messages.wavCreated', 'WAV-Datei wurde erzeugt.') : t('library.messages.wavExists', 'WAV-Datei ist bereits vorhanden.'), 'success');
      await onReload?.();
      if (download && result?.download_url) {
        const link = document.createElement('a');
        link.href = result.download_url;
        link.download = result.filename || `${safeFilename(pickTitle(asset), `audio_${asset.id}`)}.wav`;
        document.body.appendChild(link);
        link.click();
        link.remove();
      }
    } catch (err) {
      notify(err?.message || t('library.messages.wavFailed', 'WAV-Konvertierung fehlgeschlagen.'), 'error');
    } finally {
      setWavLoadingIds((current) => {
        const next = new Set(current);
        next.delete(asset.id);
        return next;
      });
    }
  }

  function assetContentItems(asset) {
    const srtState = srtByAsset[asset.id] || {};
    const metadata = asset?.metadata_json && typeof asset.metadata_json === 'object' ? asset.metadata_json : {};
    return [
      {
        kind: 'srt',
        label: 'SRT',
        detail: t('library.content.srtDetail', 'Untertiteldatei und SRT-Datensatz'),
        available: Boolean(srtState.exists && srtState.srt_text),
      },
      {
        kind: 'timestamped_lyrics',
        label: 'Timestamped Lyrics',
        detail: t('library.content.timestampedDetail', 'synchronisierte Lyrics aus Metadaten'),
        available: Boolean(metadata.timestamped_lyrics || metadata.timestampedLyrics),
      },
      {
        kind: 'cover',
        label: 'Cover',
        detail: t('library.content.coverDetail', 'lokaler Cover-Cache'),
        available: Boolean(isCoverCached(asset) || asset.image_url),
      },
      {
        kind: 'audio',
        label: t('library.content.localAudio', 'Lokale Audiodatei'),
        detail: t('library.content.localAudioDetail', 'nur lokale Datei/Cache, nicht der Library-Eintrag'),
        available: Boolean(asset.local_path || asset.public_url),
      },
      {
        kind: 'wav',
        label: t('library.content.wavFile', 'WAV-Datei'),
        detail: t('library.content.wavDetail', 'lokal konvertierte WAV-Datei'),
        available: readAssetWavConversion(asset).available,
      },
      {
        kind: 'lyrics',
        label: 'Songtext / Prompt',
        detail: t('library.content.lyricsDetail', 'Lyrics/Prompt aus Datenbank-Metadaten'),
        available: Boolean(pickPrompt(asset) || pickLyrics(asset)),
        danger: true,
      },
      {
        kind: 'stems',
        label: t('library.content.stemFiles', 'Stem-Dateien'),
        detail: t('library.content.stemDetail', 'Vocals und Instrumental aus lokaler Stem-Erzeugung'),
        available: readAssetStems(asset).available,
      },
      {
        kind: 'waveform',
        label: 'Waveform',
        detail: t('library.content.waveformDetail', 'berechnete Wellenformdaten'),
        available: Boolean(asset.waveform_json),
      },
      {
        kind: 'structure',
        label: t('library.content.songStructure', 'Songstruktur'),
        detail: t('library.content.structureDetail', 'erkannte Struktursegmente'),
        available: Boolean(asset.structure_segments_json),
      },
    ].filter((item) => item.available);
  }

  async function deleteAssetSingleContent(asset, item) {
    const title = pickTitle(asset);
    const extraWarning = item.kind === 'lyrics'
      ? t('library.messages.deleteLyricsWarning', '\n\nAchtung: Dadurch werden Songtext/Prompt aus den gespeicherten Metadaten dieses Assets entfernt. Die Audiodatei bleibt erhalten.')
      : item.kind === 'audio'
        ? t('library.messages.deleteAudioWarning', '\n\nDie Library-Variante bleibt erhalten, aber die lokale Audiodatei wird entfernt. Remote-Quelle bleibt, falls vorhanden.')
        : '';
    if (!confirm(t('library.messages.deleteSingleContentConfirm', '{{label}} von „{{title}}“ wirklich löschen?\n\n{{detail}}.{{warning}}', { label: item.label, title, detail: item.detail, warning: extraWarning }))) return;
    try {
      await api.archive.deleteAssetContent(asset.id, item.kind);
      if (item.kind === 'srt') {
        setSrtByAsset((current) => ({ ...current, [asset.id]: { exists: false, status: 'missing' } }));
        setSrtDraftByAsset((current) => ({ ...current, [asset.id]: [] }));
        setSrtEditorOpen(asset.id, false);
      }
      notify(t('library.messages.singleContentDeleted', '{{label}} wurde gelöscht.', { label: item.label }), 'success');
      await onReload?.();
    } catch (err) {
      notify(err?.message || t('library.messages.singleContentDeleteFailed', '{{label}} konnte nicht gelöscht werden.', { label: item.label }), 'error');
    }
  }

  function readStoredTimestampedLyrics(asset) {
    const metadata = asset?.metadata_json && typeof asset.metadata_json === 'object' ? asset.metadata_json : {};
    return metadata.timestamped_lyrics || null;
  }

  function timestampedLyricsText(asset) {
    const data = readStoredTimestampedLyrics(asset);
    if (!data) return '';
    return typeof data === 'string' ? data : JSON.stringify(data, null, 2);
  }
  function voiceInfoForAsset(asset) {
    const metadata = asset?.metadata_json && typeof asset.metadata_json === 'object' ? asset.metadata_json : {};
    const request = metadata.request_payload && typeof metadata.request_payload === 'object' ? metadata.request_payload : {};
    const candidate = metadata.candidate && typeof metadata.candidate === 'object' ? metadata.candidate : {};
    const rawVoiceId = asset?.voice_id || request.voice_id || request.voiceId || request.persona_id || request.personaId || candidate.voice_id || candidate.voiceId || candidate.persona_id || candidate.personaId || '';
    const voiceId = String(rawVoiceId || '').trim();
    if (!voiceId) return null;

    const match = (voices || []).find((voice) => {
      const knownIds = [voice.voice_id, voice.persona_id, voice.task_id].filter(Boolean).map((value) => String(value));
      return knownIds.includes(voiceId);
    });

    return {
      id: voiceId,
      nickname: match?.nickname || match?.name || '',
      source_type: match?.source_type || (request.persona_id || request.personaId ? 'persona' : 'voice'),
    };
  }

  function voiceLabelForAsset(asset) {
    const info = voiceInfoForAsset(asset);
    if (!info) return '';
    const type = info.source_type === 'persona' ? 'Persona' : 'Voice';
    return info.nickname ? `${info.nickname} · ${type}` : `${type} ${shortId(info.id, 14)}`;
  }


  function generationOptionsLines(asset) {
    const options = getGenerationOptions(asset);
    return [
      [t('library.generationOptions.negativeTags', 'Negative Tags'), options.negative_tags || '—'],
      [t('library.generationOptions.vocalGender', 'Vocal Gender'), formatVocalGender(options.vocal_gender, t)],
      [t('library.generationOptions.styleWeight', 'Style Weight'), options.styleWeight !== '' ? options.styleWeight : '—'],
      [t('library.generationOptions.weirdness', 'Weirdness'), options.weirdnessConstraint !== '' ? options.weirdnessConstraint : '—'],
      [t('library.generationOptions.audioWeight', 'Audio Weight'), options.audioWeight !== '' ? options.audioWeight : '—'],
      [t('library.generationOptions.personaId', 'Persona ID'), options.personaId ? shortId(options.personaId, 22) : '—'],
      [t('library.generationOptions.personaModel', 'Persona Model'), options.personaModel || '—'],
      [t('library.generationOptions.customMode', 'Custom Mode'), formatBoolean(options.customMode, t)],
      [t('library.generationOptions.instrumental', 'Instrumental'), formatBoolean(options.instrumental, t)],
    ];
  }

  function generationOptionsRows(asset) {
    const options = getGenerationOptions(asset);
    const missing = '—';
    return [
      {
        className: 'generation-options-row negative-tags-row',
        items: [{ label: t('library.generationOptions.negativeTags', 'Negative Tags'), value: options.negative_tags || missing, copyValue: options.negative_tags || '' }]
      },
      {
        className: 'generation-options-row main-options-row',
        items: [
          { label: t('library.generationOptions.vocalGender', 'Vocal Gender'), value: formatVocalGender(options.vocal_gender, t), copyValue: options.vocal_gender || '' },
          { label: t('library.generationOptions.styleWeight', 'Style Weight'), value: options.styleWeight !== '' ? options.styleWeight : missing, copyValue: options.styleWeight !== '' ? options.styleWeight : '' },
          { label: t('library.generationOptions.weirdness', 'Weirdness'), value: options.weirdnessConstraint !== '' ? options.weirdnessConstraint : missing, copyValue: options.weirdnessConstraint !== '' ? options.weirdnessConstraint : '' },
          { label: t('library.generationOptions.audioWeight', 'Audio Weight'), value: options.audioWeight !== '' ? options.audioWeight : missing, copyValue: options.audioWeight !== '' ? options.audioWeight : '' },
          { label: t('library.generationOptions.customMode', 'Custom Mode'), value: formatBoolean(options.customMode, t), copyValue: options.customMode === null || options.customMode === undefined || options.customMode === '' ? '' : formatBoolean(options.customMode, t) },
          { label: t('library.generationOptions.instrumental', 'Instrumental'), value: formatBoolean(options.instrumental, t), copyValue: options.instrumental === null || options.instrumental === undefined || options.instrumental === '' ? '' : formatBoolean(options.instrumental, t) },
        ]
      },
      {
        className: 'generation-options-row persona-options-row',
        items: [
          { label: t('library.generationOptions.personaId', 'Persona ID'), value: options.personaId ? shortId(options.personaId, 22) : missing, copyValue: options.personaId || '' },
          { label: t('library.generationOptions.personaModel', 'Persona Model'), value: options.personaModel || missing, copyValue: options.personaModel || '' },
        ]
      },
    ];
  }

  function generationOptionsText(asset) {
    return generationOptionsLines(asset).map(([label, value]) => `${label}: ${value}`).join('\n');
  }

  function GenerationOptionsCard({ asset }) {
    if (!hasGenerationOptions(asset)) return null;
    return (
      <div className="meta-card wide generation-options-card">
        <div className="row between">
          <h4>{t('library.generationOptions.title', 'Verwendete Optionen')}</h4>
          <button type="button" onClick={async () => { await copyToClipboard(generationOptionsText(asset)); notify(t('library.messages.optionsCopied', 'Optionen kopiert.'), 'success'); }}><Copy size={14} /></button>
        </div>
        <div className="generation-options-rows">
          {generationOptionsRows(asset).map((row) => (
            <div className={row.className} key={row.className}>
              {row.items.map(({ label, value, copyValue }) => (
                <div className="generation-option-item" key={label}>
                  <div className="generation-option-item-heading">
                    <span>{label}</span>
                    <button
                      type="button"
                      className="generation-option-copy"
                      title={t('library.messages.copyLabel', `${label} kopieren`, { label })}
                      aria-label={t('library.messages.copyLabel', `${label} kopieren`, { label })}
                      disabled={!String(copyValue || '').trim()}
                      onClick={async () => {
                        await copyToClipboard(String(copyValue || value || ''));
                        notify(t('library.messages.labelCopied', '{{label}} kopiert.', { label }), 'success');
                      }}
                    >
                      <Copy size={13} />
                    </button>
                  </div>
                  <strong>{value}</strong>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    );
  }

  function setAudioAnalysisLoading(assetId, loading) {
    setAudioAnalysisLoadingIds((current) => {
      const next = new Set(current);
      if (loading) next.add(assetId); else next.delete(assetId);
      return next;
    });
  }

  async function refreshAudioAiAnalysis(asset) {
    if (!asset?.id) return null;
    const result = await api.archive.getAudioAiAnalysis(asset.id);
    return result?.analysis || null;
  }

  async function generateAudioAiAnalysis(asset, force = false) {
    if (!asset?.id) return;
    setAudioAnalysisLoading(asset.id, true);
    try {
      const result = await api.archive.generateAudioAiAnalysis(asset.id, { profile: 'standard', include_ai_report: true, force });
      if (result?.queued) {
        notify(t('library.messages.audioAnalysisStarted', 'Audioanalyse wurde gestartet. Der Fortschritt ist auf der Statusseite sichtbar.'), 'success');
      } else if (result?.analysis) {
        setAudioAnalysisModal({ asset, analysis: result.analysis });
        notify(t('library.messages.audioAnalysisExists', 'Audioanalyse ist bereits vorhanden.'), 'success');
      }
      await preserveWindowScrollAsync(() => onReload?.());
    } catch (err) {
      notify(err?.message || t('library.messages.audioAnalysisStartFailed', 'Audioanalyse konnte nicht gestartet werden.'), 'error');
    } finally {
      setAudioAnalysisLoading(asset.id, false);
    }
  }

  async function generateLibraryAiTags(asset, force = false) {
    if (!asset?.id) return;
    try {
      const result = await api.archive.generateAiTags(asset.id, { force });
      if (result?.queued) {
        notify(t('library.messages.aiTaggingStarted', 'KI-Tagging wurde gestartet. Der Fortschritt ist auf der Statusseite sichtbar.'), 'success');
      } else if (result?.ai_tags) {
        notify(t('library.messages.aiTagsExist', 'KI-Tags sind bereits vorhanden.'), 'success');
      }
      await preserveWindowScrollAsync(() => onReload?.());
    } catch (err) {
      notify(err?.message || t('library.messages.aiTagsStartFailed', 'KI-Tags konnten nicht gestartet werden.'), 'error');
    }
  }

  async function openAudioAiAnalysisReport(asset) {
    if (!asset?.id) return;
    setAudioAnalysisLoading(asset.id, true);
    try {
      const analysis = await refreshAudioAiAnalysis(asset);
      if (!analysis) {
        notify(t('library.messages.noAudioAnalysisReport', 'Für diese Variante ist noch kein Audioanalyse-Report vorhanden.'), 'error');
        return;
      }
      setAudioAnalysisModal({ asset, analysis });
    } catch (err) {
      notify(err?.message || t('library.messages.audioAnalysisReportLoadFailed', 'Audioanalyse-Report konnte nicht geladen werden.'), 'error');
    } finally {
      setAudioAnalysisLoading(asset.id, false);
    }
  }

  async function copyAudioAiAnalysisBlock(block) {
    await copyToClipboard(`${block.title}\n\n${block.text}`.trim());
    notify(t('library.messages.reportBlockCopied', 'Report-Block kopiert.'), 'success');
  }

  async function copyAudioAiAnalysisReport(analysis) {
    const text = audioAiAnalysisBlocks(analysis, t).map((block) => `${block.title}\n${block.text}`).join('\n\n');
    await copyToClipboard(text);
    notify(t('library.messages.audioAnalysisReportCopied', 'Audioanalyse-Report kopiert.'), 'success');
  }

  function downloadAudioAiAnalysisReport(analysis, asset) {
    const text = JSON.stringify(analysis || {}, null, 2);
    downloadTextFile(`${safeFilename(pickTitle(asset) || 'audioanalyse')}-audio-ai-analysis.json`, text, 'application/json;charset=utf-8');
    notify(t('library.messages.audioAnalysisJsonDownloaded', 'Audioanalyse-JSON wurde heruntergeladen.'), 'success');
  }

  function AudioAiAnalysisCard({ asset }) {
    const analysis = readAudioAiAnalysis(asset);
    const loading = audioAnalysisLoadingIds.has(asset.id);
    const statusLabel = loading ? t('library.status.running', 'läuft') : analysis ? t('library.status.done', 'fertig') : t('library.status.notCreated', 'nicht erstellt');
    return (
      <div className="meta-card wide audio-ai-analysis-card">
        <div className="row between align-start">
          <div>
            <h4>{t('library.audioAnalysis.title', 'Lokale Audioanalyse')}</h4>
            <p className="muted">{t('library.audioAnalysis.text', 'Tempo, Beatgrid, Lautheit und ein kompakter Report werden lokal gespeichert.')}</p>
          </div>
          <span className={`status ${analysis ? 'cached' : loading ? 'processing' : ''}`}>{statusLabel}</span>
        </div>
        {analysis?.generated_at && <p className="muted">{t('library.createdAt', 'Erstellt')}: {formatDate(analysis.generated_at)}{analysis?.summary?.bpm ? ` · ${analysis.summary.bpm} BPM` : ''}{analysis?.task_local_id ? ` · Status-Task #${analysis.task_local_id}` : ''}</p>}
        <div className="button-row wrap">
          <button className="primary" type="button" onClick={() => generateAudioAiAnalysis(asset, Boolean(analysis))} disabled={loading || !isAudioLocal(asset)}>{loading ? t('library.actions.analysisRunning', 'Analyse läuft…') : analysis ? t('library.actions.regenerateAnalysis', 'Analyse neu erstellen') : t('library.actions.startAnalysis', 'Analyse starten')}</button>
          <button type="button" onClick={() => openAudioAiAnalysisReport(asset)} disabled={loading || !analysis}><FileText size={15} /> {t('library.actions.openReport', 'Report öffnen')}</button>
          {analysis?.exports?.markdown && <a className="button" href={api.archive.audioAiAnalysisExportUrl(asset.id, 'markdown')}><Download size={15} /> Markdown</a>}
          {analysis && <a className="button" href={api.archive.audioAiAnalysisExportUrl(asset.id, 'html')}><Download size={15} /> HTML</a>}
          {analysis && <a className="button" href={api.archive.audioAiAnalysisExportUrl(asset.id, 'pdf')}><Download size={15} /> PDF</a>}
          {analysis?.exports?.beatgrid_csv && <a className="button" href={api.archive.audioAiAnalysisExportUrl(asset.id, 'beatgrid_csv')}><Download size={15} /> Beatgrid CSV</a>}
        </div>
        {!isAudioLocal(asset) && <p className="warning-text">{t('library.audioAnalysis.needsLocalAudio', 'Die Analyse benötigt eine lokal gespeicherte Audiodatei.')}</p>}
      </div>
    );
  }

  function LibraryAiTagsCard({ asset }) {
    const aiTags = readLibraryAiTags(asset);
    const tags = libraryAiTagList(asset);
    return (
      <div className="meta-card wide library-ai-tags-card">
        <div className="row between align-start">
          <div>
            <h4>{t('library.aiTags.title', 'KI-Library-Tags')}</h4>
            <p className="muted">{t('library.aiTags.text', 'Kompakte Such-Tags fuer die zentrale Header-Suche.')}</p>
          </div>
          <span className={`status ${tags.length ? 'cached' : ''}`}>{tags.length ? t('library.aiTags.count', '{{count}} Tags', { count: tags.length }) : t('library.status.notCreated', 'nicht erstellt')}</span>
        </div>
        {tags.length > 0 && <div className="ai-tag-chip-row">{tags.map((tag) => <span className="ai-tag-chip" key={tag}>{tag}</span>)}</div>}
        {aiTags?.generated_at && <p className="muted">{t('library.createdAt', 'Erstellt')}: {formatDate(aiTags.generated_at)}{aiTags?.confidence ? ` · ${t('library.confidence', 'Sicherheit')} ${Math.round(Number(aiTags.confidence) * 100)}%` : ''}</p>}
        <div className="button-row wrap">
          <button type="button" className="primary" onClick={() => generateLibraryAiTags(asset, Boolean(aiTags))}><Tag size={15} /> {aiTags ? t('library.aiTags.regenerate', 'Tags neu erzeugen') : t('library.aiTags.generate', 'Tags erzeugen')}</button>
          <button type="button" disabled={!tags.length} onClick={async () => { await copyToClipboard(tags.join(', ')); notify(t('library.messages.aiTagsCopied', 'KI-Tags kopiert.'), 'success'); }}><Copy size={14} /> {t('library.aiTags.copy', 'Tags kopieren')}</button>
        </div>
      </div>
    );
  }


  async function fetchTimestampedLyrics(asset) {
    if (!asset?.audio_id) {
      notify(t('library.messages.timestampedMissingAudioId', 'Für diese Variante fehlt die Audio-ID. Timestamped Lyrics können nicht abgerufen werden.'), 'error');
      return;
    }
    setTimestampLoading(true);
    try {
      const result = await api.archive.timestampedLyrics(asset.id);
      const updatedAsset = {
        ...asset,
        metadata_json: {
          ...(asset.metadata_json || {}),
          timestamped_lyrics: result?.timestamped_lyrics,
          timestamped_lyrics_fetched_at: result?.timestamped_lyrics_fetched_at
        }
      };
      setTimestampAsset(updatedAsset);
      notify(t('library.messages.timestampedFetched', 'Timestamped Lyrics wurden abgerufen und gespeichert.'), 'success');
      await onReload?.();
    } catch (err) {
      notify(err?.message || t('library.messages.timestampedFetchFailed', 'Timestamped Lyrics konnten nicht abgerufen werden.'), 'error');
    } finally {
      setTimestampLoading(false);
    }
  }

  async function copyTimestampedLyrics(asset) {
    const text = timestampedLyricsText(asset);
    if (!text) return notify(t('library.messages.noTimestampedLyrics', 'Noch keine Timestamped Lyrics vorhanden.'), 'error');
    await copyToClipboard(text);
    notify(t('library.messages.timestampedCopied', 'Timestamped Lyrics kopiert.'), 'success');
  }

  function downloadTimestampedLyrics(asset) {
    const text = timestampedLyricsText(asset);
    if (!text) return notify(t('library.messages.noTimestampedLyrics', 'Noch keine Timestamped Lyrics vorhanden.'), 'error');
    downloadTextFile(`${safeFilename(pickTitle(asset))} - timestamped-lyrics.json`, text, 'application/json;charset=utf-8');
    notify(t('library.messages.timestampedDownloaded', 'Timestamped Lyrics wurden heruntergeladen.'), 'success');
  }

  function setSrtLoading(assetId, loading) {
    setSrtLoadingIds((current) => {
      const next = new Set(current);
      if (loading) next.add(assetId); else next.delete(assetId);
      return next;
    });
  }

  function isManualImportAsset(asset) {
    const metadata = asset?.metadata_json || {};
    const candidate = metadata?.candidate && typeof metadata.candidate === 'object' ? metadata.candidate : {};
    return String(metadata?.source || '').toLowerCase() === 'manual_import'
      || Boolean(metadata?.manual_import)
      || String(asset?.audio_id || '').toLowerCase().startsWith('manual-')
      || String(candidate?.model || '').toLowerCase() === 'manual_import';
  }

  function srtLyricsOverrideForAsset(asset) {
    if (!isManualImportAsset(asset)) return '';
    return String(pickLyrics(asset) || '').trim();
  }

  async function refreshSrt(assetId) {
    const [id, data] = await fetchSrtStateOnce(assetId);
    setSrtByAsset((current) => ({ ...current, [id]: data }));
    return data;
  }

  function notifySrtUpdated(assetId, srt) {
    if (!assetId || typeof window === 'undefined') return;
    window.dispatchEvent(new CustomEvent('srt:updated', {
      detail: {
        audio_asset_id: assetId,
        srt,
      }
    }));
  }

  function taskStatusValue(task) {
    return String(task?.status || task?.response_payload?.status || task?.result_payload?.status || '').toUpperCase();
  }

  function isTaskSuccess(task) {
    const status = taskStatusValue(task);
    const resultStatus = String(task?.result_payload?.status || '').toLowerCase();
    return status === 'SUCCESS' || resultStatus === 'completed' || Boolean(task?.result_payload?.srt_text || task?.response_payload?.result?.exists);
  }

  function isTaskFailure(task) {
    const status = taskStatusValue(task);
    return ['FAILED', 'ERROR', 'CANCELLED', 'CANCELED', 'TIMEOUT'].includes(status);
  }

  function clearSrtTaskWatcher(assetId) {
    const key = String(assetId || '');
    const watcher = srtTaskWatchersRef.current?.[key];
    if (watcher?.timer) window.clearTimeout(watcher.timer);
    if (key) delete srtTaskWatchersRef.current[key];
  }

  function startSrtTaskWatcher(asset, taskId) {
    const assetId = asset?.id;
    if (!assetId || !taskId) return;
    const assetTitle = pickTitle(asset);
    const key = String(assetId);
    clearSrtTaskWatcher(assetId);
    srtTaskWatchersRef.current[key] = { timer: null, attempts: 0, taskId };

    const poll = async () => {
      const watcher = srtTaskWatchersRef.current[key];
      if (!watcher) return;
      watcher.attempts += 1;

      try {
        const task = await api.music.getTask(taskId);
        if (isTaskSuccess(task)) {
          clearSrtTaskWatcher(assetId);
          try {
            const state = await refreshSrt(assetId);
            notifySrtUpdated(assetId, state);
          } catch (refreshError) {
            notify(refreshError?.message || t('library.messages.srtCreatedLoadPending', 'SRT wurde erzeugt, konnte aber noch nicht geladen werden.'), 'warning');
          }
          notify(t('library.messages.srtDone', 'SRT fertig{{title}}.', { title: assetTitle ? `: ${assetTitle}` : '' }), 'success');
          await onReload?.();
          setSrtLoading(assetId, false);
          return;
        }

        if (isTaskFailure(task)) {
          const message = task?.error_message || task?.response_payload?.message || task?.result_payload?.message || 'SRT-Erzeugung fehlgeschlagen.';
          clearSrtTaskWatcher(assetId);
          setSrtByAsset((current) => ({
            ...current,
            [assetId]: { audio_asset_id: assetId, exists: false, status: 'error', error_message: message }
          }));
          notify(message, 'error');
          await onReload?.();
          setSrtLoading(assetId, false);
          return;
        }
      } catch (err) {
        if (watcher.attempts >= 3) {
          notify(err?.message || t('library.messages.srtTaskStatusLoadFailed', 'SRT-Status für Task #{{task}} konnte nicht geladen werden.', { task: taskId }), 'warning');
        }
      }

      if (watcher.attempts >= 120) {
        clearSrtTaskWatcher(assetId);
        setSrtLoading(assetId, false);
        notify(t('library.messages.srtTaskStillRunning', 'SRT-Task #{{task}} läuft weiterhin. Die Statusseite zeigt den aktuellen Stand.', { task: taskId }), 'warning');
        await onReload?.();
        return;
      }

      watcher.timer = window.setTimeout(poll, watcher.attempts < 8 ? 2500 : 5000);
    };

    srtTaskWatchersRef.current[key].timer = window.setTimeout(poll, 1500);
  }

  async function generateSrt(asset) {
    if (!asset?.id) return;
    let keepLoadingForWatcher = false;
    setSrtLoading(asset.id, true);
    try {
      const lyricsOverride = srtLyricsOverrideForAsset(asset);
      const resultPromise = api.archive.generateSrt(asset.id, {
        force: true,
        ...(lyricsOverride ? { lyrics_override: lyricsOverride } : {})
      });
      window.setTimeout(() => onReload?.(), 700);
      const result = await resultPromise;
      if (result?.queued || result?.task_local_id) {
        const taskId = result.task_local_id || result.id || null;
        setSrtByAsset((current) => ({
          ...current,
          [asset.id]: {
            ...(current[asset.id] || {}),
            audio_asset_id: asset.id,
            exists: Boolean(current[asset.id]?.exists),
            status: 'running',
            task_local_id: taskId,
          }
        }));
        notifySrtUpdated(asset.id, { audio_asset_id: asset.id, status: 'running', task_local_id: taskId });
        notify(t('library.messages.srtGenerationStarted', 'SRT-Erzeugung gestartet: Task #{{task}}.', { task: taskId || '—' }), 'info');
        if (taskId) {
          keepLoadingForWatcher = true;
          startSrtTaskWatcher(asset, taskId);
        } else {
          window.setTimeout(async () => {
            try {
              const state = await refreshSrt(asset.id);
              notifySrtUpdated(asset.id, state);
              await onReload?.();
            } catch {
              // Statusseite bleibt die Quelle, wenn kein Task-Handle zur Verfügung steht.
            } finally {
              setSrtLoading(asset.id, false);
            }
          }, 6000);
        }
        window.setTimeout(() => onReload?.(), 1200);
        return;
      }
      setSrtByAsset((current) => ({ ...current, [asset.id]: result }));
      notifySrtUpdated(asset.id, result);
      notify(t('library.messages.srtCreatedSaved', 'SRT wurde erzeugt und gespeichert.'), 'success');
      await onReload?.();
    } catch (err) {
      clearSrtTaskWatcher(asset.id);
      setSrtByAsset((current) => ({ ...current, [asset.id]: { audio_asset_id: asset.id, exists: false, status: 'error', error_message: err?.message || t('library.messages.srtGenerationFailed', 'SRT-Erzeugung fehlgeschlagen.') } }));
      notify(err?.message || t('library.messages.srtGenerationFailed', 'SRT-Erzeugung fehlgeschlagen.'), 'error');
      await onReload?.();
    } finally {
      if (!keepLoadingForWatcher) setSrtLoading(asset.id, false);
    }
  }

  async function copySrt(asset) {
    const state = srtByAsset[asset?.id] || await refreshSrt(asset.id);
    const text = state?.srt_text || '';
    if (!text.trim()) return notify(t('library.messages.noSrtForVariant', 'Für diese Variante ist noch keine SRT vorhanden.'), 'error');
    await copyToClipboard(text);
    notify(t('library.messages.srtCopied', 'SRT wurde kopiert.'), 'success');
  }

  async function downloadSrtText(asset) {
    const state = srtByAsset[asset?.id] || await refreshSrt(asset.id);
    const text = state?.srt_text || '';
    if (!text.trim()) return notify(t('library.messages.noSrtForVariant', 'Für diese Variante ist noch keine SRT vorhanden.'), 'error');
    downloadTextFile(state.srt_filename || `${safeFilename(pickTitle(asset))}.srt`, text, 'application/x-subrip;charset=utf-8');
    notify(t('library.messages.srtDownloaded', 'SRT wurde heruntergeladen.'), 'success');
  }

  async function copyHalfSrt(asset) {
    const state = srtByAsset[asset?.id] || await refreshSrt(asset.id);
    const text = state?.half_srt_text || '';
    if (!text.trim()) return notify(t('library.messages.noHalfSrtForVariant', 'Für diese Variante ist noch keine Half-SRT vorhanden.'), 'error');
    await copyToClipboard(text);
    notify(t('library.messages.halfSrtCopied', 'Half-SRT wurde kopiert.'), 'success');
  }

  async function downloadHalfSrtText(asset) {
    const state = srtByAsset[asset?.id] || await refreshSrt(asset.id);
    const text = state?.half_srt_text || '';
    if (!text.trim()) return notify(t('library.messages.noHalfSrtForVariant', 'Für diese Variante ist noch keine Half-SRT vorhanden.'), 'error');
    downloadTextFile(state.half_srt_filename || `${safeFilename(pickTitle(asset))}.half.srt`, text, 'application/x-subrip;charset=utf-8');
    notify(t('library.messages.halfSrtDownloaded', 'Half-SRT wurde heruntergeladen.'), 'success');
  }

  function setSrtSaving(assetId, saving) {
    setSrtSavingIds((current) => {
      const next = new Set(current);
      if (saving) next.add(assetId); else next.delete(assetId);
      return next;
    });
  }

  function draftSegmentsForAsset(asset) {
    if (!asset?.id) return [];
    return (srtDraftByAsset[asset.id] || srtSegmentsFromState(srtByAsset[asset.id] || {})).map(normalizeSrtSegment);
  }

  function openSrtEditor(asset) {
    if (!asset?.id) return;
    ensureSrtEditorDraft(asset.id);
    setSrtEditorOpen(asset.id, true);
  }

  function updateSrtDraftSegment(assetId, index, patch) {
    setSrtDraftByAsset((current) => {
      const rows = [...(current[assetId] || srtSegmentsFromState(srtByAsset[assetId] || {}))];
      rows[index] = normalizeSrtSegment({ ...(rows[index] || {}), ...(patch || {}) }, index);
      return { ...current, [assetId]: rows.map(normalizeSrtSegment) };
    });
  }

  function addSrtSegment(asset, afterIndex = null, startOverride = null, textOverride = '') {
    if (!asset?.id) return;
    const current = draftSegmentsForAsset(asset);
    const insertAt = afterIndex === null || afterIndex === undefined ? current.length : Math.min(current.length, Math.max(0, Number(afterIndex) + 1));
    const previous = current[Math.max(0, insertAt - 1)] || null;
    const next = current[insertAt] || null;
    const start = Math.max(0, Number(startOverride ?? playbackState?.currentTime ?? previous?.end ?? 0));
    const end = next ? Math.min(Math.max(start + 1, start + 0.25), Number(next.start || start + 2)) : start + 2;
    const row = normalizeSrtSegment({ start, end, text: textOverride || t('library.srt.newSubtitleLine', 'Neue Untertitel-Zeile') }, insertAt);
    const merged = [...current.slice(0, insertAt), row, ...current.slice(insertAt)].map(normalizeSrtSegment);
    setSrtDraftByAsset((map) => ({ ...map, [asset.id]: merged }));
    setSrtEditorOpen(asset.id, true);
  }

  function deleteSrtSegment(assetId, index) {
    setSrtDraftByAsset((current) => {
      const rows = [...(current[assetId] || [])].filter((_, rowIndex) => rowIndex !== index).map(normalizeSrtSegment);
      return { ...current, [assetId]: rows };
    });
  }

  async function saveSrtEditor(asset) {
    if (!asset?.id) return;
    const segments = draftSegmentsForAsset(asset).filter((row) => row.text.trim());
    if (!segments.length) return notify(t('library.messages.noSrtSegmentsToSave', 'Keine SRT-Segmente zum Speichern vorhanden.'), 'error');
    setSrtSaving(asset.id, true);
    try {
      const result = await api.archive.updateSrt(asset.id, { segments });
      setSrtByAsset((current) => ({ ...current, [asset.id]: result }));
      setSrtDraftByAsset((current) => ({ ...current, [asset.id]: srtSegmentsFromState(result) }));
      notifySrtUpdated(asset.id, result);
      notify(t('library.messages.srtSegmentsSaved', 'SRT-Segmente wurden gespeichert.'), 'success');
      await onReload?.();
    } catch (err) {
      notify(err?.message || t('library.messages.srtSegmentsSaveFailed', 'SRT-Segmente konnten nicht gespeichert werden.'), 'error');
    } finally {
      setSrtSaving(asset.id, false);
    }
  }

  function resetSrtEditor(asset) {
    if (!asset?.id) return;
    setSrtDraftByAsset((current) => ({ ...current, [asset.id]: srtSegmentsFromState(srtByAsset[asset.id] || {}) }));
    notify(t('library.messages.srtEditorReset', 'SRT-Editor wurde auf gespeicherte Daten zurückgesetzt.'), 'info');
  }

  function openSrtAssistant(asset) {
    window.dispatchEvent(new CustomEvent('assistant:send', {
      detail: {
        message: `Öffne den SRT-Editor für AudioAsset ${asset.id} und hilf mir beim Korrigieren der Untertitel-Segmente.`,
        actionId: 'srt_focus_editor'
      }
    }));
  }

  function AssetContentManager({ asset }) {
    const items = assetContentItems(asset);
    if (!items.length) return null;
    return (
      <div className="meta-card wide asset-content-manager">
        <div className="row between align-start">
          <div>
            <h4>{t('library.content.title', 'Einzelinhalte')}</h4>
            <p className="muted">{t('library.content.text', 'Nur einzelne Bestandteile dieser Variante löschen. Die Song-Variante selbst bleibt erhalten.')}</p>
          </div>
        </div>
        <div className="button-row wrap asset-content-actions">
          <button className="primary" type="button" onClick={() => openWorkflowWizard(asset)}><FileText size={15} /> {t('library.workflow.audioWizard', 'Audio-Wizard')}</button>
          <button type="button" onClick={() => convertAssetToWav(asset, { download: true })} disabled={wavLoadingIds.has(asset.id) || !canConvertAssetToWav(asset)}><Download size={15} /> {wavLoadingIds.has(asset.id) ? t('library.actions.converting', 'Konvertiere…') : t('library.actions.convertToWav', 'Convert to WAV')}</button>
          {readAssetWavConversion(asset).available && <a className="button" href={api.archive.wavDownloadUrl(asset.id)}><Download size={15} /> {t('library.actions.downloadWav', 'WAV herunterladen')}</a>}
          <a className="button" href={api.archive.assetBundleUrl(asset.id)}><Download size={15} /> {t('library.actions.completeZip', 'Komplettes ZIP')}</a>
          {readAssetStems(asset).available && <a className="button" href={api.archive.stemsDownloadUrl(asset.id)}><Download size={15} /> Stems ZIP</a>}
          {readAssetStems(asset).files?.vocals && <a className="button" href={api.archive.stemDownloadUrl(asset.id, 'vocals')}><Download size={15} /> Vocals</a>}
          {readAssetStems(asset).files?.instrumental && <a className="button" href={api.archive.stemDownloadUrl(asset.id, 'instrumental')}><Download size={15} /> Instrumental</a>}
        </div>
        <div className="asset-content-grid">
          {items.map((item) => (
            <div className="asset-content-item" key={`${asset.id}-${item.kind}`}>
              <div>
                <strong>{item.label}</strong>
                <small>{item.detail}</small>
              </div>
              <button
                className={`icon-danger ${item.danger ? 'danger' : ''}`.trim()}
                type="button"
                title={t('library.messages.deleteLabel', '{{label}} löschen', { label: item.label })}
                onClick={() => deleteAssetSingleContent(asset, item)}
              >
                <Trash2 size={15} />
              </button>
            </div>
          ))}
        </div>
      </div>
    );
  }

  function openStemPreview(asset) {
    if (!asset) return;
    window.dispatchEvent(new CustomEvent('player:command', { detail: { action: 'pause' } }));
    setStemPreviewAsset(asset);
  }

  function StemPreviewModal({ asset }) {
    if (!asset) return null;
    const stems = readAssetStems(asset);
    const files = stems.files || {};
    const playableStems = [
      files.vocals ? { kind: 'vocals', label: 'Vocals', description: t('library.stems.vocalDescription', 'Nur Stimme / Vocal-Stem') } : null,
      files.instrumental ? { kind: 'instrumental', label: 'Instrumental', description: t('library.stems.instrumentalDescription', 'Instrumental ohne Vocals') } : null,
    ].filter(Boolean);
    return (
      <Modal open={Boolean(asset)} title={t('library.stems.playerTitle', 'Stem-Player: {{title}}', { title: pickTitle(asset) })} onClose={() => setStemPreviewAsset(null)} wide cardClassName="stem-preview-modal">
        <div className="stem-preview stack">
          <div className="stem-preview-header">
            <img src={pickCover(asset)} alt="Cover" onError={handleCoverImageError} />
            <div>
              <p className="eyebrow">{t('library.stems.playback', 'Stem-Wiedergabe')}</p>
              <h3>{pickTitle(asset)}</h3>
              <p className="muted">{t('library.stems.previewText', 'Die normale Wiedergabe wurde pausiert. Spiele Vocals oder Instrumental direkt hier im Modal ab.')}</p>
              <p className="muted">{stems.backend ? `Backend: ${stems.backend}` : t('library.stems.files', 'Stem-Dateien')}{stems.bpm ? ` · ${stems.bpm} BPM` : ''}</p>
            </div>
          </div>
          {!playableStems.length && <p className="warning-text">{t('library.stems.noPlayableFiles', 'Für diese Variante sind noch keine abspielbaren Stem-Dateien vorhanden.')}</p>}
          <div className="stem-preview-grid">
            {playableStems.map((stem) => (
              <section className="stem-preview-card" key={stem.kind}>
                <div>
                  <p className="eyebrow">{stem.label}</p>
                  <h4>{stem.description}</h4>
                  <p className="muted">{files[stem.kind]?.filename || files[stem.kind]?.local_path || t('library.stems.file', 'Stem-Datei')}</p>
                </div>
                <audio controls preload="metadata" src={api.archive.stemStreamUrl(asset.id, stem.kind)} />
                <a className="button" href={api.archive.stemDownloadUrl(asset.id, stem.kind)}><Download size={15} /> {t('library.stems.downloadStem', '{{label}} herunterladen', { label: stem.label })}</a>
              </section>
            ))}
          </div>
          {stems.available && <a className="button" href={api.archive.stemsDownloadUrl(asset.id)}><Download size={15} /> {t('library.stems.downloadAllZip', 'Alle Stems als ZIP herunterladen')}</a>}
        </div>
      </Modal>
    );
  }

  function StemCard({ asset }) {
    const stems = readAssetStems(asset);
    const loading = stemLoadingIds.has(asset.id) || String(stems.status || '').toLowerCase() === 'running';
    return (
      <div className="meta-card wide stem-card">
        <div className="row between align-start">
          <div>
            <h4>{t('library.stems.title', 'Stem-Dateien')}</h4>
            <p className="muted">{t('library.stems.text', 'Vocals und Instrumental lokal erzeugen und einzeln oder als ZIP herunterladen.')}</p>
          </div>
          <span className={`status ${stems.available ? 'cached' : String(stems.status || '').toLowerCase() === 'failed' ? 'error' : loading ? 'processing' : ''}`}>{loading ? t('library.status.running', 'läuft') : stems.available ? t('library.status.done', 'fertig') : String(stems.status || '').toLowerCase() === 'failed' ? t('status.stats.error', 'Fehler') : t('library.status.notGenerated', 'nicht erzeugt')}</span>
        </div>
        {stems.task_local_id && <p className="muted">{t('library.statusTaskVisible', 'Status-Task: #{{id}} · im Status-Frontend sichtbar.', { id: stems.task_local_id })}</p>}
        {stems.error_message && <p className="warning-text">{stems.error_message}</p>}
        <div className="button-row wrap">
          <button className="primary" type="button" onClick={() => generateAssetStems(asset)} disabled={loading || !isAudioLocal(asset)}>{loading ? t('library.stems.generating', 'Erzeuge Stems…') : stems.available ? t('library.actions.regenerateStems', 'Stems neu erzeugen') : t('library.bulk.createStems', 'Stems erzeugen')}</button>
          {stems.available && <button type="button" onClick={() => openStemPreview(asset)}><Headphones size={15} /> {t('library.actions.playStems', 'Stems abspielen')}</button>}
          {stems.available && <a className="button" href={api.archive.stemsDownloadUrl(asset.id)}><Download size={15} /> Stems ZIP</a>}
          {stems.files?.vocals && <a className="button" href={api.archive.stemDownloadUrl(asset.id, 'vocals')}><Download size={15} /> Vocals</a>}
          {stems.files?.instrumental && <a className="button" href={api.archive.stemDownloadUrl(asset.id, 'instrumental')}><Download size={15} /> Instrumental</a>}
        </div>
        <p className="muted">{stems.available ? `Backend: ${stems.backend || 'demucs'}${stems.bpm ? ` · ${stems.bpm} BPM` : ''}` : t('library.stems.needsDemucs', 'Benötigt lokal installiertes Demucs im FastAPI-Python-Environment.')}</p>
      </div>
    );
  }

  function AudioAiAnalysisReportModal() {
    const asset = audioAnalysisModal.asset;
    const analysis = audioAnalysisModal.analysis;
    const blocks = audioAiAnalysisBlocks(analysis, t);
    const metrics = audioAiAnalysisMetricCards(analysis, t);
    const summary = analysis?.summary || {};
    const copyright = analysis?.copyright_analysis || {};
    const leadText = audioAiReportLead(blocks, analysis, t);
    return (
      <Modal open={Boolean(asset && analysis)} title={asset ? t('library.audioAnalysis.reportTitleForAsset', 'Audioanalyse-Report: {{title}}', { title: pickTitle(asset) }) : t('library.audioAnalysis.reportTitle', 'Audioanalyse-Report')} onClose={() => setAudioAnalysisModal({ asset: null, analysis: null })} wide cardClassName="audio-ai-report-modal">
        {asset && analysis && <div className="stack audio-ai-report">
          <div className="audio-ai-report-hero">
            <div className="audio-ai-cover-frame">
              <img src={pickCover(asset)} alt="Cover" onError={handleCoverImageError} />
            </div>
            <div className="audio-ai-report-headline">
              <p className="eyebrow">{t('library.audioAnalysis.localReport', 'Lokaler Analysebericht')}</p>
              <h3>{pickTitle(asset)}</h3>
              <div className="audio-ai-meta-row">
                <span>Asset #{asset.id}</span>
                <span>{summary.duration_label || formatDuration(asset.duration_seconds)}</span>
                <span>{formatDate(analysis.generated_at)}</span>
                <span>{t('library.audioAnalysis.internalAnalysis', 'App-interne Analyse')}</span>
              </div>
              {analysis?.ai_report?.error && <p className="warning-text">{analysis.ai_report.error}</p>}
              <div className="audio-ai-lead-card">
                <span>{t('library.audioAnalysis.assessment', 'Einschätzung')}</span>
                <p>{leadText}</p>
              </div>
            </div>
          </div>
          <div className="audio-ai-report-actions button-row wrap">
            <button type="button" onClick={() => copyAudioAiAnalysisReport(analysis)}><Copy size={15} /> {t('library.audioAnalysis.copyAll', 'Alles kopieren')}</button>
            {analysis?.exports?.json && <a className="button" href={api.archive.audioAiAnalysisExportUrl(asset.id, 'json')}><Download size={15} /> {t('library.audioAnalysis.jsonFile', 'JSON-Datei')}</a>}
            {analysis?.exports?.markdown && <a className="button" href={api.archive.audioAiAnalysisExportUrl(asset.id, 'markdown')}><Download size={15} /> Markdown</a>}
            <a className="button" href={api.archive.audioAiAnalysisExportUrl(asset.id, 'html')}><Download size={15} /> HTML</a>
            <a className="button" href={api.archive.audioAiAnalysisExportUrl(asset.id, 'pdf')}><Download size={15} /> PDF</a>
            {analysis?.exports?.beatgrid_csv && <a className="button" href={api.archive.audioAiAnalysisExportUrl(asset.id, 'beatgrid_csv')}><Download size={15} /> Beatgrid CSV</a>}
          </div>
          <div className="audio-ai-report-summary-grid">
            {metrics.map((item) => (
              <article className={`audio-ai-summary-card tone-${item.tone}`} key={item.label}>
                <span>{item.label}</span>
                <strong>{item.value}</strong>
                <small>{item.detail}</small>
              </article>
            ))}
          </div>
          {Array.isArray(copyright.db_matches) && copyright.db_matches.length > 0 && (
            <div className="audio-ai-warning-strip">
              <strong>{t('library.audioAnalysis.acoustIdMatches', 'AcoustID Treffer gefunden')}</strong>
              <span>{copyright.db_matches.slice(0, 2).map((match) => `${match.title || t('common.unknown', 'Unbekannt')}${match.artist ? ` - ${match.artist}` : ''} (${match.score})`).join(' · ')}</span>
            </div>
          )}
          <div className="audio-ai-report-grid">
            {blocks.map((block) => (
              <article className={`audio-ai-report-block tone-${audioAiBlockTone(block.title)}`} key={block.title}>
                <div className="row between">
                  <h4>{block.title}</h4>
                  <button type="button" title={t('library.audioAnalysis.copySection', 'Abschnitt kopieren')} onClick={() => copyAudioAiAnalysisBlock(block)}><Copy size={14} /></button>
                </div>
                <div className="audio-ai-block-text keyboard-scroll-region" onWheel={(event) => event.stopPropagation()} onTouchMove={(event) => event.stopPropagation()}>
                  {audioAiReportLines(block.text).map((line, index) => (
                    <p className={line.startsWith('-') || line.startsWith('•') ? 'audio-ai-bullet-line' : ''} key={`${block.title}-${index}`}>{line.replace(/^[-•]\s*/, '')}</p>
                  ))}
                </div>
              </article>
            ))}
          </div>
          <details className="tech-details">
            <summary>{t('library.audioAnalysis.showRawData', 'Rohdaten anzeigen')}</summary>
            <pre className="large-pre keyboard-scroll-region" onWheel={(event) => event.stopPropagation()} onTouchMove={(event) => event.stopPropagation()}>{JSON.stringify(analysis, null, 2)}</pre>
          </details>
        </div>}
      </Modal>
    );
  }

  function AssetWorkflowWizardModal({ asset }) {
    if (!asset) return null;
    const selectedBundleKeys = selectedBundleContentKeys();
    const bundleHref = selectedBundleKeys.length ? api.archive.assetBundleUrl(asset.id, selectedBundleKeys) : '#';
    return (
      <Modal open={Boolean(asset)} title={t('library.workflow.titleForAsset', 'Audio-Wizard: {{title}}', { title: pickTitle(asset) })} onClose={() => setWorkflowWizardAsset(null)} wide cardClassName="asset-wizard-modal">
        <div className="asset-wizard stack">
          <div className="asset-wizard-header">
            <img src={pickCover(asset)} alt="Cover" onError={handleCoverImageError} />
            <div>
              <p className="eyebrow">{t('library.workflow.eyebrow', 'Ein Audio · mehrere Arbeitsschritte')}</p>
              <h3>{pickTitle(asset)}</h3>
              <p className="muted">{t('library.workflow.text', 'Aktiviere nur die Funktionen, die für diese Variante ausgeführt oder exportiert werden sollen.')}</p>
            </div>
          </div>

          <section className="asset-wizard-section">
            <div className="row between align-start">
              <div>
                <h4>{t('library.workflow.captureTitle', 'Erfassen / erzeugen')}</h4>
                <p className="muted">{t('library.workflow.captureText', 'Die aktivierten Aufgaben werden nacheinander ausgeführt.')}</p>
              </div>
              <button className="primary" type="button" onClick={() => runWorkflowWizard(asset)} disabled={workflowWizardBusy}>{workflowWizardBusy ? t('library.status.running', 'Läuft…') : t('library.workflow.startActiveTasks', 'Aktivierte Aufgaben starten')}</button>
            </div>
            <div className="wizard-toggle-grid">
              {wizardCaptureOptions.map((option) => {
                const disabled = option.key === 'timestampedLyrics' ? !asset.audio_id : option.key === 'stems' ? !isAudioLocal(asset) : false;
                return (
                  <button
                    key={option.key}
                    type="button"
                    className={`wizard-toggle ${workflowCaptureState[option.key] ? 'is-on' : ''}`}
                    onClick={() => !disabled && toggleWizardCapture(option.key)}
                    disabled={disabled || workflowWizardBusy}
                  >
                    <span>{workflowCaptureState[option.key] ? t('common.active', 'aktiv') : t('common.off', 'aus')}</span>
                    <strong>{t(`library.workflow.captureOptions.${option.key}.label`, option.label)}</strong>
                    <small>{disabled ? t('library.workflow.notAvailableForVariant', 'Nicht verfügbar für diese Variante.') : t(`library.workflow.captureOptions.${option.key}.description`, option.description)}</small>
                  </button>
                );
              })}
            </div>
          </section>

          <section className="asset-wizard-section">
            <div className="row between align-start">
              <div>
                <h4>{t('library.workflow.zipTitle', 'ZIP-Inhalte auswählen')}</h4>
                <p className="muted">{t('library.workflow.zipText', 'Das ZIP wird nur für diese Audio-Variante erstellt und enthält nur die ausgewählten Inhalte.')}</p>
              </div>
              <a className={`button primary ${!selectedBundleKeys.length ? 'disabled' : ''}`} href={selectedBundleKeys.length ? bundleHref : undefined}><Download size={15} /> {t('library.bulk.selectionZip', 'Ausgewähltes ZIP')}</a>
            </div>
            <div className="wizard-toggle-grid bundle-toggle-grid">
              {bundleContentOptions.map((option) => (
                <button
                  key={option.key}
                  type="button"
                  className={`wizard-toggle compact ${bundleContentState[option.key] ? 'is-on' : ''}`}
                  onClick={() => toggleBundleContent(option.key)}
                >
                  <span>{bundleContentState[option.key] ? t('library.workflow.inZip', 'im ZIP') : t('common.off', 'aus')}</span>
                  <strong>{t(`library.workflow.bundleOptions.${option.key}.label`, option.label)}</strong>
                  <small>{t(`library.workflow.bundleOptions.${option.key}.description`, option.description)}</small>
                </button>
              ))}
            </div>
          </section>
        </div>
      </Modal>
    );
  }

  async function cacheVideoFromModal(asset, video) {
    if (!asset?.id || !video?.id) return;
    setVideoModal((current) => ({ ...current, loading: true, error: '' }));
    try {
      const cached = await api.archive.cacheVideo(asset.id, video.id);
      setVideoModal((current) => {
        const currentVideos = Array.isArray(current.videos) ? current.videos : [];
        const nextVideos = currentVideos.length
          ? currentVideos.map((item) => String(item.id) === String(cached.id) ? cached : item)
          : [cached];
        return { ...current, videos: nextVideos, loading: false, error: '' };
      });
      notify?.(t('library.video.cachedNow', 'MP4 wurde lokal gesichert.'), 'success');
      onReload?.();
    } catch (error) {
      const message = error?.message || t('library.video.cacheError', 'MP4 konnte nicht lokal gesichert werden.');
      setVideoModal((current) => ({ ...current, loading: false, error: message }));
      notify?.(message, 'error');
    }
  }

  function VideoSummaryCard({ asset }) {
    const { latest: latestVideo, count: videoCount, isLocal } = assetVideoSummary(asset);
    if (!hasAssetVideo(asset)) return null;
    const playUrl = latestVideo?.id ? videoPlaybackUrl(asset, latestVideo) : '';
    const downloadUrl = latestVideo?.id ? videoDownloadUrl(asset, latestVideo) : '';
    return (
      <div className="meta-card wide video-summary-card">
        <div className="row between align-start">
          <div>
            <h4><Film size={16} /> {t('library.video.summaryTitle', 'MP4-Musikvideo')}</h4>
            <p className="muted">{t('library.video.summaryText', 'Das Video ist an dieses AudioAsset gebunden und bleibt getrennt von der Audio-Kernlogik.')}</p>
          </div>
          <span className={`status ${isLocal ? 'cached' : 'warning'}`}>MP4 {isLocal ? t('library.status.localShort', 'lokal') : t('library.status.remoteShort', 'remote')}</span>
        </div>
        <p className="muted">
          {t('library.video.summaryMeta', '{{count}} Video(s) · Status {{status}}', { count: videoCount || 1, status: latestVideo?.status || 'remote' })}
          {latestVideo?.filename ? ` · ${latestVideo.filename}` : ''}
        </p>
        <div className="button-row wrap">
          <button type="button" className="primary mp4-watch-button" onClick={(event) => openVideoModalFromEvent(event, asset)}><Film size={16} /> {t('library.video.watchMp4', 'MP4 ansehen')}</button>
          {downloadUrl && <a className="button" href={downloadUrl} onClick={(event) => event.stopPropagation()}><Download size={15} /> {t('library.video.downloadMp4', 'MP4 herunterladen')}</a>}
          {playUrl && <a className="button" href={playUrl} target="_blank" rel="noopener noreferrer" onClick={(event) => event.stopPropagation()}><ExternalLink size={15} /> {t('library.video.openDirect', 'Direkt öffnen')}</a>}
        </div>
      </div>
    );
  }

  function SrtCard({ asset }) {
    const state = srtByAsset[asset.id] || { exists: false, status: 'missing' };
    const busy = srtLoadingIds.has(asset.id);
    const saving = srtSavingIds.has(asset.id);
    const hasSrt = hasAssetSrt(asset, srtByAsset);
    const hasHalfSrt = hasAssetHalfSrt(asset, srtByAsset);
    const editorOpen = String(srtEditorAssetId || '') === String(asset.id);
    const rawOpen = srtRawOpenIds.has(asset.id);
    const segments = draftSegmentsForAsset(asset);
    const liveLine = liveSrtLineForAsset(asset);
    const liveSegments = srtSegmentsFromState(state);
    const visibleSegment = liveLine || (!liveLine && isCurrentAsset(asset) ? findActiveSrtSegment(liveSegments, playbackState?.currentTime || 0) : null);
    const visibleText = String(visibleSegment?.text || '').trim();
    return (
      <div className="meta-card wide srt-card">
        <div className="row between align-start">
          <div>
            <h4>{t('library.srt.title', 'SRT-Untertitel')}</h4>
            <p className="muted">{t('library.srt.text', 'Lyrics sind Source of Truth · Live-Anzeige und Segment-Editor')}</p>
          </div>
          <span className={`status ${hasSrt ? 'cached' : state.status === 'error' ? 'error' : ''}`}>{busy ? t('library.status.running', 'läuft') : hasSrt ? t('library.status.done', 'fertig') : state.status === 'error' ? t('status.stats.error', 'Fehler') : t('library.status.notGenerated', 'nicht erzeugt')}</span>
        </div>
        {state.error_message && <p className="warning-text">{state.error_message}</p>}
        <div className="button-row wrap">
          <button className="primary" type="button" onClick={() => generateSrt(asset)} disabled={busy || saving}>{busy ? t('library.srt.generating', 'Erzeuge SRT…') : hasSrt ? t('library.srt.regenerate', 'SRT neu erzeugen') : t('library.bulk.createSrt', 'SRT erzeugen')}</button>
          <button type="button" onClick={() => copySrt(asset)} disabled={!hasSrt || busy}><Copy size={14} /> {t('common.copy', 'Kopieren')}</button>
          <button type="button" onClick={() => downloadSrtText(asset)} disabled={!hasSrt || busy}><Download size={14} /> {t('common.download', 'Herunterladen')}</button>
          <button type="button" onClick={() => copyHalfSrt(asset)} disabled={!hasHalfSrt || busy}><Copy size={14} /> {t('library.srt.copyHalf', 'Half kopieren')}</button>
          <button type="button" onClick={() => downloadHalfSrtText(asset)} disabled={!hasHalfSrt || busy}><Download size={14} /> {t('library.srt.downloadHalf', 'Half herunterladen')}</button>
          <button type="button" onClick={() => openSrtEditor(asset)} disabled={!hasSrt && !segments.length}>{editorOpen ? t('library.srt.toEditor', 'Zum Editor') : t('library.srt.openEditor', 'SRT-Editor öffnen')}</button>
          <button type="button" onClick={() => addSrtSegment(asset)} disabled={!hasSrt && !segments.length}><Plus size={14} /> Segment</button>
          <button type="button" onClick={() => openSrtAssistant(asset)}>{t('globalAi.help', 'KI-Hilfe')}</button>
          {hasSrt && <a className="button" href={api.archive.srtDownloadUrl(asset.id)}><Download size={14} /> {t('library.srt.file', 'Datei')}</a>}
          {hasHalfSrt && <a className="button" href={api.archive.srtHalfDownloadUrl(asset.id)}><Download size={14} /> {t('library.srt.halfFile', 'Half-Datei')}</a>}
          {hasSrt && <SrtLiveColorSelect compact />}
        </div>
        {hasSrt && (
          <div className={`srt-live-container ${isCurrentAsset(asset) ? 'is-live' : ''}`} style={srtLiveColorStyle}>
            <div className="srt-live-label">
              <span>{isCurrentAsset(asset) ? playbackState?.isPlaying ? t('library.srt.liveRunning', 'Live-Untertitel läuft') : t('library.srt.liveReady', 'Live-Untertitel bereit') : t('library.srt.live', 'Live-Untertitel')}</span>
              <small>{isCurrentAsset(asset) ? `${formatDuration(playbackState?.currentTime || 0)} / ${formatDuration(playbackState?.duration || asset.duration_seconds)}` : t('library.srt.startVariantToRead', 'Starte diese Variante zum Mitlesen')}</small>
            </div>
            <strong>{visibleText || '\u00a0'}</strong>
            {visibleSegment && <small>{formatDuration(visibleSegment.start)} → {formatDuration(visibleSegment.end)}</small>}
          </div>
        )}
        <div className="srt-editor-inline-note">
          <strong>{t('library.srt.largeEditor', 'Großer SRT-Editor')}</strong>
          <p className="muted">{t('library.srt.largeEditorText', 'Der Segment-Editor öffnet sich in einem großen Arbeitsbereich, damit Untertitel, Roh-SRT und Live-Anzeige nicht mehr gequetscht sind.')}</p>
          <div className="button-row wrap">
            <button type="button" onClick={() => openSrtEditor(asset)} disabled={!hasSrt && !segments.length}>{editorOpen ? t('library.srt.toOpenEditor', 'Zum offenen Editor') : t('library.srt.openEditorNow', 'Editor jetzt öffnen')}</button>
            <button type="button" onClick={() => addSrtSegment(asset, null, playbackState?.currentTime || null)} disabled={!hasSrt && !segments.length}><Plus size={14} /> {t('library.srt.segmentAtPlayerTime', 'Segment bei Playerzeit')}</button>
          </div>
        </div>
        {hasSrt && (
          <div className={`srt-raw-details ${rawOpen ? 'is-open' : ''}`}>
            <button
              type="button"
              className="srt-raw-summary"
              aria-expanded={rawOpen}
              onClick={() => setSrtRawOpen(asset.id, !rawOpen)}
            >
              {rawOpen ? t('library.srt.hideRaw', 'Roh-SRT ausblenden') : t('library.srt.showRaw', 'Roh-SRT anzeigen')}
            </button>
            {rawOpen && <pre className="large-pre srt-preview keyboard-scroll-region" onWheel={(event) => event.stopPropagation()} onTouchMove={(event) => event.stopPropagation()}>{state.srt_text}</pre>}
          </div>
        )}
      </div>
    );
  }

  function SrtEditorModal({ asset }) {
    if (!asset) return null;
    const state = srtByAsset[asset.id] || { exists: false, status: 'missing' };
    const busy = srtLoadingIds.has(asset.id);
    const saving = srtSavingIds.has(asset.id);
    const hasSrt = hasAssetSrt(asset, srtByAsset);
    const hasHalfSrt = hasAssetHalfSrt(asset, srtByAsset);
    const segments = draftSegmentsForAsset(asset);
    const liveLine = liveSrtLineForAsset(asset);
    const liveSegments = srtSegmentsFromState(state);
    const visibleSegment = liveLine || (!liveLine && isCurrentAsset(asset) ? findActiveSrtSegment(liveSegments, playbackState?.currentTime || 0) : null);
    const visibleText = String(visibleSegment?.text || '').trim();
    const rawOpen = srtRawOpenIds.has(asset.id);
    return (
      <Modal
        open={Boolean(asset)}
        title={t('library.srt.editorTitle', 'SRT-Editor: {{title}}', { title: pickTitle(asset) })}
        onClose={() => setSrtEditorOpen(asset.id, false)}
        wide
        cardClassName="srt-editor-modal"
        contentClassName="srt-editor-modal-content"
      >
        <div className="srt-modal-shell">
          <div className="srt-modal-toolbar">
            <div>
              <strong>{t('library.srt.editSubtitles', 'Untertitel bearbeiten')}</strong>
              <p className="muted">{t('library.srt.editorWorkspaceText', 'Großer Arbeitsbereich für Live-Zeile, Segmentliste und Roh-SRT.')}</p>
            </div>
            <div className="button-row wrap">
              <button className="primary" type="button" onClick={() => generateSrt(asset)} disabled={busy || saving}>{busy ? t('library.srt.generating', 'Erzeuge SRT…') : hasSrt ? t('library.srt.regenerate', 'SRT neu erzeugen') : t('library.bulk.createSrt', 'SRT erzeugen')}</button>
              <button type="button" onClick={() => addSrtSegment(asset, null, playbackState?.currentTime || null)}><Plus size={14} /> {t('library.srt.atCurrentTime', 'Bei aktueller Zeit')}</button>
              <button type="button" onClick={() => resetSrtEditor(asset)}>{t('common.reset', 'Zurücksetzen')}</button>
              <button type="button" onClick={() => openSrtAssistant(asset)}>{t('globalAi.help', 'KI-Hilfe')}</button>
              <SrtLiveColorSelect compact />
              <button className="primary" type="button" onClick={() => saveSrtEditor(asset)} disabled={saving}>{saving ? t('common.saving', 'Speichert…') : t('common.save', 'Speichern')}</button>
            </div>
          </div>
          <div className="srt-modal-workbench">
            <aside className="srt-modal-sidebar">
              <div className={`srt-live-container ${isCurrentAsset(asset) ? 'is-live' : ''}`} style={srtLiveColorStyle}>
                <div className="srt-live-label">
                  <span>{isCurrentAsset(asset) ? playbackState?.isPlaying ? t('library.srt.liveRunning', 'Live-Untertitel läuft') : t('library.srt.liveReady', 'Live-Untertitel bereit') : t('library.srt.live', 'Live-Untertitel')}</span>
                  <small>{isCurrentAsset(asset) ? `${formatDuration(playbackState?.currentTime || 0)} / ${formatDuration(playbackState?.duration || asset.duration_seconds)}` : t('library.srt.startVariantToRead', 'Starte diese Variante zum Mitlesen')}</small>
                </div>
                <strong>{visibleText || '\u00a0'}</strong>
                {visibleSegment && <small>{formatDuration(visibleSegment.start)} → {formatDuration(visibleSegment.end)}</small>}
              </div>
              <div className="meta-card srt-modal-summary-card">
                <h4>{t('library.srt.helpTitle', 'Bedienhilfe')}</h4>
                <ul className="srt-help-list">
                  <li><strong>{t('common.save', 'Speichern')}</strong> {t('library.srt.helpSave', 'schreibt nur deine aktuellen Segmentänderungen zurück.')}</li>
                  <li><strong>{t('library.srt.atCurrentTime', 'Bei aktueller Zeit')}</strong> {t('library.srt.helpCurrentTime', 'setzt schnell ein neues Segment an der Playerposition.')}</li>
                  <li><strong>{t('library.srt.rawSrt', 'Roh-SRT')}</strong> {t('library.srt.helpRaw', 'bleibt unten sichtbar und kann direkt kopiert oder heruntergeladen werden.')}</li>
                </ul>
                <div className="button-row wrap">
                  <button type="button" onClick={() => copySrt(asset)} disabled={!hasSrt || busy}><Copy size={14} /> {t('common.copy', 'Kopieren')}</button>
                  <button type="button" onClick={() => downloadSrtText(asset)} disabled={!hasSrt || busy}><Download size={14} /> {t('common.download', 'Herunterladen')}</button>
                  <button type="button" onClick={() => copyHalfSrt(asset)} disabled={!hasHalfSrt || busy}><Copy size={14} /> {t('library.srt.copyHalf', 'Half kopieren')}</button>
                  <button type="button" onClick={() => downloadHalfSrtText(asset)} disabled={!hasHalfSrt || busy}><Download size={14} /> {t('library.srt.downloadHalf', 'Half herunterladen')}</button>
                  {hasSrt && <a className="button" href={api.archive.srtDownloadUrl(asset.id)}><Download size={14} /> {t('library.srt.file', 'Datei')}</a>}
                  {hasHalfSrt && <a className="button" href={api.archive.srtHalfDownloadUrl(asset.id)}><Download size={14} /> {t('library.srt.halfFile', 'Half-Datei')}</a>}
                </div>
              </div>
              {hasSrt && (
                <div className={`srt-raw-details srt-modal-raw ${rawOpen ? 'is-open' : ''}`}>
                  <button
                    type="button"
                    className="srt-raw-summary"
                    aria-expanded={rawOpen}
                    onClick={() => setSrtRawOpen(asset.id, !rawOpen)}
                  >
                    {rawOpen ? t('library.srt.hideRaw', 'Roh-SRT ausblenden') : t('library.srt.showRaw', 'Roh-SRT anzeigen')}
                  </button>
                  {rawOpen && <pre className="large-pre srt-preview srt-modal-preview keyboard-scroll-region" onWheel={(event) => event.stopPropagation()} onTouchMove={(event) => event.stopPropagation()}>{state.srt_text}</pre>}
                </div>
              )}
            </aside>
            <section className="srt-modal-main">
              {state.error_message && <p className="warning-text">{state.error_message}</p>}
              <div className="srt-segment-editor srt-segment-editor-modal">
                <div className="row between align-start">
                  <div>
                    <strong>{t('library.srt.segmentList', 'Segment-Liste')}</strong>
                    <p className="muted">{t('library.srt.segmentListText', 'Zeiten und Text korrigieren, neue Zeilen ergänzen oder problematische Stellen direkt bereinigen.')}</p>
                  </div>
                  <span className={`status ${hasSrt ? 'cached' : state.status === 'error' ? 'error' : ''}`}>{busy ? t('library.status.running', 'läuft') : hasSrt ? t('library.status.done', 'fertig') : state.status === 'error' ? t('status.stats.error', 'Fehler') : t('library.status.notGenerated', 'nicht erzeugt')}</span>
                </div>
                <div className="srt-editor-list srt-editor-list-modal">
                  {segments.map((segment, index) => {
                    const rowActive = isCurrentAsset(asset) && Number(playbackState?.currentTime || 0) >= segment.start && Number(playbackState?.currentTime || 0) < segment.end;
                    return (
                      <div className={`srt-editor-row ${rowActive ? 'is-active' : ''}`} key={`${asset.id}-${index}`}>
                        <span className="srt-editor-index">{index + 1}</span>
                        <label>{t('library.srt.start', 'Start')}<input type="number" min="0" step="0.05" value={segment.start} onChange={(event) => updateSrtDraftSegment(asset.id, index, { start: event.target.value })} /></label>
                        <label>{t('library.srt.end', 'Ende')}<input type="number" min="0" step="0.05" value={segment.end} onChange={(event) => updateSrtDraftSegment(asset.id, index, { end: event.target.value })} /></label>
                        <textarea value={segment.text} rows={3} onChange={(event) => updateSrtDraftSegment(asset.id, index, { text: event.target.value })} />
                        <div className="srt-editor-actions">
                          <button type="button" onClick={() => updateSrtDraftSegment(asset.id, index, { start: playbackState?.currentTime || 0 })} disabled={!isCurrentAsset(asset)}>{t('library.srt.startNow', 'Start = Jetzt')}</button>
                          <button type="button" onClick={() => updateSrtDraftSegment(asset.id, index, { end: playbackState?.currentTime || segment.end })} disabled={!isCurrentAsset(asset)}>{t('library.srt.endNow', 'Ende = Jetzt')}</button>
                          <button type="button" onClick={() => addSrtSegment(asset, index, segment.end)}><Plus size={13} /> {t('library.srt.after', 'danach')}</button>
                          <button type="button" onClick={() => addSrtSegment(asset, index, Math.max(0, segment.start - 1), t('library.srt.newSubtitleLine', 'Neue Untertitel-Zeile'))}><Plus size={13} /> {t('library.srt.before', 'davor')}</button>
                          <button type="button" onClick={() => deleteSrtSegment(asset.id, index)}><Trash2 size={13} /> {t('common.delete', 'löschen')}</button>
                        </div>
                      </div>
                    );
                  })}
                  {!segments.length && <p className="warning-text">{t('library.srt.noSegments', 'Keine Segmente im Editor. Erzeuge zuerst eine SRT oder füge ein Segment hinzu.')}</p>}
                </div>
              </div>
            </section>
          </div>
        </div>
      </Modal>
    );
  }

  function defaultAudioOperationForm(asset, typeName) {
    const baseTitle = pickTitle(asset) || 'Song';
    const sourceText = pickPrompt(asset) || pickLyrics(asset) || '';
    const sourceStyle = pickStyle(asset) || '';
    const generationOptions = getGenerationOptions(asset);
    const duration = Number(asset?.duration_seconds || 0);
    const continueAtOverrides = readExtendContinueAtOverrides();
    const storedContinueAt = asset?.id ? continueAtOverrides[String(asset.id)] : '';
    const continueAt = storedContinueAt || (duration > 0 ? Math.max(1, Math.floor(duration * 0.72)) : 60);
    const safeModel = sunoModelOptions.includes(String(asset?.model_name || asset?.model || '')) ? String(asset?.model_name || asset?.model) : 'V5_5';
    if (typeName === 'Cover Song') {
      return {
        model: safeModel,
        title: `${baseTitle} Cover`,
        prompt: sourceText || baseTitle,
        style: sourceStyle,
        continueAt: '',
        customMode: Boolean(sourceStyle || sourceText),
        instrumental: false,
        negative_tags: String(generationOptions.negative_tags || '')
      };
    }
    if (typeName === 'Add Vocals') {
      return {
        model: 'V4_5PLUS',
        title: `${baseTitle} Vocals`,
        prompt: sourceText || baseTitle,
        style: sourceStyle || 'studio vocals',
        continueAt: '',
        customMode: false,
        instrumental: false,
        negative_tags: String(generationOptions.negative_tags || 'low quality, distorted, off key')
      };
    }
    if (typeName === 'Add Instrumental') {
      return {
        model: 'V4_5PLUS',
        title: `${baseTitle} Instrumental`,
        prompt: '',
        style: sourceStyle || 'studio instrumental',
        continueAt: '',
        customMode: false,
        instrumental: true,
        negative_tags: String(generationOptions.negative_tags || 'low quality, distorted, noisy')
      };
    }
    return {
      model: safeModel,
      title: `${baseTitle} Extended`,
      prompt: sourceText,
      style: sourceStyle,
      continueAt: String(continueAt),
      customMode: true,
      instrumental: false,
      negative_tags: String(generationOptions.negative_tags || '')
    };
  }

  function openAudioOperationModal(asset, typeName) {
    if (!asset?.id) return;
    if (!canRunSunoApiAction(asset, typeName)) {
      notify(localOnlyHint(asset, t) || t('library.messages.actionDisabledForAsset', '{{type}} ist für dieses AudioAsset deaktiviert.', { type: typeName }), 'info');
      return;
    }
    setActionAsset(null);
    setOpenAudioMenuId(null);
    setOpenAudioMenuPosition(null);
    setAudioOperationForm(defaultAudioOperationForm(asset, typeName));
    setAudioOperationModal({ type: typeName, asset });
  }

  function closeAudioOperationModal() {
    if (audioOperationBusy || continueAtAnalysisBusy) return;
    setAudioOperationModal({ type: '', asset: null });
  }

  async function analyzeAudioOperationContinueAt() {
    const asset = audioOperationModal.asset;
    if (!asset?.id) return;
    setContinueAtAnalysisBusy(true);
    try {
      const result = await api.archive.analyzeExtendContinueAt(asset.id);
      const continueAt = Number(result?.continue_at ?? result?.continueAt);
      if (!Number.isFinite(continueAt) || continueAt <= 0) {
        notify(t('library.messages.continueAtInvalidResult', 'continueAt-Analyse hat keinen gültigen Wert geliefert.'), 'error');
        return;
      }
      writeExtendContinueAtOverride(asset.id, continueAt);
      setAudioOperationForm((state) => ({ ...state, continueAt: String(continueAt) }));
      notify(t('library.messages.continueAtCalculated', 'continueAt berechnet: {{seconds}}s', { seconds: continueAt.toFixed(3) }), 'success');
    } catch (err) {
      notify(err?.message || t('library.messages.continueAtFailed', 'continueAt-Analyse fehlgeschlagen.'), 'error');
    } finally {
      setContinueAtAnalysisBusy(false);
    }
  }

  async function submitAudioOperation() {
    const asset = audioOperationModal.asset;
    const typeName = audioOperationModal.type;
    if (!asset?.id || !typeName) return;
    const model = sunoModelOptions.includes(audioOperationForm.model) ? audioOperationForm.model : 'V5_5';
    const title = String(audioOperationForm.title || '').trim();
    const prompt = String(audioOperationForm.prompt || '').trim();
    const style = String(audioOperationForm.style || '').trim();
    const negativeTags = String(audioOperationForm.negative_tags || '').trim();
    const generationOptions = getGenerationOptions(asset);
    const voiceInfo = voiceInfoForAsset(asset);
    const personaPayload = voiceInfo?.id ? {
      persona_id: voiceInfo.id,
      persona_model: voiceInfo.source_type === 'persona' ? 'style_persona' : 'voice_persona'
    } : {};

    if (!title) return notify(t('library.messages.titleRequired', 'Bitte einen Titel angeben.'), 'error');
    if (!prompt && typeName === 'Cover Song' && !audioOperationForm.instrumental) return notify(t('library.messages.coverPromptRequired', 'Bitte Songtext/Prompt für den Cover Song angeben.'), 'error');
    if (!prompt && typeName === 'Extend') return notify(t('library.messages.extendPromptRequired', 'Bitte den erweiterten Songtext/Prompt angeben.'), 'error');

    setAudioOperationBusy(true);
    try {
      let result;
      if (typeName === 'Extend') {
        const continueAt = Number(String(audioOperationForm.continueAt || '').replace(',', '.'));
        if (!Number.isFinite(continueAt) || continueAt <= 0) {
          notify(t('library.messages.extendStartRequired', 'Bitte eine gültige Extend-Startzeit in Sekunden angeben.'), 'error');
          return;
        }
        if (!style) {
          notify(t('library.messages.extendStyleRequired', 'Bitte Style/Tags für die Extension angeben.'), 'error');
          return;
        }
        const useCustomExtend = Boolean(prompt && style && title && Number.isFinite(continueAt) && continueAt > 0);
        result = await api.archive.extend(asset.id, {
          model,
          title,
          prompt,
          style,
          continueAt: useCustomExtend ? continueAt : undefined,
          defaultParamFlag: useCustomExtend,
          negative_tags: negativeTags || undefined,
          vocal_gender: generationOptions.vocalGender || undefined,
          styleWeight: optionalGenerationNumber(generationOptions.styleWeight),
          weirdnessConstraint: optionalGenerationNumber(generationOptions.weirdnessConstraint),
          audioWeight: optionalGenerationNumber(generationOptions.audioWeight),
          ...personaPayload
        });
      } else {
        const customMode = Boolean(audioOperationForm.customMode);
        if (customMode && !style) {
          notify(t('library.messages.coverStyleRequired', 'Bitte Style/Tags für den Custom-Cover-Song angeben oder Custom-Modus deaktivieren.'), 'error');
          return;
        }
        result = await api.archive.coverSong(asset.id, {
          model,
          title,
          prompt: prompt || title,
          style: style || undefined,
          customMode,
          instrumental: Boolean(audioOperationForm.instrumental),
          negative_tags: negativeTags || undefined
        });
      }
      notify(t('library.messages.operationStarted', '{{type}} gestartet: {{task}}', { type: typeName, task: result.task_id || result.external_task_id || t('library.messages.taskCreated', 'Task erstellt') }), 'success');
      setAudioOperationModal({ type: '', asset: null });
      await onReload?.();
    } catch (err) {
      notify(err.message || t('library.messages.operationFailed', '{{type}} fehlgeschlagen.', { type: typeName }), 'error');
    } finally {
      setAudioOperationBusy(false);
    }
  }

  async function runAction(asset, typeName) {
    if (!canRunSunoApiAction(asset, typeName)) {
      notify(localOnlyHint(asset, t) || t('library.messages.actionDisabledForAsset', '{{type}} ist für dieses AudioAsset deaktiviert.', { type: typeName }), 'info');
      return;
    }
    if (typeName === 'Extend' || typeName === 'Cover Song') {
      openAudioOperationModal(asset, typeName);
      return;
    }
    const title = pickTitle(asset);
    const generationOptions = getGenerationOptions(asset);
    const optionPayload = {
      vocalGender: generationOptions.vocalGender || undefined,
      styleWeight: optionalGenerationNumber(generationOptions.styleWeight),
      weirdnessConstraint: optionalGenerationNumber(generationOptions.weirdnessConstraint),
      audioWeight: optionalGenerationNumber(generationOptions.audioWeight)
    };
    const payload = { title: `${title} - ${typeName}` };
    if (typeName === 'Extend') payload.prompt = pickPrompt(asset) || '';
    if (typeName === 'Cover Song') payload.prompt = pickPrompt(asset) || title;
    if (typeName === 'Add Vocals') {
      payload.prompt = pickPrompt(asset) || pickLyrics(asset) || title;
      payload.style = pickStyle(asset) || 'studio vocals';
      payload.negativeTags = generationOptions.negativeTags || 'low quality, distorted, off key';
      payload.model = 'V4_5PLUS';
      Object.assign(payload, optionPayload);
    }
    if (typeName === 'Add Instrumental') {
      payload.tags = pickStyle(asset) || 'studio instrumental';
      payload.negativeTags = generationOptions.negativeTags || 'low quality, distorted, noisy';
      payload.model = 'V4_5PLUS';
      Object.assign(payload, optionPayload);
    }
    try {
      const result = typeName === 'Extend'
        ? await api.archive.extend(asset.id, payload)
        : typeName === 'Cover Song'
          ? await api.archive.coverSong(asset.id, payload)
          : typeName === 'Add Vocals'
            ? await api.archive.addVocals(asset.id, payload)
            : typeName === 'Add Instrumental'
              ? await api.archive.addInstrumental(asset.id, payload)
              : typeName === 'Persona'
                ? await api.archive.createPersona(asset.id, { name: `${title} Persona`, description: title })
                : await api.archive.createCoverImage(asset.id, { prompt: title });
      notify(t('library.messages.operationStarted', '{{type}} gestartet: {{task}}', { type: typeName, task: result.task_id || result.external_task_id || t('library.messages.taskCreated', 'Task erstellt') }), 'success');
      setActionAsset(null);
      await onReload();
    } catch (err) {
      notify(err.message || t('library.messages.operationFailed', '{{type}} fehlgeschlagen.', { type: typeName }), 'error');
    }
  }


  async function exportProjectJson(project) {
    downloadTextFile(`${safeFilename(project.title)} - ${t('library.export.projectJsonFilename', 'Projekt')}.json`, JSON.stringify(project, null, 2), 'application/json;charset=utf-8');
    notify(t('library.messages.projectJsonExported', 'Projekt-JSON wurde exportiert.'), 'success');
  }

  async function exportProjectText(project) {
    const lines = [
      `${t('library.export.project', 'Projekt')}: ${project.title}`,
      `${t('library.stats.variants', 'Varianten')}: ${project.assets.length}`,
      '',
      ...project.assets.map((asset, index) => [
        `--- ${t('library.export.variant', 'Variante')} ${index + 1}/${project.assets.length || 1}: ${pickTitle(asset)} ---`,
        `${t('library.export.operation', 'Vorgang')}: ${operationLabel(asset.operation_type || asset.task_type || asset.operation_label, t)}`,
        `${t('library.audioOperation.duration', 'Dauer')}: ${formatDuration(asset.duration_seconds)}`,
        `Audio-ID: ${asset.audio_id || ''}`,
        `Task-ID: ${asset.suno_task_id || asset.task_id || ''}`,
        '',
        'STYLE:',
        pickStyle(asset) || '',
        '',
        'PROMPT / LYRICS:',
        pickPrompt(asset) || pickLyrics(asset) || '',
        ''
      ].join('\n'))
    ];
    downloadTextFile(`${safeFilename(project.title)} - ${t('library.export.lyricsAndStyleFilename', 'Songtext und Style')}.txt`, lines.join('\n'), 'text/plain;charset=utf-8');
    notify(t('library.messages.projectTextExported', 'Projekt-Text wurde exportiert.'), 'success');
  }

  async function saveProjectLyrics(project) {
    const best = project.assets.find((asset) => asset.is_final) || project.assets.find((asset) => asset.is_favorite) || project.assets[0];
    const text = pickPrompt(best) || pickLyrics(best);
    if (!text) return notify(t('library.messages.noLyricsPromptToSave', 'Kein Songtext/Prompt zum Speichern gefunden.'), 'error');
    await api.library.createLyric({ title: project.title, content: text, lyrics: text, tags: pickStyle(best) });
    notify(t('library.messages.lyricsSavedToArchive', 'Songtext wurde im Songtext-Archiv gespeichert.'), 'success');
    await onReload();
  }

  function reuseProjectPrompt(project) {
    const best = project.assets.find((asset) => asset.is_final) || project.assets.find((asset) => asset.is_favorite) || project.assets.find((asset) => pickPrompt(asset) || pickLyrics(asset) || pickStyle(asset)) || project.assets[0];
    const text = pickPrompt(best) || pickLyrics(best);
    const nextStyle = pickStyle(best);
    if (!text && !nextStyle) return notify(t('library.messages.noPromptOrStyleToReuse', 'Kein Prompt oder Style zum Wiederverwenden gefunden.'), 'error');
    onReusePrompt?.({ title: project.title, prompt: text || '', lyrics: text || '', style: nextStyle || '' });
  }

  function reuseAssetPrompt(asset) {
    const text = pickPrompt(asset) || pickLyrics(asset);
    const nextStyle = pickStyle(asset);
    if (!text && !nextStyle) return notify(t('library.messages.noPromptOrStyleToReuse', 'Kein Prompt oder Style zum Wiederverwenden gefunden.'), 'error');
    onReusePrompt?.({ title: pickTitle(asset), prompt: text || '', lyrics: text || '', style: nextStyle || '' });
  }

  function prepareAssetExtendInMusic(asset) {
    if (!asset?.id) return;
    const text = pickPrompt(asset) || pickLyrics(asset);
    const nextStyle = pickStyle(asset);
    const generationOptions = getGenerationOptions(asset);
    const rawAudioId = String(asset.audio_id || '').trim();
    const hasReusableAudioId = Boolean(rawAudioId && !rawAudioId.toLowerCase().startsWith('manual-'));
    const preparedMode = hasReusableAudioId ? 'extend' : 'upload-extend';
    const continueAtSeconds = asset.duration_seconds ? Math.max(30, Math.floor(Number(asset.duration_seconds) * 0.72)) : 60;
    onReusePrompt?.({
      title: `${pickTitle(asset)} - Extended`,
      prompt: text || '',
      lyrics: text || '',
      style: nextStyle || '',
      operationMode: preparedMode,
      selectedAssetId: String(asset.id),
      audioUrl: preparedMode === 'upload-extend' ? String(asset.source_url || asset.public_url || '') : '',
      continueAt: String(continueAtSeconds),
      negativeTags: generationOptions.negativeTags || undefined,
      vocalGender: generationOptions.vocalGender || undefined,
      styleWeight: generationOptions.styleWeight !== '' ? generationOptions.styleWeight : undefined,
      weirdnessConstraint: generationOptions.weirdnessConstraint !== '' ? generationOptions.weirdnessConstraint : undefined,
      audioWeight: generationOptions.audioWeight !== '' ? generationOptions.audioWeight : undefined,
      customMode: true,
      work_mode: 'extend',
      forceAdvanced: true,
      message: hasReusableAudioId
        ? t('library.messages.extendPreparedInGenerator', 'Musik erweitern wurde im Generator vorbereitet.')
        : t('library.messages.uploadExtendPrepared', 'Upload And Extend wurde vorbereitet. Prüfe bei lokalen Importen, ob eine extern erreichbare Audio-URL vorhanden ist.')
    });
  }

  async function saveAssetLyricsToArchive(asset) {
    const text = pickPrompt(asset) || pickLyrics(asset);
    if (!text) return notify(t('library.messages.noLyricsAvailable', 'Kein Songtext vorhanden.'), 'error');
    await api.library.createLyric({ title: pickTitle(asset), content: text, tags: pickStyle(asset) });
    notify(t('library.messages.lyricsSaved', 'Songtext gespeichert.'), 'success');
    await onReload?.();
  }

  function resolveEditorAsset(assetOrId) {
    const id = typeof assetOrId === 'object' ? assetOrId?.id : assetOrId;
    if (!id) return null;
    return visibleAssets.find((item) => String(item.id) === String(id)) || (typeof assetOrId === 'object' ? assetOrId : null);
  }

  function openLyricsEditor(assetOrId, event) {
    event?.preventDefault?.();
    event?.stopPropagation?.();
    const asset = resolveEditorAsset(assetOrId);
    if (!asset?.id) {
      notify(t('library.messages.lyricsEditorMissingAudioId', 'Der Songtext-Editor konnte nicht geöffnet werden, weil die Audio-ID fehlt.'), 'error');
      return;
    }
    setOpenAudioMenuId(null);
    setActionAsset(null);
    setLyricsEditorAssetSnapshot(asset);
    setLyricsEditorAssetId(asset.id);
    setLyricsEditorDraft(pickPrompt(asset) || pickLyrics(asset) || '');
  }

  function closeLyricsEditor() {
    if (lyricsEditorBusy) return;
    setLyricsEditorAssetId(null);
    setLyricsEditorAssetSnapshot(null);
    setLyricsEditorDraft('');
  }

  async function saveLyricsEditor({ regenerateSrt = false } = {}) {
    const asset = lyricsEditorAsset;
    if (!asset?.id) return;
    const cleanText = String(lyricsEditorDraft || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
    if (!cleanText) {
      notify(t('library.messages.lyricsEmpty', 'Der Songtext darf nicht leer sein.'), 'error');
      return;
    }
    setLyricsEditorBusy(true);
    try {
      const updated = await api.archive.updateLyrics(asset.id, { lyrics: cleanText, prompt: cleanText });
      notify(t('library.messages.lyricsSavedSourceOfTruth', 'Prompt/Lyrics wurden gespeichert. Neue SRT-Erzeugungen nutzen diesen Text als Source of Truth.'), 'success');
      if (regenerateSrt) {
        const srt = await api.archive.generateSrt(asset.id, { force: true, lyrics_override: cleanText });
        if (srt?.queued || srt?.task_local_id) {
          notify(t('library.messages.lyricsSavedSrtStarted', 'Prompt/Lyrics gespeichert und SRT-Erzeugung gestartet: Task #{{task}}.', { task: srt.task_local_id || '—' }), 'success');
        } else {
          setSrtByAsset((current) => ({ ...current, [asset.id]: srt }));
          notifySrtUpdated(asset.id, srt);
          notify(t('library.messages.lyricsSavedSrtCreated', 'Prompt/Lyrics gespeichert und SRT wurde neu erzeugt.'), 'success');
        }
      }
      setLyricsEditorAssetSnapshot(updated || asset);
      setLyricsEditorAssetId((updated || asset)?.id || asset.id);
      await onReload?.();
      setLyricsEditorAssetId(null);
      setLyricsEditorAssetSnapshot(null);
      setLyricsEditorDraft('');
    } catch (err) {
      notify(err?.message || t('library.messages.lyricsSaveFailed', 'Prompt/Lyrics konnten nicht gespeichert werden.'), 'error');
    } finally {
      setLyricsEditorBusy(false);
    }
  }

  function openAiCoverModal(asset) {
    if (!asset?.id) return;
    setAiCoverForm({ model: 'pro', note: '', referenceFile: null });
    setAiCoverAsset(asset);
  }

  function closeAiCoverModal() {
    if (aiCoverBusy) return;
    setAiCoverAsset(null);
    setAiCoverForm({ model: 'pro', note: '', referenceFile: null });
  }

  function handleAiCoverReferenceFileChange(event) {
    event?.stopPropagation?.();
    const file = event?.currentTarget?.files?.[0] || null;
    setAiCoverForm((state) => ({ ...state, referenceFile: file }));
  }

  async function submitAiCover() {
    if (!aiCoverAsset?.id) return;
    try {
      setAiCoverBusy(true);
      const formData = new FormData();
      formData.append('model', String(aiCoverForm.model || 'pro'));
      if (String(aiCoverForm.note || '').trim()) formData.append('note', String(aiCoverForm.note || '').trim());
      if (aiCoverForm.referenceFile) formData.append('reference_image', aiCoverForm.referenceFile, aiCoverForm.referenceFile.name || 'reference-image');
      const result = await api.archive.generateAiCover(aiCoverAsset.id, formData);
      notify?.(t('library.messages.aiCoverStarted', 'KI-Cover gestartet: {{task}}', { task: result.task_id || result.id || t('library.messages.taskCreated', 'Task erstellt') }), 'success');
      setAiCoverAsset(null);
      setAiCoverForm({ model: 'pro', note: '', referenceFile: null });
      await onReload?.({ forceContentRefresh: true });
    } catch (err) {
      notify?.(err?.message || t('library.messages.aiCoverFailed', 'KI-Cover konnte nicht gestartet werden.'), 'error');
    } finally {
      setAiCoverBusy(false);
    }
  }

  function openCoverReplaceModal(asset) {
    if (!asset?.id) return;
    setCoverReplaceFile(null);
    setCoverReplaceAsset(asset);
  }

  function closeCoverReplaceModal() {
    if (coverReplaceBusy) return;
    setCoverReplaceAsset(null);
    setCoverReplaceFile(null);
  }

  async function submitCoverReplace() {
    if (!coverReplaceAsset?.id) return;
    if (!coverReplaceFile) return notify?.(t('library.messages.selectCoverFile', 'Bitte eine Cover-Datei auswählen.'), 'error');
    try {
      setCoverReplaceBusy(true);
      const formData = new FormData();
      formData.append('cover', coverReplaceFile);
      const result = await api.library.updateCover('audio', coverReplaceAsset.id, formData);
      const coverUrl = result?.cover?.public_url || '';
      const updatedIds = Array.isArray(result?.updated_audio_asset_ids) && result.updated_audio_asset_ids.length
        ? result.updated_audio_asset_ids
        : [coverReplaceAsset.id];
      if (coverUrl) {
        setCoverOverrides((current) => {
          const next = { ...current };
          updatedIds.forEach((id) => { if (id !== null && id !== undefined) next[String(id)] = coverUrl; });
          return next;
        });
      }
      notify?.(t('library.messages.coverReplaced', 'Cover wurde ersetzt.'), 'success');
      setCoverReplaceAsset(null);
      setCoverReplaceFile(null);
      await onReload?.({ forceContentRefresh: true });
    } catch (err) {
      notify?.(err?.message || t('library.messages.coverReplaceFailed', 'Cover konnte nicht ersetzt werden.'), 'error');
    } finally {
      setCoverReplaceBusy(false);
    }
  }

  function openPictureViewer(asset) {
    if (!asset?.id) return;
    const coverUrl = pickCover(asset);
    if (isFallbackCoverUrl(coverUrl)) {
      notify?.(t('library.messages.noCoverForTrack', 'Für diesen Track ist kein Coverbild vorhanden.'), 'error');
      return;
    }
    setPictureViewerAsset(asset);
    setPictureViewerZoom(1);
    setPictureViewerMaximized(false);
  }

  function closePictureViewer() {
    setPictureViewerAsset(null);
    setPictureViewerZoom(1);
    setPictureViewerMaximized(false);
  }

  function changePictureViewerZoom(delta) {
    setPictureViewerZoom((value) => Math.min(4, Math.max(0.25, Number((value + delta).toFixed(2)))));
  }

  async function downloadCoverImage(asset) {
    if (!asset?.id) return;
    const coverUrl = pickCover(asset);
    if (isFallbackCoverUrl(coverUrl)) {
      notify?.(t('library.messages.noCoverForTrack', 'Für diesen Track ist kein Coverbild vorhanden.'), 'error');
      return;
    }
    const filename = coverDownloadFilename(asset, coverUrl);
    const triggerDownload = (href) => {
      const link = document.createElement('a');
      link.href = href;
      link.download = filename;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      document.body.appendChild(link);
      link.click();
      link.remove();
    };
    try {
      const response = await fetch(coverUrl, { credentials: 'include' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      triggerDownload(objectUrl);
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1500);
      notify?.(t('library.messages.coverDownloaded', 'Coverbild wurde heruntergeladen.'), 'success');
    } catch (err) {
      triggerDownload(coverUrl);
      notify?.(t('library.messages.coverDownloadFallback', 'Coverbild wurde über die Bild-URL geöffnet. Falls der Browser den Download blockiert, dort speichern.'), 'warning');
    }
  }

  async function cacheMissingLibraryContent() {
    try {
      setContentCacheBusy(true);
      const result = await api.archive.cacheMissingContent();
      notify?.(result?.message || t('library.messages.libraryContentChecked', 'Library-Inhalte wurden geprüft.'), result?.failed ? 'warning' : 'success');
      await onReload?.({ forceContentRefresh: true });
    } catch (err) {
      notify?.(err?.message || t('library.messages.libraryContentCheckFailed', 'Library-Inhalte konnten nicht geprüft werden.'), 'error');
    } finally {
      setContentCacheBusy(false);
    }
  }

  function audioMenuKey(asset) {
    return asset?.id ? `audio-${asset.id}` : '';
  }

  function calculateAudioMenuPosition(trigger) {
    if (!trigger || typeof window === 'undefined') return null;
    const rect = trigger.getBoundingClientRect();
    const margin = 12;
    const width = Math.min(330, Math.max(260, window.innerWidth - (margin * 2)));
    const left = Math.min(
      Math.max(margin, rect.right - width),
      Math.max(margin, window.innerWidth - width - margin)
    );
    const spaceBelow = Math.max(0, window.innerHeight - rect.bottom - margin);
    const spaceAbove = Math.max(0, rect.top - margin);
    const openUp = spaceBelow < 300 && spaceAbove > spaceBelow;
    const maxHeight = Math.max(220, Math.min(620, (openUp ? spaceAbove : spaceBelow) - 8));
    return {
      placement: openUp ? 'top' : 'bottom',
      left,
      width,
      maxHeight,
      top: openUp ? undefined : Math.min(window.innerHeight - margin, rect.bottom + 8),
      bottom: openUp ? Math.min(window.innerHeight - margin, window.innerHeight - rect.top + 8) : undefined,
    };
  }

  function toggleAudioMenu(event, asset) {
    event?.preventDefault?.();
    event?.stopPropagation?.();
    const key = audioMenuKey(asset);
    if (!key) return;
    const position = calculateAudioMenuPosition(event?.currentTarget);
    preserveWindowScroll(() => {
      setOpenAudioMenuId((current) => {
        if (current === key) {
          setOpenAudioMenuPosition(null);
          return null;
        }
        audioMenuScrollRef.current = { key, scrollTop: 0 };
        setOpenAudioMenuPosition(position);
        return key;
      });
    });
  }

  function closeAudioMenu() {
    preserveWindowScroll(() => {
      setOpenAudioMenuId(null);
      setOpenAudioMenuPosition(null);
    });
  }

  async function openVideoModal(asset) {
    if (!asset?.id) return;
    const optimisticVideo = latestAssetVideo(asset);
    const optimisticVideos = optimisticVideo ? [optimisticVideo] : [];
    // Sofort sichtbar machen. Die Detailabfrage darf das Modal nicht blockieren
    // und darf keine Warnung erzeugen, solange die Library bereits latest_video
    // mit valider Video-ID geliefert hat.
    setVideoModal({ asset, videos: optimisticVideos, loading: true, error: '' });
    try {
      const videos = await api.archive.videos(asset.id);
      const normalizedVideos = Array.isArray(videos) && videos.length ? videos : optimisticVideos;
      setVideoModal({ asset, videos: normalizedVideos, loading: false, error: '' });
    } catch (error) {
      const message = error?.message || t('library.video.loadError', 'Videos konnten nicht geladen werden.');
      setVideoModal({
        asset,
        videos: optimisticVideos,
        loading: false,
        error: optimisticVideos.length ? '' : message,
      });
      if (!optimisticVideos.length) notify?.(message, 'error');
    }
  }

  function openVideoModalFromEvent(event, asset) {
    event?.preventDefault?.();
    event?.stopPropagation?.();
    void openVideoModal(asset);
  }

  function closeVideoModal() {
    setVideoModal({ asset: null, videos: [], loading: false, error: '' });
  }

  function AudioActionMenu({ asset, label = 'Aktionen', compact = false, dropUp = false, playQueue = null, playIndex = 0, project = null } = {}) {
    if (!asset?.id) return null;
    const key = audioMenuKey(asset);
    const open = openAudioMenuId === key;
    const stems = readAssetStems(asset);
    const wav = readAssetWavConversion(asset);
    const wavBusy = wavLoadingIds.has(asset.id);
    const stemBusy = stemLoadingIds.has(asset.id) || String(stems.status || '').toLowerCase() === 'running';
    const srtBusy = srtLoadingIds.has(asset.id);
    const audioAnalysis = readAudioAiAnalysis(asset);
    const audioAnalysisBusy = audioAnalysisLoadingIds.has(asset.id);
    const hasLyricsText = Boolean(pickPrompt(asset) || pickLyrics(asset));
    const hasReusableText = Boolean(hasLyricsText || pickStyle(asset));
    const menuStyle = openAudioMenuPosition ? {
      left: `${openAudioMenuPosition.left}px`,
      width: `${openAudioMenuPosition.width}px`,
      maxHeight: `${openAudioMenuPosition.maxHeight}px`,
      ...(openAudioMenuPosition.placement === 'top'
        ? { bottom: `${openAudioMenuPosition.bottom}px` }
        : { top: `${openAudioMenuPosition.top}px` }),
    } : undefined;
    const allowSunoFollowups = canUseSunoApiFollowups(asset);
    const importHint = localOnlyHint(asset, t);
    const extendInfo = extendInfoForAsset(asset);
    const menuNode = open ? (
      <div
        className={`audio-action-menu audio-action-menu-portal placement-${openAudioMenuPosition?.placement || 'bottom'}`}
        role="menu"
        style={menuStyle}
        ref={(node) => {
          if (!node) return;
          const remembered = audioMenuScrollRef.current;
          if (remembered?.key === key && Number(remembered.scrollTop || 0) > 0) {
            node.scrollTop = Number(remembered.scrollTop || 0);
          }
        }}
        onScroll={(event) => { audioMenuScrollRef.current = { key, scrollTop: event.currentTarget.scrollTop || 0 }; }}
        onClick={(event) => event.stopPropagation()}
        onPointerDown={(event) => event.stopPropagation()}
        onWheel={(event) => event.stopPropagation()}
        onTouchMove={(event) => event.stopPropagation()}
      >
        <div className="audio-action-menu-header">
          <strong>{pickTitle(asset)}</strong>
          <small>{operationLabel(asset.operation_type || asset.task_type || asset.operation_label, t)} · {formatDuration(asset.duration_seconds)}</small>
        </div>
        <button role="menuitem" type="button" className={isAssetFavorite(asset) ? 'favorite-action is-favorite' : 'favorite-action'} onClick={() => { closeAudioMenu(); toggleAssetFavorite(asset); }} disabled={favoriteSavingIds.has(asset.id)}><ThumbsUp size={15} fill={isAssetFavorite(asset) ? 'currentColor' : 'none'} /> {isAssetFavorite(asset) ? t('library.actions.removeFavorite', 'Favorit entfernen') : t('library.favoriteOne', 'Favorit')}</button>
        <button role="menuitem" type="button" onClick={() => { closeAudioMenu(); playAsset(asset, playQueue, playIndex, project || activeProject); }} disabled={!isPlayable(asset)}>{isPlayingAsset(asset) ? <Pause size={15} /> : <Play size={15} />} {isPlayingAsset(asset) ? t('player.pause', 'Pause') : t('player.play', 'Abspielen')}</button>
        {extendInfo.isExtended && (
          <button
            role="menuitem"
            type="button"
            onClick={(event) => { closeAudioMenu(); openExtendOriginal(asset, event); }}
            disabled={!extendInfo.originalAsset || !extendInfo.originalProject}
            title={extendInfo.originalAsset ? t('library.actions.openOriginalTitle', 'Original öffnen: {{title}}', { title: pickTitle(extendInfo.originalAsset) }) : (extendInfo.sourceAudioId ? t('library.actions.originalAudioIdMissing', 'Original Audio-ID nicht lokal gefunden: {{audioId}}', { audioId: extendInfo.sourceAudioId }) : t('library.actions.originalMissing', 'Original nicht lokal gefunden'))}
          >
            <ArrowLeft size={15} /> {extendInfo.originalAsset ? t('library.actions.openOriginal', 'Original öffnen') : t('library.actions.originalMissing', 'Original nicht lokal gefunden')}
          </button>
        )}
        {importHint && <div className="audio-action-menu-note">{importHint}</div>}
        {allowSunoFollowups && canRunSunoApiAction(asset, 'Extend') && <button role="menuitem" type="button" onClick={() => { closeAudioMenu(); openAudioOperationModal(asset, 'Extend'); }}><ArrowRight size={15} /> {t('library.actions.configureExtend', 'Extend konfigurieren')}</button>}
        {allowSunoFollowups && canRunSunoApiAction(asset, 'Extend') && <button role="menuitem" type="button" onClick={() => { closeAudioMenu(); prepareAssetExtendInMusic(asset); }}><ArrowRight size={15} /> {t('library.actions.openInMusicGenerator', 'Im Musik-Generator öffnen')}</button>}
        <button role="menuitem" type="button" onClick={() => { closeAudioMenu(); reuseAssetPrompt(asset); }} disabled={!hasReusableText}><SparklesIconFallback /> {t('library.actions.reuse', 'Wiederverwenden')}</button>
        {canRunSunoApiAction(asset, 'Cover Song') && <button role="menuitem" type="button" onClick={() => { closeAudioMenu(); runAction(asset, 'Cover Song'); }}><MusicActionIcon /> {t('library.actions.generateCoverSong', 'Cover Song generieren')}</button>}
        <button role="menuitem" type="button" onClick={() => { closeAudioMenu(); openAiCoverModal(asset); }}><MusicActionIcon /> {t('library.actions.generateAiCover', 'KI-Coverbild generieren')}</button>
        <button role="menuitem" type="button" onClick={() => { closeAudioMenu(); openCoverReplaceModal(asset); }}><Edit3 size={15} /> {t('library.actions.replaceUploadCover', 'Upload-Cover ersetzen')}</button>
        <button role="menuitem" type="button" onClick={() => { closeAudioMenu(); openPictureViewer(asset); }} disabled={isFallbackCoverUrl(pickCover(asset))}><Maximize2 size={15} /> {t('library.actions.viewCoverLarge', 'Cover groß anzeigen')}</button>
        <button role="menuitem" type="button" onClick={() => { closeAudioMenu(); downloadCoverImage(asset); }} disabled={isFallbackCoverUrl(pickCover(asset))}><Download size={15} /> {t('library.actions.downloadCover', 'Cover herunterladen')}</button>
        {canRunSunoApiAction(asset, 'Add Vocals') && <button role="menuitem" type="button" onClick={() => { closeAudioMenu(); runAction(asset, 'Add Vocals'); }}><MusicActionIcon /> {t('library.actions.addVocals', 'Add Vocals')}</button>}
        {canRunSunoApiAction(asset, 'Add Instrumental') && <button role="menuitem" type="button" onClick={() => { closeAudioMenu(); runAction(asset, 'Add Instrumental'); }}><MusicActionIcon /> {t('library.actions.addInstrumental', 'Add Instrumental')}</button>}
        <button role="menuitem" type="button" onClick={() => { closeAudioMenu(); generateSrt(asset); }} disabled={srtBusy}><FileText size={15} /> {srtBusy ? t('library.bulk.srtRunning', 'SRT läuft…') : t('library.bulk.createSrt', 'SRT erzeugen')}</button>
        <button role="menuitem" type="button" onClick={() => { closeAudioMenu(); generateAssetStems(asset); }} disabled={stemBusy || !isAudioLocal(asset)}><Headphones size={15} /> {stemBusy ? t('library.bulk.stemsRunning', 'Stems laufen…') : stems.available ? t('library.actions.regenerateStems', 'Stems neu erzeugen') : t('library.bulk.createStems', 'Stems erzeugen')}</button>
        {stems.available && <button role="menuitem" type="button" onClick={() => { closeAudioMenu(); openStemPreview(asset); }}><Headphones size={15} /> {t('library.actions.playStems', 'Stems abspielen')}</button>}
        <button role="menuitem" type="button" onClick={() => { closeAudioMenu(); generateLibraryAiTags(asset, Boolean(readLibraryAiTags(asset))); }}><Tag size={15} /> {readLibraryAiTags(asset) ? t('library.actions.regenerateAiTags', 'KI-Tags neu erzeugen') : t('library.actions.generateAiTags', 'KI-Tags erzeugen')}</button>
        <button role="menuitem" type="button" onClick={() => { closeAudioMenu(); generateAudioAiAnalysis(asset, Boolean(audioAnalysis)); }} disabled={audioAnalysisBusy || !isAudioLocal(asset)}><FileText size={15} /> {audioAnalysisBusy ? t('library.actions.audioAnalysisRunning', 'Audioanalyse läuft…') : audioAnalysis ? t('library.actions.regenerateAudioAnalysis', 'Audioanalyse neu erstellen') : t('library.actions.startAudioAnalysis', 'Audioanalyse starten')}</button>
        {audioAnalysis && <button role="menuitem" type="button" onClick={() => { closeAudioMenu(); openAudioAiAnalysisReport(asset); }} disabled={audioAnalysisBusy}><FileText size={15} /> {t('library.actions.openAudioAnalysisReport', 'Audioanalyse-Report öffnen')}</button>}
        <button role="menuitem" type="button" onClick={() => { closeAudioMenu(); convertAssetToWav(asset, { download: true }); }} disabled={wavBusy || !canConvertAssetToWav(asset)}><Download size={15} /> {wavBusy ? t('library.actions.converting', 'Konvertiere…') : t('library.actions.convertToWav', 'Convert to WAV')}</button>
        {wav.available && <a role="menuitem" className="button" href={api.archive.wavDownloadUrl(asset.id)} onClick={closeAudioMenu}><Download size={15} /> {t('library.actions.downloadWav', 'WAV herunterladen')}</a>}
        {hasAssetVideo(asset) && <button role="menuitem" type="button" onClick={(event) => { event.preventDefault(); event.stopPropagation(); closeAudioMenu(); void openVideoModal(asset); }}><Film size={15} /> {t('library.video.open', 'MP4 ansehen')}</button>}
        {hasAssetVideo(asset) && latestAssetVideo(asset)?.id && <a role="menuitem" className="button" href={api.archive.videoDownloadUrl(asset.id, latestAssetVideo(asset).id)} onClick={closeAudioMenu}><Download size={15} /> {t('library.video.downloadMp4', 'MP4 herunterladen')}</a>}
        <button role="menuitem" type="button" onClick={() => { closeAudioMenu(); setTimestampAsset(asset); }}><Clock3 size={15} /> {t('library.timestamped.title', 'Timestamped Lyrics')}</button>
        <button role="menuitem" type="button" onClick={() => { closeAudioMenu(); openWorkflowWizard(asset); }}><FileText size={15} /> {t('library.workflow.audioWizard', 'Audio-Wizard')}</button>
        <button role="menuitem" type="button" onClick={() => { closeAudioMenu(); onOpenDaw?.(asset); }}><Scissors size={15} /> {t('library.actions.openInMiniDaw', 'In Mini-DAW öffnen')}</button>
        <button role="menuitem" type="button" onClick={() => { closeAudioMenu(); setPlaylistAsset(asset); }}><Plus size={15} /> {t('nav.playlists', 'Playlists')}</button>
        <button role="menuitem" type="button" onClick={(event) => openLyricsEditor(asset, event)}><Edit3 size={15} /> {t('library.actions.editLyrics', 'Songtext bearbeiten')}</button>
        <button role="menuitem" type="button" onClick={() => { closeAudioMenu(); saveAssetLyricsToArchive(asset); }} disabled={!hasLyricsText}><FileText size={15} /> {t('library.actions.saveLyrics', 'Songtext speichern')}</button>
        <button role="menuitem" type="button" onClick={() => { closeAudioMenu(); copyAssetInfo(asset); }}><Copy size={15} /> {t('library.actions.copyTrackData', 'Trackdaten kopieren')}</button>
        <button role="menuitem" type="button" onClick={() => { closeAudioMenu(); renameAsset(asset); }}><Edit3 size={15} /> {t('library.actions.renameTitle', 'Titel ändern')}</button>
        <a role="menuitem" className="button" href={api.archive.assetBundleUrl(asset.id)} onClick={closeAudioMenu}><Download size={15} /> {t('library.actions.audioPackageZip', 'Audio-Paket ZIP')}</a>
        <a role="menuitem" className="button" href={api.archive.downloadUrl(asset.id)} onClick={closeAudioMenu}><Download size={15} /> {t('library.actions.downloadAudio', 'Audio herunterladen')}</a>
        <button role="menuitem" type="button" onClick={() => { closeAudioMenu(); setActionAsset(asset); }}><MoreHorizontal size={15} /> {t('library.actions.moreActions', 'Weitere Aktionen')}</button>
        <button role="menuitem" type="button" className="danger" onClick={() => { closeAudioMenu(); deleteAsset(asset); }}><Trash2 size={15} /> {t('library.actions.moveToTrash', 'In Papierkorb')}</button>
      </div>
    ) : null;
    return (
      <div className={`audio-action-menu-shell ${compact ? 'compact' : ''} ${open ? 'is-open' : ''}`} onClick={(event) => event.stopPropagation()} onPointerDown={(event) => event.stopPropagation()}>
        <button
          type="button"
          className={`audio-action-trigger ${compact ? 'compact' : ''}`}
          aria-haspopup="menu"
          aria-expanded={open}
          title={t('library.actions.assetActionsTitle', '{{title}} Aktionen', { title: pickTitle(asset) })}
          onClick={(event) => toggleAudioMenu(event, asset)}
        >
          <MoreHorizontal size={compact ? 16 : 18} />
          {!compact && <span>{label}</span>}
        </button>
        {open && typeof document !== 'undefined' ? createPortal(menuNode, document.body) : null}
      </div>
    );
  }

  function SparklesIconFallback() {
    return <Star size={15} />;
  }

  function MusicActionIcon() {
    return <ListMusic size={15} />;
  }

  function PromptLyricsCard({ asset }) {
    if (!asset) return null;
    const text = pickPrompt(asset) || pickLyrics(asset) || '';
    const manualOverride = asset?.metadata_json?.lyrics_manual_override;
    return (
      <div className="meta-card wide prompt-lyrics-card">
        <div className="row between align-start prompt-lyrics-head">
          <div>
            <h4>{t('library.promptLyrics.title', 'Prompt / Lyrics')}</h4>
            <small className="muted">{t('library.promptLyrics.sourceOfTruth', 'Source of Truth für Wiederverwenden und neue SRT-Erzeugungen')}</small>
          </div>
          <div className="button-row compact prompt-lyrics-actions">
            <button type="button" onClick={async (event) => { event.stopPropagation(); await copyToClipboard(text); notify(t('library.messages.textCopied', 'Text kopiert.'), 'success'); }} disabled={!text}><Copy size={14} /> {t('common.copy', 'Kopieren')}</button>
            <button type="button" className="primary" onClick={(event) => openLyricsEditor(asset, event)}><Edit3 size={14} /> {t('stylesPage.edit', 'Bearbeiten')}</button>
          </div>
        </div>
        {manualOverride?.enabled && (
          <p className="status cached prompt-lyrics-override-note">{t('library.promptLyrics.manuallyCorrected', 'Manuell korrigiert')} · {formatDate(manualOverride.updated_at)}</p>
        )}
        <pre className="keyboard-scroll-region" onWheel={(event) => event.stopPropagation()} onTouchMove={(event) => event.stopPropagation()}>{text || '—'}</pre>
        <div className="button-row wrap">
          <button type="button" onClick={(event) => { event.stopPropagation(); saveAssetLyricsToArchive(asset); }} disabled={!text}>{t('library.promptLyrics.saveUnderLyrics', 'Unter Songtexte speichern')}</button>
          <button type="button" onClick={(event) => openLyricsEditor(asset, event)}><Edit3 size={14} /> {t('library.promptLyrics.correctForSrt', 'Für SRT korrigieren')}</button>
        </div>
      </div>
    );
  }

  function VideoPlayerModal() {
    const asset = videoModal.asset;
    const videos = videoModal.videos || [];
    const first = videos[0] || latestAssetVideo(asset);
    const playUrl = first?.id ? videoPlaybackUrl(asset, first) : '';
    const downloadUrl = first?.id ? videoDownloadUrl(asset, first) : '';
    const firstIsLocal = videoIsLocallyPlayable(first);
    return (
      <Modal open={Boolean(asset)} title={asset ? t('library.video.titleForAsset', 'MP4-Video: {{title}}', { title: pickTitle(asset) }) : t('library.video.title', 'MP4-Video')} onClose={closeVideoModal} wide>
        {asset && <div className="stack video-player-modal">
          <p className="muted">audio_assets.id {asset.id} · Audio-ID {asset.audio_id || '—'} · {videos.length || Number(asset.video_count || 0)} MP4</p>
          {videoModal.loading && <p className="muted">{t('common.loading', 'Lädt…')}</p>}
          {videoModal.error && <p className="warning-text">{videoModal.error}</p>}
          {!videoModal.loading && !videos.length && <p className="warning-text">{t('library.video.noneStored', 'Für diese Variante ist noch keine MP4-Datei gespeichert.')}</p>}
          {first?.id && (
            <>
              {!firstIsLocal && <p className="warning-text">{t('library.video.remoteOnly', 'Dieses MP4 ist noch nicht lokal gesichert. Der Player versucht den Remote-Link; sichere das Video lokal, solange die SunoAPI-URL noch gültig ist.')}</p>}
              <video
                key={`${asset.id}-${first.id}-${playUrl}`}
                className="library-video-player"
                src={playUrl}
                controls
                preload="metadata"
                playsInline
                onError={() => setVideoModal((current) => ({
                  ...current,
                  error: t('library.video.playbackError', 'MP4 konnte nicht geladen werden. Prüfe, ob die Datei lokal existiert oder sichere den Remote-Link erneut.'),
                }))}
              />
              <div className="button-row wrap">
                {downloadUrl && <a className="button primary" href={downloadUrl}><Download size={15} /> {t('library.video.downloadMp4', 'MP4 herunterladen')}</a>}
                {playUrl && <a className="button" href={playUrl} target="_blank" rel="noopener noreferrer"><ExternalLink size={15} /> {t('library.video.openDirect', 'Direkt öffnen')}</a>}
                <button type="button" onClick={() => cacheVideoFromModal(asset, first)} disabled={videoModal.loading || !first?.source_url}><Download size={15} /> {t('library.video.cacheLocal', 'MP4 lokal sichern')}</button>
              </div>
            </>
          )}
          {videos.length > 1 && <div className="stack compact">
            {videos.map((video, index) => {
              const itemPlayUrl = videoPlaybackUrl(asset, video);
              const itemDownloadUrl = videoDownloadUrl(asset, video);
              return <div key={video.id} className="meta-card wide">
                <strong>MP4 {index + 1}</strong>
                <p className="muted">{formatDate(video.created_at)} · {video.status || 'cached'} · {video.filename || video.public_url || video.source_url}</p>
                <div className="button-row wrap">
                  {itemPlayUrl && <a className="button" href={itemPlayUrl} target="_blank" rel="noopener noreferrer"><ExternalLink size={14} /> {t('library.video.openDirect', 'Direkt öffnen')}</a>}
                  {itemDownloadUrl && <a className="button" href={itemDownloadUrl}><Download size={14} /> MP4</a>}
                  <button type="button" onClick={() => cacheVideoFromModal(asset, video)} disabled={videoModal.loading || !video?.source_url}>{t('library.video.cacheLocalShort', 'lokal sichern')}</button>
                </div>
              </div>;
            })}
          </div>}
        </div>}
      </Modal>
    );
  }

  function AudioOperationModal() {
    const asset = audioOperationModal.asset;
    const typeName = audioOperationModal.type;
    const isExtend = typeName === 'Extend';
    const isCoverSong = typeName === 'Cover Song';
    const title = asset ? pickTitle(asset) : '';
    return (
      <Modal open={Boolean(asset && typeName)} title={asset ? t('library.audioOperation.configureForTitle', '{{type}} konfigurieren: {{title}}', { type: typeName, title }) : t('library.audioOperation.configure', '{{type}} konfigurieren', { type: typeName || t('library.actionModal.title', 'Aktion') })} onClose={closeAudioOperationModal} wide>
        {asset && (
          <div className="stack audio-operation-modal">
            <div className="meta-card wide">
              <strong>{title}</strong>
              <p className="muted">songs.id: {songDatabaseId(asset) ?? '—'} · audio_assets.id: {asset.id || '—'} · {t('library.audioOperation.duration', 'Dauer')}: {formatDuration(asset.duration_seconds)} · Audio-ID: {asset.audio_id || '—'}</p>
              {isCoverSong && <p className="warning-text">{t('library.audioOperation.coverSongUrlWarning', 'Cover Song benötigt eine wiederverwendbare Audio-URL. Bei rein lokal importierten Audios muss zuerst eine extern erreichbare Quelle vorhanden sein.')}</p>}
            </div>
            <div className="form-grid two">
              <label>{t('common.title', 'Titel')}
                <input value={audioOperationForm.title} onChange={(event) => setAudioOperationForm((state) => ({ ...state, title: event.target.value }))} disabled={audioOperationBusy} />
              </label>
              <label>{t('music.fields.model', 'Modell')}
                <select value={audioOperationForm.model} onChange={(event) => setAudioOperationForm((state) => ({ ...state, model: event.target.value }))} disabled={audioOperationBusy}>
                  {sunoModelOptions.map((model) => <option key={model} value={model}>{model}</option>)}
                </select>
              </label>
              {isExtend && (
                <label>{t('library.audioOperation.extendFromSecond', 'Extend ab Sekunde')}
                  <div className="button-row nowrap">
                    <input type="number" min="1" step="0.1" value={audioOperationForm.continueAt} onChange={(event) => setAudioOperationForm((state) => ({ ...state, continueAt: event.target.value }))} disabled={audioOperationBusy || continueAtAnalysisBusy} />
                    <button type="button" onClick={analyzeAudioOperationContinueAt} disabled={audioOperationBusy || continueAtAnalysisBusy}>{continueAtAnalysisBusy ? t('library.audioOperation.analyzing', 'Analysiere…') : t('library.audioOperation.detectAutomatically', 'Automatisch ermitteln')}</button>
                  </div>
                </label>
              )}
              {isCoverSong && (
                <>
                  <label className="checkbox-row"><input type="checkbox" checked={Boolean(audioOperationForm.customMode)} onChange={(event) => setAudioOperationForm((state) => ({ ...state, customMode: event.target.checked }))} disabled={audioOperationBusy} /> Custom Mode</label>
                  <label className="checkbox-row"><input type="checkbox" checked={Boolean(audioOperationForm.instrumental)} onChange={(event) => setAudioOperationForm((state) => ({ ...state, instrumental: event.target.checked }))} disabled={audioOperationBusy} /> Instrumental</label>
                </>
              )}
            </div>
            <label>Style / Tags
              <textarea rows={3} value={audioOperationForm.style} onChange={(event) => setAudioOperationForm((state) => ({ ...state, style: event.target.value }))} disabled={audioOperationBusy} placeholder={t('library.audioOperation.stylePlaceholder', 'Style, Genre, Stimmung, Instrumentierung')} />
            </label>
            <label>{isExtend ? t('library.audioOperation.extendPromptLabel', 'Erweiterter Songtext / Prompt ab dieser Stelle') : t('library.audioOperation.coverPromptLabel', 'Songtext / Prompt für Cover Song')}
              <textarea className="lyrics-canvas" rows={12} value={audioOperationForm.prompt} onChange={(event) => setAudioOperationForm((state) => ({ ...state, prompt: event.target.value }))} disabled={audioOperationBusy} placeholder={isExtend ? t('library.audioOperation.extendPromptPlaceholder', 'Hier den Teil eintragen, der ab der Extend-Position fortgesetzt werden soll.') : t('library.audioOperation.coverPromptPlaceholder', 'Hier Songtext oder Prompt für den Cover Song eintragen.')} />
            </label>
            <label>{t('music.fields.negativeTagsOptional', 'Negative Tags optional')}
              <input value={audioOperationForm.negative_tags} onChange={(event) => setAudioOperationForm((state) => ({ ...state, negative_tags: event.target.value }))} disabled={audioOperationBusy} placeholder={t('library.audioOperation.negativePlaceholder', 'z. B. offbeat, low quality')} />
            </label>
            <div className="button-row wrap right">
              <button type="button" onClick={closeAudioOperationModal} disabled={audioOperationBusy}>{t('common.cancel', 'Abbrechen')}</button>
              <button className="primary" type="button" onClick={submitAudioOperation} disabled={audioOperationBusy}>{audioOperationBusy ? t('library.audioOperation.starting', 'Starte…') : t('music.actions.startOperation', '{{operation}} starten', { operation: typeName })}</button>
            </div>
          </div>
        )}
      </Modal>
    );
  }

  // WICHTIG: Diese Cover-Modals duerfen keine lokalen React-Komponenten namens
  // AiCoverModal oder CoverReplaceModal sein. Lokale Komponenten, die
  // innerhalb von LibraryPage definiert und als JSX-Komponententyp gerendert
  // werden, bekommen bei jedem State-Update eine neue Identitaet. Das remountet
  // das Modal, Textfelder verlieren nach jedem Buchstaben den Fokus und
  // File-Uploads werden scheinbar nicht uebernommen. Deshalb bewusst als
  // Render-Funktionen aufrufen: {renderAiCoverModal()} / {renderCoverReplaceModal()}.
  function renderAiCoverModal() {
    const asset = aiCoverAsset;
    const referenceName = aiCoverForm.referenceFile?.name || '';
    return (
      <Modal open={Boolean(asset)} title={asset ? t('library.cover.aiTitleForAsset', 'KI-Coverbild generieren: {{title}}', { title: pickTitle(asset) }) : t('library.actions.generateAiCover', 'KI-Coverbild generieren')} onClose={closeAiCoverModal} wide>
        {asset && (
          <div className="stack ai-cover-modal">
            <p className="muted">{t('library.cover.aiText', 'Erstellt ein professionelleres Titel-Cover aus Titel, Prompt/Lyrics und Style/Tags dieses Songs. Optional kannst du Zusatzanweisungen wie --note und ein Referenzbild wie --ref mitgeben.')}</p>
            <label>{t('music.fields.model', 'Modell')}
              <select value={aiCoverForm.model} onChange={(event) => setAiCoverForm((state) => ({ ...state, model: event.target.value }))}>
                <option value="pro">{t('library.cover.modelPro', 'pro · bester Allrounder')}</option>
                <option value="max">{t('library.cover.modelMax', 'max · höchste Detailtreue')}</option>
                <option value="flex">{t('library.cover.modelFlex', 'flex · Typografie stärker')}</option>
                <option value="klein">{t('library.cover.modelSmall', 'klein · schneller/günstiger')}</option>
                <option value="schnell">{t('library.cover.modelFast', 'schnell · Testmodell')}</option>
              </select>
            </label>
            <label>{t('library.cover.extraInstructionsOptional', 'Zusatzanweisungen optional')}
              <textarea rows={4} placeholder={t('library.cover.extraPlaceholder', 'z. B. winterstimmung, schnee')} value={aiCoverForm.note} onKeyDown={(event) => event.stopPropagation()} onKeyUp={(event) => event.stopPropagation()} onChange={(event) => setAiCoverForm((state) => ({ ...state, note: event.target.value }))} />
            </label>
            <label>{t('library.cover.referenceOptional', 'Referenzbild optional')}
              <input type="file" accept="image/*,.jpg,.jpeg,.png,.webp,.gif,.avif" onClick={(event) => event.stopPropagation()} onChange={handleAiCoverReferenceFileChange} />
            </label>
            {referenceName && <p className="muted">{t('library.cover.referenceApplied', 'Referenz übernommen: {{name}}', { name: referenceName })}</p>}
            <div className="button-row wrap">
              <button type="button" onClick={closeAiCoverModal} disabled={aiCoverBusy}>{t('common.cancel', 'Abbrechen')}</button>
              <button className="primary" type="button" onClick={submitAiCover} disabled={aiCoverBusy}>{aiCoverBusy ? t('library.cover.creating', 'Erstellt…') : t('library.cover.generateCover', 'Cover generieren')}</button>
            </div>
          </div>
        )}
      </Modal>
    );
  }

  function renderCoverReplaceModal() {
    const asset = coverReplaceAsset;
    const currentCover = asset ? pickCover(asset) : '/static/favicon.ico';
    const previewCover = coverReplacePreviewUrl || currentCover || '/static/favicon.ico';
    const fileName = coverReplaceFile?.name || '';
    return (
      <Modal open={Boolean(asset)} title={asset ? t('library.cover.replaceTitleForAsset', 'Upload-Cover ersetzen: {{title}}', { title: pickTitle(asset) }) : t('library.actions.replaceUploadCover', 'Upload-Cover ersetzen')} onClose={closeCoverReplaceModal} wide>
        {asset && (
          <div className="stack cover-replace-modal">
            <div className="cover-replace-preview">
              <img src={previewCover} alt={t('library.cover.previewAlt', 'Cover Vorschau')} onError={handleCoverImageError} />
              <div>
                <strong>{pickTitle(asset)}</strong>
                <p className="muted">{t('library.cover.replaceText', 'Das hochgeladene Bild ersetzt das Cover dieses Tracks und wird lokal unter dem Cover-Speicher abgelegt.')}</p>
                {fileName && <small className="status cached">{t('library.cover.newFile', 'Neue Datei: {{name}}', { name: fileName })}</small>}
              </div>
            </div>
            <label>{t('library.cover.coverFile', 'Cover-Datei')}
              <input
                key={asset.id}
                type="file"
                accept="image/*,.jpg,.jpeg,.png,.webp,.gif,.avif"
                onChange={(event) => setCoverReplaceFile(event.target.files?.[0] || null)}
                disabled={coverReplaceBusy}
              />
            </label>
            <div className="button-row wrap right">
              <button type="button" onClick={closeCoverReplaceModal} disabled={coverReplaceBusy}>{t('common.cancel', 'Abbrechen')}</button>
              <button className="primary" type="button" onClick={submitCoverReplace} disabled={coverReplaceBusy || !coverReplaceFile}>{coverReplaceBusy ? t('library.cover.saving', 'Speichere…') : t('library.cover.saveUploadCover', 'Upload-Cover speichern')}</button>
            </div>
          </div>
        )}
      </Modal>
    );
  }

  function renderPictureViewerModal() {
    const asset = pictureViewerAsset;
    const coverUrl = asset ? pickCover(asset) : '';
    const zoomLabel = `${Math.round(pictureViewerZoom * 100)}%`;
    return (
      <Modal
        open={Boolean(asset)}
        title={asset ? t('library.cover.viewTitleForAsset', 'Cover anzeigen: {{title}}', { title: pickTitle(asset) }) : t('library.cover.viewTitle', 'Cover anzeigen')}
        onClose={closePictureViewer}
        wide
        cardClassName={`picture-viewer-modal ${pictureViewerMaximized ? 'is-maximized' : ''}`}
        contentClassName="picture-viewer-modal-content"
      >
        {asset && (
          <div className="stack picture-viewer-shell">
            <div className="picture-viewer-toolbar">
              <button type="button" onClick={() => changePictureViewerZoom(-0.25)} disabled={pictureViewerZoom <= 0.25}><ZoomOut size={15} /> {t('library.cover.smaller', 'Kleiner')}</button>
              <span className="status cached">{zoomLabel}</span>
              <button type="button" onClick={() => changePictureViewerZoom(0.25)} disabled={pictureViewerZoom >= 4}><ZoomIn size={15} /> {t('library.cover.larger', 'Größer')}</button>
              <button type="button" onClick={() => setPictureViewerZoom(1)}>100%</button>
              <button type="button" onClick={() => setPictureViewerMaximized((value) => !value)}>{pictureViewerMaximized ? <Minimize2 size={15} /> : <Maximize2 size={15} />} {pictureViewerMaximized ? t('library.cover.normal', 'Normal') : t('library.cover.maximize', 'Maximieren')}</button>
              <button type="button" onClick={() => downloadCoverImage(asset)}><Download size={15} /> {t('library.actions.downloadCover', 'Herunterladen')}</button>
              <a className="button" href={coverUrl} target="_blank" rel="noopener noreferrer"><ExternalLink size={15} /> {t('library.cover.openImage', 'Bild öffnen')}</a>
            </div>
            <div className="picture-viewer-stage keyboard-scroll-region" onWheel={(event) => event.stopPropagation()} onTouchMove={(event) => event.stopPropagation()}>
              <img
                src={coverUrl}
                alt={`Cover ${pickTitle(asset)}`}
                style={{ transform: `scale(${pictureViewerZoom})` }}
                onError={handleCoverImageError}
              />
            </div>
          </div>
        )}
      </Modal>
    );
  }

  function LyricsEditorModal() {
    const asset = lyricsEditorAsset;
    const charCount = String(lyricsEditorDraft || '').length;
    const lineCount = String(lyricsEditorDraft || '').split(/\n/).length;
    return (
      <Modal open={Boolean(asset)} title={asset ? t('library.promptLyrics.editTitleForAsset', 'Prompt/Lyrics bearbeiten: {{title}}', { title: pickTitle(asset) }) : t('library.promptLyrics.editTitle', 'Prompt/Lyrics bearbeiten')} onClose={closeLyricsEditor} wide>
        {asset && (
          <div className="stack lyrics-edit-modal">
            <div className="lyrics-edit-context">
              <p className="muted">
                {t('library.promptLyrics.editorHint', 'Korrigiere hier den gespeicherten Songtext, wenn Suno Teile wie Wiederholungen in Klammern ausgelassen hat. Der gespeicherte Text wird danach in Song und AudioAsset-Metadaten aktualisiert.')}
              </p>
              <p className="warning-text">
                {t('library.promptLyrics.srtRegenerateHint', 'Bereits vorhandene SRT-Dateien werden nur geändert, wenn du „Speichern & SRT neu erzeugen“ nutzt.')}
              </p>
            </div>
            <label className="wide lyrics-edit-label">
              <span>{t('library.promptLyrics.canvas', 'Canvas')}</span>
              <textarea
                className="lyrics-canvas lyrics-edit-canvas"
                value={lyricsEditorDraft}
                onChange={(event) => setLyricsEditorDraft(event.target.value)}
                spellCheck="false"
                placeholder={'[Verse 1]\nDiese Welt, (diese Welt), Diese Welt!'}
                disabled={lyricsEditorBusy}
              />
            </label>
            <div className="lyrics-edit-footer">
              <span className="muted">{t('library.promptLyrics.editorCounts', '{{lines}} Zeilen · {{chars}} Zeichen', { lines: lineCount, chars: charCount })}</span>
              <div className="button-row wrap right">
                <button type="button" onClick={async () => { await copyToClipboard(lyricsEditorDraft); notify(t('library.messages.canvasCopied', 'Canvas kopiert.'), 'success'); }} disabled={!lyricsEditorDraft || lyricsEditorBusy}>{t('common.copy', 'Kopieren')}</button>
                <button type="button" onClick={closeLyricsEditor} disabled={lyricsEditorBusy}>{t('common.cancel', 'Abbrechen')}</button>
                <button type="button" className="primary" onClick={() => saveLyricsEditor({ regenerateSrt: false })} disabled={lyricsEditorBusy || !String(lyricsEditorDraft || '').trim()}>
                  {lyricsEditorBusy ? t('common.saving', 'Speichere…') : t('common.save', 'Speichern')}
                </button>
                <button type="button" className="primary strong" onClick={() => saveLyricsEditor({ regenerateSrt: true })} disabled={lyricsEditorBusy || !String(lyricsEditorDraft || '').trim()}>
                  {lyricsEditorBusy ? t('library.promptLyrics.working', 'Arbeite…') : t('library.promptLyrics.saveAndRegenerateSrt', 'Speichern & SRT neu erzeugen')}
                </button>
              </div>
            </div>
          </div>
        )}
      </Modal>
    );
  }

  async function copyAssetInfo(asset) {
    const text = [
      `${t('common.title', 'Titel')}: ${pickTitle(asset)}`,
      `songs.id: ${songDatabaseId(asset) ?? '—'}`,
      `audio_assets.id: ${asset.id || '—'}`,
      `Audio-ID: ${asset.audio_id || '—'}`,
      `Task-ID: ${asset.suno_task_id || asset.task_id || '—'}`,
      `${t('library.detail.voice', 'Stimme')}: ${voiceLabelForAsset(asset) || '—'}`,
      `URL: ${asset.public_url || asset.source_url || '—'}`,
      `${t('library.meta.model', 'Modell')}: ${pickModel(asset) || '—'}`,
      `Style: ${pickStyle(asset) || '—'}`,
      `${t('library.generationOptions.title', 'Optionen')}:
${generationOptionsText(asset)}`,
      `Prompt/Lyrics: ${pickPrompt(asset) || pickLyrics(asset) || '—'}`
    ].join('\n');
    await copyToClipboard(text);
    notify(t('library.messages.trackDataCopied', 'Trackdaten kopiert.'), 'success');
  }

  function toggleSelected(assetId) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(assetId)) next.delete(assetId); else next.add(assetId);
      return next;
    });
  }

  function projectSelectableAssetIds(project) {
    return (project?.assets || []).filter((asset) => asset?.id).map((asset) => asset.id);
  }

  function isProjectSelectionComplete(project) {
    const ids = projectSelectableAssetIds(project);
    return Boolean(ids.length) && ids.every((id) => selectedIds.has(id));
  }

  function toggleProjectSelected(project) {
    const ids = projectSelectableAssetIds(project);
    if (!ids.length) return;
    setSelectedIds((current) => {
      const next = new Set(current);
      const allSelected = ids.every((id) => next.has(id));
      ids.forEach((id) => {
        if (allSelected) next.delete(id); else next.add(id);
      });
      return next;
    });
  }

  async function deleteSelected(project) {
    if (!selectedIds.size) return;
    const ids = [...selectedIds];
    if (!confirm(t('library.messages.deleteSelectedConfirm', '{{count}} ausgewählte Audiodateien in den Papierkorb verschieben?', { count: ids.length }))) return;
    const payload = { items: ids.map((id) => ({ type: 'audio', id })), delete_files: false };
    const result = api.library.bulkDeleteContent
      ? await api.library.bulkDeleteContent(payload)
      : { deleted: await Promise.all(ids.map(async (id) => { await api.library.deleteContent('audio', id); return { id }; })) };
    const deletedIds = Array.isArray(result?.deleted) && result.deleted.length ? result.deleted.map((item) => item.id) : ids;
    stopPlaybackForDeletedAssets(deletedIds);
    hideDeletedAssetsLocally(deletedIds);
    notify(t('library.messages.selectedMovedToTrash', '{{count}} ausgewählte Audio(s) wurden in den Papierkorb verschoben.', { count: deletedIds.length }), 'success');
    onTrashChanged?.();
    setSelectedIds(new Set());
    await reloadAfterLibraryMutation();
  }

  async function generateSelectedSrt() {
    const rows = selectedAssets.filter((asset) => asset?.id);
    if (!rows.length) return notify(t('library.messages.noSelectedSrtRows', 'Keine ausgewählten Varianten für SRT-Erzeugung gefunden.'), 'error');
    if (!confirm(t('library.messages.bulkSrtConfirm', 'SRT für {{count}} ausgewählte Variante(n) erzeugen?\n\nDer Sammellauf wird im Hintergrund gestartet und ist im Status-Frontend als aktiver Task sichtbar.', { count: rows.length }))) return;
    const ids = rows.map((asset) => asset.id);
    setBulkActionBusy('srt');
    setSrtLoadingIds((current) => new Set([...current, ...ids]));
    try {
      const result = await api.archive.bulkGenerateSrt(ids, { force: true });
      notify(t('library.messages.bulkSrtStarted', 'SRT-Sammellauf gestartet: Task #{{task}} · {{count}} Variante(n).', { task: result?.task_local_id || '—', count: rows.length }), 'success');
      await onReload?.();
      window.setTimeout(() => onReload?.(), 1200);
    } catch (err) {
      notify(err?.message || t('library.messages.bulkSrtFailed', 'SRT-Sammellauf konnte nicht gestartet werden.'), 'error');
    } finally {
      setBulkActionBusy('');
      setSrtLoadingIds((current) => {
        const next = new Set(current);
        ids.forEach((id) => next.delete(id));
        return next;
      });
    }
  }

  async function generateSelectedStems() {
    const allRows = selectedAssets.filter((asset) => asset?.id);
    const rows = allRows.filter(isAudioLocal);
    const skipped = allRows.length - rows.length;
    if (!rows.length) return notify(t('library.messages.noSelectedLocalStems', 'Keine lokal gespeicherten Audios in der Auswahl für Stem-Erzeugung gefunden.'), 'error');
    if (!confirm(t('library.messages.bulkStemsConfirm', 'Stems für {{count}} lokale ausgewählte Variante(n) erzeugen?{{skipped}}\n\nDer Sammellauf wird im Hintergrund gestartet und ist im Status-Frontend als aktiver Task sichtbar.', { count: rows.length, skipped: skipped ? t('library.messages.bulkStemsSkipped', '\n\n{{count}} nicht lokale Variante(n) werden übersprungen.', { count: skipped }) : '' }))) return;
    const ids = rows.map((asset) => asset.id);
    setBulkActionBusy('stems');
    setStemLoadingIds((current) => new Set([...current, ...ids]));
    try {
      const result = await api.archive.bulkGenerateStems(ids);
      notify(t('library.messages.bulkStemsStarted', 'Stem-Sammellauf gestartet: Task #{{task}} · {{count}} Variante(n){{skipped}}.', { task: result?.task_local_id || '—', count: rows.length, skipped: skipped ? t('library.messages.bulkSkippedSuffix', ' · {{count}} übersprungen', { count: skipped }) : '' }), 'success');
      await onReload?.();
      window.setTimeout(() => onReload?.(), 1200);
    } catch (err) {
      notify(err?.message || t('library.messages.bulkStemsFailed', 'Stem-Sammellauf konnte nicht gestartet werden.'), 'error');
    } finally {
      setBulkActionBusy('');
      setStemLoadingIds((current) => {
        const next = new Set(current);
        ids.forEach((id) => next.delete(id));
        return next;
      });
    }
  }

  async function generateSelectedAiTags() {
    const rows = selectedAssets.filter((asset) => asset?.id);
    if (!rows.length) return notify(t('library.messages.noSelectedAiTags', 'Keine ausgewählten Varianten für KI-Tags gefunden.'), 'error');
    if (!confirm(t('library.messages.bulkAiTagsConfirm', 'KI-Tags für {{count}} ausgewählte Variante(n) erzeugen?\n\nDer Sammellauf wird im Hintergrund gestartet und ist im Status-Frontend sichtbar.', { count: rows.length }))) return;
    const ids = rows.map((asset) => asset.id);
    setBulkActionBusy('ai-tags');
    try {
      const result = await api.archive.bulkGenerateAiTags(ids, { force: false });
      notify(t('library.messages.bulkAiTagsStarted', 'KI-Tagging gestartet: Task #{{task}} · {{count}} Variante(n).', { task: result?.task_local_id || '—', count: rows.length }), 'success');
      await onReload?.();
      window.setTimeout(() => onReload?.(), 1200);
    } catch (err) {
      notify(err?.message || t('library.messages.bulkAiTagsFailed', 'KI-Tagging konnte nicht gestartet werden.'), 'error');
    } finally {
      setBulkActionBusy('');
    }
  }

  async function convertSelectedToWav() {
    const allRows = selectedAssets.filter((asset) => asset?.id);
    const rows = allRows.filter(canConvertAssetToWav);
    const skipped = allRows.length - rows.length;
    if (!rows.length) return notify(t('library.messages.noConvertibleSelected', 'Keine konvertierbaren Audios in der Auswahl gefunden.'), 'error');
    if (!confirm(t('library.messages.bulkWavConfirm', 'WAV für {{count}} ausgewählte Variante(n) erzeugen?{{skipped}}\n\nDie Originaldateien bleiben unverändert.', { count: rows.length, skipped: skipped ? t('library.messages.bulkWavSkipped', '\n\n{{count}} Variante(n) ohne lokale Datei oder Audio-URL werden übersprungen.', { count: skipped }) : '' }))) return;
    const ids = rows.map((asset) => asset.id);
    setBulkActionBusy('wav');
    setWavLoadingIds((current) => new Set([...current, ...ids]));
    try {
      for (const asset of rows) {
        await api.archive.convertToWav(asset.id, { force: false });
      }
      notify(t('library.messages.bulkWavDone', 'WAV-Konvertierung abgeschlossen: {{count}} Variante(n){{skipped}}.', { count: rows.length, skipped: skipped ? t('library.messages.bulkSkippedSuffix', ' · {{count}} übersprungen', { count: skipped }) : '' }), 'success');
      await onReload?.();
    } catch (err) {
      notify(err?.message || t('library.messages.bulkWavFailed', 'WAV-Konvertierung der Auswahl fehlgeschlagen.'), 'error');
    } finally {
      setBulkActionBusy('');
      setWavLoadingIds((current) => {
        const next = new Set(current);
        ids.forEach((id) => next.delete(id));
        return next;
      });
    }
  }

  async function handleManualAudioImport(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    const audioFile = formData.get('audio');
    const title = String(formData.get('title') || '').trim();
    if (!audioFile || typeof audioFile === 'string' || !audioFile.size) {
      return notify(t('library.messages.selectAudioFile', 'Bitte eine Audiodatei auswählen.'), 'error');
    }
    if (!title) {
      return notify(t('library.messages.importTitleRequired', 'Bitte einen Titel für den Import angeben.'), 'error');
    }
      setManualImportBusy(true);
    try {
      const result = await api.archive.importManualAudio(formData);
      notify(result?.message || t('library.messages.audioImported', 'Audio wurde importiert.'), 'success');
      setManualImportOpen(false);
      form.reset();
      await onReload?.();
      if (result?.project_id || result?.audio_asset_id) {
        const importedProject = projects.find((project) => String(project.id) === String(result.project_id)
          || String(project.id) === `project-${result.project_id}`
          || project.assets.some((asset) => String(asset.id) === String(result.audio_asset_id)));
        if (importedProject) openProjectDetails(importedProject);
        window.setTimeout(() => document.querySelector(`[data-react-asset-row="${CSS.escape(String(result.audio_asset_id || ''))}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 250);
      }
    } catch (err) {
      notify(err?.message || t('library.messages.audioImportFailed', 'Audio-Import fehlgeschlagen.'), 'error');
    } finally {
      setManualImportBusy(false);
    }
  }

  function ManualAudioImportModal() {
    return (
      <Modal open={manualImportOpen} title={t('library.manualImport.title', 'Audio manuell erfassen')} onClose={() => !manualImportBusy && setManualImportOpen(false)} wide>
        <form className="form-grid manual-audio-import-form" onSubmit={handleManualAudioImport}>
          <label className="wide">{t('library.manualImport.audioFile', 'Audiodatei')}
            <input name="audio" type="file" accept="audio/*,.mp3,.wav,.m4a,.aac,.ogg,.flac" required />
          </label>
          <label>{t('common.title', 'Titel')}
            <input name="title" placeholder={t('library.manualImport.titlePlaceholder', 'z. B. Kalte Hände')} required />
          </label>
          <label>{t('library.manualImport.projectNameOptional', 'Projektname optional')}
            <input name="project_title" placeholder={t('library.manualImport.projectPlaceholder', 'leer = Titel')} />
          </label>
          <label>{t('library.manualImport.language', 'Sprache')}
            <select name="language" defaultValue="de">
              <option value="de">{t('language.label', 'Deutsch')}</option>
              <option value="en">English</option>
              <option value="auto">Auto</option>
            </select>
          </label>
          <label>{t('library.manualImport.coverOptional', 'Cover optional')}
            <input name="cover" type="file" accept="image/*,.jpg,.jpeg,.png,.webp,.gif,.avif" />
          </label>
          <label className="wide">Songtext / Lyrics
            <textarea name="lyrics" rows={10} placeholder={t('library.manualImport.lyricsPlaceholder', 'Songtext einfügen. Dieser Text wird später für SRT als Source of Truth verwendet.')} />
          </label>
          <label className="wide">Style
            <textarea name="style" rows={4} placeholder={t('library.manualImport.stylePlaceholder', 'z. B. German emotional boom bap, male rap vocals, dark piano...')} />
          </label>
          <label className="wide">{t('library.manualImport.promptOptional', 'Prompt / Beschreibung optional')}
            <textarea name="prompt" rows={4} placeholder={t('library.manualImport.promptPlaceholder', 'Optionaler Prompt. Falls leer, wird der Songtext auch als Prompt gespeichert.')} />
          </label>
          <label className="wide">{t('library.manualImport.notesOptional', 'Notizen optional')}
            <textarea name="notes" rows={3} placeholder={t('library.manualImport.notesPlaceholder', 'Interne Notizen zum Import.')} />
          </label>
          <div className="wide manual-import-hint">
            <strong>{t('library.manualImport.fullSongTitle', 'Import als vollwertiger Library-Song')}</strong>
            <p className="muted">{t('library.manualImport.fullSongText', 'Die Datei wird unter dem Audio-Storage gespeichert und als normales AudioAsset mit Song, Projekt, Lyrics, Style und Metadaten angelegt. Danach funktionieren Player, SRT-Erzeugung, Editor, ZIP-Export und Einzelinhalte wie bei Suno-generierten Songs.')}</p>
          </div>
          <div className="wide button-row wrap right">
            <button type="button" onClick={() => setManualImportOpen(false)} disabled={manualImportBusy}>{t('common.cancel', 'Abbrechen')}</button>
            <button className="primary" type="submit" disabled={manualImportBusy}>{manualImportBusy ? t('library.manualImport.importing', 'Importiere…') : t('library.actions.importAudio', 'Audio importieren')}</button>
          </div>
        </form>
      </Modal>
    );
  }

  function LibraryPaginationControls({ embedded = false } = {}) {
    return (
      <div className={`library-pagination-bar ${embedded ? 'embedded-pagination' : 'panel slim-panel'}`}>
        <div className="library-pagination-left">
          <div className="button-row wrap view-mode-switcher">
            <button type="button" className={libraryViewMode === 'list' ? 'active' : ''} onClick={() => setLibraryViewMode('list')}><ResponsiveLabel full={t('library.views.list', 'Listenansicht')} short={t('library.views.listShort', 'Liste')} /></button>
            <button type="button" className={libraryViewMode === 'flat-list' ? 'active' : ''} onClick={() => setLibraryViewMode('flat-list')}><ResponsiveLabel full={t('library.views.flatList', 'Titelliste')} short={t('library.views.flatListShort', 'Titel')} /></button>
            <button type="button" className={libraryViewMode === 'gallery' ? 'active' : ''} onClick={() => setLibraryViewMode('gallery')}><ResponsiveLabel full={t('library.views.gallery', 'Cover-Ansicht')} short={t('library.views.galleryShort', 'Cover')} /></button>
          </div>
          <div className="library-count-pill library-count-summary" title={t('library.statsTitle', '{{groups}} Songgruppen · {{variants}} Varianten · {{playable}} abspielbar', { groups: libraryStats.groups, variants: libraryStats.variants, playable: libraryStats.playable })}>
            <span><strong>{libraryStats.groups}</strong><small>{t('library.stats.groups', 'Songgruppen')}</small></span>
            <span><strong>{libraryStats.variants}</strong><small>{t('library.stats.variants', 'Varianten')}</small></span>
            <span><strong>{libraryStats.playable}</strong><small>{t('library.stats.playable', 'abspielbar')}</small></span>
            {localFilter === 'favorites' && <span><strong>{libraryStats.favorites}</strong><small>{t('library.favorites', 'Favoriten')}</small></span>}
          </div>
        </div>
        <div className="pagination-controls elegant-controls">
          {libraryViewMode === 'gallery' && (
            <div className="button-row compact gallery-view-toggles" aria-label={t('library.galleryModeAria', 'Coveransicht Modus')}>
              <button type="button" className={libraryGalleryMode === 'simple' ? 'active' : ''} onClick={() => setLibraryGalleryMode('simple')}><ResponsiveLabel full={t('library.modes.simple', 'Einfach')} short={t('library.modes.simpleShort', 'Einfach')} /></button>
              <button type="button" className={libraryGalleryMode === 'advanced' ? 'active' : ''} onClick={() => setLibraryGalleryMode('advanced')}><ResponsiveLabel full={t('library.modes.advanced', 'Erweitert')} short={t('library.modes.advancedShort', 'Erw.')} /></button>
            </div>
          )}
          {libraryViewMode === 'flat-list' && (
            <div className="button-row compact gallery-view-toggles" aria-label={t('library.flatListModeAria', 'Titelliste Modus')}>
              <button type="button" className={libraryFlatListMode === 'simple' ? 'active' : ''} onClick={() => setLibraryFlatListMode('simple')}><ResponsiveLabel full={t('library.modes.simple', 'Einfach')} short={t('library.modes.simpleShort', 'Einfach')} /></button>
              <button type="button" className={libraryFlatListMode === 'advanced' ? 'active' : ''} onClick={() => setLibraryFlatListMode('advanced')}><ResponsiveLabel full={t('library.modes.advanced', 'Erweitert')} short={t('library.modes.advancedShort', 'Erw.')} /></button>
            </div>
          )}
          {libraryViewMode === 'flat-list' && (
            <div className="asset-flat-size-controls" aria-label={t('library.flatListSizeAria', 'Titelliste Spaltengröße')}>
              <button type="button" onClick={() => setLibraryFlatListScale((value) => Math.max(0, value - 1))} disabled={libraryFlatListScale <= 0} title={t('library.flatListCompact', 'Titelliste kompakter anzeigen')}>−</button>
              <span><ResponsiveLabel full={flatListScaleLabel} short={flatListScaleShortLabel} /></span>
              <button type="button" onClick={() => setLibraryFlatListScale((value) => Math.min(2, value + 1))} disabled={libraryFlatListScale >= 2} title={t('library.flatListWide', 'Titelliste breiter anzeigen')}>+</button>
            </div>
          )}
          {libraryViewMode === 'gallery' && libraryGalleryMode === 'simple' && (
            <label className="gallery-density-select elegant-select" title={t('library.tilesPerRow', 'Kacheln pro Reihe')}>
              <span>Grid</span>
              <select value={libraryGalleryColumns} onChange={(event) => setLibraryGalleryColumns(event.target.value)} aria-label={t('library.tilesPerRow', 'Kacheln pro Reihe')}>
                <option value="3">3</option>
                <option value="5">5</option>
                <option value="8">8</option>
                <option value="10">10</option>
              </select>
            </label>
          )}
          <label className="page-size-select elegant-select" title={t('library.pageSize', 'Anzahl anzeigen')}>
            <span><ResponsiveLabel full={t('library.count', 'Anzahl')} short={t('library.countShort', 'Anz.')} /></span>
            <select value={libraryPageSize} onChange={(event) => setLibraryPageSize(event.target.value)} aria-label={t('library.pageSize', 'Anzahl anzeigen')}>
              <option value="25">25</option>
              <option value="50">50</option>
              <option value="100">100</option>
              <option value="all">{t('library.allLower', 'alle')}</option>
            </select>
          </label>
          {libraryPageSize !== 'all' && (
            <div className="library-page-nav">
              <button type="button" disabled={safeLibraryPage <= 1} onClick={() => setLibraryPage((value) => Math.max(1, value - 1))} aria-label={t('library.previousPage', 'Vorherige Seite')}>←</button>
              <span><ResponsiveLabel full={t('library.pageStatus', 'Seite {{page}} / {{total}}', { page: safeLibraryPage, total: libraryTotalPages })} short={t('library.pageStatusShort', '{{page}}/{{total}}', { page: safeLibraryPage, total: libraryTotalPages })} /></span>
              <button type="button" disabled={safeLibraryPage >= libraryTotalPages} onClick={() => setLibraryPage((value) => Math.min(libraryTotalPages, value + 1))} aria-label={t('library.nextPage', 'Nächste Seite')}>→</button>
            </div>
          )}
        </div>
      </div>
    );
  }

  function openGalleryAssetDetails(project, asset, event = null) {
    if (!project?.id) return;
    openProjectDetails(project, event);
    if (asset?.id) {
      window.setTimeout(() => document.querySelector(`[data-react-asset-row="${CSS.escape(String(asset.id))}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 150);
    }
  }

  function extendInfoForAsset(asset) {
    const sourceAudioId = extendSourceAudioId(asset);
    const originalAsset = sourceAudioId ? assetByAudioId.get(String(sourceAudioId)) : null;
    const usableOriginalAsset = originalAsset && String(originalAsset.id) !== String(asset?.id) ? originalAsset : null;
    return {
      isExtended: isExtendedAsset(asset),
      sourceAudioId,
      originalAsset: usableOriginalAsset,
      originalProject: usableOriginalAsset ? projectByAssetId.get(String(usableOriginalAsset.id)) : null,
    };
  }

  function openExtendOriginal(asset, event = null) {
    event?.preventDefault?.();
    event?.stopPropagation?.();
    const info = extendInfoForAsset(asset);
    if (!info.originalAsset || !info.originalProject) return;
    openGalleryAssetDetails(info.originalProject, info.originalAsset);
  }

  function preferredGalleryAsset(project) {
    if (!project) return null;
    return currentAssetForProject(project)
      || project.assets?.find((asset) => asset.is_final)
      || project.assets?.find((asset) => asset.is_favorite)
      || project.playable?.[0]
      || project.assets?.[0]
      || null;
  }

  function galleryDisplayCover(project) {
    const asset = preferredGalleryAsset(project);
    return asset ? pickCover(asset) : project?.cover || '/static/favicon.ico';
  }

  function galleryDisplayCoverForGroup(rows = []) {
    const activeProject = rows.find((project) => currentAssetForProject(project));
    return galleryDisplayCover(activeProject || rows[0]);
  }

  function AssetGalleryTile({ item }) {
    const { project, asset, label } = item;
    const projectQueue = visibleGalleryPlayableQueue();
    const queueIndex = Math.max(0, projectQueue.findIndex((row) => String(row.id) === String(asset.id)));
    const active = isCurrentAsset(asset);
    return (
      <article key={`asset-${asset.id}`} className={`library-gallery-tile ${active ? 'is-playing-row' : ''} ${selectedIds.has(asset.id) ? 'is-selected' : ''}`} title={`${pickTitle(asset)} · ${label}`}>
        <div className="gallery-single-cover-wrap">
          <label className="gallery-select-checkbox" title={t('library.selectAsset', '{{title}} auswählen', { title: pickTitle(asset) })} onPointerDown={(event) => event.stopPropagation()} onClick={(event) => event.stopPropagation()}>
            <input type="checkbox" checked={selectedIds.has(asset.id)} onChange={() => toggleSelected(asset.id)} aria-label={t('library.selectAsset', '{{title}} auswählen', { title: pickTitle(asset) })} />
          </label>
          <button className="gallery-single-cover" type="button" onClick={() => playAsset(asset, projectQueue, queueIndex)} title={isPlayingAsset(asset) ? t('player.pause', 'Pause') : t('player.play', 'Abspielen')}>
            <img src={pickCover(asset)} alt={pickTitle(asset)} onError={handleCoverImageError} />
            <span className="cover-play">{isPlayingAsset(asset) ? <Pause size={18} /> : <Play size={18} fill="currentColor" />}</span>
          </button>
          <button
            className="cover-details-overlay"
            type="button"
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => { event.preventDefault(); event.stopPropagation(); openGalleryAssetDetails(project, asset); }}
            title={t('library.openSongDetails', 'Songdetails öffnen')}
          >{t('library.details', 'Details')}</button>
          <div className="gallery-audio-menu-anchor">
            <AudioActionMenu asset={asset} compact label="" playQueue={projectQueue} playIndex={queueIndex} project={project} />
          </div>
        </div>
        <div className="gallery-tile-caption">
          <button type="button" onClick={() => openGalleryAssetDetails(project, asset)}>{pickTitle(asset)}</button>
          <small>{label} · {formatDuration(asset.duration_seconds)}</small>
        </div>
        <div className="gallery-tile-actions">
          <button type="button" onClick={() => playAsset(asset, projectQueue, queueIndex)}>{isPlayingAsset(asset) ? t('player.pause', 'Pause') : t('player.play', 'Play')}</button>
          <button type="button" onClick={() => openWorkflowWizard(asset)}>Wizard</button>
          <AudioActionMenu asset={asset} compact label="" dropUp playQueue={projectQueue} playIndex={queueIndex} project={project} />
        </div>
      </article>
    );
  }

  function AssetFlatListRow({ item }) {
    const { project, asset, label } = item;
    const projectQueue = visibleGalleryPlayableQueue();
    const queueIndex = Math.max(0, projectQueue.findIndex((row) => String(row.id) === String(asset.id)));
    const active = isCurrentAsset(asset);
    const badges = assetContentBadges(asset, srtByAsset);
    const advanced = libraryFlatListMode === 'advanced';
    return (
      <article className={`asset-flat-row is-${libraryFlatListMode} ${active ? 'is-playing-row' : ''} ${selectedIds.has(asset.id) ? 'is-selected' : ''}`} key={`flat-asset-${asset.id}`} data-react-asset-row={asset.id}>
        <label className="asset-flat-select" title={t('library.selectAsset', '{{title}} auswählen', { title: pickTitle(asset) })} onPointerDown={(event) => event.stopPropagation()} onClick={(event) => event.stopPropagation()}>
          <input type="checkbox" checked={selectedIds.has(asset.id)} onChange={() => toggleSelected(asset.id)} aria-label={t('library.selectAsset', '{{title}} auswählen', { title: pickTitle(asset) })} />
        </label>
        <button className={`asset-flat-cover ${active ? 'is-active-cover' : ''}`} type="button" onClick={() => playAsset(asset, projectQueue, queueIndex, project)} disabled={!isPlayable(asset)} title={isPlayingAsset(asset) ? t('player.pause', 'Pause') : t('player.play', 'Abspielen')}>
          <img src={pickCover(asset)} alt={pickTitle(asset)} onError={handleCoverImageError} />
          <span className="cover-play">{isPlayingAsset(asset) ? <Pause size={16} /> : <Play size={16} fill="currentColor" />}</span>
        </button>
        <div className="asset-flat-main">
          <button className="asset-flat-title" type="button" onClick={(event) => openGalleryAssetDetails(project, asset, event)} title={t('library.openSongDetails', 'Songdetails öffnen')}>
            <strong>{pickTitle(asset)}</strong>
            <span>{advanced ? `${project?.title || t('library.noSongGroup', 'Ohne Songgruppe')} · ${label} · ${operationLabel(asset.operation_type || asset.task_type || asset.operation_label, t)}` : `${label} · ${formatDuration(asset.duration_seconds)} · ${storageStatusLabel(asset, t)}`}</span>
          </button>
          {advanced && active && (
            <div className="library-inline-waveform asset-flat-waveform">
              <span>{playbackState?.isPlaying ? t('library.playback.running', 'Läuft') : t('library.playback.ready', 'Bereit')} · {formatDuration(playbackState?.currentTime || 0)} / {formatDuration(playbackState?.duration || asset.duration_seconds)}</span>
              <Waveform asset={asset} compact currentTime={playbackState?.currentTime || 0} durationSeconds={playbackState?.duration || asset.duration_seconds} interactive={false} />
            </div>
          )}
          {advanced && <div className="asset-flat-meta">
            <span>{formatDuration(asset.duration_seconds)}</span>
            <span>{storageStatusLabel(asset, t)}</span>
            <span>audio_assets.id {asset.id}</span>
            {asset.audio_id && <span>Audio-ID {shortId(asset.audio_id, 12)}</span>}
          </div>}
        </div>
        {advanced && <div className="asset-flat-badges">
          {isAssetFavorite(asset) && <span className="status favorite"><ThumbsUp size={14} fill="currentColor" /> {t('library.favorites', 'Favorit')}</span>}
          {isAssetFullyLocal(asset) && <span className="status cached">{fullLocalLabel(t)}</span>}
          {badges.map((badge) => <span key={badge.key} className={`status ${badge.className || 'cached'}`}>{badge.label}</span>)}
        </div>}
        <div className="asset-flat-actions">
          <button type="button" onClick={() => playAsset(asset, projectQueue, queueIndex, project)} disabled={!isPlayable(asset)}>{isPlayingAsset(asset) ? <Pause size={15} /> : <Play size={15} fill="currentColor" />}</button>
          <button type="button" className={isAssetFavorite(asset) ? 'favorite-action is-favorite' : 'favorite-action'} onClick={() => toggleAssetFavorite(asset)} disabled={favoriteSavingIds.has(asset.id)} title={isAssetFavorite(asset) ? t('library.actions.removeFavorite', 'Favorit entfernen') : t('library.actions.saveFavorite', 'Als Favorit speichern')}>
            <ThumbsUp size={15} fill={isAssetFavorite(asset) ? 'currentColor' : 'none'} />
          </button>
          <AudioActionMenu asset={asset} compact label="" dropUp playQueue={projectQueue} playIndex={queueIndex} project={project} />
        </div>
      </article>
    );
  }

  function LibraryFlatListView() {
    return (
      <div className={`asset-flat-list mode-${libraryFlatListMode} scale-${libraryFlatListScale}`}>
        {pagedGalleryAssets.map((item) => <AssetFlatListRow key={`flat-row-${item.asset.id}`} item={item} />)}
      </div>
    );
  }

  function ProjectGalleryCard({ project }) {
    const currentProjectAsset = currentAssetForProject(project);
    const projectActive = Boolean(currentProjectAsset);
    const projectPlaying = isPlayingProject(project);
    const bestAsset = project.assets.find((asset) => asset.is_final) || project.assets.find((asset) => asset.is_favorite) || project.playable[0] || project.assets[0];
    const displayCover = galleryDisplayCover(project);
    const projectSelected = isProjectSelectionComplete(project);
    return (
      <article key={`project-${project.id}`} className={`library-gallery-card ${projectActive ? 'is-playing-row' : ''} ${projectSelected ? 'is-selected' : ''}`}>
        <label className="gallery-select-checkbox project-select-checkbox" title={t('library.selectAllProjectVariants', 'Alle Varianten von {{title}} auswählen', { title: project.title })} onPointerDown={(event) => event.stopPropagation()} onClick={(event) => event.stopPropagation()}>
          <input type="checkbox" checked={projectSelected} onChange={() => toggleProjectSelected(project)} aria-label={t('library.selectAllProjectVariants', 'Alle Varianten von {{title}} auswählen', { title: project.title })} />
        </label>
        <button className="gallery-cover-collage single-cover" type="button" onClick={(event) => openProjectDetails(project, event)} title={t('library.openDetails', 'Details öffnen')}>
          <img src={displayCover || '/static/favicon.ico'} alt={`${project.title} Cover`} />
          <span className="cover-play">{projectPlaying ? <Pause size={18} /> : <Play size={18} fill="currentColor" />}</span>
        </button>
        <button className="gallery-card-title" type="button" onClick={(event) => openProjectDetails(project, event)}>
          <strong>{project.title}</strong>
          <small>{t('library.variantsWithDuration', '{{count}} Varianten · {{duration}}', { count: project.assets.length, duration: formatDuration(project.duration) })}</small>
        </button>
        <p className="muted">{summarizeStyle(pickStyle(bestAsset), 90, t)}</p>
        <div className="project-gallery-asset-actions">
          {project.assets.map((asset, index) => (
            <div className="gallery-asset-menu-pill" key={`gallery-action-${project.id}-${asset.id}`}>
              <span>{index + 1}/{project.assets.length || 1}</span>
              <small>{variantTitle(asset, project)}</small>
              <AudioActionMenu asset={asset} compact label="" dropUp />
            </div>
          ))}
        </div>
        <div className="button-row wrap compact">
          <button type="button" onClick={() => playProject(project)}>{projectPlaying ? t('player.pause', 'Pause') : t('player.play', 'Play')}</button>
          <button type="button" onClick={(event) => openProjectDetails(project, event)}>{t('library.details', 'Details')}</button>
          {bestAsset && <button type="button" onClick={() => openWorkflowWizard(bestAsset)}>Wizard</button>}
        </div>
      </article>
    );
  }

  function LibraryGalleryView() {
    if (libraryGalleryMode === 'simple') {
      return (
        <div className="library-gallery-view simple-gallery-view stack">
          <section className="library-gallery-section">
            <h3>{t('library.gallery.allSongsVariants', 'Alle Songs & Varianten')}</h3>
            <p className="muted">{t('library.gallery.simpleText', 'Kompakte Coverübersicht über alle Varianten. Klick auf das Cover startet die Wiedergabe, Details öffnet die Songdetails.')}</p>
            <div className="library-gallery-grid simple-cover-grid" style={galleryGridStyle}>
              {pagedGalleryAssets.map((item) => AssetGalleryTile({ item }))}
            </div>
          </section>
        </div>
      );
    }
    const recent = pagedProjects;
    const groupedByDay = pagedProjects.reduce((groups, project) => {
      const rawDate = project.created_at || project.sort_at || '';
      const parsedDate = parseBackendDate(rawDate);
      const label = parsedDate ? new Intl.DateTimeFormat('de-DE', { timeZone: 'Europe/Berlin', day: '2-digit', month: '2-digit' }).format(parsedDate) : t('library.noDate', 'Ohne Datum');
      groups[label] = groups[label] || [];
      groups[label].push(project);
      return groups;
    }, {});
    const byYear = pagedProjects.reduce((groups, project) => {
      const rawDate = project.created_at || project.sort_at || '';
      const parsedDate = parseBackendDate(rawDate);
      const year = parsedDate ? new Intl.DateTimeFormat('de-DE', { timeZone: 'Europe/Berlin', year: 'numeric' }).format(parsedDate) : t('library.noYear', 'Ohne Jahr');
      groups[year] = groups[year] || [];
      groups[year].push(project);
      return groups;
    }, {});
    return (
      <div className="library-gallery-view stack">
        <section className="library-gallery-section">
          <h3>{t('library.gallery.creativeMatches', 'Creative Matches')}</h3>
          <p className="muted">{t('library.gallery.matchesText', 'Aktuelle Treffer aus deiner Library, passend zu Suche und Filter.')}</p>
          <div className="library-gallery-grid" style={galleryGridStyle}>
            {recent.map((project) => ProjectGalleryCard({ project }))}
          </div>
        </section>
        <section className="library-gallery-section">
          <h3>{t('library.gallery.uploadsByDay', 'Uploads, gruppiert nach Tag')}</h3>
          <div className="library-gallery-grid grouped-gallery-grid" style={galleryGridStyle}>
            {Object.entries(groupedByDay).map(([label, rows]) => (
              <button className="library-group-card" type="button" key={label} onClick={(event) => rows[0] && openProjectDetails(rows[0], event)}>
                <div className="gallery-cover-collage small single-cover">
                  <img src={galleryDisplayCoverForGroup(rows)} alt="Cover" onError={handleCoverImageError} />
                </div>
                <strong>{label}</strong>
                <small>{t('library.tracks', '{{count}} Tracks', { count: rows.reduce((sum, project) => sum + project.assets.length, 0) })}</small>
              </button>
            ))}
          </div>
        </section>
        <section className="library-gallery-section">
          <h3>{t('library.gallery.byYear', 'Library, gruppiert nach Jahr')}</h3>
          <div className="library-gallery-grid grouped-gallery-grid" style={galleryGridStyle}>
            {Object.entries(byYear).sort(([a], [b]) => String(b).localeCompare(String(a))).map(([label, rows]) => (
              <button className="library-group-card" type="button" key={label} onClick={(event) => rows[0] && openProjectDetails(rows[0], event)}>
                <div className="gallery-cover-collage small single-cover">
                  <img src={galleryDisplayCoverForGroup(rows)} alt="Cover" onError={handleCoverImageError} />
                </div>
                <strong>{label}</strong>
                <small>{t('library.songs', '{{count}} Songs', { count: rows.length })}</small>
              </button>
            ))}
          </div>
        </section>
      </div>
    );
  }

  function SelectedBulkActions() {
    if (!selectedAssets.length) return null;
    const ids = selectedAssets.map((asset) => asset.id).filter(Boolean);
    const localCount = selectedAssets.filter(isAudioLocal).length;
    const wavCount = selectedAssets.filter(canConvertAssetToWav).length;
    const isBusy = Boolean(bulkActionBusy);
    return (
      <div className="selected-bulk-actions" aria-label={t('library.bulk.aria', 'Aktionen für ausgewählte Library-Inhalte')}>
        <span className="selected-bulk-count"><strong>{selectedAssets.length}</strong> {t('library.bulk.selected', 'ausgewählt')}</span>
        <button type="button" className="danger" onClick={() => deleteSelected()} disabled={isBusy}><Trash2 size={15} /> {t('common.delete', 'Löschen')}</button>
        <button type="button" onClick={() => setSelectedPlaylistOpen(true)} disabled={isBusy}><ListMusic size={15} /> {t('library.actions.toPlaylist', 'In Playlist')}</button>
        <button type="button" onClick={generateSelectedSrt} disabled={isBusy}><FileText size={15} /> {bulkActionBusy === 'srt' ? t('library.bulk.srtRunning', 'SRT läuft…') : t('library.bulk.createSrt', 'SRT erzeugen')}</button>
        <button type="button" onClick={generateSelectedStems} disabled={isBusy || !localCount}><Scissors size={15} /> {bulkActionBusy === 'stems' ? t('library.bulk.stemsRunning', 'Stems laufen…') : t('library.bulk.createStems', 'Stems erzeugen')}</button>
        <button type="button" onClick={convertSelectedToWav} disabled={isBusy || !wavCount}><Download size={15} /> {bulkActionBusy === 'wav' ? t('library.bulk.wavRunning', 'WAV läuft…') : t('library.bulk.createWav', 'WAV erzeugen')}</button>
        <button type="button" onClick={generateSelectedAiTags} disabled={isBusy}><Tag size={15} /> {bulkActionBusy === 'ai-tags' ? t('library.bulk.tagsRunning', 'Tags laufen…') : t('library.aiTags.title', 'KI-Tags')}</button>
        {ids.length > 0 && <a className="button" href={api.archive.bulkAssetBundleUrl(ids)}><Download size={15} /> {t('library.bulk.selectionZip', 'Auswahl ZIP')}</a>}
        <button type="button" onClick={() => setSelectedIds(new Set())} disabled={isBusy}>{t('library.bulk.clearSelection', 'Auswahl aufheben')}</button>
      </div>
    );
  }

  if (activeProject) {
    const dossierStats = {
      audioLocal: activeProject.assets.filter(isAudioLocal).length,
      coverLocal: activeProject.assets.filter(isCoverCached).length,
      prompts: activeProject.assets.filter((asset) => pickPrompt(asset) || pickLyrics(asset)).length,
      payloads: activeProject.assets.filter((asset) => asset.metadata_json).length,
      final: activeProject.assets.find((asset) => asset.is_final),
      favorite: activeProject.assets.filter((asset) => asset.is_favorite).length,
    };
    const projectCoverAsset = activeProject.assets.find((asset) => asset.is_final && !isFallbackCoverUrl(pickCover(asset)))
      || activeProject.assets.find((asset) => isAssetFavorite(asset) && !isFallbackCoverUrl(pickCover(asset)))
      || activeProject.playable?.find?.((asset) => !isFallbackCoverUrl(pickCover(asset)))
      || activeProject.assets.find((asset) => !isFallbackCoverUrl(pickCover(asset)))
      || null;
    return (
      <section className={`page stack library-detail-page ${playbackState?.isPlaying ? 'is-playback-stable' : ''}`}>
        <div className="detail-navigation-bar">
          <button className="ghost compact" type="button" onClick={closeProjectDetails}><ArrowLeft size={16} /> {t('library.detail.backToLibrary', 'Zurück zur Library')}</button>
          <div className="detail-navigation-actions">
            <button className="ghost compact" type="button" disabled={!previousProject} onClick={(event) => previousProject && openProjectDetails(previousProject, event)}>← {t('library.detail.previousSong', 'Vorheriger Song')}</button>
            <button className="ghost compact" type="button" disabled={!nextProject} onClick={(event) => nextProject && openProjectDetails(nextProject, event)}>{t('library.detail.nextSong', 'Nächster Song')} →</button>
          </div>
        </div>
        <div className="detail-hero library-hero">
          <button className={`hero-cover-button ${isCurrentProject(activeProject) ? 'is-active-cover' : ''}`} type="button" onClick={() => playProject(activeProject)} title={isPlayingProject(activeProject) ? t('player.pause', 'Pause') : t('library.detail.playBestVersion', 'Beste Version abspielen')}>
            <img src={activeProject.cover || '/static/favicon.ico'} alt="Cover" onError={handleCoverImageError} />
            <span>{isPlayingProject(activeProject) ? <Pause size={18} /> : <Play size={18} fill="currentColor" />}</span>
          </button>
          <div>
            <p className="eyebrow">{t('library.detail.projectSong', 'Projekt / Song')}</p>
            <h1>{activeProject.title}</h1>
            <p className="muted">{t('library.detail.projectMeta', '{{variants}} Varianten · {{operations}} Vorgänge · erstellt {{created}} · aktualisiert {{updated}}', { variants: activeProject.assets.length, operations: activeProject.operations.length, created: formatDate(activeProject.created_at), updated: formatDate(activeProject.updated_at) })}</p>
            <p className="muted">{summarizeStyle(pickStyle(activeProject.assets.find((asset) => pickStyle(asset))), 220, t)}</p>
            {activeProject.assets.some((asset) => voiceLabelForAsset(asset)) && <p className="muted voice-detail-line">{t('library.detail.voice', 'Stimme')}: <strong>{voiceLabelForAsset(activeProject.assets.find((asset) => voiceLabelForAsset(asset)))}</strong></p>}
            <div className="button-row wrap">
              <button className="primary" type="button" onClick={() => playProject(activeProject)}><Headphones size={16} /> {isPlayingProject(activeProject) ? t('player.pause', 'Pause') : t('library.detail.playBestVersion', 'Beste Version abspielen')}</button>
              <button type="button" onClick={() => openPictureViewer(projectCoverAsset)} disabled={!projectCoverAsset}><Maximize2 size={16} /> {t('library.actions.viewCoverLarge', 'Cover groß anzeigen')}</button>
              <button type="button" onClick={() => downloadCoverImage(projectCoverAsset)} disabled={!projectCoverAsset}><Download size={16} /> {t('library.actions.downloadCover', 'Cover herunterladen')}</button>
              <button type="button" onClick={() => { const best = activeProject.assets.find((item) => isAssetFavorite(item)) || activeProject.playable?.[0] || activeProject.assets[0]; if (best) toggleAssetFavorite(best, !isAssetFavorite(best)); }} disabled={!activeProject.assets.length || Boolean(favoriteSavingIds.size)}><ThumbsUp size={16} fill={activeProject.assets.some((item) => isAssetFavorite(item)) ? 'currentColor' : 'none'} /> {activeProject.assets.some((item) => isAssetFavorite(item)) ? t('library.actions.removeFavorite', 'Favorit entfernen') : t('library.actions.saveFavorite', 'Als Favorit speichern')}</button>
              <button type="button" onClick={() => exportProjectJson(activeProject)}>Projekt JSON</button>
              <button type="button" onClick={() => exportProjectText(activeProject)}>TXT Export</button>
              <button type="button" onClick={() => saveProjectLyrics(activeProject)}>{t('library.actions.saveLyrics', 'Songtext speichern')}</button>
              <button type="button" onClick={() => reuseProjectPrompt(activeProject)}>{t('library.actions.reuse', 'Reuse Prompt')}</button>
              <button type="button" onClick={() => generateProjectSrt(activeProject)} disabled={Boolean(bulkActionBusy)}><FileText size={16} /> {bulkActionBusy === 'srt' ? t('library.bulk.srtRunning', 'SRT läuft…') : t('library.detail.createAllSrt', 'Alle SRT erzeugen')}</button>
              <button type="button" onClick={() => generateProjectStems(activeProject)} disabled={Boolean(bulkActionBusy)}><Headphones size={16} /> {bulkActionBusy === 'stems' ? t('library.bulk.stemsRunning', 'Stems laufen…') : t('library.detail.createAllStems', 'Alle Stems erzeugen')}</button>
              <a className="button primary" href={api.archive.bulkAssetBundleUrl(activeProject.assets.map((asset) => asset.id))}><Download size={16} /> {t('library.detail.allAsZip', 'Alle als ZIP')}</a>
              <button type="button" onClick={() => setSelectedIds(new Set(activeProject.assets.map((asset) => asset.id)))}>{t('library.detail.selectAll', 'Alle auswählen')}</button>
              <button type="button" onClick={() => setSelectedIds(new Set())}>{t('library.bulk.clearSelection', 'Auswahl aufheben')}</button>
              <button type="button" onClick={() => openAllVariants(activeProject)}>{t('library.detail.openAllVariants', 'Alle Varianten öffnen')}</button>
              <button type="button" onClick={() => collapseAllVariants(activeProject)}>{t('library.detail.collapseAllVariants', 'Alle Varianten zuklappen')}</button>
              <button className="danger" type="button" onClick={() => deleteSelected(activeProject)} disabled={!selectedIds.size}><Trash2 size={16} /> {t('library.detail.deleteSelection', 'Auswahl löschen')}</button>
            </div>
          </div>
        </div>

        <section className="panel project-dossier-panel">
          <div>
            <p className="eyebrow">{t('library.detail.dossier', 'Projektakte')}</p>
            <h2>{t('library.detail.backupVersions', 'Sicherung & Versionen')}</h2>
            <p className="muted">{t('library.detail.dossierText', 'Alle Varianten, lokalen Dateien und Produktionsdaten dieses Songs auf einen Blick.')}</p>
          </div>
          <div className="live-status-grid dossier-grid">
            <span><strong>{dossierStats.audioLocal}/{activeProject.assets.length}</strong><small>{t('library.localFilter.audioLocal', 'Audio lokal')}</small></span>
            <span><strong>{dossierStats.coverLocal}/{activeProject.assets.length}</strong><small>{t('library.localFilter.coverLocal', 'Cover lokal')}</small></span>
            <span><strong>{dossierStats.prompts}</strong><small>Prompts/Lyrics</small></span>
            <span><strong>{dossierStats.payloads}</strong><small>Payloads</small></span>
            <span><strong>{dossierStats.favorite}</strong><small>{t('library.favorites', 'Favoriten')}</small></span>
            <span><strong>{dossierStats.final ? t('common.yes', 'Ja') : t('common.no', 'Nein')}</strong><small>{t('library.detail.finalMarked', 'Final markiert')}</small></span>
          </div>
        </section>

        {(() => {
          const projectQueue = activeProject.assets.filter(isPlayable).map((asset) => withVariantPlaybackMeta(asset, activeProject));
          return (
            <article className="operation-section" key={`${activeProject.id}-variants`}>
              <header className="operation-header">
                <div>
                  <p className="eyebrow">{t('library.stats.variants', 'Varianten')}</p>
                  <h2>{activeProject.title} · {t('library.detail.variantCount', '{{count}} Variante(n)', { count: activeProject.assets.length })}</h2>
                  <p className="muted">{t('library.detail.operationsCreatedUpdated', '{{operations}} Vorgänge · erstellt {{created}} · zuletzt aktualisiert {{updated}}', { operations: activeProject.operations.length, created: formatDate(activeProject.created_at), updated: formatDate(activeProject.updated_at) })}</p>
                </div>
                <button type="button" onClick={() => onPlay(projectQueue, 0)} disabled={!projectQueue.length}>{t('library.detail.playAllVariants', 'Alle Varianten abspielen')}</button>
              </header>
              <div className="variant-grid compact-variants">
                {activeProject.assets.map((asset, index) => {
                  const playbackAsset = withVariantPlaybackMeta(asset, activeProject);
                  const variantOpen = isVariantAccordionOpen(asset, index);
                  const collapsedSrtLine = !variantOpen ? liveSrtLineForAsset(asset) : null;
                  return (
                    <article className={`variant-card horizontal variant-accordion-card ${variantOpen ? 'is-open' : 'is-collapsed'} ${isCurrentAsset(asset) ? 'is-playing-row' : ''}`} key={asset.id} data-react-asset-row={asset.id}>
                      <label className="select-box"><input type="checkbox" checked={selectedIds.has(asset.id)} onChange={() => toggleSelected(asset.id)} /></label>
                      <div className="variant-cover-column">
                        <button className={`variant-cover-button ${isCurrentAsset(asset) ? 'is-active-cover' : ''}`} type="button" onClick={() => playAsset(playbackAsset, projectQueue, index, activeProject)} disabled={!isPlayable(asset)} title={isPlayingAsset(asset) ? t('player.pause', 'Pause') : t('player.play', 'Abspielen')}>
                          <img src={pickCover(asset)} alt="Cover" onError={handleCoverImageError} />
                          <span>{isPlayingAsset(asset) ? <Pause size={18} /> : <Play size={18} fill="currentColor" />}</span>
                        </button>
                        {hasAssetVideo(asset) && <button type="button" className="primary mp4-watch-button variant-cover-mp4-button" onClick={(event) => openVideoModalFromEvent(event, asset)}><Film size={14} /> {t('library.video.watchMp4Short', 'MP4')}</button>}
                      </div>
                      <div className="variant-body">
                        <button className="variant-accordion-toggle" type="button" onClick={() => toggleVariantAccordion(asset, index)} aria-expanded={variantOpen}>
                          <span className="variant-accordion-title">
                            <span className="variant-accordion-icon">{variantOpen ? <ChevronDown size={17} /> : <ChevronRight size={17} />}</span>
                            <span>
                              <p className="eyebrow">{variantEyebrow(asset, activeProject, t)}</p>
                              <h3>{variantTitle(asset, activeProject)}</h3>
                            </span>
                          </span>
                          <span className="variant-accordion-badges">
                            <span className={`status ${isAssetFullyLocal(asset) ? 'cached' : audioStatusClass(asset)}`}>{storageStatusLabel(asset, t)}</span>
                            {isAssetFavorite(asset) && <span className="status favorite"><ThumbsUp size={13} fill="currentColor" /> {t('library.favoriteOne', 'Favorit')}</span>}
                            {assetContentBadges(asset, srtByAsset).map((badge) => <span key={badge.key} className={`status ${badge.className || 'cached'}`}>{badge.label}</span>)}
                            <span className="muted compact-only">{formatDuration(asset.duration_seconds)}</span>
                          </span>
                        </button>
                        {variantOpen && (
                          <>
                        <p className="muted">{formatDuration(asset.duration_seconds)} · songs.id {songDatabaseId(asset) ?? '—'} · audio_assets.id {asset.id} · Audio-ID {shortId(asset.audio_id, 14)} · Task {shortId(asset.suno_task_id, 14)}{voiceLabelForAsset(asset) ? ` · ${t('library.detail.voice', 'Stimme')} ${voiceLabelForAsset(asset)}` : ''}</p>
                          {isCurrentAsset(asset) && <div className="library-inline-waveform"><span>{playbackState?.isPlaying ? t('library.playback.running', 'Läuft') : t('library.playback.ready', 'Bereit')} · {formatDuration(playbackState?.currentTime || 0)} / {formatDuration(playbackState?.duration || asset.duration_seconds)}</span><Waveform asset={asset} compact currentTime={playbackState?.currentTime || 0} durationSeconds={playbackState?.duration || asset.duration_seconds} interactive={false} /></div>}
                          <div className="button-row wrap">
                            <button type="button" onClick={() => playAsset(playbackAsset, projectQueue, index, activeProject)}>{isPlayingAsset(asset) ? t('player.pause', 'Pause') : t('player.play', 'Abspielen')}</button>
                            <button type="button" className={isAssetFavorite(asset) ? 'favorite-action is-favorite' : 'favorite-action'} onClick={() => toggleAssetFavorite(asset)} disabled={favoriteSavingIds.has(asset.id)}><ThumbsUp size={15} fill={isAssetFavorite(asset) ? 'currentColor' : 'none'} /> {t('library.favorites', 'Favoriten')}</button>
                            <button type="button" className="stable-detail-action-button" onClick={() => setActionAsset(playbackAsset)}><MoreHorizontal size={15} /> {t('library.actionModal.title', 'Aktionen')}</button>
                            <button type="button" onClick={() => openPictureViewer(asset)} disabled={isFallbackCoverUrl(pickCover(asset))}><Maximize2 size={15} /> {t('library.actions.viewCoverLarge', 'Cover groß anzeigen')}</button>
                            <button type="button" onClick={() => downloadCoverImage(asset)} disabled={isFallbackCoverUrl(pickCover(asset))}><Download size={15} /> {t('library.actions.downloadCover', 'Cover')}</button>
                            <button type="button" onClick={() => convertAssetToWav(asset, { download: true })} disabled={wavLoadingIds.has(asset.id) || !canConvertAssetToWav(asset)}><Download size={15} /> {wavLoadingIds.has(asset.id) ? t('library.actions.converting', 'Konvertiere…') : t('library.actions.convertToWav', 'Convert to WAV')}</button>
                            {readAssetWavConversion(asset).available && <a className="button" href={api.archive.wavDownloadUrl(asset.id)}><Download size={15} /> WAV</a>}
                            <button type="button" onClick={() => renameAsset(asset)}><Edit3 size={15} /> {t('common.title', 'Titel')}</button>
                            <button type="button" onClick={() => copyAssetInfo(asset)}><Copy size={15} /> {t('common.copy', 'Kopieren')}</button>
                            <button type="button" onClick={() => reuseAssetPrompt(asset)}>{t('library.actions.reusePrompt', 'Reuse Prompt')}</button>
                            <button type="button" onClick={() => setTimestampAsset(asset)}><Clock3 size={15} /> {t('library.timestamped.title', 'Timestamped Lyrics')}</button>
                            <button type="button" onClick={() => openWorkflowWizard(asset)}><FileText size={15} /> {t('library.workflow.audioWizard', 'Audio-Wizard')}</button>
                            <button type="button" onClick={() => generateSrt(asset)} disabled={srtLoadingIds.has(asset.id)}><FileText size={15} /> {srtLoadingIds.has(asset.id) ? t('library.bulk.srtRunning', 'SRT läuft…') : t('library.bulk.createSrt', 'SRT erzeugen')}</button>
                            <button type="button" onClick={() => generateAssetStems(asset)} disabled={stemLoadingIds.has(asset.id) || !isAudioLocal(asset)}><Headphones size={15} /> {stemLoadingIds.has(asset.id) ? t('library.bulk.stemsRunning', 'Stems laufen…') : t('library.content.stemFiles', 'Stem-Dateien')}</button>
                            <button type="button" onClick={() => generateLibraryAiTags(asset, Boolean(readLibraryAiTags(asset)))}><Tag size={15} /> {t('library.aiTags.title', 'KI-Tags')}</button>
                            <button type="button" onClick={() => onOpenDaw?.(asset)}><Scissors size={15} /> {t('library.actions.openInMiniDaw', 'In Mini-DAW öffnen')}</button>
                            <button type="button" onClick={() => setPlaylistAsset(asset)}><Plus size={15} /> {t('nav.playlists', 'Playlists')}</button>
                            <a className="button primary" href={api.archive.assetBundleUrl(asset.id)}><Download size={15} /> {t('library.actions.audioPackageZip', 'Audio-Paket ZIP')}</a>
                            <a className="button" href={api.archive.downloadUrl(asset.id)}><Download size={15} /> {t('library.actions.downloadAudio', 'Audio herunterladen')}</a>
                          </div>
                          <div className="variant-meta-grid">
                            <div className="meta-card"><div className="row between"><h4>{t('library.meta.database', 'Datenbank')}</h4><button type="button" onClick={async () => { await copyToClipboard(assetDatabaseSummary(asset)); notify(t('library.messages.databaseIdsCopied', 'Datenbank-IDs kopiert.'), 'success'); }}><Copy size={14} /></button></div><p>songs.id: {songDatabaseId(asset) ?? '—'}<br />audio_assets.id: {asset.id}</p></div>
                            <div className="meta-card"><div className="row between"><h4>{t('library.meta.model', 'Modell')}</h4><button type="button" onClick={async () => { await copyToClipboard(pickModel(asset)); notify(t('library.messages.modelCopied', 'Modell kopiert.'), 'success'); }}><Copy size={14} /></button></div><p>{pickModel(asset) || '—'}</p></div>
                            <div className="meta-card"><div className="row between"><h4>Audio-ID</h4><button type="button" onClick={async () => { await copyToClipboard(asset.audio_id); notify(t('library.messages.audioIdCopied', 'Audio-ID kopiert.'), 'success'); }}><Copy size={14} /></button></div><p>{asset.audio_id || '—'}</p></div>
                            <div className="meta-card"><div className="row between"><h4>Task-ID</h4><button type="button" onClick={async () => { await copyToClipboard(asset.suno_task_id || asset.task_id); notify(t('library.messages.taskIdCopied', 'Task-ID kopiert.'), 'success'); }}><Copy size={14} /></button></div><p>{asset.suno_task_id || asset.task_id || '—'}</p></div>
                            <div className="meta-card"><div className="row between"><h4>{t('library.detail.voice', 'Stimme')}</h4><button type="button" disabled={!voiceInfoForAsset(asset)?.id} onClick={async () => { await copyToClipboard(voiceInfoForAsset(asset)?.id || ''); notify(t('library.messages.voiceIdCopied', 'Voice-ID kopiert.'), 'success'); }}><Copy size={14} /></button></div><p>{voiceLabelForAsset(asset) || '—'}</p></div>
                            <GenerationOptionsCard asset={asset} />
                            <div className="meta-card wide"><div className="row between"><h4>Style</h4><button type="button" onClick={async () => { await copyToClipboard(pickStyle(asset)); notify(t('library.messages.styleCopied', 'Style kopiert.'), 'success'); }}><Copy size={14} /></button></div><p>{pickStyle(asset) || '—'}</p></div>
                            <PromptLyricsCard asset={asset} />
                            <LibraryAiTagsCard asset={asset} />
                            <AudioAiAnalysisCard asset={asset} />
                            <StemCard asset={asset} />
                            {hasAssetVideo(asset) && <VideoSummaryCard asset={asset} />}
                            <SrtCard asset={asset} />
                            <AssetContentManager asset={asset} />
                          </div>
                          <details className="tech-details"><summary>{t('library.meta.rawTechnicalData', 'Technische Rohdaten')}</summary><pre className="keyboard-scroll-region" onWheel={(event) => event.stopPropagation()} onTouchMove={(event) => event.stopPropagation()}>{JSON.stringify(asset, null, 2)}</pre></details>
                            </>
                        )}
                        {!variantOpen && (
                          <div className="variant-collapsed-summary">
                            <div className="variant-collapsed-copy">
                              <span className="variant-collapsed-meta">{formatDuration(asset.duration_seconds)} · songs.id {songDatabaseId(asset) ?? '—'} · audio_assets.id {asset.id} · Audio-ID {shortId(asset.audio_id, 12)} · Task {shortId(asset.suno_task_id, 12)}</span>
                              {collapsedSrtLine?.text && (
                                <span className={`variant-collapsed-srt ${collapsedSrtLine.isPlaying ? 'is-live' : ''}`}>
                                  <span>SRT</span>
                                  <strong>{collapsedSrtLine.text}</strong>
                                </span>
                              )}
                            </div>
                            <div className="button-row wrap">
                              <button type="button" onClick={() => playAsset(playbackAsset, projectQueue, index, activeProject)}>{isPlayingAsset(asset) ? t('player.pause', 'Pause') : t('player.play', 'Abspielen')}</button>
                              <button type="button" className={isAssetFavorite(asset) ? 'favorite-action is-favorite' : 'favorite-action'} onClick={() => toggleAssetFavorite(asset)} disabled={favoriteSavingIds.has(asset.id)}><ThumbsUp size={15} fill={isAssetFavorite(asset) ? 'currentColor' : 'none'} /></button>
                              <AudioActionMenu asset={playbackAsset} compact label="" dropUp />
                              <button type="button" onClick={() => toggleVariantAccordion(asset, index)}>{t('library.detail.showDetails', 'Details anzeigen')}</button>
                              <button type="button" onClick={() => openWorkflowWizard(asset)}><FileText size={15} /> Wizard</button>
                              <a className="button primary" href={api.archive.assetBundleUrl(asset.id)}><Download size={15} /> ZIP</a>
                            </div>
                          </div>
                        )}
                      </div>
                    </article>
                  );
                })}
              </div>
            </article>
          );
        })()}

        <AssetWorkflowWizardModal asset={workflowWizardAsset} />
        <ManualAudioImportModal />
        {renderAiCoverModal()}
        {renderCoverReplaceModal()}
        {renderPictureViewerModal()}
        <LyricsEditorModal />
        <SrtEditorModal asset={srtEditorAsset} />
        <StemPreviewModal asset={stemPreviewAsset} />
        <AudioAiAnalysisReportModal />
        <Modal open={Boolean(playlistAsset)} title={t('library.playlist.addTitle', 'Zu Playlist hinzufügen')} onClose={() => setPlaylistAsset(null)}>
          {playlistAsset && <div className="stack">
            <p className="muted">{t('library.playlist.track', 'Track')}: <strong>{pickTitle(playlistAsset)}</strong></p>
            {!playlists.length && <p className="warning-text">{t('library.playlist.noneYet', 'Noch keine Playlist vorhanden. Bitte zuerst im Playlist-Tab eine Playlist erstellen.')}</p>}
            <div className="button-grid">
              {playlists.map((playlist) => <button key={playlist.id} type="button" onClick={() => addToPlaylist(playlistAsset, playlist.id)}>{playlist.name}</button>)}
            </div>
          </div>}
        </Modal>
        <Modal open={Boolean(timestampAsset)} title={timestampAsset ? t('library.timestamped.titleForAsset', 'Timestamped Lyrics: {{title}}', { title: pickTitle(timestampAsset) }) : 'Timestamped Lyrics'} onClose={() => setTimestampAsset(null)}>
          {timestampAsset && <div className="stack">
            <p className="muted">Audio-ID: {timestampAsset.audio_id || '—'} · Task-ID: {timestampAsset.suno_task_id || timestampAsset.task_id || '—'}</p>
            {!readStoredTimestampedLyrics(timestampAsset) && <p className="warning-text">{t('library.timestamped.noneStored', 'Noch keine synchronisierten Lyrics gespeichert. Jetzt über SunoAPI abrufen und im AudioAsset speichern.')}</p>}
            <div className="button-row wrap">
              <button type="button" className="primary" onClick={() => fetchTimestampedLyrics(timestampAsset)} disabled={timestampLoading || !timestampAsset.audio_id}>{timestampLoading ? t('library.timestamped.fetching', 'Rufe ab…') : t('library.timestamped.fetchAndSave', 'Abrufen & speichern')}</button>
              <button type="button" onClick={() => copyTimestampedLyrics(timestampAsset)} disabled={!readStoredTimestampedLyrics(timestampAsset)}>{t('library.timestamped.copyToClipboard', 'In Zwischenablage')}</button>
              <button type="button" onClick={() => downloadTimestampedLyrics(timestampAsset)} disabled={!readStoredTimestampedLyrics(timestampAsset)}><Download size={15} /> {t('common.download', 'Herunterladen')}</button>
            </div>
            <pre className="large-pre keyboard-scroll-region" onWheel={(event) => event.stopPropagation()} onTouchMove={(event) => event.stopPropagation()}>{timestampedLyricsText(timestampAsset) || t('common.noData', 'Noch keine Daten vorhanden.')}</pre>
          </div>}
        </Modal>
        <AudioOperationModal />
        <VideoPlayerModal />
        <ActionModal
          asset={actionAsset}
          onClose={() => setActionAsset(null)}
          onAction={runAction}
          onDelete={deleteAsset}
          onOpenDaw={onOpenDaw}
          onReuse={reuseAssetPrompt}
          onPrepareExtend={prepareAssetExtendInMusic}
          onRename={renameAsset}
          onCopy={copyAssetInfo}
          onSaveLyrics={saveAssetLyricsToArchive}
          onEditLyrics={openLyricsEditor}
          onOpenWizard={openWorkflowWizard}
          onPlaylist={setPlaylistAsset}
          onTimestamp={setTimestampAsset}
          onGenerateSrt={generateSrt}
          onGenerateStems={generateAssetStems}
          onGenerateAudioAnalysis={generateAudioAiAnalysis}
          onGenerateAiTags={generateLibraryAiTags}
          onOpenAudioAnalysisReport={openAudioAiAnalysisReport}
          onOpenAiCover={openAiCoverModal}
          onReplaceCover={openCoverReplaceModal}
          onOpenCoverViewer={openPictureViewer}
          onDownloadCover={downloadCoverImage}
          onToggleFavorite={toggleAssetFavorite}
          isAssetFavorite={isAssetFavorite}
          favoriteSavingIds={favoriteSavingIds}
        />
      </section>
    );
  }

  return (
    <section className="page stack">
      <SectionHeader eyebrow={t('library.eyebrow', 'Library')} title={localFilter === 'favorites' ? t('library.favorites', 'Favoriten') : t('library.title', 'Library')} />
      <div className="library-controls-panel panel slim-panel">
        <div className="library-toolbar">
          <select value={sort} onChange={(event) => setSort(event.target.value)} aria-label={t('library.sortAria', 'Library sortieren')}>
            <option value="newest">{t('library.sort.newest', 'Neueste zuerst')}</option>
            <option value="oldest">{t('library.sort.oldest', 'Älteste zuerst')}</option>
            <option value="updated">{t('library.sort.updated', 'Zuletzt aktualisiert')}</option>
            <option value="title">{t('library.sort.title', 'Titel A-Z')}</option>
            <option value="variants">{t('library.sort.variants', 'Meiste Varianten')}</option>
          </select>
          <select value={localFilter} onChange={(event) => preserveWindowScroll(() => setLocalFilter(event.target.value))} aria-label={t('library.localFilterAria', 'Sicherung und Local-Status filtern')}>
            <option value="all">{t('library.localFilter.all', 'Sicherung: alle')}</option>
            <option value="audio-local">{t('library.localFilter.audioLocal', 'Audio lokal')}</option>
            <option value="cover-local">{t('library.localFilter.coverLocal', 'Cover lokal')}</option>
            <option value="missing-backup">{t('library.localFilter.missingBackup', 'Backup fehlt')}</option>
            <option value="favorites">{t('library.favorites', 'Favoriten')}</option>
          </select>
          <div className="filter-chips library-command-chips">
            {localizedPrimaryTypeFilters.map(([key, label]) => (
              <button key={key} type="button" className={type === key ? 'active' : ''} onClick={() => setType(key)}><Filter size={14} /> <ResponsiveLabel full={label} short={t(`library.typeFiltersShort.${key}`, label)} /></button>
            ))}
            <details className={`library-more-filter chip-select ${localizedSecondaryTypeFilters.some(([key]) => key === type) ? 'active' : ''}`}>
              <summary><Filter size={14} /> <ResponsiveLabel full={t('library.moreFilters', 'Weitere')} short={t('library.moreFiltersShort', 'Mehr')} /> <ChevronDown size={14} /></summary>
              <div className="library-more-filter-menu">
                {localizedSecondaryTypeFilters.map(([key, label]) => (
                  <button key={key} type="button" className={type === key ? 'active' : ''} onClick={(event) => { setType(key); event.currentTarget.closest('details')?.removeAttribute('open'); }}>{label}</button>
                ))}
              </div>
            </details>
            <button type="button" className={localFilter === 'favorites' ? 'active' : ''} onClick={() => preserveWindowScroll(() => setLocalFilter(localFilter === 'favorites' ? 'all' : 'favorites'))}><ThumbsUp size={14} /> {t('library.favorites', 'Favoriten')}</button>
            <span className="library-chip-spacer" aria-hidden="true" />
            <button type="button" onClick={cacheMissingLibraryContent} disabled={contentCacheBusy}>{contentCacheBusy ? t('library.actions.checking', 'Prüfe…') : <ResponsiveLabel full={t('library.actions.checkContent', 'Inhalte prüfen')} short={t('library.actions.checkContentShort', 'Prüfen')} />}</button>
            <button type="button" className="library-refresh-chip" onClick={onReload}><ResponsiveLabel full={t('common.refresh', 'Aktualisieren')} short={t('common.refreshShort', 'Aktual.')} /></button>
          </div>
        </div>
        {SelectedBulkActions()}
        {LibraryPaginationControls({ embedded: true })}
      </div>
      {localFilter === 'favorites' && <div className="panel slim-panel favorites-list-hint"><ThumbsUp size={18} fill="currentColor" /><div><strong>{t('library.favoritesList', 'Favoritenliste')}</strong><small>{t('library.favoritesHint', '{{count}} Songgruppe(n) mit markierten Lieblingsvarianten. Klicke erneut auf den Daumen, um einen Song zu entfernen.', { count: filteredProjects.length })}</small></div></div>}
      {loadError && <div className="panel slim-panel warning-panel"><strong>{t('library.loadFailed', 'Library konnte nicht geladen werden.')}</strong><small>{loadError}</small><button type="button" onClick={onReload}>{t('common.retry', 'Erneut laden')}</button></div>}
      {!loadError && !libraryPaginationTotal && <EmptyState title={t('library.emptyTitle', 'Keine Songs gefunden')} text={t('library.emptyText', 'Passe Suche oder Filter an, oder generiere einen neuen Song.')} />}
      {libraryViewMode === 'gallery' ? LibraryGalleryView() : libraryViewMode === 'flat-list' ? LibraryFlatListView() : (
      <div className="project-list library-project-list">
        {pagedProjects.map((project) => {
          const currentProjectAsset = currentAssetForProject(project);
          const projectActive = Boolean(currentProjectAsset);
          const projectPlaying = isPlayingProject(project);
          const projectQueue = (project.playable.length ? project.playable : project.assets.filter(isPlayable)).map((asset) => withVariantPlaybackMeta(asset, project)).filter(isPlayable);
          return (
            <article className={`project-row suno-row ${projectActive ? 'is-playing-row' : ''}`} key={project.id}>
              <button className={`cover-button ${projectActive ? 'is-active-cover' : ''}`} type="button" onClick={() => playProject(project)} title={projectPlaying ? t('player.pause', 'Pause') : t('library.playDirectly', 'Direkt abspielen')}>
                <img src={project.cover || '/static/favicon.ico'} alt="Cover" onError={handleCoverImageError} />
                <span className="cover-play">{projectPlaying ? <Pause size={18} /> : <Play size={18} fill="currentColor" />}</span>
              </button>
              <div className="project-row-main">
                <button className="title-button" type="button" onClick={(event) => openProjectDetails(project, event)} title={t('library.openDetailPage', 'Detailseite öffnen')}>
                  <strong>{project.title}</strong>
                  <span>{t('library.projectStatsLine', '{{variants}} Varianten · {{operations}} Vorgänge · {{playable}} abspielbar', { variants: project.assets.length, operations: project.operations.length, playable: project.playable.length })}</span>
                  <small>{summarizeStyle(pickStyle(project.assets.find((asset) => pickStyle(asset))), 160, t)}</small>
                </button>
                {projectActive && currentProjectAsset && (
                  <div className="library-inline-waveform project-waveform">
                    <span>{projectPlaying ? t('library.playback.nowPlaying', 'Jetzt läuft') : t('library.playback.ready', 'Bereit')} · {formatDuration(playbackState?.currentTime || 0)} / {formatDuration(playbackState?.duration || currentProjectAsset.duration_seconds)}</span>
                    <Waveform asset={currentProjectAsset} compact currentTime={playbackState?.currentTime || 0} durationSeconds={playbackState?.duration || currentProjectAsset.duration_seconds} interactive={false} />
                  </div>
                )}
                <div className="project-audio-actions-strip" aria-label={t('library.audioQuickActions', 'Audio-Schnellaktionen')}>
                  {project.assets.map((asset, index) => {
                    const queueIndex = Math.max(0, projectQueue.findIndex((row) => String(row.id) === String(asset.id)));
                    return (
	                    <div className={`project-audio-action-pill ${isCurrentAsset(asset) ? 'is-current' : ''} ${selectedIds.has(asset.id) ? 'is-selected' : ''}`} key={`project-action-${project.id}-${asset.id}`}>
	                      <label className="project-audio-select-mini" title={t('library.selectAsset', '{{title}} auswählen', { title: variantTitle(asset, project) })}>
	                        <input type="checkbox" checked={selectedIds.has(asset.id)} onChange={() => toggleSelected(asset.id)} aria-label={t('library.selectAsset', '{{title}} auswählen', { title: variantTitle(asset, project) })} />
	                      </label>
	                      <button type="button" className="project-audio-play-mini" onClick={() => playAsset(asset, projectQueue, queueIndex, project)} title={t('library.playAsset', '{{title}} abspielen', { title: variantTitle(asset, project) })}>
                        {isPlayingAsset(asset) ? <Pause size={13} /> : <Play size={13} fill="currentColor" />}
                      </button>
                      <button type="button" className="project-audio-title-mini" onClick={(event) => openProjectDetails(project, event)} title={variantTitle(asset, project)}>
                        <strong>{index + 1}/{project.assets.length || 1}</strong>
                        <span>{variantTitle(asset, project)}</span>
                      </button>
                      <button type="button" className={isAssetFavorite(asset) ? 'project-audio-favorite-mini is-favorite' : 'project-audio-favorite-mini'} onClick={(event) => { event.stopPropagation(); toggleAssetFavorite(asset); }} disabled={favoriteSavingIds.has(asset.id)} title={isAssetFavorite(asset) ? t('library.actions.removeFavorite', 'Favorit entfernen') : t('library.actions.saveFavorite', 'Als Favorit speichern')}>
                        <ThumbsUp size={13} fill={isAssetFavorite(asset) ? 'currentColor' : 'none'} />
                      </button>
                      <AudioActionMenu asset={asset} compact label="" dropUp />
                    </div>
                  );})}
                </div>
              </div>
              <div className="project-actions">
                <div className="project-badges">
                  <span className="status cached"><ListMusic size={14} /> {formatDuration(project.duration)}</span>
                  {project.assets.some((asset) => isAssetFavorite(asset)) && <span className="status favorite"><ThumbsUp size={14} fill="currentColor" /> {project.assets.filter((asset) => isAssetFavorite(asset)).length === project.assets.length ? t('library.favoriteOne', 'Favorit') : t('library.favoriteCount', '{{count}}/{{total}} Favoriten', { count: project.assets.filter((asset) => isAssetFavorite(asset)).length, total: project.assets.length })}</span>}
                  {isProjectFullyLocal(project) && <span className="status cached">{fullLocalLabel(t)}</span>}
                  {projectContentBadgeLabel(project, (asset) => hasAssetSrt(asset, srtByAsset), 'SRT') && <span className="status cached">{projectContentBadgeLabel(project, (asset) => hasAssetSrt(asset, srtByAsset), 'SRT')}</span>}
                  {projectContentBadgeLabel(project, (asset) => assetContentBadges(asset, srtByAsset).some((badge) => badge.key === 'stems'), 'STEMS') && <span className="status cached">{projectContentBadgeLabel(project, (asset) => assetContentBadges(asset, srtByAsset).some((badge) => badge.key === 'stems'), 'STEMS')}</span>}
                  {projectContentBadgeLabel(project, (asset) => assetContentBadges(asset, srtByAsset).some((badge) => badge.key === 'wav'), 'WAV') && <span className="status cached">{projectContentBadgeLabel(project, (asset) => assetContentBadges(asset, srtByAsset).some((badge) => badge.key === 'wav'), 'WAV')}</span>}
                </div>
                <div className="project-action-buttons">
                  <button type="button" onClick={() => playProject(project)}><Headphones size={16} /> {projectPlaying ? t('player.pause', 'Pause') : t('player.play', 'Abspielen')}</button>
                  <button type="button" onClick={() => onOpenDaw?.(project.playable[0] || project.assets[0])}><Scissors size={16} /> {t('library.actions.openInMiniDaw', 'In Mini-DAW öffnen')}</button>
                </div>
              </div>
            </article>
          );
        })}
      </div>
      )}
      {LibraryPaginationControls()}
      <AssetWorkflowWizardModal asset={workflowWizardAsset} />
      <ManualAudioImportModal />
      {renderAiCoverModal()}
      {renderCoverReplaceModal()}
      {renderPictureViewerModal()}
      <LyricsEditorModal />
      <SrtEditorModal asset={srtEditorAsset} />
      <StemPreviewModal asset={stemPreviewAsset} />
      <AudioAiAnalysisReportModal />
      <Modal open={Boolean(playlistAsset)} title={t('library.playlist.addTitle', 'Zu Playlist hinzufügen')} onClose={() => setPlaylistAsset(null)}>
        {playlistAsset && <div className="stack">
          <p className="muted">{t('library.playlist.track', 'Track')}: <strong>{pickTitle(playlistAsset)}</strong></p>
          {!playlists.length && <p className="warning-text">{t('library.playlist.noneYet', 'Noch keine Playlist vorhanden. Bitte zuerst im Playlist-Tab eine Playlist erstellen.')}</p>}
          <div className="button-grid">
            {playlists.map((playlist) => <button key={playlist.id} type="button" onClick={() => addToPlaylist(playlistAsset, playlist.id)}>{playlist.name}</button>)}
          </div>
        </div>}
      </Modal>
      <Modal open={selectedPlaylistOpen} title={t('library.playlist.addSelectionTitle', 'Auswahl zu Playlist hinzufügen')} onClose={() => setSelectedPlaylistOpen(false)}>
        <div className="stack">
          <p className="muted">{t('library.playlist.selectedTracksAdded', '{{count}} ausgewählte Track(s) werden hinzugefügt.', { count: selectedAssets.length })}</p>
          {!playlists.length && <p className="warning-text">{t('library.playlist.noneYet', 'Noch keine Playlist vorhanden. Bitte zuerst im Playlist-Tab eine Playlist erstellen.')}</p>}
          <div className="button-grid">
            {playlists.map((playlist) => <button key={playlist.id} type="button" onClick={() => addSelectedToPlaylist(playlist.id)}>{playlist.name}</button>)}
          </div>
        </div>
      </Modal>
      <Modal open={Boolean(timestampAsset)} title={timestampAsset ? t('library.timestamped.titleForAsset', 'Timestamped Lyrics: {{title}}', { title: pickTitle(timestampAsset) }) : 'Timestamped Lyrics'} onClose={() => setTimestampAsset(null)}>
        {timestampAsset && <div className="stack">
          <p className="muted">Audio-ID: {timestampAsset.audio_id || '—'} · Task-ID: {timestampAsset.suno_task_id || timestampAsset.task_id || '—'}</p>
          {!readStoredTimestampedLyrics(timestampAsset) && <p className="warning-text">{t('library.timestamped.noneStored', 'Noch keine synchronisierten Lyrics gespeichert. Jetzt über SunoAPI abrufen und im AudioAsset speichern.')}</p>}
          <div className="button-row wrap">
            <button type="button" className="primary" onClick={() => fetchTimestampedLyrics(timestampAsset)} disabled={timestampLoading || !timestampAsset.audio_id}>{timestampLoading ? t('library.timestamped.fetching', 'Rufe ab…') : t('library.timestamped.fetchAndSave', 'Abrufen & speichern')}</button>
            <button type="button" onClick={() => copyTimestampedLyrics(timestampAsset)} disabled={!readStoredTimestampedLyrics(timestampAsset)}>{t('library.timestamped.copyToClipboard', 'In Zwischenablage')}</button>
            <button type="button" onClick={() => downloadTimestampedLyrics(timestampAsset)} disabled={!readStoredTimestampedLyrics(timestampAsset)}><Download size={15} /> {t('common.download', 'Herunterladen')}</button>
          </div>
          <pre className="large-pre keyboard-scroll-region" onWheel={(event) => event.stopPropagation()} onTouchMove={(event) => event.stopPropagation()}>{timestampedLyricsText(timestampAsset) || t('common.noData', 'Noch keine Daten vorhanden.')}</pre>
        </div>}
      </Modal>
      <AudioOperationModal />
      <VideoPlayerModal />
      <ActionModal
        asset={actionAsset}
        onClose={() => setActionAsset(null)}
        onAction={runAction}
        onDelete={deleteAsset}
        onOpenDaw={onOpenDaw}
        onReuse={reuseAssetPrompt}
        onPrepareExtend={prepareAssetExtendInMusic}
        onRename={renameAsset}
        onCopy={copyAssetInfo}
        onSaveLyrics={saveAssetLyricsToArchive}
        onEditLyrics={openLyricsEditor}
        onOpenWizard={openWorkflowWizard}
        onPlaylist={setPlaylistAsset}
        onTimestamp={setTimestampAsset}
        onGenerateSrt={generateSrt}
        onGenerateStems={generateAssetStems}
        onGenerateAudioAnalysis={generateAudioAiAnalysis}
        onGenerateAiTags={generateLibraryAiTags}
        onOpenAudioAnalysisReport={openAudioAiAnalysisReport}
        onOpenAiCover={openAiCoverModal}
        onReplaceCover={openCoverReplaceModal}
        onOpenCoverViewer={openPictureViewer}
        onDownloadCover={downloadCoverImage}
        onOpenVideo={openVideoModal}
        onToggleFavorite={toggleAssetFavorite}
        isAssetFavorite={isAssetFavorite}
        favoriteSavingIds={favoriteSavingIds}
      />
    </section>
  );
}

function ActionModal({ asset, onClose, onAction, onDelete, onOpenDaw, onReuse, onPrepareExtend, onRename, onCopy, onSaveLyrics, onEditLyrics, onOpenWizard, onPlaylist, onTimestamp, onGenerateSrt, onGenerateStems, onGenerateAudioAnalysis, onGenerateAiTags, onOpenAudioAnalysisReport, onOpenAiCover, onReplaceCover, onOpenCoverViewer, onDownloadCover, onOpenVideo, onToggleFavorite, isAssetFavorite = () => false, favoriteSavingIds = new Set() }) {
  const { t } = useI18n();
  const audioAnalysis = readAudioAiAnalysis(asset);
  const aiTags = readLibraryAiTags(asset);
  return (
    <Modal open={Boolean(asset)} title={asset ? t('library.actionModal.titleWithAsset', 'Aktionen: {{title}}', { title: pickTitle(asset) }) : t('library.actionModal.title', 'Aktionen')} onClose={onClose} cardClassName="library-action-modal" contentClassName="library-action-modal-content">
      {asset && <div className="stack">
        <p className="muted">songs.id: {songDatabaseId(asset) ?? '—'} · audio_assets.id: {asset.id || '—'} · Audio-ID: {asset.audio_id || '—'} · Task-ID: {asset.suno_task_id || asset.task_id || '—'}</p>
        {localOnlyHint(asset, t) && <p className="warning-text">{localOnlyHint(asset, t)}</p>}
        <div className="action-grid">
          {canRunSunoApiAction(asset, 'Extend') && <button className="primary" type="button" onClick={() => onAction(asset, 'Extend')}><ArrowRight size={16} /> {t('library.actions.configureExtend', 'Extend konfigurieren')}</button>}
          {canRunSunoApiAction(asset, 'Extend') && <button type="button" onClick={() => { onPrepareExtend?.(asset); onClose?.(); }}><ArrowRight size={16} /> {t('library.actions.openInMusicGenerator', 'Im Generator vorbereiten')}</button>}
          <button type="button" onClick={() => { onReuse?.(asset); onClose?.(); }}><Star size={16} /> {t('library.actions.reuse', 'Wiederverwenden')}</button>
          <button type="button" className={isAssetFavorite(asset) ? 'favorite-action is-favorite' : 'favorite-action'} onClick={() => { onToggleFavorite?.(asset); onClose?.(); }} disabled={favoriteSavingIds.has(asset.id)}><ThumbsUp size={16} fill={isAssetFavorite(asset) ? 'currentColor' : 'none'} /> {isAssetFavorite(asset) ? t('library.actions.removeFavorite', 'Favorit entfernen') : t('library.actions.saveFavorite', 'Als Favorit speichern')}</button>
          {['Cover Song', 'Add Vocals', 'Add Instrumental', 'Persona', 'Cover-Bild'].filter((item) => canRunSunoApiAction(asset, item)).map((item) => <button key={item} type="button" onClick={() => onAction(asset, item)}>{item === 'Cover Song' ? t('library.actions.generateCoverSong', 'Cover Song generieren') : item === 'Cover-Bild' ? t('library.actions.generateSunoCover', 'Suno-Coverbild generieren') : item === 'Add Vocals' ? t('library.actions.addVocals', 'Add Vocals') : item === 'Add Instrumental' ? t('library.actions.addInstrumental', 'Add Instrumental') : item}</button>)}
          <button type="button" onClick={() => { onOpenAiCover?.(asset); onClose?.(); }}>{t('library.actions.generateAiCover', 'KI-Coverbild generieren')}</button>
          <button type="button" onClick={() => { onReplaceCover?.(asset); onClose?.(); }}><Edit3 size={16} /> {t('library.actions.replaceUploadCover', 'Upload-Cover ersetzen')}</button>
          <button type="button" onClick={() => { onOpenCoverViewer?.(asset); onClose?.(); }} disabled={isFallbackCoverUrl(pickCover(asset))}><Maximize2 size={16} /> {t('library.actions.viewCoverLarge', 'Cover groß anzeigen')}</button>
          <button type="button" onClick={() => { onDownloadCover?.(asset); onClose?.(); }} disabled={isFallbackCoverUrl(pickCover(asset))}><Download size={16} /> {t('library.actions.downloadCover', 'Cover herunterladen')}</button>
          {hasAssetVideo(asset) && <button type="button" className="primary mp4-watch-button" onClick={(event) => { event.preventDefault(); event.stopPropagation(); onClose?.(); window.setTimeout(() => onOpenVideo?.(asset), 0); }}><Film size={16} /> {t('library.video.watchMp4', 'MP4 ansehen')}</button>}
          <button type="button" onClick={() => { onGenerateSrt?.(asset); onClose?.(); }}><FileText size={16} /> {t('library.bulk.createSrt', 'SRT erzeugen')}</button>
          <button type="button" onClick={() => { onGenerateStems?.(asset); onClose?.(); }}><Headphones size={16} /> {t('library.bulk.createStems', 'Stems erzeugen')}</button>
          <button type="button" onClick={() => { onGenerateAiTags?.(asset, Boolean(aiTags)); onClose?.(); }}><Tag size={16} /> {aiTags ? t('library.actions.regenerateAiTags', 'KI-Tags neu erzeugen') : t('library.actions.generateAiTags', 'KI-Tags erzeugen')}</button>
          <button type="button" onClick={() => { onGenerateAudioAnalysis?.(asset, Boolean(audioAnalysis)); onClose?.(); }}><FileText size={16} /> {audioAnalysis ? t('library.actions.regenerateAudioAnalysis', 'Audioanalyse neu erstellen') : t('library.actions.startAudioAnalysis', 'Audioanalyse starten')}</button>
          {audioAnalysis && <button type="button" onClick={() => { onOpenAudioAnalysisReport?.(asset); onClose?.(); }}><FileText size={16} /> {t('library.actions.openAudioAnalysisReport', 'Audioanalyse-Report öffnen')}</button>}
          <button type="button" onClick={() => { onTimestamp?.(asset); onClose?.(); }}><Clock3 size={16} /> {t('library.timestamped.title', 'Timestamped Lyrics')}</button>
          <button type="button" onClick={() => { onOpenWizard?.(asset); onClose?.(); }}><FileText size={16} /> {t('library.workflow.audioWizard', 'Audio-Wizard')}</button>
          <button type="button" onClick={() => { onPlaylist?.(asset); onClose?.(); }}><Plus size={16} /> {t('library.actions.toPlaylist', 'Zur Playlist')}</button>
          <button type="button" onClick={(event) => { onEditLyrics?.(asset, event); onClose?.(); }}><Edit3 size={16} /> {t('library.actions.editLyrics', 'Songtext bearbeiten')}</button>
          <button type="button" onClick={() => { onOpenDaw?.(asset); onClose?.(); }}><Scissors size={16} /> {t('library.actions.openInMiniDaw', 'In Mini-DAW öffnen')}</button>
          <button type="button" onClick={() => { onCopy?.(asset); onClose?.(); }}><Copy size={16} /> {t('library.actions.copyTrackData', 'Trackdaten kopieren')}</button>
          <button type="button" onClick={() => { onSaveLyrics?.(asset); onClose?.(); }}><FileText size={16} /> {t('library.actions.saveLyrics', 'Songtext speichern')}</button>
          <button type="button" onClick={() => { onRename?.(asset); onClose?.(); }}><Edit3 size={16} /> {t('library.actions.renameTitle', 'Titel ändern')}</button>
          <button className="danger" type="button" onClick={() => onDelete(asset)}><Trash2 size={16} /> {t('library.actions.moveToTrash', 'In Papierkorb')}</button>
        </div>
      </div>}
    </Modal>
  );
}
