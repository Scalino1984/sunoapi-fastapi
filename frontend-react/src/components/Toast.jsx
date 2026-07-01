import React, { useEffect, useRef } from 'react';
import { useI18n } from '../i18n/I18nContext.jsx';

export function Toast({ message, type = 'info', onClose, onClick, autoCloseMs = 0, onAutoClose, toastKey = '' }) {
  const { t } = useI18n();
  const onCloseRef = useRef(onClose);
  const onAutoCloseRef = useRef(onAutoClose);

  useEffect(() => {
    onCloseRef.current = onClose;
    onAutoCloseRef.current = onAutoClose;
  }, [onClose, onAutoClose]);

  useEffect(() => {
    if (!message || !autoCloseMs || Number(autoCloseMs) <= 0) return undefined;

    const timerId = window.setTimeout(() => {
      if (typeof onAutoCloseRef.current === 'function') onAutoCloseRef.current();
      else if (typeof onCloseRef.current === 'function') onCloseRef.current();
    }, Number(autoCloseMs));

    return () => window.clearTimeout(timerId);
  }, [message, autoCloseMs, toastKey]);

  if (!message) return null;

  return (
    <div className={`toast toast-${type}`} role="status" aria-live="polite">
      <button type="button" className="toast-main" onClick={onClick || undefined}>{message}</button>
      <button type="button" onClick={onClose} aria-label={t('common.close', 'Schließen')}>×</button>
    </div>
  );
}
