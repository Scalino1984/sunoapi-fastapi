export const DAW_TRACK_HEIGHT = 88;
export const DAW_RULER_HEIGHT = 48;
export const DAW_TRACK_HEADER_WIDTH = 220;
export const DAW_MIN_CLIP_SECONDS = 0.08;
export const DAW_DEFAULT_TRACKS = [
  { id: 'track-1', name: 'Spur 1', muted: false, solo: false, volume_db: 0 },
  { id: 'track-2', name: 'Spur 2', muted: false, solo: false, volume_db: 0 },
  { id: 'track-3', name: 'Spur 3', muted: false, solo: false, volume_db: 0 },
];

export const DAW_ZOOM_PRESETS = [
  { id: 0, label: 'Kompakt', pxPerSecond: 42 },
  { id: 1, label: 'Normal', pxPerSecond: 64 },
  { id: 2, label: 'Detail', pxPerSecond: 92 },
  { id: 3, label: 'Schnitt', pxPerSecond: 132 },
  { id: 4, label: 'Mikro', pxPerSecond: 180 },
];

export function safeNumber(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function clamp(value, min, max) {
  const parsed = safeNumber(value, min);
  return Math.max(min, Math.min(max, parsed));
}

export function makeDawId(prefix = 'id') {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`;
}

export function cloneDaw(value) {
  return value ? JSON.parse(JSON.stringify(value)) : value;
}

export function assetTitle(asset) {
  return String(asset?.display_title || asset?.title || asset?.filename || `Audio ${asset?.id || ''}`).trim();
}

export function beatsPerBar(timeSignature = '4/4') {
  const raw = String(timeSignature || '4/4').trim();
  const match = raw.match(/^(\d{1,2})\s*\/\s*(\d{1,2})$/);
  if (!match) return 4;
  return clamp(Number(match[1]), 1, 16);
}

export function secondsPerBeat(bpm) {
  const value = clamp(safeNumber(bpm, 120), 20, 300);
  return 60 / value;
}

export function secondsPerBar(bpm, timeSignature = '4/4') {
  return secondsPerBeat(bpm) * beatsPerBar(timeSignature);
}

export function snapStepSeconds(arrangement) {
  const bpm = safeNumber(arrangement?.bpm, 0);
  if (!bpm) return 0;
  const beat = secondsPerBeat(bpm);
  const unit = String(arrangement?.snap_unit || 'beat');
  if (unit === 'bar') return secondsPerBar(bpm, arrangement?.time_signature);
  if (unit === 'half') return beat / 2;
  if (unit === 'quarter') return beat / 4;
  return beat;
}

export function snapTime(value, arrangement, force = false) {
  const seconds = Math.max(0, safeNumber(value));
  if (!force && !arrangement?.snap_enabled) return seconds;
  const step = snapStepSeconds(arrangement);
  if (!step) return seconds;
  return Math.max(0, Math.round(seconds / step) * step);
}

export function formatTime(value, compact = false) {
  const seconds = Math.max(0, safeNumber(value));
  const minutes = Math.floor(seconds / 60);
  const rest = seconds - minutes * 60;
  if (compact) return `${minutes}:${String(Math.floor(rest)).padStart(2, '0')}`;
  return `${minutes}:${String(rest.toFixed(2)).padStart(5, '0')}`;
}

export function formatBarsBeats(value, arrangement) {
  const bpm = safeNumber(arrangement?.bpm, 0);
  if (!bpm) return 'Bar -- Beat --';
  const beatLength = secondsPerBeat(bpm);
  const barBeats = beatsPerBar(arrangement?.time_signature);
  const totalBeats = Math.max(0, Math.floor((safeNumber(value) / beatLength) + 0.00001));
  const bar = Math.floor(totalBeats / barBeats) + 1;
  const beat = (totalBeats % barBeats) + 1;
  return `Takt ${bar} · Beat ${beat}`;
}

export function clipDuration(clip) {
  return Math.max(DAW_MIN_CLIP_SECONDS, safeNumber(clip?.source_end) - safeNumber(clip?.source_start));
}

export function clipEnd(clip) {
  return safeNumber(clip?.timeline_start) + clipDuration(clip);
}

export function arrangementDuration(arrangement, fallback = 1) {
  const clipsEnd = Math.max(0, ...((arrangement?.clips || []).map(clipEnd)));
  const markersEnd = Math.max(0, ...((arrangement?.markers || []).map((marker) => safeNumber(marker?.time))));
  const declared = safeNumber(arrangement?.duration_seconds, 0);
  return Math.max(1, safeNumber(fallback, 1), declared, clipsEnd, markersEnd);
}

export function normalizeTrack(track, index = 0) {
  return {
    id: String(track?.id || `track-${index + 1}`).slice(0, 40),
    name: String(track?.name || `Spur ${index + 1}`).slice(0, 120),
    muted: Boolean(track?.muted),
    solo: Boolean(track?.solo),
    volume_db: clamp(track?.volume_db, -24, 24),
  };
}

export function defaultArrangement(asset, durationSeconds = 0) {
  const duration = Math.max(DAW_MIN_CLIP_SECONDS, safeNumber(durationSeconds, 0) || safeNumber(asset?.duration_seconds, 0) || 1);
  return {
    version: 2,
    source_audio_id: Number(asset?.id || 0),
    duration_seconds: duration,
    bpm: safeNumber(asset?.metadata_json?.bpm || asset?.bpm, 0) || null,
    time_signature: '4/4',
    snap_enabled: true,
    snap_unit: 'beat',
    tracks: DAW_DEFAULT_TRACKS.map((track) => ({ ...track })),
    clips: [{
      id: `clip-${asset?.id || 'asset'}-1`,
      track_id: 'track-1',
      source_audio_id: Number(asset?.id || 0),
      timeline_start: 0,
      source_start: 0,
      source_end: duration,
      gain_db: 0,
      fade_in: 0,
      fade_out: 0,
      label: assetTitle(asset),
      muted: false,
      locked: false,
      color: 'cyan',
    }],
    markers: [],
  };
}

export function normalizeArrangement(input, asset, durationSeconds = 0) {
  const fallback = defaultArrangement(asset, durationSeconds);
  const raw = input && typeof input === 'object' ? cloneDaw(input) : fallback;
  const sourceId = Number(raw.source_audio_id || asset?.id || fallback.source_audio_id || 0);
  const tracks = (Array.isArray(raw.tracks) && raw.tracks.length ? raw.tracks : fallback.tracks)
    .slice(0, 24)
    .map(normalizeTrack);
  const validTracks = new Set(tracks.map((track) => track.id));
  const sourceDuration = Math.max(DAW_MIN_CLIP_SECONDS, safeNumber(asset?.duration_seconds, 0), safeNumber(durationSeconds, 0), safeNumber(raw.duration_seconds, 0));
  const clips = (Array.isArray(raw.clips) && raw.clips.length ? raw.clips : fallback.clips)
    .slice(0, 300)
    .map((clip, index) => {
      const start = clamp(clip?.source_start, 0, 60 * 60 * 6);
      const end = clamp(clip?.source_end ?? sourceDuration, start + DAW_MIN_CLIP_SECONDS, 60 * 60 * 6);
      const trackId = validTracks.has(String(clip?.track_id)) ? String(clip.track_id) : tracks[0].id;
      return {
        id: String(clip?.id || makeDawId('clip')).slice(0, 80),
        track_id: trackId,
        source_audio_id: Number(clip?.source_audio_id || sourceId),
        timeline_start: clamp(clip?.timeline_start, 0, 60 * 60 * 12),
        source_start: start,
        source_end: Math.max(start + DAW_MIN_CLIP_SECONDS, end),
        gain_db: clamp(clip?.gain_db, -24, 24),
        fade_in: clamp(clip?.fade_in, 0, 60),
        fade_out: clamp(clip?.fade_out, 0, 60),
        label: String(clip?.label || assetTitle(asset) || `Clip ${index + 1}`).slice(0, 140),
        muted: Boolean(clip?.muted),
        locked: Boolean(clip?.locked),
        color: String(clip?.color || 'cyan').slice(0, 40),
      };
    })
    .sort((a, b) => a.timeline_start - b.timeline_start || a.track_id.localeCompare(b.track_id));
  const markers = (Array.isArray(raw.markers) ? raw.markers : [])
    .slice(0, 500)
    .map((marker, index) => ({
      id: String(marker?.id || `marker-${index + 1}`).slice(0, 80),
      label: String(marker?.label || 'Marker').slice(0, 120),
      time: clamp(marker?.time, 0, 60 * 60 * 12),
      type: String(marker?.type || 'marker').slice(0, 80),
      note: marker?.note ? String(marker.note).slice(0, 500) : null,
    }))
    .sort((a, b) => a.time - b.time);
  const normalized = {
    version: 2,
    source_audio_id: sourceId,
    duration_seconds: 1,
    bpm: raw.bpm === null || raw.bpm === undefined || raw.bpm === '' ? null : clamp(raw.bpm, 20, 300),
    time_signature: String(raw.time_signature || '4/4').slice(0, 12),
    snap_enabled: Boolean(raw.snap_enabled ?? true),
    snap_unit: ['bar', 'beat', 'half', 'quarter'].includes(String(raw.snap_unit)) ? String(raw.snap_unit) : 'beat',
    tracks,
    clips,
    markers,
  };
  normalized.duration_seconds = arrangementDuration(normalized, sourceDuration);
  return normalized;
}

export function moveClip(arrangement, clipId, nextValues) {
  return {
    ...arrangement,
    clips: arrangement.clips.map((clip) => (clip.id === clipId ? { ...clip, ...nextValues } : clip)),
  };
}

export function splitClipAt(arrangement, clipId, time) {
  const clip = arrangement.clips.find((item) => item.id === clipId);
  if (!clip || clip.locked) return { arrangement, createdClipId: '' };
  const start = safeNumber(clip.timeline_start);
  const end = clipEnd(clip);
  const splitTime = snapTime(time, arrangement, true);
  if (splitTime <= start + DAW_MIN_CLIP_SECONDS || splitTime >= end - DAW_MIN_CLIP_SECONDS) return { arrangement, createdClipId: '' };
  const sourceSplit = safeNumber(clip.source_start) + (splitTime - start);
  const left = { ...clip, source_end: sourceSplit };
  const right = {
    ...clip,
    id: makeDawId('clip'),
    timeline_start: splitTime,
    source_start: sourceSplit,
    label: `${clip.label || 'Clip'} Schnitt`,
  };
  const clips = arrangement.clips.flatMap((item) => (item.id === clipId ? [left, right] : [item]));
  const next = { ...arrangement, clips };
  next.duration_seconds = arrangementDuration(next, arrangement.duration_seconds);
  return { arrangement: next, createdClipId: right.id };
}

export function duplicateClip(arrangement, clipId, insertAt = null) {
  const clip = arrangement.clips.find((item) => item.id === clipId);
  if (!clip) return { arrangement, createdClipId: '' };
  const duration = clipDuration(clip);
  const timelineStart = insertAt === null ? clipEnd(clip) : Math.max(0, safeNumber(insertAt));
  const clone = {
    ...clip,
    id: makeDawId('clip'),
    timeline_start: snapTime(timelineStart, arrangement, true),
    label: `${clip.label || 'Clip'} Kopie`,
    locked: false,
  };
  const next = { ...arrangement, clips: [...arrangement.clips, clone] };
  next.duration_seconds = arrangementDuration(next, arrangement.duration_seconds + duration);
  return { arrangement: next, createdClipId: clone.id };
}

export function sectionsFromAssetAndBeatgrid(asset, beatgrid, arrangement) {
  const raw = [];
  const pushList = (list, source) => {
    if (!Array.isArray(list)) return;
    list.forEach((item, index) => {
      const start = safeNumber(item?.start ?? item?.start_sec ?? item?.from, NaN);
      const end = safeNumber(item?.end ?? item?.end_sec ?? item?.to, NaN);
      if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return;
      const label = String(item?.label || item?.name || item?.title || item?.section || item?.type || `Abschnitt ${index + 1}`);
      raw.push({ id: `${source}-${index + 1}`, label, kind: normalizeSectionKind(item?.kind || item?.type || label), start, end, source });
    });
  };
  pushList(asset?.structure_segments_json, 'asset');
  pushList(asset?.metadata_json?.structure_segments_json, 'metadata');
  pushList(asset?.metadata_json?.structure_segments, 'metadata');
  pushList(asset?.waveform_json?.segments, 'waveform');
  pushList(beatgrid?.sections || beatgrid?.beatgrid?.sections, 'beatgrid');
  if (!raw.length && Array.isArray(arrangement?.markers)) {
    const sectionMarkers = arrangement.markers.filter((marker) => String(marker.type || '').includes('section'));
    sectionMarkers.forEach((marker, index) => {
      const next = sectionMarkers[index + 1];
      raw.push({
        id: `marker-${index + 1}`,
        label: marker.label || `Abschnitt ${index + 1}`,
        kind: normalizeSectionKind(marker.label),
        start: safeNumber(marker.time),
        end: next ? safeNumber(next.time) : arrangementDuration(arrangement),
        source: 'marker',
      });
    });
  }
  return raw
    .filter((item) => item.end - item.start > 0.2)
    .sort((a, b) => a.start - b.start)
    .map((item, index) => ({ ...item, id: item.id || `section-${index + 1}`, display: `${item.label} · ${formatTime(item.start, true)}–${formatTime(item.end, true)}` }));
}

export function normalizeSectionKind(value) {
  const text = String(value || '').toLowerCase();
  if (/(hook|refrain|chorus)/.test(text)) return 'chorus';
  if (/(verse|strophe|part)/.test(text)) return 'verse';
  if (/pre/.test(text) && /chorus/.test(text)) return 'pre_chorus';
  if (/post/.test(text) && /chorus/.test(text)) return 'post_chorus';
  if (/intro/.test(text)) return 'intro';
  if (/outro/.test(text)) return 'outro';
  if (/bridge/.test(text)) return 'bridge';
  if (/(break|drop|solo|instrument)/.test(text)) return 'break';
  return 'section';
}

export function findSectionByCommand(sections, message, selectedSectionId = '') {
  const text = String(message || '').toLowerCase();
  if (selectedSectionId) {
    const selected = sections.find((section) => section.id === selectedSectionId);
    if (selected) return selected;
  }
  const targets = [
    ['chorus', /(hook|refrain|chorus)/],
    ['intro', /intro/],
    ['verse', /(verse|strophe|part)/],
    ['bridge', /bridge/],
    ['outro', /outro/],
  ];
  for (const [kind, pattern] of targets) {
    if (!pattern.test(text)) continue;
    const ordinal = /(?:zweite|2\.|2\b)/.test(text) ? 1 : /(?:dritte|3\.|3\b)/.test(text) ? 2 : 0;
    const matches = sections.filter((section) => section.kind === kind || String(section.label || '').toLowerCase().includes(kind));
    if (matches[ordinal]) return matches[ordinal];
  }
  return null;
}
