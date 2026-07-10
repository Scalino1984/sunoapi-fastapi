import React, { useEffect, useRef } from 'react';
import { clamp, safeNumber } from '../timeUtils.js';
import { useDawStore } from '../store.js';

// Flüssiger Playhead als eigene Ebene: Position wird bei Wiedergabe direkt per
// requestAnimationFrame aus der Audio-Engine gelesen und ins DOM geschrieben –
// ohne React-Re-Render. Der Rest der DAW bekommt Zeit-Updates nur gedrosselt
// (~11 Hz) über den Store. Optional folgt der Scroll-Container dem Playhead.
export const PlayheadLayer = React.memo(function PlayheadLayer({ engine, duration, scrollRef, follow }) {
  const nodeRef = useRef(null);
  const followRef = useRef(follow);
  followRef.current = follow;
  // Pausiert/gestoppt: Position kommt aus dem Store (Seek, Marker, Stop).
  const pausedTime = useDawStore((state) => (state.isPlaying ? null : state.currentTime));

  useEffect(() => {
    const applyPosition = (time) => {
      const node = nodeRef.current;
      if (!node) return;
      const pct = clamp((safeNumber(time) / Math.max(duration, 0.001)) * 100, 0, 100);
      node.style.left = `${pct}%`;
    };
    const followPlayhead = (time) => {
      const scroller = scrollRef?.current;
      if (!scroller || !followRef.current) return;
      const px = (safeNumber(time) / Math.max(duration, 0.001)) * scroller.scrollWidth;
      const viewStart = scroller.scrollLeft;
      const viewEnd = viewStart + scroller.clientWidth;
      if (px > viewEnd - scroller.clientWidth * 0.12 || px < viewStart) {
        scroller.scrollLeft = Math.max(0, px - scroller.clientWidth * 0.2);
      }
    };
    let raf = 0;
    const tick = () => {
      if (engine?.playing) {
        const time = engine.currentTime();
        applyPosition(time);
        followPlayhead(time);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [engine, duration, scrollRef]);

  // Positionsupdate im pausierten Zustand (Seek per Ruler, Marker 1–9, Stop).
  useEffect(() => {
    if (pausedTime === null) return;
    const node = nodeRef.current;
    if (!node) return;
    node.style.left = `${clamp((safeNumber(pausedTime) / Math.max(duration, 0.001)) * 100, 0, 100)}%`;
  }, [pausedTime, duration]);

  return (
    <div ref={nodeRef} className="daw-playhead-layer" aria-hidden="true">
      <span className="daw-playhead-cap" />
    </div>
  );
});
