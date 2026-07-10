import React from 'react';
import { AlertTriangle, Bot, CheckCircle2, Loader2, Send, Sparkles, Trash2, X } from 'lucide-react';
import { clamp, safeNumber, clipDuration, secondsToClock } from '../timeUtils.js';
import { CLIP_COLORS } from '../arrangement.js';

// ---------------------------------------------------------------------------
// AiCommandPanel – globales DAW-KI-Panel mit Verlauf, Beispielen und
// optionaler Server-KI (FastAPI-Planer) für komplexe/mehrdeutige Befehle.
// ---------------------------------------------------------------------------
export function AiCommandPanel({
  open, onClose,
  value, onChange, onSubmit, busy,
  status, history = [], examples = [],
  useServerAi, onToggleServerAi,
  onClearHistory,
  onPromptHookSelect,
}) {
  if (!open) return null;
  return (
    <aside className="daw-ai-panel" role="dialog" aria-label="DAW-KI">
      <div className="daw-ai-panel-head">
        <span className="daw-ai-panel-title"><Bot size={17} /> DAW-KI</span>
        <label className="daw-ai-server-toggle" title="Komplexe Befehle zusätzlich vom Server-KI-Planer auflösen lassen (wird in SQLite protokolliert)">
          <input type="checkbox" checked={useServerAi} onChange={(event) => onToggleServerAi(event.target.checked)} />
          Server-KI
        </label>
        <button
          type="button"
          className="icon-button ghost"
          title="Verlauf und Eingabe leeren"
          disabled={!history.length && !value && !status}
          onClick={onClearHistory}
        >
          <Trash2 size={15} />
        </button>
        <button type="button" className="icon-button ghost" title="Schließen (Esc)" onClick={onClose}><X size={15} /></button>
      </div>
      <div className="daw-ai-history">
        {history.length === 0 ? (
          <p className="daw-ai-empty">
            Beschreibe eine Timeline-Aktion in normaler Sprache. Jede Aktion wird
            zuerst als prüfbarer Plan angezeigt und erst nach Bestätigung angewendet.
          </p>
        ) : history.map((entry) => {
          const promptHooks = Array.isArray(entry.meta?.promptHooks) ? entry.meta.promptHooks : [];
          return (
            <div key={entry.id} className={`daw-ai-message daw-ai-${entry.role} ${entry.meta?.tone || ''}`}>
              {entry.text}
              {promptHooks.length ? (
                <div className="daw-ai-prompt-hooks">
                  {promptHooks.map((hook) => (
                    <button
                      key={hook.id}
                      type="button"
                      title={hook.prompt}
                      onClick={() => onPromptHookSelect?.(hook)}
                    >
                      <Sparkles size={13} /> {hook.title}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          );
        })}
        {busy ? <div className="daw-ai-message daw-ai-assistant"><Loader2 size={13} className="daw-spin" /> KI plant …</div> : null}
      </div>
      {status ? <div className="daw-ai-status">{status}</div> : null}
      <div className="daw-ai-examples">
        {examples.map((example) => (
          <button key={example} type="button" onClick={() => onChange(example)}>{example}</button>
        ))}
      </div>
      <div className="daw-ai-input-row">
        <textarea
          value={value}
          rows={2}
          placeholder="z. B. „Setze die erste Hook doppelt“ oder „Kürze das Intro auf 8 Takte“"
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              onSubmit();
            }
          }}
        />
        <button type="button" className="primary" disabled={busy || !value.trim()} onClick={onSubmit}>
          <Send size={14} />
        </button>
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// CommandPreviewModal – jede Änderung (Button, Shortcut oder KI) wird vor dem
// Anwenden als Plan angezeigt: Titel, Schritte, Warnungen, Vorher/Nachher.
// ---------------------------------------------------------------------------
export function CommandPreviewModal({ plan, onApply, onCancel }) {
  if (!plan) return null;
  return (
    <div className="daw-command-overlay" role="dialog" aria-modal="true" aria-label={plan.title}>
      <div className="daw-command-modal">
        <div className="daw-command-head">
          {plan.aiPrompt ? <Sparkles size={15} /> : <CheckCircle2 size={15} />}
          <strong>{plan.title}</strong>
          <button type="button" className="icon-button ghost" onClick={onCancel}><X size={14} /></button>
        </div>
        <p className="daw-command-summary">{plan.summary}</p>
        <ul className="daw-command-actions">
          {plan.actions.map((action, index) => <li key={index}>{action}</li>)}
        </ul>
        {plan.warnings?.length ? (
          <div className="daw-command-warnings">
            {plan.warnings.map((warning, index) => (
              <div key={index}><AlertTriangle size={13} /> {warning}</div>
            ))}
          </div>
        ) : null}
        <div className="daw-command-meta">
          <span>Länge: {secondsToClock(plan.beforeDuration, true)} → {secondsToClock(plan.afterDuration, true)}</span>
        </div>
        <div className="daw-command-buttons">
          <button type="button" onClick={onCancel}>Abbrechen</button>
          <button type="button" className="primary" onClick={() => onApply(plan)}>Anwenden</button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ClipInspector – Eigenschaften des ausgewählten Clips.
// ---------------------------------------------------------------------------
export function ClipInspector({ clip, tracks = [], onPatch, onDuplicate, onDelete, onSplitAtPlayhead }) {
  if (!clip) return null;
  const length = clipDuration(clip);
  return (
    <div className="daw-clip-inspector">
      <div className="daw-clip-inspector-row">
        <label>
          <span>Label</span>
          <input value={clip.label || ''} onChange={(event) => onPatch({ label: event.target.value })} />
        </label>
        <label>
          <span>Spur</span>
          <select value={clip.track_id} onChange={(event) => onPatch({ track_id: event.target.value })}>
            {tracks.map((track) => <option key={track.id} value={track.id}>{track.name}</option>)}
          </select>
        </label>
        <label>
          <span>Farbe</span>
          <select value={clip.color || 'cyan'} onChange={(event) => onPatch({ color: event.target.value })}>
            {CLIP_COLORS.map((color) => <option key={color} value={color}>{color}</option>)}
          </select>
        </label>
      </div>
      <div className="daw-clip-inspector-row">
        <label>
          <span>Gain (dB)</span>
          <input type="number" min={-24} max={24} step={0.5} value={clip.gain_db} onChange={(event) => onPatch({ gain_db: clamp(safeNumber(event.target.value), -24, 24) })} />
        </label>
        <label>
          <span>Fade-in (s)</span>
          <input type="number" min={0} max={Math.max(0, length / 2)} step={0.1} value={clip.fade_in} onChange={(event) => onPatch({ fade_in: Math.max(0, safeNumber(event.target.value)) })} />
        </label>
        <label>
          <span>Fade-out (s)</span>
          <input type="number" min={0} max={Math.max(0, length / 2)} step={0.1} value={clip.fade_out} onChange={(event) => onPatch({ fade_out: Math.max(0, safeNumber(event.target.value)) })} />
        </label>
        <label className="daw-check">
          <input type="checkbox" checked={clip.muted} onChange={(event) => onPatch({ muted: event.target.checked })} />
          <span>Mute</span>
        </label>
        <label className="daw-check">
          <input type="checkbox" checked={clip.locked} onChange={(event) => onPatch({ locked: event.target.checked })} />
          <span>Sperren</span>
        </label>
      </div>
      <div className="daw-clip-inspector-buttons">
        <button type="button" onClick={onSplitAtPlayhead}>Am Playhead schneiden</button>
        <button type="button" onClick={onDuplicate}>Duplizieren</button>
        <button type="button" className="danger" onClick={onDelete}>Löschen</button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
export function DawEmptyState({ lastKnownAsset, onOpenLast, onBackToLibrary }) {
  return (
    <div className="daw-empty-state">
      <h2>Mini-DAW</h2>
      <p>Wähle oben einen Song aus der Library, um die Timeline zu öffnen.</p>
      <div className="daw-empty-actions">
        {lastKnownAsset ? (
          <button type="button" className="primary" onClick={onOpenLast}>
            Zuletzt bearbeitet öffnen: {lastKnownAsset.display_title || lastKnownAsset.title || `Audio ${lastKnownAsset.id}`}
          </button>
        ) : null}
        <button type="button" onClick={onBackToLibrary}>Zur Library</button>
      </div>
    </div>
  );
}
