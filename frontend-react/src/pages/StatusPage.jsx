import React, { useMemo, useState } from 'react';
import { Bell, Check, Eye, ImageDown, RefreshCw, ShieldCheck, Square, Trash2 } from 'lucide-react';
import { api } from '../api/client.js';
import { EmptyState } from '../components/EmptyState.jsx';
import { formatDate, friendlyNotification, safeArray, shortId } from '../utils.js';

const ACTIVE_STATUSES = new Set(['PENDING', 'PROCESSING', 'RUNNING', 'QUEUED', 'SUBMITTED', 'CREATED', 'TEXT_SUCCESS', 'FIRST_SUCCESS', 'submitted', 'processing']);
const NOTIFICATION_PAGE_SIZE = 25;
const TASK_PAGE_SIZE = 30;

function PaginationControls({ page, totalItems, pageSize, onPageChange, label = 'Einträge' }) {
  const totalPages = Math.max(1, Math.ceil(Number(totalItems || 0) / pageSize));
  const safePage = Math.min(Math.max(Number(page || 1), 1), totalPages);
  if (!totalItems || totalItems <= pageSize) return null;
  const first = (safePage - 1) * pageSize + 1;
  const last = Math.min(safePage * pageSize, totalItems);
  return (
    <div className="pagination-controls">
      <span>{first}-{last} von {totalItems} {label}</span>
      <div className="pagination-buttons">
        <button type="button" onClick={() => onPageChange(1)} disabled={safePage <= 1}>Erste</button>
        <button type="button" onClick={() => onPageChange(safePage - 1)} disabled={safePage <= 1}>Zurück</button>
        <strong>Seite {safePage}/{totalPages}</strong>
        <button type="button" onClick={() => onPageChange(safePage + 1)} disabled={safePage >= totalPages}>Weiter</button>
        <button type="button" onClick={() => onPageChange(totalPages)} disabled={safePage >= totalPages}>Letzte</button>
      </div>
    </div>
  );
}

function isActiveTask(task) {
  const status = String(task?.status || '').trim();
  return ACTIVE_STATUSES.has(status) || ACTIVE_STATUSES.has(status.toUpperCase());
}

function taskClass(task) {
  const status = String(task?.status || '').toLowerCase();
  if (isActiveTask(task)) return 'active';
  if (status.includes('success') || status.includes('done') || status.includes('complete')) return 'success';
  if (status.includes('fail') || status.includes('error')) return 'failed';
  return '';
}

export function StatusPage({ notifications = [], tasks = [], onReload, onCheckStatus, taskRefreshState, onOpenNotification, onOpenTaskDetails, notify }) {
  const [selected, setSelected] = useState(() => new Set());
  const [filter, setFilter] = useState('all');
  const [importingTask, setImportingTask] = useState(false);
  const [cachingCovers, setCachingCovers] = useState(false);
  const [importPayload, setImportPayload] = useState({ task_id: '', task_type: 'generate_music', title: '', prompt: '', style: '', model: '', cache_audio: true, generate_srt: false, generate_stems: false });
  const [batchImporting, setBatchImporting] = useState(false);
  const [batchImportPayload, setBatchImportPayload] = useState({ task_ids: '', task_type: 'generate_music', cache_audio: true, title_prefix: '', generate_srt: false, generate_stems: false });
  const [songImporting, setSongImporting] = useState(false);
  const [songImportPayload, setSongImportPayload] = useState({ song_id: '', cache_audio: true, cache_cover: true, import_video_url: true, overwrite_existing: false, generate_srt: false, generate_stems: false });
  const [songBatchImporting, setSongBatchImporting] = useState(false);
  const [songBatchImportPayload, setSongBatchImportPayload] = useState({ song_ids: '', cache_audio: true, cache_cover: true, import_video_url: true, overwrite_existing: false, generate_srt: false, generate_stems: false });
  const [notificationPage, setNotificationPage] = useState(1);
  const [taskPage, setTaskPage] = useState(1);
  const [highlightTaskId, setHighlightTaskId] = useState(null);

  const rows = useMemo(() => {
    return safeArray(notifications, ['notifications', 'items']).filter((item) => {
      if (filter === 'unread') return item.status !== 'done';
      if (filter === 'done') return item.status === 'done';
      return true;
    });
  }, [notifications, filter]);

  const notificationTotalPages = Math.max(1, Math.ceil(rows.length / NOTIFICATION_PAGE_SIZE));
  const safeNotificationPage = Math.min(Math.max(notificationPage, 1), notificationTotalPages);
  const paginatedRows = useMemo(() => {
    const start = (safeNotificationPage - 1) * NOTIFICATION_PAGE_SIZE;
    return rows.slice(start, start + NOTIFICATION_PAGE_SIZE);
  }, [rows, safeNotificationPage]);

  const normalizedTasks = useMemo(() => safeArray(tasks, ['tasks', 'items']), [tasks]);
  const taskTotalPages = Math.max(1, Math.ceil(normalizedTasks.length / TASK_PAGE_SIZE));
  const safeTaskPage = Math.min(Math.max(taskPage, 1), taskTotalPages);
  const paginatedTasks = useMemo(() => {
    const start = (safeTaskPage - 1) * TASK_PAGE_SIZE;
    return normalizedTasks.slice(start, start + TASK_PAGE_SIZE);
  }, [normalizedTasks, safeTaskPage]);
  const openTaskCount = useMemo(() => normalizedTasks.filter(isActiveTask).length, [normalizedTasks]);
  const taskStats = useMemo(() => {
    const stats = { active: 0, success: 0, failed: 0, other: 0 };
    normalizedTasks.forEach((task) => {
      const status = String(task?.status || '').toLowerCase();
      if (isActiveTask(task)) stats.active += 1;
      else if (status.includes('success') || status.includes('done') || status.includes('complete')) stats.success += 1;
      else if (status.includes('fail') || status.includes('error')) stats.failed += 1;
      else stats.other += 1;
    });
    return stats;
  }, [normalizedTasks]);
  const liveTasks = useMemo(() => normalizedTasks.filter(isActiveTask).slice(0, 6), [normalizedTasks]);

  const productionGroups = useMemo(() => {
    const groups = new Map();
    normalizedTasks.forEach((task) => {
      const key = task.task_type || 'unknown';
      const status = String(task.status || '').toLowerCase();
      if (!groups.has(key)) groups.set(key, { key, total: 0, active: 0, success: 0, failed: 0, latest: null });
      const group = groups.get(key);
      group.total += 1;
      if (isActiveTask(task)) group.active += 1;
      else if (status.includes('success') || status.includes('done') || status.includes('complete')) group.success += 1;
      else if (status.includes('fail') || status.includes('error')) group.failed += 1;
      if (!group.latest || String(task.updated_at || task.created_at || '') > String(group.latest.updated_at || group.latest.created_at || '')) group.latest = task;
    });
    return [...groups.values()].sort((a, b) => b.active - a.active || b.failed - a.failed || b.total - a.total).slice(0, 12);
  }, [normalizedTasks]);

  const backupStats = useMemo(() => {
    const totals = { audioLocal: 0, audioRemote: 0, coverLocal: 0, coverRemote: 0, payloads: 0 };
    normalizedTasks.forEach((task) => {
      if (task.request_payload || task.response_payload || task.result_payload) totals.payloads += 1;
    });
    return totals;
  }, [normalizedTasks]);


  function toggle(id) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  async function markDone(ids) {
    const payload = ids || [...selected];
    if (!payload.length) return;
    await api.notifications.bulkDone(payload);
    setSelected(new Set());
    notify('Benachrichtigungen als erledigt markiert.', 'success');
    await onReload();
  }

  async function remove(ids) {
    const payload = ids || [...selected];
    if (!payload.length) return;
    if (!confirm(`${payload.length} Benachrichtigung(en) endgültig ausblenden?`)) return;
    await api.notifications.bulkDelete(payload);
    setSelected(new Set());
    notify('Benachrichtigungen gelöscht.', 'success');
    await onReload();
  }

  async function refreshSingleTask(task) {
    if (!task?.id) return;
    try {
      await api.music.refreshTask(task.id);
      notify('Task wurde geprüft.', 'success');
      await onReload();
    } catch (err) {
      notify(err?.message || 'Task konnte nicht geprüft werden.', 'error');
    }
  }

  async function markTaskDone(task) {
    if (!task?.id) return;
    try {
      await api.music.markTaskDone(task.id);
      notify('Task wurde manuell als erledigt markiert.', 'success');
      await onReload();
    } catch (err) {
      notify(err?.message || 'Task konnte nicht als erledigt markiert werden.', 'error');
    }
  }

  async function cancelTask(task) {
    if (!task?.id) return;
    if (!confirm(`Lokalen Task „${task.task_type || task.id}“ abbrechen?`)) return;
    try {
      await api.music.cancelTask(task.id);
      notify('Abbruch wurde angefordert.', 'warning');
      await onReload();
    } catch (err) {
      notify(err?.message || 'Task konnte nicht abgebrochen werden.', 'error');
    }
  }

  async function deleteTask(task) {
    if (!task?.id) return;
    if (!confirm(`Task „${task.task_type || task.id}“ wirklich löschen/ausblenden?`)) return;
    try {
      await api.music.deleteTask(task.id);
      notify('Task wurde gelöscht.', 'success');
      await onReload();
    } catch (err) {
      notify(err?.message || 'Task konnte nicht gelöscht werden.', 'error');
    }
  }

  function findTaskForStatusNotification(notification) {
    const payload = notification?.target_payload || {};
    const localId = payload.task_local_id || notification?.task_local_id;
    const sunoTaskId = payload.suno_task_id || notification?.suno_task_id;
    return normalizedTasks.find((task) => {
      if (localId && String(task.id) === String(localId)) return true;
      if (sunoTaskId && task.task_id && String(task.task_id) === String(sunoTaskId)) return true;
      return false;
    }) || null;
  }

  function jumpToTaskStatus(task, notification = null) {
    if (!task?.id) {
      if (notification) onOpenNotification?.(notification);
      return;
    }
    const index = normalizedTasks.findIndex((item) => String(item.id) === String(task.id));
    if (index >= 0) {
      const nextPage = Math.floor(index / TASK_PAGE_SIZE) + 1;
      setTaskPage(nextPage);
    }
    setHighlightTaskId(task.id);
    window.setTimeout(() => {
      const element = document.querySelector(`[data-task-row-id="${task.id}"]`);
      element?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 80);
    window.setTimeout(() => setHighlightTaskId((current) => String(current) === String(task.id) ? null : current), 2600);
  }

  function openNotificationStatusTarget(notification) {
    const task = findTaskForStatusNotification(notification);
    if (task) {
      const index = normalizedTasks.findIndex((item) => String(item.id) === String(task.id));
      if (index >= 0) {
        setTaskPage(Math.floor(index / TASK_PAGE_SIZE) + 1);
      }
      setHighlightTaskId(task.id);
      window.setTimeout(() => setHighlightTaskId((current) => String(current) === String(task.id) ? null : current), 2500);
    }
    // Immer die Notification öffnen: App.jsx lädt darüber bei Bedarf den Task nach
    // und zeigt das StatusDetailModal inklusive Meldung + Taskdetails.
    onOpenNotification?.(notification);
  }


  function updateBatchImportPayload(key, value) {
    setBatchImportPayload((current) => ({ ...current, [key]: value }));
  }

  async function importExternalTasksBatch(event) {
    event.preventDefault();
    if (!batchImportPayload.task_ids.trim()) return notify('Bitte mindestens eine Task-ID eintragen.', 'error');
    setBatchImporting(true);
    try {
      const result = await api.music.importBatchFromSuno(batchImportPayload);
      const summary = result?.summary || {};
      if (result?.queued) {
        notify(result?.message || `SunoAPI.org Task-Batchimport wurde gestartet (${summary.total || 0} Einträge).`, 'info');
        setBatchImportPayload((current) => ({ ...current, task_ids: '', title_prefix: '' }));
        await onReload();
        window.setTimeout(() => onReload?.(), 1500);
        return;
      }
      notify(result?.message || `${summary.imported || 0} importiert, ${summary.already_imported || 0} bereits vorhanden, ${summary.failed || 0} Fehler.`, summary.failed ? 'info' : 'success');
      if (!summary.failed) setBatchImportPayload((current) => ({ ...current, task_ids: '', title_prefix: '' }));
      await onReload();
    } catch (err) {
      notify(err?.message || 'Batch-Import fehlgeschlagen.', 'error');
    } finally {
      setBatchImporting(false);
    }
  }

  function updateImportPayload(key, value) {
    setImportPayload((current) => ({ ...current, [key]: value }));
  }

  function updateSongImportPayload(key, value) {
    setSongImportPayload((current) => ({ ...current, [key]: value }));
  }

  function updateSongBatchImportPayload(key, value) {
    setSongBatchImportPayload((current) => ({ ...current, [key]: value }));
  }


  async function cacheMissingCovers() {
    setCachingCovers(true);
    try {
      const result = await api.archive.cacheMissingCovers();
      notify(result?.message || 'Cover wurden lokal gesichert.', 'success');
      await onReload();
    } catch (err) {
      notify(err?.message || 'Cover konnten nicht lokal gesichert werden.', 'error');
    } finally {
      setCachingCovers(false);
    }
  }

  async function importExternalTask(event) {
    event.preventDefault();
    const taskId = importPayload.task_id.trim();
    if (!taskId) {
      notify('Bitte eine Suno Task-ID eintragen.', 'error');
      return;
    }

    setImportingTask(true);
    try {
      const payload = {
        task_id: taskId,
        task_type: importPayload.task_type || 'generate_music',
        title: importPayload.title.trim() || undefined,
        prompt: importPayload.prompt.trim() || undefined,
        style: importPayload.style.trim() || undefined,
        model: importPayload.model.trim() || undefined,
        cache_audio: Boolean(importPayload.cache_audio),
        generate_srt: Boolean(importPayload.generate_srt),
        generate_stems: Boolean(importPayload.generate_stems)
      };
      const result = await api.music.importFromSuno(payload);
      if (result?.already_imported || result?.import_status === 'already_imported') {
        notify(result?.import_message || 'Dieser Suno-Task wurde bereits importiert. Es wurde nichts doppelt erstellt.', 'info');
      } else {
        notify(result?.import_message || `Suno-Task importiert: ${result?.status || 'OK'}`, 'success');
        setImportPayload((current) => ({ ...current, task_id: '', title: '', prompt: '', style: '', model: '' }));
      }
      await onReload();
    } catch (err) {
      notify(err?.message || 'Suno-Task konnte nicht importiert werden.', 'error');
    } finally {
      setImportingTask(false);
    }
  }

  async function importPublicSunoSong(event) {
    event.preventDefault();
    const songId = songImportPayload.song_id.trim();
    if (!songId) {
      notify('Bitte eine Suno Song-ID oder Suno-URL eintragen.', 'error');
      return;
    }

    setSongImporting(true);
    try {
      const payload = {
        song_id: songId,
        cache_audio: Boolean(songImportPayload.cache_audio),
        cache_cover: Boolean(songImportPayload.cache_cover),
        import_video_url: Boolean(songImportPayload.import_video_url),
        overwrite_existing: Boolean(songImportPayload.overwrite_existing),
        generate_srt: Boolean(songImportPayload.generate_srt),
        generate_stems: Boolean(songImportPayload.generate_stems)
      };
      const result = await api.music.importSongFromSuno(payload);
      const message = result?.message || (result?.already_imported ? 'Suno-Song wurde bereits importiert.' : 'Suno-Song wurde importiert.');
      notify(message, result?.already_imported ? 'info' : 'success');
      if (!result?.already_imported || songImportPayload.overwrite_existing) {
        setSongImportPayload((current) => ({ ...current, song_id: '', overwrite_existing: false }));
      }
      await onReload();
    } catch (err) {
      notify(err?.message || 'Suno-Song konnte nicht importiert werden.', 'error');
    } finally {
      setSongImporting(false);
    }
  }


  async function importPublicSunoSongsBatch(event) {
    event.preventDefault();
    if (!songBatchImportPayload.song_ids.trim()) {
      notify('Bitte mindestens eine Suno Song-ID oder URL eintragen.', 'error');
      return;
    }
    setSongBatchImporting(true);
    try {
      const result = await api.music.importSongBatchFromSuno(songBatchImportPayload);
      const summary = result?.summary || {};
      if (result?.queued) {
        notify(result?.message || `Suno.com Song-Batchimport wurde gestartet (${summary.total || 0} Einträge).`, 'info');
        setSongBatchImportPayload((current) => ({ ...current, song_ids: '', overwrite_existing: false }));
        await onReload();
        window.setTimeout(() => onReload?.(), 1500);
        return;
      }
      notify(result?.message || `${summary.imported || 0} importiert, ${summary.already_imported || 0} bereits vorhanden, ${summary.failed || 0} Fehler.`, summary.failed ? 'info' : 'success');
      if (!summary.failed) {
        setSongBatchImportPayload((current) => ({ ...current, song_ids: '', overwrite_existing: false }));
      }
      await onReload();
    } catch (err) {
      notify(err?.message || 'Suno-Song-Batch konnte nicht importiert werden.', 'error');
    } finally {
      setSongBatchImporting(false);
    }
  }

  return (
    <section className="page stack">
      <header className="page-header">
        <div><p className="eyebrow">Status</p><h1>Benachrichtigungen & Tasks</h1><p className="muted">Fertige Tasks erneut öffnen, erledigen oder endgültig ausblenden.</p></div>
        <div className="header-inline-actions">
          <button onClick={onCheckStatus} disabled={taskRefreshState?.running}><RefreshCw size={16} className={taskRefreshState?.running ? 'spin-icon' : ''} /> Status prüfen</button>
          <button onClick={onReload}><RefreshCw size={16} /> Aktualisieren</button>
        </div>
      </header>

      <section className="panel task-status-panel live-status-panel">
        <div>
          <p className="eyebrow">Live Status</p>
          <h2>{openTaskCount ? `${openTaskCount} offene Task(s)` : 'Keine offenen Tasks'}</h2>
          <p className="muted">
            <span className={`live-dot inline ${openTaskCount || taskRefreshState?.running ? 'is-live' : ''}`} />
            {openTaskCount || taskRefreshState?.running ? 'Automatische Prüfung läuft im Hintergrund.' : 'Bereit. Es sind aktuell keine aktiven Suno-Tasks offen.'}
            {' '}Letzte Prüfung: {taskRefreshState?.lastCheck ? formatDate(taskRefreshState.lastCheck) : 'noch keine'}
            {taskRefreshState?.lastMessage ? ` · ${taskRefreshState.lastMessage}` : ''}
            {taskRefreshState?.lastError ? ` · Fehler: ${taskRefreshState.lastError}` : ''}
          </p>
          <div className="live-status-grid">
            <span><strong>{taskStats.active}</strong><small>aktiv</small></span>
            <span><strong>{taskStats.success}</strong><small>fertig</small></span>
            <span><strong>{taskStats.failed}</strong><small>Fehler</small></span>
            <span><strong>{taskStats.other}</strong><small>sonstige</small></span>
          </div>
          {liveTasks.length > 0 && (
            <div className="live-task-strip">
              {liveTasks.map((task) => (
                <button type="button" key={task.id || task.task_id} onClick={() => onOpenTaskDetails?.(task)}>
                  <RefreshCw size={13} className={taskRefreshState?.running ? 'spin-icon' : ''} />
                  {task.task_type || 'Task'} · {task.status || 'offen'}
                </button>
              ))}
            </div>
          )}
        </div>
        <button type="button" className="primary" onClick={onCheckStatus} disabled={taskRefreshState?.running}>
          <RefreshCw size={16} className={taskRefreshState?.running ? 'spin-icon' : ''} />
          {taskRefreshState?.running ? 'Prüfe…' : 'Jetzt prüfen'}
        </button>
      </section>

      <section className="panel stack production-monitor-panel">
        <div className="row between align-start">
          <div>
            <p className="eyebrow">Produktionsmonitor</p>
            <h2>Alle Workflows auf einen Blick</h2>
            <p className="muted">Musik, Cover, Voice, MIDI, WAV, Stem Separation, Video, Imports und Backfills in einer Übersicht.</p>
          </div>
          <span className="status cached"><ShieldCheck size={14} /> Payloads gesichert: {backupStats.payloads}</span>
        </div>
        {!productionGroups.length ? <p className="muted">Noch keine Workflow-Daten vorhanden.</p> : <div className="production-monitor-grid">
          {productionGroups.map((group) => (
            <button type="button" className={`production-monitor-card ${group.failed ? 'failed' : group.active ? 'active' : ''}`} key={group.key} onClick={() => group.latest && onOpenTaskDetails?.(group.latest)}>
              <strong>{group.key}</strong>
              <span>{group.total} gesamt</span>
              <small>{group.active} aktiv · {group.success} fertig · {group.failed} Fehler</small>
            </button>
          ))}
        </div>}
      </section>

      <section className="panel stack slim-panel">
        <div>
          <p className="eyebrow">Backfill / Import</p>
          <h2>Externen SunoAPI.org-Task importieren</h2>
          <p className="muted">SunoAPI.org-Task-ID eintragen, über die offizielle Task-/Record-Info laden und lokal als Task, Song und AudioAsset ablegen.</p>
        </div>
        <div className="button-row wrap">
          <button type="button" onClick={cacheMissingCovers} disabled={cachingCovers}>
            <ImageDown size={16} className={cachingCovers ? 'spin-icon' : ''} />
            {cachingCovers ? 'Sichere Cover…' : 'Fehlende Cover lokal sichern'}
          </button>
        </div>
        <form className="form-grid" onSubmit={importExternalTask}>
          <label>Task-ID
            <input value={importPayload.task_id} onChange={(event) => updateImportPayload('task_id', event.target.value)} placeholder="z. B. b762e25da0e27d420535ae1068504ecd" />
          </label>
          <label>Task-Typ
            <select value={importPayload.task_type} onChange={(event) => updateImportPayload('task_type', event.target.value)}>
              <option value="generate_music">Generate Music</option>
              <option value="extend_music">Extend Music</option>
              <option value="upload_and_cover">Upload And Cover</option>
              <option value="upload_and_extend">Upload And Extend</option>
              <option value="add_vocals">Add Vocals</option>
              <option value="add_instrumental">Add Instrumental</option>
              <option value="generate_mashup">Generate Mashup</option>
              <option value="generate_sounds">Generate Sounds</option>
              <option value="create_cover">Generate Music Cover</option>
              <option value="generate_lyrics">Generate Lyrics</option>
              <option value="separate">Stem Separation</option>
              <option value="convert_to_wav">Convert to WAV</option>
              <option value="generate_midi">Generate MIDI</option>
              <option value="create_video">Create Music Video</option>
              <option value="create_custom_voice">Custom Voice</option>
            </select>
          </label>
          <label>Titel optional
            <input value={importPayload.title} onChange={(event) => updateImportPayload('title', event.target.value)} placeholder="Lokaler Anzeigename" />
          </label>
          <label>Modell optional
            <input value={importPayload.model} onChange={(event) => updateImportPayload('model', event.target.value)} placeholder="z. B. V5_5" />
          </label>
          <label>Prompt / Lyrics optional
            <textarea rows={3} value={importPayload.prompt} onChange={(event) => updateImportPayload('prompt', event.target.value)} placeholder="Nur falls lokal ergänzt werden soll…" />
          </label>
          <label>Style optional
            <textarea rows={3} value={importPayload.style} onChange={(event) => updateImportPayload('style', event.target.value)} placeholder="Style lokal ergänzen…" />
          </label>
          <label className="check-row">
            <input type="checkbox" checked={importPayload.cache_audio} onChange={(event) => updateImportPayload('cache_audio', event.target.checked)} />
            Audio lokal cachen, falls URL verfügbar
          </label>
          <label className="check-row">
            <input type="checkbox" checked={importPayload.generate_srt} onChange={(event) => updateImportPayload('generate_srt', event.target.checked)} />
            Nach Import SRT erzeugen
          </label>
          <label className="check-row">
            <input type="checkbox" checked={importPayload.generate_stems} onChange={(event) => updateImportPayload('generate_stems', event.target.checked)} />
            Nach Import Stems erzeugen
          </label>
          <div className="form-actions">
            <button className="primary" type="submit" disabled={importingTask}>
              <RefreshCw size={16} className={importingTask ? 'spin-icon' : ''} />
              {importingTask ? 'Importiere…' : 'Task importieren'}
            </button>
          </div>
        </form>

        <details className="batch-import-box">
          <summary>Mehrere SunoAPI.org Task-IDs als Batch importieren</summary>
          <form className="form-grid" onSubmit={importExternalTasksBatch}>
            <label className="wide">Task-IDs, eine pro Zeile
              <textarea rows={5} value={batchImportPayload.task_ids} onChange={(event) => updateBatchImportPayload('task_ids', event.target.value)} placeholder="Task-ID 1
Task-ID 2
Task-ID 3" />
            </label>
            <label>Task-Typ
              <select value={batchImportPayload.task_type} onChange={(event) => updateBatchImportPayload('task_type', event.target.value)}>
                <option value="generate_music">Generate Music</option>
                <option value="extend_music">Extend Music</option>
                <option value="upload_and_cover">Upload And Cover</option>
                <option value="upload_and_extend">Upload And Extend</option>
                <option value="add_vocals">Add Vocals</option>
                <option value="add_instrumental">Add Instrumental</option>
                <option value="generate_mashup">Generate Mashup</option>
                <option value="generate_sounds">Generate Sounds</option>
                <option value="create_cover">Generate Music Cover</option>
                <option value="generate_lyrics">Generate Lyrics</option>
                <option value="separate">Stem Separation</option>
                <option value="convert_to_wav">Convert to WAV</option>
                <option value="generate_midi">Generate MIDI</option>
                <option value="create_video">Create Music Video</option>
                <option value="create_custom_voice">Custom Voice</option>
              </select>
            </label>
            <label>Titel-Präfix optional
              <input value={batchImportPayload.title_prefix} onChange={(event) => updateBatchImportPayload('title_prefix', event.target.value)} placeholder="z. B. Backfill" />
            </label>
            <label className="check-row"><input type="checkbox" checked={batchImportPayload.cache_audio} onChange={(event) => updateBatchImportPayload('cache_audio', event.target.checked)} /> Audio lokal cachen</label>
            <label className="check-row"><input type="checkbox" checked={batchImportPayload.generate_srt} onChange={(event) => updateBatchImportPayload('generate_srt', event.target.checked)} /> Nach Import SRT erzeugen</label>
            <label className="check-row"><input type="checkbox" checked={batchImportPayload.generate_stems} onChange={(event) => updateBatchImportPayload('generate_stems', event.target.checked)} /> Nach Import Stems erzeugen</label>
            <div className="form-actions"><button className="primary" type="submit" disabled={batchImporting}><RefreshCw size={16} className={batchImporting ? 'spin-icon' : ''} /> {batchImporting ? 'Importiere…' : 'Batch importieren'}</button></div>
          </form>
        </details>

        <div className="status-import-divider" />
        <div>
          <p className="eyebrow">Öffentlicher Suno.com Song-Import</p>
          <h3>Öffentliche Suno.com Song-ID / URL importieren</h3>
          <p className="muted">Öffentliche Suno-Song-URL oder Clip-ID importieren. Lokale Funktionen wie Playback, Download, Lyrics und SRT bleiben aktiv; SunoAPI.org-Folgeaktionen werden für diese Imports deaktiviert.</p>
        </div>
        <form className="form-grid status-song-import-grid" onSubmit={importPublicSunoSong}>
          <label className="wide">Suno Song-ID oder URL
            <input value={songImportPayload.song_id} onChange={(event) => updateSongImportPayload('song_id', event.target.value)} placeholder="z. B. https://suno.com/song/96fdbd12-4ea1-41b4-a132-4b731ec6594e" />
          </label>
          <label className="check-row">
            <input type="checkbox" checked={songImportPayload.cache_audio} onChange={(event) => updateSongImportPayload('cache_audio', event.target.checked)} />
            Audio lokal speichern
          </label>
          <label className="check-row">
            <input type="checkbox" checked={songImportPayload.cache_cover} onChange={(event) => updateSongImportPayload('cache_cover', event.target.checked)} />
            Cover lokal speichern
          </label>
          <label className="check-row">
            <input type="checkbox" checked={songImportPayload.import_video_url} onChange={(event) => updateSongImportPayload('import_video_url', event.target.checked)} />
            Video-URL übernehmen
          </label>
          <label className="check-row">
            <input type="checkbox" checked={songImportPayload.overwrite_existing} onChange={(event) => updateSongImportPayload('overwrite_existing', event.target.checked)} />
            Vorhandenen Import aktualisieren
          </label>
          <label className="check-row">
            <input type="checkbox" checked={songImportPayload.generate_srt} onChange={(event) => updateSongImportPayload('generate_srt', event.target.checked)} />
            Nach Import SRT erzeugen
          </label>
          <label className="check-row">
            <input type="checkbox" checked={songImportPayload.generate_stems} onChange={(event) => updateSongImportPayload('generate_stems', event.target.checked)} />
            Nach Import Stems erzeugen
          </label>
          <div className="form-actions">
            <button className="primary" type="submit" disabled={songImporting}>
              <RefreshCw size={16} className={songImporting ? 'spin-icon' : ''} />
              {songImporting ? 'Importiere…' : 'Song importieren'}
            </button>
          </div>
        </form>

        <details className="batch-import-box">
          <summary>Mehrere öffentliche Suno.com Song-IDs / URLs als Batch importieren</summary>
          <form className="form-grid" onSubmit={importPublicSunoSongsBatch}>
            <label className="wide">Suno Song-IDs oder URLs, eine pro Zeile
              <textarea rows={5} value={songBatchImportPayload.song_ids} onChange={(event) => updateSongBatchImportPayload('song_ids', event.target.value)} placeholder="https://suno.com/song/96fdbd12-4ea1-41b4-a132-4b731ec6594e
96fdbd12-4ea1-41b4-a132-4b731ec6594e" />
            </label>
            <label className="check-row">
              <input type="checkbox" checked={songBatchImportPayload.cache_audio} onChange={(event) => updateSongBatchImportPayload('cache_audio', event.target.checked)} />
              Audio lokal speichern
            </label>
            <label className="check-row">
              <input type="checkbox" checked={songBatchImportPayload.cache_cover} onChange={(event) => updateSongBatchImportPayload('cache_cover', event.target.checked)} />
              Cover lokal speichern
            </label>
            <label className="check-row">
              <input type="checkbox" checked={songBatchImportPayload.import_video_url} onChange={(event) => updateSongBatchImportPayload('import_video_url', event.target.checked)} />
              Video-URL übernehmen
            </label>
            <label className="check-row">
              <input type="checkbox" checked={songBatchImportPayload.overwrite_existing} onChange={(event) => updateSongBatchImportPayload('overwrite_existing', event.target.checked)} />
              Vorhandene Imports aktualisieren
            </label>
            <label className="check-row">
              <input type="checkbox" checked={songBatchImportPayload.generate_srt} onChange={(event) => updateSongBatchImportPayload('generate_srt', event.target.checked)} />
              Nach Import SRT erzeugen
            </label>
            <label className="check-row">
              <input type="checkbox" checked={songBatchImportPayload.generate_stems} onChange={(event) => updateSongBatchImportPayload('generate_stems', event.target.checked)} />
              Nach Import Stems erzeugen
            </label>
            <div className="form-actions"><button className="primary" type="submit" disabled={songBatchImporting}><RefreshCw size={16} className={songBatchImporting ? 'spin-icon' : ''} /> {songBatchImporting ? 'Importiere…' : 'Song-Batch importieren'}</button></div>
          </form>
        </details>

      </section>

      <section className="panel stack slim-panel">
        <div className="filter-chips">
          {['all','unread','done'].map((key) => <button key={key} className={filter === key ? 'active' : ''} onClick={() => { setFilter(key); setNotificationPage(1); setSelected(new Set()); }}>{key === 'all' ? 'Alle' : key === 'unread' ? 'Offen' : 'Erledigt'}</button>)}
        </div>
        <div className="button-row wrap">
          <button onClick={() => setSelected(new Set(paginatedRows.map((item) => item.id)))}>Aktuelle Seite auswählen</button>
          <button onClick={() => setSelected(new Set())}>Auswahl aufheben</button>
          <button onClick={() => markDone()} disabled={!selected.size}><Check size={16} /> Auswahl erledigt</button>
          <button className="danger" onClick={() => remove()} disabled={!selected.size}><Trash2 size={16} /> Auswahl löschen</button>
        </div>
        <PaginationControls page={safeNotificationPage} totalItems={rows.length} pageSize={NOTIFICATION_PAGE_SIZE} onPageChange={setNotificationPage} label="Benachrichtigungen" />
        {!rows.length ? <EmptyState title="Keine Benachrichtigungen" text="Sobald Tasks fertig sind, erscheinen sie hier." /> : <div className="notification-list">
          {paginatedRows.map((item) => { const friendly = friendlyNotification(item); return <article key={item.id} className={`notification-row ${item.status === 'done' ? 'done' : 'unread'}`}>
            <label className="notification-check"><input type="checkbox" checked={selected.has(item.id)} onChange={() => toggle(item.id)} /></label>
            <button className="notification-open" onClick={() => openNotificationStatusTarget(item)} title="Statusdetails öffnen">
              <Bell size={16} /><span><strong>{friendly.title}</strong><small>{friendly.message || ''} · {formatDate(item.created_at)}</small></span>
            </button>
            <div className="notification-actions">
              <button onClick={() => onOpenNotification(item)}><Eye size={16} /> Details</button>
              <button onClick={() => markDone([item.id])}><Check size={16} /> Erledigt</button>
              <button className="danger" onClick={() => remove([item.id])}><Trash2 size={16} /></button>
            </div>
          </article>; })}
        </div>}
        <PaginationControls page={safeNotificationPage} totalItems={rows.length} pageSize={NOTIFICATION_PAGE_SIZE} onPageChange={setNotificationPage} label="Benachrichtigungen" />
      </section>

      <section className="panel stack">
        <div className="section-title-row">
          <h2>Letzte Tasks</h2>
          <span className="muted">{normalizedTasks.length} Task(s)</span>
        </div>
        <PaginationControls page={safeTaskPage} totalItems={normalizedTasks.length} pageSize={TASK_PAGE_SIZE} onPageChange={setTaskPage} label="Tasks" />
        {!normalizedTasks.length ? <EmptyState title="Keine Tasks" text="Noch keine Tasks vorhanden." /> : <div className="task-list">
          {paginatedTasks.map((task) => <article className={`task-row ${taskClass(task)} ${String(highlightTaskId || '') === String(task.id || '') ? 'is-highlighted' : ''}`} data-task-row-id={task.id} key={task.id || task.task_id}>
            <strong>{task.task_type || 'Task'}</strong>
            <span className="task-status-badge">{task.status || '—'}</span>
            <code>{shortId(task.task_id, 16)}</code>
            <small>{formatDate(task.updated_at || task.created_at)}</small>
            {task.error_message && <p className="task-error">{task.error_message}</p>}
            <div className="task-row-actions">
              <button type="button" onClick={() => onOpenTaskDetails?.(task)}>
                <Eye size={14} /> Details
              </button>
              <button type="button" onClick={() => refreshSingleTask(task)} disabled={!task.task_id}>
                <RefreshCw size={14} /> Prüfen
              </button>
              {isActiveTask(task) && <button type="button" onClick={() => cancelTask(task)}>
                <Square size={14} /> Abbrechen
              </button>}
              <button type="button" onClick={() => markTaskDone(task)}>
                <Check size={14} /> Erledigt
              </button>
              <button type="button" className="danger" onClick={() => deleteTask(task)}>
                <Trash2 size={14} /> Löschen
              </button>
            </div>
          </article>)}
        </div>}
        <PaginationControls page={safeTaskPage} totalItems={normalizedTasks.length} pageSize={TASK_PAGE_SIZE} onPageChange={setTaskPage} label="Tasks" />
      </section>
    </section>
  );
}
