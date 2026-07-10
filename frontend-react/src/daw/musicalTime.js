// Takt-/Beat-Mathematik: BPM-Erkennung, Beatgrid-Snapping, Bar-Map-Bereiche
// und Ruler-Ticks. Verbatim-Port aus der bisherigen DawPage.
import { clamp, safeNumber, secondsToClock, collectDawTextValues } from './timeUtils.js';

export function inferBpmFromAsset(asset) {
  const explicit = [
    asset?.bpm,
    asset?.tempo,
    asset?.metadata?.bpm,
    asset?.metadata?.tempo,
    asset?.metadata_json?.bpm,
    asset?.metadata_json?.tempo,
    asset?.metadata_json?.request_payload?.bpm,
    asset?.metadata_json?.request_payload?.tempo,
  ];
  for (const value of explicit) {
    const parsed = safeNumber(value, Number.NaN);
    if (Number.isFinite(parsed) && parsed >= 20 && parsed <= 300) return Math.round(parsed * 10) / 10;
  }

  const text = collectDawTextValues({
    tags: asset?.tags,
    style: asset?.style,
    style_prompt: asset?.style_prompt,
    metadata_json: asset?.metadata_json,
    metadata: asset?.metadata,
    candidate: asset?.candidate,
    request_payload: asset?.request_payload,
  }).join(' | ');
  const patterns = [
    /(?:^|[^0-9])([2][0-9]{2}|1[0-9]{2}|[6-9][0-9])\s*bpm\b/i,
    /\bbpm\s*[:=]?\s*([2][0-9]{2}|1[0-9]{2}|[6-9][0-9])\b/i,
    /\btempo\s*[:=]?\s*([2][0-9]{2}|1[0-9]{2}|[6-9][0-9])\b/i,
  ];
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (!match) continue;
    const parsed = safeNumber(match[1], Number.NaN);
    if (Number.isFinite(parsed) && parsed >= 20 && parsed <= 300) return Math.round(parsed * 10) / 10;
  }
  return null;
}

export function sectionBarCandidates(kind = '') {
  if (kind === 'chorus' || kind === 'post_chorus' || kind === 'pre_chorus') return [16, 8, 12, 4, 24, 32];
  if (kind === 'verse') return [16, 24, 32, 12, 8];
  if (kind === 'intro' || kind === 'outro' || kind === 'break' || kind === 'bridge') return [4, 8, 16, 12, 24, 32];
  return [4, 8, 12, 16, 24, 32];
}

export function estimateMusicalBarsForSection(section, bpm) {
  const duration = Math.max(0, safeNumber(section?.duration || (safeNumber(section?.end) - safeNumber(section?.start))));
  const safeBpm = safeNumber(bpm, 0);
  if (!duration || safeBpm < 20) return null;
  const barLength = 240 / safeBpm;
  const candidates = sectionBarCandidates(section?.kind);
  let best = null;
  candidates.forEach((bars, index) => {
    const expected = bars * barLength;
    const diff = Math.abs(duration - expected);
    const score = diff + index * 0.035;
    if (!best || score < best.score) best = { bars, expected, diff, score };
  });
  const tolerance = Math.max(0.65, barLength * 0.45);
  return best && best.diff <= tolerance ? best : null;
}

export function deriveBarGridOffset(sections = [], bpm = 0, fallback = 0) {
  const safeBpm = safeNumber(bpm, 0);
  if (safeBpm < 20) return 0;
  const barLength = 240 / safeBpm;
  const boundaries = [];
  sections.forEach((section) => {
    const start = safeNumber(section?.start, Number.NaN);
    const end = safeNumber(section?.end, Number.NaN);
    if (Number.isFinite(start) && start > 0.05) boundaries.push(start);
    if (Number.isFinite(end) && end > 0.05) boundaries.push(end);
  });
  if (!boundaries.length) return ((safeNumber(fallback) % barLength) + barLength) % barLength;
  let x = 0;
  let y = 0;
  boundaries.forEach((time) => {
    const residue = ((time % barLength) + barLength) % barLength;
    const angle = (residue / barLength) * Math.PI * 2;
    x += Math.cos(angle);
    y += Math.sin(angle);
  });
  if (Math.hypot(x, y) < 0.0001) return ((safeNumber(fallback) % barLength) + barLength) % barLength;
  const angle = Math.atan2(y, x);
  return ((angle / (Math.PI * 2)) * barLength + barLength) % barLength;
}

export function snapToMusicalBar(time, bpm, offset = 0, duration = Infinity) {
  const safeBpm = safeNumber(bpm, 0);
  if (safeBpm < 20) return safeNumber(time);
  const barLength = 240 / safeBpm;
  const snapped = safeNumber(offset) + Math.round((safeNumber(time) - safeNumber(offset)) / barLength) * barLength;
  return clamp(snapped, 0, Number.isFinite(duration) ? duration : Math.max(snapped, 0));
}

export function validDawBeatgrid(grid) {
  return Boolean(grid?.ok && Array.isArray(grid?.bars) && grid.bars.length >= 2);
}

export function dawBeatgridBoundaries(grid, duration = 0) {
  if (!validDawBeatgrid(grid)) return [];
  const boundaries = [];
  (grid.bars || []).forEach((bar) => {
    const start = safeNumber(bar?.start, Number.NaN);
    if (Number.isFinite(start)) boundaries.push(start);
  });
  const lastEnd = safeNumber(grid.bars?.[grid.bars.length - 1]?.end, Number.NaN);
  if (Number.isFinite(lastEnd)) boundaries.push(lastEnd);
  const safeDuration = safeNumber(duration, 0);
  if (safeDuration > 0) boundaries.push(safeDuration);
  return [...new Set(boundaries.map((value) => Math.round(clamp(value, 0, safeDuration || value) * 1000) / 1000))].sort((a, b) => a - b);
}

export function nearestDawBeatgridBoundary(time, grid, duration = 0) {
  const boundaries = dawBeatgridBoundaries(grid, duration);
  if (!boundaries.length) return null;
  const raw = safeNumber(time, 0);
  return boundaries.reduce((best, value) => (Math.abs(value - raw) < Math.abs(best - raw) ? value : best), boundaries[0]);
}

export function nearestDawBeat(time, grid, duration = 0) {
  const beats = Array.isArray(grid?.beats) ? grid.beats.map((value) => safeNumber(value, Number.NaN)).filter(Number.isFinite) : [];
  if (!beats.length) return nearestDawBeatgridBoundary(time, grid, duration);
  const raw = clamp(safeNumber(time, 0), 0, duration || safeNumber(grid?.duration_seconds, 0) || Math.max(...beats));
  return beats.reduce((best, value) => (Math.abs(value - raw) < Math.abs(best - raw) ? value : best), beats[0]);
}

export function snapToDawBeatgrid(time, grid, snapUnit = 'beat', duration = 0) {
  if (!validDawBeatgrid(grid)) return null;
  if (snapUnit === 'bar') return nearestDawBeatgridBoundary(time, grid, duration);
  if (snapUnit === 'beat') return nearestDawBeat(time, grid, duration);
  // Half/quarter are approximated locally from neighbouring beat intervals.
  const beats = Array.isArray(grid?.beats) ? grid.beats.map((value) => safeNumber(value, Number.NaN)).filter(Number.isFinite).sort((a, b) => a - b) : [];
  if (beats.length < 2) return nearestDawBeat(time, grid, duration);
  const raw = clamp(safeNumber(time, 0), 0, duration || safeNumber(grid?.duration_seconds, 0) || beats[beats.length - 1]);
  let best = beats[0];
  let bestDistance = Math.abs(best - raw);
  for (let index = 0; index < beats.length - 1; index += 1) {
    const start = beats[index];
    const end = beats[index + 1];
    const divisions = snapUnit === 'quarter' ? 4 : 2;
    for (let part = 0; part <= divisions; part += 1) {
      const candidate = start + ((end - start) * part) / divisions;
      const distance = Math.abs(candidate - raw);
      if (distance < bestDistance) {
        best = candidate;
        bestDistance = distance;
      }
    }
  }
  return clamp(best, 0, duration || best);
}

export function medianNumber(values = []) {
  const cleaned = values.map((value) => safeNumber(value, Number.NaN)).filter(Number.isFinite).sort((a, b) => a - b);
  if (!cleaned.length) return null;
  const mid = Math.floor(cleaned.length / 2);
  return cleaned.length % 2 ? cleaned[mid] : (cleaned[mid - 1] + cleaned[mid]) / 2;
}

export function medianBarLengthFromGrid(grid) {
  const lengths = (Array.isArray(grid?.bars) ? grid.bars : [])
    .map((bar) => safeNumber(bar?.end) - safeNumber(bar?.start))
    .filter((value) => value > 0.25 && value < 12);
  return medianNumber(lengths) || (safeNumber(grid?.bpm, 0) >= 20 ? 240 / safeNumber(grid.bpm) : null);
}

export function estimateBarsForSectionFromGrid(section, grid, rawStart, rawEnd) {
  const barLength = medianBarLengthFromGrid(grid);
  const duration = Math.max(0, safeNumber(rawEnd) - safeNumber(rawStart));
  if (!barLength || !duration) return null;
  const candidates = sectionBarCandidates(section?.kind);
  let best = null;
  candidates.forEach((bars, index) => {
    const expected = bars * barLength;
    const diff = Math.abs(duration - expected);
    const score = diff + index * 0.025;
    if (!best || score < best.score) best = { bars, expected, diff, score };
  });
  const tolerance = Math.max(0.9, barLength * 0.68);
  if (best && best.diff <= tolerance) return best.bars;
  const rounded = Math.round(duration / barLength);
  return rounded >= 1 && rounded <= 128 ? rounded : null;
}

export function boundaryIndexAtOrBefore(boundaries = [], time = 0, tolerance = 0.12) {
  if (!boundaries.length) return -1;
  const raw = safeNumber(time);
  let index = -1;
  for (let i = 0; i < boundaries.length; i += 1) {
    if (boundaries[i] <= raw + tolerance) index = i;
    else break;
  }
  return index;
}

export function matchingGridSegment(section, grid) {
  if (!section || !Array.isArray(grid?.segments)) return null;
  const kind = String(section.kind || '').toLowerCase();
  const occurrence = safeNumber(section.occurrence, 0);
  const candidates = grid.segments
    .filter((segment) => String(segment?.kind || '').toLowerCase() === kind)
    .sort((a, b) => safeNumber(a?.start) - safeNumber(b?.start));
  if (!candidates.length) return null;
  if (occurrence >= 1 && candidates[occurrence - 1]) return candidates[occurrence - 1];
  const rawStart = safeNumber(section.start);
  return candidates.reduce((best, item) => (Math.abs(safeNumber(item.start) - rawStart) < Math.abs(safeNumber(best.start) - rawStart) ? item : best), candidates[0]);
}

export function dawBeatgridRangeForSection(section, grid, duration = 0) {
  if (!validDawBeatgrid(grid) || !section) return null;
  const maxDuration = duration || safeNumber(grid.duration_seconds, 0);
  const rawStart = clamp(safeNumber(section.start), 0, maxDuration);
  const rawEnd = clamp(safeNumber(section.end), rawStart + 0.25, maxDuration);
  const boundaries = dawBeatgridBoundaries(grid, maxDuration);
  if (boundaries.length < 2) return null;

  const gridSegment = matchingGridSegment(section, grid);
  const segmentStart = gridSegment && Number.isFinite(Number(gridSegment.snapped_start)) ? safeNumber(gridSegment.snapped_start) : null;
  const segmentEnd = gridSegment && Number.isFinite(Number(gridSegment.snapped_end)) ? safeNumber(gridSegment.snapped_end) : null;
  const kind = String(section.kind || '').toLowerCase();
  const isMusicalSection = ['chorus', 'post_chorus', 'pre_chorus', 'verse', 'bridge', 'break', 'intro', 'outro'].includes(kind);
  const barLength = medianBarLengthFromGrid(grid) || 0;
  const barsWanted = estimateBarsForSectionFromGrid(section, grid, rawStart, rawEnd);

  let startIndex = -1;
  let endIndex = -1;

  if (segmentStart != null && segmentEnd != null && segmentEnd > segmentStart + 0.2) {
    startIndex = boundaries.findIndex((value) => Math.abs(value - segmentStart) <= 0.025);
    if (startIndex < 0) startIndex = boundaryIndexAtOrBefore(boundaries, segmentStart, 0.12);
    if (startIndex < 0) startIndex = 0;
    endIndex = boundaries.findIndex((value) => Math.abs(value - segmentEnd) <= 0.025);
  }

  if (startIndex < 0) {
    // For semantic song sections, never cut the beginning late: prefer the last
    // downbeat/bar-boundary at or slightly before the detected structure start.
    startIndex = boundaryIndexAtOrBefore(boundaries, rawStart, 0.14);
    if (startIndex < 0) startIndex = 0;

    // If the detector timestamp is only marginally before the next downbeat,
    // use that next downbeat instead of pulling in a full extra bar.
    const next = boundaries[startIndex + 1];
    if (barLength > 0 && Number.isFinite(next) && next - rawStart >= 0 && next - rawStart <= Math.min(0.18, barLength * 0.08)) {
      startIndex += 1;
    }
  }

  if (barsWanted && isMusicalSection) {
    endIndex = Math.min(boundaries.length - 1, startIndex + barsWanted);
  }
  if (endIndex < 0 || endIndex <= startIndex) {
    // Without a stable bar count, prefer the last boundary at or before the end
    // for chorus/verse style commands. This avoids copying the first half-line
    // of the following section into the duplicate.
    endIndex = boundaryIndexAtOrBefore(boundaries, rawEnd, 0.18);
    if (endIndex <= startIndex) {
      const after = boundaries.findIndex((value) => value > rawEnd + 0.1);
      endIndex = after > startIndex ? after : Math.min(boundaries.length - 1, startIndex + 1);
    }
  }

  let start = clamp(boundaries[startIndex], 0, maxDuration);
  let end = clamp(boundaries[endIndex], start + 0.25, maxDuration);
  if (end <= start + 0.2) {
    start = nearestDawBeatgridBoundary(rawStart, grid, maxDuration);
    end = nearestDawBeatgridBoundary(rawEnd, grid, maxDuration);
  }
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start + 0.2) return null;

  const bars = Math.max(1, endIndex - startIndex) || (grid.bars || []).filter((bar) => safeNumber(bar?.start) >= start - 0.02 && safeNumber(bar?.end) <= end + 0.02).length || null;
  const adjusted = Math.abs(start - rawStart) > 0.035 || Math.abs(end - rawEnd) > 0.035;
  const source = grid.source_label || grid.source || 'local_bar_map';
  const confidence = safeNumber(grid.confidence, null);
  const modeLabel = segmentStart != null ? 'Analyse-Segment + Bar-Map' : 'Bar-Map-Schnitt';
  return {
    start,
    end,
    bars,
    bpm: safeNumber(grid.bpm, null),
    adjusted,
    source,
    confidence,
    label: adjusted
      ? `${modeLabel}: ${secondsToClock(rawStart, true)} – ${secondsToClock(rawEnd, true)} → ${secondsToClock(start, true)} – ${secondsToClock(end, true)}${bars ? ` (${bars} Takte` : ''}${confidence ? `, Sicherheit ${Math.round(confidence * 100)}%` : ''}`
      : `Bar-Map aktiv${bars ? ` (${bars} Takte` : ''}${confidence ? `, Sicherheit ${Math.round(confidence * 100)}%` : ''}`,
  };
}

export function ticksForDuration(duration, zoomLevel = 1) {
  const counts = [8, 10, 12, 16, 20];
  const count = counts[clamp(zoomLevel, 0, counts.length - 1)] || 10;
  return Array.from({ length: count + 1 }, (_, index) => {
    const time = (duration / count) * index;
    const major = index === 0 || index === count || index % 2 === 0;
    return {
      index,
      major,
      time,
      left: `${(index / count) * 100}%`,
      label: secondsToClock(time, zoomLevel >= 3 && duration <= 360),
    };
  });
}
