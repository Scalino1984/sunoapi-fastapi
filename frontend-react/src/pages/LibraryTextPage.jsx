import React, { useMemo, useState } from 'react';
import { Copy, Download, Edit3, FileText, LayoutGrid, List, Music2, Save, Trash2, Upload } from 'lucide-react';
import { api } from '../api/client.js';
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

export function LibraryTextPage({ lyrics, notify, onReload, useForMusic, searchQuery = '' }) {
  const { t } = useI18n();
  const [editor, setEditor] = useState(null);
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

  function setViewMode(value) {
    setTextViewMode(value);
    storeTextViewMode(value);
  }

  function openEditor(item = null) {
    setEditor(item ? { ...item, content: lyricContent(item) } : { title: '', content: '' });
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
      <div className={`button-row wrap ${compact ? 'compact text-list-actions' : ''}`}>
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
            <span><strong>{textStats.count}</strong><small>{t('texts.stats.texts', 'Songtexte')}</small></span>
            <span><strong>{textStats.lines}</strong><small>{t('texts.stats.lines', 'Zeilen')}</small></span>
            <span><strong>{textStats.characters}</strong><small>{t('texts.stats.characters', 'Zeichen')}</small></span>
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
              <article className="panel text-card" key={item.id}>
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
        <div className="texts-list-view panel">
          {filtered.map((item) => {
            const stats = lyricStats(item);
            return (
              <article className="texts-list-row" key={item.id}>
                <div className="texts-list-main">
                  <div className="texts-list-title-row">
                    <h3>{item.title}</h3>
                    <span className="pill compact-pill">{t('texts.lines', '{{count}} Zeilen', { count: stats.lines })}</span>
                  </div>
                  <p className="muted texts-list-meta">{t('texts.characters', '{{count}} Zeichen', { count: stats.characters })} · {formatDate(stats.updatedAt)}</p>
                  <p className="texts-list-preview">{lyricPreview(stats.content, 220).replace(/\n+/g, ' · ')}</p>
                </div>
                {renderTextActions(item, true)}
              </article>
            );
          })}
        </div>
      )}

      <Modal open={Boolean(editor)} title={editor?.id ? t('texts.editText', 'Songtext bearbeiten') : t('texts.newText', 'Neuer Songtext')} onClose={() => setEditor(null)} wide>
        {editor && <div className="stack"><input placeholder={t('texts.titlePlaceholder', 'Titel')} value={editor.title} onChange={(event) => setEditor({ ...editor, title: event.target.value })} /><textarea className="large" value={editor.content} onChange={(event) => setEditor({ ...editor, content: event.target.value })} /><button type="button" className="primary" onClick={save}><Save size={16} /> {t('texts.save', 'Speichern')}</button></div>}
      </Modal>
    </section>
  );
}
