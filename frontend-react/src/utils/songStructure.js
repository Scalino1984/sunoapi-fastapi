const SECTION_PATTERNS = [
  [/\bpre\s*[- ]?(?:chorus|hook|refrain)\b/i, 'Pre-Chorus', 'pre_chorus'],
  [/\bpost\s*[- ]?(?:chorus|hook|refrain)\b/i, 'Post-Chorus', 'post_chorus'],
  [/\b(?:final|last|letzte[rsn]?)\s+(?:chorus|hook|refrain)\b/i, 'Final Chorus', 'chorus'],
  [/\b(?:chorus|hook|refrain)\b/i, 'Chorus', 'chorus'],
  [/\b(?:verse|strophe|part)\s*(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)?\b/i, 'Verse', 'verse'],
  [/\bbuild\s*[- ]?up\b/i, 'Build-Up', 'build_up'],
  [/\bbridge\b|\bmiddle\s*8\b|\bmittelteil\b/i, 'Bridge', 'bridge'],
  [/\bintro\b|\bopening\b|\banfang\b/i, 'Intro', 'intro'],
  [/\boutro\b|\bending\b|\bende\b/i, 'Outro', 'outro'],
  [/\binterlude\b|\bzwischen(?:spiel|teil)\b/i, 'Interlude', 'interlude'],
  [/\bbreak\s*[- ]?down\b|\bbreakdown\b|\bbreak\b/i, 'Break', 'break'],
  [/\bdrop\b|\bclimax\b/i, 'Drop', 'drop'],
  [/\binstrumental\b|\bsolo\b/i, 'Instrumental', 'instrumental'],
];

const NUMBER_WORDS = {
  one: '1',
  two: '2',
  three: '3',
  four: '4',
  five: '5',
  six: '6',
  seven: '7',
  eight: '8',
  nine: '9',
  ten: '10',
};

export function parseMaybeJson(value) {
  if (!value) return null;
  if (Array.isArray(value) || typeof value === 'object') return value;
  if (typeof value === 'string') {
    try { return JSON.parse(value); } catch { return null; }
  }
  return null;
}

function extractSegmentArray(value) {
  const parsed = parseMaybeJson(value);
  if (Array.isArray(parsed)) return parsed;
  if (!parsed || typeof parsed !== 'object') return [];
  for (const key of ['segments', 'structure_segments', 'structureSegments', 'sections', 'items', 'data']) {
    const candidate = parseMaybeJson(parsed[key]);
    if (Array.isArray(candidate)) return candidate;
    if (candidate && typeof candidate === 'object' && candidate !== parsed) {
      const nested = extractSegmentArray(candidate);
      if (nested.length) return nested;
    }
  }
  return [];
}

function normalizedRawLabel(value) {
  return String(value || '')
    .replace(/^\s*\[/, '')
    .replace(/\]\s*$/, '')
    .replace(/[_/]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function primaryTagClause(value) {
  const raw = normalizedRawLabel(value);
  if (!raw) return '';
  return raw.split(/\s*(?:\||:)\s*/, 1)[0].trim();
}

export function structureMarker(label) {
  const raw = normalizedRawLabel(label);
  const primary = primaryTagClause(label);
  if (!primary) return null;
  for (const [pattern, display, type] of SECTION_PATTERNS) {
    const match = primary.match(pattern);
    if (!match) continue;
    let text = display;
    if (type === 'verse' && match[1]) {
      text = `Verse ${NUMBER_WORDS[String(match[1]).toLowerCase()] || match[1]}`;
    }
    // Repeat instructions such as `x2` belong to the lyrics/instruction source,
    // not to the compact visible arrangement label used by the waveforms.
    // They remain available through rawLabel/primaryLabel for reconciliation.
    return { label: text, type, rawLabel: raw, primaryLabel: primary };
  }
  return null;
}

function segmentMarker(segment) {
  if (!segment || typeof segment !== 'object') return null;
  return structureMarker(segment.label)
    || structureMarker(segment.type)
    || structureMarker(segment.name)
    || structureMarker(segment.title)
    || structureMarker(segment.section)
    || structureMarker(segment.kind)
    || structureMarker(segment.tag);
}

function numberFromKeys(segment, keys) {
  for (const key of keys) {
    if (!(key in segment)) continue;
    let value = Number(segment[key]);
    if (!Number.isFinite(value)) continue;
    if (/ms$/i.test(key)) value /= 1000;
    return value;
  }
  return Number.NaN;
}

function rawNormalizedSegments(value) {
  const parsed = extractSegmentArray(value);
  if (!parsed.length) return [];
  return parsed
    .map((segment, sourceIndex) => {
      if (!segment || typeof segment !== 'object') return null;
      const marker = segmentMarker(segment);
      if (!marker) return null;
      let start = numberFromKeys(segment, ['start_seconds', 'startSeconds', 'start_sec', 'startSec', 'start_ms', 'startMs', 'start', 'from', 'begin']);
      let end = numberFromKeys(segment, ['end_seconds', 'endSeconds', 'end_sec', 'endSec', 'end_ms', 'endMs', 'end', 'to', 'until', 'finish']);
      if (!Number.isFinite(start)) start = 0;
      if (!Number.isFinite(end)) end = start;
      start = Math.max(0, start);
      end = Math.max(0, end);
      if (end <= start) return null;
      return {
        ...segment,
        label: marker.label,
        type: marker.type,
        rawLabel: marker.rawLabel,
        start,
        end,
        sourceIndex,
      };
    })
    .filter(Boolean);
}

function segmentSpecificity(segment) {
  const raw = String(segment?.rawLabel || segment?.label || '');
  let score = raw.length;
  if (/final|last|letzte/i.test(raw)) score += 40;
  if (/\bx\s*\d+/i.test(raw)) score += 25;
  if (/\d+/.test(raw)) score += 12;
  if (/pre|post|build/i.test(raw)) score += 10;
  return score;
}

function chooseMoreSpecific(left, right) {
  return segmentSpecificity(right) > segmentSpecificity(left) ? right : left;
}

function dedupeNearIdenticalSegments(segments) {
  const result = [];
  for (const segment of segments) {
    const duplicateIndex = result.findIndex((existing) => (
      existing.type === segment.type
      && Math.abs(existing.start - segment.start) <= 0.45
      && Math.abs(existing.end - segment.end) <= 0.75
    ));
    if (duplicateIndex >= 0) {
      result[duplicateIndex] = chooseMoreSpecific(result[duplicateIndex], segment);
      continue;
    }
    result.push(segment);
  }
  return result;
}

function dropContainedDuplicates(segments) {
  return segments.filter((segment, index) => !segments.some((other, otherIndex) => {
    if (index === otherIndex || other.type !== segment.type) return false;
    const contained = segment.start >= other.start - 0.2 && segment.end <= other.end + 0.2;
    const otherLonger = (other.end - other.start) >= (segment.end - segment.start) + 0.75;
    return contained && otherLonger;
  }));
}

function reconcileTimeline(segments, duration) {
  const safeDuration = Number(duration) > 0 ? Number(duration) : Math.max(0, ...segments.map((segment) => segment.end));
  const ordered = [...segments]
    .sort((a, b) => (a.start - b.start) || (b.end - a.end) || (a.sourceIndex - b.sourceIndex));
  const result = [];
  const minimumDuration = Math.max(0.65, safeDuration * 0.0025);

  for (const rawSegment of ordered) {
    const segment = {
      ...rawSegment,
      start: Math.max(0, Math.min(safeDuration || rawSegment.start, rawSegment.start)),
      end: Math.max(0, Math.min(safeDuration || rawSegment.end, rawSegment.end)),
    };
    if (segment.end - segment.start < minimumDuration) continue;

    const previous = result[result.length - 1];
    if (!previous) {
      result.push(segment);
      continue;
    }

    if (segment.start < previous.end) {
      const overlap = previous.end - segment.start;
      const shorterDuration = Math.min(previous.end - previous.start, segment.end - segment.start);
      if (previous.type === segment.type && overlap >= shorterDuration * 0.55) {
        result[result.length - 1] = chooseMoreSpecific(previous, {
          ...segment,
          start: Math.min(previous.start, segment.start),
          end: Math.max(previous.end, segment.end),
        });
        continue;
      }

      const boundary = segment.start;
      if (boundary - previous.start >= minimumDuration) {
        previous.end = boundary;
      } else {
        result.pop();
      }
    } else {
      const gap = segment.start - previous.end;
      if (gap <= Math.max(1.25, safeDuration * 0.006)) previous.end = segment.start;
    }

    if (segment.end - segment.start >= minimumDuration) result.push(segment);
  }

  return result.filter((segment) => segment.end - segment.start >= minimumDuration);
}

function addOccurrenceLabels(segments) {
  const counters = new Map();
  const genericCounters = new Map();
  const genericTotals = new Map();
  segments.forEach((segment) => {
    const explicit = /\d+|\bx\s*\d+|final|last|letzte/i.test(String(segment.rawLabel || segment.label || ''));
    if (!explicit) genericTotals.set(segment.type, (genericTotals.get(segment.type) || 0) + 1);
  });
  return segments.map((segment) => {
    const occurrence = (counters.get(segment.type) || 0) + 1;
    counters.set(segment.type, occurrence);
    const explicit = /\d+|\bx\s*\d+|final|last|letzte/i.test(String(segment.rawLabel || segment.label || ''));
    const genericOccurrence = (genericCounters.get(segment.type) || 0) + 1;
    if (!explicit) genericCounters.set(segment.type, genericOccurrence);
    const repeatedGeneric = (genericTotals.get(segment.type) || 0) > 1 && !explicit && ['verse', 'chorus', 'bridge', 'break', 'instrumental'].includes(segment.type);
    return {
      ...segment,
      label: repeatedGeneric ? `${segment.label} ${genericOccurrence}` : segment.label,
      occurrence,
    };
  });
}

export function normalizeStructureSegments(value, duration = 0) {
  const parsed = rawNormalizedSegments(value);
  if (!parsed.length) return [];
  const deduped = dedupeNearIdenticalSegments(parsed);
  const containedCleaned = dropContainedDuplicates(deduped);
  return addOccurrenceLabels(reconcileTimeline(containedCleaned, duration));
}

export function assetStructureSegments(asset) {
  for (const candidate of [
    asset?.structure_segments_json,
    asset?.structure_segments,
    asset?.waveform_json?.structure_segments_json,
    asset?.waveform_json?.structure_segments,
    asset?.metadata_json?.structure_segments_json,
    asset?.metadata_json?.structure_segments,
  ]) {
    const segments = extractSegmentArray(candidate);
    if (segments.length) return segments;
  }
  return [];
}

export function waveformSegments(waveform) {
  return extractSegmentArray(waveform);
}

export function segmentsHaveDescriptorNoise(value) {
  const parsed = extractSegmentArray(value);
  if (!parsed.length) return true;
  return parsed.some((segment) => {
    const marker = segmentMarker(segment);
    if (!marker) return true;
    const label = normalizedRawLabel(segment?.label || segment?.type || segment?.name || segment?.title || '');
    return label.toLowerCase() !== marker.label.toLowerCase();
  });
}

export function scaleStructureSegments(segments, duration) {
  const maxDuration = Number(duration || 0);
  if (!segments.length || !(maxDuration > 0)) return segments;
  const sourceEnd = Math.max(0, ...segments.map((segment) => Number(segment.end || 0)).filter(Number.isFinite));
  if (!(sourceEnd > 0)) return segments;
  if (Math.abs(sourceEnd - maxDuration) <= Math.max(1, maxDuration * 0.02)) return segments;
  const ratio = maxDuration / sourceEnd;
  return segments.map((segment) => ({
    ...segment,
    start: Math.max(0, Number(segment.start || 0) * ratio),
    end: Math.max(0, Number(segment.end || 0) * ratio),
  }));
}
