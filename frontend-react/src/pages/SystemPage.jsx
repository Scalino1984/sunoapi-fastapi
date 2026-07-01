import React, { useEffect, useState } from 'react';
import { Copy, DatabaseBackup, Download, RefreshCw, UploadCloud, Wrench } from 'lucide-react';
import { api } from '../api/client.js';
import { SectionHeader } from '../components/SectionHeader.jsx';
import { useI18n } from '../i18n/I18nContext.jsx';

function uploadLabel(file) {
  return file?.original_name || file?.source_url || file?.uploaded_url || `Upload #${file?.id}`;
}

export function SystemPage({ notify, uploadedFiles = [], onRefresh }) {
  const { t } = useI18n();
  const [diagnostics, setDiagnostics] = useState(null);
  const [backupStatus, setBackupStatus] = useState(null);
  const [dbMaintenance, setDbMaintenance] = useState(null);
  const [dbMaintBusy, setDbMaintBusy] = useState(false);
  const [dbMaintVacuum, setDbMaintVacuum] = useState(false);
  const [songSyncExternalSource, setSongSyncExternalSource] = useState('');
  const [coverCacheLimit, setCoverCacheLimit] = useState(100);
  const [loading, setLoading] = useState(false);
  const [backupBusy, setBackupBusy] = useState(false);
  const [backupFile, setBackupFile] = useState(null);
  const [backupJob, setBackupJob] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [urlUpload, setUrlUpload] = useState('');
  const [base64Upload, setBase64Upload] = useState('');
  const [base64Name, setBase64Name] = useState('');
  const [streamFile, setStreamFile] = useState(null);

  async function load(options = {}) {
    const silent = Boolean(options.silent);
    setLoading(true);
    try {
      const [diagResult, backupResult, maintenanceResult] = await Promise.allSettled([
        api.system.diagnostics(),
        api.system.portableBackupStatus(),
        api.system.databaseMaintenanceStatus()
      ]);
      if (diagResult.status === 'fulfilled') {
        setDiagnostics(diagResult.value);
        if (!silent && diagResult.value?.ok) notify?.(t('system.messages.diagnosticsUpdated', 'Systemdiagnose aktualisiert.'), 'success');
        if (!silent && diagResult.value?.ok === false) notify?.(t('system.messages.diagnosticsWarning', 'Systemdiagnose mit Warnungen geladen.'), 'warning');
      } else {
        const err = diagResult.reason;
        const message = err?.status === 401
          ? t('system.messages.sessionExpired', 'Deine Sitzung ist abgelaufen. Bitte neu anmelden.')
          : err?.message || t('system.messages.diagnosticsFailed', 'Diagnose konnte nicht geladen werden.');
        setDiagnostics({ ok: false, error: message });
        if (!silent) notify?.(message, 'error');
      }
      if (backupResult.status === 'fulfilled') setBackupStatus(backupResult.value);
      if (maintenanceResult.status === 'fulfilled') setDbMaintenance(maintenanceResult.value);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load({ silent: true }); }, []);



  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename || 'suno_song_studio_backup.zip';
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function sleep(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  function isTerminalJob(job) {
    return ['completed', 'failed', 'cancelled'].includes(String(job?.status || '').toLowerCase());
  }

  async function waitForBackupJob(jobId, options = {}) {
    const downloadWhenComplete = Boolean(options.downloadWhenComplete);
    let latest = null;
    for (;;) {
      latest = await api.system.portableBackupJob(jobId);
      setBackupJob(latest);
      if (isTerminalJob(latest)) break;
      await sleep(1000);
    }
    if (latest?.status === 'failed') {
      throw new Error(latest?.error || latest?.message || t('system.messages.backupJobFailed', 'Portable-Backup-Job fehlgeschlagen.'));
    }
    if (latest?.status !== 'completed') {
      throw new Error(latest?.message || t('system.messages.backupJobIncomplete', 'Portable-Backup-Job wurde nicht abgeschlossen.'));
    }
    if (downloadWhenComplete && latest?.download_ready) {
      const result = await api.system.downloadPortableBackupJob(jobId);
      downloadBlob(result.blob, result.filename || latest.download_filename);
    }
    return latest;
  }

  async function createPortableBackup() {
    setBackupBusy(true);
    setUploadProgress(null);
    setBackupJob({ status: 'queued', phase: 'start', message: t('system.messages.exportPreparing', 'Export wird vorbereitet.'), percent: 0 });
    try {
      const job = await api.system.startPortableBackupExport({ normalize_paths: true, note: 'Frontend Portable Backup' });
      setBackupJob(job);
      await waitForBackupJob(job.id, { downloadWhenComplete: true });
      notify?.(t('system.messages.backupCreated', 'Portables Backup wurde erstellt und heruntergeladen.'), 'success');
      await load({ silent: true });
    } catch (err) {
      notify?.(err.message || t('system.messages.backupCreateFailed', 'Portables Backup konnte nicht erstellt werden.'), 'error');
    } finally {
      setBackupBusy(false);
    }
  }

  async function normalizePortablePaths() {
    setBackupBusy(true);
    try {
      const result = await api.system.normalizePortablePaths(false);
      await load({ silent: true });
      const changed = Object.values(result?.stats || {}).reduce((sum, item) => sum + Number(item?.changed || 0), 0);
      notify?.(t('system.messages.pathsNormalized', 'Portable Pfade normalisiert: {{count}} Änderung(en).', { count: changed }), 'success');
    } catch (err) {
      notify?.(err.message || t('system.messages.pathsNormalizeFailed', 'Portable Pfade konnten nicht normalisiert werden.'), 'error');
    } finally {
      setBackupBusy(false);
    }
  }

  async function importPortableBackup(event) {
    event.preventDefault();
    if (!backupFile) return notify?.(t('system.messages.backupZipMissing', 'Bitte ein Portable-Backup-ZIP auswählen.'), 'error');
    const confirmed = window.confirm(t('system.messages.confirmBackupImport', 'Import wirklich starten? Vor dem Import wird automatisch ein Backup des aktuellen Ist-Stands erstellt. Danach wird der importierte Stand als frischer Zustand übernommen.'));
    if (!confirmed) return;
    setBackupBusy(true);
    setBackupJob({ status: 'uploading', phase: 'upload', message: t('system.messages.backupUploading', 'Backup-ZIP wird hochgeladen.'), percent: 0 });
    setUploadProgress({ percent: 0, loaded: 0, total: backupFile.size || 0 });
    try {
      const job = await api.system.startPortableBackupImport(backupFile, (percent, loaded, total) => {
        setUploadProgress({ percent, loaded, total });
        setBackupJob({ status: 'uploading', phase: 'upload', message: t('system.messages.backupUploadingPercent', 'Backup-ZIP wird hochgeladen: {{percent}}%', { percent }), percent: Math.min(25, Math.round(percent * 0.25)), current: loaded, total });
      });
      setBackupJob(job);
      setUploadProgress(null);
      const result = await waitForBackupJob(job.id);
      setBackupFile(null);
      event.target.reset();
      await onRefresh?.({ silent: true });
      await load({ silent: true });
      notify?.(t('system.messages.backupImported', 'Portable Backup importiert. Vorher-Backup: {{backup}}', { backup: result?.result?.pre_import_backup || t('system.messages.createdFallback', 'erstellt') }), 'success');
    } catch (err) {
      notify?.(err.message || t('system.messages.backupImportFailed', 'Portable Backup konnte nicht importiert werden.'), 'error');
    } finally {
      setBackupBusy(false);
    }
  }


  function severityClass(value) {
    const key = String(value || 'ok').toLowerCase();
    if (['critical', 'high'].includes(key)) return 'danger';
    if (['medium', 'low'].includes(key)) return 'warning';
    return 'success';
  }

  async function runDatabaseMaintenance(dryRun = true) {
    if (!dryRun) {
      const confirmed = window.confirm(t('system.messages.confirmDbMaintenance', 'DB-Wartung wirklich ausführen? Vorher wird automatisch ein Backup der SQLite-Datenbank erstellt.'));
      if (!confirmed) return;
    }
    setDbMaintBusy(true);
    try {
      const result = await api.system.runDatabaseMaintenance({
        dry_run: dryRun,
        confirm: !dryRun,
        backup: true,
        vacuum: !dryRun && dbMaintVacuum,
        materialize_limit: 800
      });
      setDbMaintenance(result);
      await load({ silent: true });
      notify?.(dryRun ? t('system.messages.dbDryRunDone', 'DB-Wartung Dry-Run abgeschlossen.') : t('system.messages.dbMaintenanceDone', 'DB-Wartung abgeschlossen.'), result?.ok ? 'success' : 'warning');
    } catch (err) {
      notify?.(err.message || t('system.messages.dbMaintenanceFailed', 'DB-Wartung konnte nicht ausgeführt werden.'), 'error');
    } finally {
      setDbMaintBusy(false);
    }
  }


  async function syncSongsToLibrary(dryRun = true) {
    if (!dryRun) {
      const confirmed = window.confirm(t('system.messages.confirmSongSync', 'Songs wirklich in die Library synchronisieren? Fehlende AudioAssets werden aus lokalen /api/music/songs-Metadaten ergänzt und Original-Suno-Daten für die Sortierung normalisiert.'));
      if (!confirmed) return;
    }
    setDbMaintBusy(true);
    try {
      const externalSource = songSyncExternalSource.trim();
      const result = await api.system.syncSongsToLibrary({
        dry_run: dryRun,
        limit: 2000,
        task_type: 'generate_music',
        task_ids: externalSource,
        source_json: externalSource.startsWith('[') || externalSource.startsWith('{') ? externalSource : ''
      });
      await load({ silent: true });
      const label = dryRun ? t('system.messages.songSyncChecked', 'Song-Library-Sync geprüft') : t('system.messages.songSyncDone', 'Song-Library-Sync ausgeführt');
      notify?.(t('system.messages.songSyncSummary', '{{label}}: {{created}} erstellt, {{updated}} aktualisiert, {{external}} extern importiert, {{cached}} lokal gespeichert.', { label, created: result.created || 0, updated: result.updated || 0, external: result.external_task_imported || 0, cached: result.cached_audio_files || 0 }), result?.ok ? 'success' : 'warning');
    } catch (err) {
      notify?.(err.message || t('system.messages.songSyncFailed', 'Song-Library-Sync konnte nicht ausgeführt werden.'), 'error');
    } finally {
      setDbMaintBusy(false);
    }
  }


  async function cacheExternalCovers(dryRun = true) {
    if (!dryRun) {
      const confirmed = window.confirm(t('system.messages.confirmCoverCache', 'Externe Cover wirklich lokal nach storage/covers cachen? Die betroffenen Cover-Referenzen werden anschließend auf /media/covers/... umgestellt.'));
      if (!confirmed) return;
    }
    setDbMaintBusy(true);
    try {
      const result = await api.system.cacheExternalCovers({
        dry_run: dryRun,
        confirm: !dryRun,
        limit: Number(coverCacheLimit || 100)
      });
      await load({ silent: true });
      const label = dryRun ? t('system.messages.externalCoversChecked', 'Externe Cover geprüft') : t('system.messages.externalCoversCached', 'Externe Cover lokal gecacht');
      notify?.(t('system.messages.coverCacheSummary', '{{label}}: {{urls}} URL(s), {{updated}} Referenz(en) aktualisiert, {{failed}} Fehler.', { label, urls: result.candidate_urls || 0, updated: result.updated_references || 0, failed: result.failed || 0 }), result?.ok ? 'success' : 'warning');
    } catch (err) {
      notify?.(err.message || t('system.messages.coverCacheFailed', 'Externe Cover konnten nicht verarbeitet werden.'), 'error');
    } finally {
      setDbMaintBusy(false);
    }
  }

  async function afterUpload(message) {
    await onRefresh?.({ silent: true });
    notify?.(message, 'success');
  }

  async function submitUrlUpload(event) {
    event.preventDefault();
    if (!urlUpload.trim()) return notify?.(t('system.messages.urlMissing', 'Bitte eine URL eintragen.'), 'error');
    setUploading(true);
    try {
      await api.files.uploadUrl(urlUpload.trim());
      setUrlUpload('');
      await afterUpload(t('system.messages.urlUploadDone', 'URL-Upload abgeschlossen. Die Upload-URL kann jetzt in Musik-Operationen verwendet werden.'));
    } catch (err) {
      notify?.(err.message || t('system.messages.urlUploadFailed', 'URL-Upload fehlgeschlagen.'), 'error');
    } finally {
      setUploading(false);
    }
  }

  async function submitStreamUpload(event) {
    event.preventDefault();
    if (!streamFile) return notify?.(t('system.messages.fileMissing', 'Bitte eine Datei auswählen.'), 'error');
    setUploading(true);
    try {
      await api.files.uploadStream(streamFile);
      setStreamFile(null);
      event.target.reset();
      await afterUpload(t('system.messages.fileUploadDone', 'Datei-Upload abgeschlossen.'));
    } catch (err) {
      notify?.(err.message || t('system.messages.fileUploadFailed', 'Datei-Upload fehlgeschlagen.'), 'error');
    } finally {
      setUploading(false);
    }
  }

  async function submitBase64Upload(event) {
    event.preventDefault();
    if (!base64Upload.trim()) return notify?.(t('system.messages.base64Missing', 'Bitte Base64-Inhalt eintragen.'), 'error');
    setUploading(true);
    try {
      await api.files.uploadBase64(base64Upload.trim(), base64Name.trim());
      setBase64Upload('');
      setBase64Name('');
      await afterUpload(t('system.messages.base64UploadDone', 'Base64-Upload abgeschlossen.'));
    } catch (err) {
      notify?.(err.message || t('system.messages.base64UploadFailed', 'Base64-Upload fehlgeschlagen.'), 'error');
    } finally {
      setUploading(false);
    }
  }

  async function copyUrl(url) {
    if (!url) return;
    await navigator.clipboard?.writeText(url);
    notify?.(t('system.messages.uploadUrlCopied', 'Upload-URL kopiert.'), 'success');
  }

  return (
    <section className="page stack">
      <SectionHeader eyebrow={t('system.eyebrow', 'Betrieb')} title={t('nav.system', 'System')}>
        <button onClick={() => load()} className={loading ? 'spin' : ''}><RefreshCw size={16} /> {t('topbar.refresh', 'Aktualisieren')}</button>
      </SectionHeader>




      <section className="panel stack database-maintenance-panel">
        <div className="row between align-start">
          <div>
            <p className="eyebrow">{t('system.db.eyebrow', 'Lokaler Master · Datenbankwartung')}</p>
            <h2>{t('system.db.title', 'Datenbank prüfen und konsistent halten')}</h2>
            <p className="muted">{t('system.db.text', 'Sichere Wartung für Altzustände, verwaiste Verknüpfungen, Favoriten-Sync, hängende lokale Tasks, portable Pfade und optionale SQLite-Optimierung. Standard ist immer zuerst ein Dry-Run.')}</p>
          </div>
          <Wrench size={24} />
        </div>
        {dbMaintenance && (
          <div className="system-backup-grid">
            <article className="nested-panel soft-panel"><span>{t('system.db.integrity', 'Integrität')}</span><strong>{dbMaintenance.integrity}</strong></article>
            <article className="nested-panel soft-panel"><span>{t('system.db.maxSeverity', 'Max. Schwere')}</span><strong className={`severity-text ${severityClass(dbMaintenance.max_severity)}`}>{dbMaintenance.max_severity}</strong></article>
            <article className="nested-panel soft-panel"><span>Dry-Run</span><strong>{dbMaintenance.dry_run ? t('common.yes', 'ja') : t('common.no', 'nein')}</strong></article>
            <article className="nested-panel soft-panel"><span>{t('system.backup.backup', 'Backup')}</span><code>{dbMaintenance.backup_path || '—'}</code></article>
          </div>
        )}
        {dbMaintenance?.summary && (
          <div className="db-maintenance-summary">
            {Object.entries(dbMaintenance.summary).map(([key, value]) => (
              <span key={key} className={`status-pill ${key}`}>{key}: {value}</span>
            ))}
          </div>
        )}
        <div className="song-sync-external-source">
          <label>{t('system.db.externalSourceLabel', 'Optionale externe SunoAPI.org Task-IDs oder Server-/api/music/songs JSON')}
            <textarea
              rows={4}
              value={songSyncExternalSource}
              onChange={(event) => setSongSyncExternalSource(event.target.value)}
              placeholder={t('system.db.externalSourcePlaceholder', 'Task-ID 1\nTask-ID 2\noder komplette JSON-Antwort von /api/music/songs einfügen')}
            />
          </label>
          <p className="muted">{t('system.db.externalSourceHint', 'Wenn hier Task-IDs oder Server-JSON stehen, importiert die Synchronisierung fehlende SunoAPI.org Tasks über die vorhandene Record-Info-Schnittstelle und speichert sie bei SUNO_AUDIO_CACHE_MODE=on_success lokal.')}</p>
        </div>

        <div className="song-sync-external-source">
          <label>{t('system.db.coverCacheLimit', 'Limit für externe Cover-Cache-Prüfung')}
            <input
              type="number"
              min="1"
              max="500"
              value={coverCacheLimit}
              onChange={(event) => setCoverCacheLimit(event.target.value)}
            />
          </label>
          <p className="muted">{t('system.db.coverCacheHint', 'Prüft externe Cover-URLs in audio_assets, songs und audio_projects. Ein echter Lauf lädt die Bilder über die vorhandene sichere Cover-Cache-Logik nach storage/covers und ersetzt die Referenzen durch /media/covers/...')}</p>
        </div>
        <div className="system-backup-actions">
          <button type="button" onClick={() => runDatabaseMaintenance(true)} disabled={dbMaintBusy}>{t('system.db.dryRunCheck', 'Dry-Run prüfen')}</button>
          <button type="button" className="primary" onClick={() => runDatabaseMaintenance(false)} disabled={dbMaintBusy}>{t('system.db.runMaintenance', 'Wartung ausführen')}</button>
          <button type="button" onClick={() => syncSongsToLibrary(true)} disabled={dbMaintBusy}>{t('system.db.checkSongSync', 'Songs -> Library prüfen')}</button>
          <button type="button" onClick={() => syncSongsToLibrary(false)} disabled={dbMaintBusy}>{t('system.db.syncSongs', 'Songs -> Library synchronisieren')}</button>
          <button type="button" onClick={() => cacheExternalCovers(true)} disabled={dbMaintBusy}>{t('system.db.checkExternalCovers', 'Externe Cover prüfen')}</button>
          <button type="button" onClick={() => cacheExternalCovers(false)} disabled={dbMaintBusy}>{t('system.db.cacheExternalCovers', 'Externe Cover lokal cachen')}</button>
          <label className="inline-check"><input type="checkbox" checked={dbMaintVacuum} onChange={(event) => setDbMaintVacuum(event.target.checked)} /> {t('system.db.vacuumAnalyze', 'SQLite VACUUM/ANALYZE ausführen')}</label>
        </div>
        {dbMaintenance?.actions?.length > 0 && (
          <div className="table-wrap">
            <table className="mini-table db-maintenance-table">
              <thead><tr><th>{t('system.table.area', 'Bereich')}</th><th>Code</th><th>{t('system.table.severity', 'Schwere')}</th><th>{t('system.table.count', 'Anzahl')}</th><th>{t('system.table.description', 'Beschreibung')}</th></tr></thead>
              <tbody>
                {dbMaintenance.actions.filter((item) => Number(item.count || 0) > 0).map((item) => (
                  <tr key={`${item.area}-${item.code}`}>
                    <td>{item.area}</td>
                    <td><code>{item.code}</code></td>
                    <td><span className={`status-pill ${item.severity}`}>{item.severity}</span></td>
                    <td>{item.count}</td>
                    <td>{item.description}{item.examples?.length ? <details><summary>{t('system.table.examples', 'Beispiele')}</summary><pre>{JSON.stringify(item.examples, null, 2)}</pre></details> : null}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel stack">
        <div className="row between align-start">
          <div>
            <p className="eyebrow">{t('system.backup.eyebrow', 'Lokaler Master · Portable Backup')}</p>
            <h2>{t('system.backup.title', 'Backup exportieren / importieren')}</h2>
            <p className="muted">{t('system.backup.text', 'Das portable Backup enthält die SQLite-Datenbank sowie lokale Audio-, Cover-, Transcript-, Stem- und Export-Dateien. Pfade werden portabel gespeichert, damit ein Backup lokal erstellt und auf einem frischen oder bestehenden Server importiert werden kann.')}</p>
          </div>
          <DatabaseBackup size={24} />
        </div>
        <div className="system-backup-actions">
          <button type="button" className="primary" onClick={createPortableBackup} disabled={backupBusy}>
            <Download size={16} /> {t('system.backup.create', 'Portable Backup erstellen')}
          </button>
          <button type="button" onClick={normalizePortablePaths} disabled={backupBusy}>{t('system.backup.normalizePaths', 'Pfade normalisieren')}</button>
          <button type="button" onClick={() => load()} disabled={loading || backupBusy}>{t('system.backup.refreshStatus', 'Status aktualisieren')}</button>
        </div>
        {(backupJob || uploadProgress) && (
          <div className="system-backup-progress nested-panel soft-panel">
            <div className="row between align-start">
              <div>
                <strong>{backupJob?.job_type === 'portable_import' || backupJob?.status === 'uploading' ? t('system.backup.importProgress', 'Import-Fortschritt') : t('system.backup.exportProgress', 'Export-Fortschritt')}</strong>
                <p className="muted">{backupJob?.message || t('system.backup.waitingProgress', 'Warte auf Fortschrittsdaten…')}</p>
              </div>
              <span className={`status-pill ${backupJob?.status || 'queued'}`}>{backupJob?.status || 'queued'}</span>
            </div>
            <div className="backup-progress-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={Number(backupJob?.percent || 0)}>
              <span style={{ width: `${Math.max(0, Math.min(100, Number(backupJob?.percent || 0)))}%` }} />
            </div>
            <div className="row between small muted">
              <span>{backupJob?.phase || 'start'}</span>
              <span>{Math.max(0, Math.min(100, Number(backupJob?.percent || 0)))}%</span>
            </div>
            {backupJob?.total ? <small className="muted">{t('system.backup.progress', 'Fortschritt')}: {backupJob.current || 0} / {backupJob.total}</small> : null}
            {backupJob?.error ? <p className="error-text">{backupJob.error}</p> : null}
          </div>
        )}
        {backupStatus && (
          <div className="system-backup-grid">
            <article className="nested-panel soft-panel"><span>{t('system.backup.localStorage', 'Lokaler Speicher')}</span><strong>{backupStatus.local_content_storage_enabled ? t('system.state.active', 'aktiv') : t('system.state.inactive', 'deaktiviert')}</strong></article>
            <article className="nested-panel soft-panel"><span>{t('system.backup.audioCache', 'Audio-Cache')}</span><strong>{backupStatus.audio_cache_mode}</strong></article>
            <article className="nested-panel soft-panel"><span>{t('system.backup.backupDir', 'Backup-Verzeichnis')}</span><code>{backupStatus.backup_dir}</code></article>
          </div>
        )}
        {backupStatus?.portable_path_check?.stats && (
          <div className="nested-panel soft-panel stack">
            <h3>{t('system.backup.pathCheck', 'Portable Pfadprüfung')}</h3>
            <div className="table-wrap">
              <table className="mini-table"><thead><tr><th>{t('system.table.area', 'Bereich')}</th><th>{t('system.backup.checked', 'Geprüft')}</th><th>{t('system.backup.absolutePaths', 'Absolute Pfade')}</th><th>{t('system.backup.changeable', 'Änderbar')}</th><th>{t('system.backup.missingFiles', 'Fehlende Dateien')}</th></tr></thead><tbody>
                {Object.entries(backupStatus.portable_path_check.stats).map(([key, item]) => (
                  <tr key={key}><td>{key}</td><td>{item.checked}</td><td>{item.absolute_before}</td><td>{item.changed}</td><td>{item.missing_files}</td></tr>
                ))}
              </tbody></table>
            </div>
          </div>
        )}
        <form className="nested-panel soft-panel stack" onSubmit={importPortableBackup}>
          <h3>{t('system.backup.importTitle', 'Portable Backup importieren')}</h3>
          <p className="muted">{t('system.backup.importText', 'Beim Import wird automatisch zuerst ein Backup des aktuellen Ist-Stands abgelegt. Danach werden DB und lokale Dateien aus dem ZIP als neuer frischer Stand übernommen.')}</p>
          <label>{t('system.backup.backupZip', 'Backup-ZIP')}<input type="file" accept=".zip,application/zip" onChange={(event) => setBackupFile(event.target.files?.[0] || null)} /></label>
          <button type="submit" className="danger" disabled={backupBusy || !backupFile}>{t('system.backup.importButton', 'Backup importieren')}</button>
        </form>
      </section>

      <section className="panel stack">
        <div className="row between align-start">
          <div>
            <p className="eyebrow">{t('system.upload.eyebrow', 'Expertenbereich · SunoAPI Upload-Cache')}</p>
            <h2>{t('system.upload.title', 'Zentrale Upload-Ablage')}</h2>
            <p className="muted">{t('system.upload.text', 'Diese Ablage ist nur die technische Übersicht bereits vorbereiteter SunoAPI-Upload-URLs. Für normale Nutzung findest du Uploads jetzt direkt bei der jeweiligen Aktion unter Musik -> Upload And Extend, Upload And Cover, Add Vocals oder ähnlichen Folgeoperationen.')}</p>
          </div>
          <UploadCloud size={24} />
        </div>
        <details className="nested-panel soft-panel stack system-upload-expert-panel">
          <summary>{t('system.upload.manualSummary', 'Manueller Upload in die zentrale Ablage')}</summary>
          <p className="muted">{t('system.upload.manualText', 'Nur verwenden, wenn du bewusst eine Upload-URL unabhängig von einer konkreten Musik-Aktion vorbereiten möchtest. Im Alltag ist der Upload direkt im passenden Musik-Workflow übersichtlicher.')}</p>
          <div className="form-grid three">
            <form className="nested-panel soft-panel stack" onSubmit={submitUrlUpload}>
              <h3>{t('system.upload.urlUpload', 'URL Upload')}</h3>
              <label>{t('system.upload.sourceUrl', 'Quell-URL')}<input value={urlUpload} onChange={(event) => setUrlUpload(event.target.value)} placeholder="https://.../audio.mp3" /></label>
              <button className="primary" disabled={uploading}>{t('system.upload.uploadUrl', 'URL hochladen')}</button>
            </form>
            <form className="nested-panel soft-panel stack" onSubmit={submitStreamUpload}>
              <h3>{t('system.upload.fileUpload', 'Datei Upload')}</h3>
              <label>{t('system.upload.file', 'Datei')}<input type="file" accept="audio/*,.mp3,.wav,.m4a,.aac,.flac,.ogg,.webm" onChange={(event) => setStreamFile(event.target.files?.[0] || null)} /></label>
              <button className="primary" disabled={uploading}>{t('system.upload.uploadFile', 'Datei hochladen')}</button>
            </form>
            <form className="nested-panel soft-panel stack" onSubmit={submitBase64Upload}>
              <h3>{t('system.upload.base64Upload', 'Base64 Upload')}</h3>
              <label>{t('system.upload.filenameOptional', 'Dateiname optional')}<input value={base64Name} onChange={(event) => setBase64Name(event.target.value)} placeholder="aufnahme.mp3" /></label>
              <label>Base64<textarea rows={4} value={base64Upload} onChange={(event) => setBase64Upload(event.target.value)} placeholder={t('system.upload.base64Placeholder', 'Base64-Inhalt…')} /></label>
              <button className="primary" disabled={uploading}>{t('system.upload.uploadBase64', 'Base64 hochladen')}</button>
            </form>
          </div>
        </details>

        {uploadedFiles.length > 0 && (
          <div className="upload-file-list">
            {uploadedFiles.map((file) => (
              <article className="upload-file-card" key={file.id}>
                <div>
                  <strong>{uploadLabel(file)}</strong>
                  <small>{file.upload_method} · #{file.id}</small>
                  {file.uploaded_url && <code>{file.uploaded_url}</code>}
                </div>
                <button type="button" onClick={() => copyUrl(file.uploaded_url)} disabled={!file.uploaded_url}><Copy size={15} /> {t('common.copy', 'Kopieren')}</button>
              </article>
            ))}
          </div>
        )}
      </section>

      <div className="system-grid">
        {diagnostics && Object.entries(diagnostics).filter(([, value]) => typeof value !== 'object' || value === null).map(([key, value]) => <article className="panel system-card" key={key}><span>{key}</span><strong>{String(value)}</strong></article>)}
      </div>
      <pre className="panel diagnostics-panel">{JSON.stringify(diagnostics, null, 2)}</pre>
    </section>
  );
}
