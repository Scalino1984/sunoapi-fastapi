import { useCallback, useEffect, useRef, useState } from 'react';
import { arrangementDuration, clipDuration, safeNumber } from './dawMath.js';
import { api } from '../api/client.js';

function assetUrl(asset) {
  if (!asset) return '';
  if (asset.id) return api.archive.streamUrl(asset.id);
  return asset.public_url || asset.source_url || '';
}

async function decodeAudioBuffer(context, url) {
  const response = await fetch(url, { credentials: 'include' });
  if (!response.ok) throw new Error(`Audio konnte nicht geladen werden (${response.status}).`);
  const buffer = await response.arrayBuffer();
  return context.decodeAudioData(buffer);
}

export function useDawAudioEngine({ arrangement, assetsById, primaryAsset, onTime }) {
  const contextRef = useRef(null);
  const buffersRef = useRef(new Map());
  const sourcesRef = useRef([]);
  const startedAtRef = useRef(0);
  const offsetRef = useRef(0);
  const rafRef = useRef(0);
  const arrangementRef = useRef(arrangement);
  const onTimeRef = useRef(onTime);
  const [isPlaying, setIsPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => { arrangementRef.current = arrangement; }, [arrangement]);
  useEffect(() => { onTimeRef.current = onTime; }, [onTime]);

  const stopScheduled = useCallback(() => {
    sourcesRef.current.forEach((node) => {
      try { node.stop(0); } catch (_) { /* already stopped */ }
      try { node.disconnect(); } catch (_) { /* already disconnected */ }
    });
    sourcesRef.current = [];
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = 0;
  }, []);

  const ensureContext = useCallback(() => {
    if (!contextRef.current) {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) throw new Error('Web Audio API wird von diesem Browser nicht unterstützt.');
      contextRef.current = new AudioContextClass();
    }
    return contextRef.current;
  }, []);

  const ensureBuffer = useCallback(async (assetId) => {
    const numeric = Number(assetId || primaryAsset?.id || 0);
    if (buffersRef.current.has(numeric)) return buffersRef.current.get(numeric);
    const asset = assetsById.get(numeric) || primaryAsset;
    const url = assetUrl(asset);
    if (!url) throw new Error('Für einen Clip fehlt die Audio-URL.');
    const context = ensureContext();
    const buffer = await decodeAudioBuffer(context, url);
    buffersRef.current.set(numeric, buffer);
    return buffer;
  }, [assetsById, ensureContext, primaryAsset]);

  const tick = useCallback(() => {
    const context = contextRef.current;
    if (!context) return;
    const now = Math.max(0, context.currentTime - startedAtRef.current + offsetRef.current);
    onTimeRef.current?.(now);
    const total = arrangementDuration(arrangementRef.current, primaryAsset?.duration_seconds || 1);
    if (now >= total + 0.05) {
      stopScheduled();
      setIsPlaying(false);
      onTimeRef.current?.(0);
      return;
    }
    rafRef.current = requestAnimationFrame(tick);
  }, [primaryAsset?.duration_seconds, stopScheduled]);

  const pause = useCallback(() => {
    const context = contextRef.current;
    if (context && isPlaying) {
      offsetRef.current = Math.max(0, context.currentTime - startedAtRef.current + offsetRef.current);
    }
    stopScheduled();
    setIsPlaying(false);
  }, [isPlaying, stopScheduled]);

  const play = useCallback(async (offset = offsetRef.current || 0) => {
    const currentArrangement = arrangementRef.current;
    if (!currentArrangement?.clips?.length) return;
    setLoading(true);
    setError('');
    try {
      const context = ensureContext();
      if (context.state === 'suspended') await context.resume();
      stopScheduled();
      offsetRef.current = Math.max(0, safeNumber(offset));
      startedAtRef.current = context.currentTime;
      const soloTracks = new Set((currentArrangement.tracks || []).filter((track) => track.solo).map((track) => track.id));
      const mutedTracks = new Set((currentArrangement.tracks || []).filter((track) => track.muted).map((track) => track.id));
      const clips = (currentArrangement.clips || [])
        .filter((clip) => !clip.muted)
        .filter((clip) => !mutedTracks.has(clip.track_id))
        .filter((clip) => !soloTracks.size || soloTracks.has(clip.track_id));
      for (const clip of clips) {
        const timelineStart = safeNumber(clip.timeline_start);
        const duration = clipDuration(clip);
        const timelineEnd = timelineStart + duration;
        if (timelineEnd <= offsetRef.current) continue;
        const buffer = await ensureBuffer(clip.source_audio_id || currentArrangement.source_audio_id);
        const source = context.createBufferSource();
        const gain = context.createGain();
        source.buffer = buffer;
        const clipGain = Math.pow(10, safeNumber(clip.gain_db) / 20);
        gain.gain.setValueAtTime(clipGain, context.currentTime);
        const relativeStart = Math.max(0, timelineStart - offsetRef.current);
        const requestedOffset = safeNumber(clip.source_start) + Math.max(0, offsetRef.current - timelineStart);
        const trimOffset = Math.max(0, Math.min(Math.max(0, buffer.duration - 0.02), requestedOffset));
        const requestedDuration = Math.max(0.02, duration - Math.max(0, offsetRef.current - timelineStart));
        const playableDuration = Math.max(0.02, Math.min(requestedDuration, Math.max(0.02, buffer.duration - trimOffset)));
        const startTime = context.currentTime + relativeStart;
        const fadeIn = Math.min(safeNumber(clip.fade_in), playableDuration);
        const fadeOut = Math.min(safeNumber(clip.fade_out), playableDuration);
        if (fadeIn > 0 && offsetRef.current <= timelineStart + fadeIn) {
          gain.gain.setValueAtTime(0.0001, startTime);
          gain.gain.linearRampToValueAtTime(clipGain, startTime + fadeIn);
        }
        if (fadeOut > 0) {
          const fadeOutStart = Math.max(startTime, startTime + playableDuration - fadeOut);
          gain.gain.setValueAtTime(clipGain, fadeOutStart);
          gain.gain.linearRampToValueAtTime(0.0001, startTime + playableDuration);
        }
        source.connect(gain).connect(context.destination);
        source.start(startTime, trimOffset, playableDuration);
        sourcesRef.current.push(source);
      }
      setIsPlaying(true);
      rafRef.current = requestAnimationFrame(tick);
    } catch (exc) {
      stopScheduled();
      setError(exc?.message || 'Playback konnte nicht gestartet werden.');
      setIsPlaying(false);
    } finally {
      setLoading(false);
    }
  }, [ensureBuffer, ensureContext, stopScheduled, tick]);

  const seek = useCallback((time) => {
    const value = Math.max(0, safeNumber(time));
    offsetRef.current = value;
    onTimeRef.current?.(value);
    if (isPlaying) void play(value);
  }, [isPlaying, play]);

  const toggle = useCallback(() => {
    if (isPlaying) pause();
    else void play(offsetRef.current);
  }, [isPlaying, pause, play]);

  useEffect(() => () => {
    stopScheduled();
    try { contextRef.current?.close?.(); } catch (_) { /* noop */ }
  }, [stopScheduled]);

  return { isPlaying, loading, error, play, pause, toggle, seek };
}
