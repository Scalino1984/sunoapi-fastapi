import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useHotkeys } from 'react-hotkeys-hook';
import {
  AlertTriangle,
  ArrowLeft,
  Bot,
  CheckCircle2,
  Copy,
  Download,
  FileAudio,
  Flag,
  GripHorizontal,
  Headphones,
  Loader2,
  Magnet,
  Pause,
  Play,
  Redo2,
  RotateCcw,
  Save,
  Undo2,
  Scissors,
  SkipBack,
  SkipForward,
  SplitSquareHorizontal,
  Trash2,
  Volume2,
} from 'lucide-react';
import { api } from '../api/client.js';
import { Waveform } from '../components/Waveform.jsx';
import { formatDuration, handleCoverImageError, pickCover, pickTitle } from '../utils.js';
import { useI18n } from '../i18n/I18nContext.jsx';

const TRACKS = [
  { id: 'track-1', name: 'Spur 1' },
  { id: 'track-2', name: 'Spur 2' },
  { id: 'track-3', name: 'Spur 3' },
];
const TOOL_MODES = [
  { id: 'select', label: 'Auswahl', icon: GripHorizontal },
  { id: 'range', label: 'Bereich', icon: Flag },
  { id: 'split', label: 'Schere', icon: Scissors },
  { id: 'marker', label: 'Marker', icon: Flag },
];
const SNAP_UNITS = [
  { id: 'bar', label: 'Takt' },
  { id: 'beat', label: 'Beat' },
  { id: 'half', label: '1/2' },
  { id: 'quarter', label: '1/4' },
];
const TOOL_HELP = {
  select: {
    title: 'Auswahl aktiv',
    text: 'Clip anklicken, halten und ziehen. Linken oder rechten Rand ziehen zum Kürzen.',
  },
  range: {
    title: 'Bereich markieren',
    text: 'In freie Timeline-Fläche ziehen, danach Bereich entfernen oder als Short nutzen.',
  },
  split: {
    title: 'Schere aktiv',
    text: 'Klick in einen Clip oder S drücken, um am Playhead zu schneiden.',
  },
  marker: {
    title: 'Marker setzen',
    text: 'Klick in die Timeline oder M drücken, um einen Marker am Playhead zu setzen.',
  },
};
const OUTPUT_FORMATS = ['mp3', 'wav', 'm4a'];
const HISTORY_LIMIT = 40;

function cloneArrangementSnapshot(value) {
  if (!value) return null;
  try { return JSON.parse(JSON.stringify(value)); } catch { return null; }
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, Number(value || 0)));
}

function safeNumber(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function clipDuration(clip) {
  return Math.max(0, safeNumber(clip?.source_end) - safeNumber(clip?.source_start));
}

function normalizeFadePair(fadeInValue, fadeOutValue, durationValue) {
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

function fadeHandlePercent(value, durationValue, side = 'left') {
  const duration = Math.max(0.1, safeNumber(durationValue, 0.1));
  const raw = clamp((safeNumber(value) / duration) * 100, 0, 50);
  if (side === 'right') return clamp(100 - raw, 50, 99.2);
  return clamp(raw, 0.8, 50);
}

function secondsToClock(value, withTenths = false) {
  const total = Math.max(0, Number(value || 0));
  const minutes = Math.floor(total / 60);
  const seconds = Math.floor(total % 60);
  if (!withTenths) return `${minutes}:${String(seconds).padStart(2, '0')}`;
  const tenths = Math.floor((total % 1) * 10);
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${tenths}`;
}

function percent(value, duration) {
  if (!duration) return 0;
  return clamp((safeNumber(value) / duration) * 100, 0, 100);
}

function makeId(prefix) {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function arrangementLength(arrangement, fallbackDuration = 0) {
  const clips = Array.isArray(arrangement?.clips) ? arrangement.clips : [];
  const clipEnd = clips.reduce((max, clip) => Math.max(max, safeNumber(clip.timeline_start) + clipDuration(clip)), 0);
  const markerEnd = (arrangement?.markers || []).reduce((max, marker) => Math.max(max, safeNumber(marker.time)), 0);
  return Math.max(1, safeNumber(arrangement?.duration_seconds), fallbackDuration, clipEnd, markerEnd);
}

function buildDefaultArrangement(asset, duration = 0) {
  const safeDuration = Math.max(1, safeNumber(duration || asset?.duration_seconds, 1));
  const title = pickTitle(asset) || `Audio ${asset?.id || ''}`;
  return {
    version: 1,
    source_audio_id: Number(asset?.id || 0),
    duration_seconds: safeDuration,
    bpm: null,
    time_signature: '4/4',
    snap_enabled: false,
    snap_unit: 'beat',
    tracks: TRACKS.map((track) => ({ ...track, muted: false, solo: false, volume_db: 0 })),
    clips: [{
      id: makeId('clip'),
      track_id: 'track-1',
      source_audio_id: Number(asset?.id || 0),
      timeline_start: 0,
      source_start: 0,
      source_end: safeDuration,
      gain_db: 0,
      fade_in: 0,
      fade_out: 0,
      label: title,
      muted: false,
      locked: false,
      color: 'cyan',
    }],
    markers: [],
  };
}

function normalizeArrangement(raw, asset, duration = 0) {
  const base = buildDefaultArrangement(asset, duration);
  if (!raw || typeof raw !== 'object') return base;
  const tracks = Array.isArray(raw.tracks) && raw.tracks.length ? raw.tracks.slice(0, 3) : base.tracks;
  const validTrackIds = new Set(tracks.map((track, index) => track?.id || `track-${index + 1}`));
  const sourceDuration = Math.max(0, safeNumber(duration || asset?.duration_seconds, 0));
  const minClipLength = 0.25;
  const clips = (Array.isArray(raw.clips) ? raw.clips : base.clips).map((clip, index) => {
    let sourceStart = Math.max(0, safeNumber(clip?.source_start));
    let sourceEnd = safeNumber(clip?.source_end, sourceStart + 1);
    if (sourceDuration > minClipLength) {
      sourceStart = clamp(sourceStart, 0, Math.max(0, sourceDuration - minClipLength));
      sourceEnd = clamp(sourceEnd, sourceStart + minClipLength, sourceDuration);
    }
    if (sourceEnd <= sourceStart) sourceEnd = sourceStart + minClipLength;
    const trackId = validTrackIds.has(clip?.track_id) ? clip.track_id : 'track-1';
    const fades = normalizeFadePair(clip?.fade_in, clip?.fade_out, sourceEnd - sourceStart);
    return {
      id: String(clip?.id || makeId(`clip-${index + 1}`)),
      track_id: trackId,
      source_audio_id: Number(clip?.source_audio_id || asset?.id || 0),
      timeline_start: Math.max(0, safeNumber(clip?.timeline_start)),
      source_start: sourceStart,
      source_end: sourceEnd,
      gain_db: clamp(safeNumber(clip?.gain_db), -24, 24),
      fade_in: fades.fadeIn,
      fade_out: fades.fadeOut,
      label: String(clip?.label || pickTitle(asset) || `Clip ${index + 1}`),
      muted: Boolean(clip?.muted),
      locked: Boolean(clip?.locked),
      color: String(clip?.color || 'cyan'),
    };
  });
  return {
    ...base,
    ...raw,
    source_audio_id: Number(asset?.id || raw.source_audio_id || 0),
    duration_seconds: arrangementLength({ ...raw, clips }, base.duration_seconds),
    tracks: tracks.map((track, index) => ({
      id: String(track?.id || `track-${index + 1}`),
      name: String(track?.name || `Spur ${index + 1}`),
      muted: Boolean(track?.muted),
      solo: Boolean(track?.solo),
      volume_db: clamp(safeNumber(track?.volume_db), -24, 24),
    })),
    clips,
    markers: (Array.isArray(raw.markers) ? raw.markers : []).map((marker, index) => ({
      id: String(marker?.id || makeId(`marker-${index + 1}`)),
      label: String(marker?.label || 'Marker'),
      time: Math.max(0, safeNumber(marker?.time)),
      type: String(marker?.type || 'marker'),
      note: marker?.note || null,
    })).sort((a, b) => a.time - b.time),
    snap_enabled: Boolean(raw.snap_enabled),
    snap_unit: ['bar', 'beat', 'half', 'quarter'].includes(raw.snap_unit) ? raw.snap_unit : 'beat',
    bpm: raw.bpm ? clamp(safeNumber(raw.bpm), 20, 300) : null,
  };
}

function ticksForDuration(duration) {
  const count = duration > 600 ? 12 : 8;
  return Array.from({ length: count + 1 }, (_, index) => {
    const time = (duration / count) * index;
    return { time, left: `${(index / count) * 100}%`, label: secondsToClock(time) };
  });
}

function usePointerDrag(onMove, onEnd) {
  const state = useRef(null);
  useEffect(() => {
    function handleMove(event) {
      if (!state.current) return;
      onMove(event, state.current);
    }
    function handleEnd(event) {
      if (!state.current) return;
      const current = state.current;
      state.current = null;
      onEnd?.(event, current);
    }
    window.addEventListener('pointermove', handleMove);
    window.addEventListener('pointerup', handleEnd);
    window.addEventListener('pointercancel', handleEnd);
    return () => {
      window.removeEventListener('pointermove', handleMove);
      window.removeEventListener('pointerup', handleEnd);
      window.removeEventListener('pointercancel', handleEnd);
    };
  }, [onMove, onEnd]);
  return state;
}

function DawEmptyState({ t, lastKnownAsset, onOpenLast, onBackToLibrary }) {
  return (
    <section className="panel empty-state daw-empty-state">
      <Scissors size={34} />
      <h3>{t('daw.empty.title', 'Kein Audio ausgewählt')}</h3>
      <p>{t('daw.empty.description', 'Öffne einen Song oder eine Variante aus der Library über „In Mini-DAW öffnen“.')}</p>
      <div className="button-row wrap">
        <button className="primary" type="button" onClick={onBackToLibrary}><ArrowLeft size={15} /> {t('daw.backToLibrary', 'Zur Library')}</button>
        {lastKnownAsset && <button type="button" onClick={onOpenLast}><FileAudio size={15} /> Zuletzt öffnen</button>}
      </div>
    </section>
  );
}

export function DawPage({ assets = [], selectedAssetId = null, onSelectedHandled, onAssetChange, onBackToLibrary, onPlay, notify, onReload }) {
  const { t } = useI18n();
  const playable = useMemo(() => (assets || []).filter((asset) => asset?.id && (asset.public_url || asset.local_path || asset.source_url)), [assets]);
  const [assetId, setAssetId] = useState(() => String(selectedAssetId || '').trim());
  const [lastKnownAssetId, setLastKnownAssetId] = useState(() => localStorage.getItem('react-daw-asset-id') || '');
  const [project, setProject] = useState(null);
  const [arrangement, setArrangement] = useState(null);
  const [selectedClipId, setSelectedClipId] = useState('');
  const [undoStack, setUndoStack] = useState([]);
  const [redoStack, setRedoStack] = useState([]);
  const [toolMode, setToolMode] = useState('select');
  const [currentTime, setCurrentTime] = useState(0);
  const [mediaDuration, setMediaDuration] = useState(0);
  const [selection, setSelection] = useState(null);
  const [closeGap, setCloseGap] = useState(true);
  const [outputFormat, setOutputFormat] = useState('mp3');
  const [versionLabel, setVersionLabel] = useState('DAW Arrangement');
  const [previewUrl, setPreviewUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [renderTask, setRenderTask] = useState(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [volume, setVolume] = useState(1);
  const [dragTooltip, setDragTooltip] = useState(null);
  const audioRef = useRef(null);
  const timelineRef = useRef(null);
  const arrangementRef = useRef(null);
  const timelineDurationRef = useRef(1);
  const snapTimeRef = useRef((value) => Number(value || 0));
  const selectedClipIdRef = useRef('');

  const currentAsset = project?.asset || playable.find((asset) => String(asset.id) === String(assetId));
  const lastKnownAsset = playable.find((asset) => String(asset.id) === String(lastKnownAssetId));
  const audioUrl = currentAsset?.public_url ? api.archive.streamUrl(currentAsset.id) : currentAsset?.source_url;
  const timelineDuration = arrangementLength(arrangement, mediaDuration || currentAsset?.duration_seconds || 1);
  const selectedClip = (arrangement?.clips || []).find((clip) => clip.id === selectedClipId) || null;
  const ticks = ticksForDuration(timelineDuration);
  const sourceDuration = Math.max(0, safeNumber(mediaDuration), safeNumber(currentAsset?.duration_seconds));

  function showDragTimeTooltip(event, payload) {
    if (!event) return;
    setDragTooltip({
      x: event.clientX,
      y: event.clientY,
      mode: payload?.mode || 'info',
      title: payload?.title || '',
      rows: Array.isArray(payload?.rows) ? payload.rows : [],
    });
  }

  function hideDragTimeTooltip() {
    setDragTooltip(null);
  }

  const snapTime = useCallback((value) => {
    const raw = clamp(value, 0, timelineDuration);
    if (!arrangement?.snap_enabled || !arrangement?.bpm) return raw;
    const beat = 60 / Number(arrangement.bpm);
    const unit = arrangement.snap_unit === 'bar' ? beat * 4 : arrangement.snap_unit === 'half' ? beat / 2 : arrangement.snap_unit === 'quarter' ? beat / 4 : beat;
    return clamp(Math.round(raw / unit) * unit, 0, timelineDuration);
  }, [arrangement?.bpm, arrangement?.snap_enabled, arrangement?.snap_unit, timelineDuration]);

  useEffect(() => { arrangementRef.current = arrangement; }, [arrangement]);
  useEffect(() => { timelineDurationRef.current = timelineDuration; }, [timelineDuration]);
  useEffect(() => { snapTimeRef.current = snapTime; }, [snapTime]);
  useEffect(() => { selectedClipIdRef.current = selectedClipId; }, [selectedClipId]);

  const renderTaskStatus = String(renderTask?.status || '').toUpperCase();
  const renderTaskActive = Boolean(renderTask?.id || renderTask?.task_local_id) && !['SUCCESS', 'COMPLETED', 'COMPLETE', 'DONE', 'FAILED', 'ERROR', 'CANCELLED', 'COMPLETED_MANUAL'].includes(renderTaskStatus);
  const renderTaskProgress = Number(renderTask?.response_payload?.progress?.percent ?? renderTask?.progress ?? 0);
  const renderTaskPhase = renderTask?.response_payload?.progress?.message || renderTask?.response_payload?.progress?.phase || renderTask?.error_message || '';

  useEffect(() => {
    const taskId = renderTask?.id || renderTask?.task_local_id;
    if (!taskId || !renderTaskActive) return undefined;
    let cancelled = false;
    const poll = async () => {
      try {
        const fresh = await api.music.getTask(taskId);
        if (cancelled) return;
        setRenderTask(fresh);
        const status = String(fresh?.status || '').toUpperCase();
        if (['SUCCESS', 'COMPLETED', 'COMPLETE', 'DONE'].includes(status)) {
          notify?.('DAW-Version wurde fertig gespeichert.', 'success');
          onReload?.();
        }
        if (['FAILED', 'ERROR', 'CANCELLED'].includes(status)) {
          notify?.(fresh?.error_message || 'DAW-Render wurde beendet oder ist fehlgeschlagen.', status === 'CANCELLED' ? 'warning' : 'error');
        }
      } catch {
        // Polling darf den Editor nicht blockieren; Statusseite/Topbar behalten ebenfalls den Task.
      }
    };
    const timer = window.setInterval(poll, 1800);
    poll();
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [renderTask?.id, renderTask?.task_local_id, renderTaskActive, notify, onReload]);

  const rawTimeFromPointer = useCallback((event) => {
    const rect = timelineRef.current?.getBoundingClientRect();
    if (!rect) return 0;
    const x = clamp(event.clientX - rect.left, 0, rect.width);
    return clamp((x / rect.width) * timelineDuration, 0, timelineDuration);
  }, [timelineDuration]);

  const timeFromPointer = useCallback((event) => {
    return snapTime(rawTimeFromPointer(event));
  }, [rawTimeFromPointer, snapTime]);

  const secondsFromPixels = useCallback((pixels) => {
    const rect = timelineRef.current?.getBoundingClientRect();
    if (!rect?.width) return 0;
    return (Number(pixels || 0) / rect.width) * timelineDurationRef.current;
  }, []);

  const trackIdFromClientY = useCallback((clientY, fallback = 'track-1') => {
    const rows = Array.from(timelineRef.current?.querySelectorAll('.daw-arr-track-row') || []);
    const row = rows.find((item) => {
      const rect = item.getBoundingClientRect();
      return clientY >= rect.top && clientY <= rect.bottom;
    });
    return row?.getAttribute('data-track-id') || fallback;
  }, []);

  const updateArrangement = useCallback((updater) => {
    setArrangement((current) => {
      const base = normalizeArrangement(current, currentAsset, mediaDuration || currentAsset?.duration_seconds || 1);
      const next = typeof updater === 'function' ? updater(base) : updater;
      return normalizeArrangement(next, currentAsset, mediaDuration || currentAsset?.duration_seconds || 1);
    });
  }, [currentAsset, mediaDuration]);

  const commitArrangementHistory = useCallback((snapshot = arrangementRef.current) => {
    const cloned = cloneArrangementSnapshot(snapshot);
    if (!cloned) return;
    setUndoStack((items) => [...items.slice(-(HISTORY_LIMIT - 1)), cloned]);
    setRedoStack([]);
  }, []);

  const restoreArrangementSnapshot = useCallback((snapshot) => {
    const cloned = cloneArrangementSnapshot(snapshot);
    if (!cloned) return;
    const normalized = normalizeArrangement(cloned, currentAsset, mediaDuration || currentAsset?.duration_seconds || 1);
    setArrangement(normalized);
    setSelectedClipId((current) => normalized.clips.some((clip) => clip.id === current) ? current : (normalized.clips[0]?.id || ''));
    setSelection(null);
  }, [currentAsset, mediaDuration]);

  const undoArrangement = useCallback(() => {
    setUndoStack((items) => {
      if (!items.length) return items;
      const previous = items[items.length - 1];
      const current = cloneArrangementSnapshot(arrangementRef.current);
      if (current) setRedoStack((redoItems) => [...redoItems.slice(-(HISTORY_LIMIT - 1)), current]);
      restoreArrangementSnapshot(previous);
      return items.slice(0, -1);
    });
  }, [restoreArrangementSnapshot]);

  const redoArrangement = useCallback(() => {
    setRedoStack((items) => {
      if (!items.length) return items;
      const next = items[items.length - 1];
      const current = cloneArrangementSnapshot(arrangementRef.current);
      if (current) setUndoStack((undoItems) => [...undoItems.slice(-(HISTORY_LIMIT - 1)), current]);
      restoreArrangementSnapshot(next);
      return items.slice(0, -1);
    });
  }, [restoreArrangementSnapshot]);

  const selectAsset = useCallback((nextAssetId, options = {}) => {
    const normalized = String(nextAssetId || '').trim();
    setAssetId(normalized);
    setProject(null);
    setArrangement(null);
    setSelectedClipId('');
    setMediaDuration(0);
    setSelection(null);
    setUndoStack([]);
    setRedoStack([]);
    setCurrentTime(0);
    setPreviewUrl((current) => { if (current) URL.revokeObjectURL(current); return ''; });
    if (normalized) {
      localStorage.setItem('react-daw-asset-id', normalized);
      setLastKnownAssetId(normalized);
    }
    if (options.notifyParent !== false) onAssetChange?.(normalized);
  }, [onAssetChange]);

  useEffect(() => {
    const normalized = String(selectedAssetId || '').trim();
    if (normalized === String(assetId || '').trim()) {
      onSelectedHandled?.();
      return;
    }
    selectAsset(normalized, { notifyParent: false });
    onSelectedHandled?.();
  }, [selectedAssetId, assetId, selectAsset, onSelectedHandled]);

  useEffect(() => {
    if (!assetId) return;
    setLoading(true);
    Promise.all([api.daw.project(assetId), api.daw.getArrangement(assetId)])
      .then(([projectResult, arrangementResult]) => {
        setProject(projectResult);
        const asset = projectResult?.asset || playable.find((item) => String(item.id) === String(assetId));
        const nextArrangement = normalizeArrangement(arrangementResult?.arrangement, asset, asset?.duration_seconds || 1);
        setArrangement(nextArrangement);
        setSelectedClipId(nextArrangement.clips?.[0]?.id || '');
        setVersionLabel('DAW Arrangement');
      })
      .catch((err) => notify?.(err.message || 'DAW-Projekt konnte nicht geladen werden.', 'error'))
      .finally(() => setLoading(false));
  }, [assetId]);

  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl); }, [previewUrl]);

  const dragState = usePointerDrag(
    (event, state) => {
      if (!arrangement) return;
      const nextTime = timeFromPointer(event);
      if (state.kind === 'range') {
        const nextSelection = { start: Math.min(state.start, nextTime), end: Math.max(state.start, nextTime) };
        setSelection(nextSelection);
        showDragTimeTooltip(event, {
          mode: 'range',
          title: 'Bereich',
          rows: [
            `Start ${secondsToClock(nextSelection.start, true)}`,
            `Ende ${secondsToClock(nextSelection.end, true)}`,
            `Länge ${secondsToClock(nextSelection.end - nextSelection.start, true)}`,
          ],
        });
        return;
      }
      if (state.kind === 'playhead') {
        seekTo(nextTime);
        showDragTimeTooltip(event, { mode: 'playhead', title: 'Playhead', rows: [secondsToClock(nextTime, true)] });
        return;
      }
      if (state.kind === 'move') {
        state.moved = true;
        const delta = secondsFromPixels(event.clientX - state.startClientX);
        const nextStart = snapTime(Math.max(0, state.originalStart + delta));
        const nextTrackId = trackIdFromClientY(event.clientY, state.originalTrackId);
        showDragTimeTooltip(event, {
          mode: 'move',
          title: 'Clip verschieben',
          rows: [
            `Position ${secondsToClock(nextStart, true)}`,
            `Spur ${nextTrackId.replace('track-', '')}`,
          ],
        });
        updateArrangement((current) => ({
          ...current,
          clips: current.clips.map((clip) => clip.id === state.clipId ? { ...clip, timeline_start: nextStart, track_id: nextTrackId } : clip),
        }));
        return;
      }
      if (state.kind === 'fade') {
        state.moved = true;
        const rawTime = rawTimeFromPointer(event);
        const minGap = 0.05;
        const clipStart = state.originalTimelineStart;
        const clipEnd = state.originalTimelineStart + state.originalDuration;
        const maxFade = Math.max(0, state.originalDuration - minGap);
        let nextFade = 0;
        let patch = null;
        let tooltipPayload = null;

        if (state.edge === 'in') {
          nextFade = clamp(rawTime - clipStart, 0, maxFade);
          const fades = normalizeFadePair(nextFade, state.originalFadeOut, state.originalDuration);
          patch = { fade_in: fades.fadeIn, fade_out: fades.fadeOut };
          tooltipPayload = {
            mode: 'fade',
            title: 'Fade-in',
            rows: [
              `Fade-in ${secondsToClock(fades.fadeIn, true)}`,
              `endet bei ${secondsToClock(clipStart + fades.fadeIn, true)}`,
              `Clip-Länge ${secondsToClock(state.originalDuration, true)}`,
            ],
          };
        } else {
          nextFade = clamp(clipEnd - rawTime, 0, maxFade);
          const fades = normalizeFadePair(state.originalFadeIn, nextFade, state.originalDuration);
          patch = { fade_in: fades.fadeIn, fade_out: fades.fadeOut };
          tooltipPayload = {
            mode: 'fade',
            title: 'Fade-out',
            rows: [
              `Fade-out ${secondsToClock(fades.fadeOut, true)}`,
              `startet bei ${secondsToClock(clipEnd - fades.fadeOut, true)}`,
              `Clip-Ende ${secondsToClock(clipEnd, true)}`,
            ],
          };
        }

        showDragTimeTooltip(event, tooltipPayload);
        updateArrangement((current) => ({
          ...current,
          clips: current.clips.map((clip) => clip.id === state.clipId ? { ...clip, ...patch } : clip),
        }));
        return;
      }
      if (state.kind === 'resize') {
        state.moved = true;
        const delta = secondsFromPixels(event.clientX - state.startClientX);
        const minLength = 0.25;
        const sourceLimit = Math.max(minLength, state.sourceDuration || state.originalSourceEnd);
        let clipPatch = null;
        let tooltipPayload = null;

        if (state.edge === 'left') {
          const maxPositive = Math.max(0, state.originalDuration - minLength);
          const minNegative = -Math.min(state.originalSourceStart, state.originalTimelineStart);
          const rawTimelineStart = Math.max(0, state.originalTimelineStart + delta);
          const snappedTimelineStart = snapTime(rawTimelineStart);
          const snappedDelta = snappedTimelineStart - state.originalTimelineStart;
          const limitedDelta = clamp(snappedDelta, minNegative, maxPositive);
          const nextTimelineStart = Math.max(0, state.originalTimelineStart + limitedDelta);
          const nextSourceStart = clamp(state.originalSourceStart + limitedDelta, 0, Math.max(0, sourceLimit - minLength));
          const nextLength = Math.max(minLength, state.originalSourceEnd - nextSourceStart);
          clipPatch = {
            timeline_start: nextTimelineStart,
            source_start: nextSourceStart,
            source_end: state.originalSourceEnd,
          };
          tooltipPayload = {
            mode: 'trim',
            title: 'Linke Kante',
            rows: [
              `Start ${secondsToClock(nextTimelineStart, true)}`,
              `Quelle ${secondsToClock(nextSourceStart, true)}`,
              `Länge ${secondsToClock(nextLength, true)}`,
            ],
          };
        } else {
          const rawDuration = state.originalDuration + delta;
          const snappedEnd = snapTime(state.originalTimelineStart + rawDuration);
          const snappedDuration = snappedEnd - state.originalTimelineStart;
          const limitedDuration = clamp(snappedDuration, minLength, Math.max(minLength, sourceLimit - state.originalSourceStart));
          const nextSourceEnd = state.originalSourceStart + limitedDuration;
          const nextTimelineEnd = state.originalTimelineStart + limitedDuration;
          clipPatch = { source_end: nextSourceEnd };
          tooltipPayload = {
            mode: 'trim',
            title: 'Rechte Kante',
            rows: [
              `Ende ${secondsToClock(nextTimelineEnd, true)}`,
              `Quelle ${secondsToClock(nextSourceEnd, true)}`,
              `Länge ${secondsToClock(limitedDuration, true)}`,
            ],
          };
        }

        // Tooltip-Werte werden bewusst vor dem React-State-Update berechnet.
        // Sonst bleibt bei gebatchten setState-Aufrufen nur der Wert vom PointerDown sichtbar.
        showDragTimeTooltip(event, tooltipPayload);
        updateArrangement((current) => ({
          ...current,
          clips: current.clips.map((clip) => clip.id === state.clipId ? { ...clip, ...clipPatch } : clip),
        }));
      }
    },
    (event, state) => {
      if (state.kind === 'range') {
        const nextTime = timeFromPointer(event);
        const nextSelection = { start: Math.min(state.start, nextTime), end: Math.max(state.start, nextTime) };
        if (nextSelection.end - nextSelection.start < 0.1) setSelection(null);
        else setSelection(nextSelection);
      }
      if ((state.kind === 'move' || state.kind === 'resize' || state.kind === 'fade') && state.clipId) {
        setSelectedClipId(state.clipId);
        if (state.moved) commitArrangementHistory(state.originalArrangement);
      }
      hideDragTimeTooltip();
    }
  );

  function handleDurationDetected(event) {
    const duration = safeNumber(event.currentTarget?.duration, 0);
    if (duration > 0) {
      setMediaDuration(duration);
      setArrangement((current) => current ? normalizeArrangement({ ...current, duration_seconds: Math.max(current.duration_seconds || 0, duration) }, currentAsset, duration) : current);
    }
  }

  function seekTo(time) {
    const next = snapTime(time);
    setCurrentTime(next);
    if (audioRef.current) audioRef.current.currentTime = clamp(next, 0, safeNumber(audioRef.current.duration, next));
  }

  async function togglePlayback() {
    if (!audioRef.current) return;
    try {
      if (audioRef.current.paused) {
        await audioRef.current.play();
        setIsPlaying(true);
      } else {
        audioRef.current.pause();
        setIsPlaying(false);
      }
    } catch {
      setIsPlaying(false);
    }
  }

  function addMarkerAt(time = currentTime) {
    commitArrangementHistory();
    const nextTime = snapTime(time);
    updateArrangement((current) => ({
      ...current,
      markers: [...(current.markers || []), { id: makeId('marker'), label: `Marker ${current.markers.length + 1}`, time: nextTime, type: 'marker', note: null }].sort((a, b) => a.time - b.time),
    }));
    setCurrentTime(nextTime);
  }

  function splitClipAt(time = currentTime, clipId = selectedClipId) {
    if (!arrangement) return;
    const target = arrangement.clips.find((clip) => clip.id === clipId) || arrangement.clips.find((clip) => time > clip.timeline_start && time < clip.timeline_start + clipDuration(clip));
    if (!target || target.locked) return notify?.('Kein Clip am Schnittpunkt gefunden.', 'error');
    const splitTime = snapTime(time);
    const offset = splitTime - safeNumber(target.timeline_start);
    const length = clipDuration(target);
    if (offset <= 0.05 || offset >= length - 0.05) return notify?.('Schnittpunkt liegt zu nah am Clip-Rand.', 'error');
    const left = { ...target, id: makeId('clip'), source_end: safeNumber(target.source_start) + offset };
    const right = { ...target, id: makeId('clip'), timeline_start: splitTime, source_start: safeNumber(target.source_start) + offset };
    commitArrangementHistory();
    updateArrangement((current) => ({
      ...current,
      clips: current.clips.flatMap((clip) => clip.id === target.id ? [left, right] : [clip]),
    }));
    setSelectedClipId(right.id);
    notify?.('Clip am Playhead geteilt.', 'success');
  }

  function cutRange() {
    const range = selection;
    if (!arrangement || !range || range.end - range.start <= 0.05) return notify?.('Bitte zuerst einen Bereich in der Timeline markieren.', 'error');
    const cutStart = snapTime(range.start);
    const cutEnd = snapTime(range.end);
    const cutLength = cutEnd - cutStart;
    commitArrangementHistory();
    updateArrangement((current) => {
      const nextClips = [];
      for (const clip of current.clips) {
        if (clip.locked) {
          nextClips.push(clip);
          continue;
        }
        const start = safeNumber(clip.timeline_start);
        const end = start + clipDuration(clip);
        if (end <= cutStart || start >= cutEnd) {
          const shifted = closeGap && start >= cutEnd ? { ...clip, timeline_start: Math.max(0, start - cutLength) } : clip;
          nextClips.push(shifted);
          continue;
        }
        if (start < cutStart) {
          nextClips.push({ ...clip, id: makeId('clip'), source_end: safeNumber(clip.source_start) + (cutStart - start) });
        }
        if (end > cutEnd) {
          const rightSourceStart = safeNumber(clip.source_start) + (cutEnd - start);
          nextClips.push({
            ...clip,
            id: makeId('clip'),
            timeline_start: closeGap ? cutStart : cutEnd,
            source_start: rightSourceStart,
          });
        }
      }
      const nextMarkers = (current.markers || [])
        .filter((marker) => marker.time < cutStart || marker.time > cutEnd)
        .map((marker) => closeGap && marker.time >= cutEnd ? { ...marker, time: Math.max(0, marker.time - cutLength) } : marker);
      return { ...current, clips: nextClips, markers: nextMarkers };
    });
    setSelection(null);
    notify?.(closeGap ? 'Bereich entfernt und Lücke geschlossen.' : 'Bereich entfernt. Lücke bleibt bestehen.', 'success');
  }

  function duplicateClip() {
    if (!selectedClip) return;
    commitArrangementHistory();
    const copy = { ...selectedClip, id: makeId('clip'), timeline_start: selectedClip.timeline_start + clipDuration(selectedClip), label: `${selectedClip.label || 'Clip'} Kopie` };
    updateArrangement((current) => ({ ...current, clips: [...current.clips, copy] }));
    setSelectedClipId(copy.id);
  }

  function moveSelectedClipToTrack(trackId) {
    if (!selectedClip) return;
    commitArrangementHistory();
    updateArrangement((current) => ({ ...current, clips: current.clips.map((clip) => clip.id === selectedClip.id ? { ...clip, track_id: trackId } : clip) }));
  }

  function updateSelectedClip(patch) {
    if (!selectedClip) return;
    commitArrangementHistory();
    updateArrangement((current) => ({ ...current, clips: current.clips.map((clip) => clip.id === selectedClip.id ? { ...clip, ...patch } : clip) }));
  }

  function removeSelectedClip() {
    if (!selectedClip) return;
    commitArrangementHistory();
    updateArrangement((current) => ({ ...current, clips: current.clips.filter((clip) => clip.id !== selectedClip.id) }));
    setSelectedClipId('');
  }

  function timelinePointerDown(event, trackId) {
    if (!arrangement) return;
    const time = timeFromPointer(event);
    if (event.target?.closest?.('.daw-arr-clip')) return;
    if (toolMode === 'marker') {
      addMarkerAt(time);
      return;
    }
    if (toolMode === 'range') {
      setSelection({ start: time, end: time });
      showDragTimeTooltip(event, { mode: 'range', title: 'Bereich', rows: [`Start ${secondsToClock(time, true)}`, `Ende ${secondsToClock(time, true)}`, 'Länge 00:00.0'] });
      dragState.current = { kind: 'range', start: time };
      return;
    }
    if (toolMode === 'split') {
      splitClipAt(time);
      return;
    }
    seekTo(time);
    showDragTimeTooltip(event, { mode: 'playhead', title: 'Playhead', rows: [secondsToClock(time, true)] });
    dragState.current = { kind: 'playhead' };
  }

  function clipPointerDown(event, clip) {
    event.stopPropagation();
    event.preventDefault();
    if (!clip || clip.locked) return;
    setSelectedClipId(clip.id);
    const time = timeFromPointer(event);
    const fadeHandle = event.target?.closest?.('.clip-fade-handle');
    if (fadeHandle) {
      const edge = fadeHandle.classList.contains('left') ? 'in' : 'out';
      showDragTimeTooltip(event, {
        mode: 'fade',
        title: edge === 'in' ? 'Fade-in' : 'Fade-out',
        rows: edge === 'in'
          ? [`Fade-in ${secondsToClock(safeNumber(clip.fade_in), true)}`, `endet bei ${secondsToClock(safeNumber(clip.timeline_start) + safeNumber(clip.fade_in), true)}`, `Clip-Länge ${secondsToClock(clipDuration(clip), true)}`]
          : [`Fade-out ${secondsToClock(safeNumber(clip.fade_out), true)}`, `startet bei ${secondsToClock(safeNumber(clip.timeline_start) + clipDuration(clip) - safeNumber(clip.fade_out), true)}`, `Clip-Ende ${secondsToClock(safeNumber(clip.timeline_start) + clipDuration(clip), true)}`],
      });
      dragState.current = {
        kind: 'fade',
        clipId: clip.id,
        edge,
        originalTimelineStart: safeNumber(clip.timeline_start),
        originalDuration: clipDuration(clip),
        originalFadeIn: safeNumber(clip.fade_in),
        originalFadeOut: safeNumber(clip.fade_out),
        originalArrangement: cloneArrangementSnapshot(arrangementRef.current),
      };
      return;
    }
    const resizeHandle = event.target?.closest?.('.clip-resize-handle');
    if (resizeHandle) {
      const edge = resizeHandle.classList.contains('left') ? 'left' : 'right';
      showDragTimeTooltip(event, {
        mode: 'trim',
        title: edge === 'left' ? 'Linke Kante' : 'Rechte Kante',
        rows: edge === 'left'
          ? [`Start ${secondsToClock(safeNumber(clip.timeline_start), true)}`, `Quelle ${secondsToClock(safeNumber(clip.source_start), true)}`, `Länge ${secondsToClock(clipDuration(clip), true)}`]
          : [`Ende ${secondsToClock(safeNumber(clip.timeline_start) + clipDuration(clip), true)}`, `Quelle ${secondsToClock(safeNumber(clip.source_end), true)}`, `Länge ${secondsToClock(clipDuration(clip), true)}`],
      });
      dragState.current = {
        kind: 'resize',
        clipId: clip.id,
        edge,
        startClientX: event.clientX,
        originalTimelineStart: safeNumber(clip.timeline_start),
        originalSourceStart: safeNumber(clip.source_start),
        originalSourceEnd: safeNumber(clip.source_end),
        originalDuration: clipDuration(clip),
        sourceDuration: Math.max(safeNumber(mediaDuration), safeNumber(currentAsset?.duration_seconds), safeNumber(clip.source_end)),
        originalArrangement: cloneArrangementSnapshot(arrangementRef.current),
      };
      return;
    }
    if (toolMode === 'split') {
      splitClipAt(time, clip.id);
      return;
    }
    if (toolMode === 'marker') {
      addMarkerAt(time);
      return;
    }
    if (toolMode === 'range') {
      setSelection({ start: time, end: time });
      showDragTimeTooltip(event, { mode: 'range', title: 'Bereich', rows: [`Start ${secondsToClock(time, true)}`, `Ende ${secondsToClock(time, true)}`, 'Länge 00:00.0'] });
      dragState.current = { kind: 'range', start: time };
      return;
    }
    seekTo(time);
    showDragTimeTooltip(event, {
      mode: 'move',
      title: 'Clip verschieben',
      rows: [`Position ${secondsToClock(safeNumber(clip.timeline_start), true)}`, `Spur ${String(clip.track_id || 'track-1').replace('track-', '')}`],
    });
    dragState.current = {
      kind: 'move',
      clipId: clip.id,
      startClientX: event.clientX,
      originalStart: safeNumber(clip.timeline_start),
      originalTrackId: clip.track_id,
      originalArrangement: cloneArrangementSnapshot(arrangementRef.current),
    };
  }

  function currentArrangementPayload() {
    const snapshot = normalizeArrangement(arrangementRef.current || arrangement, currentAsset, timelineDuration || mediaDuration || currentAsset?.duration_seconds || 1);
    return { ...snapshot, duration_seconds: timelineDuration };
  }

  async function saveArrangement(showSuccess = true) {
    if (!assetId || !arrangementRef.current) return;
    setSaving(true);
    try {
      const payload = currentArrangementPayload();
      const result = await api.daw.saveArrangement(assetId, payload);
      const normalized = normalizeArrangement(result.arrangement, currentAsset, timelineDuration);
      setArrangement(normalized);
      arrangementRef.current = normalized;
      if (showSuccess) notify?.('DAW-Arrangement gespeichert.', 'success');
    } catch (err) {
      notify?.(err.message || 'DAW-Arrangement konnte nicht gespeichert werden.', 'error');
    } finally {
      setSaving(false);
    }
  }

  async function previewArrangement() {
    if (!assetId || !arrangementRef.current) return;
    setPreviewing(true);
    try {
      const payload = currentArrangementPayload();
      const result = await api.daw.previewArrangement(assetId, { arrangement: payload, output_format: outputFormat, version_label: versionLabel || 'Editiert Vorschau' });
      const url = URL.createObjectURL(result.blob);
      setPreviewUrl((current) => { if (current) URL.revokeObjectURL(current); return url; });
      notify?.('Arrangement-Vorschau erstellt.', 'success');
    } catch (err) {
      notify?.(err.message || 'Arrangement-Vorschau fehlgeschlagen.', 'error');
    } finally {
      setPreviewing(false);
    }
  }

  async function renderArrangement() {
    if (!assetId || !arrangementRef.current) return;
    setRendering(true);
    try {
      const payload = currentArrangementPayload();
      const task = await api.daw.renderArrangementTask(assetId, { arrangement: payload, output_format: outputFormat, version_label: versionLabel || 'Editiert', create_notification: true });
      setRenderTask({ ...task, id: task.task_local_id, progress: 0, response_payload: { progress: { percent: 0, phase: 'queued', message: task.message || 'DAW-Render wurde gestartet.' } } });
      notify?.('DAW-Render wurde gestartet und läuft als aktiver Task im Hintergrund.', 'success');
      onReload?.();
    } catch (err) {
      notify?.(err.message || 'Arrangement-Render konnte nicht gestartet werden.', 'error');
    } finally {
      setRendering(false);
    }
  }

  function resetArrangement() {
    if (!currentAsset) return;
    commitArrangementHistory();
    const next = buildDefaultArrangement(currentAsset, mediaDuration || currentAsset.duration_seconds || 1);
    setArrangement(next);
    setSelectedClipId(next.clips[0]?.id || '');
    setSelection(null);
  }

  // Clip-Verschieben und Kürzen wird bewusst über Pointer-Events umgesetzt.
  // Das vermeidet Konflikte zwischen Drittanbieter-Drag-Handlern, React-Re-Renders und der Waveform-Komponente.


  useHotkeys('space,k,p', (event) => {
    event.preventDefault();
    togglePlayback();
  }, { enableOnFormTags: false, preventDefault: true }, [togglePlayback]);

  useHotkeys('s', (event) => {
    event.preventDefault();
    splitClipAt(currentTime);
  }, { enableOnFormTags: false, preventDefault: true }, [currentTime, selectedClipId, arrangement, splitClipAt]);

  useHotkeys('m', (event) => {
    event.preventDefault();
    addMarkerAt(currentTime);
  }, { enableOnFormTags: false, preventDefault: true }, [currentTime, addMarkerAt]);

  useHotkeys('delete,backspace', (event) => {
    event.preventDefault();
    if (selectedClipIdRef.current) removeSelectedClip();
  }, { enableOnFormTags: false, preventDefault: true }, [removeSelectedClip]);

  useHotkeys('esc', (event) => {
    event.preventDefault();
    setSelection(null);
    setSelectedClipId('');
  }, { enableOnFormTags: false, preventDefault: true }, []);

  useHotkeys('left,right', (event) => {
    event.preventDefault();
    const step = event.shiftKey ? 5 : 1;
    seekTo(currentTime + (event.key === 'ArrowLeft' ? -step : step));
  }, { enableOnFormTags: false, preventDefault: true }, [currentTime, seekTo]);

  useHotkeys('ctrl+z,meta+z', (event) => {
    event.preventDefault();
    undoArrangement();
  }, { enableOnFormTags: false, preventDefault: true }, [undoArrangement]);

  useHotkeys('ctrl+y,ctrl+shift+z,meta+shift+z', (event) => {
    event.preventDefault();
    redoArrangement();
  }, { enableOnFormTags: false, preventDefault: true }, [redoArrangement]);

  const warnings = [];
  if (!arrangement?.clips?.length) warnings.push('Keine Clips im Arrangement.');
  if (selection && selection.end - selection.start > 0.05) warnings.push(`Bereich aktiv: ${secondsToClock(selection.start)} – ${secondsToClock(selection.end)}`);
  const toolHelp = TOOL_HELP[toolMode] || TOOL_HELP.select;

  return (
    <section className="page stack daw-page daw-arr-page">
      {!assetId ? (
        <DawEmptyState t={t} lastKnownAsset={lastKnownAsset} onOpenLast={() => lastKnownAsset && selectAsset(lastKnownAsset.id)} onBackToLibrary={onBackToLibrary} />
      ) : <>
        <header className="daw-projectbar panel">
          <div className="daw-projectbar-left">
            <button type="button" className="daw-nav-button" onClick={onBackToLibrary}><ArrowLeft size={16} /> Library</button>
            <img className="daw-project-cover" src={pickCover(currentAsset) || '/static/favicon.ico'} alt="Cover" onError={handleCoverImageError} />
            <div className="daw-project-title">
              <strong>{currentAsset ? pickTitle(currentAsset) : 'Audio wird geladen …'}</strong>
              <small>{formatDuration(timelineDuration)} · {outputFormat.toUpperCase()} · Lokal · Original bleibt unverändert</small>
            </div>
          </div>
          <div className="daw-projectbar-actions">
            <button type="button" onClick={() => currentAsset && onPlay?.([currentAsset], 0)} disabled={!currentAsset}><Headphones size={15} /> Quelle</button>
            {currentAsset && <a className="button" href={api.archive.downloadUrl(currentAsset.id)}><Download size={15} /> Download</a>}
            <label className="daw-format-select"><span>Format</span><select value={outputFormat} onChange={(event) => setOutputFormat(event.target.value)} aria-label="Ausgabeformat">{OUTPUT_FORMATS.map((format) => <option key={format} value={format}>{format.toUpperCase()}</option>)}</select></label>
            <button type="button" onClick={previewArrangement} disabled={previewing || rendering || !arrangement}>{previewing ? <Loader2 className="spin-icon" size={15} /> : <Headphones size={15} />} Vorschau</button>
            <button className="primary daw-save-version" type="button" onClick={renderArrangement} disabled={rendering || renderTaskActive || !arrangement}>{(rendering || renderTaskActive) ? <Loader2 className="spin-icon" size={15} /> : <Save size={15} />} {renderTaskActive ? 'Speichert …' : 'Version speichern'}</button>
          </div>
        </header>

        {renderTask && (
          <div className={`daw-render-task-strip ${renderTaskActive ? 'active' : renderTaskStatus === 'FAILED' ? 'failed' : 'done'}`}>
            <div>
              <strong>{renderTaskActive ? 'Version wird im Hintergrund gespeichert' : renderTaskStatus === 'FAILED' ? 'Render fehlgeschlagen' : 'Version gespeichert'}</strong>
              <span>{renderTaskPhase || (renderTaskActive ? 'Task läuft. Du kannst den Live-Status auch oben bei den aktiven Tasks öffnen.' : renderTaskStatus)}</span>
            </div>
            <div className="daw-render-task-progress" aria-label="DAW Render Fortschritt">
              <span style={{ width: `${Math.max(4, Math.min(100, renderTaskProgress || (renderTaskActive ? 8 : 100)))}%` }} />
            </div>
            <button type="button" onClick={() => onReload?.()}>Status aktualisieren</button>
          </div>
        )}

        {currentAsset && <audio ref={audioRef} src={audioUrl || ''} preload="metadata" className="daw-hidden-audio" onLoadedMetadata={handleDurationDetected} onDurationChange={handleDurationDetected} onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime || 0)} onPlay={() => setIsPlaying(true)} onPause={() => setIsPlaying(false)} onEnded={() => setIsPlaying(false)} />}

        <section className="daw-control-surface panel" aria-label="DAW Steuerung">
          <div className="daw-control-row daw-control-main">
            <div className="daw-control-group daw-history-group" aria-label="Verlauf">
              <span className="daw-group-label">Verlauf</span>
              <button type="button" onClick={undoArrangement} disabled={!undoStack.length} title="Rückgängig (Strg+Z)"><Undo2 size={15} /> Undo</button>
              <button type="button" onClick={redoArrangement} disabled={!redoStack.length} title="Wiederholen (Strg+Y)"><Redo2 size={15} /> Redo</button>
            </div>
            <div className="daw-control-group daw-transport-group" aria-label="Wiedergabe">
              <span className="daw-group-label">Wiedergabe</span>
              <button type="button" onClick={() => seekTo(Math.max(0, currentTime - 10))}><SkipBack size={15} /> 10s</button>
              <button type="button" className="play" onClick={togglePlayback} aria-label={isPlaying ? 'Pause' : 'Abspielen'}>{isPlaying ? <Pause size={20} /> : <Play size={20} />}</button>
              <button type="button" onClick={() => seekTo(Math.min(timelineDuration, currentTime + 10))}>10s <SkipForward size={15} /></button>
              <strong>{secondsToClock(currentTime, true)} / {secondsToClock(timelineDuration)}</strong>
            </div>
            <div className="daw-control-group daw-timing-group" aria-label="Timing und Raster">
              <span className="daw-group-label">Raster</span>
              <label>BPM <input type="number" min="20" max="300" value={arrangement?.bpm || ''} placeholder="frei" onChange={(event) => updateArrangement((current) => ({ ...current, bpm: event.target.value ? Number(event.target.value) : null }))} /></label>
              <button className={arrangement?.snap_enabled ? 'active' : ''} type="button" onClick={() => updateArrangement((current) => ({ ...current, snap_enabled: !current.snap_enabled }))}><Magnet size={15} /> Snap</button>
              <select value={arrangement?.snap_unit || 'beat'} onChange={(event) => updateArrangement((current) => ({ ...current, snap_unit: event.target.value }))} aria-label="Rastereinheit">{SNAP_UNITS.map((unit) => <option key={unit.id} value={unit.id}>{unit.label}</option>)}</select>
            </div>
            <div className="daw-control-group daw-project-group" aria-label="Projekt">
              <span className="daw-group-label">Projekt</span>
              <button type="button" onClick={() => saveArrangement(true)} disabled={saving}>{saving ? <Loader2 className="spin-icon" size={15} /> : <Save size={15} />} Arrangement sichern</button>
              <button type="button" onClick={resetArrangement}><RotateCcw size={15} /> Reset</button>
            </div>
          </div>
          <div className="daw-control-row daw-edit-row">
            <div className="daw-control-group daw-tool-mode-group" aria-label="Werkzeugmodus">
              <span className="daw-group-label">Werkzeug</span>
              {TOOL_MODES.map((mode) => {
                const Icon = mode.icon;
                return <button key={mode.id} className={toolMode === mode.id ? 'active' : ''} type="button" onClick={() => setToolMode(mode.id)}><Icon size={15} /> {mode.label}</button>;
              })}
            </div>
            <div className="daw-control-group daw-clip-action-group" aria-label="Clip-Aktionen">
              <span className="daw-group-label">Clip</span>
              <button type="button" onClick={() => splitClipAt(currentTime)}><SplitSquareHorizontal size={15} /> Am Playhead schneiden</button>
              <button type="button" onClick={cutRange} disabled={!selection}><Trash2 size={15} /> Bereich entfernen</button>
              <label className="inline-check"><input type="checkbox" checked={closeGap} onChange={(event) => setCloseGap(event.target.checked)} /> Lücke schließen</label>
            </div>
            <div className="daw-control-shortcuts">Leertaste Play/Pause · S schneiden · M Marker · Entf Clip löschen</div>
          </div>
        </section>

        {loading && <div className="daw-loading-strip"><Loader2 className="spin-icon" size={15} /> Arrangement wird geladen …</div>}

        <section className="daw-arr-editor panel">
          <div className="daw-arr-sidebar">
            <div className="daw-arr-track-head spacer" />
            {TRACKS.map((track) => (
              <div key={track.id} className="daw-arr-track-head">
                <strong>{track.name}</strong>
                <span>{(arrangement?.clips || []).filter((clip) => clip.track_id === track.id).length} Clips</span>
              </div>
            ))}
          </div>
          <div className="daw-arr-timeline" ref={timelineRef}>
            <div className="daw-arr-ruler">
              {ticks.map((tick) => <span key={tick.label} style={{ left: tick.left }}>{tick.label}</span>)}
            </div>
            <div className="daw-arr-markers" onPointerDown={(event) => timelinePointerDown(event, 'track-1')}>
              {(arrangement?.markers || []).map((marker) => <button key={marker.id} type="button" style={{ left: `${percent(marker.time, timelineDuration)}%` }} onClick={(event) => { event.stopPropagation(); seekTo(marker.time); }}>{marker.label}</button>)}
            </div>
            <span
              className="daw-arr-playhead"
              role="slider"
              aria-label="Playhead"
              aria-valuemin={0}
              aria-valuemax={Math.round(timelineDuration)}
              aria-valuenow={Math.round(currentTime)}
              style={{ left: `${percent(currentTime, timelineDuration)}%` }}
              onPointerDown={(event) => {
                event.stopPropagation();
                event.preventDefault();
                const next = timeFromPointer(event);
                seekTo(next);
                showDragTimeTooltip(event, { mode: 'playhead', title: 'Playhead', rows: [secondsToClock(next, true)] });
                dragState.current = { kind: 'playhead' };
              }}
            />
            {selection && selection.end - selection.start > 0.05 && <span className="daw-arr-selection" style={{ left: `${percent(selection.start, timelineDuration)}%`, width: `${Math.max(0.4, percent(selection.end, timelineDuration) - percent(selection.start, timelineDuration))}%` }}><b>{secondsToClock(selection.start)} – {secondsToClock(selection.end)}</b></span>}
            {TRACKS.map((track) => (
              <div key={track.id} className="daw-arr-track-row" data-track-id={track.id} onPointerDown={(event) => timelinePointerDown(event, track.id)}>
                {(arrangement?.clips || []).filter((clip) => clip.track_id === track.id).map((clip) => {
                  const left = percent(clip.timeline_start, timelineDuration);
                  const width = Math.max(0.5, percent(clip.timeline_start + clipDuration(clip), timelineDuration) - left);
                  const duration = clipDuration(clip);
                  const fadeInPercent = duration > 0 ? clamp((safeNumber(clip.fade_in) / duration) * 100, 0, 50) : 0;
                  const fadeOutPercent = duration > 0 ? clamp((safeNumber(clip.fade_out) / duration) * 100, 0, 50) : 0;
                  const fadeInHandleLeft = fadeHandlePercent(clip.fade_in, duration, 'left');
                  const fadeOutHandleLeft = fadeHandlePercent(clip.fade_out, duration, 'right');
                  return (
                    <div
                      key={clip.id}
                      role="button"
                      tabIndex={0}
                      data-clip-id={clip.id}
                      aria-label={`Clip ${clip.label || ''}`.trim()}
                      className={`daw-arr-clip ${clip.id === selectedClipId ? 'selected' : ''}`}
                      style={{ left: `${left}%`, width: `${width}%` }}
                      onPointerDown={(event) => clipPointerDown(event, clip)}
                      onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedClipId(clip.id); } }}
                    >
                      <span className="clip-waveform" aria-hidden="true">
                        {currentAsset && <Waveform
                          asset={currentAsset}
                          audioRef={audioRef}
                          compact={false}
                          durationSeconds={duration}
                          sourceStartSeconds={safeNumber(clip.source_start)}
                          sourceEndSeconds={safeNumber(clip.source_end)}
                          interactive={false}
                          showProgress={false}
                        />}
                      </span>
                      {fadeInPercent > 0 && <span className="clip-fade-overlay in" aria-hidden="true" style={{ width: `${fadeInPercent}%` }} />}
                      {fadeOutPercent > 0 && <span className="clip-fade-overlay out" aria-hidden="true" style={{ width: `${fadeOutPercent}%` }} />}
                      <span className="clip-resize-handle left" aria-hidden="true" />
                      <span className="clip-resize-handle right" aria-hidden="true" />
                      <span className="clip-fade-handle left" role="slider" aria-label="Fade-in ziehen" aria-valuemin={0} aria-valuemax={Math.round(duration)} aria-valuenow={Math.round(safeNumber(clip.fade_in))} style={{ left: `${fadeInHandleLeft}%` }} />
                      <span className="clip-fade-handle right" role="slider" aria-label="Fade-out ziehen" aria-valuemin={0} aria-valuemax={Math.round(duration)} aria-valuenow={Math.round(safeNumber(clip.fade_out))} style={{ left: `${fadeOutHandleLeft}%` }} />
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        </section>

        <section className="daw-arr-bottom panel daw-arr-bottom-compact">
          <div className="daw-arr-quickbar">
            <div className="daw-arr-tool-status">
              <strong>{toolHelp.title}</strong>
              <span>{toolHelp.text}</span>
            </div>
            <div className="button-row wrap daw-arr-primary-actions">
              <button type="button" onClick={() => splitClipAt(currentTime)}><Scissors size={15} /> Am Playhead schneiden</button>
              <button type="button" onClick={() => setSelection({ start: currentTime, end: Math.min(timelineDuration, currentTime + 30) })}><Flag size={15} /> 30s-Bereich</button>
              <button type="button" onClick={cutRange} disabled={!selection}><Trash2 size={15} /> Bereich entfernen</button>
              <button type="button" onClick={() => addMarkerAt(currentTime)}><Flag size={15} /> Marker</button>
              <button type="button" onClick={duplicateClip} disabled={!selectedClip}><Copy size={15} /> Duplizieren</button>
            </div>
            {warnings.length > 0 && (
              <div className="daw-arr-warning-row">
                {warnings.map((warning) => <span key={warning}><AlertTriangle size={14} /> {warning}</span>)}
              </div>
            )}
          </div>

          <details className="daw-arr-details">
            <summary>Ausgewählter Clip / Expertenwerte</summary>
            {selectedClip ? <>
              <div className="form-grid compact-grid">
                <label>Label<input value={selectedClip.label || ''} onChange={(event) => updateSelectedClip({ label: event.target.value })} /></label>
                <label>Position<input type="number" step="0.01" value={Number(selectedClip.timeline_start).toFixed(2)} onChange={(event) => updateSelectedClip({ timeline_start: snapTime(Number(event.target.value)) })} /></label>
                <label>Quelle Start<input type="number" step="0.01" value={Number(selectedClip.source_start).toFixed(2)} onChange={(event) => updateSelectedClip({ source_start: Math.max(0, Number(event.target.value)) })} /></label>
                <label>Quelle Ende<input type="number" step="0.01" value={Number(selectedClip.source_end).toFixed(2)} onChange={(event) => updateSelectedClip({ source_end: Math.max(selectedClip.source_start + 0.1, Number(event.target.value)) })} /></label>
                <label>Fade-in<input type="number" step="0.1" value={selectedClip.fade_in || 0} onChange={(event) => updateSelectedClip({ fade_in: Number(event.target.value) })} /></label>
                <label>Fade-out<input type="number" step="0.1" value={selectedClip.fade_out || 0} onChange={(event) => updateSelectedClip({ fade_out: Number(event.target.value) })} /></label>
                <label>Gain dB<input type="number" step="0.5" value={selectedClip.gain_db || 0} onChange={(event) => updateSelectedClip({ gain_db: Number(event.target.value) })} /></label>
              </div>
              <div className="button-row wrap">
                {TRACKS.map((track) => <button key={track.id} type="button" className={selectedClip.track_id === track.id ? 'active' : ''} onClick={() => moveSelectedClipToTrack(track.id)}>{track.name}</button>)}
                <button type="button" className="danger ghost" onClick={removeSelectedClip}><Trash2 size={15} /> Clip löschen</button>
              </div>
            </> : <p className="muted">Klicke einen Clip in der Timeline an.</p>}
          </details>

          <details className="daw-arr-details preview" open={Boolean(previewUrl)}>
            <summary>Vorschau / Version</summary>
            <div className="daw-arr-version-grid">
              <label>Versionsname<input value={versionLabel} onChange={(event) => setVersionLabel(event.target.value)} /></label>
              <label className="daw-arr-volume"><Volume2 size={15} /><input type="range" min="0" max="1" step="0.01" value={volume} onChange={(event) => { const next = Number(event.target.value); setVolume(next); if (audioRef.current) audioRef.current.volume = next; }} /></label>
            </div>
            {previewUrl ? <audio controls src={previewUrl} preload="metadata" /> : <p className="muted">Vorschau rendert das komplette Arrangement inklusive Schnitte, Lücken, Tracks und Fades.</p>}
          </details>
        </section>
        {dragTooltip && (
          <div
            className={`daw-time-tooltip ${dragTooltip.mode || ''}`}
            style={{ left: `${dragTooltip.x}px`, top: `${dragTooltip.y}px` }}
            role="status"
            aria-live="polite"
          >
            {dragTooltip.title && <strong>{dragTooltip.title}</strong>}
            {dragTooltip.rows.map((row, index) => <span key={`${row}-${index}`}>{row}</span>)}
          </div>
        )}
      </>}
    </section>
  );
}
