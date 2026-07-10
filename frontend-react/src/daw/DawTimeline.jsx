import React, { memo, useMemo, useRef, useState } from 'react';
import { Bot, Lock, Scissors, Volume2 } from 'lucide-react';
import { Waveform } from '../components/Waveform.jsx';
import {
  DAW_RULER_HEIGHT,
  DAW_TRACK_HEADER_WIDTH,
  DAW_TRACK_HEIGHT,
  DAW_ZOOM_PRESETS,
  arrangementDuration,
  beatsPerBar,
  clipDuration,
  clipEnd,
  formatBarsBeats,
  formatTime,
  safeNumber,
  secondsPerBeat,
  snapTime,
} from './dawMath.js';

function pointerTime(event, container, pxPerSecond) {
  const rect = container.getBoundingClientRect();
  return Math.max(0, (event.clientX - rect.left + container.scrollLeft - DAW_TRACK_HEADER_WIDTH) / pxPerSecond);
}

function makeTicks(totalDuration, arrangement, pxPerSecond) {
  const bpm = safeNumber(arrangement?.bpm, 0);
  const ticks = [];
  if (bpm) {
    const beat = secondsPerBeat(bpm);
    const beats = beatsPerBar(arrangement?.time_signature);
    for (let time = 0; time <= totalDuration + beat; time += beat) {
      const beatIndex = Math.round(time / beat);
      const isBar = beatIndex % beats === 0;
      if (!isBar && pxPerSecond < 84) continue;
      ticks.push({ time, label: isBar ? `T${Math.floor(beatIndex / beats) + 1}` : `${(beatIndex % beats) + 1}`, isBar });
    }
  } else {
    const step = pxPerSecond > 120 ? 1 : pxPerSecond > 72 ? 2 : 5;
    for (let time = 0; time <= totalDuration + step; time += step) ticks.push({ time, label: formatTime(time, true), isBar: time % 10 === 0 });
  }
  return ticks;
}

function trackIndexByPointer(event, tracks) {
  const row = event.target.closest?.('[data-track-row]');
  const id = row?.getAttribute('data-track-row');
  const found = tracks.findIndex((track) => track.id === id);
  return found >= 0 ? found : 0;
}

const DawClip = memo(function DawClip({ clip, asset, selected, pxPerSecond, sourceDuration, onPointerDown, onSelect, onSplit, onOpenAi }) {
  const left = safeNumber(clip.timeline_start) * pxPerSecond;
  const width = Math.max(28, clipDuration(clip) * pxPerSecond);
  const mutedClass = clip.muted ? ' is-muted' : '';
  const lockedClass = clip.locked ? ' is-locked' : '';
  return (
    <div
      className={`daw-pro-clip${selected ? ' is-selected' : ''}${mutedClass}${lockedClass}`}
      style={{ left, width }}
      onPointerDown={(event) => onPointerDown(event, clip, 'move')}
      onClick={(event) => { event.stopPropagation(); onSelect(clip.id); }}
      title={`${clip.label} · ${formatTime(clip.timeline_start)} – ${formatTime(clipEnd(clip))}`}
    >
      <div className="daw-pro-clip-title">
        <strong>{clip.label || 'Clip'}</strong>
        <span>{formatTime(clip.timeline_start, true)} · {formatTime(clipDuration(clip), true)}</span>
      </div>
      <div className="daw-pro-clip-wave">
        <Waveform
          asset={asset}
          compact
          interactive={false}
          showProgress={false}
          sourceStartSeconds={clip.source_start}
          sourceEndSeconds={clip.source_end}
          sourceDurationSeconds={sourceDuration}
          showSegments
        />
      </div>
      {clip.fade_in > 0 ? <div className="daw-pro-fade daw-pro-fade-in" style={{ width: Math.min(width - 12, clip.fade_in * pxPerSecond) }} /> : null}
      {clip.fade_out > 0 ? <div className="daw-pro-fade daw-pro-fade-out" style={{ width: Math.min(width - 12, clip.fade_out * pxPerSecond) }} /> : null}
      <button className="daw-pro-clip-ai" type="button" onClick={(event) => { event.stopPropagation(); onOpenAi(clip.id); }} title="KI-Befehl für diesen Clip">
        <Bot size={14} />
      </button>
      <button className="daw-pro-clip-split" type="button" onClick={(event) => { event.stopPropagation(); onSplit(clip.id); }} title="Am Playhead schneiden">
        <Scissors size={14} />
      </button>
      <div className="daw-pro-handle daw-pro-handle-left" onPointerDown={(event) => onPointerDown(event, clip, 'trim-left')} />
      <div className="daw-pro-handle daw-pro-handle-right" onPointerDown={(event) => onPointerDown(event, clip, 'trim-right')} />
      {clip.locked ? <Lock className="daw-pro-clip-lock" size={14} /> : null}
    </div>
  );
});

export function DawTimeline({
  arrangement,
  asset,
  assetsById,
  selectedClipId,
  selectedSectionId,
  sections,
  currentTime,
  zoom,
  tool,
  onSelectClip,
  onChangeArrangement,
  onCommitHistory,
  onSeek,
  onSplitClip,
  onOpenClipAi,
  onSelectSection,
}) {
  const scrollRef = useRef(null);
  const [dragState, setDragState] = useState(null);
  const pxPerSecond = DAW_ZOOM_PRESETS[zoom]?.pxPerSecond || DAW_ZOOM_PRESETS[1].pxPerSecond;
  const totalDuration = arrangementDuration(arrangement, asset?.duration_seconds || 1);
  const width = Math.max(980, Math.ceil(totalDuration * pxPerSecond) + 360);
  const ticks = useMemo(() => makeTicks(totalDuration, arrangement, pxPerSecond), [totalDuration, arrangement, pxPerSecond]);
  const sourceDuration = safeNumber(asset?.duration_seconds, totalDuration);

  function handlePointerDown(event, clip, mode) {
    if (clip.locked) return;
    event.stopPropagation();
    event.preventDefault();
    onSelectClip(clip.id);
    onCommitHistory();
    const startTrackIndex = arrangement.tracks.findIndex((track) => track.id === clip.track_id);
    setDragState({
      pointerId: event.pointerId,
      clipId: clip.id,
      mode,
      pointerStartX: event.clientX,
      pointerStartY: event.clientY,
      startTimeline: safeNumber(clip.timeline_start),
      startSourceStart: safeNumber(clip.source_start),
      startSourceEnd: safeNumber(clip.source_end),
      startTrackIndex: Math.max(0, startTrackIndex),
    });
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function handlePointerMove(event) {
    if (!dragState) return;
    const deltaSeconds = (event.clientX - dragState.pointerStartX) / pxPerSecond;
    const deltaTracks = Math.round((event.clientY - dragState.pointerStartY) / DAW_TRACK_HEIGHT);
    onChangeArrangement((current) => {
      const clip = current.clips.find((item) => item.id === dragState.clipId);
      if (!clip) return current;
      const duration = Math.max(0.08, dragState.startSourceEnd - dragState.startSourceStart);
      const targetTrack = current.tracks[Math.max(0, Math.min(current.tracks.length - 1, dragState.startTrackIndex + deltaTracks))] || current.tracks[0];
      const nextClip = { ...clip };
      if (dragState.mode === 'move') {
        nextClip.timeline_start = snapTime(Math.max(0, dragState.startTimeline + deltaSeconds), current);
        nextClip.track_id = targetTrack.id;
      } else if (dragState.mode === 'trim-left') {
        const trim = Math.max(0, Math.min(duration - 0.08, deltaSeconds));
        const nextTimeline = snapTime(dragState.startTimeline + trim, current);
        const actualTrim = Math.max(0, Math.min(duration - 0.08, nextTimeline - dragState.startTimeline));
        nextClip.timeline_start = dragState.startTimeline + actualTrim;
        nextClip.source_start = dragState.startSourceStart + actualTrim;
      } else if (dragState.mode === 'trim-right') {
        const nextEnd = snapTime(dragState.startTimeline + duration + deltaSeconds, current);
        const actualDuration = Math.max(0.08, nextEnd - dragState.startTimeline);
        nextClip.source_end = dragState.startSourceStart + actualDuration;
      }
      const clips = current.clips.map((item) => item.id === dragState.clipId ? nextClip : item);
      return { ...current, clips };
    });
  }

  function handlePointerUp() {
    if (!dragState) return;
    setDragState(null);
  }

  function handleTimelineClick(event) {
    if (!scrollRef.current) return;
    const time = snapTime(pointerTime(event, scrollRef.current, pxPerSecond), arrangement, false);
    if (tool === 'split' && selectedClipId) onSplitClip(selectedClipId, time);
    else onSeek(time);
  }

  return (
    <section className="daw-pro-timeline-shell" onPointerMove={handlePointerMove} onPointerUp={handlePointerUp} onPointerCancel={handlePointerUp}>
      <div className="daw-pro-track-column" style={{ width: DAW_TRACK_HEADER_WIDTH }}>
        <div className="daw-pro-corner">
          <strong>Timeline</strong>
          <span>{formatBarsBeats(currentTime, arrangement)}</span>
        </div>
        {arrangement.tracks.map((track, index) => (
          <div className="daw-pro-track-head" key={track.id} style={{ height: DAW_TRACK_HEIGHT }}>
            <strong>{track.name || `Spur ${index + 1}`}</strong>
            <span><Volume2 size={13} /> {track.muted ? 'Mute' : track.solo ? 'Solo' : `${safeNumber(track.volume_db).toFixed(1)} dB`}</span>
          </div>
        ))}
      </div>
      <div className="daw-pro-scroll" ref={scrollRef} onClick={handleTimelineClick}>
        <div className="daw-pro-canvas" style={{ width, height: DAW_RULER_HEIGHT + arrangement.tracks.length * DAW_TRACK_HEIGHT }}>
          <div className="daw-pro-ruler" style={{ height: DAW_RULER_HEIGHT }}>
            {ticks.map((tick) => (
              <span key={`${tick.time}-${tick.label}`} className={tick.isBar ? 'is-bar' : ''} style={{ left: tick.time * pxPerSecond }}>
                {tick.label}
              </span>
            ))}
          </div>
          <div className="daw-pro-sections" style={{ height: DAW_RULER_HEIGHT }}>
            {sections.map((section) => {
              const left = safeNumber(section.start) * pxPerSecond;
              const sectionWidth = Math.max(28, (safeNumber(section.end) - safeNumber(section.start)) * pxPerSecond);
              return (
                <button
                  key={section.id}
                  className={`daw-pro-section${selectedSectionId === section.id ? ' is-selected' : ''}`}
                  style={{ left, width: sectionWidth }}
                  type="button"
                  onClick={(event) => { event.stopPropagation(); onSelectSection(section.id); onSeek(section.start); }}
                >
                  {section.label}
                </button>
              );
            })}
          </div>
          <div className="daw-pro-playhead" style={{ left: currentTime * pxPerSecond }} />
          {arrangement.tracks.map((track, trackIndex) => (
            <div
              key={track.id}
              className="daw-pro-track-row"
              data-track-row={track.id}
              style={{ top: DAW_RULER_HEIGHT + trackIndex * DAW_TRACK_HEIGHT, height: DAW_TRACK_HEIGHT }}
            >
              {ticks.filter((tick) => tick.isBar).map((tick) => <i key={`grid-${track.id}-${tick.time}`} style={{ left: tick.time * pxPerSecond }} />)}
              {(arrangement.clips || []).filter((clip) => clip.track_id === track.id).map((clip) => (
                <DawClip
                  key={clip.id}
                  clip={clip}
                  asset={assetsById.get(Number(clip.source_audio_id)) || asset}
                  sourceDuration={sourceDuration}
                  selected={selectedClipId === clip.id}
                  pxPerSecond={pxPerSecond}
                  onPointerDown={handlePointerDown}
                  onSelect={onSelectClip}
                  onSplit={(clipId) => onSplitClip(clipId)}
                  onOpenAi={onOpenClipAi}
                />
              ))}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
