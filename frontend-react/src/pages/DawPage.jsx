// Mini-DAW – überarbeitete, modulare Fassung.
//
// Aufbau (Trennung der Verantwortlichkeiten):
//   src/daw/timeUtils.js     – pure Zeit-/Arrangement-Helfer (Verbatim-Port)
//   src/daw/musicalTime.js   – Takt-/Beat-Mathematik, Beatgrid-Snapping
//   src/daw/sections.js      – Songstruktur (Intro/Verse/Hook ...)
//   src/daw/arrangement.js   – Arrangement-Modell + Kommandoplaner (pur)
//   src/daw/aiParser.js      – lokaler DAW-KI-Parser (deterministisch)
//   src/daw/audioEngine.js   – Web-Audio-Echtzeit-Wiedergabe (neu)
//   src/daw/store.js         – zustand-Store (History, Auswahl, Transport)
//   src/daw/components/*     – UI-Bausteine
//
// Backend-Anbindung: ausschließlich über die bestehenden /api/daw-Endpunkte
// (Arrangement in audio_assets.metadata_json.daw_arrangement, Beatgrid,
// Render-Tasks) plus das neue KI-Endpoint /arrangement/ai-command.

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useHotkeys } from 'react-hotkeys-hook';
import { ArrowLeft, Download, FileAudio, Loader2, Plus, RotateCcw, Save, Trash2 } from 'lucide-react';
import { api } from '../api/client.js';
import { pickTitle } from '../utils.js';
import { useI18n } from '../i18n/I18nContext.jsx';
import {
  clamp, safeNumber, clipDuration, secondsToClock, makeId, sortMarkers,
  arrangementLength, parseMaybeJson,
} from '../daw/timeUtils.js';
import { snapToDawBeatgrid, validDawBeatgrid, dawBeatgridBoundaries } from '../daw/musicalTime.js';
import { buildResolvedSections } from '../daw/sections.js';
import { normalizeArrangement, MAX_TRACKS } from '../daw/arrangement.js';
import { dawAiSectionKindFromText, parseDawAiCommand } from '../daw/aiParser.js';
import { DawAudioEngine } from '../daw/audioEngine.js';
import { useDawStore } from '../daw/store.js';
import { TransportBar } from '../daw/components/TransportBar.jsx';
import { TimelineRuler } from '../daw/components/TimelineRuler.jsx';
import { SectionRail } from '../daw/components/SectionRail.jsx';
import { TrackHeaders, TrackLanes } from '../daw/components/TrackLane.jsx';
import { PlayheadLayer } from '../daw/components/PlayheadLayer.jsx';
import { AiCommandPanel, CommandPreviewModal, ClipInspector, DawEmptyState } from '../daw/components/DawPanels.jsx';
import '../daw/daw.css';

const ZOOM_PX_PER_SECOND = [4, 6, 10, 16, 26, 42, 70, 110, 160];
const OUTPUT_FORMATS = ['mp3', 'wav', 'm4a'];
const JUMP_MARKER_LABELS = ['1', '2', '3', '4', '5', '6', '7', '8', '9'];
const AI_EXAMPLES = [
  'Setze die erste Hook doppelt',
  'Schneide den Clip exakt nach 4 Takten',
  'Kürze das Intro auf 8 Takte',
  'Verschiebe diesen Clip einen Takt nach rechts',
  'Erstelle aus dem markierten Bereich einen Loop',
  'Schließe alle Lücken',
];

export function DawPage({ assets = [], selectedAssetId = null, onSelectedHandled, onAssetChange, onBackToLibrary, onPlay, notify, onReload }) {
  const { t } = useI18n();
  const playable = useMemo(
    () => (assets || []).filter((asset) => asset?.id && (asset.public_url || asset.local_path || asset.source_url)),
    [assets],
  );

  // ---- Store (Selector-basiert: currentTime wird hier bewusst NICHT
  // abonniert – Zeit-Ticks rendern nur TimeReadout + PlayheadLayer) ---------
  const asset = useDawStore((s) => s.asset);
  const project = useDawStore((s) => s.project);
  const arrangement = useDawStore((s) => s.arrangement);
  const beatgrid = useDawStore((s) => s.beatgrid);
  const sections = useDawStore((s) => s.sections);
  const sourceDuration = useDawStore((s) => s.sourceDuration);
  const selectedClipId = useDawStore((s) => s.selectedClipId);
  const selectedSectionId = useDawStore((s) => s.selectedSectionId);
  const selection = useDawStore((s) => s.selection);
  const toolMode = useDawStore((s) => s.toolMode);
  const closeGap = useDawStore((s) => s.closeGap);
  const timelineZoom = useDawStore((s) => s.timelineZoom);
  const isPlaying = useDawStore((s) => s.isPlaying);
  const volume = useDawStore((s) => s.volume);
  const commandPreview = useDawStore((s) => s.commandPreview);
  const aiBusy = useDawStore((s) => s.aiBusy);
  const dirty = useDawStore((s) => s.dirty);
  const canUndo = useDawStore((s) => s.undoStack.length > 0);
  const canRedo = useDawStore((s) => s.redoStack.length > 0);
  // zustand-Actions sind stabil -> einmalig destrukturieren
  const store = useDawStore.getState();

  const [assetId, setAssetId] = useState(() => String(selectedAssetId || '').trim());
  const [lastKnownAssetId, setLastKnownAssetId] = useState(() => localStorage.getItem('react-daw-asset-id') || '');
  const [loading, setLoading] = useState(false);
  const [beatgridLoading, setBeatgridLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [renderTask, setRenderTask] = useState(null);
  const [arrangementSessions, setArrangementSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [outputFormat, setOutputFormat] = useState('mp3');
  const [versionLabel, setVersionLabel] = useState('DAW Arrangement');
  const [snapGuide, setSnapGuide] = useState(null);
  const [aiPanelOpen, setAiPanelOpen] = useState(false);
  const [aiCommandText, setAiCommandText] = useState('');
  const [aiCommandStatus, setAiCommandStatus] = useState('');
  const [aiHistory, setAiHistory] = useState([]);
  const [dawPromptHooks, setDawPromptHooks] = useState([]);
  const [useServerAi, setUseServerAi] = useState(true);
  const [clipAiState, setClipAiState] = useState({ clipId: '', prompt: '' });
  const [followPlayhead, setFollowPlayhead] = useState(true);
  const [hiResPeaks, setHiResPeaks] = useState({});

  const timelineScrollRef = useRef(null);
  const timelineContentRef = useRef(null);
  const engineRef = useRef(null);
  const arrangementRef = useRef(null);
  const dragStateRef = useRef(null);
  const snapGuideTimerRef = useRef(0);
  const zoomAnchorRef = useRef(null);
  const loadTokenRef = useRef(0);

  useEffect(() => { arrangementRef.current = arrangement; }, [arrangement]);
  useEffect(() => {
    document.body.classList.add('daw-page-active');
    return () => document.body.classList.remove('daw-page-active');
  }, []);
  useEffect(() => {
    let cancelled = false;
    api.daw.promptHooks()
      .then((items) => {
        if (!cancelled) setDawPromptHooks(Array.isArray(items) ? items : []);
      })
      .catch(() => {
        if (!cancelled) setDawPromptHooks([]);
      });
    return () => { cancelled = true; };
  }, []);

  // ---- Abgeleitete Werte -----------------------------------------------------
  const timelineDuration = Math.max(arrangementLength(arrangement, sourceDuration || 1), sourceDuration, 1);
  const activeBeatgrid = validDawBeatgrid(beatgrid) ? beatgrid : null;
  const pxPerSecond = ZOOM_PX_PER_SECOND[clamp(timelineZoom, 0, ZOOM_PX_PER_SECOND.length - 1)];
  const timelineWidthPx = Math.max(640, Math.ceil(timelineDuration * pxPerSecond));
  const selectedClip = (arrangement?.clips || []).find((clip) => clip.id === selectedClipId) || null;
  const selectedSection = sections.find((section) => section.id === selectedSectionId) || null;

  const waveformPeaksById = useMemo(() => {
    const map = {};
    const register = (item) => {
      if (!item?.id) return;
      const waveform = parseMaybeJson(item.waveform_json) || item.waveform_json;
      if (waveform?.peaks?.length) map[String(item.id)] = waveform.peaks;
    };
    register(asset);
    (project?.versions || []).forEach(register);
    playable.forEach(register);
    // Hochauflösende Peaks aus dem AudioBuffer (sobald geladen) haben Vorrang.
    return { ...map, ...hiResPeaks };
  }, [asset, project, playable, hiResPeaks]);

  const beatgridStatusLabel = activeBeatgrid
    ? `Bar-Map: ${activeBeatgrid.bars?.length || 0} Takte${activeBeatgrid.bpm ? ` · ${Math.round(Number(activeBeatgrid.bpm) * 10) / 10} BPM` : ''}`
    : beatgridLoading
      ? 'Bar-Map wird analysiert …'
      : beatgrid?.status === 'missing_dependency'
        ? 'Bar-Map: Analyse-Abhängigkeit fehlt (BPM-Raster aktiv)'
        : '';

  // ---- Snap ------------------------------------------------------------------
  const snapTime = useCallback((value) => {
    const raw = clamp(safeNumber(value), 0, timelineDuration);
    if (!arrangement?.snap_enabled) return raw;
    const gridSnap = snapToDawBeatgrid(raw, activeBeatgrid, arrangement.snap_unit, timelineDuration);
    if (gridSnap !== null && Number.isFinite(gridSnap)) return clamp(gridSnap, 0, timelineDuration);
    const bpm = safeNumber(arrangement?.bpm);
    if (bpm < 20) return raw;
    const beat = 60 / bpm;
    const unit = arrangement.snap_unit === 'bar' ? beat * 4 : arrangement.snap_unit === 'half' ? beat / 2 : arrangement.snap_unit === 'quarter' ? beat / 4 : beat;
    return clamp(Math.round(raw / unit) * unit, 0, timelineDuration);
  }, [activeBeatgrid, arrangement?.bpm, arrangement?.snap_enabled, arrangement?.snap_unit, timelineDuration]);

  const clipEdgeSnap = useCallback((value, excludeClipId, trackId) => {
    const threshold = clamp(14 / pxPerSecond, 0.08, 0.65);
    let best = null;
    (arrangementRef.current?.clips || []).forEach((clip) => {
      if (clip.id === excludeClipId) return;
      if (trackId && clip.track_id !== trackId) return;
      const start = safeNumber(clip.timeline_start);
      const end = start + clipDuration(clip);
      [start, end].forEach((edge) => {
        const distance = Math.abs(edge - value);
        if (distance <= threshold && (!best || distance < best.distance)) best = { time: edge, distance };
      });
    });
    return best ? best.time : null;
  }, [pxPerSecond]);

  const showSnapGuide = useCallback((time, label = 'Snap') => {
    setSnapGuide({ time: clamp(safeNumber(time), 0, timelineDuration), label });
    window.clearTimeout(snapGuideTimerRef.current);
    snapGuideTimerRef.current = window.setTimeout(() => setSnapGuide(null), 900);
  }, [timelineDuration]);

  // ---- Audio-Engine ------------------------------------------------------------
  if (!engineRef.current) {
    engineRef.current = new DawAudioEngine({
      resolveClipUrl: (sourceAudioId) => api.archive.streamUrl(sourceAudioId),
    });
  }
  useEffect(() => {
    const engine = engineRef.current;
    engine.onTick = (time) => useDawStore.getState().setCurrentTime(time);
    engine.onEnded = () => useDawStore.getState().setIsPlaying(false);
    return () => { engine.stop({ silent: true }); };
  }, []);
  useEffect(() => () => engineRef.current?.dispose(), []);
  useEffect(() => { engineRef.current?.setVolume(volume); }, [volume]);

  // Hochauflösende Waveforms: sobald die Buffers (fürs Playback ohnehin nötig)
  // geladen sind, Peaks je Quelle berechnen und die 180-Punkte-Peaks ersetzen.
  const sourceIdsKey = (arrangement?.clips || []).map((clip) => clip.source_audio_id).filter(Boolean).sort().join(',');
  useEffect(() => {
    if (!arrangement || !sourceIdsKey) return undefined;
    let cancelled = false;
    const engine = engineRef.current;
    engine.prepareArrangement(arrangement).then(() => {
      if (cancelled) return;
      const next = {};
      sourceIdsKey.split(',').forEach((id) => {
        const peaks = engine.peaksFor(id, 1600);
        if (peaks) next[String(id)] = peaks;
      });
      if (Object.keys(next).length) setHiResPeaks((current) => ({ ...current, ...next }));
    }).catch(() => null);
    return () => { cancelled = true; };
  }, [sourceIdsKey, asset?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Ctrl+Mausrad: Zoom auf Cursor-Position (nicht-passiver Listener nötig).
  useEffect(() => {
    const scroller = timelineScrollRef.current;
    if (!scroller) return undefined;
    const onWheel = (event) => {
      if (!event.ctrlKey) return;
      event.preventDefault();
      const state = useDawStore.getState();
      const zoom = state.timelineZoom;
      const nextZoom = clamp(zoom + (event.deltaY < 0 ? 1 : -1), 0, ZOOM_PX_PER_SECOND.length - 1);
      if (nextZoom === zoom) return;
      const rect = scroller.getBoundingClientRect();
      const offsetX = event.clientX - rect.left;
      zoomAnchorRef.current = {
        time: (scroller.scrollLeft + offsetX) / ZOOM_PX_PER_SECOND[zoom],
        offsetX,
      };
      state.setTimelineZoom(nextZoom);
    };
    scroller.addEventListener('wheel', onWheel, { passive: false });
    return () => scroller.removeEventListener('wheel', onWheel);
  }, [asset?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Nach Zoomwechsel: Zeitpunkt unter dem Cursor stabil halten.
  useEffect(() => {
    const anchorState = zoomAnchorRef.current;
    const scroller = timelineScrollRef.current;
    if (!anchorState || !scroller) return;
    zoomAnchorRef.current = null;
    scroller.scrollLeft = Math.max(0, anchorState.time * ZOOM_PX_PER_SECOND[clamp(timelineZoom, 0, ZOOM_PX_PER_SECOND.length - 1)] - anchorState.offsetX);
  }, [timelineZoom]);
  useEffect(() => {
    // Laufende Wiedergabe folgt Arrangement-Änderungen (Undo, Drag, KI-Kommando).
    if (isPlaying && arrangement) engineRef.current?.refresh(arrangement).catch(() => null);
  }, [arrangement]); // eslint-disable-line react-hooks/exhaustive-deps

  const playPause = useCallback(async () => {
    const engine = engineRef.current;
    const state = useDawStore.getState();
    if (!state.arrangement) return;
    if (state.isPlaying) {
      engine.pause();
      state.setIsPlaying(false);
      return;
    }
    try {
      await engine.play(state.arrangement, state.currentTime);
      state.setIsPlaying(true);
    } catch (err) {
      notify?.(err.message || 'Wiedergabe konnte nicht gestartet werden.', 'error');
    }
  }, [notify]);

  const stopPlayback = useCallback(() => {
    engineRef.current?.stop();
    useDawStore.getState().setIsPlaying(false);
  }, []);

  const seekTo = useCallback((time) => {
    const state = useDawStore.getState();
    const target = clamp(safeNumber(time), 0, timelineDuration);
    state.setCurrentTime(target);
    engineRef.current?.seek(state.arrangement, target).catch(() => null);
  }, [timelineDuration]);

  // ---- Projekt laden -------------------------------------------------------------
  const selectAsset = useCallback(async (nextAssetId, options = {}) => {
    const id = String(nextAssetId || '').trim();
    const sessionId = options.sessionId || null;
    const token = loadTokenRef.current + 1;
    loadTokenRef.current = token;
    setAssetId(id);
    if (!id) return;
    setLoading(true);
    stopPlayback();
    setHiResPeaks({});
    setArrangementSessions([]);
    setActiveSessionId(sessionId);
    setAiHistory([]);
    setAiCommandStatus('');
    useDawStore.getState().loadProject({
      asset: null,
      project: null,
      arrangement: null,
      sections: [],
      sourceDuration: 0,
    });
    try {
      const [arrangementResult, projectResult, sessionsResult] = await Promise.all([
        api.daw.getArrangement(id, sessionId),
        api.daw.project(id).catch(() => null),
        api.daw.arrangementSessions(id).catch(() => ({ sessions: [] })),
      ]);
      if (loadTokenRef.current !== token) return;
      const loadedAsset = arrangementResult?.asset || playable.find((item) => String(item.id) === id) || null;
      const duration = Math.max(1, safeNumber(loadedAsset?.duration_seconds, 1));
      const normalized = normalizeArrangement(arrangementResult?.arrangement, loadedAsset, duration);
      const resolvedSections = buildResolvedSections(
        { project: projectResult, asset: loadedAsset, arrangement: normalized, beatgrid: null },
        Math.max(duration, arrangementLength(normalized, duration)),
      );
      useDawStore.getState().loadProject({
        asset: loadedAsset,
        project: projectResult,
        arrangement: normalized,
        sections: resolvedSections,
        sourceDuration: duration,
      });
      useDawStore.getState().setSelectedSectionId(resolvedSections.find((section) => section.kind === 'chorus')?.id || resolvedSections[0]?.id || '');
      const sessions = Array.isArray(sessionsResult?.sessions) ? sessionsResult.sessions : [];
      const activeSession = arrangementResult?.session || sessions[0] || null;
      setArrangementSessions(activeSession && !sessions.some((item) => String(item.id) === String(activeSession.id)) ? [activeSession, ...sessions] : sessions);
      setActiveSessionId(activeSession?.id || null);
      localStorage.setItem('react-daw-asset-id', id);
      setLastKnownAssetId(id);
      onAssetChange?.(id);
      onSelectedHandled?.();
      setVersionLabel((activeSession?.title || `DAW ${pickTitle(loadedAsset) || 'Arrangement'}`).slice(0, 80));
      // Beatgrid asynchron laden – blockiert das Öffnen nicht.
      setBeatgridLoading(true);
      api.daw.getBeatgrid(id)
        .then((result) => {
          if (loadTokenRef.current !== token) return;
          const grid = result?.beatgrid || result;
          useDawStore.getState().setProjectState({ beatgrid: grid || null });
          const freshSections = buildResolvedSections(
            { project: projectResult, asset: loadedAsset, arrangement: useDawStore.getState().arrangement, beatgrid: validDawBeatgrid(grid) ? grid : null },
            Math.max(duration, arrangementLength(useDawStore.getState().arrangement, duration)),
          );
          useDawStore.getState().setProjectState({ sections: freshSections });
        })
        .catch(() => {
          if (loadTokenRef.current === token) useDawStore.getState().setProjectState({ beatgrid: { status: 'failed' } });
        })
        .finally(() => {
          if (loadTokenRef.current === token) setBeatgridLoading(false);
        });
    } catch (err) {
      if (loadTokenRef.current === token) notify?.(err.message || 'DAW-Projekt konnte nicht geladen werden.', 'error');
    } finally {
      if (loadTokenRef.current === token) setLoading(false);
    }
  }, [notify, onAssetChange, onSelectedHandled, playable, stopPlayback]);

  useEffect(() => {
    const wanted = String(selectedAssetId || '').trim();
    if (wanted && (wanted !== assetId || String(asset?.id || '') !== wanted)) selectAsset(wanted);
  }, [selectedAssetId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const stored = clamp(safeNumber(localStorage.getItem('react-daw-timeline-zoom'), 1), 0, ZOOM_PX_PER_SECOND.length - 1);
    useDawStore.getState().setTimelineZoom(stored);
  }, []);
  useEffect(() => { localStorage.setItem('react-daw-timeline-zoom', String(timelineZoom)); }, [timelineZoom]);

  // ---- Sektionen bei Arrangement-Änderungen aktualisieren --------------------------
  useEffect(() => {
    if (!asset || !arrangement) return;
    const fresh = buildResolvedSections({ project, asset, arrangement, beatgrid: activeBeatgrid }, Math.max(sourceDuration, timelineDuration));
    useDawStore.getState().setProjectState({ sections: fresh });
  }, [asset?.id, arrangement, activeBeatgrid, project, sourceDuration, timelineDuration]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- Pointer-Mathematik ------------------------------------------------------------
  const timeFromPointer = useCallback((event) => {
    const content = timelineContentRef.current;
    if (!content) return 0;
    const rect = content.getBoundingClientRect();
    const x = clamp(event.clientX - rect.left, 0, rect.width);
    return clamp((x / Math.max(rect.width, 1)) * timelineDuration, 0, timelineDuration);
  }, [timelineDuration]);

  const trackIdFromClientY = useCallback((clientY, fallback) => {
    const lanes = timelineContentRef.current?.querySelectorAll('[data-track-id]') || [];
    for (const lane of lanes) {
      const rect = lane.getBoundingClientRect();
      if (clientY >= rect.top && clientY <= rect.bottom) return lane.dataset.trackId;
    }
    return fallback;
  }, []);

  // ---- Drag-Interaktionen (Move / Trim / Fade / Range) ------------------------------
  const beginPointerDrag = useCallback((event, state) => {
    event.preventDefault();
    event.stopPropagation();
    dragStateRef.current = { ...state, moved: false, startX: event.clientX, startY: event.clientY };
    const handleMove = (moveEvent) => {
      const drag = dragStateRef.current;
      if (!drag) return;
      if (!drag.moved && Math.hypot(moveEvent.clientX - drag.startX, moveEvent.clientY - drag.startY) < 3) return;
      drag.moved = true;
      drag.onMove(moveEvent, drag);
    };
    const handleUp = (upEvent) => {
      window.removeEventListener('pointermove', handleMove);
      window.removeEventListener('pointerup', handleUp);
      const drag = dragStateRef.current;
      dragStateRef.current = null;
      if (drag) drag.onEnd?.(upEvent, drag);
    };
    window.addEventListener('pointermove', handleMove);
    window.addEventListener('pointerup', handleUp);
  }, []);

  const patchClipLive = useCallback((clipId, patch) => {
    // Live-Update ohne History (History wird beim Drag-Start committet).
    const state = useDawStore.getState();
    if (!state.arrangement) return;
    const next = {
      ...state.arrangement,
      clips: state.arrangement.clips.map((clip) => (clip.id === clipId ? { ...clip, ...patch } : clip)),
    };
    next.duration_seconds = arrangementLength(next, state.sourceDuration || 1);
    state.setArrangementDirect(next);
  }, []);

  const onClipPointerDown = useCallback((event, clip) => {
    if (event.button !== 0 || clip.locked || toolMode === 'range' || toolMode === 'marker') {
      useDawStore.getState().setSelectedClipId(clip.id);
      return;
    }
    useDawStore.getState().setSelectedClipId(clip.id);
    const startTime = timeFromPointer(event);
    const grabOffset = startTime - safeNumber(clip.timeline_start);
    useDawStore.getState().commitHistory();
    beginPointerDrag(event, {
      kind: 'move',
      clipId: clip.id,
      grabOffset,
      duration: clipDuration(clip),
      onMove: (moveEvent, drag) => {
        const raw = timeFromPointer(moveEvent) - drag.grabOffset;
        const trackId = trackIdFromClientY(moveEvent.clientY, clip.track_id);
        const startSnap = clipEdgeSnap(raw, drag.clipId, trackId);
        const endSnap = clipEdgeSnap(raw + drag.duration, drag.clipId, trackId);
        let nextStart;
        if (Number.isFinite(startSnap)) nextStart = startSnap;
        else if (Number.isFinite(endSnap)) nextStart = endSnap - drag.duration;
        else nextStart = snapTime(raw);
        nextStart = clamp(nextStart, 0, Math.max(0, timelineDuration * 2));
        patchClipLive(drag.clipId, { timeline_start: nextStart, track_id: trackId });
        showSnapGuide(nextStart, secondsToClock(nextStart, true));
      },
      onEnd: (_upEvent, drag) => {
        if (!drag.moved) return;
        // Endzustand normalisieren + Engine aktualisieren.
        const state = useDawStore.getState();
        state.setArrangementDirect(normalizeArrangement(state.arrangement, state.asset, Math.max(state.sourceDuration, arrangementLength(state.arrangement, 1))));
      },
    });
  }, [beginPointerDrag, clipEdgeSnap, patchClipLive, showSnapGuide, snapTime, timeFromPointer, timelineDuration, toolMode, trackIdFromClientY]);

  const onTrimPointerDown = useCallback((event, clip, edge) => {
    if (event.button !== 0 || clip.locked) return;
    event.stopPropagation();
    useDawStore.getState().setSelectedClipId(clip.id);
    useDawStore.getState().commitHistory();
    const base = { ...clip };
    beginPointerDrag(event, {
      kind: 'trim',
      onMove: (moveEvent) => {
        const pointerTime = snapTime(timeFromPointer(moveEvent));
        const baseStart = safeNumber(base.timeline_start);
        const baseLength = clipDuration(base);
        if (edge === 'start') {
          const delta = clamp(pointerTime - baseStart, -safeNumber(base.source_start), baseLength - 0.25);
          patchClipLive(clip.id, {
            timeline_start: baseStart + delta,
            source_start: safeNumber(base.source_start) + delta,
          });
          showSnapGuide(baseStart + delta, 'Anfang trimmen');
        } else {
          const maxExtend = Math.max(0, (sourceDuration || safeNumber(base.source_end)) - safeNumber(base.source_end));
          const delta = clamp(pointerTime - (baseStart + baseLength), 0.25 - baseLength, maxExtend);
          patchClipLive(clip.id, { source_end: safeNumber(base.source_end) + delta });
          showSnapGuide(baseStart + baseLength + delta, 'Ende trimmen');
        }
      },
    });
  }, [beginPointerDrag, patchClipLive, showSnapGuide, snapTime, sourceDuration, timeFromPointer]);

  const onFadePointerDown = useCallback((event, clip, side) => {
    if (event.button !== 0 || clip.locked) return;
    event.stopPropagation();
    useDawStore.getState().setSelectedClipId(clip.id);
    useDawStore.getState().commitHistory();
    beginPointerDrag(event, {
      kind: 'fade',
      onMove: (moveEvent) => {
        const pointerTime = timeFromPointer(moveEvent);
        const start = safeNumber(clip.timeline_start);
        const length = clipDuration(clip);
        if (side === 'in') {
          const fade = clamp(pointerTime - start, 0, length / 2);
          patchClipLive(clip.id, { fade_in: Math.round(fade * 100) / 100 });
        } else {
          const fade = clamp(start + length - pointerTime, 0, length / 2);
          patchClipLive(clip.id, { fade_out: Math.round(fade * 100) / 100 });
        }
      },
    });
  }, [beginPointerDrag, patchClipLive, timeFromPointer]);

  const onSplitClick = useCallback((event, clip) => {
    const time = snapTime(timeFromPointer(event));
    useDawStore.getState().previewCommand({ type: 'clip_split', time, clipId: clip.id });
  }, [snapTime, timeFromPointer]);

  const onRulerPointerDown = useCallback((event) => {
    if (event.button !== 0) return;
    const store2 = useDawStore.getState();
    const time = timeFromPointer(event);
    if (toolMode === 'marker' || event.shiftKey) {
      const usedLabels = new Set((arrangementRef.current?.markers || []).map((marker) => marker.label));
      const label = event.shiftKey
        ? JUMP_MARKER_LABELS.find((value) => !usedLabels.has(value)) || 'M'
        : `M${(arrangementRef.current?.markers || []).length + 1}`;
      store2.updateArrangement((draft) => {
        draft.markers = sortMarkers([...(draft.markers || []), { id: makeId('marker'), label, time: snapTime(time), type: event.shiftKey ? 'jump' : 'marker', note: null }]);
        return draft;
      });
      return;
    }
    if (toolMode === 'range' || event.ctrlKey || event.metaKey || event.altKey) {
      const anchor = snapTime(time);
      store2.setSelection({ start: anchor, end: anchor });
      beginPointerDrag(event, {
        kind: 'range',
        onMove: (moveEvent) => {
          const now = snapTime(timeFromPointer(moveEvent));
          useDawStore.getState().setSelection({ start: Math.min(anchor, now), end: Math.max(anchor, now) });
        },
        onEnd: () => {
          const range = useDawStore.getState().selection;
          if (range && range.end - range.start < 0.05) useDawStore.getState().setSelection(null);
        },
      });
      return;
    }
    seekTo(snapTime(time));
    beginPointerDrag(event, {
      kind: 'scrub',
      onMove: (moveEvent) => seekTo(snapTime(timeFromPointer(moveEvent))),
    });
  }, [beginPointerDrag, seekTo, snapTime, timeFromPointer, toolMode]);

  const onLanePointerDown = useCallback((event) => {
    if (event.target !== event.currentTarget) return;
    if (toolMode === 'split') return;
    seekTo(snapTime(timeFromPointer(event)));
    useDawStore.getState().setSelectedClipId('');
    setClipAiState({ clipId: '', prompt: '' });
  }, [seekTo, snapTime, timeFromPointer, toolMode]);

  const onMarkerClick = useCallback((event, marker, index) => {
    if (event.altKey) {
      useDawStore.getState().updateArrangement((draft) => {
        draft.markers = (draft.markers || []).filter((_, markerIndex) => markerIndex !== index);
        return draft;
      });
      return;
    }
    seekTo(marker.time);
  }, [seekTo]);

  // ---- Track-Verwaltung ------------------------------------------------------------
  const patchTrack = useCallback((trackId, patch) => {
    useDawStore.getState().updateArrangement((draft) => {
      draft.tracks = draft.tracks.map((track) => (track.id === trackId ? { ...track, ...patch } : track));
      return draft;
    }, { commit: false });
  }, []);

  const addTrack = useCallback(() => {
    useDawStore.getState().updateArrangement((draft) => {
      if ((draft.tracks || []).length >= MAX_TRACKS) return draft;
      const index = draft.tracks.length + 1;
      let id = `track-${index}`;
      while (draft.tracks.some((track) => track.id === id)) id = makeId('track');
      draft.tracks = [...draft.tracks, { id, name: `Spur ${index}`, muted: false, solo: false, volume_db: 0 }];
      return draft;
    });
  }, []);

  const removeTrack = useCallback((trackId) => {
    useDawStore.getState().updateArrangement((draft) => {
      if (draft.tracks.length <= 1) return draft;
      draft.tracks = draft.tracks.filter((track) => track.id !== trackId);
      const fallback = draft.tracks[0].id;
      draft.clips = draft.clips.map((clip) => (clip.track_id === trackId ? { ...clip, track_id: fallback } : clip));
      return draft;
    });
  }, []);

  // ---- KI-Befehle --------------------------------------------------------------------
  const appendAiHistory = useCallback((role, text, meta = {}) => {
    const value = String(text || '').trim();
    if (!value) return;
    setAiHistory((current) => [...current.slice(-9), { id: makeId('ai'), role, text: value, meta }]);
  }, []);

  const applyLocalAudioExpansionFromDawCommand = useCallback((prompt) => {
    const state = useDawStore.getState();
    const currentAsset = state.asset;
    if (!currentAsset?.id) {
      const message = 'Kein AudioAsset für die lokale DAW-Änderung ausgewählt.';
      setAiCommandStatus(message);
      appendAiHistory('assistant', message, { tone: 'warning' });
      notify?.(message, 'warning');
      return false;
    }

    const text = String(prompt || '').toLowerCase();
    let sectionKind = dawAiSectionKindFromText(prompt);
    if (!sectionKind && /(?:^|\s)(?:part|strophe|verse|rap)(?:\s|$)/.test(text)) sectionKind = 'verse';
    const selectedSection = state.sections.find((section) => section.id === state.selectedSectionId) || null;
    const section = (sectionKind
      ? state.sections.find((item) => item.kind === sectionKind)
      : null) || selectedSection;
    const appendToEnd = /ans?\s*ende|am\s*ende|append|neue[nrms]?|neu|hinzufueg|hinzufug|fuege|fuge|dritter|dritten/.test(text)
      && section?.kind !== 'intro';
    try {
      let plan;
      if (section) {
        plan = state.previewCommand({
          type: appendToEnd ? 'section_append_to_end' : 'section_duplicate',
          sectionId: section.id,
          section,
          aiPrompt: prompt,
          aiSource: 'local-daw-audio-expansion',
        });
      } else if (state.selectedClipId) {
        plan = state.previewCommand({
          type: 'clip_duplicate',
          clipId: state.selectedClipId,
          aiPrompt: prompt,
          aiSource: 'local-daw-audio-expansion',
        });
      } else {
        throw new Error('Für lokale Verlängerung brauche ich einen erkannten Abschnitt oder ausgewählten Clip.');
      }
      const normalized = state.applyCommandPlan(plan);
      if (!normalized) throw new Error('Lokaler DAW-Plan konnte nicht angewendet werden.');
      if (Number.isFinite(Number(plan.guideTime))) seekTo(plan.guideTime);
      const message = `${plan.title || 'Lokale Audio-Änderung'} direkt in der Timeline angewendet.`;
      setAiCommandStatus(message);
      appendAiHistory('assistant', message, { tone: 'success' });
      notify?.(message, 'success');
      return true;
    } catch (err) {
      const message = err?.message || 'Lokale Audio-Änderung konnte nicht angewendet werden.';
      setAiCommandStatus(message);
      appendAiHistory('assistant', message, { tone: 'warning' });
      notify?.(message, 'warning');
      return false;
    }
  }, [appendAiHistory, notify, seekTo]);

  const runServerAiCommand = useCallback(async (prompt, options = {}) => {
    const state = useDawStore.getState();
    if (!state.asset) return false;
    state.setAiBusy(true);
    try {
      const result = await api.daw.arrangementAiCommand(state.asset.id, {
        message: prompt,
        arrangement: state.arrangement,
        selected_clip_id: options.clipId || state.selectedClipId || null,
        selected_section_id: state.selectedSectionId || null,
        current_time: state.currentTime,
        selection: state.selection,
        execute: false,
      });
      if (!result?.ok || !result?.arrangement) {
        const message = result?.message || 'Die Server-KI konnte den Befehl nicht auflösen.';
        setAiCommandStatus(message);
        appendAiHistory('assistant', message, { tone: 'warning' });
        return false;
      }
      const normalized = normalizeArrangement(result.arrangement, state.asset, Math.max(state.sourceDuration, safeNumber(result.arrangement?.duration_seconds)));
      const plan = {
        id: makeId('daw-command'),
        command: { type: 'server_ai', message: prompt },
        aiPrompt: prompt,
        aiInterpretation: result.interpretation || result.message || '',
        aiSource: result.source || 'daw_arrangement_ai',
        title: `KI: ${result.title || 'Arrangement-Änderung'}`,
        summary: result.message || result.interpretation || 'Von der Server-KI geplante Änderung prüfen.',
        actions: Array.isArray(result.actions) && result.actions.length ? result.actions : [`KI-Befehl: „${prompt}“`],
        warnings: Array.isArray(result.warnings) ? result.warnings : [],
        beforeDuration: arrangementLength(state.arrangement, state.sourceDuration || 1),
        afterDuration: arrangementLength(normalized, state.sourceDuration || 1),
        originalArrangement: state.arrangement,
        nextArrangement: normalized,
        nextSelectedClipId: result.selected_clip_id || state.selectedClipId,
        nextSelection: null,
      };
      const applied = state.applyCommandPlan(plan);
      if (!applied) throw new Error('Server-KI-Plan konnte nicht angewendet werden.');
      if (Number.isFinite(Number(plan.guideTime))) seekTo(plan.guideTime);
      appendAiHistory('assistant', plan.aiInterpretation || 'Server-KI-Plan direkt in der Timeline angewendet.');
      setAiCommandStatus(plan.aiInterpretation || 'Server-KI-Plan direkt angewendet.');
      return true;
    } catch (err) {
      const message = err.message || 'Server-KI ist nicht erreichbar.';
      setAiCommandStatus(message);
      appendAiHistory('assistant', message, { tone: 'warning' });
      return false;
    } finally {
      useDawStore.getState().setAiBusy(false);
    }
  }, [appendAiHistory, seekTo]);

  const runDawAiCommand = useCallback(async (prompt, options = {}) => {
    const rawPrompt = String(prompt || '').trim();
    if (!rawPrompt) return;
    appendAiHistory('user', rawPrompt);
    if (rawPrompt.toLowerCase().startsWith('/prompts')) {
      const query = rawPrompt.slice('/prompts'.length).trim().toLowerCase();
      const promptHooks = dawPromptHooks.filter((hook) => {
        if (!query) return true;
        return `${hook.title || ''} ${hook.description || ''} ${hook.prompt || ''}`.toLowerCase().includes(query);
      });
      const message = promptHooks.length ? 'Gespeicherte DAW-Aufhänger:' : 'Keine passenden DAW-Aufhänger gespeichert.';
      setAiCommandStatus(message);
      appendAiHistory('assistant', message, { promptHooks });
      return;
    }
    const state = useDawStore.getState();
    const ctx = {
      sections: state.sections,
      selectedSection: state.sections.find((section) => section.id === state.selectedSectionId) || null,
      selectedSectionId: state.selectedSectionId,
      selectedClipId: state.selectedClipId,
      selection: state.selection,
      currentTime: state.currentTime,
      closeGap: state.closeGap,
      arrangement: state.arrangement,
      asset: state.asset,
      beatgrid: state.beatgrid,
      sourceDuration: state.sourceDuration,
    };
    try {
      const command = parseDawAiCommand(rawPrompt, ctx, options);
      if (command.uiAction === 'needs_generation_workflow') {
        applyLocalAudioExpansionFromDawCommand(rawPrompt);
        return;
      }
      setAiCommandStatus(command.aiInterpretation || 'Befehl erkannt.');
      appendAiHistory('assistant', command.aiInterpretation || 'Befehl erkannt und als prüfbarer Plan vorbereitet.');
      if (command.uiAction === 'focus_section' && command.section) {
        state.setSelectedSectionId(command.section.id);
        state.setSelection({ start: command.section.start, end: command.section.end });
        seekTo(command.section.start);
        return;
      }
      if (command.uiAction === 'range_30') {
        const start = state.currentTime;
        state.setSelection({ start, end: Math.min(timelineDuration, start + 30) });
        return;
      }
      const plan = state.previewCommand(command);
      const applied = state.applyCommandPlan(plan);
      if (!applied) throw new Error('DAW-Befehl konnte nicht angewendet werden.');
      if (Number.isFinite(Number(plan.guideTime))) seekTo(plan.guideTime);
      setAiCommandStatus(plan.aiInterpretation || plan.summary || 'Befehl direkt in der Timeline angewendet.');
      if (options.closeClipPanel !== false) setClipAiState({ clipId: '', prompt: '' });
    } catch (err) {
      // Lokal nicht auflösbar → Server-KI-Planer (mit Beatgrid-/Sektionskontext).
      if (useServerAi && await runServerAiCommand(rawPrompt, options)) {
        if (options.closeClipPanel !== false) setClipAiState({ clipId: '', prompt: '' });
        return;
      }
      const message = err.message || 'KI-DAW-Befehl konnte nicht interpretiert werden.';
      setAiCommandStatus(message);
      appendAiHistory('assistant', message, { tone: 'warning' });
      notify?.(message, 'warning');
    }
  }, [appendAiHistory, applyLocalAudioExpansionFromDawCommand, dawPromptHooks, notify, runServerAiCommand, seekTo, timelineDuration, useServerAi]);

  const clipAi = useMemo(() => ({
    clipId: clipAiState.clipId,
    prompt: clipAiState.prompt,
    open: (clip) => {
      useDawStore.getState().setSelectedClipId(clip.id);
      setAiPanelOpen(false);
      setClipAiState((current) => ({ clipId: clip.id, prompt: current.clipId === clip.id ? current.prompt : '' }));
    },
    close: () => setClipAiState({ clipId: '', prompt: '' }),
    setPrompt: (clip, prompt) => setClipAiState({ clipId: clip.id, prompt }),
    submit: (clip) => {
      const prompt = clipAiState.clipId === clip.id ? clipAiState.prompt : '';
      if (!prompt.trim()) return;
      runDawAiCommand(prompt, { clipId: clip.id, source: 'clip-ai' });
    },
  }), [clipAiState, runDawAiCommand]);

  // ---- Persistenz / Render --------------------------------------------------------------
  const currentArrangementPayload = useCallback(() => {
    const state = useDawStore.getState();
    return normalizeArrangement(state.arrangement, state.asset, Math.max(state.sourceDuration, arrangementLength(state.arrangement, 1)));
  }, []);

  const saveArrangement = useCallback(async ({ silent = false } = {}) => {
    const state = useDawStore.getState();
    if (!state.asset || !state.arrangement) return null;
    setSaving(true);
    try {
      const payload = currentArrangementPayload();
      const result = await api.daw.saveArrangement(state.asset.id, payload, { sessionId: activeSessionId, title: versionLabel });
      if (result?.session) {
        setActiveSessionId(result.session.id);
        setArrangementSessions((items) => {
          const rest = items.filter((item) => String(item.id) !== String(result.session.id));
          return [result.session, ...rest].sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')));
        });
      }
      state.markSaved();
      if (!silent) notify?.('Arrangement gespeichert.', 'success');
      return result;
    } catch (err) {
      notify?.(err.message || 'Arrangement konnte nicht gespeichert werden.', 'error');
      return null;
    } finally {
      setSaving(false);
    }
  }, [activeSessionId, currentArrangementPayload, notify, versionLabel]);

  const createNewSession = useCallback(async () => {
    const state = useDawStore.getState();
    if (!state.asset || !state.arrangement) return;
    setSaving(true);
    try {
      const title = `${versionLabel || 'DAW Session'} Kopie`.slice(0, 80);
      const result = await api.daw.createArrangementSession(state.asset.id, currentArrangementPayload(), title);
      if (result?.session) {
        setActiveSessionId(result.session.id);
        setVersionLabel(result.session.title || title);
        setArrangementSessions((items) => [result.session, ...items.filter((item) => String(item.id) !== String(result.session.id))]);
        useDawStore.getState().markSaved();
        notify?.('Neue DAW-Session gespeichert.', 'success');
      }
    } catch (err) {
      notify?.(err.message || 'DAW-Session konnte nicht erstellt werden.', 'error');
    } finally {
      setSaving(false);
    }
  }, [currentArrangementPayload, notify, versionLabel]);

  const deleteActiveSession = useCallback(async () => {
    const state = useDawStore.getState();
    if (!state.asset || !activeSessionId) return;
    if (!confirm('Aktuelle DAW-Session wirklich löschen?')) return;
    try {
      await api.daw.deleteArrangementSession(state.asset.id, activeSessionId);
      const remaining = arrangementSessions.filter((item) => String(item.id) !== String(activeSessionId));
      setArrangementSessions(remaining);
      notify?.('DAW-Session gelöscht.', 'success');
      await selectAsset(state.asset.id, { sessionId: remaining[0]?.id || null });
    } catch (err) {
      notify?.(err.message || 'DAW-Session konnte nicht gelöscht werden.', 'error');
    }
  }, [activeSessionId, arrangementSessions, notify, selectAsset]);

  // Auto-Save: 2,5s nach der letzten Änderung.
  useEffect(() => {
    if (!dirty || !asset) return undefined;
    const timer = window.setTimeout(() => { saveArrangement({ silent: true }); }, 2500);
    return () => window.clearTimeout(timer);
  }, [dirty, arrangement, asset, saveArrangement]);

  const downloadPreview = useCallback(async () => {
    const state = useDawStore.getState();
    if (!state.asset) return;
    setPreviewing(true);
    try {
      const blob = await api.daw.previewArrangement(state.asset.id, {
        arrangement: currentArrangementPayload(),
        session_id: activeSessionId,
        output_format: outputFormat,
        version_label: versionLabel,
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${versionLabel || 'daw_preview'}.${outputFormat}`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 4000);
    } catch (err) {
      notify?.(err.message || 'Vorschau-Render fehlgeschlagen.', 'error');
    } finally {
      setPreviewing(false);
    }
  }, [activeSessionId, currentArrangementPayload, notify, outputFormat, versionLabel]);

  const renderAsVersion = useCallback(async () => {
    const state = useDawStore.getState();
    if (!state.asset) return;
    try {
      await saveArrangement({ silent: true });
      const result = await api.daw.renderArrangementTask(state.asset.id, {
        arrangement: currentArrangementPayload(),
        session_id: activeSessionId,
        output_format: outputFormat,
        version_label: versionLabel,
        create_notification: true,
      });
      setRenderTask({ id: result.task_local_id, status: result.status || 'RUNNING' });
      notify?.(result.message || 'Render als Hintergrund-Task gestartet.', 'info');
    } catch (err) {
      notify?.(err.message || 'Render konnte nicht gestartet werden.', 'error');
    }
  }, [activeSessionId, currentArrangementPayload, notify, outputFormat, saveArrangement, versionLabel]);

  const renderTaskStatus = String(renderTask?.status || '').toUpperCase();
  const renderTaskActive = Boolean(renderTask?.id) && !['SUCCESS', 'COMPLETED', 'DONE', 'FAILED', 'ERROR', 'CANCELLED'].includes(renderTaskStatus);
  useEffect(() => {
    if (!renderTask?.id || !renderTaskActive) return undefined;
    let cancelled = false;
    const poll = async () => {
      try {
        const fresh = await api.music.getTask(renderTask.id);
        if (cancelled) return;
        setRenderTask(fresh);
        const status = String(fresh?.status || '').toUpperCase();
        if (['SUCCESS', 'COMPLETED', 'DONE'].includes(status)) {
          notify?.('DAW-Version wurde fertig gespeichert.', 'success');
          onReload?.();
        } else if (['FAILED', 'ERROR', 'CANCELLED'].includes(status)) {
          notify?.(fresh?.error_message || 'DAW-Render ist fehlgeschlagen.', 'error');
        }
      } catch { /* Polling darf den Editor nicht blockieren */ }
    };
    const timer = window.setInterval(poll, 1800);
    poll();
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [renderTask?.id, renderTaskActive, notify, onReload]);
  const renderTaskProgress = safeNumber(renderTask?.response_payload?.progress?.percent ?? renderTask?.progress, 0);

  const resetArrangement = useCallback(() => {
    const state = useDawStore.getState();
    if (!state.asset) return;
    state.commitHistory();
    const fresh = normalizeArrangement(null, state.asset, state.sourceDuration);
    state.setArrangementDirect(fresh);
    state.setSelectedClipId(fresh.clips[0]?.id || '');
    state.setSelection(null);
    notify?.('Arrangement auf den Ausgangszustand zurückgesetzt.', 'info');
  }, [notify]);

  // ---- Shortcuts --------------------------------------------------------------------------
  const hotkeyOptions = { enableOnFormTags: false, preventDefault: true };
  useHotkeys('space', () => playPause(), hotkeyOptions, [playPause]);
  useHotkeys('s', () => useDawStore.getState().previewCommand({ type: 'clip_split', time: useDawStore.getState().currentTime }), hotkeyOptions, []);
  useHotkeys('delete,backspace', () => {
    const state = useDawStore.getState();
    if (state.selection) state.previewCommand({ type: 'range_delete', range: state.selection, closeGap: state.closeGap });
    else if (state.selectedClipId) state.previewCommand({ type: 'clip_delete', clipId: state.selectedClipId });
  }, hotkeyOptions, []);
  useHotkeys('escape', () => {
    const state = useDawStore.getState();
    state.setSelection(null);
    state.setCommandPreview(null);
    setClipAiState({ clipId: '', prompt: '' });
  }, { ...hotkeyOptions, enableOnFormTags: true }, []);
  useHotkeys('mod+z', () => { useDawStore.getState().undo(); }, hotkeyOptions, []);
  useHotkeys('mod+y,mod+shift+z', () => { useDawStore.getState().redo(); }, hotkeyOptions, []);
  useHotkeys('left', () => seekTo(useDawStore.getState().currentTime - 1), hotkeyOptions, [seekTo]);
  useHotkeys('right', () => seekTo(useDawStore.getState().currentTime + 1), hotkeyOptions, [seekTo]);
  useHotkeys('shift+left', () => seekTo(useDawStore.getState().currentTime - 5), hotkeyOptions, [seekTo]);
  useHotkeys('shift+right', () => seekTo(useDawStore.getState().currentTime + 5), hotkeyOptions, [seekTo]);
  useHotkeys('1,2,3,4,5,6,7,8,9', (event) => {
    const marker = (arrangementRef.current?.markers || []).find((item) => item.label === event.key);
    if (marker) seekTo(marker.time);
  }, hotkeyOptions, [seekTo]);

  // ---- Rendering ---------------------------------------------------------------------------
  const lastKnownAsset = playable.find((item) => String(item.id) === String(lastKnownAssetId));

  if (!asset) {
    return (
      <section className="daw-shell">
        <header className="daw-header">
          <button type="button" className="icon-button" onClick={onBackToLibrary}><ArrowLeft size={15} /> Library</button>
          <AssetPicker playable={playable} value={assetId} onChange={selectAsset} />
          {loading ? <span className="daw-status-chip"><Loader2 size={13} className="daw-spin" /> Lädt …</span> : null}
        </header>
        {loading ? <div className="daw-empty-state"><h2>Mini-DAW</h2><p>Song wird geladen …</p></div> : <DawEmptyState lastKnownAsset={lastKnownAsset} onOpenLast={() => selectAsset(lastKnownAssetId)} onBackToLibrary={onBackToLibrary} />}
      </section>
    );
  }

  return (
    <section className="daw-shell" aria-busy={loading}>
      <header className="daw-header">
        <button type="button" className="icon-button" onClick={onBackToLibrary}><ArrowLeft size={15} /> Library</button>
        <AssetPicker playable={playable} value={assetId} onChange={selectAsset} />
        <div className="daw-header-status">
          {loading ? <span className="daw-status-chip"><Loader2 size={13} className="daw-spin" /> Lädt …</span> : null}
          {dirty ? <span className="daw-status-chip warn">Ungespeicherte Änderungen</span> : <span className="daw-status-chip ok">Gespeichert</span>}
          {renderTaskActive ? <span className="daw-status-chip"><Loader2 size={13} className="daw-spin" /> Render {Math.round(renderTaskProgress)}%</span> : null}
        </div>
        <div className="daw-header-actions">
          <label className="daw-inline-field">
            <span>Session</span>
            <select
              value={activeSessionId || ''}
              onChange={(event) => selectAsset(asset.id, { sessionId: event.target.value || null })}
              title="Gespeicherte DAW-Session öffnen"
            >
              <option value="">Neuester Stand</option>
              {arrangementSessions.map((session) => (
                <option key={session.id} value={session.id}>{session.title || `Session ${session.id}`}</option>
              ))}
            </select>
          </label>
          <button type="button" onClick={createNewSession} disabled={saving} title="Aktuelles Arrangement als neue Session speichern"><Plus size={14} /> Session</button>
          <button type="button" className="icon-button" onClick={deleteActiveSession} disabled={!activeSessionId} title="Aktuelle DAW-Session löschen"><Trash2 size={14} /></button>
          <label className="daw-inline-field">
            <span>Version</span>
            <input value={versionLabel} maxLength={80} onChange={(event) => setVersionLabel(event.target.value)} />
          </label>
          <select value={outputFormat} onChange={(event) => setOutputFormat(event.target.value)} title="Ausgabeformat">
            {OUTPUT_FORMATS.map((format) => <option key={format} value={format}>{format.toUpperCase()}</option>)}
          </select>
          <button type="button" className="icon-button" onClick={resetArrangement} title="Arrangement zurücksetzen"><RotateCcw size={14} /></button>
          <button type="button" onClick={() => saveArrangement()} disabled={saving}><Save size={14} /> Speichern</button>
          <button type="button" onClick={downloadPreview} disabled={previewing} title="Arrangement als Datei herunterladen (ffmpeg-Render)">
            {previewing ? <Loader2 size={14} className="daw-spin" /> : <Download size={14} />} Export
          </button>
          <button type="button" className="primary" onClick={renderAsVersion} disabled={renderTaskActive} title="Als neue Version in die Library rendern">
            <FileAudio size={14} /> Als Version speichern
          </button>
        </div>
      </header>

      <TransportBar
        isPlaying={isPlaying}
        timelineDuration={timelineDuration}
        volume={volume}
        onPlayPause={playPause}
        onStop={stopPlayback}
        onSkip={(delta) => seekTo(useDawStore.getState().currentTime + delta)}
        onVolumeChange={(value) => store.setVolume(value)}
        bpm={arrangement?.bpm ?? null}
        timeSignature={arrangement?.time_signature || '4/4'}
        onBpmChange={(bpm) => store.updateArrangement((draft) => ({ ...draft, bpm }), { commit: false })}
        onTimeSignatureChange={(value) => store.updateArrangement((draft) => ({ ...draft, time_signature: value }), { commit: false })}
        snapEnabled={Boolean(arrangement?.snap_enabled)}
        snapUnit={arrangement?.snap_unit || 'beat'}
        onSnapToggle={() => store.updateArrangement((draft) => ({ ...draft, snap_enabled: !draft.snap_enabled }), { commit: false })}
        onSnapUnitChange={(unit) => store.updateArrangement((draft) => ({ ...draft, snap_unit: unit }), { commit: false })}
        beatgridStatusLabel={beatgridStatusLabel}
        beatgrid={activeBeatgrid}
        toolMode={toolMode}
        onToolModeChange={(mode) => store.setToolMode(mode)}
        zoom={timelineZoom}
        zoomMax={ZOOM_PX_PER_SECOND.length - 1}
        onZoomChange={(zoom) => store.setTimelineZoom(clamp(zoom, 0, ZOOM_PX_PER_SECOND.length - 1))}
        followPlayhead={followPlayhead}
        onToggleFollow={() => setFollowPlayhead((value) => !value)}
        canUndo={canUndo}
        canRedo={canRedo}
        onUndo={() => store.undo()}
        onRedo={() => store.redo()}
        aiPanelOpen={aiPanelOpen}
        onToggleAiPanel={() => { setAiPanelOpen((open) => !open); setClipAiState({ clipId: '', prompt: '' }); }}
      />

      <div className="daw-workspace">
        <div className="daw-timeline-frame">
          <TrackHeaders
            tracks={arrangement?.tracks || []}
            onTrackPatch={patchTrack}
            onAddTrack={addTrack}
            onRemoveTrack={removeTrack}
            canAddTrack={(arrangement?.tracks || []).length < MAX_TRACKS}
          />
          <div className="daw-timeline-scroll" ref={timelineScrollRef}>
            <div className="daw-timeline-content" ref={timelineContentRef} style={{ width: `${timelineWidthPx}px` }}>
              <SectionRail
                sections={sections}
                duration={timelineDuration}
                selectedSectionId={selectedSectionId}
                onFocusSection={(sectionId) => {
                  const section = sections.find((item) => item.id === sectionId);
                  if (!section) return;
                  store.setSelectedSectionId(sectionId);
                  store.setSelection({ start: section.start, end: section.end });
                  seekTo(section.start);
                }}
                onSectionCommand={(type, section) => store.previewCommand({ type, sectionId: section.id, section, closeGap })}
              />
              <TimelineRuler
                duration={timelineDuration}
                zoom={timelineZoom}
                beatgrid={activeBeatgrid}
                bpm={arrangement?.bpm}
                markers={arrangement?.markers || []}
                selection={selection}
                snapGuide={snapGuide}
                onPointerDown={onRulerPointerDown}
                onMarkerClick={onMarkerClick}
              />
              <TrackLanes
                tracks={arrangement?.tracks || []}
                clips={arrangement?.clips || []}
                duration={timelineDuration}
                sourceDuration={sourceDuration}
                waveformPeaksById={waveformPeaksById}
                selectedClipId={selectedClipId}
                toolMode={toolMode}
                interactions={{ onClipPointerDown, onTrimPointerDown, onFadePointerDown, onSplitClick }}
                clipAi={clipAi}
                aiBusy={aiBusy}
                onSelectClip={(clipId) => store.setSelectedClipId(clipId)}
                onLanePointerDown={onLanePointerDown}
              />
              <PlayheadLayer engine={engineRef.current} duration={timelineDuration} scrollRef={timelineScrollRef} follow={followPlayhead} />
            </div>
          </div>
        </div>

        <div className="daw-bottom">
          <ClipInspector
            clip={selectedClip}
            tracks={arrangement?.tracks || []}
            onPatch={(patch) => store.updateArrangement((draft) => ({
              ...draft,
              clips: draft.clips.map((clip) => (clip.id === selectedClipId ? { ...clip, ...patch } : clip)),
            }))}
            onDuplicate={() => store.previewCommand({ type: 'clip_duplicate', clipId: selectedClipId })}
            onDelete={() => store.previewCommand({ type: 'clip_delete', clipId: selectedClipId })}
            onSplitAtPlayhead={() => store.previewCommand({ type: 'clip_split', time: useDawStore.getState().currentTime, clipId: selectedClipId })}
          />
          {selectedSection ? (
            <div className="daw-selected-section-hint">
              Abschnitt: <strong>{selectedSection.displayLabel}</strong> · {secondsToClock(selectedSection.start, true)} – {secondsToClock(selectedSection.end, true)}
              <label className="daw-check">
                <input type="checkbox" checked={closeGap} onChange={(event) => store.setCloseGap(event.target.checked)} />
                <span>Lücke nach Entfernen schließen</span>
              </label>
            </div>
          ) : null}
        </div>
      </div>

      <AiCommandPanel
        open={aiPanelOpen}
        onClose={() => setAiPanelOpen(false)}
        value={aiCommandText}
        onChange={setAiCommandText}
        onSubmit={() => { runDawAiCommand(aiCommandText); setAiCommandText(''); }}
        busy={aiBusy}
        status={aiCommandStatus}
        history={aiHistory}
        examples={AI_EXAMPLES}
        useServerAi={useServerAi}
        onToggleServerAi={setUseServerAi}
        onClearHistory={() => { setAiHistory([]); setAiCommandStatus(''); setAiCommandText(''); }}
        onPromptHookSelect={(hook) => setAiCommandText(hook?.prompt || '')}
      />

      <CommandPreviewModal
        plan={commandPreview}
        onApply={(plan) => {
          const normalized = store.applyCommandPlan(plan);
          if (normalized && Number.isFinite(plan.guideTime)) showSnapGuide(plan.guideTime, plan.guideLabel || 'Angewendet');
          if (normalized) notify?.(`${plan.title} angewendet.`, 'success');
        }}
        onCancel={() => store.setCommandPreview(null)}
      />
    </section>
  );
}

function AssetPicker({ playable, value, onChange }) {
  return (
    <select
      className="daw-asset-picker"
      value={value || ''}
      onChange={(event) => onChange(event.target.value)}
      aria-label="Song für die DAW auswählen"
    >
      <option value="">Song auswählen …</option>
      {playable.map((item) => (
        <option key={item.id} value={item.id}>
          {(item.display_title || item.title || item.filename || `Audio ${item.id}`).slice(0, 80)}
          {item.version_label ? ` · ${item.version_label}` : ''}
        </option>
      ))}
    </select>
  );
}

export default DawPage;
