// SunoAPI-Generate-Vertrag:
// Die normale /music-Generierung muss die offiziellen SunoAPI-Feldnamen senden:
// negativeTags, vocalGender, styleWeight, weirdnessConstraint, audioWeight.
// Diese Werte werden in der DB fuer Songdetails/Library/Offline-Anzeige gespeichert.
// Nicht auf interne snake_case-Namen zurueckbauen und nicht nur in buildAdvancedPayload()
// pflegen; submit() ist der tatsaechliche Generate-Button-Pfad.
import React, { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, ArrowRight, CheckCircle2, Copy, Loader2, Music2, RefreshCw, Search, Sparkles, Tag, Wand2 } from 'lucide-react';
import { api } from '../api/client.js';
import { SectionHeader } from '../components/SectionHeader.jsx';
import { Modal } from '../components/Modal.jsx';
import { useI18n } from '../i18n/I18nContext.jsx';

const models = ['V5_5', 'V5', 'V4_5ALL', 'V4_5', 'V4_5PLUS', 'V4'];
const addModels = ['V4_5PLUS', 'V5', 'V5_5'];
const soundModels = ['V5'];
const startModes = [
  ['idea', 'Ich habe nur eine Idee', 'Suno erzeugt aus einer kurzen Idee einen Song.'],
  ['lyrics', 'Ich habe fertige Lyrics', 'Du nutzt den Custom-Modus mit deinem vollständigen Songtext.'],
  ['instrumental', 'Ich möchte ein Instrumental', 'Es wird ein Track ohne Gesang erzeugt.']
];
const styleCategories = [
  ['dark-boombap', 'Dark Boom Bap', 'grimy NYC boom bap, dusty vinyl drums, hard snare crack, deep kick, dark piano, cinematic strings, male rap lead'],
  ['emotional-rap', 'Emotional Rap', 'emotional German rap, cinematic piano, warm strings, deep male vocal, dramatic chorus, heartfelt mood'],
  ['patwa-rap', 'Deutschrap + Patwa', 'German rap, Jamaican Patois toasting hook, ragga rhythm accents, gritty boom bap drums, deep bass'],
  ['trap-dark', 'Dark Trap', 'dark trap, heavy 808, minor synths, aggressive rap delivery, cinematic atmosphere'],
  ['cinematic-horror', 'Cinematic Horror', 'horror cinematic rap, low brass, choir textures, dark orchestral samples, heavy drums']
];
const operationModes = [
  ['generate', 'Generate Music'],
  ['generate-lyrics', 'Generate Lyrics'],
  ['import-suno-song', 'Suno Song-ID importieren'],
  ['extend', 'Extended'],
  ['upload-extend', 'Upload And Extend Audio'],
  ['upload-cover', 'Upload And Cover Song'],
  ['add-instrumental', 'Add Instrumental'],
  ['add-vocals', 'Add Voice / Vocals'],
  ['sounds', 'Generate Sounds'],
  ['stem-separation', 'Stem Separation'],
  ['convert-wav', 'Convert to WAV'],
  ['midi', 'Generate MIDI from Audio'],
  ['video', 'Create Music Video'],
  ['cover-image', 'Cover-Bilder aus Task'],
  ['replace-section', 'Replace Music Section'],
  ['persona', 'Persona erstellen'],
  ['boost-style', 'Style verbessern'],
  ['mashup', 'Mashup']
];
const MUSIC_PAGE_STATE_STORAGE_KEY = 'suno-song-studio:music-page-state:v1';
const MUSIC_PAGE_STATE_MAX_BYTES = 260_000;
const MUSIC_PAGE_TEXT_MAX_CHARS = 30_000;
const MUSIC_PAGE_RESULT_MAX_CHARS = 8_000;
const MUSIC_PAGE_ARRAY_MAX_ITEMS = 12;
const STYLE_ENGINE_LYRICS_MAX_CHARS = 5000;
const STYLE_ENGINE_MUSIC_STYLE_MAX_CHARS = 1000;
const STYLE_ENGINE_BPM_MIN = 40;
const STYLE_ENGINE_BPM_MAX = 240;

function limitText(value, maxLength = MUSIC_PAGE_TEXT_MAX_CHARS) {
  const text = String(value || '');
  return text.length > maxLength ? `${text.slice(0, maxLength)}\n… [gekürzt]` : text;
}

function limitForSunoField(value, maxLength = 0) {
  const text = String(value || '').trim();
  const limit = Number(maxLength || 0);
  if (!limit || text.length <= limit) return text;
  const clipped = text.slice(0, Math.max(0, limit));
  const softBreak = Math.max(
    clipped.lastIndexOf(';'),
    clipped.lastIndexOf(','),
    clipped.lastIndexOf('.')
  );
  return (softBreak > Math.floor(limit * 0.65) ? clipped.slice(0, softBreak) : clipped).trim().replace(/[;,.-]+$/, '').trim();
}

function compactArray(value, maxItems = MUSIC_PAGE_ARRAY_MAX_ITEMS) {
  if (!Array.isArray(value)) return [];
  return value.slice(0, maxItems).map((item) => {
    if (!item || typeof item !== 'object') return limitText(item, MUSIC_PAGE_RESULT_MAX_CHARS);
    const next = {};
    Object.entries(item).forEach(([key, entry]) => {
      if (typeof entry === 'string') next[key] = limitText(entry, MUSIC_PAGE_RESULT_MAX_CHARS);
      else if (Array.isArray(entry)) next[key] = compactArray(entry, 8);
      else if (entry && typeof entry === 'object') next[key] = JSON.parse(JSON.stringify(entry, (_, nested) => typeof nested === 'string' ? limitText(nested, 1600) : nested));
      else next[key] = entry;
    });
    return next;
  });
}

function compactMusicPageState(value) {
  const source = value && typeof value === 'object' ? value : {};
  return {
    ...source,
    title: limitText(source.title, 500),
    prompt: limitText(source.prompt, MUSIC_PAGE_TEXT_MAX_CHARS),
    style: limitText(source.style, MUSIC_PAGE_TEXT_MAX_CHARS),
    styleExtraPrompt: limitText(source.styleExtraPrompt, 4000),
    styleBpmMin: limitText(source.styleBpmMin, 10),
    styleBpmMax: limitText(source.styleBpmMax, 10),
    audioUrl: limitText(source.audioUrl, 2000),
    negativeTags: limitText(source.negativeTags, 4000),
    operationTags: limitText(source.operationTags, 4000),
    replaceFullLyrics: limitText(source.replaceFullLyrics, MUSIC_PAGE_TEXT_MAX_CHARS),
    personaDescription: limitText(source.personaDescription, 4000),
    mashupUrls: limitText(source.mashupUrls, 4000),
    safeCheckResult: source.safeCheckResult && typeof source.safeCheckResult === 'object' ? JSON.parse(JSON.stringify(source.safeCheckResult, (_, nested) => typeof nested === 'string' ? limitText(nested, MUSIC_PAGE_RESULT_MAX_CHARS) : nested)) : null,
    masterPackageText: limitText(source.masterPackageText, MUSIC_PAGE_RESULT_MAX_CHARS),
    styleSuggestions: compactArray(source.styleSuggestions),
    abVariants: compactArray(source.abVariants),
  };
}

function readStoredMusicPageState() {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage?.getItem(MUSIC_PAGE_STATE_STORAGE_KEY);
    if (!raw) return {};
    if (raw.length > MUSIC_PAGE_STATE_MAX_BYTES) {
      window.localStorage?.removeItem(MUSIC_PAGE_STATE_STORAGE_KEY);
      return {};
    }
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? compactMusicPageState(parsed) : {};
  } catch {
    try { window.localStorage?.removeItem(MUSIC_PAGE_STATE_STORAGE_KEY); } catch { /* ignore */ }
    return {};
  }
}

function writeStoredMusicPageState(value) {
  if (typeof window === 'undefined') return;
  try {
    let serialized = JSON.stringify(compactMusicPageState(value || {}));
    if (serialized.length > MUSIC_PAGE_STATE_MAX_BYTES) {
      const compact = compactMusicPageState({
        ...value,
        safeCheckResult: null,
        masterPackageText: '',
        styleSuggestions: compactArray(value?.styleSuggestions, 6),
        abVariants: compactArray(value?.abVariants, 6),
      });
      serialized = JSON.stringify(compact);
    }
    if (serialized.length > MUSIC_PAGE_STATE_MAX_BYTES) {
      window.localStorage?.removeItem(MUSIC_PAGE_STATE_STORAGE_KEY);
      return;
    }
    window.localStorage?.setItem(MUSIC_PAGE_STATE_STORAGE_KEY, serialized);
  } catch {
    // Persistenz ist nur Komfort. Bei vollem/gesperrtem Storage darf die Musikseite nicht brechen.
  }
}


function clampStyleAmount(value) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return 3;
  return Math.max(1, Math.min(5, parsed));
}

const STYLE_VARIANT_STRATEGIES = [
  ['balanced', 'Sicher', 'klarer Suno-Style mit wenig Risiko'],
  ['hook_focus', 'Hook', 'Ohrwurm, Refrain und Wiedererkennbarkeit maximieren'],
  ['darker', 'Dunkler', 'härter, düsterer und druckvoller'],
  ['radio', 'Radio', 'zugänglicher, klarer und weniger überladen'],
  ['experimental', 'Mutiger', 'Genre-Fusion und ungewöhnlichere Instrumente'],
  ['diverse', 'Mehr Unterschied', 'bewusst unterschiedliche Varianten']
];

const DEFAULT_STYLE_FEATURES = {
  instruments: true,
  arrangement: true,
  negative_tags: true,
  scores: true,
  vocal_delivery: true,
  lyric_vocal_tags: true
};

const STYLE_FEATURE_TOGGLE_OPTIONS = [
  ['instruments', 'Instrumente', 'Instrumentenliste und Rollen im Vorschlag anfordern'],
  ['arrangement', 'Arrangement', 'Abschnittslogik und Aufbau-Ideen anfordern'],
  ['negative_tags', 'Negative', 'Exclude-/Negative-Tags anfordern'],
  ['scores', 'Scores', 'Fit, Hook, Klarheit und Risiko bewerten'],
  ['vocal_delivery', 'Vocals', 'kompakte Vocal-Delivery im Style anzeigen'],
  ['lyric_vocal_tags', 'Songtext-Tags', 'fertige Section-Tags für den Songtext erzeugen']
];

const EMPTY_LYRIC_TAG_PREVIEW = {
  open: false,
  suggestion: null,
  title: '',
  taggedText: '',
  tagText: '',
  lyricTags: [],
  loading: false,
  error: '',
  notes: '',
  runtimeInfo: null
};

function normalizeStyleFeatures(value) {
  const source = value && typeof value === 'object' ? value : {};
  return {
    instruments: source.instruments !== false,
    arrangement: source.arrangement !== false,
    negative_tags: source.negative_tags !== false,
    scores: source.scores !== false,
    vocal_delivery: source.vocal_delivery !== false,
    lyric_vocal_tags: source.lyric_vocal_tags !== false && source.songtext_vocal_tags !== false
  };
}

function suggestionInstruments(suggestion) {
  return Array.isArray(suggestion?.instruments) ? suggestion.instruments.filter(Boolean).slice(0, 10) : [];
}

function suggestionArrangement(suggestion) {
  return Array.isArray(suggestion?.arrangement) ? suggestion.arrangement.filter(Boolean).slice(0, 8) : [];
}

function suggestionNegativeTags(suggestion) {
  return String(
    suggestion?.negative_tags
    ?? suggestion?.negativeTags
    ?? suggestion?.negative
    ?? suggestion?.avoid
    ?? ''
  ).trim();
}

function normalizeVocalTagText(value) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (!text) return '';
  return text.startsWith('[') ? text : `[${text.replace(/^\[|\]$/g, '').trim()}]`;
}

function suggestionLyricVocalTags(suggestion) {
  const source = suggestion?.lyric_vocal_tags
    ?? suggestion?.lyrics_vocal_tags
    ?? suggestion?.songtext_vocal_tags
    ?? suggestion?.vocal_tags_for_lyrics
    ?? [];
  const rawItems = Array.isArray(source) ? source : Object.entries(source && typeof source === 'object' ? source : {}).map(([section, tag]) => ({ section, tag }));
  return rawItems.map((item, index) => {
    if (!item || typeof item !== 'object') {
      const tag = normalizeVocalTagText(item);
      return tag ? { section: `Abschnitt ${index + 1}`, tag, reason: '' } : null;
    }
    const tag = normalizeVocalTagText(item.tag || item.vocal_tag || item.vocalTag || item.text || item.value);
    if (!tag) return null;
    return {
      section: String(item.section || item.part || item.name || item.abschnitt || `Abschnitt ${index + 1}`).trim(),
      tag,
      reason: String(item.reason || item.why || item.description || item.beschreibung || '').trim()
    };
  }).filter(Boolean).slice(0, 8);
}

const PROTECTED_LYRIC_DIRECTIVE_RE = /^\[(end|fade out|fade to silence|stop|silence)\]$/i;

function cleanSectionDescriptor(value) {
  return String(value || '')
    .trim()
    .replace(/^\s*[\[(]/, '')
    .replace(/[\])]\s*$/, '')
    .split(':')[0]
    .split('|')[0]
    .toLowerCase()
    .replace(/[^a-zäöüß0-9 ]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function freeformLyricSectionMeta(value) {
  const text = cleanSectionDescriptor(String(value || '').replace(/[\[\]()]/g, ' '));
  if (!text) return null;
  const numberMatch = text.match(/\b(?:verse|strophe|part|hook|chorus|refrain|bridge|breakdown|break|drop|pre chorus|prechorus|post chorus|postchorus)\s*(\d{1,2})\b/) || text.match(/\b(\d{1,2})\b/);
  const number = numberMatch ? numberMatch[1] : '';
  if (/\b(intro|einleitung)\b/.test(text)) return { base: 'intro', key: 'intro', label: 'Intro' };
  if (/\b(verse|strophe|part)\b/.test(text)) return { base: 'verse', key: number ? `verse-${number}` : 'verse', label: number ? `Verse ${number}` : 'Verse' };
  if (/\b(pre chorus|prechorus|pre refrain)\b/.test(text)) return { base: 'pre-chorus', key: number ? `pre-chorus-${number}` : 'pre-chorus', label: number ? `Pre-Chorus ${number}` : 'Pre-Chorus' };
  if (/\b(post chorus|postchorus)\b/.test(text)) return { base: 'post-chorus', key: number ? `post-chorus-${number}` : 'post-chorus', label: number ? `Post-Chorus ${number}` : 'Post-Chorus' };
  if (/\b(hook|chorus|refrain)\b/.test(text)) return { base: 'chorus', key: number ? `chorus-${number}` : 'chorus', label: number ? `Chorus ${number}` : 'Chorus' };
  if (/\b(bridge|breakdown|break)\b/.test(text)) return { base: 'bridge', key: number ? `bridge-${number}` : 'bridge', label: number ? `Bridge ${number}` : 'Bridge' };
  if (/\b(drop)\b/.test(text)) return { base: 'drop', key: number ? `drop-${number}` : 'drop', label: number ? `Drop ${number}` : 'Drop' };
  if (/\b(outro|ende|finale)\b/.test(text)) return { base: 'outro', key: 'outro', label: 'Outro' };
  if (/\b(adlib|adlibs)\b/.test(text)) return { base: 'adlibs', key: 'adlibs', label: 'Adlibs' };
  return null;
}

function lyricSectionMeta(value) {
  const raw = String(value || '').trim();
  if (!raw) return null;
  const isSquareTag = /^\[[^\]]+\]$/.test(raw);
  const isRoundHeader = /^\([^)]+\)$/.test(raw);
  if (!isSquareTag && !isRoundHeader) return null;

  const text = cleanSectionDescriptor(raw);
  if (!text) return null;

  const numberMatch = text.match(/\b(\d{1,2})\b/);
  const number = numberMatch ? numberMatch[1] : '';
  if (/\b(intro|einleitung)\b/.test(text)) return { base: 'intro', key: 'intro', label: 'Intro' };
  if (/\b(verse|strophe|part)\b/.test(text)) return { base: 'verse', key: number ? `verse-${number}` : 'verse', label: number ? `Verse ${number}` : 'Verse' };
  if (/\b(pre chorus|prechorus|pre refrain)\b/.test(text)) return { base: 'pre-chorus', key: number ? `pre-chorus-${number}` : 'pre-chorus', label: number ? `Pre-Chorus ${number}` : 'Pre-Chorus' };
  if (/\b(post chorus|postchorus)\b/.test(text)) return { base: 'post-chorus', key: number ? `post-chorus-${number}` : 'post-chorus', label: number ? `Post-Chorus ${number}` : 'Post-Chorus' };
  if (/\b(hook|chorus|refrain)\b/.test(text)) return { base: 'chorus', key: number ? `chorus-${number}` : 'chorus', label: number ? `Chorus ${number}` : 'Chorus' };
  if (/\b(bridge|breakdown|break)\b/.test(text)) return { base: 'bridge', key: number ? `bridge-${number}` : 'bridge', label: number ? `Bridge ${number}` : 'Bridge' };
  if (/\b(drop)\b/.test(text)) return { base: 'drop', key: number ? `drop-${number}` : 'drop', label: number ? `Drop ${number}` : 'Drop' };
  if (/\b(outro|ende|finale)\b/.test(text)) return { base: 'outro', key: 'outro', label: 'Outro' };
  if (/\b(adlib|adlibs)\b/.test(text)) return { base: 'adlibs', key: 'adlibs', label: 'Adlibs' };
  return null;
}

function vocalTagSectionKey(value) {
  const meta = freeformLyricSectionMeta(value);
  return meta?.key || 'section';
}

function vocalTagBaseKey(value) {
  const meta = freeformLyricSectionMeta(value);
  return meta?.base || vocalTagSectionKey(value);
}

function isStandaloneBracketDirective(line) {
  const text = String(line || '').trim();
  return /^\[[^\]]+\]$/.test(text) && !PROTECTED_LYRIC_DIRECTIVE_RE.test(text);
}

function isRoundSectionHeader(line) {
  const text = String(line || '').trim();
  return /^\([^)]+\)$/.test(text) && Boolean(lyricSectionMeta(text));
}

function fallbackSectionTagFromMeta(meta) {
  if (!meta?.label) return '';
  return `[${meta.label}]`;
}

function stripLeadingOrphanTagBlock(lines) {
  let index = 0;
  while (index < lines.length && !String(lines[index] || '').trim()) index += 1;
  const startIndex = index;
  let tagCount = 0;
  while (index < lines.length) {
    const trimmed = String(lines[index] || '').trim();
    if (!trimmed) break;
    if (!/^\[[^\]]+\]$/.test(trimmed) || !lyricSectionMeta(trimmed)) break;
    tagCount += 1;
    index += 1;
  }
  if (!tagCount) return lines;

  let nextIndex = index;
  while (nextIndex < lines.length && !String(lines[nextIndex] || '').trim()) nextIndex += 1;
  const nextLine = String(lines[nextIndex] || '').trim();
  if (!/^\([^)]+\)$/.test(nextLine) || !lyricSectionMeta(nextLine)) return lines;

  return [...lines.slice(0, startIndex), ...lines.slice(nextIndex)];
}

function buildVocalTagPackage(tags) {
  return tags.map((item) => item.tag).filter(Boolean).join('\n');
}

function buildLyricVocalTagPreviewText(currentPrompt, tags) {
  return mergeLyricVocalTagsIntoPrompt(currentPrompt, tags);
}

function mergeLyricVocalTagsIntoPrompt(currentPrompt, tags) {
  const normalizedTags = Array.isArray(tags) ? tags.filter((item) => item?.tag) : [];
  if (!normalizedTags.length) return String(currentPrompt || '');

  const exactTags = new Map();
  const baseTags = new Map();
  normalizedTags.forEach((item) => {
    const keySource = `${item.section || ''} ${item.tag || ''}`;
    const key = vocalTagSectionKey(keySource);
    const base = vocalTagBaseKey(keySource);
    if (key && key !== 'section' && !exactTags.has(key)) exactTags.set(key, item);
    if (base && base !== 'section' && !baseTags.has(base)) baseTags.set(base, item);
  });

  const text = String(currentPrompt || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  const lines = stripLeadingOrphanTagBlock(text.split('\n'));
  const output = [];
  const insertedKeys = new Set();
  const insertedBases = new Set();

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const meta = lyricSectionMeta(line);
    const replacement = meta ? (exactTags.get(meta.key) || baseTags.get(meta.base)) : null;

    if (replacement?.tag) {
      output.push(replacement.tag);
      insertedKeys.add(vocalTagSectionKey(`${replacement.section || ''} ${replacement.tag || ''}`));
      insertedBases.add(vocalTagBaseKey(`${replacement.section || ''} ${replacement.tag || ''}`));

      let cursor = index + 1;
      while (cursor < lines.length) {
        const candidate = String(lines[cursor] || '').trim();
        if (!candidate) {
          const nextNonEmptyIndex = lines.findIndex((nextLine, nextIndex) => nextIndex > cursor && String(nextLine || '').trim());
          const nextNonEmpty = nextNonEmptyIndex >= 0 ? String(lines[nextNonEmptyIndex] || '').trim() : '';
          if (nextNonEmpty && (isStandaloneBracketDirective(nextNonEmpty) || isRoundSectionHeader(nextNonEmpty))) {
            cursor += 1;
            continue;
          }
          break;
        }
        if (isStandaloneBracketDirective(candidate) || isRoundSectionHeader(candidate)) {
          cursor += 1;
          continue;
        }
        break;
      }
      index = cursor - 1;
      continue;
    }

    if (meta && isRoundSectionHeader(line)) {
      const fallbackTag = fallbackSectionTagFromMeta(meta);
      output.push(fallbackTag || line);
      continue;
    }

    output.push(line);
  }

  const mergedText = output.join('\n').replace(/\n{3,}/g, '\n\n').trim();
  const missingTags = [];
  normalizedTags.forEach((item) => {
    const key = vocalTagSectionKey(`${item.section || ''} ${item.tag || ''}`);
    const base = vocalTagBaseKey(`${item.section || ''} ${item.tag || ''}`);
    if (!insertedKeys.has(key) && !insertedBases.has(base) && item.tag && !mergedText.includes(item.tag)) {
      missingTags.push(item.tag);
    }
  });

  if (!missingTags.length) return mergedText;
  return `${missingTags.join('\n')}\n\n${mergedText}`.trim();
}

function buildStyleProfileJson(suggestion) {
  return {
    source: 'ai_style_suggestions',
    role: suggestion?.role || null,
    suggested_song_title: suggestionSongTitle(suggestion) || null,
    bpm: suggestion?.bpm || null,
    key_hint: suggestion?.key_hint || null,
    energy: suggestion?.energy || null,
    vocal_delivery: suggestion?.vocal_delivery || null,
    instruments: suggestionInstruments(suggestion),
    arrangement: suggestionArrangement(suggestion),
    lyric_vocal_tags: suggestionLyricVocalTags(suggestion),
    negative_tags: suggestionNegativeTags(suggestion),
    scores: suggestion?.scores || null
  };
}

function suggestionSongTitle(suggestion) {
  return String(
    suggestion?.suggested_song_title
    || suggestion?.suggestedSongTitle
    || suggestion?.song_title
    || suggestion?.songTitle
    || ''
  ).trim();
}

function instrumentLabel(item) {
  if (!item || typeof item !== 'object') return String(item || '').trim();
  return String(item.name || item.instrument || item.label || '').trim();
}

function instrumentRole(item) {
  if (!item || typeof item !== 'object') return '';
  return String(item.role || item.category || '').trim();
}

function arrangementSection(item, index) {
  if (!item || typeof item !== 'object') return `Abschnitt ${index + 1}`;
  return String(item.section || item.part || item.name || `Abschnitt ${index + 1}`).trim();
}

function arrangementIdea(item) {
  if (!item || typeof item !== 'object') return String(item || '').trim();
  return String(item.idea || item.description || item.text || '').trim();
}

function mergeCommaTags(current, incoming) {
  const existing = String(current || '').split(',').map((item) => item.trim()).filter(Boolean);
  const additions = String(incoming || '').split(',').map((item) => item.trim()).filter(Boolean);
  const seen = new Set(existing.map((item) => item.toLowerCase()));
  const merged = [...existing];
  additions.forEach((item) => {
    const key = item.toLowerCase();
    if (!seen.has(key)) {
      seen.add(key);
      merged.push(item);
    }
  });
  return merged.join(', ');
}

function formatScorePercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  return `${Math.round(Math.max(0, Math.min(1, number)) * 100)}%`;
}

function voiceLabel(voice, t = null) {
  if (!voice) return t ? t('music.fields.noVoicePersona', 'Keine Voice / Persona') : 'Keine Voice / Persona';
  const nickname = voice.nickname || voice.name || 'Voice';
  const shortId = String(voice.voice_id || voice.persona_id || '').slice(0, 10);
  const type = voice.source_type === 'persona' ? 'Persona' : 'Voice';
  return `${nickname} · ${type}${shortId ? ` · ${shortId}…` : ''}`;
}

function assetTitle(asset, t = null) {
  if (!asset) return t ? t('music.fields.chooseAudio', 'Audio wählen…') : 'Audio wählen…';
  const title = asset.display_title || asset.title || `Audio #${asset.id}`;
  const variant = asset.operation_label || asset.version_label || asset.task_type || asset.status || '';
  return `${title}${variant ? ` · ${variant}` : ''}`;
}

function assetMetadata(asset) {
  return asset?.metadata_json && typeof asset.metadata_json === 'object' ? asset.metadata_json : {};
}

function isLocalOnlyAsset(asset) {
  const metadata = assetMetadata(asset);
  return Boolean(
    asset?.is_suno_clip_import || metadata.is_suno_clip_import || metadata.import_source === 'suno_public_clip' ||
    asset?.is_opencli_generation || metadata.is_opencli_generation || metadata.generation_source === 'opencli' || metadata.provider === 'opencli'
  );
}

function operationCapabilityKey(mode) {
  return {
    extend: 'sunoapi_extend',
    'upload-extend': 'sunoapi_extend',
    'upload-cover': 'sunoapi_cover_song',
    'add-vocals': 'sunoapi_add_vocals',
    'add-instrumental': 'sunoapi_add_instrumental',
    'cover-image': 'sunoapi_create_cover',
    persona: 'sunoapi_persona',
    'convert-wav': 'sunoapi_wav',
    midi: 'sunoapi_midi',
    video: 'sunoapi_video',
    'stem-separation': 'sunoapi_extend',
    'replace-section': 'sunoapi_extend'
  }[mode] || '';
}

function canUseSelectedAssetForOperation(asset, mode) {
  const key = operationCapabilityKey(mode);
  if (!key || !asset) return true;
  const metadata = assetMetadata(asset);
  const caps = metadata.capabilities && typeof metadata.capabilities === 'object' ? metadata.capabilities : asset.capabilities || {};
  if (caps[key] === false) return false;
  if (isLocalOnlyAsset(asset) && key.startsWith('sunoapi_')) return false;
  return true;
}

function localOnlyAssetHint(asset, t = null) {
  if (!isLocalOnlyAsset(asset)) return '';
  const metadata = assetMetadata(asset);
  if (metadata.import_source === 'suno_public_clip' || metadata.is_suno_clip_import) return t ? t('music.messages.publicSunoImportLocalOnly', 'Öffentlicher Suno-Import: lokale Funktionen verfügbar, SunoAPI.org-Folgeaktionen deaktiviert.') : 'Öffentlicher Suno-Import: lokale Funktionen verfügbar, SunoAPI.org-Folgeaktionen deaktiviert.';
  if (metadata.generation_source === 'opencli' || metadata.provider === 'opencli' || metadata.is_opencli_generation) return t ? t('music.messages.openCliAssetLocalOnly', 'OpenCLI-Asset: lokale Funktionen verfügbar, SunoAPI.org-Folgeaktionen deaktiviert.') : 'OpenCLI-Asset: lokale Funktionen verfügbar, SunoAPI.org-Folgeaktionen deaktiviert.';
  return t ? t('music.messages.localAssetSunoDisabled', 'Lokales Asset: SunoAPI.org-Folgeaktionen deaktiviert.') : 'Lokales Asset: SunoAPI.org-Folgeaktionen deaktiviert.';
}

function numberOrNull(value) {
  if (value === '' || value === null || value === undefined) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function splitStyleTags(value) {
  return String(value || '')
    .split(/[#,;|]/)
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean)
    .slice(0, 18);
}

function StylePresetModal({ open, onClose, styles = [], builtinStyles = [], onApply, t }) {
  const [query, setQuery] = useState('');
  const [tab, setTab] = useState('all');

  const rows = useMemo(() => {
    const saved = (styles || []).map((item) => ({
      id: `saved-${item.id}`,
      source: 'saved',
      favorite: Boolean(item.is_favorite),
      name: item.name,
      genre: item.genre || '',
      bpm: item.bpm || '',
      text: item.style_text || item.content || item.description || item.name || '',
      description: item.description || '',
      tags: [...new Set([...splitStyleTags(item.tags), ...splitStyleTags(item.genre), ...(item.is_favorite ? ['favorit'] : [])])],
    }));
    const builtin = (builtinStyles || []).map(([key, label, text]) => ({
      id: `builtin-${key}`,
      source: 'builtin',
      favorite: false,
      name: label,
      genre: label,
      bpm: '',
      text,
      description: t('music.stylePresetModal.builtinDescription', 'Schneller eingebauter Style-Vorschlag'),
      tags: splitStyleTags(`${label}, preset, vorschlag, ${text}`),
    }));
    return [...saved, ...builtin];
  }, [styles, builtinStyles]);

  const availableTags = useMemo(() => {
    const tags = new Set();
    rows.forEach((row) => row.tags.forEach((tag) => tags.add(tag)));
    return [...tags].sort((a, b) => a.localeCompare(b)).slice(0, 28);
  }, [rows]);

  const tabs = [
    ['all', t('music.stylePresetModal.tabs.all', 'Alle')],
    ['saved', t('music.stylePresetModal.tabs.saved', 'Gespeichert')],
    ['builtin', t('music.stylePresetModal.tabs.builtin', 'Vorschläge')],
    ['favorite', t('music.stylePresetModal.tabs.favorite', 'Favoriten')],
    ...availableTags.slice(0, 12).map((tag) => [`tag:${tag}`, `#${tag}`]),
  ];

  const needle = query.trim().toLowerCase();
  const filtered = rows.filter((row) => {
    const hay = [row.name, row.genre, row.description, row.text, row.tags.join(' ')].join(' ').toLowerCase();
    const matchesSearch = !needle || hay.includes(needle);
    const matchesTab = tab === 'all'
      || row.source === tab
      || (tab === 'favorite' && row.favorite)
      || (tab.startsWith('tag:') && row.tags.includes(tab.slice(4)));
    return matchesSearch && matchesTab;
  });

  return (
    <Modal open={open} title={t('music.stylePresetModal.title', 'Style Preset auswählen')} onClose={onClose} wide>
      <div className="style-preset-modal stack">
        <div className="search-wrap"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('music.stylePresetModal.searchPlaceholder', 'Style, Genre, Tag, Stimmung suchen…')} /></div>
        <div className="style-preset-tabs">
          {tabs.map(([key, label]) => <button key={key} type="button" className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>{label}</button>)}
        </div>
        <div className="style-preset-grid">
          {filtered.map((row) => (
            <article key={row.id} className="style-preset-card">
              <div className="row between align-start"><div><p className="eyebrow">{row.source === 'saved' ? t('music.stylePresetModal.saved', 'Gespeichert') : t('music.stylePresetModal.suggestion', 'Vorschlag')}</p><h3>{row.name}</h3></div>{row.favorite && <span className="status cached">{t('music.stylePresetModal.favorite', 'Favorit')}</span>}</div>
              <p className="muted">{row.genre || t('music.stylePresetModal.noGenre', 'Ohne Genre')}{row.bpm ? ` · ${row.bpm} BPM` : ''}</p>
              <p className="ai-style-text">{row.text}</p>
              <div className="tag-chip-row">{row.tags.slice(0, 10).map((tag) => <span key={tag}><Tag size={12} /> {tag}</span>)}</div>
              <button type="button" className="primary" onClick={() => { onApply(row.text, row); onClose?.(); }}>{t('music.stylePresetModal.apply', 'Style übernehmen')}</button>
            </article>
          ))}
          {!filtered.length && <p className="muted">{t('music.stylePresetModal.empty', 'Kein Style gefunden. Passe Suche oder Filter an.')}</p>}
        </div>
      </div>
    </Modal>
  );
}

export function MusicPage({ styles, voices = [], uploadedFiles = [], assets = [], draft, notify, onRefresh, onMusicStarted, onCheckStatus, taskRefreshState, initialWizard = false }) {
  const { t } = useI18n();
  const storedMusicState = useMemo(() => readStoredMusicPageState(), []);
  const [title, setTitle] = useState(() => storedMusicState.title || '');
  const [prompt, setPrompt] = useState(() => storedMusicState.prompt || '');
  const [style, setStyle] = useState(() => storedMusicState.style || '');
  const [model, setModel] = useState(() => storedMusicState.model || 'V5_5');
  const [customMode, setCustomMode] = useState(() => storedMusicState.customMode !== undefined ? Boolean(storedMusicState.customMode) : true);
  const [instrumental, setInstrumental] = useState(() => Boolean(storedMusicState.instrumental));
  const [loading, setLoading] = useState(false);
  const [runtime, setRuntime] = useState(null);
  const [adminRuntimeSettings, setAdminRuntimeSettings] = useState(null);
  const [wizard, setWizard] = useState(() => storedMusicState.wizard !== undefined ? Boolean(storedMusicState.wizard) : initialWizard);
  const [step, setStep] = useState(() => Number.isFinite(Number(storedMusicState.step)) ? Number(storedMusicState.step) : 0);
  const [startMode, setStartMode] = useState(() => storedMusicState.startMode || 'lyrics');
  const [styleAmount, setStyleAmount] = useState(() => clampStyleAmount(storedMusicState.styleAmount || 3));
  const [styleVariantStrategy, setStyleVariantStrategy] = useState(() => storedMusicState.styleVariantStrategy || 'balanced');
  const [styleFeatureOptions, setStyleFeatureOptions] = useState(() => normalizeStyleFeatures(storedMusicState.styleFeatureOptions));
  const [styleExtraPrompt, setStyleExtraPrompt] = useState(() => storedMusicState.styleExtraPrompt || '');
  const [styleBpmMin, setStyleBpmMin] = useState(() => storedMusicState.styleBpmMin || '');
  const [styleBpmMax, setStyleBpmMax] = useState(() => storedMusicState.styleBpmMax || '');
  const [styleSuggestions, setStyleSuggestions] = useState(() => Array.isArray(storedMusicState.styleSuggestions) ? storedMusicState.styleSuggestions : []);
  const [stylePresetModalOpen, setStylePresetModalOpen] = useState(false);
  const [styleSuggestionRuntime, setStyleSuggestionRuntime] = useState(() => storedMusicState.styleSuggestionRuntime || null);
  const [styleSuggestionLoading, setStyleSuggestionLoading] = useState(false);
  const [styleSuggestionError, setStyleSuggestionError] = useState('');
  const [styleConsultation, setStyleConsultation] = useState({ open: false, suggestion: null, draft: null, messages: [], input: '', loading: false, error: '' });
  const [lyricTagPreview, setLyricTagPreview] = useState(EMPTY_LYRIC_TAG_PREVIEW);
  const [selectedVoiceId, setSelectedVoiceId] = useState(() => storedMusicState.selectedVoiceId || '');
  const [generationProvider, setGenerationProvider] = useState(() => storedMusicState.generationProvider || 'sunoapi');
  const [operationMode, setOperationMode] = useState(() => storedMusicState.operationMode || 'generate');
  const [selectedAssetId, setSelectedAssetId] = useState(() => storedMusicState.selectedAssetId || '');
  const [selectedUploadId, setSelectedUploadId] = useState(() => storedMusicState.selectedUploadId || '');
  const [sunoImportId, setSunoImportId] = useState(() => storedMusicState.sunoImportId || '');
  const [sunoImportCacheAudio, setSunoImportCacheAudio] = useState(() => storedMusicState.sunoImportCacheAudio !== undefined ? Boolean(storedMusicState.sunoImportCacheAudio) : true);
  const [sunoImportCacheCover, setSunoImportCacheCover] = useState(() => storedMusicState.sunoImportCacheCover !== undefined ? Boolean(storedMusicState.sunoImportCacheCover) : true);
  const [sunoImportOverwrite, setSunoImportOverwrite] = useState(() => Boolean(storedMusicState.sunoImportOverwrite));
  const [audioUrl, setAudioUrl] = useState(() => storedMusicState.audioUrl || '');
  const [operationUploadFile, setOperationUploadFile] = useState(null);
  const [operationUploadUrl, setOperationUploadUrl] = useState('');
  const [operationUploadBusy, setOperationUploadBusy] = useState(false);
  const [continueAt, setContinueAt] = useState(() => storedMusicState.continueAt || '60');
  const [autoContinueAt, setAutoContinueAt] = useState(() => Boolean(storedMusicState.autoContinueAt));
  const [negativeTags, setNegativeTags] = useState(() => storedMusicState.negativeTags || '');
  const [operationTags, setOperationTags] = useState(() => storedMusicState.operationTags || '');
  const [vocalGender, setVocalGender] = useState(() => storedMusicState.vocalGender || '');
  const [styleWeight, setStyleWeight] = useState(() => storedMusicState.styleWeight || '');
  const [weirdnessConstraint, setWeirdnessConstraint] = useState(() => storedMusicState.weirdnessConstraint || '');
  const [audioWeight, setAudioWeight] = useState(() => storedMusicState.audioWeight || '');
  const [soundLoop, setSoundLoop] = useState(() => Boolean(storedMusicState.soundLoop));
  const [soundTempo, setSoundTempo] = useState(() => storedMusicState.soundTempo || '');
  const [soundKey, setSoundKey] = useState(() => storedMusicState.soundKey || '');
  const [grabLyrics, setGrabLyrics] = useState(() => Boolean(storedMusicState.grabLyrics));
  const [stemSeparationType, setStemSeparationType] = useState(() => storedMusicState.stemSeparationType || 'separate_vocal');
  const [taskIdInput, setTaskIdInput] = useState(() => storedMusicState.taskIdInput || '');
  const [audioIdInput, setAudioIdInput] = useState(() => storedMusicState.audioIdInput || '');
  const [replaceStart, setReplaceStart] = useState(() => storedMusicState.replaceStart || '30');
  const [replaceEnd, setReplaceEnd] = useState(() => storedMusicState.replaceEnd || '45');
  const [replaceFullLyrics, setReplaceFullLyrics] = useState(() => storedMusicState.replaceFullLyrics || '');
  const [personaName, setPersonaName] = useState(() => storedMusicState.personaName || '');
  const [personaDescription, setPersonaDescription] = useState(() => storedMusicState.personaDescription || '');
  const [vocalStart, setVocalStart] = useState(() => storedMusicState.vocalStart || '0');
  const [vocalEnd, setVocalEnd] = useState(() => storedMusicState.vocalEnd || '30');
  const [mashupUrls, setMashupUrls] = useState(() => storedMusicState.mashupUrls || '');
  const [videoAuthor, setVideoAuthor] = useState(() => storedMusicState.videoAuthor || '');
  const [videoDomain, setVideoDomain] = useState(() => storedMusicState.videoDomain || '');
  const [safeCheckLoading, setSafeCheckLoading] = useState(false);
  const [safeCheckResult, setSafeCheckResult] = useState(() => storedMusicState.safeCheckResult || null);
  const [masterPackageText, setMasterPackageText] = useState(() => storedMusicState.masterPackageText || '');
  const [abVariants, setAbVariants] = useState(() => Array.isArray(storedMusicState.abVariants) ? storedMusicState.abVariants : []);
  const [safeCheckRequestedPending, setSafeCheckRequestedPending] = useState(false);

  useEffect(() => { api.runtimeConfig().then(setRuntime).catch(() => setRuntime(null)); }, []);
  useEffect(() => { api.admin.aiSettings().then(setAdminRuntimeSettings).catch(() => setAdminRuntimeSettings(null)); }, []);
  useEffect(() => {
    writeStoredMusicPageState({
      title,
      prompt,
      style,
      model,
      customMode,
      instrumental,
      wizard,
      step,
      startMode,
      styleAmount,
      styleVariantStrategy,
      styleFeatureOptions,
      styleExtraPrompt,
      styleBpmMin,
      styleBpmMax,
      styleSuggestions,
      styleSuggestionRuntime,
      selectedVoiceId,
      generationProvider,
      operationMode,
      selectedAssetId,
      selectedUploadId,
      sunoImportId,
      sunoImportCacheAudio,
      sunoImportCacheCover,
      sunoImportOverwrite,
      audioUrl,
      continueAt,
      autoContinueAt,
      negativeTags,
      operationTags,
      vocalGender,
      styleWeight,
      weirdnessConstraint,
      audioWeight,
      soundLoop,
      soundTempo,
      soundKey,
      grabLyrics,
      stemSeparationType,
      taskIdInput,
      audioIdInput,
      replaceStart,
      replaceEnd,
      replaceFullLyrics,
      personaName,
      personaDescription,
      vocalStart,
      vocalEnd,
      mashupUrls,
      videoAuthor,
      videoDomain,
      safeCheckResult,
      masterPackageText,
      abVariants
    });
  }, [
    title, prompt, style, model, customMode, instrumental, wizard, step, startMode,
    styleAmount, styleVariantStrategy, styleFeatureOptions, styleExtraPrompt, styleBpmMin, styleBpmMax, styleSuggestions, styleSuggestionRuntime, selectedVoiceId,
    generationProvider, operationMode, selectedAssetId, selectedUploadId, sunoImportId,
    sunoImportCacheAudio, sunoImportCacheCover, sunoImportOverwrite, audioUrl, continueAt, autoContinueAt,
    negativeTags, operationTags, vocalGender, styleWeight, weirdnessConstraint, audioWeight,
    soundLoop, soundTempo, soundKey, grabLyrics, stemSeparationType, taskIdInput,
    audioIdInput, replaceStart, replaceEnd, replaceFullLyrics, personaName, personaDescription,
    vocalStart, vocalEnd, mashupUrls, videoAuthor, videoDomain, safeCheckResult,
    masterPackageText, abVariants
  ]);
  useEffect(() => {
    if (!draft) return;
    const isInstrumentalDraft = Boolean(draft.instrumental) || ['instrumental', 'instrumental_blueprint', 'blueprint', 'sound_blueprint'].includes(String(draft.work_mode || '').toLowerCase().replace('-', '_'));
    if (draft.title) setTitle(draft.title);
    if (draft.prompt) setPrompt(draft.prompt);
    if (draft.style) {
      setStyle(draft.style);
      setOperationTags(draft.style);
    }
    if (draft.negative_tags !== undefined || draft.negativeTags !== undefined) setNegativeTags(String(draft.negative_tags ?? draft.negativeTags ?? ''));
    if (draft.vocal_gender !== undefined || draft.vocalGender !== undefined) setVocalGender(String(draft.vocal_gender ?? draft.vocalGender ?? ''));
    if (draft.styleWeight !== undefined || draft.style_weight !== undefined) setStyleWeight(String(draft.styleWeight ?? draft.style_weight ?? ''));
    if (draft.weirdnessConstraint !== undefined || draft.weirdness_constraint !== undefined || draft.weirdness !== undefined) setWeirdnessConstraint(String(draft.weirdnessConstraint ?? draft.weirdness_constraint ?? draft.weirdness ?? ''));
    if (draft.audioWeight !== undefined || draft.audio_weight !== undefined) setAudioWeight(String(draft.audioWeight ?? draft.audio_weight ?? ''));
    if (draft.provider === 'opencli' || draft.generationProvider === 'opencli') setGenerationProvider('opencli');
    setCustomMode(draft.customMode !== undefined ? Boolean(draft.customMode) : true);
    setInstrumental(isInstrumentalDraft);
    setStartMode(isInstrumentalDraft ? 'instrumental' : 'lyrics');
    setSelectedVoiceId(isInstrumentalDraft ? '' : selectedVoiceId);
    setWizard(true);
    setStep(draft.safeCheckRequested ? 4 : 1);
    if (draft.safeCheckRequested) setSafeCheckRequestedPending(true);
  }, [draft]);
  useEffect(() => {
    if (initialWizard) setWizard(true);
  }, [initialWizard]);

  useEffect(() => {
    if (!safeCheckRequestedPending) return;
    if (!prompt.trim() && !style.trim()) return;
    setSafeCheckRequestedPending(false);
    runSafeCheck();
  }, [safeCheckRequestedPending, prompt, style]);

  useEffect(() => {
    if (!selectedVoiceId) return;
    const stillExists = voices.some((voice) => String(voice.id) === String(selectedVoiceId));
    if (!stillExists) setSelectedVoiceId('');
  }, [voices, selectedVoiceId]);
  useEffect(() => {
    if (!selectedAssetId && assets.length) setSelectedAssetId(String(assets[0].id));
  }, [assets, selectedAssetId]);
  useEffect(() => {
    function handleAssistantStyleRequest() {
      generateStyleSuggestions();
    }
    window.addEventListener('assistant:music-generate-styles', handleAssistantStyleRequest);
    return () => window.removeEventListener('assistant:music-generate-styles', handleAssistantStyleRequest);
  }, [title, prompt, style, styleAmount, styleExtraPrompt, styleBpmMin, styleBpmMax]);

  const modelLimit = useMemo(() => {
    const limits = runtime?.model_limits?.[model] || {};
    return customMode ? limits.custom_prompt : limits.simple_prompt;
  }, [runtime, model, customMode]);

  const styleLimit = useMemo(() => {
    const limits = runtime?.model_limits?.[model] || {};
    return Number(limits.style || 0);
  }, [runtime, model]);

  const titleLimit = useMemo(() => {
    const limits = runtime?.model_limits?.[model] || {};
    return Number(limits.title || 0);
  }, [runtime, model]);

  const isGenerateMode = operationMode === 'generate';
  const promptLength = String(prompt || '').length;
  const styleLength = String(style || '').length;
  const titleLength = String(title || '').length;
  const promptOverLimit = Boolean(isGenerateMode && modelLimit && promptLength > modelLimit);
  const styleOverLimit = Boolean(isGenerateMode && styleLimit && styleLength > styleLimit);
  const titleOverLimit = Boolean(isGenerateMode && titleLimit && titleLength > titleLimit);
  const generationLimitMessages = [
    titleOverLimit ? t('music.messages.titleTooLong', 'Titel ist für {{model}} zu lang: {{current}}/{{limit}} Zeichen.', { model, current: titleLength, limit: titleLimit }) : '',
    promptOverLimit ? t('music.messages.promptTooLong', 'Prompt/Lyrics sind für {{model}} zu lang: {{current}}/{{limit}} Zeichen.', { model, current: promptLength, limit: modelLimit }) : '',
    styleOverLimit ? t('music.messages.styleTooLong', 'Style ist für {{model}} zu lang: {{current}}/{{limit}} Zeichen.', { model, current: styleLength, limit: styleLimit }) : ''
  ].filter(Boolean);
  const generationBlockedByLimits = generationLimitMessages.length > 0;

  const localizedStartModes = useMemo(() => [
    ['idea', t('music.startModes.idea.label', 'Ich habe nur eine Idee'), t('music.startModes.idea.text', 'Suno erzeugt aus einer kurzen Idee einen Song.')],
    ['lyrics', t('music.startModes.lyrics.label', 'Ich habe fertige Lyrics'), t('music.startModes.lyrics.text', 'Du nutzt den Custom-Modus mit deinem vollständigen Songtext.')],
    ['instrumental', t('music.startModes.instrumental.label', 'Ich möchte ein Instrumental'), t('music.startModes.instrumental.text', 'Es wird ein Track ohne Gesang erzeugt.')]
  ], [t]);

  const localizedOperationModes = useMemo(() => operationModes.map(([key, label]) => [key, t(`music.operationModes.${key}`, label)]), [t]);

  const wizardStepLabels = useMemo(() => [
    t('music.wizard.steps.start', 'Start'),
    t('music.wizard.steps.content', 'Inhalt'),
    t('music.wizard.steps.style', 'Style'),
    t('music.wizard.steps.model', 'Modell'),
    t('music.wizard.steps.check', 'Prüfen')
  ], [t]);

  const localizedStyleVariantStrategies = useMemo(() => STYLE_VARIANT_STRATEGIES.map(([key, label, description]) => [
    key,
    t(`music.styleStrategies.${key}.label`, label),
    t(`music.styleStrategies.${key}.description`, description)
  ]), [t]);

  const localizedStyleFeatureOptions = useMemo(() => STYLE_FEATURE_TOGGLE_OPTIONS.map(([key, label, description]) => [
    key,
    t(`music.styleFeatures.${key}.label`, label),
    t(`music.styleFeatures.${key}.description`, description)
  ]), [t]);

  const styleConsultationChips = useMemo(() => [
    t('music.styleConsultation.chips.morePressure', 'Mehr Druck'),
    t('music.styleConsultation.chips.biggerHook', 'Hook größer'),
    t('music.styleConsultation.chips.lessBusy', 'Weniger überladen'),
    t('music.styleConsultation.chips.moreBoomBap', 'Mehr Boom Bap'),
    t('music.styleConsultation.chips.moreTrap', 'Mehr Trap'),
    t('music.styleConsultation.chips.moreCinema', 'Mehr Kino'),
    t('music.styleConsultation.chips.improveNegative', 'Negative Tags verbessern'),
    t('music.styleConsultation.chips.shorterSuno', 'Suno-kürzer formulieren')
  ], [t]);

  const selectedVoice = voices.find((item) => String(item.id) === String(selectedVoiceId));
  const selectedAsset = assets.find((item) => String(item.id) === String(selectedAssetId));
  const selectedUpload = uploadedFiles.find((item) => String(item.id) === String(selectedUploadId));
  const playableAssets = useMemo(() => (assets || []).filter((item) => item?.id && String(item.status || '').toLowerCase() !== 'failed'), [assets]);
  const uploadUrlOptions = useMemo(() => (uploadedFiles || []).filter((item) => item?.uploaded_url), [uploadedFiles]);
  const openCliRuntime = runtime?.opencli || {};
  const openCliEnabled = Boolean(openCliRuntime.enabled);
  const openCliReady = Boolean(openCliRuntime.enabled && openCliRuntime.installed);
  const autoContinueAtEnabled = Boolean(adminRuntimeSettings?.extend_auto_continue_at_enabled);

  useEffect(() => {
    if (runtime?.opencli && !runtime.opencli.enabled && generationProvider === 'opencli') {
      setGenerationProvider('sunoapi');
    }
  }, [runtime?.opencli?.enabled, generationProvider]);

  function selectedTaskId() {
    return taskIdInput.trim() || selectedAsset?.suno_task_id || selectedAsset?.task_id || '';
  }

  function selectedAudioId() {
    return audioIdInput.trim() || selectedAsset?.audio_id || '';
  }

  function selectedAudioUrl() {
    return audioUrl.trim() || selectedUpload?.uploaded_url || selectedAsset?.source_url || selectedAsset?.public_url || '';
  }

  function applyStartMode(value) {
    setStartMode(value);
    if (value === 'idea') {
      setCustomMode(false);
      setInstrumental(false);
    }
    if (value === 'lyrics') {
      setCustomMode(true);
      setInstrumental(false);
    }
    if (value === 'instrumental') {
      setCustomMode(false);
      setInstrumental(true);
    }
  }

  function applyStylePreset(value) {
    const preset = styles.find((item) => String(item.id) === String(value));
    if (!preset) return;
    setStyle(preset.style_text || preset.content || preset.description || preset.name || '');
  }

  function applyStylePresetText(value, preset = null) {
    setStyle(String(value || ''));
    if (preset?.tags?.length) setOperationTags(preset.tags.join(', '));
    notify?.(t('music.messages.stylePresetApplied', 'Style „{{name}}“ übernommen.', { name: preset?.name || 'Preset' }), 'success');
  }

  function applySuggestedStyle(value) {
    const preset = styleCategories.find((item) => item[0] === value);
    if (preset) setStyle(preset[2]);
  }

  async function generateStyleSuggestions() {
    const lyrics = String(prompt || '').trim();
    const currentMusicStyle = String(style || '').trim();
    const bpmMinText = String(styleBpmMin || '').trim();
    const bpmMaxText = String(styleBpmMax || '').trim();
    const hasBpmRange = Boolean(bpmMinText || bpmMaxText);
    let bpmMinValue = null;
    let bpmMaxValue = null;
    if (!lyrics) {
      const message = t('music.messages.stylePromptMissing', 'Bitte zuerst Lyrics oder einen Prompt einfügen. Dann kann die KI passende Suno-Styles erstellen.');
      setStyleSuggestionError(message);
      notify?.(message, 'error');
      return;
    }
    if (lyrics.length > STYLE_ENGINE_LYRICS_MAX_CHARS) {
      const message = t('music.messages.styleLyricsTooLong', 'Songtext/Prompt ist zu lang für Styles generieren: {{current}} / {{limit}} Zeichen.', { current: lyrics.length, limit: STYLE_ENGINE_LYRICS_MAX_CHARS });
      setStyleSuggestionError(message);
      notify?.(message, 'error');
      return;
    }
    if (currentMusicStyle.length > STYLE_ENGINE_MUSIC_STYLE_MAX_CHARS) {
      const message = t('music.messages.styleEngineStyleTooLong', 'Music Style ist zu lang für Styles generieren: {{current}} / {{limit}} Zeichen.', { current: currentMusicStyle.length, limit: STYLE_ENGINE_MUSIC_STYLE_MAX_CHARS });
      setStyleSuggestionError(message);
      notify?.(message, 'error');
      return;
    }
    if (hasBpmRange) {
      if (!bpmMinText || !bpmMaxText) {
        const message = t('music.messages.styleBpmRangeIncomplete', 'BPM-Eingrenzung benötigt Von- und Bis-Wert.');
        setStyleSuggestionError(message);
        notify?.(message, 'error');
        return;
      }
      if (!/^\d+$/.test(bpmMinText) || !/^\d+$/.test(bpmMaxText)) {
        const message = t('music.messages.styleBpmRangeInteger', 'BPM-Eingrenzung muss aus ganzen Zahlen bestehen.');
        setStyleSuggestionError(message);
        notify?.(message, 'error');
        return;
      }
      bpmMinValue = Number(bpmMinText);
      bpmMaxValue = Number(bpmMaxText);
      if (bpmMinValue < STYLE_ENGINE_BPM_MIN || bpmMaxValue > STYLE_ENGINE_BPM_MAX || bpmMinValue > bpmMaxValue) {
        const message = t('music.messages.styleBpmRangeInvalid', 'BPM-Eingrenzung muss zwischen {{min}} und {{max}} liegen; Von darf nicht größer als Bis sein.', { min: STYLE_ENGINE_BPM_MIN, max: STYLE_ENGINE_BPM_MAX });
        setStyleSuggestionError(message);
        notify?.(message, 'error');
        return;
      }
    }

    setStyleSuggestionLoading(true);
    setStyleSuggestionError('');
    try {
      const response = await api.assistant.styleSuggestions({
        lyrics,
        amount: clampStyleAmount(styleAmount),
        extra_prompt: styleExtraPrompt,
        title,
        current_style: currentMusicStyle,
        ...(hasBpmRange ? { bpm_min: bpmMinValue, bpm_max: bpmMaxValue } : {}),
        variant_strategy: styleVariantStrategy,
        features: styleFeatureOptions,
        batch_mode: 'auto'
      });
      const suggestions = Array.isArray(response?.suggestions) ? response.suggestions : [];
      setStyleSuggestions(suggestions);
      setStyleSuggestionRuntime(response?.runtime_info || null);
      notify?.(t('music.messages.styleSuggestionsCreated', '{{count}} KI-Style-Vorschlag/Vorschläge erstellt.', { count: suggestions.length || 0 }), 'success');
    } catch (err) {
      const message = err?.message || t('music.messages.styleSuggestionsFailed', 'KI-Style-Vorschläge konnten nicht erstellt werden.');
      setStyleSuggestionError(message);
      notify?.(message, 'error');
    } finally {
      setStyleSuggestionLoading(false);
    }
  }

  function applyAiStyle(suggestion, options = {}) {
    const nextStyle = String(suggestion?.style || '').trim();
    if (!nextStyle) return;
    const includeNegative = options.includeNegative !== false;
    const negativeMode = options.negativeMode === 'replace' ? 'replace' : 'append';
    const nextNegative = suggestionNegativeTags(suggestion);
    setStyle(nextStyle);
    setOperationTags(nextStyle);
    if (includeNegative && nextNegative) {
      setNegativeTags((current) => negativeMode === 'replace' ? nextNegative : mergeCommaTags(current, nextNegative));
    }
    notify?.(
      includeNegative && nextNegative
        ? t('music.messages.masterStyleWithNegativeApplied', 'Master Style „{{title}}“ inkl. Negative Tags übernommen.', { title: suggestion?.title || t('music.aiStyleFallback', 'KI-Vorschlag') })
        : t('music.messages.masterStyleApplied', 'Master Style „{{title}}“ übernommen.', { title: suggestion?.title || t('music.aiStyleFallback', 'KI-Vorschlag') }),
      'success'
    );
  }

  function applySuggestedSongTitle(suggestion) {
    const nextTitleRaw = suggestionSongTitle(suggestion);
    if (!nextTitleRaw) return;
    const nextTitle = titleLimit && nextTitleRaw.length > titleLimit ? nextTitleRaw.slice(0, titleLimit).trim() : nextTitleRaw;
    setTitle(nextTitle);
    notify?.(t('music.messages.songTitleApplied', 'Songtitel „{{title}}“ übernommen.', { title: nextTitle }), 'success');
  }

  function applyAiStyleWithNegative(suggestion, mode = 'append') {
    applyAiStyle(suggestion, { includeNegative: true, negativeMode: mode });
  }

  function applyNegativeTagsOnly(suggestion, mode = 'append') {
    const nextNegative = suggestionNegativeTags(suggestion);
    if (!nextNegative) return;
    setNegativeTags((current) => mode === 'replace' ? nextNegative : mergeCommaTags(current, nextNegative));
    notify?.(mode === 'replace' ? t('music.messages.negativeReplaced', 'Negative Tags ersetzt.') : t('music.messages.negativeAppended', 'Negative Tags angehängt.'), 'success');
  }

  async function openLyricTagPreview(suggestion) {
    const lyrics = String(prompt || '').trim();
    const lyricTags = suggestionLyricVocalTags(suggestion);
    if (!lyrics) {
      notify?.(t('music.messages.lyricPreviewNeedsLyrics', 'Für die Songtext-Vorschau wird zuerst ein Songtext benötigt.'), 'error');
      return;
    }
    if (lyrics.length > STYLE_ENGINE_LYRICS_MAX_CHARS) {
      notify?.(t('music.messages.lyricPreviewTooLong', 'Songtext ist zu lang für die Vorschau: {{current}} / {{limit}} Zeichen.', { current: lyrics.length, limit: STYLE_ENGINE_LYRICS_MAX_CHARS }), 'error');
      return;
    }
    if (!lyricTags.length) {
      notify?.(t('music.messages.noLyricTags', 'Dieser Style-Vorschlag enthält keine Songtext-Tags.'), 'info');
      return;
    }
    const fallbackTaggedText = buildLyricVocalTagPreviewText(lyrics, lyricTags);
    const fallbackTagText = buildVocalTagPackage(lyricTags);
    setLyricTagPreview({
      open: true,
      suggestion,
      title: suggestion?.title || t('music.aiStyleTitle', 'KI-Style'),
      taggedText: fallbackTaggedText,
      tagText: fallbackTagText,
      lyricTags,
      loading: true,
      error: '',
      notes: t('music.messages.creatingTaggedPreview', 'Erstelle vollständige Songtext-Vorschau passend zu diesem Style…'),
      runtimeInfo: null
    });
    try {
      const response = await api.assistant.styleTaggedLyrics({
        lyrics,
        title,
        suggestion
      });
      const nextTags = suggestionLyricVocalTags({ lyric_vocal_tags: response?.lyric_vocal_tags || lyricTags });
      const nextTaggedText = String(response?.tagged_lyrics || fallbackTaggedText || '').trim();
      if (nextTaggedText.length > STYLE_ENGINE_LYRICS_MAX_CHARS) {
        throw new Error(t('music.messages.taggedLyricsTooLongLimit', 'Getaggter Songtext überschreitet {{limit}} Zeichen.', { limit: STYLE_ENGINE_LYRICS_MAX_CHARS }));
      }
      setLyricTagPreview({
        open: true,
        suggestion: { ...suggestion, lyric_vocal_tags: nextTags },
        title: suggestion?.title || t('music.aiStyleTitle', 'KI-Style'),
        taggedText: nextTaggedText,
        tagText: buildVocalTagPackage(nextTags),
        lyricTags: nextTags,
        loading: false,
        error: '',
        notes: response?.notes || t('music.messages.taggedPreviewCreated', 'Vollständiger getaggter Songtext wurde erzeugt.'),
        runtimeInfo: response?.runtime_info || null
      });
    } catch (err) {
      const message = err?.message || t('music.messages.taggedPreviewFailed', 'Vollständige Songtext-Vorschau konnte nicht erstellt werden.');
      setLyricTagPreview((current) => ({
        ...current,
        loading: false,
        error: message,
        notes: t('music.messages.taggedPreviewFallback', 'Fallback-Vorschau aus den vorhandenen Section-Tags wird angezeigt.')
      }));
      notify?.(message, 'error');
    }
  }

  function closeLyricTagPreview() {
    setLyricTagPreview(EMPTY_LYRIC_TAG_PREVIEW);
  }

  function applyLyricVocalTags(suggestion, taggedTextOverride = '') {
    const lyricTags = suggestionLyricVocalTags(suggestion);
    if (!lyricTags.length) return;
    const nextText = String(taggedTextOverride || '').trim();
    const finalText = nextText || mergeLyricVocalTagsIntoPrompt(prompt, lyricTags);
    if (finalText.length > STYLE_ENGINE_LYRICS_MAX_CHARS) {
      notify?.(t('music.messages.lyricTagsApplyTooLong', 'Songtext-Tags können nicht übernommen werden: {{current}} / {{limit}} Zeichen.', { current: finalText.length, limit: STYLE_ENGINE_LYRICS_MAX_CHARS }), 'error');
      return;
    }
    setPrompt(finalText);
    notify?.(t('music.messages.lyricTagsApplied', '{{count}} Songtext-Tag(s) übernommen.', { count: lyricTags.length }), 'success');
  }

  function applyPreviewedLyricTags() {
    if (!lyricTagPreview.open || !lyricTagPreview.suggestion || !String(lyricTagPreview.taggedText || '').trim() || lyricTagPreview.loading) return;
    applyLyricVocalTags(lyricTagPreview.suggestion, lyricTagPreview.taggedText);
    closeLyricTagPreview();
  }

  async function copyTextToClipboard(text, successMessage) {
    const value = String(text || '');
    if (!value.trim()) return;
    try {
      await navigator.clipboard?.writeText(value);
      notify?.(successMessage, 'success');
    } catch {
      notify?.(t('common.copyFailed', 'Kopieren nicht möglich.'), 'error');
    }
  }

  function openStyleConsultation(suggestion) {
    const draft = {
      title: suggestion?.title || t('music.aiStyleTitle', 'KI-Style'),
      style: suggestion?.style || '',
      reason: suggestion?.reason || '',
      bpm: suggestion?.bpm || '',
      key_hint: suggestion?.key_hint || '',
      energy: suggestion?.energy || '',
      vocal_delivery: suggestion?.vocal_delivery || '',
      instruments: suggestionInstruments(suggestion),
      arrangement: suggestionArrangement(suggestion),
      lyric_vocal_tags: suggestionLyricVocalTags(suggestion),
      negative_tags: suggestionNegativeTags(suggestion),
      scores: suggestion?.scores || null,
      role: suggestion?.role || ''
    };
    setStyleConsultation({ open: true, suggestion, draft, messages: [], input: '', loading: false, error: '' });
  }

  function closeStyleConsultation() {
    setStyleConsultation((current) => ({ ...current, open: false, loading: false, error: '' }));
  }

  async function sendStyleConsultationMessage(messageOverride = '') {
    const message = String(messageOverride || styleConsultation.input || '').trim();
    const draft = styleConsultation.draft;
    if (!message || !draft || styleConsultation.loading) return;
    const nextMessages = [...(styleConsultation.messages || []), { role: 'user', content: message }];
    setStyleConsultation((current) => ({ ...current, messages: nextMessages, input: '', loading: true, error: '' }));
    try {
      const response = await api.assistant.styleConsultation({
        lyrics: prompt,
        message,
        draft,
        history: nextMessages.slice(-10),
        mode: 'advise_or_update'
      });
      const assistantMessage = response?.assistant_message || t('music.messages.styleConsultationChecked', 'Ich habe die Zusammenstellung geprüft.');
      const updatedDraft = response?.updated_draft || null;
      setStyleConsultation((current) => ({
        ...current,
        draft: updatedDraft || current.draft,
        messages: [...nextMessages, { role: 'assistant', content: assistantMessage }],
        loading: false,
        error: ''
      }));
    } catch (err) {
      const messageText = err?.message || t('music.messages.styleConsultationFailed', 'KI-Beratung konnte nicht durchgeführt werden.');
      setStyleConsultation((current) => ({ ...current, loading: false, error: messageText }));
      notify?.(messageText, 'error');
    }
  }

  function applyStyleDraft(draft, includeNegative = true) {
    if (!draft?.style) return;
    applyAiStyle(draft, { includeNegative });
    closeStyleConsultation();
  }

  async function saveAiStyle(suggestion) {
    const nextStyle = String(suggestion?.style || '').trim();
    if (!nextStyle) return;
    try {
      const saved = await api.library.createStyle({
        name: suggestion?.title || t('music.aiStyleNamed', 'KI-Style {{date}}', { date: new Date().toLocaleString('de-DE') }),
        style_text: nextStyle,
        description: suggestion?.reason || t('music.messages.aiStyleDescription', 'KI-generierter Suno-Style aus dem Musikbereich.'),
        tags: 'ki,suno,style',
        is_favorite: false,
        profile_json: buildStyleProfileJson(suggestion)
      });
      applyAiStyle(suggestion);
      await onRefresh?.();
      notify?.(t('music.messages.styleSavedApplied', 'Style „{{name}}“ gespeichert und übernommen.', { name: saved?.name || suggestion?.title || t('music.aiStyleFallback', 'KI-Vorschlag') }), 'success');
    } catch (err) {
      notify?.(err?.message || t('music.messages.styleSaveFailed', 'Style konnte nicht gespeichert werden.'), 'error');
    }
  }

  function buildVoicePayload(options = {}) {
    const officialSunoNames = Boolean(options.officialSunoNames);
    if (instrumental) return {};
    const voiceId = String(selectedVoice?.voice_id || selectedVoice?.persona_id || '').trim();
    if (!voiceId) return {};

    if (selectedVoice?.source_type === 'persona') {
      return officialSunoNames
        ? { personaId: voiceId, personaModel: 'style_persona' }
        : { persona_id: voiceId, persona_model: 'style_persona' };
    }

    return officialSunoNames
      ? { voice_id: voiceId, personaId: voiceId, personaModel: 'voice_persona' }
      : { voice_id: voiceId, persona_id: voiceId, persona_model: 'voice_persona' };
  }

  function buildAdvancedPayload(options = {}) {
    const officialSunoNames = Boolean(options.officialSunoNames);
    const base = {
      model,
      title: title || selectedAsset?.title || 'Suno Operation',
      prompt: prompt || undefined,
      style: limitForSunoField(style || operationTags, styleLimit) || undefined,
      ...(officialSunoNames
        ? {
            negativeTags: negativeTags || undefined,
            vocalGender: vocalGender || undefined
          }
        : {
            negative_tags: negativeTags || undefined,
            vocal_gender: vocalGender || undefined
          }),
      styleWeight: numberOrNull(styleWeight),
      weirdnessConstraint: numberOrNull(weirdnessConstraint),
      audioWeight: numberOrNull(audioWeight),
      ...buildVoicePayload({ officialSunoNames })
    };
    Object.keys(base).forEach((key) => (base[key] === undefined || base[key] === null || base[key] === '') && delete base[key]);
    return base;
  }



  function buildSunoPackagePayload() {
    return {
      ...buildAdvancedPayload(),
      model,
    title: title || t('common.untitled', 'Unbenannt'),
      prompt,
      style: limitForSunoField(style, styleLimit),
      customMode,
      instrumental,
      negative_tags: negativeTags || undefined,
      vocal_gender: vocalGender || undefined,
    };
  }

  function clearMusicForm() {
    setTitle('');
    setPrompt('');
    setStyle('');
    setNegativeTags('');
    setStyleWeight('');
    setWeirdnessConstraint('');
    setAudioWeight('');
    setStyleSuggestions([]);
    setSafeCheckResult(null);
    setMasterPackageText('');
    setAbVariants([]);
  }

  async function runSafeCheck() {
    const payload = buildSunoPackagePayload();
    if (!String(payload.prompt || '').trim() && !String(payload.style || '').trim()) {
      notify?.(t('music.messages.safeCheckNeedsContent', 'Bitte zuerst Prompt/Lyrics oder Style eintragen.'), 'error');
      return null;
    }
    setSafeCheckLoading(true);
    try {
      const result = await api.music.safeCheck(payload);
      setSafeCheckResult(result);
      notify?.(t('music.messages.safeCheckResult', 'Suno-Safe-Check: Risiko {{risk}} ({{score}}/100).', { risk: result.risk || t('common.unknown', 'unbekannt'), score: result.score || 0 }), result.risk === 'high' ? 'error' : result.risk === 'medium' ? 'info' : 'success');
      return result;
    } catch (err) {
      notify?.(err?.message || t('music.messages.safeCheckFailed', 'Safe-Check fehlgeschlagen.'), 'error');
      return null;
    } finally {
      setSafeCheckLoading(false);
    }
  }

  async function createMasterPackage() {
    const payload = buildSunoPackagePayload();
    const lines = [
      `${t('common.title', 'Titel')}: ${payload.title || t('common.untitled', 'Unbenannt')}`,
      `Operation: ${operationMode}`,
      `${t('music.fields.model', 'Modell')}: ${payload.model}`,
      `Provider: ${generationProvider === 'opencli' ? 'OpenCLI' : 'SunoAPI'}`,
      `Custom Mode: ${payload.customMode ? t('common.yes', 'Ja') : t('common.no', 'Nein')}`,
      `Instrumental: ${payload.instrumental ? t('common.yes', 'Ja') : t('common.no', 'Nein')}`,
      `Voice/Persona: ${payload.persona_id || payload.voice_id || t('common.no', 'Nein')}`,
      '',
      'STYLE:',
      payload.style || '',
      '',
      payload.instrumental ? 'INSTRUMENTAL-BAUPLAN / PROMPT:' : 'LYRICS / PROMPT:',
      payload.prompt || '',
      '',
      'NEGATIVE TAGS:',
      payload.negative_tags || '',
      '',
      'ADVANCED:',
      `Vocal Gender: ${payload.vocal_gender || 'auto'}`,
      `Style Weight: ${payload.styleWeight ?? '—'}`,
      `Weirdness: ${payload.weirdnessConstraint ?? '—'}`,
      `Audio Weight: ${payload.audioWeight ?? '—'}`,
    ];
    const text = lines.join('\n');
    setMasterPackageText(text);
    try { await navigator.clipboard?.writeText(text); notify?.(t('music.messages.masterPackageCopied', 'Master-Paket wurde erstellt und kopiert.'), 'success'); } catch { notify?.(t('music.messages.masterPackageCreated', 'Master-Paket wurde erstellt.'), 'success'); }
  }

  function prepareAbVariants() {
    const baseStyle = style || 'cinematic modern production, clean mix, strong hook energy';
    const rows = [
      { label: t('music.abTest.variantA', 'Variante A · Original stärker'), style: `${baseStyle}, tighter arrangement, clearer hook focus, polished master`, note: t('music.abTest.variantANote', 'Sicherer Hauptversuch mit klarerer Struktur.') },
      { label: t('music.abTest.variantB', 'Variante B · Dunkler / härter'), style: `${baseStyle}, darker mood, heavier drums, deeper bass, more dramatic tension`, note: t('music.abTest.variantBNote', 'Mehr Druck und Atmosphäre.') },
      { label: t('music.abTest.variantC', 'Variante C · Eingängiger / größer'), style: `${baseStyle}, more catchy lead motif, wider chorus, radio-ready energy, bigger dynamics`, note: t('music.abTest.variantCNote', 'Mehr Ohrwurm und Release-Potenzial.') },
    ];
    setAbVariants(rows);
    notify?.(t('music.messages.abVariantsPrepared', 'A/B/C Varianten wurden vorbereitet.'), 'success');
  }

  function applyAbVariant(variant) {
    setStyle(variant.style);
    setOperationTags(variant.style);
    notify?.(t('music.messages.variantApplied', '{{label}} übernommen.', { label: variant.label }), 'success');
  }

  function applyWorkflowTemplate(kind) {
    if (kind === 'rap_voice') {
      setWizard(false); setOperationMode('generate'); setCustomMode(true); setInstrumental(false); setStartMode('lyrics');
      setNegativeTags(negativeTags || 'female vocals, low quality, distorted, off key');
      notify?.(t('music.messages.workflowRapVoicePrepared', 'Workflow „Rap mit Voice“ vorbereitet.'), 'info');
    } else if (kind === 'instrumental') {
      setWizard(false); setOperationMode('generate'); setCustomMode(true); setInstrumental(true); setSelectedVoiceId(''); setStartMode('instrumental');
      notify?.(t('music.messages.workflowInstrumentalPrepared', 'Workflow „Instrumental-Bauplan“ vorbereitet.'), 'info');
    } else if (kind === 'cover_video') {
      setWizard(false); setOperationMode('upload-cover'); setCustomMode(true);
      notify?.(t('music.messages.workflowCoverVideoPrepared', 'Workflow „Cover/Video“ vorbereitet. Nach dem Cover kannst du auf Music Video wechseln.'), 'info');
    } else if (kind === 'stems') {
      setWizard(false); setOperationMode('stem-separation'); setInstrumental(false); setCustomMode(false);
      notify?.(t('music.messages.workflowStemsPrepared', 'Workflow „Stem Separation“ vorbereitet.'), 'info');
    }
  }

  async function startTask(taskPromise, successText) {
    setLoading(true);
    try {
      const task = await taskPromise();
      notify?.(successText, 'success');
      if (onMusicStarted) await onMusicStarted(task);
      else await onRefresh?.();
    } catch (err) {
      notify?.(err.message || t('music.messages.operationFailed', 'Operation fehlgeschlagen.'), 'error');
    } finally {
      setLoading(false);
    }
  }

  async function submit(event) {
    event?.preventDefault?.();
    if (generationBlockedByLimits) {
      const message = generationLimitMessages.join(' ');
      notify?.(message, 'error');
      return;
    }
    const rawStyleForSubmit = String(style || operationTags || '').trim();
    const cleanedStyleForSubmit = limitForSunoField(rawStyleForSubmit, styleLimit);
    const payload = {
      model,
      customMode,
      instrumental,
      title: title || undefined,
      prompt: prompt || undefined,
      style: cleanedStyleForSubmit || undefined,
      negativeTags: negativeTags || undefined,
      vocalGender: vocalGender || undefined,
      styleWeight: numberOrNull(styleWeight),
      weirdnessConstraint: numberOrNull(weirdnessConstraint),
      audioWeight: numberOrNull(audioWeight),
      provider: generationProvider
    };
    Object.keys(payload).forEach((key) => (payload[key] === undefined || payload[key] === null || payload[key] === '') && delete payload[key]);

    if (styleLimit && rawStyleForSubmit && rawStyleForSubmit.length > styleLimit) {
      notify?.(t('music.messages.styleTrimmedForModel', 'Style wurde für {{model}} auf {{limit}} Zeichen gekürzt, damit SunoAPI die Generierung annimmt.', { model, limit: styleLimit }), 'info');
    }

    if (generationProvider === 'opencli') {
      if (runtime?.opencli && !openCliRuntime.enabled) {
        notify?.(t('music.messages.openCliDisabled', 'OpenCLI ist serverseitig deaktiviert. Setze SUNO_OPENCLI_ENABLED=true und starte FastAPI neu.'), 'error');
        return;
      }
      if (runtime?.opencli && !openCliRuntime.installed) {
        notify?.(t('music.messages.openCliMissing', 'OpenCLI wurde nicht gefunden. Installiere opencli auf dem Server oder prüfe SUNO_OPENCLI_BINARY.'), 'error');
        return;
      }
    }

    await startTask(
      () => generationProvider === 'opencli' ? api.music.generateOpenCli(payload) : api.music.generate(payload),
      generationProvider === 'opencli'
        ? t('music.messages.openCliQueued', 'OpenCLI-Generierung für „{{title}}“ wurde eingereiht. Status und Library aktualisieren sich nach Abschluss.', { title: title || t('common.untitled', 'Unbenannt') })
        : t('music.messages.songStarted', 'Dein Song „{{title}}“ wurde gestartet. Die automatische Statusprüfung läuft jetzt.', { title: title || t('common.untitled', 'Unbenannt') })
    );
  }

  async function useUploadedFileForCurrentOperation(result, message = t('music.messages.uploadApplied', 'Upload wurde für diese Operation übernommen.')) {
    const uploadedUrl = String(result?.uploaded_url || result?.url || '').trim();
    if (!uploadedUrl) {
      notify?.(t('music.messages.uploadNoUsableUrl', 'Upload abgeschlossen, aber SunoAPI hat keine verwendbare Upload-URL zurückgegeben.'), 'warning');
      await onRefresh?.({ silent: true });
      return;
    }
    setAudioUrl(uploadedUrl);
    if (result?.id) setSelectedUploadId(String(result.id));
    await onRefresh?.({ silent: true });
    notify?.(message, 'success');
  }

  async function uploadOperationFile(event) {
    event?.preventDefault?.();
    if (!operationUploadFile) return notify?.(t('music.messages.selectAudioFileFirst', 'Bitte zuerst eine Audiodatei auswählen.'), 'error');
    try {
      setOperationUploadBusy(true);
      const result = await api.files.uploadStream(operationUploadFile);
      setOperationUploadFile(null);
      await useUploadedFileForCurrentOperation(result, t('music.messages.fileUploadedApplied', 'Datei wurde hochgeladen und als Audio-URL für diese Operation übernommen.'));
    } catch (err) {
      notify?.(err?.message || t('music.messages.fileUploadFailed', 'Datei-Upload fehlgeschlagen.'), 'error');
    } finally {
      setOperationUploadBusy(false);
    }
  }

  async function uploadOperationUrl(event) {
    event?.preventDefault?.();
    const url = String(operationUploadUrl || '').trim();
    if (!url) return notify?.(t('music.messages.enterSourceUrlFirst', 'Bitte zuerst eine Quell-URL eintragen.'), 'error');
    try {
      setOperationUploadBusy(true);
      const result = await api.files.uploadUrl(url);
      setOperationUploadUrl('');
      await useUploadedFileForCurrentOperation(result, t('music.messages.urlUploadedApplied', 'URL wurde hochgeladen und als Audio-URL für diese Operation übernommen.'));
    } catch (err) {
      notify?.(err?.message || t('music.messages.urlUploadFailed', 'URL-Upload fehlgeschlagen.'), 'error');
    } finally {
      setOperationUploadBusy(false);
    }
  }

  async function submitAdvancedOperation(event) {
    event?.preventDefault?.();
    const base = buildAdvancedPayload();
    const assetId = Number(selectedAssetId);
    const directAudioUrl = audioUrl.trim();
    const hasUploadedUrl = Boolean(selectedUpload?.uploaded_url);

    const needsAudioSource = ['extend', 'upload-extend', 'upload-cover', 'add-instrumental', 'add-vocals'].includes(operationMode);
    if (selectedAsset && !canUseSelectedAssetForOperation(selectedAsset, operationMode)) {
      notify?.(localOnlyAssetHint(selectedAsset, t) || t('music.messages.operationDisabledForAsset', 'Diese Operation ist für das ausgewählte AudioAsset deaktiviert.'), 'info');
      return;
    }

    if (needsAudioSource && !assetId && !directAudioUrl && !hasUploadedUrl) {
      notify?.(t('music.messages.selectGeneratedAudioOrUrl', 'Bitte zuerst eine generierte Audiodatei auswählen oder eine Audio-URL eintragen.'), 'error');
      return;
    }

    if (operationMode === 'generate') return submit(event);

    if (operationMode === 'generate-lyrics') {
      if (!prompt.trim()) return notify?.(t('music.messages.generateLyricsNeedsPrompt', 'Für Generate Lyrics ist ein Themen-/Stil-Prompt erforderlich.'), 'error');
      return startTask(() => api.lyrics.generate({ prompt }), t('music.messages.lyricsGenerationStarted', 'Suno Lyrics-Generierung wurde gestartet.'));
    }

    if (operationMode === 'import-suno-song') {
      if (!sunoImportId.trim()) return notify?.(t('music.messages.enterSunoSongIdOrUrl', 'Bitte eine Suno Song-ID oder Suno-URL eintragen.'), 'error');
      return startTask(async () => {
        const result = await api.music.importSongFromSuno({
          song_id: sunoImportId.trim(),
          cache_audio: sunoImportCacheAudio,
          cache_cover: sunoImportCacheCover,
          overwrite_existing: sunoImportOverwrite
        });
        await onRefresh?.();
        return {
          id: result.task_local_id,
          task_id: `clip:${result.suno_song_id}`,
          status: result.ok ? 'SUCCESS' : 'FAILED',
          response_payload: result
        };
      }, sunoImportOverwrite ? t('music.messages.sunoClipUpdated', 'Suno-Clip wurde aktualisiert.') : t('music.messages.sunoClipImported', 'Suno-Clip wurde importiert.'));
    }

    if (operationMode === 'stem-separation') {
      const taskId = selectedTaskId();
      const audioId = selectedAudioId();
      if (!taskId || !audioId) return notify?.(t('music.messages.stemNeedsTaskAndAudio', 'Stem Separation benötigt Task-ID und Audio-ID einer Suno-Generierung.'), 'error');
      return startTask(() => api.audio.separate({ taskId, audioId, type: stemSeparationType }), t('music.messages.stemStarted', 'Stem Separation wurde gestartet.'));
    }

    if (operationMode === 'convert-wav') {
      const taskId = selectedTaskId();
      const audioId = selectedAudioId();
      if (!taskId || !audioId) return notify?.(t('music.messages.wavNeedsTaskAndAudio', 'Convert to WAV benötigt Task-ID und Audio-ID.'), 'error');
      return startTask(() => api.audio.wav({ taskId, audioId }), t('music.messages.wavStarted', 'WAV-Konvertierung wurde gestartet.'));
    }

    if (operationMode === 'midi') {
      const taskId = selectedTaskId();
      const audioId = selectedAudioId();
      if (!taskId) return notify?.(t('music.messages.midiNeedsTask', 'Generate MIDI benötigt mindestens eine Task-ID.'), 'error');
      return startTask(() => api.audio.midi({ taskId, audioId: audioId || undefined }), t('music.messages.midiStarted', 'MIDI-Erzeugung wurde gestartet.'));
    }

    if (operationMode === 'video') {
      const taskId = selectedTaskId();
      const audioId = selectedAudioId();
      if (!taskId || !audioId) return notify?.(t('music.messages.videoNeedsTaskAndAudio', 'Create Music Video benötigt Task-ID und Audio-ID.'), 'error');
      return startTask(() => api.music.video({ taskId, audioId, author: videoAuthor || undefined, domainName: videoDomain || undefined }), t('music.messages.videoStarted', 'Music Video wurde gestartet.'));
    }

    if (operationMode === 'sounds') {
      if (!prompt.trim()) return notify?.(t('music.messages.soundsNeedPrompt', 'Für Generate Sounds ist ein Prompt erforderlich.'), 'error');
      const payload = {
        prompt,
        model: soundModels.includes(model) ? model : 'V5',
        soundLoop,
        soundTempo: numberOrNull(soundTempo),
        soundKey: soundKey || undefined,
        grabLyrics
      };
      return startTask(() => api.music.sounds(payload), t('music.messages.soundsStarted', 'Sound-Generierung wurde gestartet.'));
    }

    if (operationMode === 'extend') {
      const continueAtValue = numberOrNull(continueAt);
      const useAutoContinueAt = Boolean(autoContinueAtEnabled && autoContinueAt);
      if (!useAutoContinueAt && (!continueAtValue || continueAtValue <= 0)) return notify?.(t('music.messages.extendNeedsValidTime', 'Bitte eine gültige Extend-Startzeit in Sekunden angeben.'), 'error');
      if (!prompt.trim()) return notify?.(t('music.messages.extendNeedsPrompt', 'Für Extend ist ein Prompt oder Songtext erforderlich.'), 'error');
      if (!style.trim() && !operationTags.trim()) return notify?.(t('music.messages.extendNeedsStyle', 'Für Extend sind Style/Tags erforderlich.'), 'error');
      if (!title.trim()) return notify?.(t('music.messages.extendNeedsTitle', 'Für Extend ist ein Titel erforderlich.'), 'error');
      const payload = {
        ...buildAdvancedPayload({ officialSunoNames: true }),
        defaultParamFlag: true,
        continueAt: continueAtValue || undefined,
        autoContinueAt: useAutoContinueAt || undefined
      };
      return startTask(() => api.archive.extend(assetId, payload), t('music.messages.extendStartedForAsset', 'Extend für „{{title}}“ wurde gestartet.', { title: assetTitle(selectedAsset, t) }));
    }

    if (operationMode === 'upload-extend') {
      const continueAtValue = numberOrNull(continueAt);
      const useAutoContinueAt = Boolean(autoContinueAtEnabled && autoContinueAt);
      if (!useAutoContinueAt && (!continueAtValue || continueAtValue <= 0)) return notify?.(t('music.messages.extendNeedsValidTime', 'Bitte eine gültige Extend-Startzeit in Sekunden angeben.'), 'error');
      if (!prompt.trim()) return notify?.(t('music.messages.uploadExtendNeedsPrompt', 'Für Upload And Extend ist ein Prompt oder Songtext erforderlich.'), 'error');
      if (!style.trim() && !operationTags.trim()) return notify?.(t('music.messages.uploadExtendNeedsStyle', 'Für Upload And Extend sind Style/Tags erforderlich.'), 'error');
      if (!title.trim()) return notify?.(t('music.messages.uploadExtendNeedsTitle', 'Für Upload And Extend ist ein Titel erforderlich.'), 'error');
      const payload = {
        ...buildAdvancedPayload({ officialSunoNames: true }),
        uploadUrl: selectedAudioUrl(),
        defaultParamFlag: true,
        instrumental,
        continueAt: continueAtValue || undefined,
        autoContinueAt: useAutoContinueAt || undefined
      };
      return startTask(() => api.music.uploadAndExtend(payload), t('music.messages.uploadExtendStarted', 'Upload And Extend Audio wurde gestartet.'));
    }

    if (operationMode === 'upload-cover') {
      if (!prompt.trim()) return notify?.(t('music.messages.uploadCoverNeedsPrompt', 'Für Upload And Cover Song ist ein Prompt oder Songtext erforderlich.'), 'error');
      const payload = {
        ...buildAdvancedPayload({ officialSunoNames: true }),
        uploadUrl: selectedAudioUrl(),
        customMode: customMode,
        instrumental: instrumental,
        prompt,
        style: style || undefined,
        title: title || `${selectedAsset?.title || 'Audio'} Cover`
      };
      return startTask(() => api.music.uploadAndCover(payload), t('music.messages.uploadCoverStarted', 'Upload And Cover Song wurde gestartet.'));
    }

    if (operationMode === 'cover-image') {
      const taskId = selectedTaskId();
      if (!taskId) return notify?.(t('music.messages.coverImagesNeedTask', 'Für Cover-Bilder ist eine Task-ID erforderlich.'), 'error');
      return startTask(() => api.music.cover({ taskId }), t('music.messages.coverImagesStarted', 'Cover-Bilder wurden gestartet.'));
    }

    if (operationMode === 'replace-section') {
      const taskId = selectedTaskId();
      const audioId = selectedAudioId();
      const tags = operationTags || style;
      const fullLyrics = (replaceFullLyrics || selectedAsset?.lyrics || selectedAsset?.prompt || prompt || '').trim();
      if (!taskId || !audioId) return notify?.(t('music.messages.replaceNeedsTaskAndAudio', 'Replace Section benötigt Task-ID und Audio-ID.'), 'error');
      if (!prompt.trim() || !tags.trim() || !title.trim()) return notify?.(t('music.messages.replaceNeedsFields', 'Replace Section benötigt Titel, Tags/Style und Prompt.'), 'error');
      if (!fullLyrics) return notify?.(t('music.messages.replaceNeedsFullLyrics', 'Replace Section benötigt vollständige Lyrics für fullLyrics.'), 'error');
      const payload = {
        taskId,
        audioId,
        title,
        prompt,
        tags,
        fullLyrics,
        infillStartS: numberOrNull(replaceStart),
        infillEndS: numberOrNull(replaceEnd),
        negativeTags: negativeTags || undefined
      };
      return startTask(() => api.music.replaceSection(payload), t('music.messages.replaceStarted', 'Replace Section wurde gestartet.'));
    }

    if (operationMode === 'persona') {
      const taskId = selectedTaskId();
      const audioId = selectedAudioId();
      if (!taskId || !audioId) return notify?.(t('music.messages.personaNeedsTaskAndAudio', 'Persona erstellen benötigt Task-ID und Audio-ID.'), 'error');
      const payload = {
        taskId,
        audioId,
        name: personaName || title || `${selectedAsset?.title || 'Audio'} Persona`,
        description: personaDescription || prompt || title || t('music.defaults.personaDescription', 'Gespeicherte Persona aus Song Studio'),
        vocalStart: numberOrNull(vocalStart),
        vocalEnd: numberOrNull(vocalEnd),
        style: style || undefined
      };
      return startTask(() => api.music.persona(payload), t('music.messages.personaStarted', 'Persona-Erstellung wurde gestartet.'));
    }

    if (operationMode === 'boost-style') {
      const content = style || operationTags || prompt;
      if (!content.trim()) return notify?.(t('music.messages.boostNeedsContent', 'Bitte zuerst einen Style oder Prompt zum Optimieren eingeben.'), 'error');
      return startTask(async () => {
        const result = await api.music.boostStyle({ content });
        const improved = result?.result_payload?.data || result?.response_payload?.data || result?.result_payload?.msg || '';
        if (typeof improved === 'string' && improved.trim()) setStyle(improved.trim());
        return result;
      }, t('music.messages.boostStarted', 'Style-Optimierung wurde gestartet.'));
    }

    if (operationMode === 'mashup') {
      const urls = mashupUrls.split(/[\n,]+/).map((item) => item.trim()).filter(Boolean);
      const selectedUrl = selectedAudioUrl();
      if (selectedUrl && !urls.includes(selectedUrl)) urls.unshift(selectedUrl);
      if (urls.length !== 2) return notify?.(t('music.messages.mashupNeedsTwoUrls', 'Mashup benötigt laut SunoAPI exakt zwei Audio-URLs.'), 'error');
      const payload = {
        uploadUrlList: urls,
        customMode,
        instrumental,
        model,
        prompt: prompt || undefined,
        style: style || undefined,
        title: title || undefined,
        vocalGender: vocalGender || undefined,
        styleWeight: numberOrNull(styleWeight),
        weirdnessConstraint: numberOrNull(weirdnessConstraint),
        audioWeight: numberOrNull(audioWeight)
      };
      return startTask(() => api.music.mashup(payload), t('music.messages.mashupStarted', 'Mashup wurde gestartet.'));
    }

    if (operationMode === 'add-instrumental') {
      const tags = operationTags || style;
      if (!tags.trim()) return notify?.(t('music.messages.addInstrumentalNeedsStyle', 'Für Add Instrumental sind Tags/Style erforderlich.'), 'error');
      const payload = {
        uploadUrl: selectedAudioUrl(),
        title: title || `${selectedAsset?.title || 'Audio'} Instrumental`,
        tags,
        negativeTags: negativeTags || 'low quality, distorted, noisy',
        vocalGender: vocalGender || undefined,
        styleWeight: numberOrNull(styleWeight),
        weirdnessConstraint: numberOrNull(weirdnessConstraint),
        audioWeight: numberOrNull(audioWeight),
        model: addModels.includes(model) ? model : 'V4_5PLUS'
      };
      if (assetId && !directAudioUrl) return startTask(() => api.archive.addInstrumental(assetId, payload), t('music.messages.addInstrumentalStartedForAsset', 'Add Instrumental für „{{title}}“ wurde gestartet.', { title: assetTitle(selectedAsset, t) }));
      return startTask(() => api.music.addInstrumental(payload), t('music.messages.addInstrumentalStarted', 'Add Instrumental wurde gestartet.'));
    }

    if (operationMode === 'add-vocals') {
      if (!prompt.trim()) return notify?.(t('music.messages.addVocalsNeedsPrompt', 'Für Add Voice/Vocals ist ein Vocal-/Lyrics-Prompt erforderlich.'), 'error');
      const payload = {
        uploadUrl: selectedAudioUrl(),
        prompt,
        title: title || `${selectedAsset?.title || 'Audio'} Vocals`,
        style: style || operationTags || 'German rap vocal, studio quality',
        negativeTags: negativeTags || 'low quality, distorted, off key',
        vocalGender: vocalGender || undefined,
        styleWeight: numberOrNull(styleWeight),
        weirdnessConstraint: numberOrNull(weirdnessConstraint),
        audioWeight: numberOrNull(audioWeight),
        model: addModels.includes(model) ? model : 'V4_5PLUS'
      };
      if (assetId && !directAudioUrl) return startTask(() => api.archive.addVocals(assetId, payload), t('music.messages.addVocalsStartedForAsset', 'Add Voice/Vocals für „{{title}}“ wurde gestartet.', { title: assetTitle(selectedAsset, t) }));
      return startTask(() => api.music.addVocals(payload), t('music.messages.addVocalsStarted', 'Add Voice/Vocals wurde gestartet.'));
    }
  }

  const canPrev = step > 0;
  const canNext = step < 4;
  const aiRuntimeLabel = styleSuggestionRuntime?.provider || styleSuggestionRuntime?.model
    ? `${styleSuggestionRuntime?.provider || 'Provider'} · ${styleSuggestionRuntime?.model || t('music.fields.model', 'Modell')}`
    : t('music.styleEngine.usesActiveAdminAi', 'nutzt die aktive KI-Konfiguration aus dem Adminbereich');
  const styleBatchingInfo = styleSuggestionRuntime?.style_batching;
  const styleBatchingLabel = styleBatchingInfo
    ? t('music.styleEngine.batchingStatus', 'Batching: {{mode}} · {{requests}} Request(s) · Batchgröße {{batchSize}}{{profile}}', {
      mode: styleBatchingInfo.mode || 'auto',
      requests: styleBatchingInfo.request_count || 1,
      batchSize: styleBatchingInfo.batch_size || '—',
      profile: styleBatchingInfo.low_token_runtime ? t('music.styleEngine.lowTokenProfileSuffix', ' · Low-Token-Profil') : ''
    })
    : '';

  const voiceSelector = voices.length > 0 ? (
    <label>Voice / Persona
      <select value={selectedVoiceId} onChange={(event) => setSelectedVoiceId(event.target.value)}>
        <option value="">{t('music.fields.noVoice', 'Keine Voice verwenden')}</option>
        {voices.map((voice) => <option key={voice.id} value={voice.id}>{voiceLabel(voice, t)}</option>)}
      </select>
    </label>
  ) : null;

  const audioSelector = !['generate', 'generate-lyrics', 'import-suno-song', 'sounds', 'boost-style'].includes(operationMode) ? (
    <>
      <label>{t('music.fields.selectGeneratedAudio', 'Generierte Audio auswählen')}
        <select value={selectedAssetId} onChange={(event) => setSelectedAssetId(event.target.value)}>
          <option value="">{t('music.fields.chooseAudio', 'Audio wählen…')}</option>
          {playableAssets.map((asset) => <option key={asset.id} value={asset.id}>{assetTitle(asset, t)}</option>)}
        </select>
      </label>
      {uploadUrlOptions.length > 0 && ['upload-extend', 'upload-cover', 'add-instrumental', 'add-vocals', 'mashup'].includes(operationMode) && (
        <label>{t('music.fields.uploadUrlFromFiles', 'Upload-URL aus Dateiablage')}
          <select value={selectedUploadId} onChange={(event) => setSelectedUploadId(event.target.value)}>
            <option value="">{t('music.fields.noUploadFile', 'Keine Upload-Datei')}</option>
            {uploadUrlOptions.map((file) => <option key={file.id} value={file.id}>{file.original_name || file.source_url || `Upload #${file.id}`}</option>)}
          </select>
        </label>
      )}
      {(['upload-extend', 'upload-cover', 'add-instrumental', 'add-vocals', 'mashup'].includes(operationMode)) && (
        <div className="wide nested-panel soft-panel operation-inline-upload-panel">
          <div className="row between align-start">
            <div>
              <p className="eyebrow">{t('music.uploadSource.eyebrow', 'Audioquelle für diese Operation')}</p>
              <h3>{t('music.uploadSource.title', 'Direkt hochladen oder URL verwenden')}</h3>
              <p className="muted">{t('music.uploadSource.text', 'Für Upload And Extend, Upload And Cover, Add Vocals und ähnliche Folgeaktionen kannst du die benötigte Audioquelle direkt hier vorbereiten. Die alte Dateiablage unter System bleibt nur als zentrale Übersicht/Expertenbereich.')}</p>
            </div>
          </div>
          <div className="form-grid two">
            <label>{t('music.uploadSource.directFile', 'Direktdatei hochladen')}
              <input type="file" accept="audio/*,.mp3,.wav,.m4a,.aac,.flac,.ogg,.webm" onChange={(event) => setOperationUploadFile(event.target.files?.[0] || null)} disabled={operationUploadBusy} />
            </label>
            <label>{t('music.uploadSource.sourceUrl', 'Quell-URL hochladen')}
              <input value={operationUploadUrl} onChange={(event) => setOperationUploadUrl(event.target.value)} placeholder="https://.../audio.mp3" disabled={operationUploadBusy} />
            </label>
          </div>
          <div className="button-row wrap">
            <button type="button" onClick={uploadOperationFile} disabled={operationUploadBusy || !operationUploadFile}>{t('music.uploadSource.uploadFileApply', 'Datei hochladen & übernehmen')}</button>
            <button type="button" onClick={uploadOperationUrl} disabled={operationUploadBusy || !operationUploadUrl.trim()}>{t('music.uploadSource.uploadUrlApply', 'URL hochladen & übernehmen')}</button>
          </div>
          <label>{t('music.uploadSource.usedAudioUrl', 'Verwendete Audio-URL')}
            <input value={audioUrl} onChange={(event) => setAudioUrl(event.target.value)} placeholder="https://.../audio.mp3" />
          </label>
        </div>
      )}
      {selectedAsset && localOnlyAssetHint(selectedAsset, t) && (
        <p className="wide warning-text">{localOnlyAssetHint(selectedAsset, t)}</p>
      )}
    </>
  ) : null;

  const operationModelOptions = operationMode === 'sounds'
    ? soundModels
    : operationMode === 'add-instrumental' || operationMode === 'add-vocals'
      ? addModels
      : models;

  const operationActionLabel = operationMode === 'generate'
    ? generationProvider === 'opencli' ? t('music.actions.generateOpenCli', 'Mit OpenCLI generieren') : t('music.actions.generateMusic', 'Musik generieren')
    : t('music.actions.startOperation', '{{operation}} starten', { operation: localizedOperationModes.find(([key]) => key === operationMode)?.[1] || t('music.operation', 'Operation') });

  const supportsAdvancedSunoControls = ['generate', 'extend', 'upload-extend', 'upload-cover', 'add-instrumental', 'add-vocals'].includes(operationMode);

  const generationProviderSelector = operationMode === 'generate' && openCliEnabled ? (
    <section className="wide generation-provider-panel">
      <div className="generation-provider-head">
        <div>
          <p className="eyebrow">{t('music.provider.eyebrow', 'Song-Erzeugung')}</p>
          <h3>{t('music.provider.title', 'Provider auswählen')}</h3>
          <p className="muted">{t('music.provider.text', 'SunoAPI bleibt der Standard. OpenCLI ist optional und importiert lokal erzeugte Audiodateien danach in die Library.')}</p>
        </div>
        <span className={generationProvider === 'opencli' && openCliReady ? 'status cached' : generationProvider === 'opencli' ? 'status error' : 'status'}>{generationProvider === 'opencli' ? openCliReady ? t('music.provider.openCliReady', 'OpenCLI bereit') : t('music.provider.openCliNotReady', 'OpenCLI nicht bereit') : t('music.provider.sunoActive', 'SunoAPI aktiv')}</span>
      </div>
      <div className="generation-provider-grid">
        <label>Provider
          <select value={generationProvider} onChange={(event) => setGenerationProvider(event.target.value)}>
            <option value="sunoapi">{t('music.provider.sunoOption', 'SunoAPI · bestehender Standard')}</option>
            {openCliEnabled && <option value="opencli">{t('music.provider.openCliOption', 'OpenCLI · lokaler Browser-Bridge-Provider')}</option>}
          </select>
        </label>
        <label>OpenCLI Status
          <input readOnly value={openCliRuntime.enabled ? openCliRuntime.installed ? t('music.provider.binaryReady', '{{binary}} bereit', { binary: openCliRuntime.binary || 'opencli' }) : t('music.provider.binaryMissing', '{{binary}} nicht gefunden', { binary: openCliRuntime.binary || 'opencli' }) : t('music.provider.disabledEnv', 'deaktiviert per .env')} />
        </label>
      </div>
      {generationProvider === 'opencli' && (
        <p className="muted small-status-line generation-provider-note">
          {t('music.provider.openCliNote', 'OpenCLI unterstützt hier Generate Music, Custom Lyrics, Instrumental, Style/Tags, Negative Tags, Style Weight und Weirdness. Voice/Persona, Vocal Gender, Audio Weight, Extend, Cover Song und Upload-Operationen bleiben weiterhin SunoAPI-Funktionen.')}
        </p>
      )}
    </section>
  ) : null;

  const advancedSunoControlFields = supportsAdvancedSunoControls ? (
    <section className="wide nested-panel soft-panel">
      <div className="row between align-start">
        <div>
          <p className="eyebrow">{t('music.advanced.eyebrow', 'Suno Advanced Controls')}</p>
          <h3>{t('music.advanced.title', 'Feinsteuerung optional')}</h3>
          <p className="muted">{t('music.advanced.text', 'Diese Werte werden nur gesetzt, wenn du sie ausfüllst.')}</p>
        </div>
      </div>
      <div className="form-grid two">
        <label>{t('music.advanced.negativeTags', 'Negative Tags')}
          <input value={negativeTags} onChange={(event) => setNegativeTags(event.target.value)} placeholder={t('music.placeholders.negativeTags', 'z. B. Heavy Metal, Aggressive Vocals')} />
        </label>
        <label>{t('music.advanced.vocalGender', 'Vocal Gender')}
          <select value={vocalGender} onChange={(event) => setVocalGender(event.target.value)}>
            <option value="">{t('music.advanced.auto', 'Automatisch')}</option>
            <option value="m">{t('music.advanced.male', 'männlich / m')}</option>
            <option value="f">{t('music.advanced.female', 'weiblich / f')}</option>
          </select>
        </label>
        <label>{t('music.advanced.styleWeight', 'Style Weight 0-1')}
          <input type="number" min="0" max="1" step="0.01" value={styleWeight} onChange={(event) => setStyleWeight(event.target.value)} placeholder="0.61" />
        </label>
        <label>{t('music.advanced.weirdness', 'Weirdness 0-1')}
          <input type="number" min="0" max="1" step="0.01" value={weirdnessConstraint} onChange={(event) => setWeirdnessConstraint(event.target.value)} placeholder="0.72" />
        </label>
        <label>{t('music.advanced.audioWeight', 'Audio Weight 0-1')}
          <input type="number" min="0" max="1" step="0.01" value={audioWeight} onChange={(event) => setAudioWeight(event.target.value)} placeholder="0.65" />
        </label>
      </div>
    </section>
  ) : null;

  const optionalOperationFields = (
    <>
      {audioSelector}
      {operationMode === 'generate-lyrics' && (
        <div className="wide nested-panel soft-panel">
          <p className="eyebrow">{t('music.operationEyebrows.sunoLyricsApi', 'Suno Lyrics API')}</p>
          <p className="muted">{t('music.operationHelp.generateLyrics', 'Nutze das große Prompt-Feld für Thema, Stimmung, Sprache, Genre und gewünschte Struktur. Das Ergebnis erscheint nach Abschluss als Task/Archiv-Eintrag.')}</p>
        </div>
      )}
      {operationMode === 'import-suno-song' && (
        <div className="wide nested-panel soft-panel">
          <p className="eyebrow">{t('music.importPublic.eyebrow', 'Öffentlicher Suno-Clip Import')}</p>
          <h3>{t('music.importPublic.title', 'Suno Song-ID oder URL importieren')}</h3>
          <p className="muted">{t('music.importPublic.text', 'Importiert einen einzelnen öffentlichen Suno-Clip in Songs, AudioAssets und Tasks. Lokale Funktionen bleiben aktiv; SunoAPI.org-Folgeaktionen werden für diesen Import deaktiviert.')}</p>
          <label className="wide">{t('music.importPublic.songIdOrUrl', 'Suno Song-ID oder URL')}
            <input value={sunoImportId} onChange={(event) => setSunoImportId(event.target.value)} placeholder={t('music.placeholders.sunoSongIdOrUrl', 'https://suno.com/song/96fdbd12-4ea1-41b4-a132-4b731ec6594e oder UUID')} />
          </label>
          <div className="button-row wrap">
            <label className="check"><input type="checkbox" checked={sunoImportCacheAudio} onChange={(event) => setSunoImportCacheAudio(event.target.checked)} /> {t('music.importPublic.cacheAudio', 'Audio lokal speichern')}</label>
            <label className="check"><input type="checkbox" checked={sunoImportCacheCover} onChange={(event) => setSunoImportCacheCover(event.target.checked)} /> {t('music.importPublic.cacheCover', 'Cover lokal speichern')}</label>
            <label className="check"><input type="checkbox" checked={sunoImportOverwrite} onChange={(event) => setSunoImportOverwrite(event.target.checked)} /> {t('music.importPublic.overwrite', 'Vorhandenen Import aktualisieren')}</label>
          </div>
        </div>
      )}
      {operationMode === 'stem-separation' && (
        <div className="wide nested-panel soft-panel">
          <p className="eyebrow">{t('music.operationEyebrows.stemSeparation', 'Stem Separation')}</p>
          <p className="muted">{t('music.operationHelp.stemSeparation', 'Die offizielle SunoAPI Stem Separation nutzt Task-ID und Audio-ID einer Suno-Generierung, nicht eine beliebige Audio-URL.')}</p>
          <label>{t('music.fields.stemType', 'Stem-Typ')}
            <select value={stemSeparationType} onChange={(event) => setStemSeparationType(event.target.value)}>
              <option value="separate_vocal">separate_vocal · Vocal + Instrumental</option>
              <option value="split_stem">split_stem · mehrspurige Stem-Aufteilung</option>
            </select>
          </label>
        </div>
      )}
      {operationMode === 'convert-wav' && (
        <div className="wide nested-panel soft-panel">
          <p className="eyebrow">{t('music.operationEyebrows.convertToWav', 'Convert to WAV')}</p>
          <p className="muted">{t('music.operationHelp.convertWav', 'Task-ID und Audio-ID werden aus der ausgewählten Datei übernommen, können aber manuell überschrieben werden.')}</p>
        </div>
      )}
      {(operationMode === 'extend' || operationMode === 'upload-extend') && (
        <>
          {autoContinueAtEnabled && (
            <label className="check"><input type="checkbox" checked={Boolean(autoContinueAt)} onChange={(event) => setAutoContinueAt(event.target.checked)} /> {t('music.fields.autoContinueAt', 'continueAt automatisch per Audioanalyse berechnen')}</label>
          )}
          <label>{t('music.fields.continueAt', 'Extend ab Sekunde (continueAt)')}
            <input type="number" min="1" step="0.1" value={continueAt} onChange={(event) => setContinueAt(event.target.value)} placeholder={autoContinueAtEnabled && autoContinueAt ? t('music.placeholders.continueAtFallback', 'Fallback, z. B. 60') : t('music.placeholders.continueAt', 'z. B. 60')} />
          </label>
        </>
      )}
      {operationMode === 'sounds' && (
        <>
          <label>{t('music.fields.soundTempo', 'Sound Tempo optional')}
            <input type="number" value={soundTempo} onChange={(event) => setSoundTempo(event.target.value)} placeholder={t('music.placeholders.soundTempo', 'z. B. 100')} />
          </label>
          <label>{t('music.fields.soundKey', 'Sound Key optional')}
            <input value={soundKey} onChange={(event) => setSoundKey(event.target.value)} placeholder={t('music.placeholders.soundKey', 'z. B. C minor')} />
          </label>
          <label className="check"><input type="checkbox" checked={soundLoop} onChange={(event) => setSoundLoop(event.target.checked)} /> {t('music.fields.createLoop', 'Loop erzeugen')}</label>
          <label className="check"><input type="checkbox" checked={grabLyrics} onChange={(event) => setGrabLyrics(event.target.checked)} /> {t('music.fields.grabLyrics', 'Lyrics erfassen')}</label>
        </>
      )}
      {operationMode === 'add-instrumental' && (
        <label className="wide">{t('music.fields.instrumentalStyleTags', 'Tags / Instrumental Style')}
          <textarea rows={3} value={operationTags} onChange={(event) => setOperationTags(event.target.value)} placeholder={t('music.placeholders.instrumentalStyleTags', 'Relaxing Piano, Ambient, Boom Bap, Hard Drums…')} />
        </label>
      )}
      {(['cover-image', 'replace-section', 'persona', 'convert-wav', 'midi', 'video', 'stem-separation'].includes(operationMode)) && (
        <>
          <label>Task-ID
            <input value={taskIdInput} onChange={(event) => setTaskIdInput(event.target.value)} placeholder={selectedAsset?.suno_task_id || 'Task-ID'} />
          </label>
          <label>Audio-ID
            <input value={audioIdInput} onChange={(event) => setAudioIdInput(event.target.value)} placeholder={selectedAsset?.audio_id || 'Audio-ID'} />
          </label>
        </>
      )}
      {operationMode === 'video' && (
        <>
          <label>{t('music.fields.authorOptional', 'Autor optional')}
            <input value={videoAuthor} onChange={(event) => setVideoAuthor(event.target.value)} placeholder={t('music.placeholders.videoAuthor', 'z.B. KlangNeural')} />
          </label>
          <label>{t('music.fields.domainOptional', 'Domain optional')}
            <input value={videoDomain} onChange={(event) => setVideoDomain(event.target.value)} placeholder={t('music.placeholders.videoDomain', 'z.B. klangneural.de')} />
          </label>
        </>
      )}
      {operationMode === 'replace-section' && (
        <>
          <label>{t('music.fields.replaceStart', 'Replace Start Sek.')}
            <input type="number" min="0" step="0.01" value={replaceStart} onChange={(event) => setReplaceStart(event.target.value)} />
          </label>
          <label>{t('music.fields.replaceEnd', 'Replace Ende Sek.')}
            <input type="number" min="0" step="0.01" value={replaceEnd} onChange={(event) => setReplaceEnd(event.target.value)} />
          </label>
          <label className="wide">{t('music.fields.replaceTagsStyle', 'Tags / Style für Ersatz')}
            <textarea rows={3} value={operationTags || style} onChange={(event) => setOperationTags(event.target.value)} placeholder={t('music.placeholders.replaceTagsStyle', 'Jazz, Boom Bap, Dark Rap...')} />
          </label>
          <label className="wide">{t('music.fields.negativeTagsOptional', 'Negative Tags optional')}
            <input value={negativeTags} onChange={(event) => setNegativeTags(event.target.value)} placeholder={t('music.placeholders.negativeQuality', 'z. B. low quality, distorted, off key')} />
          </label>
          <label className="wide">{t('music.fields.fullLyrics', 'Vollständige Lyrics / fullLyrics')}
            <textarea rows={7} value={replaceFullLyrics} onChange={(event) => setReplaceFullLyrics(event.target.value)} placeholder={selectedAsset?.lyrics || selectedAsset?.prompt || t('music.placeholders.replaceFullLyrics', 'Vollständigen Songtext einfügen. Wird für die Replace-Section API als fullLyrics gesendet.')} />
          </label>
        </>
      )}
      {operationMode === 'persona' && (
        <>
          <label>{t('music.fields.personaName', 'Persona Name')}
            <input value={personaName} onChange={(event) => setPersonaName(event.target.value)} placeholder={t('music.placeholders.personaName', 'z.B. Grimy Rap Voice')} />
          </label>
          <label>{t('music.fields.vocalStart', 'Vocal Start')}
            <input type="number" min="0" step="0.1" value={vocalStart} onChange={(event) => setVocalStart(event.target.value)} />
          </label>
          <label>{t('music.fields.vocalEnd', 'Vocal Ende')}
            <input type="number" min="0" step="0.1" value={vocalEnd} onChange={(event) => setVocalEnd(event.target.value)} />
          </label>
          <label className="wide">{t('music.fields.personaDescription', 'Persona Beschreibung')}
            <textarea rows={3} value={personaDescription} onChange={(event) => setPersonaDescription(event.target.value)} placeholder={t('music.placeholders.personaDescription', 'Stimme, Energie, Flow, Sprache, Charakter...')} />
          </label>
        </>
      )}
      {operationMode === 'mashup' && (
        <label className="wide">{t('music.fields.mashupUrls', 'Mashup Audio-URLs')}
          <textarea rows={4} value={mashupUrls} onChange={(event) => setMashupUrls(event.target.value)} placeholder={t('music.placeholders.mashupUrls', 'Eine URL pro Zeile. Optional wird die ausgewählte Audio-Datei ergänzt.')} />
        </label>
      )}
      {advancedSunoControlFields}
    </>
  );

  const styleSuggestionPanel = (
    <section className="panel ai-style-panel">
      <div className="ai-style-header">
        <div>
          <p className="eyebrow">{t('music.styleEngine.eyebrow', 'KI Style Engine')}</p>
          <h2>{t('music.styleEngine.title', 'Optimale Suno-Styles aus Lyrics erzeugen')}</h2>
          <p className="muted">{t('music.styleEngine.text', 'Die KI liest Songtext, Vocal Tags, Stimmung und Zusatzwünsche und erstellt direkt übernehmbare Suno-Style-Prompts mit Instrumenten, Negative Tags und Score-Einschätzung.')}</p>
          <p className="muted small-status-line">{t('music.styleEngine.activeAi', 'Aktive KI')}: {aiRuntimeLabel}</p>
          {styleBatchingLabel && <p className="muted small-status-line">{styleBatchingLabel}</p>}
          <p className="muted small-status-line">{t('music.styleEngine.limits', 'Limits')}: {t('music.styleEngine.lyricsLimit', 'Songtext {{count}} Zeichen', { count: STYLE_ENGINE_LYRICS_MAX_CHARS })} · {t('music.styleEngine.musicStyleLimit', 'Music Style {{count}} Zeichen', { count: STYLE_ENGINE_MUSIC_STYLE_MAX_CHARS })}</p>
        </div>
        <button type="button" className="primary" onClick={generateStyleSuggestions} disabled={styleSuggestionLoading || !prompt.trim()}>
          {styleSuggestionLoading ? <Loader2 size={16} className="spin-icon" /> : <Sparkles size={16} />}
          {styleSuggestionLoading ? t('music.styleEngine.aiWorking', 'KI arbeitet…') : t('music.styleEngine.generateStyles', 'Styles generieren')}
        </button>
      </div>

      <div className="ai-style-strategy-grid">
        {localizedStyleVariantStrategies.map(([key, label, description]) => (
          <button key={key} type="button" className={styleVariantStrategy === key ? 'active' : ''} onClick={() => setStyleVariantStrategy(key)}>
            <strong>{label}</strong>
            <span>{description}</span>
          </button>
        ))}
      </div>

      <div className="form-grid ai-style-controls">
        <label>{t('music.styleEngine.amount', 'Menge')}
          <input type="number" min="1" max="5" value={styleAmount} onChange={(event) => setStyleAmount(clampStyleAmount(event.target.value))} />
        </label>
        <label>{t('music.styleEngine.bpmMin', 'BPM von')}
          <input type="number" min={STYLE_ENGINE_BPM_MIN} max={STYLE_ENGINE_BPM_MAX} step="1" value={styleBpmMin} onChange={(event) => setStyleBpmMin(event.target.value)} placeholder="94" />
        </label>
        <label>{t('music.styleEngine.bpmMax', 'BPM bis')}
          <input type="number" min={STYLE_ENGINE_BPM_MIN} max={STYLE_ENGINE_BPM_MAX} step="1" value={styleBpmMax} onChange={(event) => setStyleBpmMax(event.target.value)} placeholder="100" />
        </label>
        <div className="wide ai-style-feature-toggles" role="group" aria-label={t('music.styleEngine.featureAria', 'Style-Features auswählen')}>
          {localizedStyleFeatureOptions.map(([key, label, description]) => {
            const active = styleFeatureOptions[key] !== false;
            return (
              <button
                key={key}
                type="button"
                className={`mini-toggle-button ${active ? 'active' : ''}`}
                aria-pressed={active}
                title={description}
                onClick={() => setStyleFeatureOptions((current) => {
                  const normalized = normalizeStyleFeatures(current);
                  return { ...normalized, [key]: normalized[key] === false };
                })}
              >
                <span className="mini-toggle-dot" aria-hidden="true" />
                {label}
              </button>
            );
          })}
        </div>
        <label className="wide">{t('music.styleEngine.extraPrompt', 'Zusatzprompt optional')}
          <textarea rows={3} value={styleExtraPrompt} onChange={(event) => setStyleExtraPrompt(event.target.value)} placeholder={t('music.placeholders.styleExtraPrompt', 'z.B. mehr grimy NYC boom bap, härtere Drums, männlicher Rapper, 101 BPM, Patwa Hook…')} />
        </label>
      </div>

      {styleSuggestionError && <p className="form-error">{styleSuggestionError}</p>}

      {styleSuggestions.length > 0 && (
        <div className="ai-style-results">
          {styleSuggestions.map((suggestion, index) => {
            const scores = suggestion?.scores && typeof suggestion.scores === 'object' ? suggestion.scores : null;
            const negative = suggestionNegativeTags(suggestion);
            const lyricTags = suggestionLyricVocalTags(suggestion);
            const suggestedTitle = suggestionSongTitle(suggestion);
            return (
              <article className="ai-style-card" key={`${suggestion.title || 'style'}-${index}`}>
                <div>
                  <span>{suggestion.role || t('music.styleEngine.suggestionNumber', 'Vorschlag {{number}}', { number: index + 1 })}</span>
                  <h3>{suggestion.title || t('music.styleEngine.aiStyleNumber', 'KI-Style {{number}}', { number: index + 1 })}</h3>
                </div>
                {suggestedTitle && (
                  <div className="ai-song-title-suggestion">
                    <span>{t('music.styleEngine.suggestedSongTitle', 'Songtitel')}</span>
                    <strong>{suggestedTitle}</strong>
                    <button type="button" onClick={() => applySuggestedSongTitle(suggestion)}>{t('music.actions.applySongTitle', 'Titel übernehmen')}</button>
                  </div>
                )}
                {(suggestion.bpm || suggestion.energy || suggestion.vocal_delivery) && (
                  <div className="ai-style-meta-row">
                    {suggestion.bpm && <span>BPM {suggestion.bpm}</span>}
                    {suggestion.energy && <span>{suggestion.energy}</span>}
                    {suggestion.vocal_delivery && <span>{suggestion.vocal_delivery}</span>}
                  </div>
                )}
                <p className="ai-style-text">{suggestion.style}</p>
                {suggestion.reason && <p className="muted">{suggestion.reason}</p>}
                {scores && (
                  <div className="ai-score-row">
                    {formatScorePercent(scores.fit) && <span>Fit {formatScorePercent(scores.fit)}</span>}
                    {formatScorePercent(scores.hook_potential) && <span>Hook {formatScorePercent(scores.hook_potential)}</span>}
                    {formatScorePercent(scores.suno_clarity) && <span>Klarheit {formatScorePercent(scores.suno_clarity)}</span>}
                    {formatScorePercent(scores.risk) && <span>{t('music.safeCheck.risk', 'Risiko')} {formatScorePercent(scores.risk)}</span>}
                  </div>
                )}
                {negative && <p className="ai-negative-tags"><strong>Negative:</strong> {negative}</p>}
                {lyricTags.length > 0 && (
                  <section className="ai-vocal-tag-preview-card">
                    <div>
                      <span className="eyebrow">{t('music.lyricTags.title', 'Songtext-Tags')}</span>
                      <strong>{t('music.lyricTags.generatedCount', '{{count}} passende Section-Tags erzeugt', { count: lyricTags.length })}</strong>
                      <small>{t('music.lyricTags.previewHint', 'Vor Übernahme als vollständigen Songtext im Modal prüfen.')}</small>
                    </div>
                    <button type="button" onClick={() => openLyricTagPreview(suggestion)}>{t('music.actions.openPreview', 'Vorschau öffnen')}</button>
                  </section>
                )}
                <div className="button-row wrap">
                  <button type="button" className="primary" onClick={() => applyAiStyle(suggestion)}>{t('music.actions.applyMasterStyle', 'Master Style übernehmen')}</button>
                  {lyricTags.length > 0 && <button type="button" onClick={() => openLyricTagPreview(suggestion)}>{t('music.actions.viewLyricTags', 'Songtext-Tags ansehen')}</button>}
                  {negative && <button type="button" onClick={() => applyNegativeTagsOnly(suggestion, 'append')}>{t('music.actions.appendNegativeOnly', 'Nur Negative anhängen')}</button>}
                  <button type="button" onClick={() => openStyleConsultation(suggestion)}>{t('music.actions.refineWithAi', 'Mit KI verfeinern')}</button>
                  <button type="button" onClick={() => saveAiStyle(suggestion)}>{t('music.actions.saveAsStyle', 'Als Style speichern')}</button>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );

  const styleConsultationModal = (
    <Modal open={styleConsultation.open} title={t('music.styleConsultation.title', 'Style mit KI verfeinern')} onClose={closeStyleConsultation} wide>
      <div className="style-consultation-modal stack">
        <section className="nested-panel">
          <p className="eyebrow">{t('music.styleConsultation.workingVersion', 'Arbeitsversion')}</p>
          <h3>{styleConsultation.draft?.title || t('music.aiStyleTitle', 'KI-Style')}</h3>
          <p className="ai-style-text">{styleConsultation.draft?.style || t('music.styleConsultation.noStyleLine', 'Keine Style-Zeile vorhanden.')}</p>
          {styleConsultation.draft?.negative_tags && <p className="ai-negative-tags"><strong>Negative:</strong> {styleConsultation.draft.negative_tags}</p>}
          {suggestionLyricVocalTags(styleConsultation.draft).length > 0 && (
            <section className="ai-vocal-tag-preview-card">
              <div>
                <span className="eyebrow">{t('music.lyricTags.title', 'Songtext-Tags')}</span>
                <strong>{t('music.styleConsultation.workingTagCount', '{{count}} Section-Tags in der Arbeitsversion', { count: suggestionLyricVocalTags(styleConsultation.draft).length })}</strong>
                <small>{t('music.styleConsultation.tagModalHint', 'Im Modal als vollständigen Songtext prüfen, kopieren oder übernehmen.')}</small>
              </div>
              <button type="button" onClick={() => openLyricTagPreview(styleConsultation.draft)}>{t('music.actions.openPreview', 'Vorschau öffnen')}</button>
            </section>
          )}
          <div className="button-row wrap">
            <button type="button" className="primary" onClick={() => applyStyleDraft(styleConsultation.draft, true)}>{t('music.actions.applyMaster', 'Master übernehmen')}</button>
            <button type="button" onClick={() => applyStyleDraft(styleConsultation.draft, false)}>{t('music.actions.applyStyleOnly', 'Nur Style übernehmen')}</button>
            {suggestionLyricVocalTags(styleConsultation.draft).length > 0 && <button type="button" onClick={() => openLyricTagPreview(styleConsultation.draft)}>{t('music.actions.viewLyricTags', 'Songtext-Tags ansehen')}</button>}
          </div>
        </section>
        <div className="style-consultation-chips">
          {styleConsultationChips.map((chip) => (
            <button key={chip} type="button" onClick={() => sendStyleConsultationMessage(chip)} disabled={styleConsultation.loading}>{chip}</button>
          ))}
        </div>
        <div className="style-consultation-chat">
          {(styleConsultation.messages || []).map((message, index) => (
            <div key={`${message.role}-${index}`} className={`style-consultation-message ${message.role === 'assistant' ? 'assistant' : 'user'}`}>
              <strong>{message.role === 'assistant' ? t('lyricsStudio.ai', 'KI') : t('lyricsStudio.you', 'Du')}</strong>
              <p>{message.content}</p>
            </div>
          ))}
          {!styleConsultation.messages?.length && <p className="muted">{t('music.styleConsultation.emptyHint', 'Frag z.B. „Mach die Hook größer, aber die Verse roher.“ Die App übernimmt nichts automatisch.')}</p>}
        </div>
        {styleConsultation.error && <p className="form-error">{styleConsultation.error}</p>}
        <div className="style-consultation-input-row">
          <textarea rows={3} value={styleConsultation.input || ''} onChange={(event) => setStyleConsultation((current) => ({ ...current, input: event.target.value }))} placeholder={t('music.styleConsultation.placeholder', 'Wunsch an die KI-Beratung…')} />
          <button type="button" className="primary" disabled={styleConsultation.loading || !String(styleConsultation.input || '').trim()} onClick={() => sendStyleConsultationMessage()}>
            {styleConsultation.loading ? <Loader2 size={16} className="spin-icon" /> : <Sparkles size={16} />}
            {t('music.actions.send', 'Senden')}
          </button>
        </div>
      </div>
    </Modal>
  );

  const lyricPreviewCharCount = String(lyricTagPreview.taggedText || '').length;
  const lyricPreviewOverLimit = lyricPreviewCharCount > STYLE_ENGINE_LYRICS_MAX_CHARS;

  const lyricTagPreviewModal = (
    <Modal open={lyricTagPreview.open} title={t('music.lyricTags.modalTitle', 'Songtext-Tags prüfen · {{title}}', { title: lyricTagPreview.title || t('music.aiStyleTitle', 'KI-Style') })} onClose={closeLyricTagPreview} wide contentClassName="lyric-tag-preview-modal-content">
      <div className="lyric-tag-preview-modal stack">
        <section className="nested-panel">
          <p className="eyebrow">{t('music.lyricTags.previewBeforeApply', 'Vorschau vor Übernahme')}</p>
          <h3>{t('music.lyricTags.fullTaggedLyrics', 'Vollständiger Songtext mit passenden Section-Tags')}</h3>
          <p className="muted">{t('music.lyricTags.text', 'Der Originaltext bleibt erhalten. Bestehende Abschnittsmarker werden gezielt durch die neuen Tags ersetzt; fehlende Tags werden oben ergänzt.')}</p>
          {lyricTagPreview.loading && <p className="muted"><Loader2 size={14} className="spin-icon" /> {t('music.lyricTags.generatingPreview', 'Vollständige Vorschau wird erzeugt…')}</p>}
          {lyricTagPreview.notes && <p className="muted small-status-line">{lyricTagPreview.notes}</p>}
          {lyricTagPreview.error && <p className="form-error">{lyricTagPreview.error}</p>}
          <div className="lyric-tag-preview-stats">
            <span>{lyricTagPreview.lyricTags.length || 0} Tags</span>
            <span className={lyricPreviewOverLimit ? 'over-limit' : ''}>{lyricPreviewCharCount} / {STYLE_ENGINE_LYRICS_MAX_CHARS} {t('music.chars', 'Zeichen')}</span>
          </div>
        </section>

        {lyricTagPreview.lyricTags.length > 0 && (
          <section className="ai-vocal-tag-details">
            <div className="row between align-start">
              <div>
                <p className="eyebrow">{t('music.lyricTags.detectedTags', 'Erkannte Tags')}</p>
                <strong>{t('music.lyricTags.sectionTagsFromStyle', 'Section-Tags aus dem gewählten Style')}</strong>
              </div>
              <button type="button" onClick={() => copyTextToClipboard(lyricTagPreview.tagText, t('music.messages.onlyTagsCopied', 'Nur Songtext-Tags kopiert.'))}>{t('music.actions.copyTagsOnly', 'Nur Tags kopieren')}</button>
            </div>
            <div className="ai-vocal-tag-list">
              {lyricTagPreview.lyricTags.map((item, tagIndex) => (
                <div className="ai-vocal-tag-item" key={`${item.section || 'section'}-${tagIndex}`}>
                  <span>{item.section || t('music.lyricTags.sectionNumber', 'Abschnitt {{number}}', { number: tagIndex + 1 })}</span>
                  <code>{item.tag}</code>
                  {item.reason && <small>{item.reason}</small>}
                </div>
              ))}
            </div>
          </section>
        )}

        <section className="lyric-tag-full-preview">
          <div className="row between align-start">
            <div>
              <p className="eyebrow">{t('music.lyricTags.taggedLyrics', 'Getaggter Songtext')}</p>
              <h3>{t('music.lyricTags.applyPreviewTitle', 'So wird der Text übernommen')}</h3>
            </div>
            <button type="button" disabled={lyricTagPreview.loading || !String(lyricTagPreview.taggedText || '').trim()} onClick={() => copyTextToClipboard(lyricTagPreview.taggedText, t('music.messages.fullTaggedLyricsCopied', 'Vollständiger getaggter Songtext kopiert.'))}>{t('music.actions.copyFullLyrics', 'Vollen Songtext kopieren')}</button>
          </div>
          <textarea readOnly rows={18} className={lyricPreviewOverLimit ? 'field-over-limit' : ''} value={lyricTagPreview.taggedText || ''} />
          {lyricPreviewOverLimit && <p className="field-limit-warning">{t('music.lyricTags.tooLongCannotApply', 'Dieser getaggte Songtext ist zu lang und kann nicht übernommen werden.')}</p>}
        </section>

        <div className="button-row wrap">
          <button type="button" className="primary" disabled={lyricTagPreview.loading || lyricPreviewOverLimit || !String(lyricTagPreview.taggedText || '').trim()} onClick={applyPreviewedLyricTags}>{t('music.actions.applyLyricTags', 'Songtext-Tags übernehmen')}</button>
          <button type="button" disabled={lyricTagPreview.loading || !String(lyricTagPreview.taggedText || '').trim()} onClick={() => copyTextToClipboard(lyricTagPreview.taggedText, t('music.messages.fullTaggedLyricsCopied', 'Vollständiger getaggter Songtext kopiert.'))}>{t('music.actions.copyToClipboard', 'In Zwischenablage kopieren')}</button>
          <button type="button" onClick={closeLyricTagPreview}>{t('common.close', 'Schließen')}</button>
        </div>
      </div>
    </Modal>
  );


  const safeCheckPanel = (safeCheckResult || safeCheckLoading) ? (
    <section className={`wide nested-panel safe-check-panel ${safeCheckResult?.risk || ''}`}>
      <div className="row between align-start">
        <div>
          <p className="eyebrow">{t('music.safeCheck.title', 'Suno-Safe-Check')}</p>
          <h3>{safeCheckLoading ? t('music.safeCheck.checkingRequest', 'Prüfe Request…') : t('music.safeCheck.riskScore', 'Risiko: {{risk}} · {{score}}/100', { risk: safeCheckResult?.risk || '—', score: safeCheckResult?.score ?? 0 })}</h3>
          <p className="muted">{t('music.safeCheck.text', 'Hilft vor allem bei Voice/Persona, sensiblen Begriffen und zu langen Prompts.')}</p>
        </div>
        <button type="button" onClick={runSafeCheck} disabled={safeCheckLoading}><RefreshCw size={15} className={safeCheckLoading ? 'spin-icon' : ''} /> {t('music.safeCheck.checkAgain', 'Erneut prüfen')}</button>
      </div>
      {safeCheckResult?.warnings?.length > 0 && <ul className="compact-advice-list">{safeCheckResult.warnings.map((item) => <li key={item}>{item}</li>)}</ul>}
      {safeCheckResult?.voice_used && <button type="button" onClick={() => { setSelectedVoiceId(''); setSafeCheckResult(null); notify?.(t('music.messages.voiceRemoved', 'Voice wurde entfernt. Bitte erneut prüfen oder generieren.'), 'info'); }}>{t('music.safeCheck.removeVoice', 'Voice entfernen')}</button>}
    </section>
  ) : null;

  const masterPackagePanel = masterPackageText ? (
    <section className="wide nested-panel master-package-panel">
      <div className="row between align-start">
        <div><p className="eyebrow">{t('music.masterPackage.title', 'Master-Paket')}</p><h3>{t('music.masterPackage.readyOverview', 'Generierfertige Übersicht')}</h3></div>
        <button type="button" onClick={() => navigator.clipboard?.writeText(masterPackageText)}><Copy size={15} /> {t('common.copy', 'Kopieren')}</button>
      </div>
      <pre>{masterPackageText}</pre>
    </section>
  ) : null;

  const abVariantPanel = abVariants.length ? (
    <section className="wide nested-panel ab-variant-panel">
      <p className="eyebrow">{t('music.abTest.eyebrow', 'A/B-Test-Modus')}</p>
      <h3>{t('music.abTest.title', '3 vorbereitete Varianten')}</h3>
      <div className="variant-suggestion-grid">
        {abVariants.map((variant) => (
          <article key={variant.label} className="ai-style-card">
            <h4>{variant.label}</h4>
            <p className="ai-style-text">{variant.style}</p>
            <p className="muted">{variant.note}</p>
            <button type="button" className="primary" onClick={() => applyAbVariant(variant)}>{t('lyricsStudio.apply', 'Übernehmen')}</button>
          </article>
        ))}
      </div>
    </section>
  ) : null;

  return (
    <section className="page stack">
      <SectionHeader eyebrow={t('music.eyebrow', 'Create')} title={t('music.title', 'Musik generieren')}>
        <button type="button" className={wizard ? 'active' : ''} onClick={() => setWizard(true)}>Wizard</button>
        <button type="button" className={!wizard ? 'active' : ''} onClick={() => setWizard(false)}>{t('music.expertForm', 'Expertenformular')}</button>
      </SectionHeader>

      {styleConsultationModal}
      {lyricTagPreviewModal}

      <section className="panel workflow-template-panel">
        <div>
          <p className="eyebrow">{t('music.workflowTemplates.eyebrow', 'Workflow-Vorlagen')}</p>
          <h2>{t('music.workflowTemplates.title', 'Schnell vorbereiten')}</h2>
          <p className="muted">{t('music.workflowTemplates.text', 'Setzt nur vorhandene Felder im Musikformular und erzeugt keine doppelte Oberfläche.')}</p>
        </div>
        <div className="button-row wrap">
          <button type="button" onClick={() => applyWorkflowTemplate('rap_voice')}>{t('music.workflowTemplates.rapVoice', 'Rap mit Voice')}</button>
          <button type="button" onClick={() => applyWorkflowTemplate('instrumental')}>{t('music.workflowTemplates.instrumental', 'Instrumental-Bauplan')}</button>
          <button type="button" onClick={() => applyWorkflowTemplate('cover_video')}>{t('music.workflowTemplates.coverVideo', 'Cover / Video')}</button>
          <button type="button" onClick={() => applyWorkflowTemplate('stems')}>{t('music.workflowTemplates.stems', 'Stem Separation')}</button>
        </div>
      </section>

      <section className="panel task-status-panel">
        <div>
          <p className="eyebrow">{t('music.status.eyebrow', 'Suno Status')}</p>
          <h2>{t('music.status.title', 'Automatische Statusprüfung')}</h2>
          <p className="muted">{t('music.status.text', 'React prüft offene Tasks automatisch und lädt Library, Tasks und Benachrichtigungen nach.')}</p>
          <p className="muted small-status-line">
            {t('music.status.lastCheck', 'Letzte Prüfung')}: {taskRefreshState?.lastCheck ? new Date(taskRefreshState.lastCheck).toLocaleString('de-DE') : t('status.live.noneYet', 'noch keine')}
            {taskRefreshState?.lastMessage ? ` · ${taskRefreshState.lastMessage}` : ''}
            {taskRefreshState?.lastError ? ` · ${t('status.stats.error', 'Fehler')}: ${taskRefreshState.lastError}` : ''}
          </p>
        </div>
        <button type="button" onClick={onCheckStatus} disabled={taskRefreshState?.running}>
          <RefreshCw size={16} className={taskRefreshState?.running ? 'spin-icon' : ''} />
          {taskRefreshState?.running ? t('status.checking', 'Prüfe…') : t('music.status.checkNow', 'Status jetzt prüfen')}
        </button>
      </section>

      {wizard ? (
        <section className="panel wizard-shell">
          <div className="wizard-steps">
            {wizardStepLabels.map((label, index) => (
              <button key={label} type="button" className={step === index ? 'active' : ''} onClick={() => setStep(index)}>{index + 1}. {label}</button>
            ))}
          </div>

          {step === 0 && (
            <div className="wizard-step">
              <h2>{t('music.wizard.whatCreate', 'Was möchtest du erstellen?')}</h2>
              <div className="workflow-card-grid">
                {localizedStartModes.map(([key, label, text]) => (
                  <button key={key} className={startMode === key ? 'workflow-card active' : 'workflow-card'} type="button" onClick={() => applyStartMode(key)}>
                    <Music2 size={22} />
                    <span><strong>{label}</strong><small>{text}</small></span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {step === 1 && (
            <div className="wizard-step form-grid">
              <label>{t('common.title', 'Titel')}<input value={title} onChange={(event) => setTitle(event.target.value)} placeholder={t('music.fields.titlePlaceholder', 'Songtitel')} /></label>
              <label className={`wide ${promptOverLimit ? 'field-limit-active' : ''}`}>{instrumental ? t('music.fields.instrumentalBlueprintPrompt', 'Instrumental-Bauplan / Prompt ohne Lyrics') : customMode ? t('music.fields.fullLyrics', 'Lyrics / vollständiger Songtext') : t('music.fields.ideaShort', 'Idee / kurze Beschreibung')} <span className={`field-counter ${promptOverLimit ? 'over-limit' : ''}`}>{prompt.length}{modelLimit ? ` / ${modelLimit}` : ''} {t('music.chars', 'Zeichen')}</span><textarea className={`large ${promptOverLimit ? 'field-over-limit' : ''}`} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder={instrumental ? t('music.placeholders.instrumentalBlueprint', 'Füge den Timecode-Bauplan ohne Lyrics ein oder beschreibe das Instrumental.') : t('music.placeholders.ideaOrLyrics', 'Beschreibe deine Idee oder füge vollständige Lyrics ein.')} /></label>
            </div>
          )}

          {step === 2 && (
            <div className="wizard-step form-grid">
              <div className="style-preset-open-card"><span>{t('music.stylePresetModal.title', 'Style Presets')}</span><button type="button" onClick={() => setStylePresetModalOpen(true)}><Search size={15} /> {t('music.actions.openStyleBrowser', 'Style-Browser öffnen')}</button><small>{t('music.stylePresetModal.cardHint', 'Mit Filtertabs, Tags, Favoriten und Vorschlägen.')}</small></div>
              <label className={`wide ${styleOverLimit ? 'field-limit-active' : ''}`}>Style / Genre <span className={`field-counter ${styleOverLimit ? 'over-limit' : ''}`}>{style.length}{styleLimit ? ` / ${styleLimit}` : ''} {t('music.chars', 'Zeichen')}</span><textarea className={styleOverLimit ? 'field-over-limit' : ''} value={style} onChange={(event) => setStyle(event.target.value)} rows={6} placeholder={t('music.placeholders.styleGenre', 'Style, Genre, Stimmung, BPM, Vocals…')} /></label>
              {generationBlockedByLimits && <p className="wide field-limit-warning">{generationLimitMessages.join(' ')}</p>}
              <div className="wide">{styleSuggestionPanel}</div>
            </div>
          )}

          {step === 3 && (
            <div className="wizard-step form-grid">
              {generationProviderSelector}
              <label>{t('music.fields.model', 'Modell')}<select value={model} onChange={(event) => setModel(event.target.value)}>{models.map((item) => <option key={item}>{item}</option>)}</select></label>
              {!instrumental && voiceSelector}
              <label className="check"><input type="checkbox" checked={customMode} onChange={(event) => setCustomMode(event.target.checked)} /> {t('music.fields.useCustomMode', 'Custom Mode verwenden')}</label>
              <label className="check"><input type="checkbox" checked={instrumental} onChange={(event) => setInstrumental(event.target.checked)} /> {t('music.fields.createInstrumental', 'Instrumental erzeugen')}</label>
              {advancedSunoControlFields}
            </div>
          )}

          {step === 4 && (
            <div className="wizard-step summary-grid">
              <div className="summary-card"><span>{t('common.title', 'Titel')}</span><strong>{title || t('common.untitled', 'Unbenannt')}</strong></div>
              <div className="summary-card"><span>{t('music.fields.model', 'Modell')}</span><strong>{model}</strong></div>
              <div className="summary-card"><span>Provider</span><strong>{generationProvider === 'opencli' ? 'OpenCLI' : 'SunoAPI'}</strong></div>
              {voices.length > 0 && !instrumental && <div className="summary-card"><span>Voice / Persona</span><strong>{selectedVoice ? voiceLabel(selectedVoice, t) : t('common.none', 'Keine')}</strong></div>}
              <div className="summary-card"><span>{t('music.fields.mode', 'Modus')}</span><strong>{customMode ? 'Custom Lyrics' : t('music.fields.ideaSimple', 'Idee / Simple')}</strong></div>
              <div className="summary-card"><span>Instrumental</span><strong>{instrumental ? t('common.yes', 'Ja') : t('common.no', 'Nein')}</strong></div>
              <div className="summary-card wide"><span>Style</span><p>{style || t('music.fields.noStyle', 'Kein Style angegeben')}</p></div>
              <div className="summary-card wide"><span>Lyrics / Prompt</span><pre>{prompt || t('music.fields.noContentYet', 'Noch kein Inhalt')}</pre></div>
              <div className="wide button-row wrap">
                <button type="button" onClick={runSafeCheck} disabled={safeCheckLoading}><RefreshCw size={15} className={safeCheckLoading ? 'spin-icon' : ''} /> {t('music.safeCheck.title', 'Suno-Safe-Check')}</button>
                <button type="button" onClick={createMasterPackage}><Copy size={15} /> {t('music.masterPackage.title', 'Master-Paket')}</button>
                <button type="button" onClick={prepareAbVariants}>{t('music.actions.prepareThreeVariants', '3 Varianten vorbereiten')}</button>
              </div>
              {safeCheckPanel}
              {masterPackagePanel}
              {abVariantPanel}
            </div>
          )}

          <div className="wizard-actions">
            <button type="button" disabled={!canPrev} onClick={() => setStep((value) => Math.max(0, value - 1))}><ArrowLeft size={16} /> {t('status.pagination.previous', 'Zurück')}</button>
            {canNext ? <button className="primary" type="button" onClick={() => setStep((value) => Math.min(4, value + 1))}>{t('status.pagination.next', 'Weiter')} <ArrowRight size={16} /></button> : <button className="primary" type="button" disabled={loading || !prompt.trim() || generationBlockedByLimits} onClick={submit}><CheckCircle2 size={17} /> {loading ? t('music.actions.starting', 'Wird gestartet…') : t('music.actions.generateNow', 'Song jetzt generieren')}</button>}
          </div>
        </section>
      ) : (
        <>
          <form className="panel form-grid music-form" onSubmit={submitAdvancedOperation}>
            <label>{t('music.fields.optionalOperation', 'Optionale Operation')}
              <select value={operationMode} onChange={(event) => setOperationMode(event.target.value)}>
                {localizedOperationModes.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
              </select>
            </label>
            {generationProviderSelector}
            <label className={titleOverLimit ? 'field-limit-active' : ''}>{t('common.title', 'Titel')} <span className={`field-counter ${titleOverLimit ? 'over-limit' : ''}`}>{title.length}{titleLimit ? ` / ${titleLimit}` : ''} {t('music.chars', 'Zeichen')}</span><input className={titleOverLimit ? 'field-over-limit' : ''} value={title} onChange={(event) => setTitle(event.target.value)} required={!['sounds', 'generate-lyrics', 'import-suno-song', 'stem-separation', 'convert-wav', 'midi', 'video', 'cover-image', 'persona', 'boost-style'].includes(operationMode)} placeholder={t('music.fields.titlePlaceholder', 'Songtitel')} /></label>
            <label>{t('music.fields.model', 'Modell')}<select value={model} onChange={(event) => setModel(event.target.value)}>{operationModelOptions.map((item) => <option key={item}>{item}</option>)}</select></label>
            <div className="style-preset-open-card"><span>{t('music.stylePresetModal.shortTitle', 'Style Preset')}</span><button type="button" onClick={() => setStylePresetModalOpen(true)}><Search size={15} /> {t('music.actions.openStyleBrowser', 'Style-Browser öffnen')}</button><small>{t('music.stylePresetModal.expertCardHint', 'Filtertabs und Style-Tags statt Dropdown.')}</small></div>
            {!instrumental && voiceSelector}
            {optionalOperationFields}
            <label className="check"><input type="checkbox" checked={customMode} onChange={(event) => setCustomMode(event.target.checked)} /> Custom Mode</label>
            <label className="check"><input type="checkbox" checked={instrumental} onChange={(event) => setInstrumental(event.target.checked)} /> Instrumental</label>
            <label className={`wide ${styleOverLimit ? 'field-limit-active' : ''}`}>Style <span className={`field-counter ${styleOverLimit ? 'over-limit' : ''}`}>{style.length}{styleLimit ? ` / ${styleLimit}` : ''} {t('music.chars', 'Zeichen')}</span><textarea className={styleOverLimit ? 'field-over-limit' : ''} value={style} onChange={(event) => setStyle(event.target.value)} rows={5} placeholder={t('music.placeholders.expertStyle', 'grimy NYC boom bap, hard snare crack, deep male rap lead…')} /></label>
            <label className={`wide ${promptOverLimit ? 'field-limit-active' : ''}`}>{instrumental ? t('music.fields.instrumentalBlueprintPrompt', 'Instrumental-Bauplan / Prompt ohne Lyrics') : operationMode === 'generate-lyrics' ? t('music.fields.lyricsPromptTopic', 'Lyrics-Prompt / Thema') : operationMode === 'stem-separation' || operationMode === 'convert-wav' ? t('music.fields.noteOptionalContext', 'Notiz / optionaler Kontext') : 'Lyrics / Prompt'} <span className={`field-counter ${promptOverLimit ? 'over-limit' : ''}`}>{prompt.length}{modelLimit ? ` / ${modelLimit}` : ''} {t('music.chars', 'Zeichen')}</span><textarea className={`large ${promptOverLimit ? 'field-over-limit' : ''}`} value={prompt} onChange={(event) => setPrompt(event.target.value)} required={!['import-suno-song', 'stem-separation', 'convert-wav', 'midi', 'video', 'cover-image', 'persona', 'replace-section'].includes(operationMode)} placeholder={instrumental ? t('music.placeholders.instrumentalSunoBlueprint', 'Suno-kompatibler Instrumental-Bauplan ohne Lyrics, z.B. [0:00 - Intro] ...') : operationMode === 'generate-lyrics' ? t('music.placeholders.lyricsTopic', 'z.B. deutscher Rap über Neuanfang, düster, Hook mit Ohrwurm, 2 Verse…') : t('music.placeholders.sunoLyricsOrPrompt', 'Suno-kompatible Lyrics oder Prompt…')} /></label>
            {generationBlockedByLimits && <p className="wide field-limit-warning">{generationLimitMessages.join(' ')}</p>}
            <div className="wide button-row wrap"><button className="primary" disabled={loading || (operationMode === 'generate' && generationBlockedByLimits)}><Wand2 size={17} /> {loading ? t('music.actions.starting', 'Wird gestartet…') : operationActionLabel}</button><button type="button" onClick={runSafeCheck} disabled={safeCheckLoading}><RefreshCw size={15} className={safeCheckLoading ? 'spin-icon' : ''} /> {t('music.safeCheck.shortTitle', 'Safe-Check')}</button><button type="button" onClick={createMasterPackage}><Copy size={15} /> {t('music.masterPackage.title', 'Master-Paket')}</button><button type="button" onClick={prepareAbVariants}>{t('music.actions.threeVariants', '3 Varianten')}</button><button type="button" onClick={clearMusicForm}>{t('music.actions.clear', 'Leeren')}</button></div>
            {safeCheckPanel}
            {masterPackagePanel}
            {abVariantPanel}
          </form>
          {styleSuggestionPanel}
        </>
      )}
          <StylePresetModal open={stylePresetModalOpen} onClose={() => setStylePresetModalOpen(false)} styles={styles} builtinStyles={styleCategories} onApply={applyStylePresetText} t={t} />
    </section>
  );
}
