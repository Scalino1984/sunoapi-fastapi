import { DEFAULT_SRT_GAP_SECONDS, MIN_SRT_SEGMENT_DURATION, secondsLabel } from './srtTime.js';
import { exportSrtText, renumberSegments } from './srtParser.js';

const LONG_SEGMENT_SECONDS = 12;
const SHORT_SEGMENT_SECONDS = 0.65;

function makeIssue(segment, severity, type, message) {
  return {
    segmentId: segment?.id,
    index: segment?.index,
    severity,
    type,
    message
  };
}

export function validateSrtSegments(segments = [], options = {}) {
  const minDuration = Number(options.minDuration ?? MIN_SRT_SEGMENT_DURATION);
  const minGap = Number(options.minGap ?? DEFAULT_SRT_GAP_SECONDS);
  const rows = renumberSegments(segments);
  const issues = [];
  if (!rows.length) {
    issues.push(makeIssue(null, 'error', 'format', 'Die Segmentliste ist leer.'));
    return { valid: false, segments: rows, issues };
  }

  let previous = null;
  rows.forEach((segment) => {
    const duration = Number(segment.end) - Number(segment.start);
    if (segment.start < 0) issues.push(makeIssue(segment, 'error', 'negative_time', `Segment ${segment.index} hat eine negative Startzeit.`));
    if (segment.end <= segment.start) issues.push(makeIssue(segment, 'error', 'invalid_duration', `Segment ${segment.index} endet nicht nach dem Start.`));
    else if (duration < minDuration) issues.push(makeIssue(segment, 'error', 'invalid_duration', `Segment ${segment.index} ist kürzer als ${secondsLabel(minDuration)}.`));
    else if (duration < SHORT_SEGMENT_SECONDS) issues.push(makeIssue(segment, 'warning', 'invalid_duration', `Segment ${segment.index} ist sehr kurz (${secondsLabel(duration)}).`));
    else if (duration > LONG_SEGMENT_SECONDS) issues.push(makeIssue(segment, 'warning', 'invalid_duration', `Segment ${segment.index} ist sehr lang (${secondsLabel(duration)}).`));
    if (!String(segment.text || '').trim()) issues.push(makeIssue(segment, 'warning', 'empty_text', `Segment ${segment.index} hat keinen Text.`));
    if (previous) {
      if (previous.end > segment.start) {
        issues.push(makeIssue(segment, 'warning', 'overlap', `Segment ${previous.index} überlappt Segment ${segment.index} um ${secondsLabel(previous.end - segment.start)}.`));
      } else if (segment.start - previous.end > minGap) {
        issues.push(makeIssue(segment, 'info', 'gap', `Lücke zwischen Segment ${previous.index} und ${segment.index}: ${secondsLabel(segment.start - previous.end)}.`));
      }
    }
    previous = segment;
  });

  try {
    if (!exportSrtText(rows).trim()) issues.push(makeIssue(null, 'error', 'format', 'SRT-Export wäre leer.'));
  } catch (error) {
    issues.push(makeIssue(null, 'error', 'format', `SRT-Export fehlgeschlagen: ${error.message}`));
  }

  return { valid: !issues.some((issue) => issue.severity === 'error'), segments: rows, issues };
}

export function issuesForSegment(issues = [], segmentId) {
  return issues.filter((issue) => issue.segmentId === segmentId);
}
