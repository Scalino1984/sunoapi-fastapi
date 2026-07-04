import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { RefreshCw, RotateCcw, Search, Trash2 } from 'lucide-react';
import { api } from '../api/client.js';
import { EmptyState } from '../components/EmptyState.jsx';
import { formatDate } from '../utils.js';
import { useI18n } from '../i18n/I18nContext.jsx';

const CONTENT_TYPES = [
  ['all', 'trash.filters.all'],
  ['audio', 'trash.filters.audio'],
  ['song', 'trash.filters.song'],
  ['lyric', 'trash.filters.lyric'],
  ['style', 'trash.filters.style'],
  ['playlist', 'trash.filters.playlist'],
  ['task', 'trash.filters.task'],
  ['project', 'trash.filters.project'],
];

function typeLabel(type, t) {
  return t(`trash.types.${type}`, type);
}

function itemKey(item) {
  return `${item?.type || ''}:${item?.id || ''}`;
}

export function TrashPage({ notify, onReload, onTrashChanged }) {
  const { t } = useI18n();
  const [items, setItems] = useState([]);
  const [selected, setSelected] = useState(() => new Set());
  const [query, setQuery] = useState('');
  const [contentType, setContentType] = useState('all');
  const [appliedQuery, setAppliedQuery] = useState('');
  const [appliedContentType, setAppliedContentType] = useState('all');
  const [loading, setLoading] = useState(false);
  const [busyKey, setBusyKey] = useState('');
  const [error, setError] = useState('');

  const loadTrash = useCallback(async (nextQuery = appliedQuery, nextContentType = appliedContentType) => {
    setLoading(true);
    setError('');
    try {
      const payload = await api.library.trash({ q: nextQuery, contentType: nextContentType, limit: 500 });
      const nextItems = Array.isArray(payload) ? payload : [];
      setItems(nextItems);
      onTrashChanged?.(nextItems.length > 0);
      const nextKeys = new Set(nextItems.map(itemKey));
      setSelected((current) => new Set([...current].filter((key) => nextKeys.has(key))));
    } catch (err) {
      const message = err?.message || t('trash.messages.loadFailed', 'Papierkorb konnte nicht geladen werden.');
      setError(message);
      notify?.(message, 'error');
    } finally {
      setLoading(false);
    }
  }, [appliedContentType, appliedQuery, notify, onTrashChanged, t]);

  useEffect(() => {
    loadTrash('', 'all');
    // Nur initial laden. Such-/Filterfelder werden erst bei "Anwenden" abgefragt.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stats = useMemo(() => {
    const byType = new Map();
    for (const item of items) {
      const key = item?.type || 'unknown';
      byType.set(key, (byType.get(key) || 0) + 1);
    }
    return Array.from(byType.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [items]);
  const selectedItems = useMemo(() => items.filter((item) => selected.has(itemKey(item))), [items, selected]);
  const selectedCount = selectedItems.length;
  const allVisibleSelected = Boolean(items.length) && items.every((item) => selected.has(itemKey(item)));

  function toggleSelected(item) {
    const key = itemKey(item);
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function selectAllVisible() {
    setSelected((current) => {
      const next = new Set(current);
      items.forEach((item) => next.add(itemKey(item)));
      return next;
    });
  }

  function clearSelection() {
    setSelected(new Set());
  }

  async function restore(item) {
    const key = `restore:${item.type}:${item.id}`;
    setBusyKey(key);
    try {
      await api.library.restoreContent(item.type, item.id);
      notify?.(t('trash.messages.restored', 'Inhalt wurde wiederhergestellt.'), 'success');
      await loadTrash();
      await onReload?.({ silent: true, forceContentRefresh: true });
    } catch (err) {
      notify?.(err?.message || t('trash.messages.restoreFailed', 'Inhalt konnte nicht wiederhergestellt werden.'), 'error');
    } finally {
      setBusyKey('');
    }
  }

  async function purge(item) {
    if (!confirm(t('trash.messages.purgeConfirm', '„{{title}}“ endgültig löschen?\n\nDiese Aktion kann nicht rückgängig gemacht werden.', { title: item.title || item.id }))) return;
    const key = `purge:${item.type}:${item.id}`;
    setBusyKey(key);
    try {
      await api.library.purgeContent(item.type, item.id, true);
      notify?.(t('trash.messages.purged', 'Inhalt wurde endgültig gelöscht.'), 'success');
      await loadTrash();
      await onReload?.({ silent: true, forceContentRefresh: true });
    } catch (err) {
      notify?.(err?.message || t('trash.messages.purgeFailed', 'Inhalt konnte nicht endgültig gelöscht werden.'), 'error');
    } finally {
      setBusyKey('');
    }
  }

  async function restoreSelected() {
    if (!selectedItems.length) return;
    setBusyKey('bulk-restore');
    try {
      const payload = { items: selectedItems.map((item) => ({ type: item.type, id: item.id })) };
      const result = await api.library.bulkRestoreContent(payload);
      const restoredCount = Number(result?.restored_count || result?.restored?.length || selectedItems.length);
      notify?.(t('trash.messages.bulkRestored', '{{count}} Inhalt(e) wurden wiederhergestellt.', { count: restoredCount }), 'success');
      clearSelection();
      await loadTrash();
      await onReload?.({ silent: true, forceContentRefresh: true });
    } catch (err) {
      notify?.(err?.message || t('trash.messages.bulkRestoreFailed', 'Auswahl konnte nicht wiederhergestellt werden.'), 'error');
    } finally {
      setBusyKey('');
    }
  }

  async function purgeItems(targetItems, { confirmMessage, emptyAfter = false } = {}) {
    if (!targetItems.length) return;
    if (confirmMessage && !confirm(confirmMessage)) return;
    setBusyKey(emptyAfter ? 'empty-trash' : 'bulk-purge');
    try {
      const results = await Promise.allSettled(targetItems.map((item) => api.library.purgeContent(item.type, item.id, true)));
      const purgedCount = results.filter((result) => result.status === 'fulfilled').length;
      const failedCount = results.length - purgedCount;
      if (purgedCount) notify?.(t('trash.messages.bulkPurged', '{{count}} Inhalt(e) wurden endgültig gelöscht.', { count: purgedCount }), 'success');
      if (failedCount) notify?.(t('trash.messages.bulkPurgePartialFailed', '{{count}} Inhalt(e) konnten nicht endgültig gelöscht werden.', { count: failedCount }), 'error');
      clearSelection();
      await loadTrash();
      await onReload?.({ silent: true, forceContentRefresh: true });
    } finally {
      setBusyKey('');
    }
  }

  async function purgeSelected() {
    await purgeItems(selectedItems, {
      confirmMessage: t('trash.messages.bulkPurgeConfirm', '{{count}} ausgewählte Inhalt(e) endgültig löschen?\n\nDiese Aktion kann nicht rückgängig gemacht werden.', { count: selectedItems.length })
    });
  }

  async function emptyTrash() {
    setBusyKey('load-empty-trash');
    try {
      const payload = await api.library.trash({ q: '', contentType: 'all', limit: 1000 });
      const allTrashItems = Array.isArray(payload) ? payload : [];
      setBusyKey('');
      if (!allTrashItems.length) {
        notify?.(t('trash.emptyTitle', 'Papierkorb ist leer'), 'info');
        return;
      }
      await purgeItems(allTrashItems, {
        emptyAfter: true,
        confirmMessage: t('trash.messages.emptyConfirm', 'Den gesamten Papierkorb mit {{count}} Inhalt(en) endgültig leeren?\n\nDiese Aktion kann nicht rückgängig gemacht werden.', { count: allTrashItems.length })
      });
    } catch (err) {
      setBusyKey('');
      notify?.(err?.message || t('trash.messages.loadFailed', 'Papierkorb konnte nicht geladen werden.'), 'error');
    }
  }

  function handleSubmit(event) {
    event.preventDefault();
    setAppliedQuery(query);
    setAppliedContentType(contentType);
    loadTrash(query, contentType);
  }

  return (
    <section className="page stack trash-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">{t('trash.eyebrow', 'Gelöschte Inhalte')}</p>
          <h1>{t('trash.title', 'Papierkorb')}</h1>
          <p className="muted">{t('trash.text', 'Hier landen Inhalte, die über Library-Aktionen in den Papierkorb verschoben wurden. Du kannst sie wiederherstellen oder endgültig entfernen.')}</p>
        </div>
        <button type="button" onClick={() => loadTrash()} disabled={loading}>
          <RefreshCw size={16} className={loading ? 'spin' : ''} /> {t('common.refresh', 'Aktualisieren')}
        </button>
      </header>

      <form className="trash-toolbar panel" onSubmit={handleSubmit}>
        <label>
          {t('common.search', 'Suche')}
          <span className="input-with-icon">
            <Search size={16} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('trash.searchPlaceholder', 'Titel oder Löschgrund suchen')} />
          </span>
        </label>
        <label>
          {t('trash.contentType', 'Inhaltstyp')}
          <select value={contentType} onChange={(event) => setContentType(event.target.value)}>
            {CONTENT_TYPES.map(([value, key]) => <option key={value} value={value}>{t(key, value)}</option>)}
          </select>
        </label>
        <button type="submit" disabled={loading}>{t('common.apply', 'Anwenden')}</button>
      </form>

      {!!stats.length && (
        <div className="trash-stats">
          {stats.map(([type, count]) => (
            <span key={type} className="badge">{typeLabel(type, t)}: {count}</span>
          ))}
        </div>
      )}

      {!!items.length && (
        <section className="trash-bulk-panel panel">
          <div>
            <strong>{t('trash.selectionTitle', 'Auswahl')}</strong>
            <small className="muted">{t('trash.selectedCount', '{{count}} ausgewählt', { count: selectedCount })}</small>
          </div>
          <div className="trash-bulk-actions">
            <button type="button" onClick={selectAllVisible} disabled={Boolean(busyKey) || allVisibleSelected}>{t('trash.selectAll', 'Alle auswählen')}</button>
            <button type="button" onClick={clearSelection} disabled={Boolean(busyKey) || !selectedCount}>{t('trash.clearSelection', 'Alle aufheben')}</button>
            <button type="button" onClick={restoreSelected} disabled={Boolean(busyKey) || !selectedCount}><RotateCcw size={15} /> {busyKey === 'bulk-restore' ? t('common.loading', 'Lädt…') : t('trash.restoreSelected', 'Auswahl wiederherstellen')}</button>
            <button type="button" className="danger" onClick={purgeSelected} disabled={Boolean(busyKey) || !selectedCount}><Trash2 size={15} /> {busyKey === 'bulk-purge' ? t('common.loading', 'Lädt…') : t('trash.purgeSelected', 'Auswahl endgültig löschen')}</button>
            <button type="button" className="danger ghost" onClick={emptyTrash} disabled={Boolean(busyKey)}><Trash2 size={15} /> {busyKey === 'empty-trash' || busyKey === 'load-empty-trash' ? t('common.loading', 'Lädt…') : t('trash.emptyTrash', 'Den gesamten Papierkorb leeren')}</button>
          </div>
        </section>
      )}

      {error && <p className="error-text">{error}</p>}

      {!loading && !items.length ? (
        <EmptyState title={t('trash.emptyTitle', 'Papierkorb ist leer')} text={t('trash.emptyText', 'Gelöschte Inhalte erscheinen hier, sobald sie per Soft-Delete entfernt wurden.')} />
      ) : (
        <div className="trash-list">
          {items.map((item) => {
            const restoreKey = `restore:${item.type}:${item.id}`;
            const purgeKey = `purge:${item.type}:${item.id}`;
            return (
              <article className={`trash-row ${selected.has(itemKey(item)) ? 'is-selected' : ''}`} key={`${item.type}-${item.id}`}>
                <label className="trash-select" title={t('trash.selectItem', '{{title}} auswählen', { title: item.title || item.id })}>
                  <input type="checkbox" checked={selected.has(itemKey(item))} onChange={() => toggleSelected(item)} />
                </label>
                <div>
                  <span className="badge">{typeLabel(item.type, t)}</span>
                  <h3>{item.title || `${item.type} #${item.id}`}</h3>
                  <p className="muted">
                    {t('trash.deletedAt', 'Gelöscht')}: {formatDate(item.deleted_at || item.updated_at)}
                    {item.deleted_reason ? ` · ${item.deleted_reason}` : ''}
                  </p>
                </div>
                <div className="trash-row-actions">
                  <button type="button" onClick={() => restore(item)} disabled={Boolean(busyKey)}>
                    <RotateCcw size={15} /> {busyKey === restoreKey ? t('common.loading', 'Lädt…') : t('trash.restore', 'Wiederherstellen')}
                  </button>
                  <button type="button" className="danger" onClick={() => purge(item)} disabled={Boolean(busyKey)}>
                    <Trash2 size={15} /> {busyKey === purgeKey ? t('common.loading', 'Lädt…') : t('trash.purge', 'Endgültig löschen')}
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
