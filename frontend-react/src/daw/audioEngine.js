// DawAudioEngine – Echtzeit-Wiedergabe des Arrangements über die Web Audio API.
//
// Warum: Bisher brauchte jede Multi-Clip-Änderung erst einen Server-Render
// (ffmpeg-Preview), bevor man sie hören konnte. Diese Engine spielt das
// Arrangement direkt im Browser ab – sample-genau, mit Clip-Gain, Fades,
// Track-Volume, Mute und Solo. Der Server-Render bleibt für Export und
// finale Versionen zuständig (bestehende Endpunkte unverändert).
//
// Architektur:
//   AudioBufferSourceNode (pro Clip) -> clipGain (Fades + gain_db)
//     -> trackGain (volume_db, Mute/Solo) -> masterGain -> destination
//
// Buffers werden pro source_audio_id dekodiert und gecacht. Geladen wird über
// die bestehende Stream-Route (api.archive.streamUrl) – die vorhandene
// Audio-Lade-Logik (lokale Pfade, public_url, Cache-Status) bleibt damit
// vollständig die einzige Quelle der Wahrheit.

import { safeNumber, clamp, clipDuration } from './timeUtils.js';

const dbToGain = (db) => Math.pow(10, safeNumber(db) / 20);

export class DawAudioEngine {
  constructor({ resolveClipUrl } = {}) {
    this.resolveClipUrl = resolveClipUrl || (() => null);
    this.context = null;
    this.masterGain = null;
    this.buffers = new Map(); // source_audio_id -> AudioBuffer
    this.bufferPromises = new Map(); // source_audio_id -> Promise
    this.activeNodes = [];
    this.trackGains = new Map();
    this.arrangement = null;
    this.playing = false;
    this.startedAtContextTime = 0;
    this.startedAtTimelineTime = 0;
    this.pausedAt = 0;
    this.volume = 1;
    this.onTick = null;
    this.onEnded = null;
    this._raf = 0;
    this._lastTickEmit = 0;
    this.peakCache = new Map(); // `${source_audio_id}:${points}` -> normierte Peaks
  }

  ensureContext() {
    if (!this.context) {
      const Ctor = window.AudioContext || window.webkitAudioContext;
      if (!Ctor) throw new Error('Web Audio wird von diesem Browser nicht unterstützt.');
      this.context = new Ctor({ latencyHint: 'interactive' });
      this.masterGain = this.context.createGain();
      this.masterGain.gain.value = this.volume;
      this.masterGain.connect(this.context.destination);
    }
    return this.context;
  }

  setVolume(value) {
    this.volume = clamp(safeNumber(value, 1), 0, 1.5);
    if (this.masterGain) this.masterGain.gain.setTargetAtTime(this.volume, this.context.currentTime, 0.01);
  }

  // ---- Buffer laden ------------------------------------------------------
  async loadBuffer(sourceAudioId) {
    const key = String(sourceAudioId);
    if (this.buffers.has(key)) return this.buffers.get(key);
    if (this.bufferPromises.has(key)) return this.bufferPromises.get(key);
    const context = this.ensureContext();
    const url = this.resolveClipUrl(sourceAudioId);
    if (!url) throw new Error(`Keine Audio-Quelle für Asset ${sourceAudioId} gefunden.`);
    const promise = (async () => {
      const response = await fetch(url, { credentials: 'include' });
      if (!response.ok) throw new Error(`Audio ${sourceAudioId} konnte nicht geladen werden (HTTP ${response.status}).`);
      const arrayBuffer = await response.arrayBuffer();
      const buffer = await context.decodeAudioData(arrayBuffer);
      this.buffers.set(key, buffer);
      this.bufferPromises.delete(key);
      return buffer;
    })();
    this.bufferPromises.set(key, promise);
    return promise;
  }

  async prepareArrangement(arrangement) {
    this.arrangement = arrangement;
    const ids = [...new Set((arrangement?.clips || []).map((clip) => String(clip.source_audio_id)))];
    await Promise.all(ids.map((id) => this.loadBuffer(id).catch((err) => {
      // Einzelne fehlende Quellen brechen die Wiedergabe nicht komplett ab.
      console.warn('[DAW] Buffer konnte nicht geladen werden:', id, err);
      return null;
    })));
  }

  hasBuffer(sourceAudioId) {
    return this.buffers.has(String(sourceAudioId));
  }

  // Hochauflösende Peaks aus dem dekodierten AudioBuffer berechnen (gecacht).
  // Ersetzt beim Zoomen die groben 180-Punkte-Peaks aus waveform_json.
  peaksFor(sourceAudioId, points = 1600) {
    const key = `${sourceAudioId}:${points}`;
    if (this.peakCache.has(key)) return this.peakCache.get(key);
    const buffer = this.buffers.get(String(sourceAudioId));
    if (!buffer) return null;
    const left = buffer.getChannelData(0);
    const right = buffer.numberOfChannels > 1 ? buffer.getChannelData(1) : null;
    const bucket = Math.max(1, Math.floor(left.length / points));
    const stride = Math.max(1, Math.floor(bucket / 64)); // Sampling statt Vollscan
    const peaks = new Array(points).fill(0);
    let maxPeak = 0.0001;
    for (let index = 0; index < points; index += 1) {
      const start = index * bucket;
      const end = Math.min(left.length, start + bucket);
      let max = 0;
      for (let j = start; j < end; j += stride) {
        const a = Math.abs(left[j]);
        if (a > max) max = a;
        if (right) {
          const b = Math.abs(right[j]);
          if (b > max) max = b;
        }
      }
      peaks[index] = max;
      if (max > maxPeak) maxPeak = max;
    }
    const normalized = peaks.map((value) => value / maxPeak);
    this.peakCache.set(key, normalized);
    return normalized;
  }

  // ---- Scheduling --------------------------------------------------------
  _teardownNodes() {
    this.activeNodes.forEach(({ source }) => {
      try { source.onended = null; source.stop(); } catch { /* bereits gestoppt */ }
      try { source.disconnect(); } catch { /* noop */ }
    });
    this.activeNodes = [];
    this.trackGains.forEach((gain) => { try { gain.disconnect(); } catch { /* noop */ } });
    this.trackGains.clear();
  }

  _buildTrackGains(arrangement) {
    const anySolo = (arrangement.tracks || []).some((track) => track.solo);
    (arrangement.tracks || []).forEach((track) => {
      const gain = this.context.createGain();
      const audible = !track.muted && (!anySolo || track.solo);
      gain.gain.value = audible ? dbToGain(track.volume_db) : 0;
      gain.connect(this.masterGain);
      this.trackGains.set(track.id, gain);
    });
  }

  _scheduleClip(clip, fromTime, contextStartTime) {
    const buffer = this.buffers.get(String(clip.source_audio_id));
    if (!buffer || clip.muted) return;
    const trackGain = this.trackGains.get(clip.track_id) || this.masterGain;
    const clipStart = safeNumber(clip.timeline_start);
    const duration = clipDuration(clip);
    const clipEnd = clipStart + duration;
    if (clipEnd <= fromTime + 0.002) return; // liegt komplett vor dem Playhead

    const intoClip = Math.max(0, fromTime - clipStart); // Offset, falls Playhead im Clip startet
    const when = contextStartTime + Math.max(0, clipStart - fromTime);
    const sourceOffset = clamp(safeNumber(clip.source_start) + intoClip, 0, buffer.duration);
    const playDuration = Math.max(0.01, Math.min(duration - intoClip, buffer.duration - sourceOffset));

    const source = this.context.createBufferSource();
    source.buffer = buffer;
    const clipGain = this.context.createGain();
    source.connect(clipGain);
    clipGain.connect(trackGain);

    // Gain + Fades relativ zur Timeline-Position des Clips planen.
    const baseGain = dbToGain(clip.gain_db);
    const fadeIn = clamp(safeNumber(clip.fade_in), 0, duration);
    const fadeOut = clamp(safeNumber(clip.fade_out), 0, duration);
    const g = clipGain.gain;
    g.cancelScheduledValues(0);
    const clipContextStart = contextStartTime + (clipStart - fromTime); // kann < now sein, wenn intoClip > 0
    if (fadeIn > 0 && intoClip < fadeIn) {
      const startLevel = baseGain * (intoClip / fadeIn);
      g.setValueAtTime(Math.max(0.0001, startLevel), when);
      g.linearRampToValueAtTime(baseGain, clipContextStart + fadeIn);
    } else {
      g.setValueAtTime(baseGain, when);
    }
    if (fadeOut > 0) {
      const fadeOutStart = clipContextStart + duration - fadeOut;
      if (fadeOutStart > when) {
        g.setValueAtTime(baseGain, fadeOutStart);
        g.linearRampToValueAtTime(0.0001, clipContextStart + duration);
      } else {
        // Playhead startet mitten im Fade-out.
        const remaining = clipEnd - fromTime;
        const level = baseGain * clamp(remaining / fadeOut, 0, 1);
        g.setValueAtTime(Math.max(0.0001, level), when);
        g.linearRampToValueAtTime(0.0001, when + Math.max(0.01, remaining));
      }
    }

    source.start(when, sourceOffset, playDuration);
    this.activeNodes.push({ source, clipGain, clipId: clip.id });
  }

  async play(arrangement, fromTime = 0) {
    const context = this.ensureContext();
    if (context.state === 'suspended') await context.resume();
    await this.prepareArrangement(arrangement);
    this.stop({ keepPosition: true, silent: true });
    this._buildTrackGains(arrangement);

    const startAt = context.currentTime + 0.06; // kleiner Vorlauf für sauberes Scheduling
    (arrangement.clips || []).forEach((clip) => this._scheduleClip(clip, fromTime, startAt));

    this.playing = true;
    this.startedAtContextTime = startAt;
    this.startedAtTimelineTime = fromTime;
    this.pausedAt = fromTime;
    this._startTicker(arrangement);
  }

  _startTicker(arrangement) {
    const totalLength = Math.max(
      safeNumber(arrangement.duration_seconds),
      ...(arrangement.clips || []).map((clip) => safeNumber(clip.timeline_start) + clipDuration(clip)),
      0.1,
    );
    const tick = () => {
      if (!this.playing) return;
      const now = this.currentTime();
      // Store-Updates drosseln (~11 Hz): flüssige Playhead-Bewegung übernimmt
      // die PlayheadLayer-Komponente direkt per requestAnimationFrame.
      const wall = performance.now();
      if (wall - this._lastTickEmit > 90) {
        this._lastTickEmit = wall;
        this.onTick?.(now);
      }
      if (now >= totalLength - 0.01) {
        this.stop({ keepPosition: false });
        this.onTick?.(0);
        this.onEnded?.();
        return;
      }
      this._raf = requestAnimationFrame(tick);
    };
    cancelAnimationFrame(this._raf);
    this._raf = requestAnimationFrame(tick);
  }

  currentTime() {
    if (!this.playing || !this.context) return this.pausedAt;
    return Math.max(0, this.startedAtTimelineTime + (this.context.currentTime - this.startedAtContextTime));
  }

  pause() {
    if (!this.playing) return this.pausedAt;
    this.pausedAt = this.currentTime();
    this.playing = false;
    cancelAnimationFrame(this._raf);
    this._teardownNodes();
    return this.pausedAt;
  }

  stop({ keepPosition = false, silent = false } = {}) {
    if (this.playing) this.pausedAt = keepPosition ? this.currentTime() : 0;
    else if (!keepPosition) this.pausedAt = 0;
    this.playing = false;
    cancelAnimationFrame(this._raf);
    this._teardownNodes();
    if (!silent) this.onTick?.(this.pausedAt);
  }

  async seek(arrangement, time) {
    const wasPlaying = this.playing;
    this.pausedAt = Math.max(0, safeNumber(time));
    if (wasPlaying) await this.play(arrangement, this.pausedAt);
    else this.onTick?.(this.pausedAt);
  }

  // Laufende Wiedergabe an geändertes Arrangement anpassen (z. B. nach Undo,
  // Clip-Drag oder KI-Kommando), ohne die Position zu verlieren.
  async refresh(arrangement) {
    if (!this.playing) { this.arrangement = arrangement; return; }
    const position = this.currentTime();
    await this.play(arrangement, position);
  }

  dispose() {
    this.stop({ silent: true });
    this.buffers.clear();
    this.bufferPromises.clear();
    this.peakCache.clear();
    if (this.context) { try { this.context.close(); } catch { /* noop */ } }
    this.context = null;
    this.masterGain = null;
  }
}
