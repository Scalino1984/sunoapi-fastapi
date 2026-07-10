import { useCallback, useRef } from 'react';

export function usePointerDrag(onMove, onEnd) {
  const state = useRef(null);
  useEffect(() => {
    function handleMove(event) {
      if (!state.current) return;
      onMove(event, state.current);
    }
    function handleEnd(event) {
      if (!state.current) return;
      const current = state.current;
      state.current = null;
      onEnd?.(event, current);
    }
    window.addEventListener('pointermove', handleMove);
    window.addEventListener('pointerup', handleEnd);
    window.addEventListener('pointercancel', handleEnd);
    return () => {
      window.removeEventListener('pointermove', handleMove);
      window.removeEventListener('pointerup', handleEnd);
      window.removeEventListener('pointercancel', handleEnd);
    };
  }, [onMove, onEnd]);
  return state;
}
