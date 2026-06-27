import React, { useEffect, useMemo, useState } from 'react';
import { Copy, Download, Plus, RotateCcw, Save, Scissors, Trash2, Undo2, Redo2, Play, Wand2 } from 'lucide-react';
import { activeSegmentAt, exportSrtText, parseSrtText, renumberSegments } from '../utils/srtParser.js';
import { secondsLabel } from '../utils/srtTime.js';
import { validateSrtSegments, issuesForSegment } from '../utils/srtValidation.js';
import {
  closeGapBefore,
  deleteSegment,
  extendPreviousToNext,
  extendSegmentAndRippleFollowing,
  fixOverlaps,
  insertSegmentAfter,
  insertSegmentBefore,
  mergeWithNeighbor,
  setSegmentTime,
  shiftSegmentsFromIndex,
  shortenSegmentAndRippleFollowing,
  splitSegmentAt,
  updateSegmentText
} from '../utils/srtEditor.js';
import { copyToClipboard, downloadTextFile, formatDuration, pickTitle, safeFilename } from '../utils.js';
import { api } from '../api/client.js';

function cloneSegments(segments) {
  return renumberSegments(segments).map((row) => ({ ...row, warning: [...(row.warning || [])] }));
}

function useSegmentHistory(segments, setSegments) {
  const [past, setPast] = useState([]);
  const [future, setFuture] = useState([]);

  function commit(nextSegments, label = '') {
    setPast((stack) => [...stack.slice(-49), { label, segments: cloneSegments(segments) }]);
    setFuture([]);
    setSegments(cloneSegments(nextSegments));
  }

  function undo() {
    setPast((stack) => {
      if (!stack.length) return stack;
      const previous = stack[stack.length - 1];
      setFuture((redoStack) => [{ label: previous.label, segments: cloneSegments(segments) }, ...redoStack.slice(0, 49)]);
      setSegments(cloneSegments(previous.segments));
      return stack.slice(0, -1);
    });
  }

  function redo() {
    setFuture((stack) => {
      if (!stack.length) return stack;
      const next = stack[0];
      setPast((undoStack) => [...undoStack.slice(-49), { label: next.label, segments: cloneSegments(segments) }]);
      setSegments(cloneSegments(next.segments));
      return stack.slice(1);
    });
  }

  return { commit, undo, redo, canUndo: past.length > 0, canRedo: future.length > 0, lastAction: past[past.length - 1]?.label || '' };
}

export function SrtTimelineEditor({
  asset,
  srtState,
  segments,
  setSegments,
  playbackState,
  isCurrentAsset,
  onPlayAsset,
  onSave,
  onCopy,
  onDownload,
  notify,
  rawOpen,
  setRawOpen
}) {
  const rows = useMemo(() => renumberSegments(segments || []), [segments]);
  const validation = useMemo(() => validateSrtSegments(rows), [rows]);
  const activeSegment = isCurrentAsset ? activeSegmentAt(rows, playbackState?.currentTime || 0) : null;
  const activeIndex = activeSegment ? rows.findIndex((row) => row.id === activeSegment.id) : -1;
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [ripple, setRipple] = useState(false);
  const [delta, setDelta] = useState('5.000');
  const [insertDuration, setInsertDuration] = useState('2.000');
  const [insertMode, setInsertMode] = useState('keep_timing');
  const [deleteMode, setDeleteMode] = useState('keep_timing');
  const [shiftScope, setShiftScope] = useState('include_current');
  const [rawDraft, setRawDraft] = useState(srtState?.srt_text || exportSrtText(rows));
  const { commit, undo, redo, canUndo, canRedo } = useSegmentHistory(rows, setSegments);

  useEffect(() => {
    if (activeIndex >= 0) setSelectedIndex(activeIndex);
  }, [activeIndex]);

  useEffect(() => {
    if (!rawOpen) setRawDraft(srtState?.srt_text || exportSrtText(rows));
  }, [srtState?.srt_text, rawOpen]);

  const selectedSegment = rows[selectedIndex] || rows[0] || null;

  useEffect(() => {
    function handleAssistantCommand(event) {
      const detail = event.detail || {};
      if (detail.audio_asset_id && String(detail.audio_asset_id) !== String(asset?.id)) return;
      const command = String(detail.command || 'focus');
      const value = Number(detail.delta ?? detail.seconds ?? delta ?? 0);
      if (command === 'shift_from_here' && selectedSegment) {
        commit(shiftSegmentsFromIndex(rows, selectedIndex, value, detail.include_current !== false), 'KI: ab hier verschoben');
        notify?.(`SRT ab Segment ${selectedIndex + 1} um ${secondsLabel(value)} verschoben.`, 'success');
      }
      if (command === 'extend_selected' && selectedSegment) {
        commit(extendSegmentAndRippleFollowing(rows, selectedIndex, value, Boolean(detail.ripple ?? ripple)), 'KI: Segment verlängert');
        notify?.(`Segment ${selectedIndex + 1} um ${secondsLabel(value)} verlängert.`, 'success');
      }
      if (command === 'add_segment') {
        addAfter(selectedIndex, Number(detail.start ?? playbackState?.currentTime ?? selectedSegment?.end ?? 0), detail.text || 'Neue Untertitel-Zeile');
      }
    }
    window.addEventListener('assistant:srt-editor-command', handleAssistantCommand);
    return () => window.removeEventListener('assistant:srt-editor-command', handleAssistantCommand);
  }, [asset?.id, rows, selectedIndex, selectedSegment?.id, delta, ripple, playbackState?.currentTime]);

  const errors = validation.issues.filter((issue) => issue.severity === 'error');
  const warnings = validation.issues.filter((issue) => issue.severity === 'warning');
  const gaps = validation.issues.filter((issue) => issue.type === 'gap');
  const overlaps = validation.issues.filter((issue) => issue.type === 'overlap');

  function seekTo(time, play = false) {
    if (!asset?.id) return;
    if (!isCurrentAsset) {
      onPlayAsset?.(asset);
      window.setTimeout(() => window.dispatchEvent(new CustomEvent('player:seek', { detail: { asset_id: asset.id, time, play } })), 350);
      return;
    }
    window.dispatchEvent(new CustomEvent('player:seek', { detail: { asset_id: asset.id, time, play } }));
  }

  function commitForSelected(mutator, label) {
    if (!selectedSegment) return;
    commit(mutator(rows, selectedIndex), label);
  }

  function addAfter(index = selectedIndex, start = null, text = 'Neue Untertitel-Zeile') {
    const base = rows[index] || rows[rows.length - 1] || null;
    const startTime = start ?? base?.end ?? Number(playbackState?.currentTime || 0);
    commit(insertSegmentAfter(rows, index, { start: startTime, duration: Number(insertDuration || 2), text }, insertMode), 'Segment hinzugefügt');
    setSelectedIndex(Math.min(rows.length, index + 1));
  }

  function addBefore(index = selectedIndex) {
    const base = rows[index] || null;
    commit(insertSegmentBefore(rows, index, { start: base ? Math.max(0, base.start - Number(insertDuration || 2)) : 0, duration: Number(insertDuration || 2), text: 'Neue Untertitel-Zeile' }, insertMode), 'Segment davor hinzugefügt');
    setSelectedIndex(Math.max(0, index));
  }

  function addInGap(index = selectedIndex) {
    const previous = rows[index] || null;
    const next = rows[index + 1] || null;
    if (!previous || !next || next.start <= previous.end) return notify?.('An dieser Stelle wurde keine Lücke gefunden.', 'error');
    const start = previous.end;
    const duration = Math.min(Number(insertDuration || 2), Math.max(0.3, next.start - previous.end));
    commit(insertSegmentAfter(rows, index, { start, duration, text: 'Neue Zeile in der Lücke' }, 'keep_timing'), 'Segment in Lücke eingefügt');
    setSelectedIndex(index + 1);
  }

  function deleteSelected() {
    if (!selectedSegment) return;
    const preview = deleteMode === 'close_gap'
      ? `Segment ${selectedSegment.index} wird gelöscht. Alle folgenden Segmente werden um ${secondsLabel(selectedSegment.end - selectedSegment.start)} nach vorne verschoben.`
      : `Segment ${selectedSegment.index} wird gelöscht. Bestehende Zeiten bleiben erhalten.`;
    if (!confirm(`${preview}\n\nFortfahren?`)) return;
    commit(deleteSegment(rows, selectedIndex, deleteMode), 'Segment gelöscht');
    setSelectedIndex(Math.max(0, selectedIndex - 1));
  }

  function shiftSelection() {
    if (!rows.length) return;
    const value = Math.abs(Number(delta || 0));
    if (!value) return;
    const sign = confirm(`Sollen die ausgewählten Segmente um +${value.toFixed(3)}s später verschoben werden?\n\nAbbrechen = früher verschieben.`) ? 1 : -1;
    let next = rows;
    const signedDelta = sign * value;
    if (shiftScope === 'all') next = shiftSegmentsFromIndex(rows, 0, signedDelta, true);
    else if (shiftScope === 'following') next = shiftSegmentsFromIndex(rows, selectedIndex, signedDelta, false);
    else next = shiftSegmentsFromIndex(rows, selectedIndex, signedDelta, true);
    commit(next, 'Zeitbereich verschoben');
  }

  function autoFix() {
    const preview = [];
    if (overlaps.length) preview.push(`${overlaps.length} Overlap(s) werden mit Mindestabstand korrigiert.`);
    preview.push('Segmente werden neu sortiert und nummeriert.');
    if (!confirm(`Auto-Fix Vorschau:\n- ${preview.join('\n- ')}\n\nAnwenden?`)) return;
    commit(fixOverlaps(rows), 'Auto-Fix angewendet');
  }

  function applyRawSrt() {
    const parsed = parseSrtText(rawDraft);
    const result = validateSrtSegments(parsed);
    if (!parsed.length || !result.valid) {
      notify?.('Roh-SRT konnte nicht übernommen werden. Bitte Fehler prüfen.', 'error');
      return;
    }
    if (!confirm(`${parsed.length} Segmente aus Roh-SRT übernehmen? Der aktuelle Editorstand wird ersetzt.`)) return;
    commit(parsed, 'Roh-SRT übernommen');
    notify?.('Roh-SRT wurde in Segmente übernommen.', 'success');
  }

  async function validateWithBackend() {
    try {
      const result = await api.srt.validate({ segments: rows });
      notify?.(result.valid ? 'Backend-Validierung erfolgreich.' : 'Backend-Validierung enthält Hinweise.', result.valid ? 'success' : 'warning');
    } catch (error) {
      notify?.(error.message || 'Backend-Validierung fehlgeschlagen.', 'error');
    }
  }

  return (
    <div className="srt-segment-editor srt-advanced-editor">
      <div className="srt-editor-toolbar">
        <div>
          <strong>Timeline-Segment-Editor</strong>
          <p className="muted">Alle Zeiten werden intern als Sekundenwerte verarbeitet. Vocal-Pausen bleiben bewusst erhalten.</p>
        </div>
        <div className="button-row wrap">
          <button type="button" className={ripple ? 'active' : ''} onClick={() => setRipple((value) => !value)}>Ripple: {ripple ? 'AN' : 'AUS'}</button>
          <button type="button" onClick={undo} disabled={!canUndo}><Undo2 size={14} /> Undo</button>
          <button type="button" onClick={redo} disabled={!canRedo}><Redo2 size={14} /> Redo</button>
          <button type="button" onClick={validateWithBackend}>Validieren</button>
          <button type="button" onClick={autoFix}><Wand2 size={14} /> Auto-Fix</button>
          <button type="button" className="primary" onClick={() => onSave?.()} disabled={Boolean(errors.length)}><Save size={14} /> Speichern</button>
        </div>
      </div>

      <div className="srt-live-container is-live">
        <div className="srt-live-label">
          <span>{isCurrentAsset ? 'Live-Untertitel' : 'Live-Untertitel bereit'}</span>
          <small>{formatDuration(playbackState?.currentTime || 0)} / {formatDuration(playbackState?.duration || asset?.duration_seconds)}</small>
        </div>
        <small>Vorher: {rows[selectedIndex - 1]?.text || '—'}</small>
        <strong>{activeSegmentAt(rows, playbackState?.currentTime || 0)?.text || selectedSegment?.text || 'Noch keine aktive Untertitel-Zeile.'}</strong>
        <small>Nächste: {rows[selectedIndex + 1]?.text || '—'}</small>
      </div>

      <div className="srt-editor-controls-grid">
        <label>Delta Sekunden<input type="number" step="0.001" min="0" value={delta} onChange={(event) => setDelta(event.target.value)} /></label>
        <label>Neue Segmentdauer<input type="number" step="0.001" min="0.3" value={insertDuration} onChange={(event) => setInsertDuration(event.target.value)} /></label>
        <label>Einfügen<select value={insertMode} onChange={(event) => setInsertMode(event.target.value)}><option value="keep_timing">Zeiten behalten</option><option value="ripple_forward">Folgende verschieben</option></select></label>
        <label>Löschen<select value={deleteMode} onChange={(event) => setDeleteMode(event.target.value)}><option value="keep_timing">Timing behalten</option><option value="close_gap">Lücke schließen</option><option value="keep_pause">Pause behalten</option></select></label>
        <label>Verschieben<select value={shiftScope} onChange={(event) => setShiftScope(event.target.value)}><option value="include_current">Dieses + folgende</option><option value="following">Nur folgende</option><option value="all">Alle Segmente</option></select></label>
        <button type="button" onClick={shiftSelection}>Ab hier verschieben</button>
        <button type="button" onClick={() => addAfter(selectedIndex)}>+ danach</button>
        <button type="button" onClick={() => addBefore(selectedIndex)}>+ davor</button>
        <button type="button" onClick={() => addInGap(selectedIndex)}>+ in Lücke</button>
        <button type="button" onClick={() => addAfter(selectedIndex, playbackState?.currentTime || 0)}>+ bei Playerzeit</button>
      </div>

      {!!validation.issues.length && (
        <div className="srt-validation-box">
          <strong>{errors.length ? `${errors.length} Fehler` : 'Validierung'} · {warnings.length} Warnung(en) · {gaps.length} Lücke(n) · {overlaps.length} Overlap(s)</strong>
          <div className="srt-issue-list">
            {validation.issues.slice(0, 10).map((issue, index) => <span key={`${issue.type}-${index}`} className={`srt-issue ${issue.severity}`}>{issue.message}</span>)}
          </div>
        </div>
      )}

      <div className="srt-editor-list">
        {rows.map((segment, index) => {
          const segmentIssues = issuesForSegment(validation.issues, segment.id);
          const isActive = activeSegment?.id === segment.id;
          const isSelected = selectedIndex === index;
          const hasGapBefore = segmentIssues.find((issue) => issue.type === 'gap');
          const hasOverlap = segmentIssues.find((issue) => issue.type === 'overlap');
          return (
            <div className={`srt-editor-row ${isActive ? 'is-active' : ''} ${isSelected ? 'is-selected' : ''}`} key={segment.id} onClick={() => setSelectedIndex(index)}>
              <span className="srt-editor-index">#{segment.index}</span>
              <label>Start<input type="number" min="0" step="0.001" value={segment.start} onChange={(event) => commit(setSegmentTime(rows, index, 'start', event.target.value), 'Startzeit geändert')} /></label>
              <label>Ende<input type="number" min="0" step="0.001" value={segment.end} onChange={(event) => commit(setSegmentTime(rows, index, 'end', event.target.value), 'Endzeit geändert')} /></label>
              <span className="srt-duration">{secondsLabel(segment.end - segment.start)}</span>
              <textarea value={segment.text} rows={2} onChange={(event) => commit(updateSegmentText(rows, index, event.target.value), 'Text geändert')} />
              <div className="srt-editor-actions">
                <button type="button" onClick={() => seekTo(segment.start, true)}><Play size={13} /> Play</button>
                <button type="button" onClick={() => seekTo(Math.max(0, segment.start - 1), true)}>−1s</button>
                <button type="button" onClick={() => seekTo(segment.end + 1, true)}>+1s</button>
                <button type="button" onClick={() => commit(setSegmentTime(rows, index, 'start', playbackState?.currentTime || 0), 'Start = Player')}>Start=Jetzt</button>
                <button type="button" onClick={() => commit(setSegmentTime(rows, index, 'end', playbackState?.currentTime || segment.end), 'Ende = Player')}>Ende=Jetzt</button>
                {[0.1, 0.5, 1].map((value) => <button key={`plus-${value}`} type="button" onClick={() => commit(extendSegmentAndRippleFollowing(rows, index, value, ripple), `Segment +${value}s`)}>+{value}s</button>)}
                {[0.1, 0.5, 1].map((value) => <button key={`minus-${value}`} type="button" onClick={() => commit(shortenSegmentAndRippleFollowing(rows, index, value, ripple), `Segment -${value}s`)}>-{value}s</button>)}
                <button type="button" onClick={() => commit(splitSegmentAt(rows, index, playbackState?.currentTime || ((segment.start + segment.end) / 2)), 'Segment geteilt')}><Scissors size={13} /> Split</button>
                <button type="button" onClick={() => addBefore(index)}><Plus size={13} /> davor</button>
                <button type="button" onClick={() => addAfter(index, segment.end)}><Plus size={13} /> danach</button>
                <button type="button" onClick={() => commit(mergeWithNeighbor(rows, index, 'previous'), 'Mit vorherigem verbunden')} disabled={index === 0}>⇤ Verbinden</button>
                <button type="button" onClick={() => commit(mergeWithNeighbor(rows, index, 'next'), 'Mit nächstem verbunden')} disabled={index >= rows.length - 1}>Verbinden ⇥</button>
                <button type="button" className="danger" onClick={deleteSelected}><Trash2 size={13} /></button>
              </div>
              {!!segmentIssues.length && <div className="srt-row-warnings">{segmentIssues.map((issue, issueIndex) => <span key={issueIndex} className={`srt-issue ${issue.severity}`}>{issue.message}</span>)}</div>}
              {(hasGapBefore || hasOverlap) && (
                <div className="srt-gap-actions">
                  {hasGapBefore && <button type="button" onClick={() => commit(closeGapBefore(rows, index), 'Lücke geschlossen')}>Lücke schließen</button>}
                  {hasGapBefore && <button type="button" onClick={() => commit(extendPreviousToNext(rows, index), 'Vorheriges Segment verlängert')}>Vorheriges bis hier verlängern</button>}
                  {hasGapBefore && <button type="button" onClick={() => addInGap(index - 1)}>Segment in Lücke</button>}
                  {hasOverlap && <button type="button" onClick={() => commit(fixOverlaps(rows), 'Overlap korrigiert')}>Overlap korrigieren</button>}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className={`srt-raw-details ${rawOpen ? 'is-open' : ''}`}>
        <button type="button" className="srt-raw-summary" aria-expanded={rawOpen} onClick={() => setRawOpen(!rawOpen)}>{rawOpen ? 'Roh-SRT ausblenden' : 'Roh-SRT anzeigen'}</button>
        {rawOpen && (
          <div className="srt-raw-editor stack">
            <textarea className="large-pre srt-preview srt-raw-textarea" value={rawDraft} rows={14} onChange={(event) => setRawDraft(event.target.value)} />
            <div className="button-row wrap">
              <button type="button" onClick={applyRawSrt}>Roh-SRT übernehmen</button>
              <button type="button" onClick={() => setRawDraft(exportSrtText(rows))}><RotateCcw size={14} /> Aus Segmenten neu erzeugen</button>
              <button type="button" onClick={() => copyToClipboard(rawDraft).then(() => notify?.('Roh-SRT kopiert.', 'success'))}><Copy size={14} /> Kopieren</button>
              <button type="button" onClick={() => downloadTextFile(`${safeFilename(pickTitle(asset))}.srt`, rawDraft, 'application/x-subrip;charset=utf-8')}><Download size={14} /> Download</button>
              <button type="button" onClick={() => notify?.(validateSrtSegments(parseSrtText(rawDraft)).valid ? 'Roh-SRT ist gültig.' : 'Roh-SRT enthält Fehler oder Warnungen.', 'info')}>Validieren</button>
            </div>
          </div>
        )}
      </div>

      <div className="button-row wrap srt-editor-footer">
        <button type="button" onClick={() => copyToClipboard(exportSrtText(rows)).then(() => notify?.('Editor-SRT kopiert.', 'success'))}><Copy size={14} /> Editor-SRT kopieren</button>
        <button type="button" onClick={() => downloadTextFile(`${safeFilename(pickTitle(asset))}.srt`, exportSrtText(rows), 'application/x-subrip;charset=utf-8')}><Download size={14} /> Editor-SRT herunterladen</button>
      </div>
    </div>
  );
}
