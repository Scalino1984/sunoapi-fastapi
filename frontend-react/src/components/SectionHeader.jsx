import React from 'react';

export function SectionHeader({ eyebrow, title, children }) {
  return (
    <div className="page-header">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
      </div>
      {children && <div className="header-inline-actions">{children}</div>}
    </div>
  );
}
