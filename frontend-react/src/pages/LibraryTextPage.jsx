import React, { useMemo, useState } from 'react';
import { Copy, Download, Edit3, FileText, Music2, Save, Trash2, Upload } from 'lucide-react';
import { api } from '../api/client.js';
import { EmptyState } from '../components/EmptyState.jsx';
import { Modal } from '../components/Modal.jsx';
import { SectionHeader } from '../components/SectionHeader.jsx';
import { copyToClipboard, downloadTextFile, formatDate, lineCount, safeArray } from '../utils.js';
import { useI18n } from '../i18n/I18nContext.jsx';

export function LibraryTextPage({ lyrics, notify, onReload, useForMusic, searchQuery = '' }) {
  const { t } = useI18n();
  const [editor, setEditor] = useState(null);
  const filtered = useMemo(() => {
    const needle = String(searchQuery || '').toLowerCase().trim();
    if (!needle) return safeArray(lyrics, ['lyrics', 'items']);
    return safeArray(lyrics, ['lyrics', 'items']).filter((item) => [item.title, item.content, item.lyrics, item.prompt].filter(Boolean).join(' ').toLowerCase().includes(needle));
  }, [lyrics, searchQuery]);

  function openEditor(item = null) {
    setEditor(item ? { ...item, content: item.content || item.lyrics || '' } : { title: '', content: '' });
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
    <section className="page stack">
      <SectionHeader eyebrow={t('texts.eyebrow', 'Archiv')} title={t('texts.title', 'Songtexte')}>
        <button type="button" onClick={() => exportLyrics('csv', 'simple')}><Download size={15} /> {t('texts.basicCsv', 'Basis CSV')}</button>
        <button type="button" onClick={() => exportLyrics('markdown', 'extended')}><FileText size={15} /> {t('texts.detailsMd', 'Details MD')}</button>
        <label className="button"><Upload size={15} /> {t('texts.import', 'Import')}<input type="file" accept=".csv,.md,.markdown,text/csv,text/markdown,text/plain" hidden onChange={importLyricsFile} /></label>
        <button className="primary" onClick={() => openEditor()}>{t('texts.newText', 'Neuer Songtext')}</button>
      </SectionHeader>
      {!filtered.length && <EmptyState title={t('texts.emptyTitle', 'Keine Songtexte')} text={t('texts.emptyText', 'Erstelle im Songtext Studio oder direkt hier einen neuen Text.')} />}
      <div className="text-list improved-text-list">
        {filtered.map((item) => {
          const content = item.content || item.lyrics || '';
          return (
            <article className="panel text-card" key={item.id}>
              <div className="row between align-start"><div><h3>{item.title}</h3><p className="muted">{t('texts.lines', '{{count}} Zeilen', { count: lineCount(content) })} · {t('texts.characters', '{{count}} Zeichen', { count: content.length })} · {formatDate(item.updated_at || item.created_at)}</p></div></div>
              <pre>{content.slice(0, 900)}{content.length > 900 ? '\n…' : ''}</pre>
              <div className="button-row wrap">
                <button onClick={() => openEditor(item)}><Edit3 size={15} /> {t('texts.edit', 'Bearbeiten')}</button>
                <button onClick={() => useForMusic(item)}><Music2 size={15} /> {t('texts.createMusic', 'Musik erstellen')}</button>
                <button onClick={async () => { await copyToClipboard(content); notify(t('texts.messages.copied', 'Songtext kopiert.'), 'success'); }}><Copy size={15} /> {t('common.copy', 'Kopieren')}</button>
                <button className="danger" onClick={() => remove(item)}><Trash2 size={15} /> {t('texts.delete', 'Löschen')}</button>
              </div>
            </article>
          );
        })}
      </div>
      <Modal open={Boolean(editor)} title={editor?.id ? t('texts.editText', 'Songtext bearbeiten') : t('texts.newText', 'Neuer Songtext')} onClose={() => setEditor(null)} wide>
        {editor && <div className="stack"><input placeholder={t('texts.titlePlaceholder', 'Titel')} value={editor.title} onChange={(event) => setEditor({ ...editor, title: event.target.value })} /><textarea className="large" value={editor.content} onChange={(event) => setEditor({ ...editor, content: event.target.value })} /><button className="primary" onClick={save}><Save size={16} /> {t('texts.save', 'Speichern')}</button></div>}
      </Modal>
    </section>
  );
}
