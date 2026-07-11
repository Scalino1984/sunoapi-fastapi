import React, { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';

export function LibraryDetailSection({
  eyebrow,
  title,
  description,
  defaultOpen = true,
  className = '',
  summarySlot = null,
  children = null,
}) {
  const [open, setOpen] = useState(Boolean(defaultOpen));

  return (
    <section className={`variant-detail-section library-detail-section-shell ${open ? 'is-open' : 'is-collapsed'} ${className}`.trim()}>
      <div className="library-detail-section-shell-head">
        <button
          type="button"
          className="library-detail-section-shell-toggle"
          onClick={() => setOpen((current) => !current)}
          aria-expanded={open}
        >
          <span className="library-detail-section-shell-icon" aria-hidden="true">
            {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          </span>
          <span className="library-detail-section-shell-title">
            {eyebrow && <span className="eyebrow">{eyebrow}</span>}
            <strong>{title}</strong>
            {description && <small className="muted">{description}</small>}
          </span>
        </button>
        {summarySlot && <div className="library-detail-section-shell-summary">{summarySlot}</div>}
      </div>
      {open && <div className="library-detail-section-shell-content">{children}</div>}
    </section>
  );
}
