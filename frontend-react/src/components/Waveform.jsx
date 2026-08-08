import React, { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client.js';
import { useI18n } from '../i18n/I18nContext.jsx';

import {
  assetStructureSegments,
  normalizeStructureSegments,
  parseMaybeJson,
  scaleStructureSegments,
  segmentsHaveDescriptorNoise,
  waveformSegments,
} from '../utils/songStructure.js';

export function useLiveAudioProgress(assetId, initialTime = 0, initialIsPlaying = false) {
  const [liveState, setLiveState] = useState({
    currentTime: Number(initialTime || 0),
    isPlaying: Boolean(initialIsPlaying),
    hasLiveTick: false,
  });

  useEffect(() => {
    setLiveState({
      currentTime: Number(initialTime || 0),
      isPlaying: Boolean(initialIsPlaying),
      hasLiveTick: false,
    });
  }, [assetId, initialTime, initialIsPlaying]);

  useEffect(() => {
    if (typeof window === 'undefined' || !assetId) return undefined;
    const handleProgress = (event) => {
      const detail = event?.detail || {};
      if (String(detail.assetId || '') !== String(assetId)) return;
      setLiveState({
        currentTime: Number(detail.currentTime || 0),
        isPlaying: Boolean(detail.isPlaying),
        hasLiveTick: true,
      });
    };
    window.addEventListener('audio:progress', handleProgress);
    return () => window.removeEventListener('audio:progress', handleProgress);
  }, [assetId]);

  return liveState;
}

function segmentClass(type) {
  return `wave-segment-${String(type || 'section').toLowerCase().replace(/[^a-z0-9_ -]/g, '').replace(/\s+/g, '_')}`;
}

function compactSegmentLabel(segment) {
  const type = String(segment?.type || '').toLowerCase();
  const label = String(segment?.label || '').trim();
  const number = label.match(/\b(\d{1,2})\b/)?.[1] || '';
  if (type === 'verse') return `V${number || ''}`;
  if (type === 'chorus') return /final/i.test(label) ? 'Final' : 'Ch';
  if (type === 'pre_chorus') return 'Pre';
  if (type === 'post_chorus') return 'Post';
  if (type === 'build_up') return 'Build';
  if (type === 'bridge') return 'Br';
  if (type === 'intro') return 'Intro';
  if (type === 'outro') return 'Outro';
  if (type === 'interlude') return 'Inter';
  if (type === 'instrumental') return 'Instr';
  if (type === 'break') return 'Break';
  if (type === 'drop') return 'Drop';
  return label.slice(0, 5);
}

function fallbackPeaks(count = 96) {
  return Array.from({ length: count }, (_, index) => 0.18 + Math.abs(Math.sin(index / 6.5)) * 0.5 + Math.abs(Math.cos(index / 17)) * 0.18);
}

function clampNumber(value, min, max) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return min;
  return Math.max(min, Math.min(max, parsed));
}

function positiveDuration(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) && number > 0 ? number : 0;
}

function resolveWaveformDuration(audio, durationSeconds, waveform, asset) {
  const nativeDuration = positiveDuration(audio?.duration);
  if (nativeDuration > 0) return nativeDuration;
  const propDuration = positiveDuration(durationSeconds);
  if (propDuration > 0) return propDuration;
  const waveformDuration = positiveDuration(waveform?.duration_seconds);
  if (waveformDuration > 0) return waveformDuration;
  return positiveDuration(asset?.duration_seconds);
}

export function Waveform({
  asset,
  audioRef,
  compact = false,
  currentTime = 0,
  durationSeconds = null,
  interactive = true,
  liveProgress = false,
  showProgress = true,
  sourceStartSeconds = 0,
  sourceEndSeconds = null,
  sourceDurationSeconds = null,
  showSegments = true,
}) {
  const { t } = useI18n();
  const [waveform, setWaveform] = useState(asset?.waveform_json || null);
  const [loading, setLoading] = useState(false);
  const [liveCurrentTime, setLiveCurrentTime] = useState(null);

  useEffect(() => {
    setLiveCurrentTime(null);
  }, [asset?.id, currentTime]);

  useEffect(() => {
    if (!liveProgress || typeof window === 'undefined' || !asset?.id) return undefined;
    const handleProgress = (event) => {
      const detail = event?.detail || {};
      if (String(detail.assetId || '') !== String(asset.id)) return;
      setLiveCurrentTime(Number(detail.currentTime || 0));
    };
    window.addEventListener('audio:progress', handleProgress);
    return () => window.removeEventListener('audio:progress', handleProgress);
  }, [asset?.id, liveProgress]);

  useEffect(() => {
    let cancelled = false;
    if (!asset?.id) return undefined;

    const embedded = parseMaybeJson(asset.waveform_json) || null;
    const embeddedSegments = waveformSegments(embedded);
    const structureSegments = assetStructureSegments(asset);
    const shouldRefresh = Boolean(
      !embedded?.peaks?.length
      || segmentsHaveDescriptorNoise(embeddedSegments)
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
        const apiStructure = normalizeStructureSegments(
          data?.structure_segments_json || data?.structure_segments || [],
          positiveDuration(data?.duration_seconds) || positiveDuration(asset?.duration_seconds),
        );
        const apiWaveformSegments = waveformSegments(data);
        const segments = apiStructure.length
          ? apiStructure
          : (apiWaveformSegments.length ? apiWaveformSegments : (structureSegments.length ? structureSegments : embeddedSegments));
        setWaveform({ ...data, segments });
      })
      .catch(() => {
        if (!cancelled) setWaveform(embedded || null);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [asset?.id, asset?.waveform_json, asset?.structure_segments_json, asset?.structure_segments, asset?.updated_at, asset?.waveform_generated_at]);

  const fullSourceDuration = positiveDuration(sourceDurationSeconds)
    || positiveDuration(asset?.duration_seconds)
    || positiveDuration(waveform?.duration_seconds)
    || positiveDuration(durationSeconds)
    || positiveDuration(audioRef?.current?.duration);
  const displaySourceDuration = resolveWaveformDuration(audioRef?.current, durationSeconds, waveform, asset);
  const hasSourceWindow = Number.isFinite(Number(sourceEndSeconds))
    && Number(sourceEndSeconds) > Number(sourceStartSeconds || 0)
    && fullSourceDuration > 0;
  const sourceDuration = hasSourceWindow ? fullSourceDuration : displaySourceDuration;
  const sourceWindowStart = hasSourceWindow ? clampNumber(sourceStartSeconds, 0, sourceDuration) : 0;
  const sourceWindowEnd = hasSourceWindow ? clampNumber(sourceEndSeconds, sourceWindowStart, sourceDuration) : 0;

  const peaks = useMemo(() => {
    const rows = waveform?.peaks?.length ? waveform.peaks : fallbackPeaks(compact ? 72 : 160);
    let visibleRows = rows;
    if (hasSourceWindow && sourceDuration > 0 && rows.length > 4) {
      const startIndex = Math.max(0, Math.floor((sourceWindowStart / sourceDuration) * rows.length));
      const endIndex = Math.min(rows.length, Math.ceil((sourceWindowEnd / sourceDuration) * rows.length));
      visibleRows = rows.slice(startIndex, Math.max(startIndex + 3, endIndex));
    }
    const max = Math.max(...visibleRows, 1);
    return visibleRows.map((value) => Math.max(0.04, Math.min(1, Number(value || 0) / max)));
  }, [waveform, compact, hasSourceWindow, sourceDuration, sourceWindowStart, sourceWindowEnd]);

  const duration = hasSourceWindow
    ? Math.max(0.1, sourceWindowEnd - sourceWindowStart)
    : sourceDuration;
  const effectiveCurrentTime = liveProgress && liveCurrentTime !== null ? liveCurrentTime : currentTime;
  const absoluteCurrentTime = Number.isFinite(Number(effectiveCurrentTime)) ? Number(effectiveCurrentTime) : 0;
  const displayCurrentTime = hasSourceWindow
    ? Math.max(0, Math.min(duration, absoluteCurrentTime - sourceWindowStart))
    : absoluteCurrentTime;
  const segments = useMemo(() => {
    const resolvedWaveformSegments = waveformSegments(waveform);
    const preferred = assetStructureSegments(asset);
    const source = resolvedWaveformSegments.length ? resolvedWaveformSegments : preferred;
    const normalized = scaleStructureSegments(normalizeStructureSegments(source, sourceDuration || duration), sourceDuration || duration);
    if (!hasSourceWindow) return scaleStructureSegments(normalized, duration);
    return normalized
      .map((segment) => {
        const start = Number(segment.start || 0);
        const end = Number(segment.end || start);
        const clippedStart = Math.max(start, sourceWindowStart);
        const clippedEnd = Math.min(end, sourceWindowEnd);
        if (clippedEnd <= clippedStart) return null;
        return {
          ...segment,
          start: clippedStart - sourceWindowStart,
          end: clippedEnd - sourceWindowStart,
          absoluteStart: clippedStart,
        };
      })
      .filter(Boolean);
  }, [asset, waveform, duration, sourceDuration, hasSourceWindow, sourceWindowStart, sourceWindowEnd]);

  function dispatchSeek(seconds, autoplay = true) {
    if (typeof window === 'undefined' || !asset?.id) return;
    window.dispatchEvent(new CustomEvent('audio:seek', {
      detail: { assetId: asset.id, seconds: Number(seconds || 0), autoplay },
    }));
  }

  function seekTo(seconds) {
    const audio = audioRef?.current;
    if (!audio) {
      dispatchSeek(seconds);
      return;
    }
    const safeDuration = resolveWaveformDuration(audio, durationSeconds, waveform, asset);
    const target = Math.max(0, Number(seconds || 0));
    audio.currentTime = safeDuration > 0 ? Math.min(safeDuration, target) : target;
    audio.play().catch(() => null);
  }

  function seekByClick(event) {
    if (!interactive || duration <= 0) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = rect.width > 0 ? (event.clientX - rect.left) / rect.width : 0;
    const target = hasSourceWindow ? sourceWindowStart + ratio * duration : ratio * duration;
    const audio = audioRef?.current;
    if (!audio) {
      dispatchSeek(target);
      return;
    }
    const safeDuration = resolveWaveformDuration(audio, durationSeconds, waveform, asset);
    audio.currentTime = Math.max(0, Math.min(safeDuration || target, target));
    audio.play().catch(() => null);
  }

  const progressRatio = showProgress && duration > 0 ? Math.max(0, Math.min(1, displayCurrentTime / duration)) : 0;
  const activeIndex = showProgress && peaks.length > 0 ? Math.floor(progressRatio * peaks.length) : -1;

  return (
    <div className={`react-waveform ${compact ? 'compact' : ''} ${loading ? 'loading' : ''} ${showProgress && progressRatio > 0 ? 'has-progress' : ''}`}>
      {showSegments && <div className="react-waveform-segments">
        {segments.map((segment, index) => {
          const start = Number(segment.start || 0);
          const end = Number(segment.end || start);
          const left = duration > 0 ? Math.max(0, Math.min(100, (start / duration) * 100)) : 0;
          const width = duration > 0 ? Math.max(1.5, Math.min(100 - left, ((end - start) / duration) * 100)) : 0;
          const absoluteStart = Number.isFinite(Number(segment.absoluteStart)) ? Number(segment.absoluteStart) : start;
          const fullLabelThreshold = compact ? 7 : 4.5;
          const compactLabelThreshold = compact ? 3 : 2.25;
          const labelMode = width >= fullLabelThreshold ? 'full' : width >= compactLabelThreshold ? 'compact' : 'hidden';
          const visibleLabel = labelMode === 'full' ? segment.label : labelMode === 'compact' ? compactSegmentLabel(segment) : '';
          return (
            <button
              key={`${segment.label}-${index}-${start}-${end}`}
              type="button"
              className={`react-waveform-segment ${segmentClass(segment.type)} label-${labelMode}`}
              style={{ left: `${left}%`, width: `${width}%` }}
              onClick={() => seekTo(absoluteStart)}
              title={segment.label || segment.type}
              aria-label={segment.label || segment.type}
            >
              {visibleLabel}
            </button>
          );
        })}
      </div>}
      <button type="button" className="react-waveform-bars" onClick={seekByClick} aria-label={t('waveform.navigation', 'Waveform Navigation')} disabled={!interactive || (!audioRef?.current && !asset?.id)}>
        {peaks.map((value, index) => <span key={index} className={index <= activeIndex ? 'played' : ''} style={{ height: `${Math.max(5, value * 100)}%` }} />)}
      </button>
      {showProgress && progressRatio > 0 && <span className="react-waveform-progress-fill" style={{ width: `${progressRatio * 100}%` }} aria-hidden="true" />}
    </div>
  );
}
