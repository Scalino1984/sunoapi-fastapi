import React, { useMemo } from 'react';
import { safeNumber, clamp } from '../timeUtils.js';

// Zeichnet die Waveform eines Clips als SVG. Die Peaks kommen aus dem
// bestehenden waveform_json des Quell-Assets (Backend: waveform_service) und
// werden proportional auf den Quellbereich (source_start..source_end)
// zugeschnitten – kein zusätzlicher Server-Roundtrip nötig.
export function ClipWaveform({ peaks = [], sourceStart = 0, sourceEnd = 1, sourceDuration = 0, height = 44 }) {
  const bars = useMemo(() => {
    const rows = Array.isArray(peaks) ? peaks : [];
    if (!rows.length || !sourceDuration) return [];
    const total = rows.length;
    const startIndex = clamp(Math.floor((safeNumber(sourceStart) / sourceDuration) * total), 0, total - 1);
    const endIndex = clamp(Math.ceil((safeNumber(sourceEnd) / sourceDuration) * total), startIndex + 1, total);
    return rows.slice(startIndex, endIndex);
  }, [peaks, sourceStart, sourceEnd, sourceDuration]);

  if (!bars.length) return <div className="daw-clip-wave daw-clip-wave-empty" />;
  const width = Math.max(1, bars.length);
  const mid = height / 2;
  const path = bars
    .map((value, index) => {
      const amp = Math.max(1.2, clamp(safeNumber(value), 0, 1) * (mid - 1.5));
      return `M ${index + 0.5} ${mid - amp} L ${index + 0.5} ${mid + amp}`;
    })
    .join(' ');
  return (
    <svg className="daw-clip-wave" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
      <path d={path} />
    </svg>
  );
}
