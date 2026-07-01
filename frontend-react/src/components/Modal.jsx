import React, { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { useI18n } from '../i18n/I18nContext.jsx';

export function Modal({ open, title, children, onClose, wide = false, cardClassName = '', contentClassName = '', cardStyle = null }) {
  const { t } = useI18n();
  useEffect(() => {
    if (!open || typeof document === 'undefined') return undefined;
    const body = document.body;
    const currentCount = Number(body.dataset.modalOpenCount || '0') || 0;
    body.dataset.modalOpenCount = String(currentCount + 1);
    body.classList.add('app-modal-open');
    return () => {
      const nextCount = Math.max(0, (Number(body.dataset.modalOpenCount || '1') || 1) - 1);
      body.dataset.modalOpenCount = String(nextCount);
      if (nextCount === 0) {
        body.classList.remove('app-modal-open');
        delete body.dataset.modalOpenCount;
      }
    };
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const handler = (event) => {
      if (event.key === 'Escape') onClose?.();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  const modal = (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => event.target === event.currentTarget && onClose?.()}
      onKeyDownCapture={(event) => event.stopPropagation()}
      onKeyUpCapture={(event) => event.stopPropagation()}
    >
      <section
        className={`modal-card ${wide ? 'modal-wide' : ''} ${cardClassName}`.trim()}
        style={cardStyle || undefined}
        onMouseDown={(event) => event.stopPropagation()}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="modal-header">
          <h2>{title}</h2>
          <button type="button" onClick={onClose} aria-label={t('common.close', 'Schließen')}><X size={18} /></button>
        </header>
        <div className={`modal-content ${contentClassName}`.trim()}>{children}</div>
      </section>
    </div>
  );

  if (typeof document === 'undefined') return modal;
  return createPortal(modal, document.body);
}
