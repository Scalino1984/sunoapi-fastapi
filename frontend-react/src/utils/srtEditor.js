import { DEFAULT_SRT_GAP_SECONDS, MIN_SRT_SEGMENT_DURATION, clampSeconds, roundSeconds } from './srtTime.js';
import { normalizeSrtSegment, renumberSegments } from './srtParser.js';

export function shiftSegmentsFromIndex(segments, startIndex, deltaSeconds, includeCurrent = true, options = {}) {
  const rows = renumberSegments(segments);
  const delta = Number(deltaSeconds || 0);
  const zeroIndex = Math.max(0, Number(startIndex || 0));
  const startAt = includeCurrent ? zeroIndex : zeroIndex + 1;
  return renumberSegments(rows.map((row, index) => {
    if (index < startAt || (options.skipLocked && row.locked)) return row;
    return { ...row, start: roundSeconds(Math.max(0, row.start + delta)), end: roundSeconds(Math.max(MIN_SRT_SEGMENT_DURATION, row.end + delta)) };
  }), { sort: false });
}

export function extendSegmentAndRippleFollowing(segments, segmentIndex, deltaSeconds, ripple = false) {
  const rows = renumberSegments(segments);
  const idx = Number(segmentIndex || 0);
  const delta = Number(deltaSeconds || 0);
  return renumberSegments(rows.map((row, index) => {
    if (index === idx) return { ...row, end: roundSeconds(Math.max(row.start + MIN_SRT_SEGMENT_DURATION, row.end + delta)) };
    if (ripple && index > idx && !row.locked) return { ...row, start: roundSeconds(Math.max(0, row.start + delta)), end: roundSeconds(Math.max(MIN_SRT_SEGMENT_DURATION, row.end + delta)) };
    return row;
  }), { sort: false });
}

export function shortenSegmentAndRippleFollowing(segments, segmentIndex, deltaSeconds, ripple = false) {
  return extendSegmentAndRippleFollowing(segments, segmentIndex, -Math.abs(Number(deltaSeconds || 0)), ripple);
}

export function deleteSegment(segments, segmentIndex, mode = 'keep_timing') {
  const rows = renumberSegments(segments);
  const idx = Number(segmentIndex || 0);
  const removed = rows[idx];
  if (!removed) return rows;
  const duration = Math.max(0, removed.end - removed.start);
  const kept = rows.filter((_, index) => index !== idx);
  if (mode === 'close_gap') {
    return renumberSegments(kept.map((row, index) => {
      if (index < idx || row.locked) return row;
      return { ...row, start: roundSeconds(Math.max(0, row.start - duration)), end: roundSeconds(Math.max(MIN_SRT_SEGMENT_DURATION, row.end - duration)) };
    }), { sort: false });
  }
  return renumberSegments(kept);
}

export function insertSegmentAfter(segments, segmentIndex, newSegment = {}, mode = 'keep_timing') {
  const rows = renumberSegments(segments);
  const idx = Number(segmentIndex ?? -1);
  const insertAt = Math.max(0, Math.min(rows.length, idx + 1));
  const previous = rows[Math.max(0, insertAt - 1)] || null;
  const next = rows[insertAt] || null;
  const start = roundSeconds(newSegment.start ?? previous?.end ?? 0);
  const duration = Math.max(MIN_SRT_SEGMENT_DURATION, Number(newSegment.duration ?? ((newSegment.end ?? start + 2) - start)) || 2);
  const segment = normalizeSrtSegment({ ...newSegment, start, end: start + duration, text: newSegment.text ?? 'Neue Untertitel-Zeile' }, insertAt);
  const shiftedTail = rows.slice(insertAt).map((row) => {
    if (mode !== 'ripple_forward' || row.locked) return row;
    return { ...row, start: roundSeconds(row.start + duration), end: roundSeconds(row.end + duration) };
  });
  if (mode === 'keep_timing' && next && segment.end > next.start) {
    segment.end = roundSeconds(Math.max(segment.start + MIN_SRT_SEGMENT_DURATION, next.start - DEFAULT_SRT_GAP_SECONDS));
  }
  return renumberSegments([...rows.slice(0, insertAt), segment, ...shiftedTail]);
}

export function insertSegmentBefore(segments, segmentIndex, newSegment = {}, mode = 'keep_timing') {
  return insertSegmentAfter(segments, Math.max(-1, Number(segmentIndex || 0) - 1), newSegment, mode);
}

export function splitSegmentAt(segments, segmentIndex, splitTime, options = {}) {
  const rows = renumberSegments(segments);
  const idx = Number(segmentIndex || 0);
  const row = rows[idx];
  if (!row) return rows;
  const split = roundSeconds(splitTime);
  if (split <= row.start + MIN_SRT_SEGMENT_DURATION || split >= row.end - MIN_SRT_SEGMENT_DURATION) return rows;
  const parts = String(row.text || '').split('\n');
  const firstText = parts.length > 1 ? parts.slice(0, Math.ceil(parts.length / 2)).join('\n') : row.text;
  const secondText = parts.length > 1 ? parts.slice(Math.ceil(parts.length / 2)).join('\n') : (options.emptySecond ? '' : row.text);
  const first = normalizeSrtSegment({ ...row, end: split, text: firstText }, idx);
  const second = normalizeSrtSegment({ start: split, end: row.end, text: secondText }, idx + 1);
  return renumberSegments([...rows.slice(0, idx), first, second, ...rows.slice(idx + 1)], { sort: false });
}

export function mergeWithNeighbor(segments, segmentIndex, direction = 'next') {
  const rows = renumberSegments(segments);
  const idx = Number(segmentIndex || 0);
  const neighborIdx = direction === 'previous' ? idx - 1 : idx + 1;
  if (!rows[idx] || !rows[neighborIdx]) return rows;
  const a = rows[Math.min(idx, neighborIdx)];
  const b = rows[Math.max(idx, neighborIdx)];
  const merged = normalizeSrtSegment({ start: a.start, end: b.end, text: [a.text, b.text].filter(Boolean).join('\n') }, Math.min(idx, neighborIdx));
  const firstIdx = Math.min(idx, neighborIdx);
  const secondIdx = Math.max(idx, neighborIdx);
  const nextRows = rows.filter((_, index) => index !== firstIdx && index !== secondIdx);
  nextRows.splice(firstIdx, 0, merged);
  return renumberSegments(nextRows, { sort: false });
}

export function closeGapBefore(segments, segmentIndex) {
  const rows = renumberSegments(segments);
  const idx = Number(segmentIndex || 0);
  if (idx <= 0 || !rows[idx] || !rows[idx - 1]) return rows;
  rows[idx] = { ...rows[idx], start: rows[idx - 1].end, end: Math.max(rows[idx - 1].end + MIN_SRT_SEGMENT_DURATION, rows[idx].end) };
  return renumberSegments(rows, { sort: false });
}

export function extendPreviousToNext(segments, segmentIndex) {
  const rows = renumberSegments(segments);
  const idx = Number(segmentIndex || 0);
  if (idx <= 0 || !rows[idx] || !rows[idx - 1]) return rows;
  rows[idx - 1] = { ...rows[idx - 1], end: Math.max(rows[idx - 1].start + MIN_SRT_SEGMENT_DURATION, rows[idx].start - DEFAULT_SRT_GAP_SECONDS) };
  return renumberSegments(rows, { sort: false });
}

export function fixOverlaps(segments, minGap = DEFAULT_SRT_GAP_SECONDS) {
  const rows = renumberSegments(segments);
  for (let i = 0; i < rows.length - 1; i += 1) {
    if (rows[i].end + minGap > rows[i + 1].start) {
      rows[i].end = roundSeconds(Math.max(rows[i].start + MIN_SRT_SEGMENT_DURATION, rows[i + 1].start - minGap));
    }
  }
  return renumberSegments(rows, { sort: false });
}

export function setSegmentTime(segments, segmentIndex, field, value) {
  const rows = renumberSegments(segments);
  const idx = Number(segmentIndex || 0);
  if (!rows[idx]) return rows;
  const next = { ...rows[idx], [field]: roundSeconds(clampSeconds(value)) };
  if (next.end <= next.start) next.end = roundSeconds(next.start + MIN_SRT_SEGMENT_DURATION);
  rows[idx] = next;
  return renumberSegments(rows, { sort: false });
}

export function updateSegmentText(segments, segmentIndex, text) {
  const rows = renumberSegments(segments);
  const idx = Number(segmentIndex || 0);
  if (!rows[idx]) return rows;
  rows[idx] = { ...rows[idx], text };
  return renumberSegments(rows, { sort: false });
}
