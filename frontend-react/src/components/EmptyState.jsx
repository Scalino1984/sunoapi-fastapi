import React from 'react';

export function EmptyState({ title = 'Keine Einträge', text = 'Noch keine Daten vorhanden.', action }) {
  return (
    <div className="empty-state">
      <div className="empty-icon">♪</div>
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  );
}
