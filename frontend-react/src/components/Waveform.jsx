import React, { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client.js';

const SECTION_PATTERNS = [
  [/\bpre\s*[- ]?chorus\b/i, 'Pre-Chorus', 'pre_chorus'],
  [/\bpost\s*[- ]?chorus\b/i, 'Post-Chorus', 'post_chorus'],
  [/\b(?:final|last)\s+(?:chorus|hook|refrain)\b/i, 'Final Chorus', 'chorus'],
  [/\b(?:chorus|hook|refrain)\b/i, 'Chorus', 'chorus'],
  [/\bverse\s*(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)?\b/i, 'Verse', 'verse'],
  [/\bpart\s*(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)?\b/i, 'Verse', 'verse'],
  [/\bbridge\b/i, 'Bridge', 'bridge'],
  [/\bintro\b/i, 'Intro', 'intro'],
  [/\boutro\b/i, 'Outro', 'outro'],
  [/\binterlude\b/i, 'Interlude', 'interlude'],
  [/\bbreak\s*[- ]?down\b|\bbreakdown\b/i, 'Breakdown', 'breakdown'],
  [/\bdrop\b/i, 'Drop', 'drop'],
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

function parseMaybeJson(value) {
  if (!value) return null;
  if (Array.isArray(value) || typeof value === 'object') return value;
  if (typeof value === 'string') {
    try { return JSON.parse(value); } catch { return null; }
  }
  return null;
}

function structureMarker(label) {
  const raw = String(label || '')
    .replace(/^\s*\[/, '')
    .replace(/\]\s*$/, '')
    .replace(/[_|/]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  if (!raw) return null;
  for (const [pattern, display, type] of SECTION_PATTERNS) {
    const match = raw.match(pattern);
    if (!match) continue;
    let text = display;
    if (type === 'verse' && match[1]) {
      text = `Verse ${NUMBER_WORDS[String(match[1]).toLowerCase()] || match[1]}`;
    }
    return { label: text, type };
  }
  return null;
}

function normalizeSegments(segments) {
  const parsed = parseMaybeJson(segments);
  if (!Array.isArray(parsed)) return [];
  return parsed
    .map((segment) => {
      if (!segment || typeof segment !== 'object') return null;
      const marker = structureMarker(segment.label) || structureMarker(segment.type) || structureMarker(segment.name) || structureMarker(segment.title);
      if (!marker) return null;
      let start = Number(segment.start || 0);
      let end = Number(segment.end || start);
      if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
      start = Math.max(0, start);
      end = Math.max(0, end);
      if (end <= start) return null;
      return { ...segment, label: marker.label, type: marker.type, start, end };
    })
    .filter(Boolean);
}

function segmentMaxEnd(segments) {
  return Math.max(0, ...segments.map((segment) => Number(segment.end || 0)).filter(Number.isFinite));
}

function scaleSegmentsForDisplay(segments, duration) {
  const maxDuration = Number(duration || 0);
  if (!segments.length || !(maxDuration > 0)) return segments;
  const sourceEnd = segmentMaxEnd(segments);
  if (!(sourceEnd > 0)) return segments;
  if (Math.abs(sourceEnd - maxDuration) <= Math.max(1, maxDuration * 0.02)) return segments;
  const ratio = maxDuration / sourceEnd;
  return segments.map((segment) => ({
    ...segment,
    start: Math.max(0, Number(segment.start || 0) * ratio),
    end: Math.max(0, Number(segment.end || 0) * ratio),
  }));
}

function hasDescriptorNoise(segments) {
  const parsed = parseMaybeJson(segments);
  if (!Array.isArray(parsed) || !parsed.length) return true;
  return parsed.some((segment) => {
    if (!segment || typeof segment !== 'object') return true;
    const marker = structureMarker(segment.label) || structureMarker(segment.type) || structureMarker(segment.name) || structureMarker(segment.title);
    if (!marker) return true;
    return String(segment.label || '').trim().toLowerCase() !== marker.label.toLowerCase();
  });
}

function assetStructureSegments(asset) {
  return (
    parseMaybeJson(asset?.structure_segments_json)
    || parseMaybeJson(asset?.structure_segments)
    || parseMaybeJson(asset?.waveform_json?.structure_segments_json)
    || parseMaybeJson(asset?.waveform_json?.structure_segments)
    || parseMaybeJson(asset?.metadata_json?.structure_segments_json)
    || parseMaybeJson(asset?.metadata_json?.structure_segments)
    || []
  );
}

function waveformSegments(waveform) {
  const parsed = parseMaybeJson(waveform);
  if (!parsed || typeof parsed !== 'object') return [];
  return parseMaybeJson(parsed.segments) || [];
}

function segmentClass(type) {
  return `wave-segment-${String(type || 'section').toLowerCase().replace(/[^a-z0-9_ -]/g, '').replace(/\s+/g, '_')}`;
}

function fallbackPeaks(count = 96) {
  return Array.from({ length: count }, (_, index) => 0.18 + Math.abs(Math.sin(index / 6.5)) * 0.5 + Math.abs(Math.cos(index / 17)) * 0.18);
}

export function Waveform({ asset, audioRef, compact = false, currentTime = 0, durationSeconds = null, interactive = true }) {
  const [waveform, setWaveform] = useState(asset?.waveform_json || null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!asset?.id) return undefined;

    const embedded = parseMaybeJson(asset.waveform_json) || null;
    const embeddedSegments = waveformSegments(embedded);
    const structureSegments = assetStructureSegments(asset);
    const shouldRefresh = Boolean(
      !embedded?.peaks?.length
      || hasDescriptorNoise(embeddedSegments)
      || (!structureSegments.length && embeddedSegments.length)
    );

    if (embedded?.peaks?.length) {
      setWaveform({
        ...embedded,
        segments: structureSegments.length ? structureSegments : embeddedSegments,
      });
      if (!shouldRefresh) return undefined;
    }

    setLoading(true);
    api.archive.waveform(asset.id)
      .then((data) => {
        if (cancelled) return;
        const apiStructure = parseMaybeJson(data?.structure_segments_json) || parseMaybeJson(data?.structure_segments) || [];
        const segments = apiStructure.length
          ? apiStructure
          : (Array.isArray(data?.segments) && data.segments.length ? data.segments : (structureSegments.length ? structureSegments : embeddedSegments));
        setWaveform({ ...data, segments });
      })
      .catch(() => {
        if (!cancelled) setWaveform(embedded || null);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [asset?.id, asset?.waveform_json, asset?.structure_segments_json, asset?.structure_segments, asset?.updated_at, asset?.waveform_generated_at]);

  const peaks = useMemo(() => {
    const rows = waveform?.peaks?.length ? waveform.peaks : fallbackPeaks(compact ? 72 : 160);
    const max = Math.max(...rows, 1);
    return rows.map((value) => Math.max(0.04, Math.min(1, Number(value || 0) / max)));
  }, [waveform, compact]);

  const duration = Number(durationSeconds || waveform?.duration_seconds || asset?.duration_seconds || 0);
  const segments = useMemo(() => {
    const preferred = assetStructureSegments(asset);
    const source = preferred.length ? preferred : waveformSegments(waveform);
    return scaleSegmentsForDisplay(normalizeSegments(source), duration);
  }, [asset, waveform, duration]);

  function seekTo(seconds) {
    const audio = audioRef?.current;
    if (!audio) return;
    audio.currentTime = Math.max(0, Number(seconds || 0));
    audio.play().catch(() => null);
  }

  function seekByClick(event) {
    const audio = audioRef?.current;
    if (!interactive || !audio || !Number.isFinite(audio.duration) || audio.duration <= 0) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = rect.width > 0 ? (event.clientX - rect.left) / rect.width : 0;
    audio.currentTime = Math.max(0, Math.min(audio.duration, ratio * audio.duration));
    audio.play().catch(() => null);
  }

  const safeCurrentTime = Number.isFinite(Number(currentTime)) ? Number(currentTime) : 0;
  const progressRatio = duration > 0 ? Math.max(0, Math.min(1, safeCurrentTime / duration)) : 0;
  const activeIndex = peaks.length > 0 ? Math.floor(progressRatio * peaks.length) : -1;

  return (
    <div className={`react-waveform ${compact ? 'compact' : ''} ${loading ? 'loading' : ''} ${progressRatio > 0 ? 'has-progress' : ''}`}>
      <div className="react-waveform-segments">
        {segments.map((segment, index) => {
          const start = Number(segment.start || 0);
          const end = Number(segment.end || start);
          const left = duration > 0 ? Math.max(0, Math.min(100, (start / duration) * 100)) : 0;
          const width = duration > 0 ? Math.max(1.5, Math.min(100 - left, ((end - start) / duration) * 100)) : 0;
          return <button key={`${segment.label}-${index}-${start}-${end}`} type="button" className={`react-waveform-segment ${segmentClass(segment.type)}`} style={{ left: `${left}%`, width: `${width}%` }} onClick={() => seekTo(start)} title={segment.label || segment.type}>{segment.label}</button>;
        })}
      </div>
      <button type="button" className="react-waveform-bars" onClick={seekByClick} aria-label="Waveform Navigation" disabled={!interactive || !audioRef?.current}>
        {peaks.map((value, index) => <span key={index} className={index <= activeIndex ? 'played' : ''} style={{ height: `${Math.max(5, value * 100)}%` }} />)}
      </button>
      {progressRatio > 0 && <span className="react-waveform-progress-line" style={{ left: `${progressRatio * 100}%` }} />}
    </div>
  );
}
