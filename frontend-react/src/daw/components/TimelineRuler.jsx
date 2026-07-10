import React, { useMemo } from 'react';
import { safeNumber, clamp, secondsToClock } from '../timeUtils.js';
import { dawBeatgridBoundaries, ticksForDuration } from '../musicalTime.js';

// Ruler + Marker-Zeile. Alle Positionen in Prozent der Timeline-Dauer, damit
// Zoom nur die Containerbreite skaliert und die Mathematik stabil bleibt.
export const TimelineRuler = React.memo(function TimelineRuler({
  duration, zoom, beatgrid, bpm,
  markers = [], selection = null,
  snapGuide = null,
  onPointerDown, onMarkerClick,
}) {
  const ticks = useMemo(() => ticksForDuration(duration, zoom), [duration, zoom]);
  const barLines = useMemo(() => {
    const boundaries = dawBeatgridBoundaries(beatgrid, duration);
    if (boundaries.length >= 2) return boundaries;
    const safeBpm = safeNumber(bpm);
    if (safeBpm >= 20) {
      const barLength = 240 / safeBpm;
      const lines = [];
      for (let t = 0; t <= duration + 0.001; t += barLength) lines.push(t);
      return lines;
    }
    return [];
  }, [beatgrid, bpm, duration]);

  const pct = (value) => `${clamp((safeNumber(value) / Math.max(duration, 0.001)) * 100, 0, 100)}%`;

  return (
    <div className="daw-ruler" onPointerDown={onPointerDown}>
      <div className="daw-ruler-grid" aria-hidden="true">
        {barLines.map((time, index) => (
          <span key={`bar-${index}`} className="daw-bar-line" style={{ left: pct(time) }}>
            {index % 4 === 0 && barLines.length <= 400 ? <i>{index + 1}</i> : null}
          </span>
        ))}
      </div>
      {ticks.map((tick) => (
        <span key={`tick-${tick.time}`} className={`daw-tick ${tick.major ? 'major' : ''}`} style={{ left: pct(tick.time) }}>
          {tick.major ? <label>{secondsToClock(tick.time)}</label> : null}
        </span>
      ))}
      {selection && selection.end - selection.start > 0.02 ? (
        <div
          className="daw-selection-range"
          style={{ left: pct(selection.start), width: `${clamp(((selection.end - selection.start) / Math.max(duration, 0.001)) * 100, 0, 100)}%` }}
          title={`Bereich ${secondsToClock(selection.start, true)} – ${secondsToClock(selection.end, true)}`}
        />
      ) : null}
      {markers.map((marker, index) => (
        <button
          key={marker.id || index}
          type="button"
          className={`daw-marker daw-marker-${marker.type || 'marker'}`}
          style={{ left: pct(marker.time) }}
          title={`${marker.label} · ${secondsToClock(marker.time, true)}${marker.note ? ` · ${marker.note}` : ''}`}
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => onMarkerClick?.(event, marker, index)}
        >
          {marker.label}
        </button>
      ))}
      {snapGuide ? (
        <div className="daw-snap-guide" style={{ left: pct(snapGuide.time) }}>
          <span>{snapGuide.label}</span>
        </div>
      ) : null}
    </div>
  );
})
