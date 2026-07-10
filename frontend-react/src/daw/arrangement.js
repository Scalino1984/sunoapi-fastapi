// Arrangement-Modell + Kommandoplaner der Mini-DAW.
// createDawCommandPlan ist der eine, geprüfte Ort für alle Timeline-Mutationen
// (Schneiden, Duplizieren, Abschnitts-Operationen, Lücken schließen, ...).
// Die Semantik ist ein Verbatim-Port aus der bisherigen DawPage – jetzt pur,
// testbar und sowohl von UI-Buttons als auch von der DAW-KI nutzbar.
import {
  clamp,
  safeNumber,
  clipDuration,
  cloneArrangementSnapshot,
  makeId,
  sortMarkers,
  secondsToClock,
  arrangementLength,
  normalizeFadePair,
} from './timeUtils.js';
import {
  inferBpmFromAsset,
  deriveBarGridOffset,
  snapToMusicalBar,
  estimateMusicalBarsForSection,
  dawBeatgridRangeForSection,
  dawBeatgridBoundaries,
  medianBarLengthFromGrid,
} from './musicalTime.js';
import { pickTitle } from '../utils.js';

export const TRACKS = [
  { id: 'track-1', name: 'Spur 1' },
  { id: 'track-2', name: 'Spur 2' },
  { id: 'track-3', name: 'Spur 3' },
];
export const MAX_TRACKS = 8;
export const SNAP_UNITS = [
  { id: 'bar', label: 'Takt' },
  { id: 'beat', label: 'Beat' },
  { id: 'half', label: '1/2' },
  { id: 'quarter', label: '1/4' },
];
export const CLIP_COLORS = ['cyan', 'violet', 'emerald', 'amber', 'rose', 'sky'];

export function buildDefaultArrangement(asset, duration = 0) {
  const safeDuration = Math.max(1, safeNumber(duration || asset?.duration_seconds, 1));
  const title = pickTitle(asset) || `Audio ${asset?.id || ''}`;
  const inferredBpm = inferBpmFromAsset(asset);
  return {
    version: 1,
    source_audio_id: Number(asset?.id || 0),
    duration_seconds: safeDuration,
    bpm: inferredBpm,
    time_signature: '4/4',
    snap_enabled: false,
    snap_unit: 'beat',
    tracks: TRACKS.map((track) => ({ ...track, muted: false, solo: false, volume_db: 0 })),
    clips: [{
      id: makeId('clip'),
      track_id: 'track-1',
      source_audio_id: Number(asset?.id || 0),
      timeline_start: 0,
      source_start: 0,
      source_end: safeDuration,
      gain_db: 0,
      fade_in: 0,
      fade_out: 0,
      label: title,
      muted: false,
      locked: false,
      color: 'cyan',
    }],
    markers: [],
  };
}

export function normalizeArrangement(raw, asset, duration = 0) {
  const base = buildDefaultArrangement(asset, duration);
  if (!raw || typeof raw !== 'object') return base;
  const tracks = Array.isArray(raw.tracks) && raw.tracks.length ? raw.tracks.slice(0, 8) : base.tracks;
  const validTrackIds = new Set(tracks.map((track, index) => track?.id || `track-${index + 1}`));
  const sourceDuration = Math.max(0, safeNumber(duration || asset?.duration_seconds, 0));
  const minClipLength = 0.25;
  const clips = (Array.isArray(raw.clips) ? raw.clips : base.clips).map((clip, index) => {
    let sourceStart = Math.max(0, safeNumber(clip?.source_start));
    let sourceEnd = safeNumber(clip?.source_end, sourceStart + 1);
    if (sourceDuration > minClipLength) {
      sourceStart = clamp(sourceStart, 0, Math.max(0, sourceDuration - minClipLength));
      sourceEnd = clamp(sourceEnd, sourceStart + minClipLength, sourceDuration);
    }
    if (sourceEnd <= sourceStart) sourceEnd = sourceStart + minClipLength;
    const trackId = validTrackIds.has(clip?.track_id) ? clip.track_id : 'track-1';
    const fades = normalizeFadePair(clip?.fade_in, clip?.fade_out, sourceEnd - sourceStart);
    return {
      id: String(clip?.id || makeId(`clip-${index + 1}`)),
      track_id: trackId,
      source_audio_id: Number(clip?.source_audio_id || asset?.id || 0),
      timeline_start: Math.max(0, safeNumber(clip?.timeline_start)),
      source_start: sourceStart,
      source_end: sourceEnd,
      gain_db: clamp(safeNumber(clip?.gain_db), -24, 24),
      fade_in: fades.fadeIn,
      fade_out: fades.fadeOut,
      label: String(clip?.label || pickTitle(asset) || `Clip ${index + 1}`),
      muted: Boolean(clip?.muted),
      locked: Boolean(clip?.locked),
      color: String(clip?.color || 'cyan'),
    };
  });
  return {
    ...base,
    ...raw,
    source_audio_id: Number(asset?.id || raw.source_audio_id || 0),
    duration_seconds: arrangementLength({ ...raw, clips }, base.duration_seconds),
    tracks: tracks.map((track, index) => ({
      id: String(track?.id || `track-${index + 1}`),
      name: String(track?.name || `Spur ${index + 1}`),
      muted: Boolean(track?.muted),
      solo: Boolean(track?.solo),
      volume_db: clamp(safeNumber(track?.volume_db), -24, 24),
    })),
    clips,
    markers: sortMarkers((Array.isArray(raw.markers) ? raw.markers : []).map((marker, index) => ({
      id: String(marker?.id || makeId(`marker-${index + 1}`)),
      label: String(marker?.label || 'Marker'),
      time: Math.max(0, safeNumber(marker?.time)),
      type: String(marker?.type || 'marker'),
      note: marker?.note || null,
    }))),
    snap_enabled: Boolean(raw.snap_enabled),
    snap_unit: ['bar', 'beat', 'half', 'quarter'].includes(raw.snap_unit) ? raw.snap_unit : 'beat',
    bpm: raw.bpm ? clamp(safeNumber(raw.bpm), 20, 300) : base.bpm,
  };
}

  export function createDawCommandPlan(command = {}, ctx = {}) {
  const {
    arrangement,
    asset: currentAsset,
    sections: resolvedSections = [],
    selectedSection = null,
    beatgrid: activeBeatgrid = null,
    selection = null,
    selectedClipId = '',
    currentTime = 0,
    closeGap = true,
    sourceDuration = 0,
    mediaDuration = 0,
    timelineDuration = 0,
    snapTime = (value) => Number(value || 0),
  } = ctx;
    const base = normalizeArrangement(arrangement, currentAsset, timelineDuration || mediaDuration || currentAsset?.duration_seconds || 1);
    const original = cloneArrangementSnapshot(base);
    const next = cloneArrangementSnapshot(base);
    if (!original || !next) throw new Error('Kein Arrangement geladen.');

    const commandType = String(command.type || '').trim();
    const actions = [];
    const warnings = Array.isArray(command.warnings) ? command.warnings.filter(Boolean) : [];
    let title = 'DAW-Kommando';
    let summary = 'Geplante Änderung prüfen und danach anwenden.';
    let nextSelectedClipId = selectedClipId;
    let nextSelection = selection ? { ...selection } : null;
    let guideTime = null;
    let guideLabel = '';

    const beforeDuration = arrangementLength(base, mediaDuration || currentAsset?.duration_seconds || 1);
    const findClipById = (id) => next.clips.find((clip) => clip.id === id) || null;
    const findClipAt = (time, explicitClipId = '') => {
      const direct = explicitClipId ? findClipById(explicitClipId) : null;
      if (direct) return direct;
      return next.clips.find((clip) => {
        const start = safeNumber(clip.timeline_start);
        const end = start + clipDuration(clip);
        return time > start + 0.001 && time < end - 0.001;
      }) || null;
    };
    const markArrangementChanged = () => {
      next.duration_seconds = arrangementLength(next, beforeDuration);
      next.clips = next.clips.map((clip) => ({ ...clip }));
      next.markers = sortMarkers(next.markers || []);
    };
    const adjacentFor = (clip, direction) => {
      if (!clip) return null;
      const start = safeNumber(clip.timeline_start);
      const end = start + clipDuration(clip);
      const candidates = (next.clips || [])
        .filter((candidate) => candidate.id !== clip.id && candidate.track_id === clip.track_id)
        .map((candidate) => {
          const candidateStart = safeNumber(candidate.timeline_start);
          const candidateEnd = candidateStart + clipDuration(candidate);
          return { ...candidate, candidateStart, candidateEnd };
        });
      if (direction === 'previous') {
        return candidates.filter((candidate) => candidate.candidateEnd <= start + 0.02).sort((a, b) => b.candidateEnd - a.candidateEnd)[0] || null;
      }
      return candidates.filter((candidate) => candidate.candidateStart >= end - 0.02).sort((a, b) => a.candidateStart - b.candidateStart)[0] || null;
    };
    const selectedId = command.clipId || selectedClipId;
    const resolveCommandSection = () => {
      const section = command.section || resolvedSections.find((item) => item.id === command.sectionId) || selectedSection;
      if (!section) throw new Error('Bitte zuerst einen Songabschnitt auswählen.');
      const start = clamp(safeNumber(section.start), 0, beforeDuration);
      const end = clamp(safeNumber(section.end), start + 0.25, beforeDuration);
      if (end - start < 0.25) throw new Error('Der ausgewählte Abschnitt ist zu kurz.');
      return { ...section, start, end, duration: end - start, displayLabel: section.displayLabel || section.label || 'Abschnitt' };
    };
    const resolveMusicalSectionRange = (section) => {
      const rawStart = clamp(safeNumber(section.start), 0, sourceDuration || beforeDuration);
      const rawEnd = clamp(safeNumber(section.end), rawStart + 0.25, sourceDuration || beforeDuration);
      const gridRange = dawBeatgridRangeForSection(section, activeBeatgrid, sourceDuration || beforeDuration);
      if (gridRange) return gridRange;
      const bpm = safeNumber(next.bpm || base.bpm || inferBpmFromAsset(currentAsset), 0);
      if (!bpm || bpm < 20) {
        return { start: rawStart, end: rawEnd, bars: null, bpm: null, adjusted: false, label: '', source: 'raw' };
      }
      const barLength = 240 / bpm;
      const offset = deriveBarGridOffset(resolvedSections, bpm, rawStart);
      const snappedStart = snapToMusicalBar(rawStart, bpm, offset, sourceDuration || beforeDuration);
      const snappedEnd = snapToMusicalBar(rawEnd, bpm, offset, sourceDuration || beforeDuration);
      const barEstimate = estimateMusicalBarsForSection(section, bpm);
      let candidates = [{
        start: snappedStart,
        end: Math.max(snappedStart + 0.25, snappedEnd),
        bars: null,
      }];
      if (barEstimate) {
        const targetLength = barEstimate.expected;
        candidates = [
          { start: snappedStart, end: snappedStart + targetLength, bars: barEstimate.bars },
          { start: snappedEnd - targetLength, end: snappedEnd, bars: barEstimate.bars },
          { start: snappedStart, end: snappedEnd, bars: barEstimate.bars },
        ];
      }
      const maxEnd = sourceDuration || beforeDuration;
      const valid = candidates
        .map((item) => ({
          ...item,
          start: clamp(item.start, 0, Math.max(0, maxEnd - 0.25)),
          end: clamp(item.end, 0.25, maxEnd),
        }))
        .filter((item) => item.end - item.start >= 0.25)
        .map((item) => ({
          ...item,
          score: Math.abs(item.start - rawStart) + Math.abs(item.end - rawEnd) + (item.bars ? 0 : 0.15),
        }))
        .sort((a, b) => a.score - b.score);
      const best = valid[0] || { start: rawStart, end: rawEnd, bars: null };
      const adjusted = Math.abs(best.start - rawStart) > 0.04 || Math.abs(best.end - rawEnd) > 0.04;
      return {
        start: best.start,
        end: best.end,
        bars: best.bars,
        bpm,
        adjusted,
        source: 'bpm_fallback',
        label: adjusted
          ? `Takt-Schnitt: ${secondsToClock(rawStart, true)} – ${secondsToClock(rawEnd, true)} → ${secondsToClock(best.start, true)} – ${secondsToClock(best.end, true)}${best.bars ? ` (${best.bars} Takte` : ''}${bpm ? `, ${Math.round(bpm * 10) / 10} BPM` : ''}${best.bars ? ')' : ''}`
          : '',
      };
    };
    const extractRangeClipParts = (rangeStart, rangeEnd, insertAt, sectionLabel) => {
      const pieces = [];
      (base.clips || []).forEach((clip) => {
        if (clip.locked) return;
        const clipStart = safeNumber(clip.timeline_start);
        const clipEnd = clipStart + clipDuration(clip);
        const overlapStart = Math.max(rangeStart, clipStart);
        const overlapEnd = Math.min(rangeEnd, clipEnd);
        if (overlapEnd - overlapStart <= 0.05) return;
        pieces.push({
          ...clip,
          id: makeId('clip'),
          timeline_start: insertAt + (overlapStart - rangeStart),
          source_start: safeNumber(clip.source_start) + (overlapStart - clipStart),
          source_end: safeNumber(clip.source_start) + (overlapEnd - clipStart),
          label: `${sectionLabel} Kopie`,
          locked: false,
        });
      });
      if (!pieces.length && sourceDuration >= rangeEnd) {
        pieces.push({
          id: makeId('clip'),
          track_id: 'track-1',
          source_audio_id: Number(currentAsset?.id || base.source_audio_id || 0),
          timeline_start: insertAt,
          source_start: rangeStart,
          source_end: rangeEnd,
          gain_db: 0,
          fade_in: 0,
          fade_out: 0,
          label: `${sectionLabel} Kopie`,
          muted: false,
          locked: false,
          color: 'cyan',
        });
      }
      return pieces.sort((a, b) => safeNumber(a.timeline_start) - safeNumber(b.timeline_start));
    };
    const resolveFirstFullBarRange = (section, bars = 4) => {
      const requestedBars = Math.max(1, Math.min(64, safeNumber(bars, 4)));
      const rawStart = clamp(safeNumber(section.start), 0, sourceDuration || beforeDuration);
      const rawEnd = clamp(safeNumber(section.end), rawStart + 0.25, sourceDuration || beforeDuration);
      const maxDuration = sourceDuration || beforeDuration;
      const boundaries = dawBeatgridBoundaries(activeBeatgrid, maxDuration);
      if (boundaries.length >= 2) {
        let startIndex = boundaries.findIndex((value) => value >= rawStart - 0.035);
        if (startIndex < 0) startIndex = boundaries.length - 2;
        if (startIndex > 0 && Math.abs(boundaries[startIndex - 1] - rawStart) <= 0.05) startIndex -= 1;
        const endIndex = Math.min(boundaries.length - 1, startIndex + requestedBars);
        if (endIndex > startIndex) {
          const start = boundaries[startIndex];
          const end = boundaries[endIndex];
          if (end <= rawEnd + 0.12 || command.excludeTransitionPickup) {
            return {
              start,
              end,
              bars: endIndex - startIndex,
              source: activeBeatgrid?.source_label || activeBeatgrid?.source || 'Beatgrid-Downbeats',
              label: `Exakter Taktbereich: Taktgrenze ${startIndex + 1} bis ${endIndex + 1}`,
            };
          }
        }
      }
      const bpm = safeNumber(next.bpm || base.bpm || inferBpmFromAsset(currentAsset), 0);
      if (bpm >= 20) {
        const barLength = medianBarLengthFromGrid(activeBeatgrid) || 240 / bpm;
        const offset = deriveBarGridOffset(resolvedSections, bpm, rawStart);
        const start = snapToMusicalBar(rawStart, bpm, offset, maxDuration);
        return {
          start,
          end: clamp(start + requestedBars * barLength, start + 0.25, maxDuration),
          bars: requestedBars,
          source: 'BPM-Bar-Fallback',
          label: `BPM-Fallback: ${requestedBars} Takte bei ${Math.round(bpm * 10) / 10} BPM`,
        };
      }
      const fallbackLength = Math.max(0.25, (rawEnd - rawStart) * Math.min(1, requestedBars / 8));
      return {
        start: rawStart,
        end: clamp(rawStart + fallbackLength, rawStart + 0.25, rawEnd),
        bars: null,
        source: 'Struktur-Fallback',
        label: 'Keine stabile Bar-Map gefunden; Strukturzeit wurde verwendet.',
      };
    };
    const insertTimelineGap = (insertAt, gapLength) => {
      const minLength = 0.25;
      const nextClips = [];
      (next.clips || []).forEach((clip) => {
        if (clip.locked) {
          nextClips.push(clip);
          return;
        }
        const start = safeNumber(clip.timeline_start);
        const end = start + clipDuration(clip);
        if (end <= insertAt + 0.001) {
          nextClips.push(clip);
          return;
        }
        if (start >= insertAt - 0.001) {
          nextClips.push({ ...clip, timeline_start: start + gapLength });
          return;
        }
        const leftLength = insertAt - start;
        const rightLength = end - insertAt;
        if (leftLength >= minLength) {
          nextClips.push({ ...clip, id: makeId('clip'), source_end: safeNumber(clip.source_start) + leftLength });
        }
        if (rightLength >= minLength) {
          nextClips.push({
            ...clip,
            id: makeId('clip'),
            timeline_start: insertAt + gapLength,
            source_start: safeNumber(clip.source_start) + leftLength,
          });
        }
      });
      next.clips = nextClips;
      next.markers = (next.markers || []).map((marker) => safeNumber(marker.time) >= insertAt ? { ...marker, time: safeNumber(marker.time) + gapLength } : marker);
    };

    if (commandType === 'duplicate_musical_range') {
      const section = resolveCommandSection();
      const musicalRange = resolveFirstFullBarRange(section, command.bars || 4);
      const rangeStart = musicalRange.start;
      const rangeEnd = musicalRange.end;
      const rangeLength = rangeEnd - rangeStart;
      if (rangeLength <= 0.05) throw new Error('Der erkannte Taktbereich ist zu kurz.');
      const insertAt = rangeEnd;
      const copies = extractRangeClipParts(rangeStart, rangeEnd, insertAt, `${section.displayLabel} ${musicalRange.bars || command.bars || ''}T`);
      if (!copies.length) throw new Error('Für diesen Taktbereich konnten keine passenden Audioclips ermittelt werden.');
      if (command.ripple !== false) insertTimelineGap(insertAt, rangeLength);
      next.clips = [...(next.clips || []), ...copies].sort((a, b) => safeNumber(a.timeline_start) - safeNumber(b.timeline_start));
      nextSelectedClipId = copies[0]?.id || '';
      nextSelection = { start: insertAt, end: insertAt + rangeLength };
      guideTime = insertAt;
      guideLabel = `${section.displayLabel}: ${musicalRange.bars || command.bars || '?'} Takte kopiert`;
      title = `${section.displayLabel} taktgenau duplizieren`;
      summary = `${section.displayLabel}: ${secondsToClock(rangeStart, true)} – ${secondsToClock(rangeEnd, true)} wird direkt danach kopiert; der weitere Songverlauf wird nach rechts verschoben.`;
      actions.push(`Quelle: ${secondsToClock(rangeStart, true)} – ${secondsToClock(rangeEnd, true)}`);
      actions.push(`Einfügen direkt danach bei ${secondsToClock(insertAt, true)}`);
      actions.push(`${copies.length} Clip-Teil${copies.length === 1 ? '' : 'e'} kopiert`);
      if (command.ripple !== false) actions.push(`Bestehenden Songverlauf ab ${secondsToClock(insertAt, true)} um ${secondsToClock(rangeLength, true)} nach rechts verschoben`);
      if (command.excludeTransitionPickup) actions.push('Übergangsauftakt nach der Hook wird durch feste Taktlänge nicht mitkopiert');
      if (musicalRange.label) actions.push(musicalRange.label);
      if (musicalRange.source) actions.push(`Taktquelle: ${musicalRange.source}`);
      markArrangementChanged();
    } else if (commandType === 'clip_split') {
      const splitTime = snapTime(command.time ?? currentTime);
      const target = findClipAt(splitTime, selectedId);
      if (!target || target.locked) throw new Error('Kein Clip am Schnittpunkt gefunden.');
      const offset = splitTime - safeNumber(target.timeline_start);
      const length = clipDuration(target);
      if (offset <= 0.05 || offset >= length - 0.05) throw new Error('Schnittpunkt liegt zu nah am Clip-Rand.');
      const left = { ...target, id: makeId('clip'), source_end: safeNumber(target.source_start) + offset };
      const right = { ...target, id: makeId('clip'), timeline_start: splitTime, source_start: safeNumber(target.source_start) + offset };
      next.clips = next.clips.flatMap((clip) => clip.id === target.id ? [left, right] : [clip]);
      nextSelectedClipId = right.id;
      guideTime = splitTime;
      guideLabel = 'Schnittpunkt';
      title = 'Clip schneiden';
      summary = `Clip „${target.label || 'Clip'}“ wird bei ${secondsToClock(splitTime, true)} in zwei Clips geteilt.`;
      actions.push(`Schnitt bei ${secondsToClock(splitTime, true)} setzen`);
      actions.push('Linken und rechten Clip erzeugen');
      markArrangementChanged();
    } else if (commandType === 'clip_duplicate') {
      const target = findClipById(selectedId);
      if (!target) throw new Error('Bitte zuerst einen Clip auswählen.');
      const duration = clipDuration(target);
      const copy = { ...target, id: makeId('clip'), timeline_start: safeNumber(target.timeline_start) + duration, label: `${target.label || 'Clip'} Kopie` };
      next.clips.push(copy);
      nextSelectedClipId = copy.id;
      guideTime = copy.timeline_start;
      guideLabel = 'Duplikat';
      title = 'Clip duplizieren';
      summary = `Clip „${target.label || 'Clip'}“ wird direkt hinter dem Original eingefügt.`;
      actions.push(`Duplikat ab ${secondsToClock(copy.timeline_start, true)} erstellen`);
      actions.push(`Länge ${secondsToClock(duration, true)} übernehmen`);
      markArrangementChanged();
    } else if (commandType === 'clip_delete') {
      const target = findClipById(selectedId);
      if (!target) throw new Error('Bitte zuerst einen Clip auswählen.');
      next.clips = next.clips.filter((clip) => clip.id !== target.id);
      nextSelectedClipId = '';
      title = 'Clip löschen';
      summary = `Clip „${target.label || 'Clip'}“ wird aus dem Arrangement entfernt.`;
      actions.push('Clip aus der Timeline entfernen');
      actions.push('Original-Audio bleibt unverändert');
      markArrangementChanged();
    } else if (commandType === 'clip_gain') {
      const target = findClipById(selectedId);
      if (!target) throw new Error('Bitte zuerst einen Clip auswählen.');
      const currentGain = safeNumber(target.gain_db);
      const nextGain = Number.isFinite(Number(command.gainDb))
        ? clamp(Number(command.gainDb), -24, 24)
        : clamp(currentGain + safeNumber(command.gainDelta), -24, 24);
      next.clips = next.clips.map((clip) => clip.id === target.id ? { ...clip, gain_db: nextGain } : clip);
      nextSelectedClipId = target.id;
      guideTime = safeNumber(target.timeline_start);
      guideLabel = 'Clip-Pegel';
      title = 'Clip-Pegel ändern';
      summary = `Clip „${target.label || 'Clip'}“ wird von ${currentGain} dB auf ${nextGain} dB gesetzt.`;
      actions.push(`Gain ${currentGain} dB → ${nextGain} dB`);
      actions.push('Änderung betrifft nur diesen Timeline-Clip');
      markArrangementChanged();
    } else if (commandType === 'clip_fade') {
      const target = findClipById(selectedId);
      if (!target) throw new Error('Bitte zuerst einen Clip auswählen.');
      const duration = clipDuration(target);
      const fadeSeconds = clamp(safeNumber(command.seconds, 2), 0, Math.max(0.1, duration / 2));
      const edge = command.edge === 'out' ? 'out' : command.edge === 'both' ? 'both' : 'in';
      next.clips = next.clips.map((clip) => {
        if (clip.id !== target.id) return clip;
        if (edge === 'both') return { ...clip, fade_in: fadeSeconds, fade_out: fadeSeconds };
        return edge === 'out' ? { ...clip, fade_out: fadeSeconds } : { ...clip, fade_in: fadeSeconds };
      });
      nextSelectedClipId = target.id;
      guideTime = edge === 'out' ? safeNumber(target.timeline_start) + duration - fadeSeconds : safeNumber(target.timeline_start);
      guideLabel = edge === 'out' ? 'Fade-out' : edge === 'both' ? 'Fade' : 'Fade-in';
      title = edge === 'out' ? 'Fade-out setzen' : edge === 'both' ? 'Fade setzen' : 'Fade-in setzen';
      summary = `Clip „${target.label || 'Clip'}“ bekommt ${edge === 'both' ? 'Fade-in und Fade-out' : edge === 'out' ? 'einen Fade-out' : 'einen Fade-in'} von ${secondsToClock(fadeSeconds, true)}.`;
      actions.push(`${edge === 'both' ? 'Fade-in/Fade-out' : edge === 'out' ? 'Fade-out' : 'Fade-in'} auf ${secondsToClock(fadeSeconds, true)} setzen`);
      actions.push('Änderung betrifft nur diesen Timeline-Clip');
      markArrangementChanged();
    } else if (commandType === 'clip_trim') {
      const target = findClipById(selectedId);
      if (!target) throw new Error('Bitte zuerst einen Clip auswählen.');
      const duration = clipDuration(target);
      const amount = clamp(safeNumber(command.seconds, 2), 0.05, Math.max(0.05, duration - 0.25));
      const edge = command.edge === 'start' ? 'start' : 'end';
      if (duration - amount < 0.25) throw new Error('Der Clip wäre nach dem Kürzen zu kurz.');
      next.clips = next.clips.map((clip) => {
        if (clip.id !== target.id) return clip;
        if (edge === 'start') return { ...clip, source_start: safeNumber(clip.source_start) + amount };
        return { ...clip, source_end: Math.max(safeNumber(clip.source_start) + 0.25, safeNumber(clip.source_end) - amount) };
      });
      nextSelectedClipId = target.id;
      guideTime = edge === 'start' ? safeNumber(target.timeline_start) : safeNumber(target.timeline_start) + duration - amount;
      guideLabel = edge === 'start' ? 'Clip-Anfang gekürzt' : 'Clip-Ende gekürzt';
      title = edge === 'start' ? 'Clip-Anfang kürzen' : 'Clip-Ende kürzen';
      summary = `Clip „${target.label || 'Clip'}“ wird am ${edge === 'start' ? 'Anfang' : 'Ende'} um ${secondsToClock(amount, true)} gekürzt.`;
      actions.push(`${edge === 'start' ? 'Quelle-Start' : 'Quelle-Ende'} um ${secondsToClock(amount, true)} verschieben`);
      actions.push(`Neue Länge ca. ${secondsToClock(duration - amount, true)}`);
      markArrangementChanged();
    } else if (commandType === 'range_delete') {
      const range = command.range || selection;
      if (!range || safeNumber(range.end) - safeNumber(range.start) <= 0.05) throw new Error('Bitte zuerst einen Bereich in der Timeline markieren.');
      const cutStart = snapTime(range.start);
      const cutEnd = snapTime(range.end);
      const cutLength = cutEnd - cutStart;
      const shouldCloseGap = command.closeGap ?? closeGap;
      const nextClips = [];
      for (const clip of next.clips) {
        if (clip.locked) {
          nextClips.push(clip);
          continue;
        }
        const start = safeNumber(clip.timeline_start);
        const end = start + clipDuration(clip);
        if (end <= cutStart || start >= cutEnd) {
          nextClips.push(shouldCloseGap && start >= cutEnd ? { ...clip, timeline_start: Math.max(0, start - cutLength) } : clip);
          continue;
        }
        if (start < cutStart) {
          nextClips.push({ ...clip, id: makeId('clip'), source_end: safeNumber(clip.source_start) + (cutStart - start) });
        }
        if (end > cutEnd) {
          const rightSourceStart = safeNumber(clip.source_start) + (cutEnd - start);
          nextClips.push({
            ...clip,
            id: makeId('clip'),
            timeline_start: shouldCloseGap ? cutStart : cutEnd,
            source_start: rightSourceStart,
          });
        }
      }
      next.clips = nextClips;
      next.markers = (next.markers || [])
        .filter((marker) => marker.time < cutStart || marker.time > cutEnd)
        .map((marker) => shouldCloseGap && marker.time >= cutEnd ? { ...marker, time: Math.max(0, marker.time - cutLength) } : marker);
      nextSelection = null;
      nextSelectedClipId = '';
      guideTime = cutStart;
      guideLabel = shouldCloseGap ? 'Bereich entfernt · Lücke geschlossen' : 'Bereich entfernt';
      title = shouldCloseGap ? 'Bereich entfernen und Lücke schließen' : 'Bereich entfernen';
      summary = `Bereich ${secondsToClock(cutStart, true)} – ${secondsToClock(cutEnd, true)} wird entfernt.`;
      actions.push(`Bereichslänge ${secondsToClock(cutLength, true)} entfernen`);
      if (shouldCloseGap) actions.push('Nachfolgende Clips und Marker nach links verschieben');
      else actions.push('Lücke in der Timeline bestehen lassen');
      markArrangementChanged();
    } else if (commandType === 'clip_align_to_playhead') {
      const target = findClipById(selectedId);
      if (!target) throw new Error('Bitte zuerst einen Clip auswählen.');
      const duration = clipDuration(target);
      const edge = command.edge === 'end' ? 'end' : 'start';
      const rawStart = edge === 'end' ? currentTime - duration : currentTime;
      const nextStart = clamp(snapTime(rawStart), 0, Math.max(0, beforeDuration - duration));
      next.clips = next.clips.map((clip) => clip.id === target.id ? { ...clip, timeline_start: nextStart } : clip);
      nextSelectedClipId = target.id;
      guideTime = edge === 'end' ? nextStart + duration : nextStart;
      guideLabel = edge === 'end' ? 'Clip-Ende an Playhead' : 'Clip-Start an Playhead';
      title = edge === 'end' ? 'Clip-Ende an Playhead' : 'Clip-Start an Playhead';
      summary = `Clip „${target.label || 'Clip'}“ wird an den aktuellen Playhead gesetzt.`;
      actions.push(`Neue Position ${secondsToClock(nextStart, true)}`);
      actions.push(`Playhead ${secondsToClock(currentTime, true)} als Bezugspunkt verwenden`);
      markArrangementChanged();
    } else if (commandType === 'clip_attach_adjacent') {
      const target = findClipById(selectedId);
      if (!target) throw new Error('Bitte zuerst einen Clip auswählen.');
      const direction = command.direction === 'next' ? 'next' : 'previous';
      const adjacent = adjacentFor(target, direction);
      if (!adjacent) throw new Error(direction === 'previous' ? 'Kein vorheriger Clip auf derselben Spur gefunden.' : 'Kein nächster Clip auf derselben Spur gefunden.');
      const duration = clipDuration(target);
      const nextStart = direction === 'previous' ? adjacent.candidateEnd : Math.max(0, adjacent.candidateStart - duration);
      next.clips = next.clips.map((clip) => clip.id === target.id ? { ...clip, timeline_start: nextStart } : clip);
      nextSelectedClipId = target.id;
      guideTime = direction === 'previous' ? nextStart : nextStart + duration;
      guideLabel = direction === 'previous' ? 'An vorherigen Clip' : 'An nächsten Clip';
      title = direction === 'previous' ? 'An Vorgänger anschließen' : 'An Nächsten anschließen';
      summary = `Clip „${target.label || 'Clip'}“ wird ohne Lücke an „${adjacent.label || 'Clip'}“ angelegt.`;
      actions.push(`Neue Position ${secondsToClock(nextStart, true)}`);
      actions.push('Nur Clips derselben Spur werden als Nachbarn genutzt');
      markArrangementChanged();
    } else if (commandType === 'section_duplicate' || commandType === 'section_append_to_end') {
      const section = resolveCommandSection();
      const musicalRange = resolveMusicalSectionRange(section);
      const rangeStart = musicalRange.start;
      const rangeEnd = musicalRange.end;
      const rangeLength = rangeEnd - rangeStart;
      const appendToEnd = commandType === 'section_append_to_end' || command.target === 'end';
      const insertAt = appendToEnd ? arrangementLength(base, beforeDuration) : rangeEnd;
      let copies = extractRangeClipParts(rangeStart, rangeEnd, insertAt, section.displayLabel);
      const sourceLimit = sourceDuration || safeNumber(currentAsset?.duration_seconds) || beforeDuration;
      if (!copies.length && sourceLimit >= rangeEnd - 0.05) {
        copies = [{
          id: makeId('clip'),
          track_id: 'track-1',
          source_audio_id: Number(currentAsset?.id || base.source_audio_id || 0),
          timeline_start: insertAt,
          source_start: rangeStart,
          source_end: rangeEnd,
          gain_db: 0,
          fade_in: 0,
          fade_out: 0,
          label: `${section.displayLabel} Kopie`,
          muted: false,
          locked: false,
          color: 'cyan',
        }];
      }
      if (!copies.length) throw new Error('Für diesen Abschnitt konnten keine passenden Audioclips ermittelt werden.');
      if (!appendToEnd) insertTimelineGap(insertAt, rangeLength);
      next.clips = [...(next.clips || []), ...copies].sort((a, b) => safeNumber(a.timeline_start) - safeNumber(b.timeline_start));
      nextSelectedClipId = copies[0]?.id || '';
      nextSelection = { start: insertAt, end: insertAt + rangeLength };
      guideTime = insertAt;
      guideLabel = appendToEnd ? `${section.displayLabel} ans Ende` : `${section.displayLabel} doppelt`;
      title = appendToEnd ? 'Abschnitt ans Ende hängen' : 'Abschnitt duplizieren';
      summary = appendToEnd
        ? `Abschnitt „${section.displayLabel}“ wird an das Ende des Arrangements gehängt.`
        : `Abschnitt „${section.displayLabel}“ wird direkt hinter dem Original eingefügt.`;
      actions.push(`${section.displayLabel}: ${secondsToClock(rangeStart, true)} – ${secondsToClock(rangeEnd, true)} verwenden`);
      if (musicalRange.label) actions.push(musicalRange.label);
      actions.push(`${copies.length} Audio-Teil${copies.length === 1 ? '' : 'e'} als neue Clip-Kopie erzeugen`);
      if (!appendToEnd) actions.push('Nachfolgende Clips bei Bedarf nach rechts verschieben');
      else actions.push(`Einfügen am Arrangement-Ende bei ${secondsToClock(insertAt, true)}`);
      if (copies.length > 1) warnings.push('Der Abschnitt liegt über mehreren Clips und wird als mehrere Teilclips eingefügt.');
      if (musicalRange.source === 'raw') warnings.push('Keine Beat-/Bar-Map gefunden; Abschnittsgrenzen werden unverändert verwendet.');
      markArrangementChanged();
    } else if (commandType === 'section_delete') {
      const section = resolveCommandSection();
      const musicalRange = resolveMusicalSectionRange(section);
      const cutStart = musicalRange.start;
      const cutEnd = musicalRange.end;
      const cutLength = cutEnd - cutStart;
      const shouldCloseGap = command.closeGap ?? closeGap;
      const nextClips = [];
      for (const clip of next.clips) {
        if (clip.locked) {
          nextClips.push(clip);
          continue;
        }
        const start = safeNumber(clip.timeline_start);
        const end = start + clipDuration(clip);
        if (end <= cutStart || start >= cutEnd) {
          nextClips.push(shouldCloseGap && start >= cutEnd ? { ...clip, timeline_start: Math.max(0, start - cutLength) } : clip);
          continue;
        }
        if (start < cutStart) {
          nextClips.push({ ...clip, id: makeId('clip'), source_end: safeNumber(clip.source_start) + (cutStart - start) });
        }
        if (end > cutEnd) {
          const rightSourceStart = safeNumber(clip.source_start) + (cutEnd - start);
          nextClips.push({
            ...clip,
            id: makeId('clip'),
            timeline_start: shouldCloseGap ? cutStart : cutEnd,
            source_start: rightSourceStart,
          });
        }
      }
      next.clips = nextClips;
      next.markers = (next.markers || [])
        .filter((marker) => marker.time < cutStart || marker.time > cutEnd)
        .map((marker) => shouldCloseGap && marker.time >= cutEnd ? { ...marker, time: Math.max(0, marker.time - cutLength) } : marker);
      nextSelection = null;
      nextSelectedClipId = '';
      guideTime = cutStart;
      guideLabel = shouldCloseGap ? `${section.displayLabel} entfernt` : `${section.displayLabel} ausgeschnitten`;
      title = 'Abschnitt entfernen';
      summary = `Abschnitt „${section.displayLabel}“ wird aus dem Arrangement entfernt.`;
      actions.push(`${section.displayLabel}: ${secondsToClock(cutStart, true)} – ${secondsToClock(cutEnd, true)} entfernen`);
      if (musicalRange.label) actions.push(musicalRange.label);
      if (musicalRange.source === 'raw') warnings.push('Keine Beat-/Bar-Map gefunden; Abschnittsgrenzen werden unverändert verwendet.');
      if (shouldCloseGap) actions.push('Nachfolgende Clips und Marker nach links verschieben');
      else actions.push('Lücke in der Timeline bestehen lassen');
      markArrangementChanged();
    } else if (commandType === 'gap_close') {
      const trackIds = (next.tracks || []).map((track) => track.id);
      let moved = 0;
      next.clips = next.clips.slice();
      trackIds.forEach((trackId) => {
        let cursor = 0;
        next.clips
          .filter((clip) => clip.track_id === trackId && !clip.locked)
          .sort((a, b) => safeNumber(a.timeline_start) - safeNumber(b.timeline_start))
          .forEach((clip) => {
            const start = safeNumber(clip.timeline_start);
            const duration = clipDuration(clip);
            if (start > cursor + 0.02) {
              clip.timeline_start = cursor;
              moved += 1;
            }
            cursor = Math.max(cursor, clip.timeline_start + duration);
          });
      });
      if (!moved) warnings.push('Es wurden keine relevanten Lücken zwischen Clips gefunden.');
      title = 'Alle Lücken schließen';
      summary = 'Alle nicht gesperrten Clips werden pro Spur nach links zusammengeschoben.';
      actions.push(`${moved} Clip${moved === 1 ? '' : 's'} verschieben`);
      actions.push('Spuren bleiben getrennt');
      markArrangementChanged();
    } else {
      throw new Error('Unbekanntes DAW-Kommando.');
    }

    if (command.aiPrompt) {
      title = `KI: ${title}`;
      actions.unshift(`KI-Befehl: „${command.aiPrompt}“`);
      if (command.aiInterpretation) actions.unshift(`Interpretation: ${command.aiInterpretation}`);
    }

    const normalizedNext = normalizeArrangement(next, currentAsset, arrangementLength(next, beforeDuration));
    const afterDuration = arrangementLength(normalizedNext, beforeDuration);
    return {
      id: makeId('daw-command'),
      command,
      aiPrompt: command.aiPrompt || '',
      aiInterpretation: command.aiInterpretation || '',
      aiSource: command.aiSource || '',
      section: command.section || resolvedSections.find((item) => item.id === command.sectionId) || null,
      title,
      summary,
      actions,
      warnings,
      beforeDuration,
      afterDuration,
      affectedClips: Math.max(0, Math.abs((normalizedNext.clips || []).length - (base.clips || []).length)) || 1,
      originalArrangement: original,
      nextArrangement: normalizedNext,
      nextSelectedClipId,
      nextSelection,
      guideTime,
      guideLabel,
    };
  }
