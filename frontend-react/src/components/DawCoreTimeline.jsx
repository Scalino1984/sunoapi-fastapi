import React, { useEffect, useMemo, useRef, useState } from 'react';
import '@dawcore/components';
import { NativePlayoutAdapter } from '@dawcore/transport';
import { Bot, Loader2 } from 'lucide-react';

function safeNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
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
        start: Math.max(0, Math.min(limit, start)),
        end: Math.max(0, Math.min(limit, end)),
      };
    })
    .filter((segment) => segment.end - segment.start > 0.05)
    .sort((a, b) => a.start - b.start);
}

function snapToMode(snapUnit) {
  if (snapUnit === 'bar') return 'bar';
  if (snapUnit === 'beat') return 'beat';
  if (snapUnit === 'half') return '1/2';
  if (snapUnit === 'quarter') return '1/4';
  return 'off';
}

function clampNumber(value, min, max) {
  return Math.max(min, Math.min(max, safeNumber(value, min)));
}

function sampleDeltaToSeconds(eventDetail, editorElement) {
  const sampleRate = Math.max(
    1,
    safeNumber(editorElement?.audioContext?.sampleRate),
    safeNumber(editorElement?.adapter?.audioContext?.sampleRate),
    safeNumber(editorElement?.adapter?.context?.sampleRate),
    48000,
  );
  return safeNumber(eventDetail?.deltaSamples) / sampleRate;
}

export function DawCoreTimeline({
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
  onReady,
  onSeek,
  onTimeUpdate,
  onPlaybackChange,
  onSelectClip,
  onClipMove,
  onClipTrim,
  onClipSplit,
  onClipAi,
  clipAiPanel,
  closeClipAiPanel,
  setClipAiPromptFor,
  runClipAiCommand,
}) {
  const editorRef = useRef(null);
  const frameRef = useRef(null);
  const adapterRef = useRef(null);
  const audioContextRef = useRef(null);
  const lastExternalSeekRef = useRef(-1);
  const [frameWidth, setFrameWidth] = useState(0);
  const [editorScroll, setEditorScroll] = useState({ left: 0, top: 0 });
  const [timelineScale, setTimelineScale] = useState(1);
  const editorId = 'suno-dawcore-editor';
  const TRACK_CONTROL_WIDTH = 176;
  const RULER_HEIGHT = 30;
  const AUDIO_SAMPLE_RATE = 48000;
  const waveHeight = Math.max(78, safeNumber(timelineZoomOption?.trackHeight, 122) - 34);
  const duration = Math.max(0.1, safeNumber(timelineDuration, 1));
  const usableTimelineWidth = Math.max(360, safeNumber(frameWidth) - TRACK_CONTROL_WIDTH - 18);
  const fitSamplesPerPixel = Math.max(64, (duration * AUDIO_SAMPLE_RATE) / usableTimelineWidth);
  const samplesPerPixel = Math.max(64, Math.round(fitSamplesPerPixel / Math.max(1, timelineScale)));
  const timelinePixelWidth = Math.max(usableTimelineWidth, (duration * AUDIO_SAMPLE_RATE) / samplesPerPixel);
  const zoomPercent = Math.round(Math.max(1, timelineScale) * 100);
  const sections = useMemo(() => normalizeSections(beatgrid, duration), [beatgrid, duration]);
  const clipMap = useMemo(() => new Map((arrangement?.clips || []).map((clip) => [clip.id, clip])), [arrangement]);
  const bpm = Math.max(20, Math.min(300, safeNumber(arrangement?.bpm || beatgrid?.bpm || beatgrid?.tempo_bpm, 120)));
  const editorKey = useMemo(() => {
    const clipSignature = (arrangement?.clips || []).map((clip) => [
      clip.id,
      clip.track_id,
      safeNumber(clip.timeline_start).toFixed(3),
      safeNumber(clip.source_start).toFixed(3),
      safeNumber(clip.source_end).toFixed(3),
      safeNumber(clip.gain_db).toFixed(2),
      safeNumber(clip.fade_in).toFixed(2),
      safeNumber(clip.fade_out).toFixed(2),
    ].join(':')).join('|');
    return `${audioUrl || 'no-audio'}::${clipSignature}::${samplesPerPixel}::${snapEnabled ? 'snap' : 'free'}::${snapUnit || ''}`;
  }, [arrangement, audioUrl, snapEnabled, snapUnit, samplesPerPixel, waveHeight]);


  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver((entries) => {
      const width = entries?.[0]?.contentRect?.width || frame.getBoundingClientRect().width || 0;
      setFrameWidth(width);
    });
    observer.observe(frame);
    setFrameWidth(frame.getBoundingClientRect().width || 0);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const editor = editorRef.current;
    if (!editor) return undefined;
    let cleanup = null;
    let attempts = 0;
    let cancelled = false;
    const attach = () => {
      if (cancelled) return;
      const scrollArea = editor.shadowRoot?.querySelector?.('.scroll-area');
      if (!scrollArea) {
        attempts += 1;
        if (attempts < 40) window.setTimeout(attach, 100);
        return;
      }
      const update = () => setEditorScroll({ left: scrollArea.scrollLeft || 0, top: scrollArea.scrollTop || 0 });
      scrollArea.addEventListener('scroll', update, { passive: true });
      update();
      cleanup = () => scrollArea.removeEventListener('scroll', update);
    };
    attach();
    return () => { cancelled = true; cleanup?.(); };
  }, [editorKey, samplesPerPixel]);

  useEffect(() => {
    const editor = editorRef.current;
    if (!editor) return undefined;
    let disposed = false;

    async function setup() {
      try {
        if (!audioContextRef.current) {
          audioContextRef.current = new AudioContext({ sampleRate: 48000 });
        }
        if (!adapterRef.current) {
          adapterRef.current = new NativePlayoutAdapter(audioContextRef.current);
        }
        editor.adapter = adapterRef.current;
        editor.bpm = bpm;
        editor.timeSignature = [4, 4];
        editor.ppqn = 960;
        if (typeof editor.ready === 'function') await editor.ready();
        if (!disposed) onReady?.(editor);
      } catch (error) {
        console.error('[Suno DAW] dawcore init failed', error);
      }
    }

    setup();
    return () => { disposed = true; };
  }, [editorKey, bpm, onReady]);

  useEffect(() => {
    const editor = editorRef.current;
    if (!editor) return undefined;

    const handlePlay = () => onPlaybackChange?.(true);
    const handlePause = () => onPlaybackChange?.(false);
    const handleStop = () => onPlaybackChange?.(false);
    const handleEnded = () => onPlaybackChange?.(false);
    const handleSeek = (event) => onSeek?.(safeNumber(event?.detail?.time, 0));
    const handleTimeUpdate = (event) => onTimeUpdate?.(safeNumber(event?.detail?.time, 0));
    const handleClipMove = (event) => {
      const clip = clipMap.get(event?.detail?.clipId);
      if (!clip) return;
      onClipMove?.(clip, sampleDeltaToSeconds(event.detail, editor));
    };
    const handleClipTrim = (event) => {
      const clip = clipMap.get(event?.detail?.clipId);
      if (!clip) return;
      onClipTrim?.(clip, event?.detail?.boundary, sampleDeltaToSeconds(event.detail, editor));
    };
    const handleClipSplit = () => onClipSplit?.();
    const handleSelection = (event) => {
      if (event?.detail?.clipId) onSelectClip?.(event.detail.clipId);
    };

    editor.addEventListener('daw-play', handlePlay);
    editor.addEventListener('daw-pause', handlePause);
    editor.addEventListener('daw-stop', handleStop);
    editor.addEventListener('daw-ended', handleEnded);
    editor.addEventListener('daw-seek', handleSeek);
    editor.addEventListener('daw-timeupdate', handleTimeUpdate);
    editor.addEventListener('daw-clip-move', handleClipMove);
    editor.addEventListener('daw-clip-trim', handleClipTrim);
    editor.addEventListener('daw-clip-split', handleClipSplit);
    editor.addEventListener('daw-selection', handleSelection);

    return () => {
      editor.removeEventListener('daw-play', handlePlay);
      editor.removeEventListener('daw-pause', handlePause);
      editor.removeEventListener('daw-stop', handleStop);
      editor.removeEventListener('daw-ended', handleEnded);
      editor.removeEventListener('daw-seek', handleSeek);
      editor.removeEventListener('daw-timeupdate', handleTimeUpdate);
      editor.removeEventListener('daw-clip-move', handleClipMove);
      editor.removeEventListener('daw-clip-trim', handleClipTrim);
      editor.removeEventListener('daw-clip-split', handleClipSplit);
      editor.removeEventListener('daw-selection', handleSelection);
    };
  }, [clipMap, onClipMove, onClipSplit, onClipTrim, onPlaybackChange, onSeek, onSelectClip, onTimeUpdate]);

  useEffect(() => {
    const editor = editorRef.current;
    if (!editor || typeof editor.seekTo !== 'function') return;
    const next = safeNumber(currentTime, 0);
    if (Math.abs(next - lastExternalSeekRef.current) < 0.08) return;
    lastExternalSeekRef.current = next;
    try {
      editor.seekTo(next);
    } catch {
      // dawcore ist eventuell noch nicht bereit; nächstes Render/Event synchronisiert erneut.
    }
  }, [currentTime, editorKey]);


  const selectedClip = selectedClipId ? clipMap.get(selectedClipId) : null;
  const selectedClipDuration = selectedClip ? clipDuration(selectedClip) : 0;
  const selectedTrackIndex = selectedClip ? Math.max(0, (tracks || []).findIndex((track) => track.id === selectedClip.track_id)) : 0;
  const estimatedTrackHeight = waveHeight * 2 + 22;
  const selectedClipLeft = selectedClip ? TRACK_CONTROL_WIDTH + (safeNumber(selectedClip.timeline_start) / duration) * timelinePixelWidth - editorScroll.left : 0;
  const selectedClipRight = selectedClip ? TRACK_CONTROL_WIDTH + ((safeNumber(selectedClip.timeline_start) + selectedClipDuration) / duration) * timelinePixelWidth - editorScroll.left : 0;
  const selectedClipTop = RULER_HEIGHT + selectedTrackIndex * estimatedTrackHeight + 6 - editorScroll.top;
  const selectedClipAiStyle = selectedClip ? {
    left: `${Math.round(clampNumber(selectedClipRight - 58, TRACK_CONTROL_WIDTH + 8, Math.max(TRACK_CONTROL_WIDTH + 8, frameWidth - 78)))}px`,
    top: `${Math.round(Math.max(RULER_HEIGHT + 6, selectedClipTop))}px`,
  } : null;
  const selectedClipPanelStyle = selectedClipAiStyle ? {
    left: `${Math.round(clampNumber(selectedClipLeft + 16, TRACK_CONTROL_WIDTH + 8, Math.max(TRACK_CONTROL_WIDTH + 8, frameWidth - 520)))}px`,
    top: `${Math.round(Math.max(RULER_HEIGHT + 38, selectedClipTop + 32))}px`,
  } : null;

  const sectionClassName = (label) => {
    const value = String(label || '').toLowerCase();
    if (value.includes('chorus') || value.includes('hook') || value.includes('refrain')) return 'chorus';
    if (value.includes('verse') || value.includes('strophe')) return 'verse';
    if (value.includes('bridge')) return 'bridge';
    if (value.includes('intro') || value.includes('outro') || value.includes('break')) return 'edge';
    return 'section';
  };

  const clipSectionOverlays = useMemo(() => {
    if (!sections.length || !arrangement?.clips?.length || !tracks?.length) return [];
    const overlays = [];
    const trackIndexById = new Map((tracks || []).map((track, index) => [track.id, index]));
    (arrangement.clips || []).forEach((clip) => {
      const trackIndex = trackIndexById.get(clip.track_id);
      if (trackIndex === undefined) return;
      const clipStart = safeNumber(clip.timeline_start);
      const clipSourceStart = safeNumber(clip.source_start);
      const clipSourceEnd = safeNumber(clip.source_end);
      const durationSeconds = Math.max(0.05, clipSourceEnd - clipSourceStart);
      const clipLeft = TRACK_CONTROL_WIDTH + (clipStart / duration) * timelinePixelWidth - editorScroll.left;
      const clipWidth = Math.max(10, (durationSeconds / duration) * timelinePixelWidth);
      const trackTop = RULER_HEIGHT + trackIndex * estimatedTrackHeight + 5 - editorScroll.top;
      const clipTop = trackTop + 20;
      sections.forEach((section) => {
        const overlapStart = Math.max(section.start, clipSourceStart);
        const overlapEnd = Math.min(section.end, clipSourceEnd);
        if (overlapEnd - overlapStart <= 0.05) return;
        const localLeft = ((overlapStart - clipSourceStart) / durationSeconds) * clipWidth;
        const localWidth = ((overlapEnd - overlapStart) / durationSeconds) * clipWidth;
        overlays.push({
          id: `${clip.id}-${section.id}-${overlapStart.toFixed(2)}-${overlapEnd.toFixed(2)}`,
          clipId: clip.id,
          label: section.label,
          start: overlapStart,
          end: overlapEnd,
          className: sectionClassName(section.label),
          style: {
            left: `${Math.round(clipLeft + localLeft)}px`,
            top: `${Math.round(clipTop)}px`,
            width: `${Math.max(22, Math.round(localWidth))}px`,
          },
        });
      });
    });
    return overlays.filter((overlay) => {
      const left = Number.parseFloat(overlay.style.left);
      const width = Number.parseFloat(overlay.style.width);
      const top = Number.parseFloat(overlay.style.top);
      return left + width >= TRACK_CONTROL_WIDTH && left <= frameWidth + 20 && top >= RULER_HEIGHT - 40 && top <= 1000;
    });
  }, [arrangement, duration, editorScroll.left, editorScroll.top, estimatedTrackHeight, frameWidth, sections, timelinePixelWidth, tracks]);

  const renderClip = (clip) => {
    const durationSeconds = Math.max(0.05, clipDuration(clip));
    const isSelected = clip.id === selectedClipId;
    const gain = Math.pow(10, safeNumber(clip.gain_db) / 20);
    return (
      <daw-clip
        key={clip.id}
        data-clip-id={clip.id}
        class={isSelected ? 'suno-dawcore-clip is-selected' : 'suno-dawcore-clip'}
        src={audioUrl || ''}
        start={safeNumber(clip.timeline_start).toFixed(4)}
        duration={durationSeconds.toFixed(4)}
        offset={safeNumber(clip.source_start).toFixed(4)}
        gain={gain.toFixed(5)}
        fade-in={safeNumber(clip.fade_in).toFixed(3)}
        fade-out={safeNumber(clip.fade_out).toFixed(3)}
        name={clip.label || assetTitle || 'Clip'}
        color={isSelected ? '#22d3ee' : '#7c3aed'}
        onClick={(event) => {
          event.stopPropagation();
          onSelectClip?.(clip.id);
        }}
      />
    );
  };

  return (
    <section className="suno-dawcore-shell panel" aria-label="DAW Timeline">
      <div className="suno-dawcore-topline">
        <div>
          <span className="daw-kicker">Timeline Engine</span>
          <strong>dawcore / native Web Audio</strong>
        </div>
        <div className="suno-dawcore-status">
          <span>{secondsToClock(currentTime, true)} / {secondsToClock(duration, true)}</span>
          <span>{Math.round(bpm)} BPM</span>
          <span>{snapEnabled ? `Snap ${snapToMode(snapUnit)}` : 'Snap aus'}</span>
          <div className="suno-dawcore-zoom-controls" aria-label="Timeline-Zoom">
            <button type="button" onClick={() => setTimelineScale((value) => Math.max(1, value / 2))} disabled={timelineScale <= 1} title="Timeline herauszoomen">−</button>
            <button type="button" onClick={() => setTimelineScale(1)} title="Gesamtlänge anzeigen">Gesamt</button>
            <strong>{zoomPercent}%</strong>
            <button type="button" onClick={() => setTimelineScale((value) => Math.min(16, value * 2))} disabled={timelineScale >= 16} title="Timeline hineinzoomen">+</button>
          </div>
        </div>
      </div>

      <div className="suno-dawcore-editor-frame" ref={frameRef}>
        <daw-editor
          key={editorKey}
          id={editorId}
          ref={editorRef}
          samples-per-pixel={String(samplesPerPixel)}
          wave-height={String(waveHeight)}
          clip-header-height="22"
          timescale
          clip-headers
          interactive-clips
          indefinite-playback
          fill-viewport
          rounded-bars
          bar-width="2"
          bar-gap="1"
          scale-mode="temporal"
          snap-to={snapEnabled ? snapToMode(snapUnit) : 'off'}
          eager-resume="document"
          time-format="hh:mm:ss.sss"
          onClick={(event) => {
            if (event.target?.tagName !== 'DAW-CLIP') return;
            const clipId = event.target?.dataset?.clipId;
            if (clipId) onSelectClip?.(clipId);
          }}
        >
          <daw-keyboard-shortcuts playback splitting undo />
          {(tracks || []).map((track) => (
            <daw-track key={track.id} id={track.id} name={track.name} render-mode="waveform">
              {(arrangement?.clips || []).filter((clip) => clip.track_id === track.id).map(renderClip)}
            </daw-track>
          ))}
        </daw-editor>
        <div className="suno-dawcore-linked-section-layer" aria-label="Abschnitte direkt auf den Audio-Clips">
          {clipSectionOverlays.map((overlay) => (
            <span
              key={overlay.id}
              className={`suno-dawcore-linked-section ${overlay.className}${overlay.clipId === selectedClipId ? ' is-selected-clip' : ''}`}
              style={overlay.style}
              title={`${overlay.label}: ${secondsToClock(overlay.start, true)} – ${secondsToClock(overlay.end, true)}`}
            >{overlay.label}</span>
          ))}
        </div>
        {selectedClip && selectedClipAiStyle && (
          <button
            type="button"
            className="suno-dawcore-clip-ai-anchor"
            style={selectedClipAiStyle}
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
      </div>

      <div className="suno-dawcore-foot">
        <span>{selectedClipId ? 'KI liegt direkt am ausgewählten Audio-Clip. Alternativ kann der Clip weiterhin über die Vorschau sicher angewendet werden.' : 'Clip in der Timeline auswählen. Danach erscheint der KI-Button direkt am Audio-Clip.'}</span>
      </div>

      {selectedClipId && clipAiPanel?.clipId === selectedClipId && (
        <form className="daw-clip-ai-popover suno-dawcore-ai-panel" style={selectedClipPanelStyle || undefined} onSubmit={(event) => runClipAiCommand?.(event, clipMap.get(selectedClipId))} onPointerDown={(event) => event.stopPropagation()} onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()} onKeyUp={(event) => event.stopPropagation()}>
          <div className="daw-clip-ai-head">
            <div>
              <span className="daw-kicker">Clip-KI</span>
              <strong>{clipMap.get(selectedClipId)?.label || 'Clip bearbeiten'}</strong>
            </div>
            <button type="button" className="ghost" onClick={closeClipAiPanel} aria-label="Clip-KI schließen">×</button>
          </div>
          <input
            value={clipAiPanel.prompt || ''}
            onChange={(event) => setClipAiPromptFor?.(clipMap.get(selectedClipId), event.target.value)}
            placeholder="z. B. erste Hook doppeln, Anfang 8s kürzen, Fade-in 3s"
            aria-label="KI-Befehl für diesen Clip"
            autoFocus
          />
          <div className="daw-clip-ai-examples">
            <button type="button" onClick={() => setClipAiPromptFor?.(clipMap.get(selectedClipId), 'Fade-in 3s')}>Fade-in 3s</button>
            <button type="button" onClick={() => setClipAiPromptFor?.(clipMap.get(selectedClipId), 'Anfang um 8s kürzen')}>Anfang kürzen</button>
            <button type="button" onClick={() => setClipAiPromptFor?.(clipMap.get(selectedClipId), 'Clip um 3 dB leiser machen')}>-3 dB</button>
            <button type="submit" className="primary"><Bot size={14} /> Planen</button>
          </div>
        </form>
      )}
    </section>
  );
}
