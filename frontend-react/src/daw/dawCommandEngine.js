import {
  arrangementDuration,
  beatsPerBar,
  clipDuration,
  clipEnd,
  cloneDaw,
  duplicateClip,
  findSectionByCommand,
  makeDawId,
  safeNumber,
  secondsPerBar,
  snapTime,
  splitClipAt,
} from './dawMath.js';

function commandBarCount(message, fallback = 1) {
  const text = String(message || '').toLowerCase().replace(',', '.');
  const match = text.match(/(\d+(?:\.\d+)?)\s*(?:takt|takte|takten|bar|bars)/);
  return match ? Math.max(0.25, Number(match[1])) : fallback;
}

function commandDirection(message) {
  const text = String(message || '').toLowerCase();
  if (/(links|zurück|back|früher)/.test(text)) return -1;
  return 1;
}

function makeResult({ arrangement, title, summary, actions, selectedClipId = '', warnings = [], focusTime = null }) {
  const next = cloneDaw(arrangement);
  next.duration_seconds = arrangementDuration(next, next.duration_seconds);
  return { ok: true, title, summary, actions, arrangement: next, selected_clip_id: selectedClipId, warnings, focus_time: focusTime };
}

function sectionPiecesFromArrangement(arrangement, sourceAssetId, section, insertAt) {
  const pieces = [];
  (arrangement.clips || []).forEach((clip) => {
    if (clip.locked) return;
    const clipStart = safeNumber(clip.timeline_start);
    const clipFinish = clipEnd(clip);
    const overlapStart = Math.max(section.start, clipStart);
    const overlapEnd = Math.min(section.end, clipFinish);
    if (overlapEnd - overlapStart <= 0.05) return;
    pieces.push({
      ...clip,
      id: makeDawId('clip'),
      timeline_start: insertAt + (overlapStart - section.start),
      source_start: safeNumber(clip.source_start) + (overlapStart - clipStart),
      source_end: safeNumber(clip.source_start) + (overlapEnd - clipStart),
      label: `${section.label || 'Abschnitt'} Kopie`,
      locked: false,
    });
  });
  if (!pieces.length) {
    pieces.push({
      id: makeDawId('clip'),
      track_id: arrangement.tracks?.[0]?.id || 'track-1',
      source_audio_id: Number(sourceAssetId || arrangement.source_audio_id || 0),
      timeline_start: insertAt,
      source_start: section.start,
      source_end: section.end,
      gain_db: 0,
      fade_in: 0,
      fade_out: 0,
      label: `${section.label || 'Abschnitt'} Kopie`,
      muted: false,
      locked: false,
      color: 'cyan',
    });
  }
  return pieces.sort((a, b) => safeNumber(a.timeline_start) - safeNumber(b.timeline_start));
}

export function resolveDawCommand({ message, arrangement, selectedClipId, selectedSectionId, sections, sourceAssetId }) {
  const text = String(message || '').trim();
  if (!text) return { ok: false, error: 'Kein Befehl angegeben.' };
  const lowered = text.toLowerCase();
  const base = cloneDaw(arrangement);
  const bpm = safeNumber(base.bpm, 0);
  const barSeconds = bpm ? secondsPerBar(bpm, base.time_signature) : 4;
  const selectedClip = base.clips.find((clip) => clip.id === selectedClipId) || base.clips[0] || null;
  const warnings = [];
  if (!bpm) warnings.push('Kein BPM-Wert gesetzt. Takte werden mit 4 Sekunden Fallback berechnet.');

  if (/(verschieb|schieb|move)/.test(lowered)) {
    if (!selectedClip) return { ok: false, error: 'Kein Clip ausgewählt.' };
    const bars = commandBarCount(lowered, 1);
    const delta = commandDirection(lowered) * bars * barSeconds;
    const nextStart = snapTime(Math.max(0, safeNumber(selectedClip.timeline_start) + delta), base, true);
    const next = { ...base, clips: base.clips.map((clip) => clip.id === selectedClip.id ? { ...clip, timeline_start: nextStart } : clip) };
    return makeResult({
      arrangement: next,
      title: 'Clip verschieben',
      summary: `${selectedClip.label || 'Clip'} wird um ${bars} Takt(e) ${delta >= 0 ? 'nach rechts' : 'nach links'} verschoben.`,
      actions: [{ type: 'move_clip', clip_id: selectedClip.id, timeline_start: nextStart }],
      selectedClipId: selectedClip.id,
      warnings,
      focusTime: nextStart,
    });
  }

  if (/(schneid|split|cut)/.test(lowered) && /(nach|bei|takt|bar)/.test(lowered)) {
    if (!selectedClip) return { ok: false, error: 'Kein Clip ausgewählt.' };
    const bars = commandBarCount(lowered, 1);
    const splitAt = snapTime(safeNumber(selectedClip.timeline_start) + bars * barSeconds, base, true);
    const result = splitClipAt(base, selectedClip.id, splitAt);
    if (!result.createdClipId) return { ok: false, error: 'Der Schnittpunkt liegt außerhalb des Clips.' };
    return makeResult({
      arrangement: result.arrangement,
      title: 'Clip taktgenau schneiden',
      summary: `${selectedClip.label || 'Clip'} wird nach ${bars} Takt(en) geteilt.`,
      actions: [{ type: 'split_clip', clip_id: selectedClip.id, time: splitAt }],
      selectedClipId: result.createdClipId,
      warnings,
      focusTime: splitAt,
    });
  }

  if (/(doppelt|duplizier|kopier|wiederhol|verlänger|loop)/.test(lowered)) {
    const section = findSectionByCommand(sections || [], lowered, selectedSectionId);
    if (section && /(hook|refrain|chorus|intro|verse|strophe|bridge|outro|abschnitt|loop)/.test(lowered)) {
      const insertAt = snapTime(section.end, base, true);
      const pieces = sectionPiecesFromArrangement(base, sourceAssetId, section, insertAt);
      const next = { ...base, clips: [...base.clips, ...pieces] };
      return makeResult({
        arrangement: next,
        title: 'Songabschnitt duplizieren',
        summary: `${section.label || 'Abschnitt'} wird direkt nach dem Original eingefügt.`,
        actions: pieces.map((clip) => ({ type: 'duplicate_section_piece', clip_id: clip.id, timeline_start: clip.timeline_start })),
        selectedClipId: pieces[0]?.id || selectedClipId,
        warnings,
        focusTime: insertAt,
      });
    }
    if (!selectedClip) return { ok: false, error: 'Kein Clip ausgewählt.' };
    const result = duplicateClip(base, selectedClip.id);
    return makeResult({
      arrangement: result.arrangement,
      title: 'Clip duplizieren',
      summary: `${selectedClip.label || 'Clip'} wird direkt dahinter kopiert.`,
      actions: [{ type: 'duplicate_clip', source_clip_id: selectedClip.id, clip_id: result.createdClipId }],
      selectedClipId: result.createdClipId,
      warnings,
      focusTime: clipEnd(selectedClip),
    });
  }

  if (/(kürz|trim|ende|end)/.test(lowered)) {
    if (!selectedClip) return { ok: false, error: 'Kein Clip ausgewählt.' };
    const bars = commandBarCount(lowered, 1);
    const duration = bars * barSeconds;
    const nextEnd = safeNumber(selectedClip.source_start) + duration;
    const next = { ...base, clips: base.clips.map((clip) => clip.id === selectedClip.id ? { ...clip, source_end: Math.max(safeNumber(clip.source_start) + 0.08, nextEnd) } : clip) };
    return makeResult({
      arrangement: next,
      title: 'Clip taktgenau kürzen',
      summary: `${selectedClip.label || 'Clip'} wird auf ${bars} Takt(e) Länge gesetzt.`,
      actions: [{ type: 'trim_clip_end', clip_id: selectedClip.id, source_end: nextEnd }],
      selectedClipId: selectedClip.id,
      warnings,
      focusTime: safeNumber(selectedClip.timeline_start) + duration,
    });
  }

  if (/(fade in|fade-in|einblenden)/.test(lowered)) {
    if (!selectedClip) return { ok: false, error: 'Kein Clip ausgewählt.' };
    const seconds = Math.max(0.05, Number((lowered.match(/(\d+(?:\.\d+)?)\s*(?:s|sek|sekunden)/) || [])[1] || 1));
    const next = { ...base, clips: base.clips.map((clip) => clip.id === selectedClip.id ? { ...clip, fade_in: Math.min(seconds, clipDuration(clip)) } : clip) };
    return makeResult({ arrangement: next, title: 'Fade-In setzen', summary: `Fade-In auf ${seconds}s gesetzt.`, actions: [{ type: 'fade_in', clip_id: selectedClip.id, duration: seconds }], selectedClipId: selectedClip.id, warnings });
  }

  if (/(fade out|fade-out|ausblenden)/.test(lowered)) {
    if (!selectedClip) return { ok: false, error: 'Kein Clip ausgewählt.' };
    const seconds = Math.max(0.05, Number((lowered.match(/(\d+(?:\.\d+)?)\s*(?:s|sek|sekunden)/) || [])[1] || 1));
    const next = { ...base, clips: base.clips.map((clip) => clip.id === selectedClip.id ? { ...clip, fade_out: Math.min(seconds, clipDuration(clip)) } : clip) };
    return makeResult({ arrangement: next, title: 'Fade-Out setzen', summary: `Fade-Out auf ${seconds}s gesetzt.`, actions: [{ type: 'fade_out', clip_id: selectedClip.id, duration: seconds }], selectedClipId: selectedClip.id, warnings });
  }

  return { ok: false, error: 'Befehl noch zu unklar. Wähle einen Clip oder Abschnitt und nutze z. B. „dupliziere diesen Clip“, „schneide nach 4 Takten“ oder „verschiebe einen Takt nach rechts“.' };
}

