import React, { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clipboard,
  Edit3,
  LoaderCircle,
  RefreshCcw,
  Search,
  Sparkles,
  Trash2,
  XCircle,
} from 'lucide-react';
import { api } from '../../api/client.js';
import { Modal } from '../Modal.jsx';
import { copyToClipboard, formatDate, formatDuration } from '../../utils.js';
import { useI18n } from '../../i18n/I18nContext.jsx';

const STATUS_OPTIONS = [
  ['all', 'Alle'],
  ['present', 'Mit Suchindex'],
  ['missing', 'Ohne Suchindex'],
  ['running', 'In Bearbeitung'],
  ['failed', 'Fehlgeschlagen'],
];

function splitTerms(value) {
  return String(value || '')
    .split(/[\n,;]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function statusIcon(status) {
  if (status === 'present') return <CheckCircle2 size={15} />;
  if (status === 'running') return <LoaderCircle size={15} className="spin-icon" />;
  if (status === 'failed') return <XCircle size={15} />;
  return <AlertTriangle size={15} />;
}

function tagsPreview(aiTags) {
  const values = [
    ...(Array.isArray(aiTags?.tags) ? aiTags.tags : []),
    ...(Array.isArray(aiTags?.genres) ? aiTags.genres : []),
    ...(Array.isArray(aiTags?.moods) ? aiTags.moods : []),
  ];
  return [...new Set(values.map((item) => String(item || '').trim()).filter(Boolean))];
}

export function LibrarySearchIndexAdmin({ notify, onTasksChanged }) {
  const { t } = useI18n();
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('all');
  const [page, setPage] = useState(1);
  const [pageSize] = useState(50);
  const [data, setData] = useState({ items: [], page: 1, pages: 1, total: 0, summary: {} });
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState('');
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const [editor, setEditor] = useState(null);

  const load = useCallback(async ({ keepSelection = true } = {}) => {
    setLoading(true);
    try {
      const result = await api.admin.librarySearchIndex({ page, pageSize, search: query, status });
      setData(result || { items: [], page: 1, pages: 1, total: 0, summary: {} });
      if (!keepSelection) setSelectedIds(new Set());
    } catch (error) {
      notify(error?.message || t('admin.librarySearchIndex.loadFailed', 'Library-Suchindex konnte nicht geladen werden.'), 'error');
    } finally {
      setLoading(false);
    }
  }, [notify, page, pageSize, query, status, t]);

  useEffect(() => {
    const timer = window.setTimeout(() => load({ keepSelection: true }), 220);
    return () => window.clearTimeout(timer);
  }, [load]);

  const items = Array.isArray(data?.items) ? data.items : [];
  const summary = data?.summary || {};
  const allPageSelected = items.length > 0 && items.every((item) => selectedIds.has(Number(item.audio_asset_id)));

  function toggleSelection(id) {
    const numericId = Number(id);
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(numericId)) next.delete(numericId);
      else next.add(numericId);
      return next;
    });
  }

  function togglePageSelection() {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (allPageSelected) items.forEach((item) => next.delete(Number(item.audio_asset_id)));
      else items.forEach((item) => next.add(Number(item.audio_asset_id)));
      return next;
    });
  }

  function openEditor(item) {
    const value = item?.ai_tags || {};
    setEditor({
      item,
      tags: (value.tags || []).join(', '),
      moods: (value.moods || []).join(', '),
      genres: (value.genres || []).join(', '),
      language: value.language || 'unknown',
      reason: value.reason || '',
    });
  }

  async function saveEditor() {
    if (!editor?.item) return;
    setBusyAction(`save-${editor.item.audio_asset_id}`);
    try {
      await api.admin.updateLibrarySearchIndex(editor.item.audio_asset_id, {
        tags: splitTerms(editor.tags),
        moods: splitTerms(editor.moods),
        genres: splitTerms(editor.genres),
        language: String(editor.language || 'unknown').trim() || 'unknown',
        reason: String(editor.reason || '').trim(),
      });
      notify(t('admin.librarySearchIndex.saved', 'Library-Suchindex wurde gespeichert.'), 'success');
      setEditor(null);
      await load({ keepSelection: true });
    } catch (error) {
      notify(error?.message || t('admin.librarySearchIndex.saveFailed', 'Library-Suchindex konnte nicht gespeichert werden.'), 'error');
    } finally {
      setBusyAction('');
    }
  }

  async function removeIndex(item) {
    if (!item?.audio_asset_id) return;
    const confirmed = window.confirm(
      t(
        'admin.librarySearchIndex.deleteConfirm',
        'Suchindex für „{{title}}“ vollständig entfernen?\n\nAndere Audio-, Song- und Metadaten bleiben unverändert.',
        { title: item.title },
      ),
    );
    if (!confirmed) return;
    setBusyAction(`delete-${item.audio_asset_id}`);
    try {
      await api.admin.deleteLibrarySearchIndex(item.audio_asset_id);
      notify(t('admin.librarySearchIndex.deleted', 'Library-Suchindex wurde entfernt.'), 'success');
      setEditor(null);
      await load({ keepSelection: true });
    } catch (error) {
      notify(error?.message || t('admin.librarySearchIndex.deleteFailed', 'Library-Suchindex konnte nicht entfernt werden.'), 'error');
    } finally {
      setBusyAction('');
    }
  }

  async function generateForIds(ids, { force = false } = {}) {
    const uniqueIds = [...new Set(ids.map(Number).filter((id) => Number.isInteger(id) && id > 0))];
    if (!uniqueIds.length) {
      notify(t('admin.librarySearchIndex.noSelection', 'Keine Audio-Varianten ausgewählt.'), 'error');
      return;
    }
    const message = force
      ? t('admin.librarySearchIndex.regenerateConfirm', 'KI-Tags für {{count}} ausgewählte Variante(n) neu erzeugen?\n\nVorhandene Suchindizes werden nach erfolgreicher Verarbeitung ersetzt.', { count: uniqueIds.length })
      : t('admin.librarySearchIndex.generateConfirm', 'Fehlende KI-Tags für {{count}} ausgewählte Variante(n) erzeugen?\n\nVorhandene Suchindizes und bereits laufende Tasks werden übersprungen.', { count: uniqueIds.length });
    if (!window.confirm(message)) return;

    setBusyAction(force ? 'bulk-regenerate' : 'bulk-generate');
    try {
      const result = await api.archive.bulkGenerateAiTags(uniqueIds, { force });
      const started = Number(result?.count || 0);
      const alreadyRunning = Number(result?.already_running_count || 0);
      if (result?.queued) {
        notify(
          t('admin.librarySearchIndex.batchStarted', '{{count}} Tagging-Aufgabe(n) wurden gestartet.{{running}}', {
            count: started,
            running: alreadyRunning ? ` ${alreadyRunning} bereits laufend.` : '',
          }),
          'success',
        );
      } else {
        notify(result?.message || t('admin.librarySearchIndex.nothingStarted', 'Es wurde kein neuer Tagging-Task gestartet.'), 'info');
      }
      setSelectedIds(new Set());
      await onTasksChanged?.();
      await load({ keepSelection: false });
    } catch (error) {
      notify(error?.message || t('admin.librarySearchIndex.batchFailed', 'Sammelverarbeitung konnte nicht gestartet werden.'), 'error');
    } finally {
      setBusyAction('');
    }
  }

  async function generateSingle(item) {
    const force = item?.tag_status === 'present';
    const confirmed = window.confirm(
      force
        ? t('admin.librarySearchIndex.singleRegenerateConfirm', 'KI-Tags für „{{title}}“ neu erzeugen?', { title: item.title })
        : t('admin.librarySearchIndex.singleGenerateConfirm', 'KI-Tags für „{{title}}“ erzeugen?', { title: item.title }),
    );
    if (!confirmed) return;
    setBusyAction(`generate-${item.audio_asset_id}`);
    try {
      const result = await api.archive.generateAiTags(item.audio_asset_id, { force });
      notify(result?.message || t('admin.librarySearchIndex.started', 'KI-Tagging wurde gestartet.'), result?.queued ? 'success' : 'info');
      await onTasksChanged?.();
      await load({ keepSelection: true });
    } catch (error) {
      notify(error?.message || t('admin.librarySearchIndex.startFailed', 'KI-Tagging konnte nicht gestartet werden.'), 'error');
    } finally {
      setBusyAction('');
    }
  }

  async function copyId(value, label) {
    await copyToClipboard(String(value || ''));
    notify(t('admin.librarySearchIndex.copied', '{{label}} kopiert.', { label }), 'success');
  }

  return (
    <article className="panel stack library-search-index-admin">
      <div className="panel-title-row library-search-index-heading">
        <div>
          <h2>{t('admin.librarySearchIndex.title', 'Library-Suchindex')}</h2>
          <p className="muted">
            {t('admin.librarySearchIndex.description', 'Zentrale Verwaltung der kompakten KI-Suchbegriffe pro Audio-Variante. Verarbeitung startet ausschließlich manuell.')}
          </p>
        </div>
        <button type="button" onClick={() => load({ keepSelection: true })} disabled={loading}>
          <RefreshCcw size={16} className={loading ? 'spin-icon' : ''} /> {t('topbar.refresh', 'Aktualisieren')}
        </button>
      </div>

      <div className="library-search-index-summary" aria-label={t('admin.librarySearchIndex.summary', 'Suchindex-Zusammenfassung')}>
        {[
          ['all', 'Audio-Varianten'],
          ['present', 'Mit Suchindex'],
          ['missing', 'Ohne Suchindex'],
          ['running', 'In Bearbeitung'],
          ['failed', 'Fehlgeschlagen'],
        ].map(([key, label]) => (
          <button key={key} type="button" className={status === key ? 'active' : ''} onClick={() => { setStatus(key); setPage(1); setSelectedIds(new Set()); }}>
            <strong>{Number(summary[key] || 0)}</strong>
            <span>{t(`admin.librarySearchIndex.summary_${key}`, label)}</span>
          </button>
        ))}
      </div>

      <div className="library-search-index-toolbar">
        <label className="library-search-index-search">
          <Search size={16} />
          <input
            value={query}
            onChange={(event) => { setQuery(event.target.value); setPage(1); setSelectedIds(new Set()); }}
            placeholder={t('admin.librarySearchIndex.searchPlaceholder', 'Titel, Audio-ID oder Tag suchen…')}
          />
        </label>
        <select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); setSelectedIds(new Set()); }}>
          {STATUS_OPTIONS.map(([value, label]) => <option key={value} value={value}>{t(`admin.librarySearchIndex.status_${value}`, label)}</option>)}
        </select>
        <button type="button" onClick={togglePageSelection} disabled={!items.length}>
          {allPageSelected ? t('admin.librarySearchIndex.unselectPage', 'Seite abwählen') : t('admin.librarySearchIndex.selectPage', 'Seite auswählen')}
        </button>
      </div>

      <div className="library-search-index-bulkbar">
        <span>{t('admin.librarySearchIndex.selected', '{{count}} ausgewählt', { count: selectedIds.size })}</span>
        <button type="button" onClick={() => generateForIds([...selectedIds], { force: false })} disabled={!selectedIds.size || Boolean(busyAction)}>
          <Sparkles size={15} /> {busyAction === 'bulk-generate' ? t('admin.librarySearchIndex.starting', 'Startet…') : t('admin.librarySearchIndex.generateMissing', 'Fehlende erzeugen')}
        </button>
        <button type="button" onClick={() => generateForIds([...selectedIds], { force: true })} disabled={!selectedIds.size || Boolean(busyAction)}>
          <RefreshCcw size={15} /> {busyAction === 'bulk-regenerate' ? t('admin.librarySearchIndex.starting', 'Startet…') : t('admin.librarySearchIndex.regenerateSelected', 'Ausgewählte neu erzeugen')}
        </button>
      </div>

      <div className="library-search-index-table" aria-busy={loading ? 'true' : 'false'}>
        <div className="library-search-index-row header-row">
          <span />
          <span>{t('admin.librarySearchIndex.columnAudio', 'Audio-Variante')}</span>
          <span>{t('admin.librarySearchIndex.columnStatus', 'Status')}</span>
          <span>{t('admin.librarySearchIndex.columnTerms', 'Suchbegriffe')}</span>
          <span>{t('admin.librarySearchIndex.columnMeta', 'Erzeugung')}</span>
          <span>{t('admin.librarySearchIndex.columnActions', 'Aktionen')}</span>
        </div>

        {items.map((item) => {
          const aiTags = item.ai_tags || {};
          const preview = tagsPreview(aiTags);
          const rowBusy = busyAction.endsWith(`-${item.audio_asset_id}`);
          return (
            <div className="library-search-index-row" key={item.audio_asset_id}>
              <label className="library-search-index-check">
                <input type="checkbox" checked={selectedIds.has(Number(item.audio_asset_id))} onChange={() => toggleSelection(item.audio_asset_id)} />
              </label>
              <div className="library-search-index-asset">
                <strong>{item.title}</strong>
                <small className="muted">
                  {item.version_label || t('admin.librarySearchIndex.noVersion', 'ohne Versionslabel')}
                  {item.duration_seconds ? ` · ${formatDuration(item.duration_seconds)}` : ''}
                  {item.audio_local ? ` · ${t('library.badges.local', 'LOCAL')}` : ''}
                </small>
                <div className="library-search-index-identifiers">
                  <button type="button" onClick={() => copyId(item.audio_asset_id, 'AudioAsset-ID')} title={t('admin.librarySearchIndex.copyAssetId', 'AudioAsset-ID kopieren')}>
                    <Clipboard size={13} /> #{item.audio_asset_id}
                  </button>
                  {item.audio_id && (
                    <button type="button" onClick={() => copyId(item.audio_id, 'Audio-ID')} title={t('admin.librarySearchIndex.copyAudioId', 'Audio-ID kopieren')}>
                      <Clipboard size={13} /> {String(item.audio_id).slice(0, 12)}…
                    </button>
                  )}
                </div>
              </div>
              <div>
                <span className={`library-search-index-status ${item.tag_status}`}>{statusIcon(item.tag_status)} {t(`admin.librarySearchIndex.status_${item.tag_status}`, item.tag_status === 'present' ? 'Vorhanden' : item.tag_status === 'running' ? 'Läuft' : item.tag_status === 'failed' ? 'Fehler' : 'Fehlt')}</span>
                {item.latest_task?.error_message && <small className="error-text" title={item.latest_task.error_message}>{item.latest_task.error_message}</small>}
              </div>
              <div className="library-search-index-tags">
                {preview.length ? preview.slice(0, 8).map((tag) => <span key={tag}>{tag}</span>) : <span className="muted empty-tag">–</span>}
                {preview.length > 8 && <small className="muted">+{preview.length - 8}</small>}
              </div>
              <div className="library-search-index-meta">
                <span>{aiTags.language && aiTags.language !== 'unknown' ? aiTags.language.toUpperCase() : '–'}</span>
                <small className="muted">{aiTags.model || aiTags.provider || '–'}</small>
                <small className="muted">{aiTags.updated_at || aiTags.generated_at ? formatDate(aiTags.updated_at || aiTags.generated_at) : '–'}</small>
              </div>
              <div className="library-search-index-actions">
                <button type="button" onClick={() => openEditor(item)} disabled={rowBusy}><Edit3 size={14} /> {t('common.edit', 'Bearbeiten')}</button>
                <button type="button" onClick={() => generateSingle(item)} disabled={rowBusy || item.tag_status === 'running'}>
                  {rowBusy ? <LoaderCircle size={14} className="spin-icon" /> : <Sparkles size={14} />}
                  {item.tag_status === 'present' ? t('admin.librarySearchIndex.regenerate', 'Neu erzeugen') : t('admin.librarySearchIndex.generate', 'Erzeugen')}
                </button>
              </div>
            </div>
          );
        })}

        {!loading && !items.length && (
          <div className="library-search-index-empty">
            <Search size={22} />
            <strong>{t('admin.librarySearchIndex.empty', 'Keine passenden Audio-Varianten gefunden.')}</strong>
          </div>
        )}
      </div>

      <div className="library-search-index-pagination">
        <span>{t('admin.librarySearchIndex.pageInfo', 'Seite {{page}} von {{pages}} · {{total}} Treffer', { page: data.page || 1, pages: data.pages || 1, total: data.total || 0 })}</span>
        <div className="inline-actions">
          <button type="button" onClick={() => { setPage((value) => Math.max(1, value - 1)); setSelectedIds(new Set()); }} disabled={(data.page || 1) <= 1 || loading}><ChevronLeft size={16} /> {t('common.previous', 'Zurück')}</button>
          <button type="button" onClick={() => { setPage((value) => Math.min(data.pages || 1, value + 1)); setSelectedIds(new Set()); }} disabled={(data.page || 1) >= (data.pages || 1) || loading}>{t('common.next', 'Weiter')} <ChevronRight size={16} /></button>
        </div>
      </div>

      <Modal
        open={Boolean(editor)}
        title={editor ? t('admin.librarySearchIndex.editTitle', 'Suchindex bearbeiten: {{title}}', { title: editor.item.title }) : ''}
        onClose={() => !busyAction && setEditor(null)}
        wide
        cardClassName="library-search-index-editor-modal"
      >
        {editor && (
          <div className="stack">
            <p className="muted">{t('admin.librarySearchIndex.editHint', 'Werte mit Komma oder Zeilenumbruch trennen. Gespeichert wird ausschließlich das ai_tags-Unterobjekt der Audio-Variante.')}</p>
            <div className="form-grid compact-grid library-search-index-editor-grid">
              <label className="wide">{t('admin.librarySearchIndex.tags', 'Such-Tags')}
                <textarea rows={4} value={editor.tags} onChange={(event) => setEditor({ ...editor, tags: event.target.value })} placeholder="boom bap, deutschrap, dark" />
              </label>
              <label>{t('admin.librarySearchIndex.genres', 'Genres')}
                <textarea rows={3} value={editor.genres} onChange={(event) => setEditor({ ...editor, genres: event.target.value })} />
              </label>
              <label>{t('admin.librarySearchIndex.moods', 'Stimmungen')}
                <textarea rows={3} value={editor.moods} onChange={(event) => setEditor({ ...editor, moods: event.target.value })} />
              </label>
              <label>{t('admin.librarySearchIndex.language', 'Sprache')}
                <input value={editor.language} onChange={(event) => setEditor({ ...editor, language: event.target.value })} maxLength={16} />
              </label>
              <label className="wide">{t('admin.librarySearchIndex.reason', 'Notiz / Begründung')}
                <textarea rows={3} value={editor.reason} onChange={(event) => setEditor({ ...editor, reason: event.target.value })} maxLength={240} />
              </label>
            </div>
            <div className="modal-actions library-search-index-editor-actions">
              <button type="button" className="danger" onClick={() => removeIndex(editor.item)} disabled={Boolean(busyAction)}><Trash2 size={15} /> {t('admin.librarySearchIndex.remove', 'Suchindex entfernen')}</button>
              <span className="spacer" />
              <button type="button" onClick={() => setEditor(null)} disabled={Boolean(busyAction)}>{t('common.cancel', 'Abbrechen')}</button>
              <button type="button" className="primary" onClick={saveEditor} disabled={Boolean(busyAction)}>
                {busyAction.startsWith('save-') ? <LoaderCircle size={15} className="spin-icon" /> : <Edit3 size={15} />} {t('common.save', 'Speichern')}
              </button>
            </div>
          </div>
        )}
      </Modal>
    </article>
  );
}
