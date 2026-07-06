import { clampSeconds, formatSrtTimestamp, parseSrtTimestamp, roundSeconds, MIN_SRT_SEGMENT_DURATION } from './srtTime.js';

function makeId() {
  if (globalThis.crypto?.randomUUID) return `seg_${globalThis.crypto.randomUUID().replaceAll('-', '').slice(0, 12)}`;
  return `seg_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

export function normalizeSrtSegment(segment = {}, index = 0) {
  const start = roundSeconds(segment.start ?? 0);
  const rawEnd = Number(segment.end ?? start + 1.5);
  const end = roundSeconds(Math.max(start + MIN_SRT_SEGMENT_DURATION, Number.isFinite(rawEnd) ? rawEnd : start + 1.5));
  return {
    id: String(segment.id || makeId()),
    index: Number(index) + 1,
    start,
    end,
    text: String(segment.text || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n'),
    locked: Boolean(segment.locked),
    warning: Array.isArray(segment.warning) ? segment.warning : []
  };
}

export function renumberSegments(segments = [], { sort = true } = {}) {
  const rows = (segments || []).filter(Boolean).map((row, index) => normalizeSrtSegment(row, index));
  if (sort) rows.sort((a, b) => a.start - b.start || a.end - b.end || a.index - b.index);
  return rows.map((row, index) => normalizeSrtSegment(row, index));
}

export function parseSrtText(text) {
  const raw = String(text || '').replace(/\ufeff/g, '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
  if (!raw) return [];
  const blocks = raw.split(/\n\s*\n+/);
  const timeRe = /(\d{1,3}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,3}:\d{2}:\d{2}[,.]\d{1,3})/;
  const rows = [];
  blocks.forEach((block) => {
    const lines = String(block || '').split('\n').map((line) => line.trimEnd()).filter((line) => line.trim());
    const timeIndex = lines.findIndex((line) => timeRe.test(line));
    if (timeIndex < 0) return;
    const match = lines[timeIndex].match(timeRe);
    if (!match) return;
    rows.push(normalizeSrtSegment({ start: parseSrtTimestamp(match[1]), end: parseSrtTimestamp(match[2]), text: lines.slice(timeIndex + 1).join('\n').trim() }, rows.length));
  });
  return renumberSegments(rows);
}

export function exportSrtText(segments = []) {
  const blocks = [];
  renumberSegments(segments).forEach((segment, index) => {
    const text = String(segment.text || '').trim();
    if (!text) return;
    blocks.push(`${index + 1}\n${formatSrtTimestamp(segment.start)} --> ${formatSrtTimestamp(segment.end)}\n${text}`);
  });
  return blocks.length ? `${blocks.join('\n\n')}\n` : '';
}

export function segmentsFromSrtState(state = {}) {
  const fileSegments = parseSrtText(state?.srt_text || '');
  if (fileSegments.length) return fileSegments;
  if (Array.isArray(state?.segments) && state.segments.length) return renumberSegments(state.segments);
  return [];
}

export function activeSegmentAt(segments = [], currentTime = 0) {
  const t = clampSeconds(currentTime);
  return (segments || []).find((segment) => t >= Number(segment.start || 0) && t <= Number(segment.end || 0)) || null;
}
