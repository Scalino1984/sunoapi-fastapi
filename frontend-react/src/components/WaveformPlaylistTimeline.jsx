import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ClipInteractionProvider,
  Waveform,
  WaveformPlaylistProvider,
  usePlaylistControls,
} from '@waveform-playlist/browser';
import { createClipFromSeconds, createTrack } from '@waveform-playlist/core';
import { Bot, Loader2 } from 'lucide-react';

function safeNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, safeNumber(value, min)));
}

function clipDuration(clip) {
  return Math.max(0, safeNumber(clip?.source_end) - safeNumber(clip?.source_start));
}

function secondsToClock(value, withMs = false) {
  const total = Math.max(0, safeNumber(value));
  const minutes = Math.floor(total / 60);
  const seconds = Math.floor(total % 60);
  if (!withMs) return `${minutes}:${String(seconds).padStart(2, '0')}`;
  const tenths = Math.floor((total - Math.floor(total)) * 10);
  return `${minutes}:${String(seconds).padStart(2, '0')}.${tenths}`;
}

function gainDbToLinear(db) {
  return Math.max(0, Math.pow(10, safeNumber(db) / 20));
}

function sectionLabel(segment) {
  return segment?.displayLabel || segment?.label || segment?.kind || segment?.type || 'Abschnitt';
}

function normalizeSections(beatgrid, duration) {
  const source = Array.isArray(beatgrid?.snapped_segments)
    ? beatgrid.snapped_segments
    : Array.isArray(beatgrid?.segments)
      ? beatgrid.segments
      : [];
  const limit = Math.max(0.1, safeNumber(duration, 1));
  return source
    .map((segment, index) => {
      const start = safeNumber(segment.start ?? segment.start_sec ?? segment.time_start_sec, 0);
      const end = safeNumber(segment.end ?? segment.end_sec ?? segment.time_end_sec, start);
      return {
        id: segment.id || `${sectionLabel(segment)}-${index}-${start}`,
        label: sectionLabel(segment),
        start: clamp(start, 0, limit),
        end: clamp(end, 0, limit),
      };
    })
    .filter((segment) => segment.end - segment.start > 0.05)
    .sort((a, b) => a.start - b.start);
}

function sectionClassName(label) {
  const value = String(label || '').toLowerCase();
  if (value.includes('chorus') || value.includes('hook') || value.includes('refrain')) return 'chorus';
  if (value.includes('verse') || value.includes('strophe')) return 'verse';
  if (value.includes('bridge')) return 'bridge';
  if (value.includes('intro') || value.includes('outro') || value.includes('break')) return 'edge';
  return 'section';
}

const annotationIntegration = {
  parseAeneas: (data) => data,
  serializeAeneas: (annotation) => annotation,
  AnnotationText: () => null,
  AnnotationBoxesWrapper: ({ children, height = 28, width }) => (
    <div className="suno-waveplaylist-section-boxes" style={{ height, width: width || '100%' }}>{children}</div>
  ),
  AnnotationBox: ({ annotationId, startPosition, endPosition, label, onClick, isActive }) => (
    <button
      type="button"
      className={`suno-waveplaylist-section-box ${sectionClassName(label)}${isActive ? ' active' : ''}`}
      style={{ left: `${Math.round(startPosition)}px`, width: `${Math.max(24, Math.round(endPosition - startPosition))}px` }}
      onClick={onClick}
      title={`${label || annotationId}`}
    >
      {label || annotationId}
    </button>
  ),
  ContinuousPlayCheckbox: () => null,
  LinkEndpointsCheckbox: () => null,
  EditableCheckbox: () => null,
  DownloadAnnotationsButton: () => null,
};

const WAVEFORM_PLAYLIST_ZOOM_LEVELS = [16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072];

const playlistTheme = {
  waveformDrawMode: 'normal',
  playlistBackgroundColor: '#020617',
  backgroundColor: '#020617',
  surfaceColor: '#071120',
  borderColor: 'rgba(34, 211, 238, .18)',
  waveOutlineColor: '#020617',
  waveFillColor: '#22d3ee',
  waveProgressColor: 'rgba(217, 70, 239, .18)',
  selectedWaveOutlineColor: '#071120',
  selectedWaveFillColor: '#67e8f9',
  selectedTrackControlsBackground: '#101a2d',
  selectedTrackBackground: 'rgba(14, 165, 233, .08)',
  timeColor: '#cbd5e1',
  timescaleBackgroundColor: '#0b1220',
  playheadColor: '#67e8f9',
  selectionColor: 'rgba(34, 211, 238, .16)',
  loopRegionColor: 'rgba(124, 58, 237, .18)',
  loopMarkerColor: '#a78bfa',
  clipHeaderBackgroundColor: '#7c3aed',
  clipHeaderBorderColor: 'rgba(255,255,255,.18)',
  clipHeaderTextColor: '#f8fafc',
  clipHeaderFontFamily: 'Inter, system-ui, sans-serif',
  selectedClipHeaderBackgroundColor: '#0891b2',
  fadeOverlayColor: 'rgba(255,255,255,.18)',
  textColor: '#e2e8f0',
  textColorMuted: '#94a3b8',
  inputBackground: '#020617',
  inputBorder: 'rgba(148, 163, 184, .24)',
  inputText: '#f8fafc',
  inputPlaceholder: '#64748b',
  inputFocusBorder: '#22d3ee',
  buttonBackground: '#111827',
  buttonText: '#f8fafc',
  buttonBorder: 'rgba(148, 163, 184, .20)',
  buttonHoverBackground: '#1f2937',
  sliderTrackColor: '#1f2937',
  sliderThumbColor: '#67e8f9',
  annotationBoxBackground: 'rgba(124, 58, 237, .88)',
  annotationBoxActiveBackground: 'rgba(14, 165, 233, .90)',
  annotationBoxHoverBackground: 'rgba(168, 85, 247, .96)',
  annotationBoxBorder: 'rgba(255,255,255,.16)',
  annotationBoxActiveBorder: '#67e8f9',
  annotationLabelColor: '#f8fafc',
  annotationResizeHandleColor: '#c4b5fd',
  annotationResizeHandleActiveColor: '#67e8f9',
  annotationTextItemHoverBackground: 'rgba(15,23,42,.80)',
  pianoRollNoteColor: '#22d3ee',
  pianoRollSelectedNoteColor: '#f472b6',
  pianoRollBackgroundColor: '#020617',
  borderRadius: '14px',
  fontFamily: 'Inter, system-ui, sans-serif',
  fontSize: '.78rem',
  fontSizeSmall: '.7rem',
};

function makeTrackControls(track, trackIndex) {
  const number = trackIndex + 1;
  return (
    <div className="suno-waveplaylist-track-control">
      <div className="suno-waveplaylist-track-title">
        <strong>{track?.name || `Spur ${number}`}</strong>
        <span>{track?.clips?.length || 0} Clips</span>
      </div>
      <div className="suno-waveplaylist-track-buttons" aria-label={`Spur ${number} Steuerung`}>
        <span>M</span>
        <span>S</span>
      </div>
      <div className="suno-waveplaylist-track-meter"><i /></div>
    </div>
  );
}

function PlaylistSync({ currentTime, onSeek, onTimeUpdate }) {
  const controls = usePlaylistControls();
  const lastExternalSeekRef = useRef(-1);

  useEffect(() => {
    const next = safeNumber(currentTime, 0);
    if (Math.abs(next - lastExternalSeekRef.current) < 0.08) return;
    lastExternalSeekRef.current = next;
    controls.seekTo(next);
  }, [controls, currentTime]);

  useEffect(() => {
    const handlePointerUp = () => {
      if (typeof controls.getPlaybackTime === 'function') {
        const next = safeNumber(controls.getPlaybackTime(), currentTime);
        onSeek?.(next);
        onTimeUpdate?.(next);
      }
    };
    window.addEventListener('pointerup', handlePointerUp, { passive: true });
    return () => window.removeEventListener('pointerup', handlePointerUp);
  }, [controls, currentTime, onSeek, onTimeUpdate]);

  return null;
}

export function WaveformPlaylistTimeline({
  arrangement,
  tracks,
  audioUrl,
  assetTitle,
  beatgrid,
  timelineDuration,
  currentTime,
  selectedClipId,
  timelineZoomOption,
  snapEnabled,
  snapUnit,
  onSeek,
  onTimeUpdate,
  onPlaybackChange,
  onSelectClip,
  onTimelineClipsChange,
  onClipAi,
  clipAiPanel,
  closeClipAiPanel,
  setClipAiPromptFor,
  runClipAiCommand,
}) {
  const shellRef = useRef(null);
  const scrollRef = useRef(null);
  const changeTimerRef = useRef(null);
  const lastEmittedSignatureRef = useRef('');
  const [audioBuffer, setAudioBuffer] = useState(null);
  const [loadError, setLoadError] = useState('');
  const [loading, setLoading] = useState(false);
  const [frameWidth, setFrameWidth] = useState(0);
  const [scrollLeft, setScrollLeft] = useState(0);
  const [zoomLevel, setZoomLevel] = useState(1);

  const duration = Math.max(0.1, safeNumber(timelineDuration || arrangement?.duration_seconds, 1));
  const waveHeight = Math.max(64, safeNumber(timelineZoomOption?.trackHeight, 122) - 48);
  const controlsWidth = 190;
  const sampleRate = audioBuffer?.sampleRate || 48000;
  const fitWidth = Math.max(420, frameWidth - controlsWidth - 18);
  const fitSamplesPerPixel = Math.max(64, Math.ceil((duration * sampleRate) / fitWidth));
  const samplesPerPixel = Math.max(16, Math.round(fitSamplesPerPixel / zoomLevel));
  const playlistZoomLevels = useMemo(() => Array.from(new Set([
    ...WAVEFORM_PLAYLIST_ZOOM_LEVELS,
    fitSamplesPerPixel,
    samplesPerPixel,
  ])).filter((value) => Number.isFinite(value) && value > 0).sort((a, b) => a - b), [fitSamplesPerPixel, samplesPerPixel]);
  const zoomPercent = Math.round(zoomLevel * 100);
  const sourceDuration = Math.max(duration, safeNumber(audioBuffer?.duration, duration));
  const sections = useMemo(() => normalizeSections(beatgrid, sourceDuration), [beatgrid, sourceDuration]);

  const clipById = useMemo(() => new Map((arrangement?.clips || []).map((clip) => [clip.id, clip])), [arrangement]);
  const selectedClip = selectedClipId ? clipById.get(selectedClipId) : null;

  useEffect(() => {
    let cancelled = false;
    setAudioBuffer(null);
    setLoadError('');
    if (!audioUrl) return undefined;
    setLoading(true);
    const context = new AudioContext({ sampleRate: 48000 });
    fetch(audioUrl)
      .then((response) => {
        if (!response.ok) throw new Error(`Audio konnte nicht geladen werden (${response.status}).`);
        return response.arrayBuffer();
      })
      .then((buffer) => context.decodeAudioData(buffer))
      .then((decoded) => {
        if (!cancelled) setAudioBuffer(decoded);
      })
      .catch((error) => {
        if (!cancelled) setLoadError(error?.message || 'Audio konnte nicht dekodiert werden.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
        context.close?.().catch?.(() => {});
      });
    return () => {
      cancelled = true;
      context.close?.().catch?.(() => {});
    };
  }, [audioUrl]);

  useEffect(() => {
    const shell = shellRef.current;
    if (!shell || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver((entries) => setFrameWidth(entries?.[0]?.contentRect?.width || shell.getBoundingClientRect().width || 0));
    observer.observe(shell);
    setFrameWidth(shell.getBoundingClientRect().width || 0);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const shell = shellRef.current;
    if (!shell) return undefined;
    let cleanup = null;
    let cancelled = false;
    let attempts = 0;
    const attach = () => {
      if (cancelled) return;
      const scroller = shell.querySelector('[data-playlist-state]');
      if (!scroller) {
        attempts += 1;
        if (attempts < 50) window.setTimeout(attach, 100);
        return;
      }
      scrollRef.current = scroller;
      const update = () => setScrollLeft(scroller.scrollLeft || 0);
      scroller.addEventListener('scroll', update, { passive: true });
      update();
      cleanup = () => scroller.removeEventListener('scroll', update);
    };
    attach();
    return () => { cancelled = true; cleanup?.(); };
  }, [audioBuffer, samplesPerPixel]);

  const playlistTracks = useMemo(() => {
    if (!audioBuffer || !arrangement) return [];
    return (tracks || []).map((track, index) => {
      const clips = (arrangement.clips || [])
        .filter((clip) => clip.track_id === track.id)
        .map((clip) => {
          const start = Math.max(0, safeNumber(clip.timeline_start));
          const offset = clamp(safeNumber(clip.source_start), 0, sourceDuration);
          const end = clamp(safeNumber(clip.source_end), offset + 0.05, sourceDuration);
          const durationSeconds = Math.max(0.05, end - offset);
          const created = createClipFromSeconds({
            audioBuffer,
            startTime: start,
            offset,
            duration: durationSeconds,
            gain: gainDbToLinear(clip.gain_db),
            name: clip.label || assetTitle || 'Clip',
            color: clip.id === selectedClipId ? '#0891b2' : '#7c3aed',
            fadeIn: safeNumber(clip.fade_in) > 0 ? { duration: safeNumber(clip.fade_in), type: 'linear' } : undefined,
            fadeOut: safeNumber(clip.fade_out) > 0 ? { duration: safeNumber(clip.fade_out), type: 'linear' } : undefined,
          });
          created.id = clip.id;
          created.__sunoTrackId = track.id;
          return created;
        });
      const createdTrack = createTrack({
        name: track.name,
        clips,
        color: index === 0 ? '#22d3ee' : '#7c3aed',
        height: Math.max(80, waveHeight * Math.max(1, audioBuffer.numberOfChannels || 1) + 28),
      });
      createdTrack.id = track.id;
      return createdTrack;
    });
  }, [arrangement, assetTitle, audioBuffer, selectedClipId, sourceDuration, tracks, waveHeight]);

  const clipSectionOverlays = useMemo(() => {
    if (!arrangement?.clips?.length || !sections.length || !audioBuffer) return [];
    const channelCount = Math.max(1, Math.min(2, audioBuffer.numberOfChannels || 1));
    const trackHeight = waveHeight * channelCount + 22;
    const result = [];
    (arrangement.clips || []).forEach((clip) => {
      const trackIndex = Math.max(0, (tracks || []).findIndex((track) => track.id === clip.track_id));
      const clipStart = safeNumber(clip.timeline_start);
      const sourceStart = safeNumber(clip.source_start);
      const sourceEnd = safeNumber(clip.source_end);
      sections.forEach((section) => {
        const overlapStart = Math.max(sourceStart, section.start);
        const overlapEnd = Math.min(sourceEnd, section.end);
        if (overlapEnd - overlapStart <= 0.05) return;
        const timelineStart = clipStart + (overlapStart - sourceStart);
        const timelineEnd = clipStart + (overlapEnd - sourceStart);
        const leftPx = controlsWidth + (timelineStart * sampleRate / samplesPerPixel) - scrollLeft;
        const widthPx = (timelineEnd - timelineStart) * sampleRate / samplesPerPixel;
        if (leftPx + widthPx < controlsWidth || leftPx > frameWidth + 200) return;
        result.push({
          id: `${clip.id}-${section.id}-${timelineStart.toFixed(2)}`,
          label: section.label,
          className: sectionClassName(section.label),
          style: {
            left: `${Math.round(leftPx)}px`,
            top: `${Math.round(31 + trackIndex * trackHeight + 24)}px`,
            width: `${Math.max(28, Math.round(widthPx))}px`,
          },
        });
      });
    });
    return result;
  }, [arrangement, audioBuffer, controlsWidth, frameWidth, sampleRate, samplesPerPixel, scrollLeft, sections, tracks, waveHeight]);

  const handleTracksChange = useCallback((changedTracks) => {
    if (!changedTracks?.length || !arrangement?.clips?.length) return;
    const nextClips = [];
    changedTracks.forEach((track) => {
      (track.clips || []).forEach((clip) => {
        const original = clipById.get(clip.id);
        if (!original) return;
        const rate = safeNumber(clip.sampleRate, sampleRate);
        const start = Math.max(0, safeNumber(clip.startSample) / rate);
        const offset = Math.max(0, safeNumber(clip.offsetSamples) / rate);
        const dur = Math.max(0.05, safeNumber(clip.durationSamples) / rate);
        nextClips.push({
          ...original,
          track_id: track.id || original.track_id,
          timeline_start: start,
          source_start: offset,
          source_end: Math.min(sourceDuration, offset + dur),
          gain_db: original.gain_db,
        });
      });
    });
    if (!nextClips.length) return;
    const signature = nextClips
      .map((clip) => `${clip.id}:${clip.track_id}:${clip.timeline_start.toFixed(3)}:${clip.source_start.toFixed(3)}:${clip.source_end.toFixed(3)}`)
      .sort()
      .join('|');
    if (signature === lastEmittedSignatureRef.current) return;
    window.clearTimeout(changeTimerRef.current);
    changeTimerRef.current = window.setTimeout(() => {
      lastEmittedSignatureRef.current = signature;
      onTimelineClipsChange?.(nextClips, selectedClipId || nextClips[0]?.id || '');
    }, 140);
  }, [arrangement, clipById, onTimelineClipsChange, sampleRate, selectedClipId, sourceDuration]);

  const handleTimelinePointerDownCapture = useCallback((event) => {
    const scroller = scrollRef.current || shellRef.current?.querySelector?.('[data-playlist-state]');
    if (!scroller || !arrangement?.clips?.length || !audioBuffer) return;
    const rect = scroller.getBoundingClientRect();
    if (event.clientX < rect.left + controlsWidth || event.clientX > rect.right || event.clientY < rect.top) return;
    const channelCount = Math.max(1, Math.min(2, audioBuffer.numberOfChannels || 1));
    const trackHeight = waveHeight * channelCount + 22;
    const x = event.clientX - rect.left - controlsWidth + (scroller.scrollLeft || 0);
    const y = event.clientY - rect.top - 31;
    const time = Math.max(0, (x * samplesPerPixel) / sampleRate);
    const trackIndex = Math.max(0, Math.floor(y / trackHeight));
    const track = tracks?.[trackIndex];
    const hitClip = (arrangement.clips || []).find((clip) => {
      if (track && clip.track_id !== track.id) return false;
      const start = safeNumber(clip.timeline_start);
      const end = start + clipDuration(clip);
      return time >= start && time <= end;
    });
    if (hitClip) onSelectClip?.(hitClip.id);
    onSeek?.(time);
  }, [arrangement, audioBuffer, controlsWidth, onSeek, onSelectClip, sampleRate, samplesPerPixel, tracks, waveHeight]);

  const selectedClipPosition = useMemo(() => {
    if (!selectedClip || !audioBuffer) return null;
    const trackIndex = Math.max(0, (tracks || []).findIndex((track) => track.id === selectedClip.track_id));
    const channelCount = Math.max(1, Math.min(2, audioBuffer.numberOfChannels || 1));
    const trackHeight = waveHeight * channelCount + 22;
    const left = controlsWidth + ((safeNumber(selectedClip.timeline_start) + clipDuration(selectedClip)) * sampleRate / samplesPerPixel) - scrollLeft;
    const top = 31 + trackIndex * trackHeight + 30;
    return {
      left: `${Math.round(clamp(left - 58, controlsWidth + 8, Math.max(controlsWidth + 8, frameWidth - 80)))}px`,
      top: `${Math.round(Math.max(38, top))}px`,
    };
  }, [audioBuffer, controlsWidth, frameWidth, sampleRate, samplesPerPixel, scrollLeft, selectedClip, tracks, waveHeight]);

  const selectedPanelPosition = useMemo(() => {
    if (!selectedClipPosition || !selectedClip) return null;
    const startLeft = controlsWidth + (safeNumber(selectedClip.timeline_start) * sampleRate / samplesPerPixel) - scrollLeft;
    return {
      left: `${Math.round(clamp(startLeft + 12, controlsWidth + 8, Math.max(controlsWidth + 8, frameWidth - 540)))}px`,
      top: `${Math.round(safeNumber(String(selectedClipPosition.top).replace('px', ''), 48) + 32)}px`,
    };
  }, [controlsWidth, frameWidth, sampleRate, samplesPerPixel, scrollLeft, selectedClip, selectedClipPosition]);

  const providerKey = `${audioUrl || 'no-audio'}:${samplesPerPixel}:${waveHeight}:${audioBuffer?.duration || 0}:${playlistTracks.map((track) => `${track.id}:${track.clips.map((clip) => `${clip.id}:${clip.startSample}:${clip.offsetSamples}:${clip.durationSamples}`).join(',')}`).join('|')}`;

  return (
    <section className="suno-waveplaylist-shell panel" aria-label="Waveform Playlist DAW Timeline" ref={shellRef}>
      <div className="suno-waveplaylist-topline">
        <div>
          <span className="daw-kicker">Timeline Engine</span>
          <strong>@waveform-playlist/browser</strong>
        </div>
        <div className="suno-waveplaylist-status">
          <span>{secondsToClock(currentTime, true)} / {secondsToClock(duration, true)}</span>
          <span>{Math.round(safeNumber(arrangement?.bpm || beatgrid?.bpm || beatgrid?.tempo_bpm, 0)) || 'frei'} BPM</span>
          <span>{snapEnabled ? `Snap ${snapUnit || 'beat'}` : 'Snap aus'}</span>
          <div className="suno-waveplaylist-zoom" aria-label="Timeline-Zoom">
            <button type="button" onClick={() => setZoomLevel((value) => Math.max(1, value / 2))} disabled={zoomLevel <= 1}>−</button>
            <button type="button" onClick={() => setZoomLevel(1)}>Gesamt</button>
            <strong>{zoomPercent}%</strong>
            <button type="button" onClick={() => setZoomLevel((value) => Math.min(32, value * 2))} disabled={zoomLevel >= 32}>+</button>
          </div>
        </div>
      </div>

      <div className="suno-waveplaylist-frame" onPointerDownCapture={handleTimelinePointerDownCapture}>
        {loading && <div className="suno-waveplaylist-loading"><Loader2 className="spin-icon" size={16} /> Audio wird für die Timeline dekodiert …</div>}
        {loadError && <div className="suno-waveplaylist-error">{loadError}</div>}
        {!loading && !loadError && audioBuffer && (
          <WaveformPlaylistProvider
            key={providerKey}
            tracks={playlistTracks}
            timescale
            mono={false}
            waveHeight={waveHeight}
            samplesPerPixel={samplesPerPixel}
            zoomLevels={playlistZoomLevels}
            controls={{ show: true, width: controlsWidth }}
            onTracksChange={handleTracksChange}
            onReady={() => onPlaybackChange?.(false)}
            onError={(error) => setLoadError(error?.message || 'Waveform Playlist konnte nicht initialisiert werden.')}
            theme={playlistTheme}
            barWidth={2}
            barGap={1}
            fillViewport
            indefinitePlayback
            sampleRate={sampleRate}
          >
            <PlaylistSync currentTime={currentTime} onSeek={onSeek} onTimeUpdate={onTimeUpdate} />
            <ClipInteractionProvider snap={Boolean(snapEnabled)} touchOptimized>
              <Waveform
                className="suno-waveplaylist-view"
                showClipHeaders
                interactiveClips
                showFades
                renderAnnotationItem={() => null}
                renderTrackControls={(trackIndex) => makeTrackControls(playlistTracks[trackIndex], trackIndex)}
              />
            </ClipInteractionProvider>
          </WaveformPlaylistProvider>
        )}
        {!loading && !loadError && audioBuffer && clipSectionOverlays.length > 0 && (
          <div className="suno-waveplaylist-section-overlay" aria-hidden="true">
            {clipSectionOverlays.map((section) => (
              <span
                key={section.id}
                className={`suno-waveplaylist-clip-section ${section.className}`}
                style={section.style}
                title={section.label}
              >
                {section.label}
              </span>
            ))}
          </div>
        )}
        {selectedClip && selectedClipPosition && (
          <button
            type="button"
            className="suno-waveplaylist-clip-ai-anchor"
            style={selectedClipPosition}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation();
              onClipAi?.(event, selectedClip);
            }}
            title="KI-Befehl für diesen Clip"
          >
            <Bot size={13} /> KI
          </button>
        )}
        {selectedClipId && clipAiPanel?.clipId === selectedClipId && (
          <form
            className="daw-clip-ai-popover suno-waveplaylist-ai-panel"
            style={selectedPanelPosition || undefined}
            onSubmit={(event) => runClipAiCommand?.(event, clipById.get(selectedClipId))}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => event.stopPropagation()}
            onKeyDown={(event) => event.stopPropagation()}
            onKeyUp={(event) => event.stopPropagation()}
          >
            <div className="daw-clip-ai-head">
              <div>
                <span className="daw-kicker">Clip-KI</span>
                <strong>{clipById.get(selectedClipId)?.label || 'Clip bearbeiten'}</strong>
              </div>
              <button type="button" className="ghost" onClick={closeClipAiPanel} aria-label="Clip-KI schließen">×</button>
            </div>
            <input
              value={clipAiPanel.prompt || ''}
              onChange={(event) => setClipAiPromptFor?.(clipById.get(selectedClipId), event.target.value)}
              placeholder="z. B. erste Hook doppeln, Anfang 8s kürzen, Fade-in 3s"
              aria-label="KI-Befehl für diesen Clip"
              autoFocus
            />
            <div className="daw-clip-ai-examples">
              <button type="button" onClick={() => setClipAiPromptFor?.(clipById.get(selectedClipId), 'Fade-in 3s')}>Fade-in 3s</button>
              <button type="button" onClick={() => setClipAiPromptFor?.(clipById.get(selectedClipId), 'Anfang um 8s kürzen')}>Anfang kürzen</button>
              <button type="button" onClick={() => setClipAiPromptFor?.(clipById.get(selectedClipId), 'Clip um 3 dB leiser machen')}>-3 dB</button>
              <button type="submit" className="primary"><Bot size={14} /> Planen</button>
            </div>
          </form>
        )}
      </div>

      <div className="suno-waveplaylist-foot">
        <span>Abschnitte liegen als Clip-Overlay direkt auf der Audio-Waveform.</span>
        <span>Drag/Trim laufen über Waveform Playlist; Speichern und Render bleiben über FastAPI.</span>
      </div>
    </section>
  );
}
