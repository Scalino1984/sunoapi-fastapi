import React, { useMemo, useState } from 'react';
import { Copy, Download, Edit3, FileText, Save, Upload } from 'lucide-react';
import { api } from '../api/client.js';
import { Modal } from '../components/Modal.jsx';
import { SectionHeader } from '../components/SectionHeader.jsx';
import { copyToClipboard, downloadTextFile, safeArray, summarizeStyle } from '../utils.js';

export function StylesPage({ styles, notify, onReload, searchQuery = '' }) {
  const [editor, setEditor] = useState(null);
  const query = String(searchQuery || '').trim().toLowerCase();
  const filtered = useMemo(() => safeArray(styles, ['styles', 'items']).filter((style) => !query || [style.name, style.style_text, style.content, style.description, style.genre, style.tags].filter(Boolean).join(' ').toLowerCase().includes(query.toLowerCase())), [styles, query]);

  function openEditor(style = null) {
    setEditor(style ? { ...style, style_text: style.style_text || style.content || '' } : { name: '', style_text: '', description: '', genre: '', bpm: '', tags: '' });
  }

  async function save() {
    if (!editor?.name?.trim()) return notify('Name fehlt.', 'error');
    const payload = { ...editor, content: editor.style_text };
    if (editor.id) await api.library.updateStyle(editor.id, payload);
    else await api.library.createStyle(payload);
    setEditor(null);
    notify('Style gespeichert.', 'success');
    onReload();
  }


  async function importStylesFile(event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    try {
      const result = await api.library.importStyles(file);
      notify(`Styles importiert: ${result.imported || 0}, übersprungen: ${result.skipped || 0}.`, result.errors?.length ? 'info' : 'success');
      await onReload();
    } catch (err) {
      notify(err?.message || 'Styles-Import fehlgeschlagen.', 'error');
    }
  }

  async function exportStyles(format = 'csv', mode = 'extended') {
    try {
      const content = await api.library.exportStyles(format, mode);
      const extension = format === 'markdown' || format === 'md' ? 'md' : 'csv';
      const mime = extension === 'md' ? 'text/markdown;charset=utf-8' : 'text/csv;charset=utf-8';
      downloadTextFile(`suno-styles-${mode}.${extension}`, content, mime);
      notify(`Styles-${mode === 'extended' ? 'Detail' : 'Basis'}export wurde erstellt.`, 'success');
    } catch (err) {
      notify(err?.message || 'Styles-Export fehlgeschlagen.', 'error');
    }
  }

  return (
    <section className="page stack">
      <SectionHeader eyebrow="Presets" title="Styles">
        <button type="button" onClick={() => exportStyles('csv', 'simple')}><Download size={15} /> Basis CSV</button>
        <button type="button" onClick={() => exportStyles('markdown', 'extended')}><FileText size={15} /> Details MD</button>
        <label className="button"><Upload size={15} /> Import<input type="file" accept=".csv,.md,.markdown,text/csv,text/markdown,text/plain" hidden onChange={importStylesFile} /></label>
        <button className="primary" onClick={() => openEditor()}>Neuer Style</button>
      </SectionHeader>
      <div className="style-grid">
        {filtered.map((style) => <article className="panel style-card" key={style.id}><div className="row between"><h3>{style.name}</h3><button onClick={() => openEditor(style)}><Edit3 size={15} /> Bearbeiten</button></div><p>{summarizeStyle(style.style_text || style.content || style.description, 420)}</p><div className="button-row"><button onClick={async () => { await copyToClipboard(style.style_text || style.content || ''); notify('Style kopiert.', 'success'); }}><Copy size={15} /> Kopieren</button></div></article>)}
      </div>
      <Modal open={Boolean(editor)} title={editor?.id ? 'Style bearbeiten' : 'Neuer Style'} onClose={() => setEditor(null)} wide>
        {editor && <div className="form-grid"><label>Name<input value={editor.name || ''} onChange={(event) => setEditor({ ...editor, name: event.target.value })} /></label><label>Genre<input value={editor.genre || ''} onChange={(event) => setEditor({ ...editor, genre: event.target.value })} /></label><label>BPM<input value={editor.bpm || ''} onChange={(event) => setEditor({ ...editor, bpm: event.target.value })} /></label><label>Tags<input value={editor.tags || ''} onChange={(event) => setEditor({ ...editor, tags: event.target.value })} /></label><label className="wide">Style<textarea className="large" value={editor.style_text || ''} onChange={(event) => setEditor({ ...editor, style_text: event.target.value })} /></label><button className="primary" onClick={save}><Save size={16} /> Speichern</button></div>}
      </Modal>
    </section>
  );
}
