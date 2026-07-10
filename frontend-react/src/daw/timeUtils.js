// Reine Zeit-/Arrangement-Hilfsfunktionen der Mini-DAW.
// Verbatim aus der bisherigen DawPage übernommen, damit sich das Verhalten
// (Rundung, Signaturen, Fade-Normalisierung) nicht ändert.

export function markerSortValue(marker) {
  const label = String(marker?.label || '');
  const numeric = Number(label);
  if (String(marker?.type || '').toLowerCase() === 'jump' && Number.isFinite(numeric)) {
    return numeric - 1000;
  }
  return safeNumber(marker?.time);
}

export function sortMarkers(markers = []) {
  return [...markers].sort((a, b) => {
    const byTime = safeNumber(a?.time) - safeNumber(b?.time);
    if (Math.abs(byTime) > 0.0001) return byTime;
    return markerSortValue(a) - markerSortValue(b);
  });
}

export function cloneArrangementSnapshot(value) {
  if (!value) return null;
  try { return JSON.parse(JSON.stringify(value)); } catch { return null; }
}

export function clamp(value, min, max) {
  return Math.max(min, Math.min(max, Number(value || 0)));
}

export function safeNumber(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function clipDuration(clip) {
  return Math.max(0, safeNumber(clip?.source_end) - safeNumber(clip?.source_start));
}

export function normalizeFadePair(fadeInValue, fadeOutValue, durationValue) {
  const duration = Math.max(0, safeNumber(durationValue));
  const maxTotal = Math.max(0, duration - 0.05);
  let fadeIn = clamp(safeNumber(fadeInValue), 0, maxTotal);
  let fadeOut = clamp(safeNumber(fadeOutValue), 0, maxTotal);
  const total = fadeIn + fadeOut;
  if (total > maxTotal && total > 0) {
    const ratio = maxTotal / total;
    fadeIn *= ratio;
    fadeOut *= ratio;
  }
  return { fadeIn, fadeOut };
}

export function fadeHandlePercent(value, durationValue, side = 'left') {
  const duration = Math.max(0.1, safeNumber(durationValue, 0.1));
  const raw = clamp((safeNumber(value) / duration) * 100, 0, 50);
  if (side === 'right') return clamp(100 - raw, 50, 99.2);
  return clamp(raw, 0.8, 50);
}

export function secondsToClock(value, withTenths = false) {
  const total = Math.max(0, Number(value || 0));
  const minutes = Math.floor(total / 60);
  const seconds = Math.floor(total % 60);
  if (!withTenths) return `${minutes}:${String(seconds).padStart(2, '0')}`;
  const tenths = Math.floor((total % 1) * 10);
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${tenths}`;
}

export function percent(value, duration) {
  if (!duration) return 0;
  return clamp((safeNumber(value) / duration) * 100, 0, 100);
}

export function makeId(prefix) {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export function arrangementLength(arrangement, fallbackDuration = 0) {
  const clips = Array.isArray(arrangement?.clips) ? arrangement.clips : [];
  const clipEnd = clips.reduce((max, clip) => Math.max(max, safeNumber(clip.timeline_start) + clipDuration(clip)), 0);
  const markerEnd = (arrangement?.markers || []).reduce((max, marker) => Math.max(max, safeNumber(marker.time)), 0);
  return Math.max(1, safeNumber(arrangement?.duration_seconds), fallbackDuration, clipEnd, markerEnd);
}

export function roundedAudioValue(value, digits = 3) {
  const factor = 10 ** digits;
  return Math.round(safeNumber(value) * factor) / factor;
}

export function arrangementPlaybackSignature(arrangement) {
  if (!arrangement || typeof arrangement !== 'object') return '';
  const clips = Array.isArray(arrangement.clips) ? arrangement.clips : [];
  const tracks = Array.isArray(arrangement.tracks) ? arrangement.tracks : [];
  return JSON.stringify({
    duration: roundedAudioValue(arrangementLength(arrangement, arrangement.duration_seconds || 0)),
    clips: clips
      .map((clip) => ({
        id: String(clip.id || ''),
        track: String(clip.track_id || ''),
        source: Number(clip.source_audio_id || 0),
        start: roundedAudioValue(clip.timeline_start),
        in: roundedAudioValue(clip.source_start),
        out: roundedAudioValue(clip.source_end),
        gain: roundedAudioValue(clip.gain_db, 2),
        fadeIn: roundedAudioValue(clip.fade_in, 2),
        fadeOut: roundedAudioValue(clip.fade_out, 2),
        muted: Boolean(clip.muted),
      }))
      .sort((a, b) => (a.track === b.track ? a.start - b.start : a.track.localeCompare(b.track))),
    tracks: tracks.map((track) => ({ id: String(track.id || ''), muted: Boolean(track.muted), solo: Boolean(track.solo), volume: roundedAudioValue(track.volume_db, 2) })),
  });
}

export function arrangementNeedsRenderedPlayback(arrangement, sourceDuration = 0) {
  const clips = Array.isArray(arrangement?.clips) ? arrangement.clips.filter((clip) => !clip.muted) : [];
  const duration = arrangementLength(arrangement, sourceDuration || arrangement?.duration_seconds || 0);
  const safeSourceDuration = Math.max(0, safeNumber(sourceDuration));
  if (!clips.length) return false;
  if (duration > safeSourceDuration + 0.15) return true;
  if (clips.length !== 1) return true;
  const clip = clips[0];
  if (Math.abs(safeNumber(clip.timeline_start)) > 0.05) return true;
  if (Math.abs(safeNumber(clip.source_start)) > 0.05) return true;
  if (safeSourceDuration > 0 && Math.abs(safeNumber(clip.source_end) - safeSourceDuration) > 0.15) return true;
  if (Math.abs(safeNumber(clip.gain_db)) > 0.01) return true;
  if (safeNumber(clip.fade_in) > 0.01 || safeNumber(clip.fade_out) > 0.01) return true;
  return false;
}

export function collectDawTextValues(value, depth = 0, sink = []) {
  if (value == null || depth > 5 || sink.length > 80) return sink;
  if (typeof value === 'string') {
    const parsed = parseMaybeJson(value);
    if (parsed && parsed !== value) collectDawTextValues(parsed, depth + 1, sink);
    const trimmed = value.trim();
    if (trimmed && trimmed.length <= 8000) sink.push(trimmed);
    return sink;
  }
  if (Array.isArray(value)) {
    value.slice(0, 30).forEach((item) => collectDawTextValues(item, depth + 1, sink));
    return sink;
  }
  if (typeof value === 'object') {
    Object.entries(value).forEach(([key, item]) => {
      if (/waveform|bars|peaks|samples|lyrics|prompt/i.test(key) && typeof item !== 'string') return;
      collectDawTextValues(item, depth + 1, sink);
    });
  }
  return sink;
}

export function parseMaybeJson(value) {
  if (!value) return null;
  if (Array.isArray(value) || (typeof value === 'object' && value !== null)) return value;
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!trimmed || !['[', '{'].includes(trimmed[0])) return null;
  try { return JSON.parse(trimmed); } catch { return null; }
}

export function parseClockValue(value) {
  if (typeof value !== 'string') return Number.NaN;
  const trimmed = value.trim();
  if (!trimmed) return Number.NaN;
  if (/^\d+(?:[.,]\d+)?$/.test(trimmed)) return Number(trimmed.replace(',', '.'));
  const parts = trimmed.split(':').map((part) => Number(part.replace(',', '.')));
  if (parts.some((part) => !Number.isFinite(part))) return Number.NaN;
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  return Number.NaN;
}
