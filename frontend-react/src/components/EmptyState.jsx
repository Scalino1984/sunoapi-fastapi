import React from 'react';
import { useI18n } from '../i18n/I18nContext.jsx';

export function EmptyState({ title, text, action }) {
  const { t } = useI18n();
  return (
    <div className="empty-state">
      <div className="empty-icon">♪</div>
      <h3>{title || t('common.noEntries', 'Keine Einträge')}</h3>
      <p>{text || t('common.noData', 'Noch keine Daten vorhanden.')}</p>
      {action}
    </div>
  );
}
