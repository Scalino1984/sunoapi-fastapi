import React, { useMemo } from 'react';
import { AlertTriangle, Bell, CheckCircle, Clock, Copy, ExternalLink, FileText, RefreshCw, StopCircle, Wand2 } from 'lucide-react';
import { Modal } from './Modal.jsx';
import { formatDate, shortId } from '../utils.js';
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


function buildErrorAssistant(task, notification, t = null) {
  const request = task?.request_payload || {};
  const status = normalizeStatus(task?.status || notification?.severity || '');
  const error = String(task?.error_message || notification?.message || '').toUpperCase();
  const hasVoice = Boolean(request.voice_id || request.persona_id || request.personaId);
  const items = [];
  if (status.includes('SENSITIVE') || error.includes('SENSITIVE')) {
    items.push(t?.('statusDetail.assistantItems.sensitive', 'Suno hat den Inhalt wegen Inhaltsprüfung blockiert. Mit Voice/Persona ist die Prüfung oft strenger.') || 'Suno hat den Inhalt wegen Inhaltsprüfung blockiert. Mit Voice/Persona ist die Prüfung oft strenger.');
    if (hasVoice) items.push(t?.('statusDetail.assistantItems.withoutVoice', 'Schnellster Test: denselben Prompt ohne Voice erneut vorbereiten.') || 'Schnellster Test: denselben Prompt ohne Voice erneut vorbereiten.');
    items.push(t?.('statusDetail.assistantItems.soften', 'Alternativ: Text entschärfen, direkte 18+/Gewalt-/Körper-Disses reduzieren und erneut prüfen.') || 'Alternativ: Text entschärfen, direkte 18+/Gewalt-/Körper-Disses reduzieren und erneut prüfen.');
  } else if (status.includes('FAIL') || error.includes('FAIL') || error.includes('ERROR')) {
    items.push(t?.('statusDetail.assistantItems.failed', 'Fehlerdetails prüfen, Task erneut abrufen und danach entweder Retry oder Import per Task-ID nutzen.') || 'Fehlerdetails prüfen, Task erneut abrufen und danach entweder Retry oder Import per Task-ID nutzen.');
  } else if (ACTIVE_STATUSES.has(status)) {
    items.push(t?.('statusDetail.assistantItems.active', 'Task läuft noch. Statusprüfung erneut ausführen oder automatische Prüfung abwarten.') || 'Task läuft noch. Statusprüfung erneut ausführen oder automatische Prüfung abwarten.');
  }
  return items;
}

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
  const errorAssistantItems = useMemo(() => buildErrorAssistant(task, notification, t), [task, notification, t]);
  const requestPayloadForActions = task?.request_payload || {};
  const hasPromptForRetry = Boolean(requestPayloadForActions.prompt || requestPayloadForActions.lyrics || requestPayloadForActions.style);

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

        {errorAssistantItems.length > 0 && (
          <section className="status-error-assistant">
            <div>
              <p className="eyebrow"><Wand2 size={14} /> {t('statusDetail.errorAssistant', 'Fehler-Assistent')}</p>
              <h4>{t('statusDetail.recommendedSteps', 'Empfohlene nächste Schritte')}</h4>
              <ul>
                {errorAssistantItems.map((item) => <li key={item}>{item}</li>)}
              </ul>
            </div>
            <div className="button-row wrap">
              {hasPromptForRetry && <button type="button" onClick={() => onPrepareRetry?.(task, 'same')}>{t('statusDetail.retry', 'Retry vorbereiten')}</button>}
              {hasPromptForRetry && <button type="button" onClick={() => onPrepareRetry?.(task, 'without_voice')}>{t('statusDetail.retryWithoutVoice', 'Ohne Voice vorbereiten')}</button>}
              {hasPromptForRetry && <button type="button" onClick={() => onPrepareRetry?.(task, 'safe_check')}>{t('statusDetail.safeCheck', 'Suno-Safe-Check öffnen')}</button>}
            </div>
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
          {taskId && (
            <button type="button" onClick={() => navigator.clipboard?.writeText(taskId)}>
              <Copy size={16} /> {t('statusDetail.copyTaskId', 'Task-ID kopieren')}
            </button>
          )}
        </div>

        <section className="status-json-stack">
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
