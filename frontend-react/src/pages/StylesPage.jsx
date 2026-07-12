import React, { useMemo, useState } from 'react';
import {
  ChevronLeft,
  ChevronRight,
  Copy,
  Download,
  Edit3,
  Eye,
  FileText,
  Heart,
  LayoutGrid,
  List,
  Music2,
  Save,
  Trash2,
  Upload,
} from 'lucide-react';
import { api } from '../api/client.js';
import { EmptyState } from '../components/EmptyState.jsx';
import { Modal } from '../components/Modal.jsx';
import { SectionHeader } from '../components/SectionHeader.jsx';
import { copyToClipboard, downloadTextFile, formatDate, safeArray } from '../utils.js';
import { useI18n } from '../i18n/I18nContext.jsx';

const styleViewStorageKey = 'react-styles-view-mode';
const styleViewModes = ['cards', 'list'];

function readStoredStyleViewMode() {
  try {
    const value = localStorage.getItem(styleViewStorageKey);
    return styleViewModes.includes(value) ? value : 'cards';
  } catch {
    return 'cards';
  }
}

function storeStyleViewMode(value) {
  if (!styleViewModes.includes(value)) return;
  try {
    localStorage.setItem(styleViewStorageKey, value);
  } catch {
    // localStorage kann in gehärteten Browser-Kontexten deaktiviert sein.
  }
}

function styleContent(style) {
  return String(style?.style_text || style?.content || style?.description || '').trim();
}

function styleTags(style) {
  return String(style?.tags || '')
    .split(/[,;|]/)
    .map((tag) => tag.trim())
    .filter(Boolean);
}

function stylePreview(content, maxLength = 420) {
  const normalized = String(content || '').replace(/\r\n/g, '\n').trim();
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, maxLength).trimEnd()}\n…`;
}

function formatNumber(value) {
  return new Intl.NumberFormat('de-DE').format(Number(value || 0));
}

function sanitizeFileName(value, fallback = 'style') {
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

function styleDownloadName(style) {
  const title = sanitizeFileName(style?.name, 'style');
  const id = style?.id ? `-${style.id}` : '';
  return `${title}${id}.txt`;
}

export function StylesPage({ styles, notify, onReload, useForMusic, searchQuery = '' }) {
  const { t } = useI18n();
  const [editor, setEditor] = useState(null);
  const [viewerId, setViewerId] = useState(null);
  const [styleViewMode, setStyleViewMode] = useState(readStoredStyleViewMode);

  const filtered = useMemo(() => {
    const query = String(searchQuery || '').trim().toLowerCase();
    const items = safeArray(styles, ['styles', 'items']);
    if (!query) return items;
    return items.filter((style) => [
      style.name,
      style.style_text,
      style.content,
      style.description,
      style.genre,
      style.tags,
      style.bpm,
    ].filter(Boolean).join(' ').toLowerCase().includes(query));
  }, [styles, searchQuery]);

  const styleStats = useMemo(() => {
    const genres = new Set();
    let favorites = 0;
    let usages = 0;
    filtered.forEach((style) => {
      const genre = String(style?.genre || '').trim().toLowerCase();
      if (genre) genres.add(genre);
      if (style?.is_favorite) favorites += 1;
      usages += Number(style?.usage_count || 0);
    });
    return { count: filtered.length, genres: genres.size, favorites, usages };
  }, [filtered]);

  const viewerIndex = useMemo(() => {
    if (viewerId == null) return -1;
    return filtered.findIndex((style) => String(style.id) === String(viewerId));
  }, [filtered, viewerId]);

  const viewerItem = viewerIndex >= 0 ? filtered[viewerIndex] : null;

  function setViewMode(value) {
    setStyleViewMode(value);
    storeStyleViewMode(value);
  }

  function openEditor(style = null) {
    setEditor(style
      ? { ...style, style_text: styleContent(style) }
      : { name: '', style_text: '', description: '', genre: '', bpm: '', tags: '', is_favorite: false });
  }

  function openViewer(style) {
    if (!style) return;
    setViewerId(style.id);
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

  function handleViewerKey(event, style) {
    if (event.target?.closest?.('button, a, input, textarea, select, [contenteditable="true"]')) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      openViewer(style);
    }
  }

  async function save() {
    if (!editor?.name?.trim()) return notify(t('stylesPage.messages.nameMissing', 'Name fehlt.'), 'error');
    if (!editor?.style_text?.trim()) return notify(t('stylesPage.messages.styleMissing', 'Style-Inhalt fehlt.'), 'error');
    const bpmValue = String(editor.bpm ?? '').trim();
    const payload = {
      ...editor,
      bpm: bpmValue ? Number.parseInt(bpmValue, 10) : null,
      content: editor.style_text,
    };
    if (editor.id) await api.library.updateStyle(editor.id, payload);
    else await api.library.createStyle(payload);
    setEditor(null);
    notify(t('stylesPage.messages.saved', 'Style gespeichert.'), 'success');
    await onReload();
  }

  async function remove(style) {
    if (!confirm(t('stylesPage.messages.confirmDelete', 'Style "{{name}}" löschen?', { name: style.name }))) return;
    await api.library.deleteContent('style', style.id);
    if (String(viewerId) === String(style.id)) closeViewer();
    notify(t('stylesPage.messages.deleted', 'Style wurde gelöscht.'), 'success');
    await onReload();
  }

  async function toggleFavorite(style) {
    await api.library.updateStyle(style.id, { is_favorite: !Boolean(style.is_favorite) });
    notify(
      style.is_favorite
        ? t('stylesPage.messages.favoriteRemoved', 'Style aus Favoriten entfernt.')
        : t('stylesPage.messages.favoriteAdded', 'Style als Favorit gespeichert.'),
      'success',
    );
    await onReload();
  }

  async function copyStyle(style) {
    await copyToClipboard(styleContent(style));
    notify(t('stylesPage.messages.copied', 'Style kopiert.'), 'success');
  }

  function downloadStyleTxt(style) {
    downloadTextFile(styleDownloadName(style), styleContent(style), 'text/plain;charset=utf-8');
    notify(t('stylesPage.messages.txtDownloaded', 'Style als TXT heruntergeladen.'), 'success');
  }

  async function useStyleForMusic(style) {
    if (typeof useForMusic !== 'function') return;
    await useForMusic(style);
  }

  function renderStyleActions(style, compact = false) {
    return (
      <div className={`button-row wrap ${compact ? 'compact styles-list-actions' : ''}`} onClick={(event) => event.stopPropagation()}>
        <button type="button" className="ghost" onClick={() => openViewer(style)}><Eye size={15} /> {t('stylesPage.view', 'Ansehen')}</button>
        <button type="button" onClick={() => openEditor(style)}><Edit3 size={15} /> {t('stylesPage.edit', 'Bearbeiten')}</button>
        <button type="button" onClick={() => useStyleForMusic(style)}><Music2 size={15} /> {t('stylesPage.createMusic', 'Musik erstellen')}</button>
        <button type="button" onClick={() => copyStyle(style)}><Copy size={15} /> {t('common.copy', 'Kopieren')}</button>
        <button type="button" className={style.is_favorite ? 'active' : ''} onClick={() => toggleFavorite(style)} aria-label={t('stylesPage.favorite', 'Favorit')}><Heart size={15} fill={style.is_favorite ? 'currentColor' : 'none'} /></button>
        <button type="button" className="danger" onClick={() => remove(style)}><Trash2 size={15} /> {t('stylesPage.delete', 'Löschen')}</button>
      </div>
    );
  }

  async function importStylesFile(event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    try {
      const result = await api.library.importStyles(file);
      notify(t('stylesPage.messages.imported', 'Styles importiert: {{imported}}, übersprungen: {{skipped}}.', { imported: result.imported || 0, skipped: result.skipped || 0 }), result.errors?.length ? 'info' : 'success');
      await onReload();
    } catch (err) {
      notify(err?.message || t('stylesPage.messages.importFailed', 'Styles-Import fehlgeschlagen.'), 'error');
    }
  }

  async function exportStyles(format = 'csv', mode = 'extended') {
    try {
      const content = await api.library.exportStyles(format, mode);
      const extension = format === 'markdown' || format === 'md' ? 'md' : 'csv';
      const mime = extension === 'md' ? 'text/markdown;charset=utf-8' : 'text/csv;charset=utf-8';
      downloadTextFile(`suno-styles-${mode}.${extension}`, content, mime);
      notify(t('stylesPage.messages.exportCreated', 'Styles-{{mode}}export wurde erstellt.', { mode: mode === 'extended' ? t('stylesPage.detail', 'Detail') : t('stylesPage.basic', 'Basis') }), 'success');
    } catch (err) {
      notify(err?.message || t('stylesPage.messages.exportFailed', 'Styles-Export fehlgeschlagen.'), 'error');
    }
  }

  return (
    <section className="page stack styles-page">
      <SectionHeader eyebrow={t('stylesPage.eyebrow', 'Presets')} title={t('nav.styles', 'Styles')}>
        <button type="button" onClick={() => exportStyles('csv', 'simple')}><Download size={15} /> {t('stylesPage.basicCsv', 'Basis CSV')}</button>
        <button type="button" onClick={() => exportStyles('markdown', 'extended')}><FileText size={15} /> {t('stylesPage.detailsMd', 'Details MD')}</button>
        <label className="button"><Upload size={15} /> {t('stylesPage.import', 'Import')}<input type="file" accept=".csv,.md,.markdown,text/csv,text/markdown,text/plain" hidden onChange={importStylesFile} /></label>
        <button type="button" className="primary" onClick={() => openEditor()}>{t('stylesPage.newStyle', 'Neuer Style')}</button>
      </SectionHeader>

      <div className="styles-toolbar panel slim-panel">
        <div className="library-pagination-left">
          <div className="button-row wrap view-mode-switcher" aria-label={t('stylesPage.viewModeAria', 'Style-Ansicht umschalten')}>
            <button type="button" className={styleViewMode === 'cards' ? 'active' : ''} onClick={() => setViewMode('cards')}><LayoutGrid size={15} /> {t('stylesPage.views.cards', 'Karten')}</button>
            <button type="button" className={styleViewMode === 'list' ? 'active' : ''} onClick={() => setViewMode('list')}><List size={15} /> {t('stylesPage.views.list', 'Liste')}</button>
          </div>
          <div className="library-count-pill style-count-summary">
            <span><strong>{formatNumber(styleStats.count)}</strong><small>{t('stylesPage.stats.styles', 'Styles')}</small></span>
            <span><strong>{formatNumber(styleStats.genres)}</strong><small>{t('stylesPage.stats.genres', 'Genres')}</small></span>
            <span><strong>{formatNumber(styleStats.favorites)}</strong><small>{t('stylesPage.stats.favorites', 'Favoriten')}</small></span>
            <span><strong>{formatNumber(styleStats.usages)}</strong><small>{t('stylesPage.stats.usages', 'Verwendungen')}</small></span>
          </div>
        </div>
        {searchQuery && <p className="muted style-search-hint">{t('stylesPage.searchActive', 'Gefiltert nach: {{query}}', { query: searchQuery })}</p>}
      </div>

      {!filtered.length && <EmptyState title={t('stylesPage.emptyTitle', 'Keine Styles')} text={t('stylesPage.emptyText', 'Erstelle direkt hier einen neuen Style oder importiere vorhandene Presets.')} />}

      {Boolean(filtered.length) && styleViewMode === 'cards' && (
        <div className="style-grid improved-style-grid">
          {filtered.map((style) => {
            const tags = styleTags(style);
            return (
              <article className={`panel style-card style-card-clickable ${style.is_favorite ? 'favorite' : ''}`} key={style.id} role="button" tabIndex={0} onClick={() => openViewer(style)} onKeyDown={(event) => handleViewerKey(event, style)} aria-label={t('stylesPage.openViewerAria', 'Style vollständig anzeigen')}>
                <div className="row between align-start style-card-heading">
                  <div>
                    <h3>{style.name || t('stylesPage.untitled', 'Ohne Namen')}</h3>
                    <p className="muted">{style.genre || t('stylesPage.noGenre', 'Ohne Genre')} · {style.bpm ? `${style.bpm} BPM` : t('stylesPage.noBpm', 'BPM offen')} · {t('stylesPage.usedCount', '{{count}}× verwendet', { count: Number(style.usage_count || 0) })}</p>
                  </div>
                  {style.is_favorite && <span className="badge success"><Heart size={13} fill="currentColor" /> {t('stylesPage.favorite', 'Favorit')}</span>}
                </div>
                {tags.length > 0 && <div className="style-tag-row">{tags.slice(0, 8).map((tag) => <span className="badge" key={tag}>{tag}</span>)}</div>}
                <pre className="style-card-preview">{stylePreview(styleContent(style), 900)}</pre>
                {renderStyleActions(style)}
              </article>
            );
          })}
        </div>
      )}

      {Boolean(filtered.length) && styleViewMode === 'list' && (
        <div className="styles-list-view panel" role="table" aria-label={t('stylesPage.listAria', 'Styles als Listenansicht')}>
          <div className="styles-list-header" role="row">
            <span>{t('stylesPage.listColumns.style', 'Style')}</span>
            <span>{t('stylesPage.listColumns.profile', 'Profil')}</span>
            <span>{t('stylesPage.listColumns.usage', 'Nutzung')}</span>
            <span>{t('stylesPage.listColumns.preview', 'Vorschau')}</span>
            <span>{t('stylesPage.listColumns.actions', 'Aktionen')}</span>
          </div>
          {filtered.map((style, index) => {
            const tags = styleTags(style);
            const preview = stylePreview(styleContent(style), 280).replace(/\n+/g, ' · ');
            return (
              <article className="styles-list-row" key={style.id} role="row" tabIndex={0} onClick={() => openViewer(style)} onKeyDown={(event) => handleViewerKey(event, style)} aria-label={t('stylesPage.openViewerAria', 'Style vollständig anzeigen')}>
                <div className="styles-list-title-cell" role="cell">
                  <span className="styles-list-index">{String(index + 1).padStart(2, '0')}</span>
                  <div className="styles-list-title-copy">
                    <h3>{style.name || t('stylesPage.untitled', 'Ohne Namen')}</h3>
                    <p>{style.is_profile ? t('stylesPage.profile', 'Style-Profil') : t('stylesPage.preset', 'Style-Preset')}</p>
                  </div>
                  {style.is_favorite && <Heart className="styles-favorite-icon" size={16} fill="currentColor" aria-label={t('stylesPage.favorite', 'Favorit')} />}
                </div>
                <div className="styles-list-profile-cell" role="cell">
                  <span>{style.genre || t('stylesPage.noGenre', 'Ohne Genre')}</span>
                  <small>{style.bpm ? `${style.bpm} BPM` : t('stylesPage.noBpm', 'BPM offen')}</small>
                  {tags.length > 0 && <small title={tags.join(', ')}>{tags.slice(0, 3).join(' · ')}</small>}
                </div>
                <div className="styles-list-usage-cell" role="cell">
                  <span className="texts-stat-badge primary"><strong>{formatNumber(style.usage_count)}</strong><small>{t('stylesPage.stats.usages', 'Verwendungen')}</small></span>
                  <span>{formatDate(style.updated_at || style.created_at)}</span>
                </div>
                <div className="styles-list-preview-cell" role="cell"><p>{preview || t('stylesPage.emptyPreview', 'Keine Vorschau vorhanden.')}</p></div>
                <div className="styles-list-action-cell" role="cell">{renderStyleActions(style, true)}</div>
              </article>
            );
          })}
        </div>
      )}

      <Modal open={Boolean(viewerItem)} title={viewerItem?.name || t('stylesPage.untitled', 'Ohne Namen')} onClose={closeViewer} wide cardClassName="style-viewer-modal" contentClassName="style-viewer-content">
        {viewerItem && (
          <div className="style-viewer stack">
            <div className="style-viewer-toolbar">
              <button type="button" className="icon-button" onClick={() => navigateViewer(-1)} aria-label={t('stylesPage.viewer.previous', 'Vorheriger Style')} disabled={filtered.length < 2}><ChevronLeft size={20} /></button>
              <div className="style-viewer-position">
                <strong>{t('stylesPage.viewer.position', '{{current}} / {{total}}', { current: viewerIndex + 1, total: filtered.length })}</strong>
                <span>{viewerItem.genre || t('stylesPage.noGenre', 'Ohne Genre')} · {viewerItem.bpm ? `${viewerItem.bpm} BPM` : t('stylesPage.noBpm', 'BPM offen')} · {t('stylesPage.usedCount', '{{count}}× verwendet', { count: Number(viewerItem.usage_count || 0) })}</span>
              </div>
              <button type="button" className="icon-button" onClick={() => navigateViewer(1)} aria-label={t('stylesPage.viewer.next', 'Nächster Style')} disabled={filtered.length < 2}><ChevronRight size={20} /></button>
              <div className="style-viewer-actions">
                <button type="button" onClick={() => downloadStyleTxt(viewerItem)}><Download size={15} /> {t('stylesPage.viewer.downloadTxt', 'TXT herunterladen')}</button>
                <button type="button" onClick={() => copyStyle(viewerItem)}><Copy size={15} /> {t('common.copy', 'Kopieren')}</button>
                <button type="button" onClick={() => toggleFavorite(viewerItem)}><Heart size={15} fill={viewerItem.is_favorite ? 'currentColor' : 'none'} /> {t('stylesPage.favorite', 'Favorit')}</button>
                <button type="button" onClick={() => openEditor(viewerItem)}><Edit3 size={15} /> {t('stylesPage.edit', 'Bearbeiten')}</button>
                <button type="button" className="primary" onClick={() => useStyleForMusic(viewerItem)}><Music2 size={15} /> {t('stylesPage.createMusic', 'Musik erstellen')}</button>
              </div>
            </div>
            <div className="style-viewer-meta">
              {viewerItem.genre && <span>{viewerItem.genre}</span>}
              {viewerItem.bpm && <span>{viewerItem.bpm} BPM</span>}
              <span>{t('stylesPage.usedCount', '{{count}}× verwendet', { count: Number(viewerItem.usage_count || 0) })}</span>
              <span>{formatDate(viewerItem.updated_at || viewerItem.created_at)}</span>
            </div>
            {styleTags(viewerItem).length > 0 && <div className="style-tag-row">{styleTags(viewerItem).map((tag) => <span className="badge" key={tag}>{tag}</span>)}</div>}
            {viewerItem.description && <p className="style-viewer-description">{viewerItem.description}</p>}
            <pre className="style-viewer-pre">{styleContent(viewerItem) || t('stylesPage.emptyPreview', 'Keine Vorschau vorhanden.')}</pre>
          </div>
        )}
      </Modal>

      <Modal open={Boolean(editor)} title={editor?.id ? t('stylesPage.editStyle', 'Style bearbeiten') : t('stylesPage.newStyle', 'Neuer Style')} onClose={() => setEditor(null)} wide>
        {editor && (
          <div className="form-grid">
            <label>{t('stylesPage.name', 'Name')}<input value={editor.name || ''} onChange={(event) => setEditor({ ...editor, name: event.target.value })} /></label>
            <label>{t('stylesPage.genre', 'Genre')}<input value={editor.genre || ''} onChange={(event) => setEditor({ ...editor, genre: event.target.value })} /></label>
            <label>BPM<input type="number" min="1" max="999" value={editor.bpm || ''} onChange={(event) => setEditor({ ...editor, bpm: event.target.value })} /></label>
            <label>{t('stylesPage.tags', 'Tags')}<input value={editor.tags || ''} onChange={(event) => setEditor({ ...editor, tags: event.target.value })} /></label>
            <label className="wide">{t('stylesPage.description', 'Beschreibung')}<textarea value={editor.description || ''} onChange={(event) => setEditor({ ...editor, description: event.target.value })} /></label>
            <label className="wide">{t('stylesPage.style', 'Style')}<textarea className="large" value={editor.style_text || ''} onChange={(event) => setEditor({ ...editor, style_text: event.target.value })} /></label>
            <label className="checkbox-row"><input type="checkbox" checked={Boolean(editor.is_favorite)} onChange={(event) => setEditor({ ...editor, is_favorite: event.target.checked })} /> {t('stylesPage.favorite', 'Favorit')}</label>
            <button type="button" className="primary" onClick={save}><Save size={16} /> {t('stylesPage.save', 'Speichern')}</button>
          </div>
        )}
      </Modal>
    </section>
  );
}
