import React from 'react';
import { Bot, Lock, Volume2, VolumeX, Headphones, Plus, Trash2, Send, X } from 'lucide-react';
import { clamp, safeNumber, clipDuration, secondsToClock, fadeHandlePercent } from '../timeUtils.js';
import { ClipWaveform } from './ClipWaveform.jsx';

// ---------------------------------------------------------------------------
// TrackHeader – Name, Mute/Solo/Volume je Spur, Spuren hinzufügen/entfernen.
// ---------------------------------------------------------------------------
export function TrackHeaders({ tracks = [], onTrackPatch, onAddTrack, onRemoveTrack, canAddTrack }) {
  return (
    <div className="daw-track-headers">
      <div className="daw-track-headers-top">
        <span>Spuren</span>
        <button type="button" className="icon-button" title="Spur hinzufügen" onClick={onAddTrack} disabled={!canAddTrack}>
          <Plus size={14} />
        </button>
      </div>
      {tracks.map((track) => (
        <div key={track.id} className="daw-track-header">
          <input
            className="daw-track-name"
            value={track.name}
            onChange={(event) => onTrackPatch(track.id, { name: event.target.value })}
            aria-label="Spurname"
          />
          <div className="daw-track-controls">
            <button
              type="button"
              className={`icon-button ${track.muted ? 'active danger' : ''}`}
              title={track.muted ? 'Stummschaltung aufheben' : 'Spur stummschalten'}
              onClick={() => onTrackPatch(track.id, { muted: !track.muted })}
            >
              {track.muted ? <VolumeX size={13} /> : <Volume2 size={13} />}
            </button>
            <button
              type="button"
              className={`icon-button ${track.solo ? 'active' : ''}`}
              title="Solo"
              onClick={() => onTrackPatch(track.id, { solo: !track.solo })}
            >
              <Headphones size={13} />
            </button>
            <input
              type="range" min={-24} max={12} step={0.5}
              value={track.volume_db}
              title={`Spur-Pegel ${track.volume_db} dB`}
              onChange={(event) => onTrackPatch(track.id, { volume_db: safeNumber(event.target.value) })}
            />
            {tracks.length > 1 ? (
              <button type="button" className="icon-button ghost" title="Spur entfernen (Clips wandern auf Spur 1)" onClick={() => onRemoveTrack(track.id)}>
                <Trash2 size={12} />
              </button>
            ) : null}
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ClipView – ein Clip in der Timeline: verschieben, trimmen, Fades ziehen,
// Schere, Auswahl und das Clip-KI-Textfeld.
// ---------------------------------------------------------------------------
const ClipView = React.memo(function ClipView({
  clip, duration, sourceDuration, waveformPeaksById,
  selected, toolMode,
  onClipPointerDown, onTrimPointerDown, onFadePointerDown,
  onSplitClick, onSelect, onOpenAi,
  aiOpen, aiPrompt, onAiPromptChange, onAiSubmit, onAiClose, aiBusy,
}) {
  const start = safeNumber(clip.timeline_start);
  const length = clipDuration(clip);
  const left = clamp((start / Math.max(duration, 0.001)) * 100, 0, 100);
  const width = clamp((length / Math.max(duration, 0.001)) * 100, 0.25, 100);
  const peaks = waveformPeaksById?.[String(clip.source_audio_id)] || [];
  const fadeInPct = fadeHandlePercent(clip.fade_in, length, 'left');
  const fadeOutPct = fadeHandlePercent(clip.fade_out, length, 'right');

  return (
    <div
      className={[
        'daw-clip',
        `daw-clip-color-${clip.color || 'cyan'}`,
        selected ? 'selected' : '',
        clip.muted ? 'muted' : '',
        clip.locked ? 'locked' : '',
      ].join(' ')}
      style={{ left: `${left}%`, width: `${width}%` }}
      onPointerDown={(event) => {
        if (toolMode === 'split') return; // Split wird per Click behandelt
        onClipPointerDown(event, clip);
      }}
      onClick={(event) => {
        event.stopPropagation();
        if (toolMode === 'split') onSplitClick(event, clip);
        else onSelect(clip.id);
      }}
      title={`${clip.label || 'Clip'} · ${secondsToClock(start, true)} – ${secondsToClock(start + length, true)} · ${secondsToClock(length, true)}`}
    >
      <div className="daw-clip-fades" aria-hidden="true">
        {safeNumber(clip.fade_in) > 0 ? <span className="daw-clip-fade-in" style={{ width: `${fadeInPct}%` }} /> : null}
        {safeNumber(clip.fade_out) > 0 ? <span className="daw-clip-fade-out" style={{ width: `${fadeOutPct}%` }} /> : null}
      </div>
      <ClipWaveform peaks={peaks} sourceStart={clip.source_start} sourceEnd={clip.source_end} sourceDuration={sourceDuration} />
      <div className="daw-clip-top">
        <span className="daw-clip-label">{clip.locked ? <Lock size={11} /> : null}{clip.label || 'Clip'}</span>
        <button
          type="button"
          className={`daw-clip-ai-button ${aiOpen ? 'active' : ''}`}
          title="KI-Befehl für diesen Clip (z. B. „Schneide exakt nach 4 Takten“)"
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => { event.stopPropagation(); onOpenAi(clip); }}
        >
          <Bot size={12} />
        </button>
      </div>
      {!clip.locked ? (
        <>
          <span className="daw-clip-handle left" title="Anfang trimmen" onPointerDown={(event) => onTrimPointerDown(event, clip, 'start')} />
          <span className="daw-clip-handle right" title="Ende trimmen" onPointerDown={(event) => onTrimPointerDown(event, clip, 'end')} />
          <span className="daw-clip-fade-handle left" title="Fade-in ziehen" onPointerDown={(event) => onFadePointerDown(event, clip, 'in')} />
          <span className="daw-clip-fade-handle right" title="Fade-out ziehen" onPointerDown={(event) => onFadePointerDown(event, clip, 'out')} />
        </>
      ) : null}
      {aiOpen ? (
        <div className="daw-clip-ai-popover" onPointerDown={(event) => event.stopPropagation()} onClick={(event) => event.stopPropagation()}>
          <div className="daw-clip-ai-popover-head">
            <span><Bot size={12} /> Clip-KI</span>
            <button type="button" className="icon-button ghost" onClick={onAiClose}><X size={12} /></button>
          </div>
          <textarea
            value={aiPrompt}
            placeholder={'z. B. „Schneide den Clip exakt nach 4 Takten“ oder „Fade-out 2 Sekunden“'}
            rows={2}
            autoFocus
            onChange={(event) => onAiPromptChange(clip, event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                onAiSubmit(clip);
              }
            }}
          />
          <div className="daw-clip-ai-popover-actions">
            <button type="button" className="primary" disabled={aiBusy || !aiPrompt.trim()} onClick={() => onAiSubmit(clip)}>
              <Send size={12} /> Ausführen
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
});

// ---------------------------------------------------------------------------
// TrackLanes – alle Spuren mit Clips; Pointer-Interaktionen laufen über den
// von der Seite gelieferten Interaktions-Controller (Move/Trim/Fade/Range).
// ---------------------------------------------------------------------------
export const TrackLanes = React.memo(function TrackLanes({
  tracks = [], clips = [], duration, sourceDuration,
  waveformPeaksById, selectedClipId, toolMode,
  interactions, clipAi, aiBusy,
  onSelectClip, onLanePointerDown,
}) {
  return (
    <div className="daw-track-lanes">
      {tracks.map((track) => (
        <div
          key={track.id}
          className={`daw-track-lane ${track.muted ? 'muted' : ''}`}
          data-track-id={track.id}
          onPointerDown={(event) => onLanePointerDown(event, track)}
        >
          {clips
            .filter((clip) => clip.track_id === track.id)
            .map((clip) => (
              <ClipView
                key={clip.id}
                clip={clip}
                duration={duration}
                sourceDuration={sourceDuration}
                waveformPeaksById={waveformPeaksById}
                selected={clip.id === selectedClipId}
                toolMode={toolMode}
                onClipPointerDown={interactions.onClipPointerDown}
                onTrimPointerDown={interactions.onTrimPointerDown}
                onFadePointerDown={interactions.onFadePointerDown}
                onSplitClick={interactions.onSplitClick}
                onSelect={onSelectClip}
                onOpenAi={clipAi.open}
                aiOpen={clipAi.clipId === clip.id}
                aiPrompt={clipAi.clipId === clip.id ? clipAi.prompt : ''}
                onAiPromptChange={clipAi.setPrompt}
                onAiSubmit={clipAi.submit}
                onAiClose={clipAi.close}
                aiBusy={aiBusy}
              />
            ))}
        </div>
      ))}
    </div>
  );
});

export { ClipView };
