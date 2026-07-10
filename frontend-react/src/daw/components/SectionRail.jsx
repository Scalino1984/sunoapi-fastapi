import React from 'react';
import { Copy, CornerDownRight, Trash2 } from 'lucide-react';
import { clamp, safeNumber, secondsToClock } from '../timeUtils.js';

// Zeigt erkannte Songabschnitte (Intro, Verse, Hook, ...) über der Timeline.
// Klick markiert den Abschnitt als Bereich; die Buttons lösen die
// taktgenauen Abschnitts-Kommandos aus (Duplizieren, ans Ende, Entfernen).
export const SectionRail = React.memo(function SectionRail({ sections = [], duration, selectedSectionId, onFocusSection, onSectionCommand }) {
  if (!sections.length) return null;
  const pct = (value) => `${clamp((safeNumber(value) / Math.max(duration, 0.001)) * 100, 0, 100)}%`;
  return (
    <div className="daw-section-rail" role="list" aria-label="Songstruktur">
      {sections.map((section) => {
        const width = clamp(((section.end - section.start) / Math.max(duration, 0.001)) * 100, 0.4, 100);
        const active = section.id === selectedSectionId;
        return (
          <div
            key={section.id}
            role="listitem"
            className={`daw-section daw-section-${section.kind || 'other'} ${active ? 'active' : ''}`}
            style={{ left: pct(section.start), width: `${width}%` }}
            title={`${section.displayLabel} · ${secondsToClock(section.start, true)} – ${secondsToClock(section.end, true)}`}
            onClick={() => onFocusSection(section.id)}
          >
            <span className="daw-section-label">{section.displayLabel}</span>
            {active ? (
              <span className="daw-section-actions" onClick={(event) => event.stopPropagation()}>
                <button type="button" title="Abschnitt duplizieren (taktgenau)" onClick={() => onSectionCommand('section_duplicate', section)}><Copy size={12} /></button>
                <button type="button" title="Abschnitt ans Ende hängen" onClick={() => onSectionCommand('section_append_to_end', section)}><CornerDownRight size={12} /></button>
                <button type="button" title="Abschnitt entfernen" onClick={() => onSectionCommand('section_delete', section)}><Trash2 size={12} /></button>
              </span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
});
