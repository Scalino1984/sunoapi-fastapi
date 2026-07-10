import React from 'react';
import {
  GripHorizontal, Flag, Scissors, Magnet, Minus, Plus, Pause, Play, Square,
  Redo2, Undo2, SkipBack, SkipForward, Volume2, Bot, LocateFixed,
} from 'lucide-react';
import { secondsToClock, safeNumber } from '../timeUtils.js';
import { dawBeatgridBoundaries } from '../musicalTime.js';
import { SNAP_UNITS } from '../arrangement.js';
import { useDawStore } from '../store.js';

// Zeit- und Takt-Anzeige mit eigener Store-Subscription: nur dieses kleine
// Element rendert bei Zeit-Ticks neu, nicht die gesamte Transportleiste.
function TimeReadout({ timelineDuration, bpm, beatgrid }) {
  const currentTime = useDawStore((state) => state.currentTime);
  let barBeatLabel = '';
  const boundaries = dawBeatgridBoundaries(beatgrid, timelineDuration);
  if (boundaries.length >= 2) {
    let barIndex = 0;
    for (let i = 0; i < boundaries.length; i += 1) {
      if (boundaries[i] <= currentTime + 0.001) barIndex = i;
      else break;
    }
    barBeatLabel = `Takt ${barIndex + 1}`;
  } else {
    const safeBpm = safeNumber(bpm);
    if (safeBpm >= 20) {
      const barLength = 240 / safeBpm;
      const bar = Math.floor(currentTime / barLength) + 1;
      const beat = Math.floor((currentTime % barLength) / (60 / safeBpm)) + 1;
      barBeatLabel = `Takt ${bar}.${beat}`;
    }
  }
  return (
    <div className="daw-time-display">
      <strong>{secondsToClock(currentTime, true)}</strong>
      <span>/ {secondsToClock(timelineDuration, true)}</span>
      {barBeatLabel ? <em>{barBeatLabel}</em> : null}
    </div>
  );
}

const TOOL_MODES = [
  { id: 'select', label: 'Auswahl', icon: GripHorizontal, hint: 'Clips verschieben, Ränder ziehen zum Trimmen' },
  { id: 'range', label: 'Bereich', icon: Flag, hint: 'Im Ruler ziehen, um einen Bereich zu markieren' },
  { id: 'split', label: 'Schere', icon: Scissors, hint: 'Klick in einen Clip schneidet an dieser Stelle' },
  { id: 'marker', label: 'Marker', icon: Flag, hint: 'Klick im Ruler setzt einen Marker' },
];

export function TransportBar({
  isPlaying, timelineDuration, volume,
  onPlayPause, onStop, onSkip, onVolumeChange,
  bpm, timeSignature, onBpmChange, onTimeSignatureChange,
  snapEnabled, snapUnit, onSnapToggle, onSnapUnitChange, beatgridStatusLabel, beatgrid,
  toolMode, onToolModeChange,
  zoom, zoomMax, onZoomChange,
  followPlayhead, onToggleFollow,
  canUndo, canRedo, onUndo, onRedo,
  aiPanelOpen, onToggleAiPanel,
}) {
  return (
    <div className="daw-transport">
      <div className="daw-transport-group">
        <button type="button" className="icon-button" title="5s zurück" onClick={() => onSkip(-5)}><SkipBack size={16} /></button>
        <button type="button" className={`daw-play-button ${isPlaying ? 'active' : ''}`} onClick={onPlayPause} title="Play/Pause (Leertaste)">
          {isPlaying ? <Pause size={18} /> : <Play size={18} />}
        </button>
        <button type="button" className="icon-button" title="Stop" onClick={onStop}><Square size={14} /></button>
        <button type="button" className="icon-button" title="5s vor" onClick={() => onSkip(5)}><SkipForward size={16} /></button>
        <TimeReadout timelineDuration={timelineDuration} bpm={bpm} beatgrid={beatgrid} />
      </div>

      <div className="daw-transport-group daw-transport-musical">
        <label className="daw-inline-field" title="Tempo für Raster & Snap">
          <span>BPM</span>
          <input
            type="number" min={20} max={300} step={0.5}
            value={bpm ?? ''}
            placeholder="auto"
            onChange={(event) => onBpmChange(event.target.value === '' ? null : safeNumber(event.target.value))}
          />
        </label>
        <label className="daw-inline-field" title="Taktart">
          <span>Takt</span>
          <select value={timeSignature} onChange={(event) => onTimeSignatureChange(event.target.value)}>
            {['4/4', '3/4', '6/8', '2/4'].map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <button
          type="button"
          className={`icon-button ${snapEnabled ? 'active' : ''}`}
          title={beatgridStatusLabel || 'Snap-to-Grid an/aus'}
          onClick={onSnapToggle}
        >
          <Magnet size={15} /> Snap
        </button>
        <div className="daw-snap-units" role="group" aria-label="Snap-Einheit">
          {SNAP_UNITS.map((unit) => (
            <button
              key={unit.id}
              type="button"
              className={snapUnit === unit.id ? 'active' : ''}
              disabled={!snapEnabled}
              onClick={() => onSnapUnitChange(unit.id)}
            >
              {unit.label}
            </button>
          ))}
        </div>
      </div>

      <div className="daw-transport-group">
        <div className="daw-tool-modes" role="group" aria-label="Werkzeug">
          {TOOL_MODES.map((tool) => {
            const Icon = tool.icon;
            return (
              <button
                key={tool.id}
                type="button"
                className={toolMode === tool.id ? 'active' : ''}
                title={tool.hint}
                onClick={() => onToolModeChange(tool.id)}
              >
                <Icon size={14} /> {tool.label}
              </button>
            );
          })}
        </div>
        <div className="daw-zoom" title="Timeline-Zoom">
          <button type="button" className="icon-button" onClick={() => onZoomChange(zoom - 1)} disabled={zoom <= 0}><Minus size={14} /></button>
          <span>{Math.round(100 + zoom * 55)}%</span>
          <button type="button" className="icon-button" onClick={() => onZoomChange(zoom + 1)} disabled={zoom >= zoomMax}><Plus size={14} /></button>
        </div>
        <button
          type="button"
          className={`icon-button ${followPlayhead ? 'active' : ''}`}
          title="Timeline folgt dem Playhead bei Wiedergabe"
          onClick={onToggleFollow}
        >
          <LocateFixed size={15} />
        </button>
        <button type="button" className="icon-button" title="Rückgängig (Strg+Z)" onClick={onUndo} disabled={!canUndo}><Undo2 size={15} /></button>
        <button type="button" className="icon-button" title="Wiederholen (Strg+Y)" onClick={onRedo} disabled={!canRedo}><Redo2 size={15} /></button>
        <label className="daw-volume" title="Abhör-Lautstärke">
          <Volume2 size={15} />
          <input type="range" min={0} max={1.2} step={0.02} value={volume} onChange={(event) => onVolumeChange(safeNumber(event.target.value, 1))} />
        </label>
        <button
          type="button"
          className={`daw-ai-toolbar-button ${aiPanelOpen ? 'active' : ''}`}
          onClick={onToggleAiPanel}
          title="DAW-KI: natürliche Befehle für die Timeline"
        >
          <Bot size={15} /> DAW-KI
        </button>
      </div>
    </div>
  );
}
