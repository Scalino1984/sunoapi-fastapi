import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Captions, ChevronDown, ChevronUp, Download, ExternalLink, FastForward, FileText, Headphones, Image as ImageIcon, MoreVertical, Pause, Play, Repeat, Rewind, RotateCcw, SkipBack, SkipForward, Sparkles, ThumbsUp, Volume2, VolumeX, Waves, X } from 'lucide-react';
import { api } from '../api/client.js';
import { formatDuration, handleCoverImageError, operationLabel, pickCover, pickLyrics, pickPrompt, pickStyle, pickTitle } from '../utils.js';
import { Waveform } from './Waveform.jsx';
import { useI18n } from '../i18n/I18nContext.jsx';

function formatClock(value) {
  const seconds = Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}:${String(rest).padStart(2, '0')}`;
}

function parseSrtTimestamp(value) {
  const match = String(value || '').trim().replace('.', ',').match(/^(\d{1,2}):(\d{2}):(\d{2}),(\d{1,3})$/);
  if (!match) return 0;
  const [, h, m, s, ms] = match;
  return Number(h) * 3600 + Number(m) * 60 + Number(s) + Number(ms.padEnd(3, '0').slice(0, 3)) / 1000;
}

function parseSrtText(text) {
  const raw = String(text || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
  if (!raw) return [];
  const blocks = raw.split(/\n\s*\n+/);
  const timeRe = /(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})/;
  return blocks.map((block) => {
    const lines = String(block || '').split('\n').map((line) => line.trim()).filter(Boolean);
    const timeIndex = lines.findIndex((line) => timeRe.test(line));
    if (timeIndex < 0) return null;
    const match = lines[timeIndex].match(timeRe);
    const textValue = lines.slice(timeIndex + 1).join('\n').trim();
    if (!match || !textValue) return null;
    return { start: parseSrtTimestamp(match[1]), end: parseSrtTimestamp(match[2]), text: textValue };
  }).filter(Boolean).sort((a, b) => a.start - b.start);
}

function srtSegmentsFromState(state) {
  if (Array.isArray(state?.segments) && state.segments.length) {
    return state.segments
      .map((segment) => ({ start: Number(segment.start || 0), end: Number(segment.end || 0), text: String(segment.text || '').trim() }))
      .filter((segment) => segment.text && segment.end > segment.start)
      .sort((a, b) => a.start - b.start);
  }
  return parseSrtText(state?.srt_text || '');
}

function findActiveSrtSegment(segments, currentTime) {
  const t = Number(currentTime || 0);
  return (segments || []).find((segment) => t >= Number(segment.start || 0) && t < Number(segment.end || 0)) || null;
}

function findRecentlyEndedSrtSegment(segments, currentTime, holdSeconds = 0.45, bridgeGapSeconds = 1.8) {
  const t = Number(currentTime || 0);
  let previous = null;
  const rows = segments || [];
  for (const segment of rows) {
    const start = Number(segment.start || 0);
    const end = Number(segment.end || 0);
    if (start > t) break;
    if (end <= t && t - end <= holdSeconds) previous = segment;
  }
  if (previous) return previous;

  for (let index = 0; index < rows.length; index += 1) {
    const segment = rows[index];
    const end = Number(segment.end || 0);
    const next = rows[index + 1] || null;
    const nextStart = Number(next?.start || 0);
    if (end <= t && next && t < nextStart && nextStart - end <= bridgeGapSeconds) return segment;
  }
  return previous;
}

const TASK_SUCCESS_STATUSES = new Set(['SUCCESS', 'COMPLETED', 'COMPLETE', 'DONE', 'FINISHED']);
const TASK_FAILURE_STATUSES = new Set(['FAILED', 'ERROR', 'CANCELLED', 'CANCELED', 'TIMEOUT']);

function taskStatusValue(task) {
  return String(task?.status || task?.response_payload?.status || task?.result_payload?.status || '').trim().toUpperCase();
}

function isTaskSuccess(task) {
  const status = taskStatusValue(task);
  const resultStatus = String(task?.result_payload?.status || task?.response_payload?.result?.status || '').trim().toLowerCase();
  return TASK_SUCCESS_STATUSES.has(status)
    || ['completed', 'success', 'done'].includes(resultStatus)
    || Boolean(task?.result_payload?.srt_text || task?.response_payload?.result?.srt_text || task?.response_payload?.result?.exists);
}

function isTaskFailure(task) {
  return TASK_FAILURE_STATUSES.has(taskStatusValue(task));
}

function taskResultPayload(task) {
  return task?.result_payload || task?.response_payload?.result || null;
}

function srtStateHasContent(state) {
  if (!state || state.exists === false) return false;
  return Boolean(
    state.srt_text
    || state.srt_url
    || state.srt_path
    || state.download_url
    || state.half_srt_text
    || state.half_srt_url
    || (Array.isArray(state.segments) && state.segments.length)
  );
}

function stableStreamUrl(assetId, cacheBust = false) {
  const safeId = encodeURIComponent(String(assetId || '').trim());
  if (!safeId) return '';
  return `/api/archive/audio/${safeId}/stream${cacheBust ? `?retry=${Date.now()}` : ''}`;
}

function parseMaybeJson(value) {
  if (!value) return null;
  if (typeof value === 'object') return value;
  try { return JSON.parse(value); } catch { return null; }
}

function trustedAssetDuration(asset) {
  const assetDuration = Number(asset?.duration_seconds || 0);
  const waveform = parseMaybeJson(asset?.waveform_json);
  const waveformDuration = Number(waveform?.duration_seconds || 0);
  if (Number.isFinite(waveformDuration) && waveformDuration > 0) return waveformDuration;
  if (Number.isFinite(assetDuration) && assetDuration > 0) return assetDuration;
  return 0;
}

function resolvePlaybackDuration(nativeDuration, asset) {
  const nativeValue = Number(nativeDuration || 0);
  const trustedValue = trustedAssetDuration(asset);
  if (trustedValue > 0) return trustedValue;
  return nativeValue > 0 ? nativeValue : 0;
}

export function MiniPlayer({ queue, currentIndex, loop, sidebarMode = 'open', mobileNavOpen = false, playerCommand = 0, onPlaybackStateChange, onLoopChange, onIndexChange, onOpenDetails, onPrepareMusic, onFavoriteChange, onClose }) {
  const { t } = useI18n();
  const audioRef = useRef(null);
  const progressRef = useRef(null);
  const lastPlayerCommandRef = useRef(0);
  const streamRetryRef = useRef({ assetId: null, count: 0 });
  const srtTaskWatchRef = useRef({ assetId: null, taskId: null, timer: null, attempts: 0 });
  const [error, setError] = useState('');
  const [isPlaying, setIsPlaying] = useState(false);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [volume, setVolume] = useState(() => Number(localStorage.getItem('react-player-volume') || '0.9'));
  const [muted, setMuted] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [playerView, setPlayerView] = useState(() => localStorage.getItem('react-mini-player-view') || 'waveform');
  const [srtState, setSrtState] = useState(null);
  const [srtLoading, setSrtLoading] = useState(false);
  const [srtGenerating, setSrtGenerating] = useState(false);
  const [actionBusy, setActionBusy] = useState('');
  const [favoriteSaving, setFavoriteSaving] = useState(false);
  const [favoriteOverride, setFavoriteOverride] = useState(null);
  const current = queue?.[currentIndex] || null;
  const currentAssetId = current?.id ? String(current.id) : '';

  const src = useMemo(() => stableStreamUrl(currentAssetId), [currentAssetId]);

  function assignAudioSource(audio, cacheBust = false) {
    if (!audio || !current?.id) return '';
    const nextSrc = stableStreamUrl(current.id, cacheBust);
    if (!nextSrc) return '';
    audio.src = nextSrc;
    audio.load();
    return nextSrc;
  }

  async function preparePlaybackAsset({ cacheBust = true } = {}) {
    const audio = audioRef.current;
    if (!audio || !current?.id) return false;

    try {
      const result = await api.archive.preparePlayback(current.id);
      if (!audioRef.current || String(current?.id || '') !== String(currentAssetId || '')) return false;
      assignAudioSource(audioRef.current, cacheBust);
      if (result?.cached) setError('');
      return Boolean(result?.ready ?? true);
    } catch {
      if (!audioRef.current) return false;
      assignAudioSource(audioRef.current, cacheBust);
      return false;
    }
  }

  function clearSrtTaskWatcher() {
    const watcher = srtTaskWatchRef.current;
    if (watcher?.timer) window.clearTimeout(watcher.timer);
    srtTaskWatchRef.current = { assetId: null, taskId: null, timer: null, attempts: 0 };
  }

  function startSrtTaskWatcher(assetId, taskId, { switchToSrt = true } = {}) {
    if (!assetId || !taskId || typeof window === 'undefined') return;
    const expectedAssetId = String(assetId);
    clearSrtTaskWatcher();
    srtTaskWatchRef.current = { assetId: expectedAssetId, taskId, timer: null, attempts: 0 };

    const finishWithSrtState = async (state) => {
      const nextState = state && String(state.audio_asset_id || expectedAssetId) === expectedAssetId
        ? { ...state, audio_asset_id: Number(assetId) || assetId }
        : state;
      if (!srtStateHasContent(nextState)) return false;
      clearSrtTaskWatcher();
      setSrtState(nextState);
      setSrtGenerating(false);
      setSrtLoading(false);
      setError('');
      if (switchToSrt) setPlayerView('srt');
      window.dispatchEvent(new CustomEvent('srt:updated', { detail: { audio_asset_id: assetId, srt: nextState } }));
      return true;
    };

    const poll = async () => {
      const watcher = srtTaskWatchRef.current;
      if (!watcher || String(watcher.assetId || '') !== expectedAssetId || String(watcher.taskId || '') !== String(taskId)) return;
      watcher.attempts += 1;

      if (String(current?.id || '') && String(current.id) !== expectedAssetId) {
        clearSrtTaskWatcher();
        setSrtGenerating(false);
        return;
      }

      try {
        const task = await api.music.getTask(taskId);
        const result = taskResultPayload(task);

        if (isTaskSuccess(task)) {
          if (await finishWithSrtState(result)) return;
          const state = await fetchSrtState(assetId, { quiet: true });
          if (await finishWithSrtState(state)) return;

          // Task ist fertig, aber die SRT-Read-Route kann unmittelbar danach noch
          // einen kurzen Moment hinterherhinken. Deshalb wenige Male nachziehen,
          // statt die Player-Meldung dauerhaft auf RUNNING stehen zu lassen.
          if (watcher.attempts >= 8) {
            clearSrtTaskWatcher();
            setSrtGenerating(false);
            setSrtLoading(false);
            setError(t('player.errors.srtGeneratedReload', 'SRT wurde erzeugt. Anzeige wird beim nächsten Aktualisieren geladen.'));
            window.dispatchEvent(new CustomEvent('srt:updated', { detail: { audio_asset_id: assetId } }));
            return;
          }
        } else if (isTaskFailure(task)) {
          const message = task?.error_message || task?.response_payload?.message || task?.result_payload?.message || t('player.errors.srtFailed', 'SRT-Erzeugung fehlgeschlagen.');
          clearSrtTaskWatcher();
          setSrtGenerating(false);
          setSrtLoading(false);
          setError(message);
          window.dispatchEvent(new CustomEvent('srt:updated', { detail: { audio_asset_id: assetId, srt: { audio_asset_id: assetId, exists: false, status: 'error', error_message: message } } }));
          return;
        } else if (watcher.attempts % 3 === 0) {
          // Auch ohne sichtbare Task-SUCCESS-Meldung kann die SRT-Datei bereits
          // geschrieben sein. Das beseitigt den Fall, dass sie erst nach einem
          // zweiten Klick sichtbar wird.
          const state = await fetchSrtState(assetId, { quiet: true });
          if (await finishWithSrtState(state)) return;
        }
      } catch (err) {
        if (watcher.attempts >= 3) {
        setError(t('player.errors.srtStatusWatching', 'SRT-Status wird weiter überwacht{{suffix}}…', { suffix: taskId ? ` (#${taskId})` : '' }));
        }
      }

      if (watcher.attempts >= 120) {
        clearSrtTaskWatcher();
        setSrtGenerating(false);
        setSrtLoading(false);
        setError(t('player.errors.srtTaskBackground', 'SRT-Task läuft weiterhin im Hintergrund{{suffix}}.', { suffix: taskId ? ` (#${taskId})` : '' }));
        return;
      }

      const delay = watcher.attempts < 10 ? 2500 : 5000;
      srtTaskWatchRef.current.timer = window.setTimeout(poll, delay);
    };

    srtTaskWatchRef.current.timer = window.setTimeout(poll, 1500);
  }

  useEffect(() => {
    streamRetryRef.current = { assetId: current?.id || null, count: 0 };
    clearSrtTaskWatcher();
    setFavoriteOverride(null);
    setFavoriteSaving(false);
    setSrtGenerating(false);
    setActionBusy('');
  }, [current?.id]);

  useEffect(() => () => clearSrtTaskWatcher(), []);

  useEffect(() => {
    if (typeof document === 'undefined') return undefined;
    const hasPlayer = Boolean(current?.id);
    document.body.classList.toggle('audio-player-open', hasPlayer);
    document.body.classList.toggle('audio-player-expanded', hasPlayer && expanded);
    return () => {
      document.body.classList.remove('audio-player-open');
      document.body.classList.remove('audio-player-expanded');
    };
  }, [current?.id, expanded]);

  useEffect(() => {
    localStorage.setItem('react-mini-player-view', playerView);
  }, [playerView]);

  async function fetchSrtState(assetId = current?.id, { quiet = false } = {}) {
    if (!assetId) return null;
    const expectedAssetId = String(assetId);
    if (!quiet) setSrtLoading(true);
    try {
      const data = await api.archive.getSrt(assetId);
      if (String(current?.id || '') !== expectedAssetId) return data;
      if (String(data?.audio_asset_id || expectedAssetId) !== expectedAssetId) {
        setSrtState(null);
        return null;
      }
      setSrtState(data);
      if (srtStateHasContent(data)) {
        setError('');
        setSrtGenerating(false);
      }
      return data;
    } catch {
      if (String(current?.id || '') === expectedAssetId) setSrtState(null);
      return null;
    } finally {
      if (!quiet && String(current?.id || '') === expectedAssetId) setSrtLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    setSrtState(null);
    if (!current?.id) return () => { cancelled = true; };
    const expectedAssetId = String(current.id);
    setSrtLoading(true);
    api.archive.getSrt(current.id)
      .then((data) => {
        if (cancelled) return;
        if (String(data?.audio_asset_id || expectedAssetId) !== expectedAssetId) {
          setSrtState(null);
          return;
        }
        setSrtState(data);
        if (srtStateHasContent(data)) setError('');
      })
      .catch(() => { if (!cancelled) setSrtState(null); })
      .finally(() => { if (!cancelled) setSrtLoading(false); });
    return () => { cancelled = true; };
  }, [current?.id]);

  useEffect(() => {
    if (typeof window === 'undefined' || !current?.id) return undefined;

    let cancelled = false;
    const expectedAssetId = String(current.id);

    async function reloadCurrentSrt() {
      setSrtLoading(true);
      try {
        const data = await api.archive.getSrt(current.id);
        if (cancelled || String(data?.audio_asset_id || '') !== expectedAssetId) return;
        setSrtState(data);
      } catch {
        if (!cancelled) setSrtState(null);
      } finally {
        if (!cancelled) setSrtLoading(false);
      }
    }

    function handleSrtUpdated(event) {
      const detail = event?.detail || {};
      const assetId = String(detail.audio_asset_id || detail.asset_id || detail.id || '');
      if (!assetId || assetId !== expectedAssetId) return;

      const nextState = detail.srt || detail.transcript || detail.result || null;
      if (nextState && String(nextState.audio_asset_id || assetId) === expectedAssetId) {
        setSrtState({ ...nextState, audio_asset_id: Number(current.id) || current.id });
        if (srtStateHasContent(nextState)) {
          setError('');
          setSrtGenerating(false);
          setPlayerView('srt');
        }
        setSrtLoading(false);
        return;
      }

      reloadCurrentSrt();
    }

    window.addEventListener('srt:updated', handleSrtUpdated);
    return () => {
      cancelled = true;
      window.removeEventListener('srt:updated', handleSrtUpdated);
    };
  }, [current?.id]);

  useEffect(() => {
    let cancelled = false;

    setError('');
    setIsPlaying(false);
    setCurrentTime(0);
    setDuration(trustedAssetDuration(current));
    setMenuOpen(false);
    setExpanded(false);

    if (!audioRef.current || !src || !currentAssetId) return () => { cancelled = true; };

    async function prepareAndPlay() {
      const audio = audioRef.current;
      if (!audio) return;

      // Auth-Refresh darf den Audio-Start nicht blockieren. Während langer Tasks
      // kann /auth/refresh kurz hängen; der vorhandene Stream funktioniert über
      // Cookie/Bearer in der Regel trotzdem. Deshalb sofort laden/spielen und
      // Refresh nur nebenbei versuchen.
      void api.auth.refresh().catch(() => null);

      audio.volume = Math.max(0, Math.min(1, volume));
      audio.muted = muted;
      assignAudioSource(audio, false);

      if (cancelled || !audioRef.current) return;

      try {
        await audio.play();
        if (!cancelled) {
          setError('');
          setIsPlaying(true);
        }
        return;
      } catch {
        // Direkt nach einer erfolgreichen Generierung kann das AudioAsset bereits
        // materialisiert sein, während der lokale Cache noch finalisiert wird.
        // Dann bereiten wir exakt dieses Asset gezielt vor und starten mit
        // cache-busted Stream-URL neu, statt den Nutzer zum Browser-F5 zu zwingen.
        if (cancelled) return;
        setError(t('player.errors.audioPreparing', 'Audio wird lokal vorbereitet. Erneuter Start läuft…'));
        await preparePlaybackAsset({ cacheBust: true });
        await new Promise((resolve) => window.setTimeout(resolve, 350));
        const retryAudio = audioRef.current;
        if (cancelled || !retryAudio) return;
        try {
          await retryAudio.play();
          if (!cancelled) {
            setError('');
            setIsPlaying(true);
          }
        } catch {
          if (!cancelled) setError(t('player.errors.autoplayBlocked', 'Autoplay wurde blockiert oder Audio ist noch nicht bereit. Bitte Play drücken.'));
        }
      }
    }

    prepareAndPlay();

    return () => {
      cancelled = true;
    };
  }, [currentAssetId, src]);

  useEffect(() => {
    if (!audioRef.current) return;
    audioRef.current.loop = Boolean(loop);
  }, [loop]);

  useEffect(() => {
    if (!audioRef.current) return;
    const safeVolume = Math.max(0, Math.min(1, volume));
    audioRef.current.volume = safeVolume;
    localStorage.setItem('react-player-volume', String(safeVolume));
  }, [volume]);

  useEffect(() => {
    if (!audioRef.current) return;
    audioRef.current.muted = muted;
  }, [muted]);

  useEffect(() => {
    onPlaybackStateChange?.({
      currentAssetId: current?.id || null,
      isPlaying,
      currentTime,
      duration: duration || Number(current?.duration_seconds || 0),
    });
  }, [current?.id, isPlaying, currentTime, duration, current?.duration_seconds, onPlaybackStateChange]);

  useEffect(() => {
    const seq = typeof playerCommand === 'object' ? Number(playerCommand?.seq || 0) : Number(playerCommand || 0);
    const action = typeof playerCommand === 'object' ? String(playerCommand?.action || 'toggle') : 'toggle';
    if (!seq || lastPlayerCommandRef.current === seq) return;
    lastPlayerCommandRef.current = seq;
    if (!current) return;

    if (action === 'toggle') { void togglePlay(); return; }
    if (action === 'pause') { pausePlayer(); return; }
    if (action === 'previous') { previous(); return; }
    if (action === 'next') { next(); return; }
    if (action === 'seek-backward') { seekRelative(-10); return; }
    if (action === 'seek-forward') { seekRelative(10); return; }
    if (action === 'mute') { setMuted((value) => !value); return; }
    if (action === 'stop-playback') { stopPlaybackOnly(); return; }
    if (action === 'stop') { closePlayer(); }
  }, [playerCommand]);

  const srtSegments = useMemo(() => srtSegmentsFromState(srtState), [srtState]);
  const activeSrtSegment = findActiveSrtSegment(srtSegments, currentTime);
  const hasSrt = srtSegments.length > 0;
  const heldSrtSegment = activeSrtSegment ? null : findRecentlyEndedSrtSegment(srtSegments, currentTime);
  const displayedSrtSegment = activeSrtSegment || heldSrtSegment || null;
  const displayedSrtText = displayedSrtSegment?.text || '';
  const displayedSrtLength = displayedSrtText.replace(/\s+/g, ' ').trim().length;
  const displayedSrtFontSize = displayedSrtLength > 125
    ? '0.58rem'
    : displayedSrtLength > 105
      ? '0.64rem'
      : displayedSrtLength > 85
        ? '0.72rem'
        : displayedSrtLength > 65
          ? '0.82rem'
          : displayedSrtLength > 45
            ? '0.94rem'
            : '1.08rem';

  useEffect(() => {
    if (typeof window === 'undefined' || !current?.id) return;
    window.dispatchEvent(new CustomEvent('player:srt-line', {
      detail: {
        assetId: current.id,
        text: displayedSrtText,
        start: displayedSrtSegment?.start || 0,
        end: displayedSrtSegment?.end || 0,
        hasSrt,
        isPlaying,
        duration: duration || Number(current?.duration_seconds || 0),
      }
    }));
  }, [current?.id, hasSrt, displayedSrtText, displayedSrtSegment?.start, displayedSrtSegment?.end, isPlaying, duration, current?.duration_seconds]);

  function handleAudioError() {
    if (!current?.id || !audioRef.current) {
      setError(t('player.errors.audioLoad', 'Audio konnte nicht geladen werden.'));
      return;
    }
    const retry = streamRetryRef.current || { assetId: current.id, count: 0 };
    if (String(retry.assetId || '') !== String(current.id)) {
      streamRetryRef.current = { assetId: current.id, count: 0 };
    }
    const count = Number(streamRetryRef.current.count || 0);
    if (count < 3) {
      streamRetryRef.current = { assetId: current.id, count: count + 1 };
      setError(t('player.errors.audioProvisioning', 'Audio wird gerade bereitgestellt. Erneuter Ladeversuch läuft…'));
      window.setTimeout(() => {
        void (async () => {
          const audio = audioRef.current;
          if (!audio || !current?.id) return;
          await preparePlaybackAsset({ cacheBust: true });
          const retryAudio = audioRef.current;
          if (!retryAudio) return;
          retryAudio.play()
            .then(() => { setError(''); setIsPlaying(true); })
            .catch(() => setError(t('player.errors.playbackRetry', 'Wiedergabe konnte noch nicht gestartet werden. Bitte erneut Play drücken.')));
        })();
      }, 1500);
      return;
    }
    setError(t('player.errors.audioLoadRefresh', 'Audio konnte nicht geladen werden. Bitte Inhalt aktualisieren oder später erneut versuchen.'));
  }

  if (!current) return null;

  const operation = operationLabel(current.operation_type || current.task_type, t);
  const currentVariantIndex = Number(current.project_variant_index || 0);
  const currentVariantTotal = Number(current.project_variant_total || queue?.length || 0);
  const currentDisplayTitle = current.project_variant_title
    || (currentVariantTotal > 1 && currentVariantIndex > 0 ? `${pickTitle(current)} ${currentVariantIndex}/${currentVariantTotal}` : pickTitle(current));
  const canPrevious = currentIndex > 0;
  const canNext = queue && currentIndex < queue.length - 1;
  const progress = duration > 0 ? Math.min(100, Math.max(0, (currentTime / duration) * 100)) : 0;
  const currentFavorite = favoriteOverride === null ? Boolean(current?.is_favorite) : Boolean(favoriteOverride);

  async function toggleCurrentFavorite() {
    if (!current?.id || favoriteSaving) return;
    const nextValue = !currentFavorite;
    setFavoriteSaving(true);
    setFavoriteOverride(nextValue);
    try {
      await api.archive.setFavorite(current.id, nextValue);
      onFavoriteChange?.(current.id, nextValue);
    } catch (err) {
      setFavoriteOverride(Boolean(current?.is_favorite));
      setError(err?.message || t('player.errors.favoriteFailed', 'Favorit konnte nicht gespeichert werden.'));
    } finally {
      setFavoriteSaving(false);
    }
  }

  async function togglePlay() {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) {
      const refreshPromise = api.auth.refresh().catch(() => null);
      const currentAudio = audioRef.current;
      if (!currentAudio) return;

      try {
        await currentAudio.play();
        setIsPlaying(true);
        setError('');
        return;
      } catch {
        // Erst wenn der direkte Start scheitert, auf einen Refresh warten und
        // die konkrete AudioAsset-Variante vorbereiten. Das vermeidet den alten
        // Zustand: neuer Song sichtbar, aber Stream erst nach Browser-F5 nutzbar.
        await refreshPromise;
        setError(t('player.errors.preparing', 'Audio wird vorbereitet. Bitte einen Moment…'));
        await preparePlaybackAsset({ cacheBust: true });
        await new Promise((resolve) => window.setTimeout(resolve, 300));
        const retryAudio = audioRef.current;
        if (!retryAudio) return;
        try {
          await retryAudio.play();
          setIsPlaying(true);
          setError('');
        } catch {
          setError(t('player.errors.playbackStartFailed', 'Wiedergabe konnte nicht gestartet werden. Bitte kurz warten und erneut Play drücken.'));
        }
      }
      return;
    }
    audio.pause();
    setIsPlaying(false);
  }

  async function restartCurrent() {
    const audio = audioRef.current;
    if (!audio || !current?.id) return;
    audio.currentTime = 0;
    setCurrentTime(0);
    try {
      await audio.play();
      setIsPlaying(true);
      setError('');
    } catch {
      setError(t('player.errors.preparing', 'Audio wird vorbereitet. Bitte einen Moment…'));
      await preparePlaybackAsset({ cacheBust: true });
      const retryAudio = audioRef.current;
      if (!retryAudio) return;
      retryAudio.currentTime = 0;
      setCurrentTime(0);
      try {
        await retryAudio.play();
        setIsPlaying(true);
        setError('');
      } catch {
        setError(t('player.errors.playbackStartFailed', 'Wiedergabe konnte nicht gestartet werden. Bitte kurz warten und erneut Play drücken.'));
      }
    }
  }

  function pausePlayer() {
    if (!audioRef.current) return;
    audioRef.current.pause();
    setIsPlaying(false);
  }

  function previous() {
    if (canPrevious) onIndexChange(currentIndex - 1);
  }

  function next() {
    if (canNext) onIndexChange(currentIndex + 1);
  }

  function closePlayer() {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.removeAttribute('src');
      audioRef.current.load();
    }
    setIsPlaying(false);
    setCurrentTime(0);
    setDuration(0);
    setMenuOpen(false);
    setExpanded(false);
    onClose?.();
  }

  function stopPlaybackOnly() {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
    }
    setIsPlaying(false);
    setCurrentTime(0);
    setMenuOpen(false);
  }

  function ended() {
    setIsPlaying(false);
    if (loop) return;
    if (canNext) onIndexChange(currentIndex + 1);
  }

  function onLoadedMetadata() {
    const detectedDuration = audioRef.current?.duration;
    const nextDuration = resolvePlaybackDuration(detectedDuration, current);
    if (nextDuration > 0) {
      setDuration(nextDuration);
    }
  }

  function onTimeUpdate() {
    const time = audioRef.current?.currentTime || 0;
    setCurrentTime(time);
  }

  function seekRelative(deltaSeconds) {
    if (!audioRef.current) return;
    const detectedDuration = duration || resolvePlaybackDuration(audioRef.current.duration, current) || 0;
    const currentPosition = audioRef.current.currentTime || 0;
    const target = Math.min(Math.max(0, currentPosition + Number(deltaSeconds || 0)), detectedDuration || Math.max(0, currentPosition + Number(deltaSeconds || 0)));
    audioRef.current.currentTime = target;
    setCurrentTime(target);
  }

  function seekFromEvent(event) {
    if (!audioRef.current || !duration || !progressRef.current) return;
    const rect = progressRef.current.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    const target = ratio * duration;
    audioRef.current.currentTime = target;
    setCurrentTime(target);
  }

  function changeVolume(event) {
    const nextVolume = Number(event.target.value) / 100;
    setVolume(nextVolume);
    if (nextVolume > 0 && muted) setMuted(false);
  }

  async function generateCurrentSrt({ switchToSrt = true } = {}) {
    if (!current?.id || srtGenerating) return;
    let keepGeneratingForWatcher = false;
    setSrtGenerating(true);
    setError(t('player.errors.srtStarting', 'SRT-Erzeugung wird gestartet…'));
    try {
      const result = await api.archive.generateSrt(current.id, { force: true });
      if (result?.queued || result?.task_local_id) {
        const taskId = result?.task_local_id || result?.id || null;
        setError(t('player.errors.srtBackground', 'SRT-Erzeugung läuft im Hintergrund{{suffix}}. Status wird automatisch überwacht…', { suffix: taskId ? ` (#${taskId})` : '' }));
        window.dispatchEvent(new CustomEvent('srt:updated', {
          detail: { audio_asset_id: current.id, srt: { audio_asset_id: current.id, status: 'running', task_local_id: taskId } }
        }));

        if (taskId) {
          keepGeneratingForWatcher = true;
          startSrtTaskWatcher(current.id, taskId, { switchToSrt });
        } else {
          window.setTimeout(async () => {
            const state = await fetchSrtState(current.id, { quiet: true });
            if (srtStateHasContent(state)) {
              setError('');
              if (switchToSrt) setPlayerView('srt');
              window.dispatchEvent(new CustomEvent('srt:updated', { detail: { audio_asset_id: current.id, srt: state } }));
            }
          }, 3500);
          window.setTimeout(async () => {
            const state = await fetchSrtState(current.id, { quiet: true });
            if (srtStateHasContent(state)) {
              setError('');
              if (switchToSrt) setPlayerView('srt');
              window.dispatchEvent(new CustomEvent('srt:updated', { detail: { audio_asset_id: current.id, srt: state } }));
            }
          }, 9000);
        }
        return;
      }
      setSrtState(result);
      window.dispatchEvent(new CustomEvent('srt:updated', { detail: { audio_asset_id: current.id, srt: result } }));
      if (switchToSrt) setPlayerView('srt');
      setError(t('player.errors.srtGenerated', 'SRT wurde erzeugt.'));
      window.setTimeout(() => setError(''), 2500);
    } catch (err) {
      clearSrtTaskWatcher();
      setError(err?.message || t('player.errors.srtFailed', 'SRT-Erzeugung fehlgeschlagen.'));
    } finally {
      if (!keepGeneratingForWatcher) setSrtGenerating(false);
    }
  }

  function handleSrtButtonClick() {
    if (hasSrt) {
      setPlayerView((value) => value === 'srt' ? 'waveform' : 'srt');
      return;
    }
    void generateCurrentSrt({ switchToSrt: true });
  }

  async function generateCurrentStems() {
    if (!current?.id || actionBusy) return;
    setActionBusy('stems');
    setError(t('player.errors.stemsStarting', 'Stem-Erzeugung wird gestartet…'));
    try {
      const result = await api.archive.generateStems(current.id);
      setError(t('player.errors.stemsStarted', 'Stems gestartet{{suffix}}.', { suffix: result?.task_local_id ? ` (#${result.task_local_id})` : '' }));
    } catch (err) {
      setError(err?.message || t('player.errors.stemsFailed', 'Stem-Erzeugung fehlgeschlagen.'));
    } finally {
      setActionBusy('');
    }
  }

  async function generateCurrentAiCover() {
    if (!current?.id || actionBusy) return;
    setActionBusy('cover');
    setError(t('player.errors.coverStarting', 'KI-Cover wird gestartet…'));
    try {
      const formData = new FormData();
      formData.append('model', 'pro');
      formData.append('note', pickTitle(current));
      const result = await api.archive.generateAiCover(current.id, formData);
      setError(t('player.errors.coverStarted', 'KI-Cover gestartet{{suffix}}.', { suffix: result?.id ? ` (#${result.id})` : result?.task_id ? ` (${result.task_id})` : '' }));
    } catch (err) {
      setError(err?.message || t('player.errors.coverFailed', 'KI-Cover konnte nicht gestartet werden.'));
    } finally {
      setActionBusy('');
    }
  }

  function prepareCurrentExtend() {
    if (!current?.id) return;
    const text = pickPrompt(current) || pickLyrics(current) || '';
    const style = pickStyle(current) || '';
    const rawAudioId = String(current.audio_id || '').trim();
    const hasReusableAudioId = Boolean(rawAudioId && !rawAudioId.toLowerCase().startsWith('manual-'));
    const preparedMode = hasReusableAudioId ? 'extend' : 'upload-extend';
    const continueAtSeconds = duration ? Math.max(30, Math.floor(Number(duration) * 0.72)) : (current.duration_seconds ? Math.max(30, Math.floor(Number(current.duration_seconds) * 0.72)) : 60);
    onPrepareMusic?.({
      title: `${pickTitle(current)} - Extended`,
      prompt: text,
      lyrics: text,
      style,
      operationMode: preparedMode,
      selectedAssetId: String(current.id),
      audioUrl: preparedMode === 'upload-extend' ? String(current.source_url || current.public_url || '') : '',
      continueAt: String(continueAtSeconds),
      customMode: true,
      work_mode: 'extend',
      forceAdvanced: true,
      message: hasReusableAudioId
        ? t('player.errors.extendPrepared', 'Musik erweitern wurde im Generator vorbereitet.')
        : t('player.errors.uploadExtendPrepared', 'Upload And Extend wurde vorbereitet. Prüfe, ob eine extern erreichbare Audio-URL vorhanden ist.')
    });
    setMenuOpen(false);
  }

  return (
    <aside className={`mini-player enhanced-mini-player custom-mini-player mini-player-sidebar-${sidebarMode} ${mobileNavOpen ? 'mini-player-mobile-nav-open' : ''} ${expanded ? 'is-expanded' : 'is-collapsed'}`.trim()}>
      <audio
        ref={audioRef}
        onEnded={ended}
        onPlay={() => setIsPlaying(true)}
        onPause={() => setIsPlaying(false)}
        onLoadedMetadata={onLoadedMetadata}
        onTimeUpdate={onTimeUpdate}
        onError={handleAudioError}
        preload="metadata"
      />

      <div className="mini-player-left">
        <img src={pickCover(current)} alt="Cover" onError={handleCoverImageError} />
        <div className="mini-meta">
          <button type="button" className="mini-title-button" onClick={(event) => { event.preventDefault(); event.stopPropagation(); onOpenDetails?.(current); }} title={t('player.openDetails', 'Songdetails öffnen')}>{currentDisplayTitle}</button>
          <span>{operation} · {currentIndex + 1}/{queue.length} · {formatDuration(duration || current.duration_seconds)}</span>
          {error && <small className="warning-text">{error}</small>}
        </div>
      </div>

      <div className="mini-player-mobile-controls">
        <button type="button" className="player-round" onClick={restartCurrent} title={t('player.restartCurrent', 'Aktuellen Song von vorn abspielen')}><RotateCcw size={18} /></button>
        <button type="button" className="player-main-play" onClick={togglePlay} title={isPlaying ? t('player.pause', 'Pause') : t('player.play', 'Abspielen')}>{isPlaying ? <Pause size={20} /> : <Play size={20} />}</button>
        <button type="button" className="player-mobile-expand" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded} title={expanded ? t('player.collapse', 'Player einklappen') : t('player.expand', 'Player erweitern')}>{expanded ? <ChevronDown size={18} /> : <ChevronUp size={18} />}</button>
        <button type="button" className="player-close-button player-close-mobile" onClick={closePlayer} aria-label={t('player.close', 'Player schließen')} title={t('player.close', 'Player schließen')}><X size={18} /></button>
      </div>

      <div className="custom-player-shell">
        <div className="custom-player-controls">
          <button type="button" className="player-round" onClick={previous} disabled={!canPrevious} title={t('player.previous', 'Vorheriger Track')}><SkipBack size={18} /></button>
          <button type="button" className="player-round" onClick={restartCurrent} title={t('player.restartCurrent', 'Aktuellen Song von vorn abspielen')}><RotateCcw size={18} /></button>
          <button type="button" className="player-round" onClick={() => seekRelative(-10)} title={t('player.seekBackward10', '10 Sekunden zurück')} aria-label={t('player.seekBackward10', '10 Sekunden zurück')}><Rewind size={18} /></button>
          <button type="button" className="player-main-play" onClick={togglePlay} title={isPlaying ? t('player.pause', 'Pause') : t('player.play', 'Abspielen')}>{isPlaying ? <Pause size={22} /> : <Play size={22} />}</button>
          <button type="button" className="player-round" onClick={() => seekRelative(10)} title={t('player.seekForward10', '10 Sekunden vor')} aria-label={t('player.seekForward10', '10 Sekunden vor')}><FastForward size={18} /></button>
          <button type="button" className="player-round" onClick={next} disabled={!canNext} title={t('player.next', 'Nächster Track')}><SkipForward size={18} /></button>
          <div className="mini-player-view-toolbar mini-player-view-toolbar-inline" aria-label={t('player.display', 'Player-Anzeige')}>
            <button type="button" className={playerView === 'waveform' ? 'active' : ''} onClick={() => setPlayerView('waveform')} title={t('player.showWaveform', 'Waveform anzeigen')}><Waves size={14} /> Waveform</button>
            <button type="button" className={playerView === 'srt' ? 'active' : ''} onClick={handleSrtButtonClick} disabled={srtLoading || srtGenerating} title={hasSrt ? t('player.showLiveSrt', 'Live-SRT anzeigen') : t('player.generateSrt', 'SRT erzeugen')}><Captions size={14} /> {srtGenerating ? 'SRT…' : 'SRT'}</button>
          </div>

          <span className="custom-time current-time">{formatClock(currentTime)}</span>
          <div className="custom-progress" ref={progressRef} onClick={seekFromEvent} role="slider" aria-label={t('player.position', 'Position')} aria-valuemin="0" aria-valuemax="100" aria-valuenow={Math.round(progress)}>
            <div className="custom-progress-track">
              <div className="custom-progress-fill" style={{ width: `${progress}%` }} />
              <span className="custom-progress-thumb" style={{ left: `${progress}%` }} />
            </div>
          </div>
          <span className="custom-time duration-time">{formatClock(duration || current.duration_seconds)}</span>
        </div>
        <div className={`mini-player-visual ${playerView === 'srt' && hasSrt ? 'is-srt' : 'is-waveform'}`}>
          {playerView === 'srt' && hasSrt ? (
            <div className="mini-player-srt-live" style={{ '--srt-live-font-size': displayedSrtFontSize }}>
              <span className="mini-player-srt-label">{t('player.liveSrt', 'Live-SRT')}</span>
              <strong title={displayedSrtText}>{displayedSrtText || '\u00a0'}</strong>
              {displayedSrtSegment && <small>{formatClock(displayedSrtSegment.start)} → {formatClock(displayedSrtSegment.end)}</small>}
            </div>
          ) : (
            <Waveform asset={current} audioRef={audioRef} currentTime={currentTime} durationSeconds={duration || current.duration_seconds} />
          )}
        </div>
      </div>

      <div className="mini-player-right custom-player-actions">
        <button type="button" className={currentFavorite ? 'active favorite-mini-button is-favorite' : 'favorite-mini-button'} onClick={toggleCurrentFavorite} disabled={favoriteSaving} title={currentFavorite ? t('player.removeFavorite', 'Favorit entfernen') : t('player.saveFavorite', 'Als Favorit speichern')}><ThumbsUp size={18} fill={currentFavorite ? 'currentColor' : 'none'} /></button>
        <button type="button" className={loop ? 'active' : ''} onClick={() => onLoopChange(!loop)} title={t('player.loop', 'Loop')}><Repeat size={18} /></button>
        <div className="player-menu-wrap">
          <button type="button" onClick={() => setMenuOpen(!menuOpen)} title={t('player.options', 'Optionen')}><MoreVertical size={18} /></button>
          {menuOpen && (
            <div className="player-menu">
              <button type="button" onClick={() => { setMenuOpen(false); onOpenDetails?.(current); }}><FileText size={15} /> {t('player.openDetails', 'Songdetails öffnen')}</button>
              <button type="button" onClick={toggleCurrentFavorite} disabled={favoriteSaving}><ThumbsUp size={15} fill={currentFavorite ? 'currentColor' : 'none'} /> {currentFavorite ? t('player.removeFavorite', 'Favorit entfernen') : t('player.favorite', 'Favorit')}</button>
              <button type="button" onClick={() => { setMenuOpen(false); hasSrt ? setPlayerView('srt') : void generateCurrentSrt({ switchToSrt: true }); }} disabled={srtLoading || srtGenerating}><Captions size={15} /> {hasSrt ? t('player.showSrt', 'SRT anzeigen') : srtGenerating ? t('player.srtRunning', 'SRT läuft…') : t('player.generateSrt', 'SRT erzeugen')}</button>
              {hasSrt && <a href={api.archive.srtDownloadUrl(current.id)}><Download size={15} /> {t('player.downloadSrt', 'SRT herunterladen')}</a>}
              <button type="button" onClick={() => { setMenuOpen(false); void generateCurrentAiCover(); }} disabled={Boolean(actionBusy)}><ImageIcon size={15} /> {actionBusy === 'cover' ? t('player.aiCoverRunning', 'KI-Cover läuft…') : t('player.createAiCover', 'KI Cover erzeugen')}</button>
              <button type="button" onClick={() => { setMenuOpen(false); void generateCurrentStems(); }} disabled={Boolean(actionBusy)}><Headphones size={15} /> {actionBusy === 'stems' ? t('player.stemsRunning', 'Stems laufen…') : t('player.createStems', 'Stems erzeugen')}</button>
              <button type="button" onClick={prepareCurrentExtend}><Sparkles size={15} /> {t('player.prepareExtend', 'Extend vorbereiten')}</button>
              <a href={api.archive.assetBundleUrl(current.id)}><Download size={15} /> {t('player.downloadAudioPackage', 'Audio-Paket ZIP')}</a>
              <a href={api.archive.downloadUrl(current.id)}><Download size={15} /> {t('player.downloadAudio', 'Audio herunterladen')}</a>
              {current.source_url && <a href={current.source_url} target="_blank" rel="noreferrer"><ExternalLink size={15} /> {t('player.openSource', 'Quelle öffnen')}</a>}
            </div>
          )}
        </div>
        <a className="icon-button player-download-primary" href={api.archive.downloadUrl(current.id)} title={t('player.download', 'Download')}><Download size={17} /></a>
        <button type="button" className="player-close-button player-close-desktop" onClick={closePlayer} aria-label={t('player.close', 'Player schließen')} title={t('player.close', 'Player schließen')}><X size={18} /></button>
        <div className="player-volume-row">
          <button type="button" onClick={() => setMuted(!muted)} title={muted ? t('player.enableSound', 'Ton aktivieren') : t('player.mute', 'Stumm')}>{muted ? <VolumeX size={18} /> : <Volume2 size={18} />}</button>
          <input className="custom-volume" type="range" min="0" max="100" value={muted ? 0 : Math.round(volume * 100)} onChange={changeVolume} aria-label={t('player.volume', 'Lautstärke')} style={{ '--volume-fill': `${muted ? 0 : Math.round(volume * 100)}%` }} />
        </div>
      </div>
    </aside>
  );
}
