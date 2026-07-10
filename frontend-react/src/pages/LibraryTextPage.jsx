import React, { useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight, Copy, Download, Edit3, Eye, FileText, LayoutGrid, List, Music2, Save, Trash2, Upload } from 'lucide-react';
import { api } from '../api/client.js';
// Schutz: /texts besitzt Kartenansicht, strukturierte Listenansicht und Viewer-Modal; Layout-Patches duerfen diese drei Modi nicht gegeneinander ueberschreiben.
import { EmptyState } from '../components/EmptyState.jsx';
import { Modal } from '../components/Modal.jsx';
import { SectionHeader } from '../components/SectionHeader.jsx';
import { copyToClipboard, downloadTextFile, formatDate, lineCount, safeArray } from '../utils.js';
import { useI18n } from '../i18n/I18nContext.jsx';

const textViewStorageKey = 'react-texts-view-mode';
const textViewModes = ['cards', 'list'];

function readStoredTextViewMode() {
  try {
    const value = localStorage.getItem(textViewStorageKey);
    return textViewModes.includes(value) ? value : 'cards';
  } catch {
    return 'cards';
  }
}

function storeTextViewMode(value) {
  if (!textViewModes.includes(value)) return;
  try {
    localStorage.setItem(textViewStorageKey, value);
  } catch {
    // localStorage can be unavailable in hardened browser contexts; the UI still works with state only.
  }
}

function lyricContent(item) {
  return item?.content || item?.lyrics || '';
}

function lyricStats(item) {
  const content = lyricContent(item);
  return {
    content,
    lines: lineCount(content),
    characters: content.length,
    updatedAt: item?.updated_at || item?.created_at,
  };
}

function lyricPreview(content, maxLength = 360) {
  const normalized = String(content || '').replace(/\r\n/g, '\n').trim();
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, maxLength).trimEnd()}\n…`;
}

function formatNumber(value) {
  return new Intl.NumberFormat('de-DE').format(Number(value || 0));
}

function sanitizeFileName(value, fallback = 'songtext') {
  const cleaned = String(value || fallback)
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9._ -]+/g, '-')
    .replace(/\s+/g, '_')
    .replace(/-+/g, '-')
    .replace(/^[-_.\s]+|[-_.\s]+$/g, '')
    .slice(0, 90);
  return cleaned || fallback;
}

function lyricDownloadName(item) {
  const title = sanitizeFileName(item?.title, 'songtext');
  const id = item?.id ? `-${item.id}` : '';
  return `${title}${id}.txt`;
}

export function LibraryTextPage({ lyrics, notify, onReload, useForMusic, searchQuery = '' }) {
  const { t } = useI18n();
  const [editor, setEditor] = useState(null);
  const [viewerId, setViewerId] = useState(null);
  const [textViewMode, setTextViewMode] = useState(readStoredTextViewMode);

  const filtered = useMemo(() => {
    const needle = String(searchQuery || '').toLowerCase().trim();
    const items = safeArray(lyrics, ['lyrics', 'items']);
    if (!needle) return items;
    return items.filter((item) => [item.title, item.content, item.lyrics, item.prompt].filter(Boolean).join(' ').toLowerCase().includes(needle));
  }, [lyrics, searchQuery]);

  const textStats = useMemo(() => {
    const totals = filtered.reduce((acc, item) => {
      const stats = lyricStats(item);
      acc.lines += stats.lines;
      acc.characters += stats.characters;
      return acc;
    }, { lines: 0, characters: 0 });
    return { count: filtered.length, ...totals };
  }, [filtered]);


  const viewerIndex = useMemo(() => {
    if (viewerId == null) return -1;
    return filtered.findIndex((item) => String(item.id) === String(viewerId));
  }, [filtered, viewerId]);

  const viewerItem = viewerIndex >= 0 ? filtered[viewerIndex] : null;
  const viewerStats = viewerItem ? lyricStats(viewerItem) : null;

  function setViewMode(value) {
    setTextViewMode(value);
    storeTextViewMode(value);
  }

  function openEditor(item = null) {
    setEditor(item ? { ...item, content: lyricContent(item) } : { title: '', content: '' });
  }


  function openViewer(item) {
    if (!item) return;
    setViewerId(item.id);
  }

  function closeViewer() {
    setViewerId(null);
  }

  function navigateViewer(direction) {
    if (!filtered.length) return;
    const current = viewerIndex >= 0 ? viewerIndex : 0;
    const nextIndex = (current + direction + filtered.length) % filtered.length;
    setViewerId(filtered[nextIndex]?.id ?? null);
  }

  function handleViewerKey(event, item) {
    if (event.target?.closest?.('button, a, input, textarea, select, [contenteditable="true"]')) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      openViewer(item);
    }
  }

  function downloadLyricTxt(item) {
    if (!item) return;
    const content = lyricContent(item);
    downloadTextFile(lyricDownloadName(item), content, 'text/plain;charset=utf-8');
    notify(t('texts.messages.txtDownloaded', 'Songtext als TXT heruntergeladen.'), 'success');
  }

  async function save() {
    if (!editor?.title?.trim()) return notify(t('texts.messages.titleMissing', 'Titel fehlt.'), 'error');
    if (editor.id) await api.library.updateLyric(editor.id, { title: editor.title, content: editor.content, lyrics: editor.content });
    else await api.library.createLyric({ title: editor.title, content: editor.content, lyrics: editor.content });
    setEditor(null);
    notify(t('texts.messages.saved', 'Songtext gespeichert.'), 'success');
    onReload();
  }

  async function remove(item) {
    if (!confirm(t('texts.messages.confirmDelete', 'Songtext "{{title}}" löschen?', { title: item.title }))) return;
    await api.library.deleteContent('lyric', item.id);
    notify(t('texts.messages.deleted', 'Songtext wurde gelöscht.'), 'success');
    onReload();
  }

  async function copyLyric(item) {
    await copyToClipboard(lyricContent(item));
    notify(t('texts.messages.copied', 'Songtext kopiert.'), 'success');
  }

  function renderTextActions(item, compact = false) {
    return (
      <div className={`button-row wrap ${compact ? 'compact text-list-actions' : ''}`} onClick={(event) => event.stopPropagation()}>
        <button type="button" className="ghost" onClick={() => openViewer(item)}><Eye size={15} /> {t('texts.view', 'Ansehen')}</button>
        <button type="button" onClick={() => openEditor(item)}><Edit3 size={15} /> {t('texts.edit', 'Bearbeiten')}</button>
        <button type="button" onClick={() => useForMusic(item)}><Music2 size={15} /> {t('texts.createMusic', 'Musik erstellen')}</button>
        <button type="button" onClick={() => copyLyric(item)}><Copy size={15} /> {t('common.copy', 'Kopieren')}</button>
        <button type="button" className="danger" onClick={() => remove(item)}><Trash2 size={15} /> {t('texts.delete', 'Löschen')}</button>
      </div>
    );
  }

  async function importLyricsFile(event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    try {
      const result = await api.library.importLyrics(file);
      notify(t('texts.messages.imported', 'Songtexte importiert: {{imported}}, übersprungen: {{skipped}}.', { imported: result.imported || 0, skipped: result.skipped || 0 }), result.errors?.length ? 'info' : 'success');
      await onReload();
    } catch (err) {
      notify(err?.message || t('texts.messages.importFailed', 'Songtext-Import fehlgeschlagen.'), 'error');
    }
  }

  async function exportLyrics(format = 'csv', mode = 'extended') {
    try {
      const content = await api.library.exportLyrics(format, mode);
      const extension = format === 'markdown' || format === 'md' ? 'md' : 'csv';
      const mime = extension === 'md' ? 'text/markdown;charset=utf-8' : 'text/csv;charset=utf-8';
      downloadTextFile(`suno-songtexte-${mode}.${extension}`, content, mime);
      notify(t('texts.messages.exportCreated', 'Songtext-{{mode}}export wurde erstellt.', { mode: mode === 'extended' ? t('texts.detail', 'Detail') : t('texts.basic', 'Basis') }), 'success');
    } catch (err) {
      notify(err?.message || t('texts.messages.exportFailed', 'Songtext-Export fehlgeschlagen.'), 'error');
    }
  }

  return (
    <section className="page stack texts-page">
      <SectionHeader eyebrow={t('texts.eyebrow', 'Archiv')} title={t('texts.title', 'Songtexte')}>
        <button type="button" onClick={() => exportLyrics('csv', 'simple')}><Download size={15} /> {t('texts.basicCsv', 'Basis CSV')}</button>
        <button type="button" onClick={() => exportLyrics('markdown', 'extended')}><FileText size={15} /> {t('texts.detailsMd', 'Details MD')}</button>
        <label className="button"><Upload size={15} /> {t('texts.import', 'Import')}<input type="file" accept=".csv,.md,.markdown,text/csv,text/markdown,text/plain" hidden onChange={importLyricsFile} /></label>
        <button type="button" className="primary" onClick={() => openEditor()}>{t('texts.newText', 'Neuer Songtext')}</button>
      </SectionHeader>

      <div className="texts-toolbar panel slim-panel">
        <div className="library-pagination-left">
          <div className="button-row wrap view-mode-switcher" aria-label={t('texts.viewModeAria', 'Songtext-Ansicht umschalten')}>
            <button type="button" className={textViewMode === 'cards' ? 'active' : ''} onClick={() => setViewMode('cards')}><LayoutGrid size={15} /> {t('texts.views.cards', 'Karten')}</button>
            <button type="button" className={textViewMode === 'list' ? 'active' : ''} onClick={() => setViewMode('list')}><List size={15} /> {t('texts.views.list', 'Liste')}</button>
          </div>
          <div className="library-count-pill text-count-summary" title={t('texts.statsTitle', '{{count}} Songtexte · {{lines}} Zeilen · {{characters}} Zeichen', textStats)}>
            <span><strong>{formatNumber(textStats.count)}</strong><small>{t('texts.stats.texts', 'Songtexte')}</small></span>
            <span><strong>{formatNumber(textStats.lines)}</strong><small>{t('texts.stats.lines', 'Zeilen')}</small></span>
            <span><strong>{formatNumber(textStats.characters)}</strong><small>{t('texts.stats.characters', 'Zeichen')}</small></span>
          </div>
        </div>
        {searchQuery && <p className="muted text-search-hint">{t('texts.searchActive', 'Gefiltert nach: {{query}}', { query: searchQuery })}</p>}
      </div>

      {!filtered.length && <EmptyState title={t('texts.emptyTitle', 'Keine Songtexte')} text={t('texts.emptyText', 'Erstelle im Songtext Studio oder direkt hier einen neuen Text.')} />}

      {Boolean(filtered.length) && textViewMode === 'cards' && (
        <div className="text-list improved-text-list">
          {filtered.map((item) => {
            const stats = lyricStats(item);
            return (
              <article className="panel text-card text-card-clickable" key={item.id} role="button" tabIndex={0} onClick={() => openViewer(item)} onKeyDown={(event) => handleViewerKey(event, item)} aria-label={t('texts.openViewerAria', 'Songtext vollständig anzeigen')}>
                <div className="row between align-start">
                  <div>
                    <h3>{item.title}</h3>
                    <p className="muted">{t('texts.lines', '{{count}} Zeilen', { count: stats.lines })} · {t('texts.characters', '{{count}} Zeichen', { count: stats.characters })} · {formatDate(stats.updatedAt)}</p>
                  </div>
                </div>
                <pre>{lyricPreview(stats.content, 900)}</pre>
                {renderTextActions(item)}
              </article>
            );
          })}
        </div>
      )}

      {Boolean(filtered.length) && textViewMode === 'list' && (
        <div className="texts-list-view panel" role="table" aria-label={t('texts.listAria', 'Songtexte als Listenansicht')}>
          <div className="texts-list-header" role="row">
            <span>{t('texts.listColumns.title', 'Songtext')}</span>
            <span>{t('texts.listColumns.scope', 'Umfang')}</span>
            <span>{t('texts.listColumns.updated', 'Geändert')}</span>
            <span>{t('texts.listColumns.preview', 'Vorschau')}</span>
            <span>{t('texts.listColumns.actions', 'Aktionen')}</span>
          </div>
          {filtered.map((item, index) => {
            const stats = lyricStats(item);
            const preview = lyricPreview(stats.content, 280).replace(/\n+/g, ' · ');
            return (
              <article className="texts-list-row" key={item.id} role="row" tabIndex={0} onClick={() => openViewer(item)} onKeyDown={(event) => handleViewerKey(event, item)} aria-label={t('texts.openViewerAria', 'Songtext vollständig anzeigen')}>
                <div className="texts-list-title-cell" role="cell">
                  <span className="texts-list-index">{String(index + 1).padStart(2, '0')}</span>
                  <div className="texts-list-title-copy">
                    <h3>{item.title || t('texts.untitled', 'Ohne Titel')}</h3>
                    <p>{t('texts.listDraftType', 'Songtext-Entwurf')}</p>
                  </div>
                </div>
                <div className="texts-list-stat-cell" role="cell">
                  <span className="texts-stat-badge primary"><strong>{formatNumber(stats.lines)}</strong><small>{t('texts.stats.lines', 'Zeilen')}</small></span>
                  <span className="texts-stat-badge"><strong>{formatNumber(stats.characters)}</strong><small>{t('texts.stats.characters', 'Zeichen')}</small></span>
                </div>
                <div className="texts-list-date-cell" role="cell">
                  <span>{formatDate(stats.updatedAt)}</span>
                </div>
                <div className="texts-list-preview-cell" role="cell">
                  <p>{preview || t('texts.emptyPreview', 'Keine Vorschau vorhanden.')}</p>
                </div>
                <div className="texts-list-action-cell" role="cell">
                  {renderTextActions(item, true)}
                </div>
              </article>
            );
          })}
        </div>
      )}

      <Modal open={Boolean(viewerItem)} title={viewerItem?.title || t('texts.untitled', 'Ohne Titel')} onClose={closeViewer} wide cardClassName="lyric-viewer-modal" contentClassName="lyric-viewer-content">
        {viewerItem && viewerStats && (
          <div className="lyric-viewer stack">
            <div className="lyric-viewer-toolbar">
              <button type="button" className="icon-button" onClick={() => navigateViewer(-1)} aria-label={t('texts.viewer.previous', 'Vorheriger Songtext')} disabled={filtered.length < 2}><ChevronLeft size={20} /></button>
              <div className="lyric-viewer-position">
                <strong>{t('texts.viewer.position', '{{current}} / {{total}}', { current: viewerIndex + 1, total: filtered.length })}</strong>
                <span>{t('texts.statsTitle', '{{count}} Songtexte · {{lines}} Zeilen · {{characters}} Zeichen', { count: 1, lines: viewerStats.lines, characters: viewerStats.characters })}</span>
              </div>
              <button type="button" className="icon-button" onClick={() => navigateViewer(1)} aria-label={t('texts.viewer.next', 'Nächster Songtext')} disabled={filtered.length < 2}><ChevronRight size={20} /></button>
              <div className="lyric-viewer-actions">
                <button type="button" onClick={() => downloadLyricTxt(viewerItem)}><Download size={15} /> {t('texts.viewer.downloadTxt', 'TXT herunterladen')}</button>
                <button type="button" onClick={() => copyLyric(viewerItem)}><Copy size={15} /> {t('common.copy', 'Kopieren')}</button>
                <button type="button" onClick={() => openEditor(viewerItem)}><Edit3 size={15} /> {t('texts.edit', 'Bearbeiten')}</button>
                <button type="button" className="primary" onClick={() => useForMusic(viewerItem)}><Music2 size={15} /> {t('texts.createMusic', 'Musik erstellen')}</button>
              </div>
            </div>
            <div className="lyric-viewer-meta">
              <span>{t('texts.lines', '{{count}} Zeilen', { count: viewerStats.lines })}</span>
              <span>{t('texts.characters', '{{count}} Zeichen', { count: formatNumber(viewerStats.characters) })}</span>
              <span>{formatDate(viewerStats.updatedAt)}</span>
            </div>
            <pre className="lyric-viewer-pre">{viewerStats.content || t('texts.emptyPreview', 'Keine Vorschau vorhanden.')}</pre>
          </div>
        )}
      </Modal>

      <Modal open={Boolean(editor)} title={editor?.id ? t('texts.editText', 'Songtext bearbeiten') : t('texts.newText', 'Neuer Songtext')} onClose={() => setEditor(null)} wide>
        {editor && <div className="stack"><input placeholder={t('texts.titlePlaceholder', 'Titel')} value={editor.title} onChange={(event) => setEditor({ ...editor, title: event.target.value })} /><textarea className="large" value={editor.content} onChange={(event) => setEditor({ ...editor, content: event.target.value })} /><button type="button" className="primary" onClick={save}><Save size={16} /> {t('texts.save', 'Speichern')}</button></div>}
      </Modal>
    </section>
  );
}
