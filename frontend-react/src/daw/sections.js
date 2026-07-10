// Songstruktur-Auflösung (Intro/Verse/Hook/...) aus structure_segments_json,
// Arrangement-Markern und Beatgrid-Segmenten. Verbatim-Port.
import { clamp, safeNumber, parseMaybeJson, parseClockValue, clipDuration } from './timeUtils.js';
import { nearestDawBeatgridBoundary, validDawBeatgrid } from './musicalTime.js';

export const SECTION_KIND_LABELS = {
  intro: 'Intro',
  verse: 'Verse',
  pre_chorus: 'Pre-Chorus',
  chorus: 'Chorus / Hook',
  post_chorus: 'Post-Chorus',
  bridge: 'Bridge',
  break: 'Break',
  drop: 'Drop',
  instrumental: 'Instrumental',
  outro: 'Outro',
};
export const SECTION_KIND_PRIORITY = ['intro', 'verse', 'pre_chorus', 'chorus', 'post_chorus', 'bridge', 'break', 'drop', 'instrumental', 'outro'];



export function segmentTimeValue(segment, keys, duration = 0) {
  if (!segment || typeof segment !== 'object') return Number.NaN;
  for (const key of keys) {
    if (!(key in segment)) continue;
    let value = segment[key];
    let parsed = typeof value === 'string' ? parseClockValue(value) : Number(value);
    if (!Number.isFinite(parsed)) continue;
    if (/ms$/i.test(key) || (parsed > 1000 && duration > 0 && parsed > duration * 2.5)) parsed /= 1000;
    return parsed;
  }
  return Number.NaN;
}

export function cleanSectionLabel(value = '') {
  return String(value || '')
    .replace(/^\s*\[/, '')
    .replace(/[\[\]]/g, ' ')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

export function sectionKindFromLabel(label = '') {
  const raw = cleanSectionLabel(label).toLowerCase();
  if (!raw) return '';
  if (/pre\s*(chorus|hook|refrain)/i.test(raw)) return 'pre_chorus';
  if (/post\s*(chorus|hook|refrain)/i.test(raw)) return 'post_chorus';
  if (/chorus|hook|refrain|refrain/i.test(raw)) return 'chorus';
  if (/verse|strophe|part\s*\d|rap\s*verse/i.test(raw)) return 'verse';
  if (/intro|anfang|opening/i.test(raw)) return 'intro';
  if (/outro|ende|ending|final/i.test(raw)) return 'outro';
  if (/bridge|middle\s*8|mittelteil/i.test(raw)) return 'bridge';
  if (/breakdown|break|pause|interlude/i.test(raw)) return 'break';
  if (/drop|climax/i.test(raw)) return 'drop';
  if (/instrumental|solo|beat/i.test(raw)) return 'instrumental';
  return '';
}

export function labelFromSegment(segment = {}) {
  const candidates = [segment.label, segment.name, segment.title, segment.section, segment.type, segment.kind, segment.part, segment.tag];
  const direct = candidates.find((item) => String(item || '').trim());
  if (direct) return cleanSectionLabel(direct);
  const text = String(segment.text || segment.line || '').trim();
  if (/^\s*\[.+\]\s*$/.test(text)) return cleanSectionLabel(text);
  return '';
}

export function extractSegmentsFromValue(value, sourceName, duration = 0, depth = 0) {
  const parsed = parseMaybeJson(value);
  if (!parsed || depth > 4) return [];
  if (Array.isArray(parsed)) {
    return parsed.flatMap((item) => extractSegmentsFromValue(item, sourceName, duration, depth + 1));
  }
  if (typeof parsed !== 'object') return [];

  const label = labelFromSegment(parsed);
  const kind = sectionKindFromLabel(label);
  const start = segmentTimeValue(parsed, ['start_seconds', 'startSeconds', 'start_sec', 'startSec', 'start_s', 'startS', 'start_time', 'startTime', 'start_ms', 'startMs', 'start', 'from', 'begin', 'time'], duration);
  const end = segmentTimeValue(parsed, ['end_seconds', 'endSeconds', 'end_sec', 'endSec', 'end_s', 'endS', 'end_time', 'endTime', 'end_ms', 'endMs', 'end', 'to', 'until', 'stop', 'finish'], duration);
  const found = [];
  if (kind && Number.isFinite(start) && Number.isFinite(end) && end - start >= 0.25) {
    found.push({
      id: `${sourceName}-${kind}-${start.toFixed(2)}-${end.toFixed(2)}`,
      label: label || SECTION_KIND_LABELS[kind] || 'Abschnitt',
      kind,
      start,
      end,
      source: sourceName,
    });
  }

  const knownKeys = ['structure_segments_json', 'structureSegmentsJson', 'structure_segments', 'structureSegments', 'section_segments', 'sectionSegments', 'sections', 'segments_json', 'segmentsJson', 'segments', 'timeline_segments', 'timelineSegments', 'song_structure', 'songStructure', 'lyrics_structure', 'lyricsStructure', 'structure', 'analysis', 'metadata'];
  for (const key of knownKeys) {
    if (parsed[key]) found.push(...extractSegmentsFromValue(parsed[key], `${sourceName}.${key}`, duration, depth + 1));
  }
  return found;
}

function snapSectionBoundary(value, beatgrid, duration = 0, tolerance = 0.14) {
  if (!validDawBeatgrid(beatgrid)) return value;
  const nearest = nearestDawBeatgridBoundary(value, beatgrid, duration);
  if (!Number.isFinite(nearest)) return value;
  return Math.abs(nearest - value) <= tolerance ? nearest : value;
}

function normalizeRawSections(items = [], duration = 0) {
  const safeDuration = Math.max(1, safeNumber(duration, 1));
  const deduped = [];
  const seen = new Set();
  items.forEach((item) => {
    const start = clamp(item.start, 0, safeDuration);
    const end = clamp(item.end, start + 0.25, safeDuration);
    if (end - start < 0.25) return;
    const key = `${item.kind}-${Math.round(start * 10)}-${Math.round(end * 10)}-${item.source || ''}`;
    if (seen.has(key)) return;
    seen.add(key);
    deduped.push({ ...item, start, end });
  });
  return deduped;
}

function projectSectionsThroughArrangement(sections = [], arrangement, duration = 0, beatgrid = null, sourceDuration = 0) {
  const clips = Array.isArray(arrangement?.clips) ? arrangement.clips : [];
  if (!clips.length) return sections;
  const projected = [];
  sections.forEach((section) => {
    const rawSourceStart = safeNumber(section.start, Number.NaN);
    const rawSourceEnd = safeNumber(section.end, Number.NaN);
    const sourceStart = snapSectionBoundary(rawSourceStart, beatgrid, sourceDuration || duration);
    const sourceEnd = snapSectionBoundary(rawSourceEnd, beatgrid, sourceDuration || duration);
    if (!Number.isFinite(sourceStart) || !Number.isFinite(sourceEnd) || sourceEnd <= sourceStart) return;
    clips.forEach((clip) => {
      if (clip?.muted) return;
      const clipTimelineStart = safeNumber(clip?.timeline_start, 0);
      const clipSourceStart = safeNumber(clip?.source_start, 0);
      const clipSourceEnd = safeNumber(clip?.source_end, clipSourceStart + clipDuration(clip));
      const overlapStart = Math.max(sourceStart, clipSourceStart);
      const overlapEnd = Math.min(sourceEnd, clipSourceEnd);
      if (overlapEnd - overlapStart < 0.18) return;
      const timelineStart = clipTimelineStart + (overlapStart - clipSourceStart);
      const timelineEnd = clipTimelineStart + (overlapEnd - clipSourceStart);
      projected.push({
        ...section,
        start: timelineStart,
        end: timelineEnd,
        source: `${section.source || 'source'}:timeline`,
      });
    });
  });
  return projected.length ? projected : sections;
}

function mergeAdjacentSections(items = [], duration = 0) {
  const safeDuration = Math.max(1, safeNumber(duration, 1));
  const ordered = [...items].sort((a, b) => {
    const byTime = a.start - b.start;
    if (Math.abs(byTime) > 0.001) return byTime;
    return SECTION_KIND_PRIORITY.indexOf(a.kind) - SECTION_KIND_PRIORITY.indexOf(b.kind);
  });
  const merged = [];
  ordered.forEach((item) => {
    const start = clamp(item.start, 0, safeDuration);
    const end = clamp(item.end, start + 0.25, safeDuration);
    if (end - start < 0.25) return;
    const previous = merged[merged.length - 1];
    if (
      previous
      && previous.kind === item.kind
      && Math.abs(start - previous.end) <= 0.16
      && (previous.label || '') === (item.label || '')
    ) {
      previous.end = Math.max(previous.end, end);
      previous.source = `${previous.source || ''}+${item.source || ''}`;
      return;
    }
    merged.push({ ...item, start, end });
  });
  return merged;
}

export function buildResolvedSections({ project, asset, arrangement, beatgrid }, duration = 0) {
  const sourceRaw = [];
  const arrangementRaw = [];
  const sourceSources = [
    ['project', project],
    ['project.asset', project?.asset],
    ['project.transcript', project?.transcript],
    ['asset', asset],
    ['asset.transcript', asset?.transcript],
  ];
  sourceSources.forEach(([name, value]) => sourceRaw.push(...extractSegmentsFromValue(value, name, duration)));
  arrangementRaw.push(...extractSegmentsFromValue(arrangement, 'arrangement', duration));

  const safeDuration = Math.max(1, safeNumber(duration, 1));
  const sourceDuration = Math.max(
    1,
    safeNumber(asset?.duration_seconds || project?.asset?.duration_seconds || arrangement?.source_duration_seconds || duration, duration),
  );
  const projectedSource = projectSectionsThroughArrangement(
    normalizeRawSections(sourceRaw, sourceDuration),
    arrangement,
    safeDuration,
    beatgrid,
    sourceDuration,
  );
  const raw = [
    ...projectedSource,
    ...normalizeRawSections(arrangementRaw, safeDuration),
  ];

  const deduped = [];
  const seen = new Set();
  raw.forEach((item) => {
    const start = clamp(item.start, 0, safeDuration);
    const end = clamp(item.end, start + 0.25, safeDuration);
    if (end - start < 0.25) return;
    const key = `${item.kind}-${Math.round(start * 10)}-${Math.round(end * 10)}`;
    if (seen.has(key)) return;
    seen.add(key);
    deduped.push({ ...item, id: key, start, end });
  });

  const ordered = mergeAdjacentSections(deduped, safeDuration);
  const counters = {};
  return ordered.map((item) => {
    counters[item.kind] = (counters[item.kind] || 0) + 1;
    const baseLabel = SECTION_KIND_LABELS[item.kind] || item.label || 'Abschnitt';
    const displayLabel = `${baseLabel}${counters[item.kind] > 1 ? ` ${counters[item.kind]}` : ''}`;
    const id = `${item.kind}-${Math.round(item.start * 100)}-${Math.round(item.end * 100)}`;
    return {
      ...item,
      id,
      occurrence: counters[item.kind],
      displayLabel,
      duration: item.end - item.start,
    };
  });
}
