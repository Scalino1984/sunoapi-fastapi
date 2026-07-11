import React, { useMemo, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';

export function LibraryDetailAccordion({
  title,
  eyebrow,
  description,
  text,
  emptyText = '—',
  maxPreviewLines = 5,
  defaultOpen = false,
  className = '',
  actionSlot = null,
  noticeSlot = null,
  children = null,
}) {
  const [open, setOpen] = useState(defaultOpen);
  const normalizedText = useMemo(() => {
    const value = typeof text === 'string' ? text : String(text ?? '');
    return value.trim() || emptyText;
  }, [text, emptyText]);
  const previewLines = Math.max(1, Number(maxPreviewLines) || 5);
  const previewCharLimit = Math.max(220, previewLines * 120);
  const hasRealText = normalizedText !== emptyText;
  const logicalLines = useMemo(() => normalizedText.split(/\r?\n/), [normalizedText]);
  const hasMoreContent = hasRealText && (logicalLines.length > previewLines || normalizedText.length > previewCharLimit);
  const previewText = useMemo(() => {
    if (open || !hasRealText) return normalizedText;
    const slicedLines = logicalLines.slice(0, previewLines).join('\n');
    const limited = slicedLines.length > previewCharLimit
      ? `${slicedLines.slice(0, previewCharLimit).trimEnd()}…`
      : slicedLines;
    if (hasMoreContent && !limited.endsWith('…')) return `${limited.trimEnd()}\n…`;
    return limited;
  }, [open, hasRealText, normalizedText, logicalLines, previewLines, previewCharLimit, hasMoreContent]);

  return (
    <div className={`meta-card wide library-detail-accordion ${open ? 'is-open' : 'is-collapsed'} ${className}`.trim()}>
      <div className="library-detail-accordion-head">
        <button
          type="button"
          className="library-detail-accordion-toggle"
          onClick={() => setOpen((current) => !current)}
          aria-expanded={open}
        >
          <span className="library-detail-accordion-icon" aria-hidden="true">
            {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          </span>
          <span className="library-detail-accordion-title-wrap">
            {eyebrow && <span className="eyebrow">{eyebrow}</span>}
            <strong>{title}</strong>
            {description && <small className="muted">{description}</small>}
          </span>
        </button>
        {actionSlot && <div className="library-detail-accordion-actions">{actionSlot}</div>}
      </div>

      {noticeSlot && <div className="library-detail-accordion-notice">{noticeSlot}</div>}

      <pre
        className={open ? 'library-detail-accordion-content-pre is-open detail-scroll-passthrough' : 'library-detail-accordion-content-pre is-preview'}
        style={{ '--library-detail-preview-lines': previewLines }}
      >
        {previewText}
      </pre>

      {!open && hasMoreContent && (
        <button type="button" className="library-detail-accordion-more" onClick={() => setOpen(true)}>
          Vollständig anzeigen
        </button>
      )}

      {open && children && <div className="library-detail-accordion-footer">{children}</div>}
    </div>
  );
}
