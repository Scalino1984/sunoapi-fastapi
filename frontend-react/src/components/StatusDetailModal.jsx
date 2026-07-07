import React, { useMemo, useState } from 'react';
import { AlertTriangle, Bell, CheckCircle, Clock, Copy, Download, ExternalLink, FileText, RefreshCw, StopCircle } from 'lucide-react';
import { Modal } from './Modal.jsx';
import { copyToClipboard, downloadTextFile, formatDate, safeFilename, shortId } from '../utils.js';
import { useI18n } from '../i18n/I18nContext.jsx';

const ACTIVE_STATUSES = new Set(['PENDING', 'PROCESSING', 'RUNNING', 'QUEUED', 'SUBMITTED', 'CREATED', 'TEXT_SUCCESS', 'FIRST_SUCCESS']);

function normalizeStatus(value) {
  return String(value || '').trim().toUpperCase();
}

function isSuccessStatus(value) {
  const status = normalizeStatus(value);
  return status === 'SUCCESS' || status.includes('COMPLETE') || status.includes('DONE');
}

function isFailedStatus(value) {
  const status = normalizeStatus(value);
  return status.includes('FAIL') || status.includes('ERROR') || status.includes('SENSITIVE_WORD_ERROR');
}

function statusTone(value) {
  if (isFailedStatus(value)) return 'failed';
  if (isSuccessStatus(value)) return 'success';
  if (ACTIVE_STATUSES.has(normalizeStatus(value))) return 'active';
  return 'neutral';
}

function prettyJson(value) {
  if (value == null || value === '') return '';
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function pick(...values) {
  return values.find((value) => value !== undefined && value !== null && String(value).trim() !== '');
}

function getPayloadValue(source, key) {
  if (!source || typeof source !== 'object') return undefined;
  return source[key];
}

function isPlainObject(value) {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

function readPath(source, path) {
  return String(path || '').split('.').filter(Boolean).reduce((current, key) => {
    if (!current || typeof current !== 'object') return undefined;
    return current[key];
  }, source);
}

function addLogSection(sections, label, source, path) {
  const value = readPath(source, path);
  if (Array.isArray(value) && value.length) {
    sections.push({ label, path, count: value.length, entries: value });
    return;
  }
  if (isPlainObject(value) && Object.keys(value).length) {
    sections.push({ label, path, count: 1, entries: [value] });
  }
}

function findNamedLogSections(source, prefix = '') {
  if (!isPlainObject(source)) return [];
  const found = [];
  const visit = (value, path, depth = 0) => {
    if (!isPlainObject(value) || depth > 3) return;
    Object.entries(value).forEach(([key, item]) => {
      const nextPath = path ? `${path}.${key}` : key;
      const normalized = key.toLowerCase();
      const looksLikeLog = normalized.includes('debug') || normalized.includes('log') || normalized.includes('report') || normalized.includes('trace');
      if (looksLikeLog && Array.isArray(item) && item.length) {
        found.push({ label: `${prefix}${nextPath}`, path: nextPath, count: item.length, entries: item });
      } else if (looksLikeLog && isPlainObject(item) && Object.keys(item).length) {
        found.push({ label: `${prefix}${nextPath}`, path: nextPath, count: 1, entries: [item] });
      }
      if (isPlainObject(item)) visit(item, nextPath, depth + 1);
    });
  };
  visit(source, '');
  return found;
}

function uniqueLogSections(sections) {
  const seen = new Set();
  return sections.filter((section) => {
    const key = `${section.label}|${section.path}|${prettyJson(section.entries).slice(0, 240)}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function buildTaskDebugPackage({ task, notification, targetPayload, requestPayload, responsePayload, resultPayload }) {
  const sections = [];
  addLogSection(sections, 'Response debug_log', responsePayload, 'debug_log');
  addLogSection(sections, 'Response steps_log', responsePayload, 'steps_log');
  addLogSection(sections, 'Result srt_debug_log', resultPayload, 'srt_debug_log');
  addLogSection(sections, 'Result debug_log', resultPayload, 'debug_log');
  addLogSection(sections, 'Result alignment_report', resultPayload, 'alignment_report');
  addLogSection(sections, 'Request debug_log', requestPayload, 'debug_log');
  addLogSection(sections, 'Request steps_log', requestPayload, 'steps_log');
  sections.push(...findNamedLogSections(responsePayload, 'response_payload.'));
  sections.push(...findNamedLogSections(resultPayload, 'result_payload.'));
  sections.push(...findNamedLogSections(requestPayload, 'request_payload.'));

  const logs = uniqueLogSections(sections);
  const timeline = logs
    .flatMap((section) => (section.entries || []).map((entry, index) => ({
      source: section.label,
      index: index + 1,
      at: isPlainObject(entry) ? (entry.at || entry.created_at || entry.updated_at || entry.completed_at || entry.heartbeat_at || null) : null,
      entry,
    })))
    .sort((a, b) => String(a.at || '').localeCompare(String(b.at || '')));

  return {
    exported_at: new Date().toISOString(),
    task_summary: {
      local_task_id: task?.id || notification?.task_local_id || targetPayload?.task_local_id || null,
      task_id: task?.task_id || targetPayload?.suno_task_id || notification?.suno_task_id || null,
      task_type: task?.task_type || targetPayload?.task_type || notification?.content_type || null,
      status: task?.status || targetPayload?.status || notification?.status || null,
      notification_id: notification?.id || null,
      notification_event_type: notification?.event_type || null,
      title: notification?.title || requestPayload?.title || resultPayload?.title || null,
      error_message: task?.error_message || null,
      created_at: task?.created_at || notification?.created_at || null,
      updated_at: task?.updated_at || notification?.updated_at || null,
      completed_at: task?.completed_at || null,
      heartbeat_at: task?.heartbeat_at || null,
    },
    debug_logs: logs,
    debug_timeline: timeline,
    payloads: {
      notification: notification || null,
      request_payload: requestPayload || {},
      response_payload: responsePayload || {},
      result_payload: resultPayload || {},
      target_payload: targetPayload || {},
    },
  };
}

function debugPackageToText(debugPackage, t = null) {
  const lines = [];
  const summary = debugPackage?.task_summary || {};
  lines.push(t?.('statusDetail.debugExportTitle', 'Status Debug Export') || 'Status Debug Export');
  lines.push('='.repeat(80));
  lines.push(`Exported at: ${debugPackage?.exported_at || ''}`);
  lines.push(`Local Task ID: ${summary.local_task_id || '—'}`);
  lines.push(`Task ID: ${summary.task_id || '—'}`);
  lines.push(`Task type: ${summary.task_type || '—'}`);
  lines.push(`Status: ${summary.status || '—'}`);
  if (summary.title) lines.push(`Title: ${summary.title}`);
  if (summary.error_message) lines.push(`Error: ${summary.error_message}`);
  lines.push('');
  lines.push('Debug Logs');
  lines.push('-'.repeat(80));
  const sections = debugPackage?.debug_logs || [];
  if (!sections.length) {
    lines.push(t?.('statusDetail.noDebugLogsFound', 'Keine expliziten Debug-Logs gefunden. Payloads sind unten enthalten.') || 'Keine expliziten Debug-Logs gefunden. Payloads sind unten enthalten.');
  }
  sections.forEach((section) => {
    lines.push('');
    lines.push(`## ${section.label} (${section.count})`);
    lines.push(prettyJson(section.entries));
  });
  lines.push('');
  lines.push('Payloads');
  lines.push('-'.repeat(80));
  lines.push(prettyJson(debugPackage?.payloads || {}));
  return lines.join('\n');
}

const LOCAL_TASK_TYPES = new Set(['generate_srt', 'generate_stems', 'bulk_generate_srt', 'bulk_generate_stems', 'generate_cover_art', 'convert_to_wav_local', 'import_sunoapi_task_batch', 'import_suno_song_batch', 'import_suno_song']);

function isLocalAppTask(task, notification) {
  const request = task?.request_payload || {};
  const target = notification?.target_payload || {};
  const type = task?.task_type || target.task_type || '';
  return Boolean(request.local_task || request.backend === 'replicate' || target.local_task || LOCAL_TASK_TYPES.has(type));
}

function statusSteps(task, localTask = false, t = null) {
  const status = normalizeStatus(task?.status);
  const failed = isFailedStatus(status);
  const success = isSuccessStatus(status);
  const submitted = localTask || Boolean(task?.task_id || status === 'SUBMITTED' || status === 'CREATED' || status === 'PENDING' || status === 'PROCESSING' || status === 'RUNNING' || success || failed);
  const processing = Boolean(status === 'PROCESSING' || status === 'RUNNING' || status === 'PENDING' || status === 'TEXT_SUCCESS' || status === 'FIRST_SUCCESS' || success || failed);
  return [
    { label: t?.('statusDetail.steps.localCreated', 'lokal angelegt') || 'lokal angelegt', done: true },
    { label: localTask ? t?.('statusDetail.steps.localWorker', 'lokaler Worker') || 'lokaler Worker' : t?.('statusDetail.steps.sunoTaskId', 'Suno Task-ID') || 'Suno Task-ID', done: submitted },
    { label: t?.('statusDetail.steps.processing', 'in Bearbeitung') || 'in Bearbeitung', done: processing, active: ACTIVE_STATUSES.has(status) },
    { label: failed ? t?.('statusDetail.steps.error', 'Fehler') || 'Fehler' : t?.('statusDetail.steps.done', 'fertig') || 'fertig', done: success || failed, failed }
  ];
}


/*
 * StatusDetailModal intentionally does not render a generic "Fehler-Assistent" box.
 * Status, progress, real error_message, retry/cancel actions and raw payloads are the
 * source of truth here. Re-introduce assistant-style guidance only when it is derived
 * from concrete FAILED/ERROR payloads and provides a task-specific action.
 */

function deriveLiveProgress(task) {
  const response = task?.response_payload && typeof task.response_payload === 'object' ? task.response_payload : {};
  const progress = response.progress && typeof response.progress === 'object' ? response.progress : {};
  const current = Number(progress.current);
  const total = Number(progress.total);
  const hasCounts = Number.isFinite(current) && Number.isFinite(total) && total > 0;
  let percent = Number(progress.percent);
  if (!Number.isFinite(percent) || percent <= 0) {
    percent = hasCounts ? Math.round((current / total) * 100) : NaN;
  }
  percent = Number.isFinite(percent) ? Math.max(0, Math.min(100, percent)) : null;
  const phase = progress.phase || progress.message || null;
  const heartbeatAt = task?.heartbeat_at || progress.last_heartbeat_at || progress.updated_at || response.heartbeat_at || null;
  const hasAny = hasCounts || percent != null || Boolean(phase) || Boolean(heartbeatAt);
  return { hasAny, hasCounts, current, total, percent, phase, heartbeatAt };
}

function DetailRow({ label, value, mono = false }) {
  if (value === undefined || value === null || value === '') return null;
  return (
    <div className="status-detail-item">
      <span>{label}</span>
      <strong className={mono ? 'mono-value' : ''}>{value}</strong>
    </div>
  );
}

function JsonDetails({ title, value }) {
  const text = prettyJson(value);
  if (!text) return null;
  return (
    <details className="status-json-details">
      <summary>{title}</summary>
      <pre>{text}</pre>
    </details>
  );
}

export function StatusDetailModal({
  open,
  notification,
  task,
  loadingTask = false,
  onClose,
  onOpenTarget,
  onRefreshTask,
  onMarkNotificationDone,
  onCancelTask,
  cancelRunning = false,
  refreshRunning = false,
  onPrepareRetry
}) {
  const { t } = useI18n();
  const [debugCopied, setDebugCopied] = useState(false);
  const targetPayload = notification?.target_payload || {};
  const requestPayload = task?.request_payload || {};
  const responsePayload = task?.response_payload || {};
  const resultPayload = task?.result_payload || {};
  const rawStatus = pick(task?.status, targetPayload.status, notification?.status, '—');
  const tone = statusTone(rawStatus);
  const taskId = pick(task?.task_id, targetPayload.suno_task_id, notification?.suno_task_id);
  const title = pick(notification?.title, requestPayload.title, resultPayload.title, task?.task_type, t('statusDetail.title', 'Statusdetails'));
  const subtitle = pick(notification?.message, task?.error_message, `${task?.task_type || notification?.event_type || 'Task'} · ${rawStatus}`);
  const canOpenTarget = Boolean(
    targetPayload.audio_asset_id
    || targetPayload.song_id
    || notification?.content_id
    || notification?.target_tab
    || targetPayload.target_tab
    || task?.id
  );
  const hasTask = Boolean(task?.id);
  const localTask = isLocalAppTask(task, notification);
  const canCancelTask = Boolean(hasTask && localTask && ACTIVE_STATUSES.has(normalizeStatus(rawStatus)));

  const steps = useMemo(() => statusSteps(task || { status: rawStatus, task_id: taskId }, localTask, t), [task, rawStatus, taskId, localTask, t]);
  const liveProgress = useMemo(() => deriveLiveProgress(task), [task]);
  const isActiveTask = ACTIVE_STATUSES.has(normalizeStatus(rawStatus));
  const requestPayloadForActions = task?.request_payload || {};
  const hasPromptForRetry = Boolean(requestPayloadForActions.prompt || requestPayloadForActions.lyrics || requestPayloadForActions.style);
  const canPrepareRetry = Boolean(onPrepareRetry && hasPromptForRetry && isFailedStatus(rawStatus));
  const debugPackage = useMemo(
    () => buildTaskDebugPackage({ task, notification, targetPayload, requestPayload, responsePayload, resultPayload }),
    [task, notification, targetPayload, requestPayload, responsePayload, resultPayload]
  );
  const debugText = useMemo(() => debugPackageToText(debugPackage, t), [debugPackage, t]);
  const debugLogCount = (debugPackage.debug_logs || []).reduce((sum, section) => sum + Number(section.count || 0), 0);
  const debugFilename = `${safeFilename([
    'status-debug',
    task?.id ? `task-${task.id}` : '',
    task?.task_type || targetPayload.task_type || notification?.event_type || '',
    title || '',
  ].filter(Boolean).join('-'))}.json`;

  async function copyDebugLogs() {
    const ok = await copyToClipboard(debugText);
    if (ok) {
      setDebugCopied(true);
      window.setTimeout(() => setDebugCopied(false), 1800);
    }
  }

  function downloadDebugLogs() {
    downloadTextFile(debugFilename, prettyJson(debugPackage), 'application/json;charset=utf-8');
  }

  return (
    <Modal open={open} onClose={onClose} title={t('statusDetail.title', 'Statusdetails')} wide cardClassName="status-detail-modal">
      <div className="status-detail-stack">
        <section className={`status-detail-hero ${tone}`}>
          <div className="status-detail-icon">
            {tone === 'failed' ? <AlertTriangle size={24} /> : tone === 'success' ? <CheckCircle size={24} /> : <Bell size={24} />}
          </div>
          <div>
            <p className="eyebrow">{notification?.event_type || task?.task_type || t('statusDetail.status', 'Status')}</p>
            <h3>{title}</h3>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <span className={`status-detail-badge ${tone}`}>{rawStatus}</span>
        </section>

        {loadingTask && <div className="status-live-box"><RefreshCw size={16} className="spin-icon" /> {t('statusDetail.loading', 'Lade Taskdetails…')}</div>}

        <section className="status-live-box">
          <div className="status-live-head">
            <span className={`live-dot ${isActiveTask ? 'is-live' : ''}`} />
            <strong>{isActiveTask ? t('statusDetail.liveActive', 'Live-Status aktiv') : t('statusDetail.overview', 'Statusübersicht')}</strong>
            <small>{task?.heartbeat_at ? t('statusDetail.heartbeat', 'Heartbeat: {{value}}', { value: formatDate(task.heartbeat_at) }) : task?.updated_at ? t('statusDetail.updated', 'Aktualisiert: {{value}}', { value: formatDate(task.updated_at) }) : notification?.created_at ? t('statusDetail.notificationAt', 'Meldung: {{value}}', { value: formatDate(notification.created_at) }) : ''}</small>
          </div>
          <div className="status-step-line">
            {steps.map((step) => (
              <span key={step.label} className={`${step.done ? 'done' : ''} ${step.active ? 'active' : ''} ${step.failed ? 'failed' : ''}`}>{step.label}</span>
            ))}
          </div>
          {liveProgress.hasAny && (isActiveTask || liveProgress.percent != null) && (
            <div className="status-live-progress">
              {liveProgress.percent != null && (
                <div className="status-progress-bar" role="progressbar" aria-valuenow={liveProgress.percent} aria-valuemin={0} aria-valuemax={100}>
                  <span className={`status-progress-fill ${isActiveTask ? 'is-active' : ''}`} style={{ width: `${liveProgress.percent}%` }} />
                </div>
              )}
              <div className="status-progress-meta">
                {liveProgress.percent != null && <strong>{liveProgress.percent}%</strong>}
                {liveProgress.hasCounts && <span>{liveProgress.current} / {liveProgress.total}</span>}
                {liveProgress.phase && <span className="muted">{liveProgress.phase}</span>}
              </div>
            </div>
          )}
        </section>

        {task?.error_message && (
          <section className="alert error">
            <strong>{t('statusDetail.error', 'Fehler')}</strong>
            <p>{task.error_message}</p>
          </section>
        )}


        <section className="status-detail-grid">
          <DetailRow label={t('statusDetail.localTaskId', 'Lokale Task-ID')} value={task?.id || notification?.task_local_id || targetPayload.task_local_id} />
          {!localTask && <DetailRow label={t('statusDetail.sunoTaskId', 'Suno Task-ID')} value={taskId ? shortId(taskId, 36) : ''} mono />}
          <DetailRow label={t('statusDetail.taskType', 'Task-Typ')} value={task?.task_type || targetPayload.task_type || notification?.content_type} />
          <DetailRow label={t('statusDetail.status', 'Status')} value={rawStatus} />
          <DetailRow label={t('statusDetail.severity', 'Severity')} value={notification?.severity} />
          <DetailRow label={t('statusDetail.target', 'Ziel')} value={notification?.target_tab || targetPayload.target_tab} />
          <DetailRow label={t('statusDetail.audioAssetId', 'AudioAsset-ID')} value={targetPayload.audio_asset_id} />
          <DetailRow label={t('statusDetail.songId', 'Song-ID')} value={targetPayload.song_id} />
          <DetailRow label={t('statusDetail.created', 'Erstellt')} value={formatDate(task?.created_at || notification?.created_at)} />
          <DetailRow label={t('statusDetail.changed', 'Geändert')} value={formatDate(task?.updated_at || notification?.updated_at)} />
        </section>

        <div className="button-row wrap">
          {hasTask && (!localTask || task?.task_id) && (
            <button type="button" onClick={() => onRefreshTask?.(task)} disabled={refreshRunning || (!localTask && !task?.task_id)}>
              <RefreshCw size={16} className={refreshRunning ? 'spin-icon' : ''} /> {t('statusDetail.checkTask', 'Task prüfen')}
            </button>
          )}
          {canCancelTask && (
            <button type="button" className="danger" onClick={() => onCancelTask?.(task)} disabled={cancelRunning}>
              <StopCircle size={16} className={cancelRunning ? 'spin-icon' : ''} /> {t('statusDetail.cancelJob', 'Job abbrechen')}
            </button>
          )}
          {canOpenTarget && (
            <button type="button" className="primary" onClick={() => onOpenTarget?.({ notification, task })}>
              <ExternalLink size={16} /> {t('statusDetail.openTarget', 'Ziel öffnen')}
            </button>
          )}
          {notification?.id && notification?.status !== 'done' && (
            <button type="button" onClick={() => onMarkNotificationDone?.(notification)}>
              <CheckCircle size={16} /> {t('statusDetail.markDone', 'Meldung erledigen')}
            </button>
          )}
          {canPrepareRetry && (
            <button type="button" onClick={() => onPrepareRetry?.(task, 'same')}>
              {t('statusDetail.retry', 'Retry vorbereiten')}
            </button>
          )}
          {canPrepareRetry && (
            <button type="button" onClick={() => onPrepareRetry?.(task, 'without_voice')}>
              {t('statusDetail.retryWithoutVoice', 'Ohne Voice vorbereiten')}
            </button>
          )}
          {canPrepareRetry && (
            <button type="button" onClick={() => onPrepareRetry?.(task, 'safe_check')}>
              {t('statusDetail.safeCheck', 'Suno-Safe-Check öffnen')}
            </button>
          )}
          {taskId && (
            <button type="button" onClick={() => navigator.clipboard?.writeText(taskId)}>
              <Copy size={16} /> {t('statusDetail.copyTaskId', 'Task-ID kopieren')}
            </button>
          )}
          <button type="button" onClick={copyDebugLogs}>
            <Copy size={16} /> {debugCopied ? t('statusDetail.debugCopied', 'Debug kopiert') : t('statusDetail.copyDebugLogs', 'Debug kopieren')}
          </button>
          <button type="button" onClick={downloadDebugLogs}>
            <Download size={16} /> {t('statusDetail.downloadDebugJson', 'Debug JSON')}
          </button>
        </div>

        <section className="status-debug-export-box">
          <div>
            <p className="eyebrow">{t('statusDetail.debugExportEyebrow', 'Debug Export')}</p>
            <strong>{t('statusDetail.debugExportTitle', 'Status Debug Export')}</strong>
            <p className="muted">
              {debugLogCount
                ? t('statusDetail.debugExportText', '{{count}} Debug-/Log-Einträge aus Task-Payloads erkannt. Export enthält zusätzlich Request, Response, Result und Target Payload.', { count: debugLogCount })
                : t('statusDetail.debugExportNoLogsText', 'Keine expliziten Debug-Logs erkannt. Export enthält trotzdem alle relevanten Payloads für die Analyse.')}
            </p>
          </div>
          <div className="button-row wrap">
            <button type="button" onClick={copyDebugLogs}><Copy size={15} /> {t('statusDetail.copyAllDebug', 'Alle Debugdaten kopieren')}</button>
            <button type="button" onClick={downloadDebugLogs}><Download size={15} /> {t('statusDetail.downloadDebugJson', 'Debug JSON')}</button>
          </div>
        </section>

        <section className="status-json-stack">
          <JsonDetails title={t('statusDetail.debugPackage', 'Debug Export Paket')} value={debugPackage} />
          <JsonDetails title={t('statusDetail.notification', 'Benachrichtigung')} value={notification} />
          <JsonDetails title={t('statusDetail.requestPayload', 'Request Payload')} value={requestPayload} />
          <JsonDetails title={t('statusDetail.responsePayload', 'Response Payload')} value={responsePayload} />
          <JsonDetails title={t('statusDetail.resultPayload', 'Result Payload')} value={resultPayload} />
          <JsonDetails title={t('statusDetail.targetPayload', 'Target Payload')} value={targetPayload} />
        </section>

        {!task && !loadingTask && (
          <p className="muted"><FileText size={14} /> {t('statusDetail.noTask', 'Zu dieser Meldung wurde kein lokaler Taskdatensatz gefunden. Die Meldungsdetails bleiben trotzdem sichtbar.')}</p>
        )}
      </div>
    </Modal>
  );
}
