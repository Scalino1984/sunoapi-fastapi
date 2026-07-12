import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Database,
  Download,
  FileWarning,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  Square,
  Wrench
} from 'lucide-react';
import { api } from '../api/client.js';
import { Modal } from '../components/Modal.jsx';
import { SectionHeader } from '../components/SectionHeader.jsx';
import { useI18n } from '../i18n/I18nContext.jsx';

const TERMINAL = new Set(['SUCCESS', 'FAILED', 'CANCELLED', 'PARTIAL_SUCCESS', 'COMPLETED', 'DONE']);
const SEVERITIES = ['critical', 'high', 'medium', 'low', 'info'];
const SEVERITY_ORDER = new Map(SEVERITIES.map((value, index) => [value, index]));
const GROUP_PAGE_SIZE = 25;
const REPAIR_CONFIRMATION_TEXT = 'REPARATUR ANWENDEN';

function arrayOf(value, key = 'items') {
  if (Array.isArray(value)) return value;
  if (Array.isArray(value?.[key])) return value[key];
  return [];
}

function formatDate(value) {
  if (!value) return '—';
  try { return new Date(value).toLocaleString(); } catch { return String(value); }
}

function statusClass(status) {
  const normalized = String(status || '').toUpperCase();
  if (['SUCCESS', 'COMPLETED', 'DONE'].includes(normalized)) return 'success';
  if (['FAILED', 'ERROR'].includes(normalized)) return 'failed';
  if (['RUNNING', 'QUEUED', 'PENDING', 'PROCESSING', 'CANCEL_REQUESTED'].includes(normalized)) return 'active';
  return '';
}

function severityLabel(value, t) {
  const map = {
    critical: t('audit.severity.critical', 'Kritisch'),
    high: t('audit.severity.high', 'Hoch'),
    medium: t('audit.severity.medium', 'Mittel'),
    low: t('audit.severity.low', 'Niedrig'),
    info: t('audit.severity.info', 'Info')
  };
  return map[value] || value;
}

function saveJson(payload, filename) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function buildFindingGroups(results) {
  const groups = new Map();

  for (const result of results) {
    for (const finding of arrayOf(result, 'findings')) {
      const severity = finding?.severity || 'info';
      const code = finding?.code || finding?.title || 'UNKNOWN_FINDING';
      const key = `${result?.check_id || 'unknown'}::${severity}::${code}`;
      if (!groups.has(key)) {
        groups.set(key, {
          key,
          checkId: result?.check_id || 'unknown',
          checkTitle: result?.title || result?.check_id || 'Audit',
          code,
          severity,
          title: finding?.title || code,
          findings: [],
          repairableCount: 0,
          repairActions: []
        });
      }
      const group = groups.get(key);
      group.findings.push({
        ...finding,
        check_id: result?.check_id || 'unknown',
        check_title: result?.title || result?.check_id || 'Audit'
      });
      if (finding?.repairable) {
        group.repairableCount += 1;
        const action = String(finding?.repair_action || '').trim();
        if (action && !group.repairActions.includes(action)) group.repairActions.push(action);
      }
    }
  }

  return [...groups.values()].sort((left, right) => {
    const severityDiff = (SEVERITY_ORDER.get(left.severity) ?? 99) - (SEVERITY_ORDER.get(right.severity) ?? 99);
    if (severityDiff !== 0) return severityDiff;
    const countDiff = right.findings.length - left.findings.length;
    if (countDiff !== 0) return countDiff;
    return left.title.localeCompare(right.title);
  });
}

function findingEntityLabel(finding) {
  const type = finding?.entity_type || '';
  const id = finding?.entity_id;
  if (!type && (id === undefined || id === null || id === '')) return '';
  return `${type || 'Datensatz'}${id !== undefined && id !== null && id !== '' ? ` #${id}` : ''}`;
}

function findingStatusBreakdown(findings) {
  const counts = new Map();
  for (const finding of findings) {
    const match = String(finding?.message || '').match(/\bStatus\s+([A-Z_]+)\b/i);
    if (!match) continue;
    const status = match[1].toUpperCase();
    counts.set(status, (counts.get(status) || 0) + 1);
  }
  return [...counts.entries()].sort((left, right) => right[1] - left[1]);
}

function problemTypeCount(report) {
  const stored = Number(report?.problem_type_count);
  if (Number.isFinite(stored)) return stored;
  return buildFindingGroups(arrayOf(report, 'results')).length;
}

function isRepairRun(run) {
  return run?.task_type === 'maintenance_repair';
}

function isVerificationRun(run) {
  return run?.task_type === 'maintenance_audit' && Boolean(run?.request_payload?.parameters?.verification_of_repair_task_id);
}

function repairSummary(report) {
  const stored = report?.repair_summary;
  if (stored && typeof stored === 'object') {
    return {
      actionCount: Number(stored.action_count || 0),
      changed: Number(stored.changed_records || 0),
      skipped: Number(stored.skipped_records || 0),
      failed: Number(stored.failed_records || 0)
    };
  }

  const actions = report?.actions || {};
  const workflow = actions?.['workflow.tasks'] || {};
  const references = actions?.['database.references'] || {};
  const provenance = actions?.['imports.provenance'] || {};
  const backfill = workflow?.backfill_task_completed_at || {};
  const notifications = workflow?.complete_terminal_task_notification || {};
  const stale = workflow?.recover_stale_task || {};
  const orphan = references?.archive_orphan_transcript || {};
  const provenanceChanged = Object.values(provenance).reduce((total, value) => total + (Number(value) || 0), 0);

  return {
    actionCount: arrayOf(report?.selected_repair_actions).length,
    changed: provenanceChanged
      + Number(backfill.backfilled || 0)
      + Number(notifications.completed || 0)
      + Number(stale.recovered_count || 0)
      + Number(orphan.archived || 0),
    skipped: Number(backfill.already_completed || 0)
      + Number(notifications.already_completed || 0)
      + Number(stale.skipped_external || 0)
      + Number(orphan.already_archived || 0),
    failed: 0
  };
}

function repairActionLabel(action, t) {
  const labels = {
    remove_false_manual_sunoapi_import_marker: t('audit.repairs.actions.provenance', 'Falsche Import-Provenienz entfernt'),
    recover_stale_task: t('audit.repairs.actions.staleTasks', 'Hängende Tasks abgeschlossen'),
    backfill_task_completed_at: t('audit.repairs.actions.completedAt', 'Fehlende Task-Abschlusszeiten ergänzt'),
    complete_terminal_task_notification: t('audit.repairs.actions.notifications', 'Fortschrittsmeldungen abgeschlossen'),
    archive_orphan_transcript: t('audit.repairs.actions.orphanTranscripts', 'Verwaiste Transcripts archiviert')
  };
  return labels[action] || action;
}

function repairActionResult(report, action) {
  const actions = report?.actions || {};
  if (action === 'remove_false_manual_sunoapi_import_marker') return actions?.['imports.provenance'] || {};
  if (action === 'archive_orphan_transcript') return actions?.['database.references']?.archive_orphan_transcript || {};
  return actions?.['workflow.tasks']?.[action] || {};
}

function findingGuidance(finding, t) {
  if (finding?.code === 'TRUSTED_HOSTS_WILDCARD') {
    return {
      title: t('audit.guidance.trustedHosts.title', 'Empfohlene Konfiguration'),
      text: t('audit.guidance.trustedHosts.text', 'Ersetze den Wildcard-Wert durch die tatsächlich verwendeten Hostnamen. Für eine rein lokale Installation reichen üblicherweise localhost und 127.0.0.1; bei Reverse Proxy oder Domain müssen deren Hostnamen ergänzt werden.'),
      source: t('audit.guidance.trustedHosts.source', 'Konfigurationsquelle: .env / TRUSTED_HOSTS'),
      example: 'TRUSTED_HOSTS=localhost,127.0.0.1'
    };
  }
  return null;
}

function runKindLabel(run, t) {
  if (isRepairRun(run)) return t('audit.run.repair', 'Reparatur');
  if (isVerificationRun(run)) return t('audit.run.verification', 'Verifikation');
  return t('audit.run.audit', 'Audit');
}

function runHistorySummary(run, t) {
  const report = run?.result_payload || {};
  if (isRepairRun(run)) {
    const summary = repairSummary(report);
    return `${summary.changed} ${t('audit.repairs.corrected', 'korrigiert')} · ${summary.actionCount} ${t('audit.repairs.actionCount', 'Aktionen')}`;
  }
  return `${problemTypeCount(report)} ${t('audit.stats.problemTypes', 'Problemtypen')} · ${Number(report?.finding_count || 0)} ${t('audit.stats.affectedRecords', 'Datensätze')}`;
}

export function AuditPage({ notify, onReload }) {
  const { t } = useI18n();
  const [checks, setChecks] = useState([]);
  const [runs, setRuns] = useState([]);
  const [selected, setSelected] = useState(() => new Set());
  const [currentRun, setCurrentRun] = useState(null);
  const [loading, setLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [applying, setApplying] = useState(false);
  const [severityFilter, setSeverityFilter] = useState('all');
  const [expandedCheck, setExpandedCheck] = useState(null);
  const [selectedGroup, setSelectedGroup] = useState(null);
  const [groupSearch, setGroupSearch] = useState('');
  const [groupPage, setGroupPage] = useState(1);
  const [selectedRepairActions, setSelectedRepairActions] = useState(() => new Set());
  const [repairConfirmOpen, setRepairConfirmOpen] = useState(false);
  const [repairConfirmText, setRepairConfirmText] = useState('');
  const [repairConfirmError, setRepairConfirmError] = useState('');
  const pollRef = useRef(null);

  async function load({ silent = false } = {}) {
    setLoading(true);
    try {
      const [checkResult, runResult] = await Promise.all([api.audit.checks(), api.audit.runs(40)]);
      const nextChecks = arrayOf(checkResult);
      setChecks(nextChecks);
      setSelected((current) => {
        if (current.size) return current;
        return new Set(nextChecks.filter((item) => item.default_selected).map((item) => item.id));
      });
      const nextRuns = arrayOf(runResult);
      setRuns(nextRuns);
      if (!currentRun && nextRuns[0]) {
        const fullLatest = await api.audit.run(nextRuns[0].id).catch(() => nextRuns[0]);
        setCurrentRun(fullLatest);
      }
      if (!silent) notify?.(t('audit.messages.updated', 'Audit-Übersicht aktualisiert.'), 'success');
    } catch (err) {
      notify?.(err?.message || t('audit.messages.loadFailed', 'Audit-Übersicht konnte nicht geladen werden.'), 'error');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load({ silent: true }); }, []);

  useEffect(() => {
    setSelectedGroup(null);
    setGroupSearch('');
    setGroupPage(1);
  }, [currentRun?.id]);

  useEffect(() => {
    const id = currentRun?.id;
    if (!id || TERMINAL.has(String(currentRun?.status || '').toUpperCase())) return undefined;
    pollRef.current = window.setInterval(async () => {
      try {
        const next = await api.audit.run(id);
        setCurrentRun(next);
        if (TERMINAL.has(String(next?.status || '').toUpperCase())) {
          window.clearInterval(pollRef.current);
          await load({ silent: true });
          await onReload?.({ silent: true });
        }
      } catch {
        // Die globale Task-/Statusanzeige bleibt unabhängig nutzbar.
      }
    }, 1800);
    return () => window.clearInterval(pollRef.current);
  }, [currentRun?.id, currentRun?.status]);

  function toggleCheck(id) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  async function startAudit() {
    if (!selected.size) return notify?.(t('audit.messages.selectCheck', 'Bitte mindestens eine Prüfung auswählen.'), 'warning');
    setStarting(true);
    try {
      const result = await api.audit.start({ check_ids: [...selected], parameters: { max_findings: 1500 } });
      setCurrentRun(result.task || { id: result.task_local_id, status: result.status });
      notify?.(t('audit.messages.started', 'Audit-Dry-Run wurde gestartet.'), 'success');
      await load({ silent: true });
      await onReload?.({ silent: true });
    } catch (err) {
      notify?.(err?.message || t('audit.messages.startFailed', 'Audit konnte nicht gestartet werden.'), 'error');
    } finally {
      setStarting(false);
    }
  }

  async function startVerification() {
    if (!currentRun?.id || !isRepairRun(currentRun) || verifying) return;
    const sourceAuditTaskId = Number(currentRun?.result_payload?.source_audit_task_id || currentRun?.request_payload?.source_audit_task_id || 0);
    if (!sourceAuditTaskId) {
      notify?.(t('audit.messages.verificationSourceMissing', 'Das Ausgangsaudit der Reparatur konnte nicht bestimmt werden.'), 'error');
      return;
    }

    setVerifying(true);
    try {
      const sourceAudit = await api.audit.run(sourceAuditTaskId);
      const sourceReport = sourceAudit?.result_payload || {};
      const sourceRequest = sourceAudit?.request_payload || {};
      const checkIds = arrayOf(sourceReport?.check_ids).length ? sourceReport.check_ids : arrayOf(sourceRequest?.check_ids);
      if (!checkIds.length) throw new Error(t('audit.messages.verificationChecksMissing', 'Die ursprünglichen Prüfungen konnten nicht geladen werden.'));
      const parameters = {
        ...(sourceReport?.parameters || sourceRequest?.parameters || {}),
        verification_of_repair_task_id: currentRun.id,
        source_audit_task_id: sourceAuditTaskId
      };
      const result = await api.audit.start({ check_ids: checkIds, parameters });
      const nextTask = result.task || { id: result.task_local_id, status: result.status, task_type: 'maintenance_audit', request_payload: { parameters } };
      setCurrentRun(nextTask);
      setRuns((current) => [nextTask, ...current.filter((item) => item.id !== nextTask.id)]);
      notify?.(t('audit.messages.verificationStarted', 'Verifikationsprüfung wurde gestartet.'), 'success');
      await onReload?.({ silent: true });
    } catch (err) {
      notify?.(err?.message || t('audit.messages.verificationFailed', 'Verifikationsprüfung konnte nicht gestartet werden.'), 'error');
    } finally {
      setVerifying(false);
    }
  }

  function openRepairConfirmation() {
    if (!currentRun?.id) return;
    const activeReport = currentRun?.result_payload || {};
    if (!Number(activeReport?.repairable_count || 0)) return;
    if (!selectedRepairActions.size) {
      notify?.(t('audit.messages.selectRepair', 'Bitte mindestens eine Reparatur auswählen.'), 'warning');
      return;
    }
    setRepairConfirmText('');
    setRepairConfirmError('');
    setRepairConfirmOpen(true);
  }

  function closeRepairConfirmation() {
    if (applying) return;
    setRepairConfirmOpen(false);
    setRepairConfirmText('');
    setRepairConfirmError('');
  }

  async function applyRepairs(event) {
    event?.preventDefault?.();
    if (!currentRun?.id || applying) return;
    const normalizedConfirmation = repairConfirmText.trim().toUpperCase();
    if (normalizedConfirmation !== REPAIR_CONFIRMATION_TEXT) {
      const message = t('audit.messages.confirmRepairMismatch', 'Der Bestätigungstext ist nicht korrekt. Gib exakt „REPARATUR ANWENDEN“ ein.');
      setRepairConfirmError(message);
      notify?.(message, 'warning');
      return;
    }

    setApplying(true);
    setRepairConfirmError('');
    try {
      const result = await api.audit.apply(currentRun.id, normalizedConfirmation, [...selectedRepairActions]);
      const nextTask = result.task || { id: result.task_local_id, status: result.status, task_type: 'maintenance_repair' };
      setCurrentRun(nextTask);
      setRuns((current) => [nextTask, ...current.filter((item) => item.id !== nextTask.id)]);
      setRepairConfirmOpen(false);
      setRepairConfirmText('');
      notify?.(t('audit.messages.repairStarted', 'Kontrollierte Reparatur wurde gestartet.'), 'warning');
      await onReload?.({ silent: true });
    } catch (err) {
      const message = err?.message || t('audit.messages.repairFailed', 'Reparatur konnte nicht gestartet werden.');
      setRepairConfirmError(message);
      notify?.(message, 'error');
    } finally {
      setApplying(false);
    }
  }

  async function cancelRun() {
    if (!currentRun?.id) return;
    try {
      const result = await api.audit.cancel(currentRun.id);
      setCurrentRun(result.task);
      notify?.(t('audit.messages.cancelRequested', 'Abbruch wurde angefordert.'), 'warning');
    } catch (err) {
      notify?.(err?.message || t('audit.messages.cancelFailed', 'Audit konnte nicht abgebrochen werden.'), 'error');
    }
  }

  async function openRun(id) {
    try {
      setCurrentRun(await api.audit.run(id));
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
      notify?.(err?.message || t('audit.messages.runLoadFailed', 'Audit-Lauf konnte nicht geladen werden.'), 'error');
    }
  }

  function openFindingGroup(group) {
    setSelectedGroup(group);
    setGroupSearch('');
    setGroupPage(1);
  }

  function toggleRepairGroup(group) {
    setSelectedRepairActions((current) => {
      const next = new Set(current);
      const actions = group?.repairActions || [];
      const allSelected = actions.length > 0 && actions.every((action) => next.has(action));
      for (const action of actions) {
        if (allSelected) next.delete(action); else next.add(action);
      }
      return next;
    });
  }

  const report = currentRun?.result_payload || {};
  const progress = currentRun?.response_payload?.progress || {};
  const repairRun = isRepairRun(currentRun);
  const verificationRun = isVerificationRun(currentRun);
  const currentRepairSummary = useMemo(() => repairSummary(report), [report]);
  const currentRepairActions = arrayOf(report?.selected_repair_actions);
  const sourceAuditTaskId = Number(report?.source_audit_task_id || currentRun?.request_payload?.source_audit_task_id || 0);
  const results = arrayOf(report, 'results');
  const allProblemGroups = useMemo(() => buildFindingGroups(results), [results]);
  const visibleProblemGroups = useMemo(
    () => allProblemGroups.filter((group) => severityFilter === 'all' || group.severity === severityFilter),
    [allProblemGroups, severityFilter]
  );
  const visibleFindingCount = useMemo(
    () => visibleProblemGroups.reduce((total, group) => total + group.findings.length, 0),
    [visibleProblemGroups]
  );
  const availableRepairActions = useMemo(() => {
    const values = [];
    for (const group of allProblemGroups) {
      for (const action of group.repairActions || []) {
        if (!values.includes(action)) values.push(action);
      }
    }
    return values;
  }, [allProblemGroups]);
  const selectedGroupFindings = useMemo(() => {
    const values = selectedGroup?.findings || [];
    const query = groupSearch.trim().toLowerCase();
    if (!query) return values;
    return values.filter((finding) => {
      const haystack = [
        finding?.code,
        finding?.title,
        finding?.message,
        finding?.entity_type,
        finding?.entity_id,
        JSON.stringify(finding?.details || {})
      ].filter(Boolean).join(' ').toLowerCase();
      return haystack.includes(query);
    });
  }, [selectedGroup, groupSearch]);
  const groupPageCount = Math.max(1, Math.ceil(selectedGroupFindings.length / GROUP_PAGE_SIZE));
  const normalizedGroupPage = Math.min(groupPage, groupPageCount);
  const pagedGroupFindings = selectedGroupFindings.slice((normalizedGroupPage - 1) * GROUP_PAGE_SIZE, normalizedGroupPage * GROUP_PAGE_SIZE);
  const selectedGroupCount = selectedGroup?.findings?.length || 0;
  const compactFindingsModal = selectedGroupCount > 0 && selectedGroupCount <= 5;
  const showGroupSearch = selectedGroupCount >= 10;
  const showGroupPagination = selectedGroupFindings.length > GROUP_PAGE_SIZE;
  const running = currentRun && !TERMINAL.has(String(currentRun.status || '').toUpperCase());
  const counts = report?.counts || {};

  useEffect(() => {
    if (groupPage > groupPageCount) setGroupPage(groupPageCount);
  }, [groupPage, groupPageCount]);

  useEffect(() => {
    setSelectedRepairActions(new Set(availableRepairActions));
  }, [currentRun?.id, report?.fingerprint]);

  return (
    <section className="page audit-page">
      <SectionHeader
        eyebrow={t('audit.eyebrow', 'Kontrolle')}
        title={t('audit.title', 'Audit & Wartung')}
        text={t('audit.intro', 'Manuelle, nachvollziehbare System-, Daten- und Medienprüfungen. Reparaturen starten niemals ohne Dry-Run und ausdrückliche Bestätigung.')}
        actions={<button type="button" onClick={() => load()} disabled={loading}><RefreshCw size={16} className={loading ? 'spin-icon' : ''} /> {t('common.refresh', 'Aktualisieren')}</button>}
      />

      <div className="audit-layout">
        <section className="audit-catalog panel-card">
          <div className="audit-section-heading">
            <div><span className="eyebrow">{t('audit.catalog.eyebrow', 'Prüfkatalog')}</span><h3>{t('audit.catalog.title', 'Prüfungen auswählen')}</h3></div>
            <button className="primary" type="button" onClick={startAudit} disabled={starting || running || !selected.size}><Play size={16} /> {starting ? t('audit.actions.starting', 'Startet…') : t('audit.actions.start', 'Dry-Run starten')}</button>
          </div>
          <div className="audit-check-grid">
            {checks.map((check) => (
              <label className={`audit-check-card ${selected.has(check.id) ? 'selected' : ''}`} key={check.id}>
                <input type="checkbox" checked={selected.has(check.id)} onChange={() => toggleCheck(check.id)} />
                <div className="audit-check-icon">{check.category === 'database' ? <Database size={18} /> : check.category === 'storage' ? <FileWarning size={18} /> : <ShieldCheck size={18} />}</div>
                <div className="audit-check-body"><strong>{check.title}</strong><p>{check.description}</p><div className="audit-check-meta"><span className={`severity-chip ${check.priority}`}>{severityLabel(check.priority, t)}</span><span>{t('audit.catalog.duration', 'Dauer')}: {check.estimated_duration}</span>{check.supports_repair && <span><Wrench size={12} /> {t('audit.catalog.repairable', 'Reparaturfähig')}</span>}</div></div>
              </label>
            ))}
          </div>
        </section>

        <section className="audit-run panel-card">
          <div className="audit-section-heading">
            <div><span className="eyebrow">{t('audit.run.eyebrow', 'Aktueller Lauf')}</span><h3>{currentRun ? `#${currentRun.id} · ${runKindLabel(currentRun, t)}` : t('audit.run.none', 'Noch kein Lauf ausgewählt')}</h3></div>
            <div className="audit-run-actions">
              {report && Object.keys(report).length > 0 && <button type="button" onClick={() => saveJson(report, `audit_run_${currentRun.id}.json`)}><Download size={15} /> JSON</button>}
              {!running && repairRun && sourceAuditTaskId > 0 && <button type="button" onClick={() => openRun(sourceAuditTaskId)}><ShieldCheck size={15} /> {t('audit.actions.openSourceAudit', 'Ausgangsaudit öffnen')}</button>}
              {running && <button type="button" onClick={cancelRun}><Square size={14} /> {t('common.cancel', 'Abbrechen')}</button>}
              {!running && currentRun?.task_type === 'maintenance_audit' && Number(report?.repairable_count || 0) > 0 && <button className="danger-soft" type="button" onClick={openRepairConfirmation} disabled={applying || !selectedRepairActions.size}><Wrench size={15} /> {applying ? t('audit.actions.applying', 'Startet…') : `${t('audit.actions.applySelected', 'Ausgewählte reparieren')} (${selectedRepairActions.size})`}</button>}
            </div>
          </div>

          {!currentRun ? <div className="empty-state compact">{t('audit.run.selectHint', 'Starte einen Dry-Run oder öffne einen früheren Lauf.')}</div> : <>
            <div className="audit-progress-card">
              <div className={`audit-status ${statusClass(currentRun.status)}`}>{running ? <RefreshCw size={15} className="spin-icon" /> : String(currentRun.status).toUpperCase() === 'SUCCESS' ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />} {currentRun.status}</div>
              <div className="audit-progress-track"><span style={{ width: `${Math.max(0, Math.min(100, Number(progress.percent ?? (running ? 5 : 100))))}%` }} /></div>
              <div className="audit-progress-meta"><span>{progress.phase || t('audit.run.waiting', 'Wartet auf Ergebnis')}</span><span>{formatDate(currentRun.updated_at)}</span></div>
              {currentRun.error_message && <p className="audit-error-text">{currentRun.error_message}</p>}
            </div>

            {Object.keys(report).length > 0 && (repairRun ? <>
              <section className="audit-repair-result" aria-labelledby="audit-repair-result-title">
                <div className="audit-repair-result-heading">
                  <div>
                    <span className="eyebrow">{t('audit.repairs.resultEyebrow', 'Reparaturergebnis')}</span>
                    <h3 id="audit-repair-result-title">{String(currentRun.status || '').toUpperCase() === 'SUCCESS' ? t('audit.repairs.successTitle', 'Reparatur erfolgreich') : t('audit.repairs.resultTitle', 'Reparaturlauf')}</h3>
                    <p>{t('audit.repairs.resultHint', 'Diese Angaben beschreiben ausschließlich die angewendeten Änderungen. Sie sind kein erneuter Gesamt-Audit.')}</p>
                  </div>
                  {sourceAuditTaskId > 0 && <div className="audit-repair-source">{t('audit.repairs.sourceAudit', 'Ausgangsaudit')} <strong>#{sourceAuditTaskId}</strong></div>}
                </div>

                <div className="audit-repair-stat-grid">
                  <div className="success"><strong>{currentRepairSummary.changed}</strong><span>{t('audit.repairs.correctedRecords', 'korrigierte Datensätze')}</span></div>
                  <div><strong>{currentRepairSummary.actionCount}</strong><span>{t('audit.repairs.appliedActions', 'angewendete Aktionen')}</span></div>
                  <div><strong>{currentRepairSummary.skipped}</strong><span>{t('audit.repairs.skippedRecords', 'übersprungen')}</span></div>
                  <div className={currentRepairSummary.failed ? 'failed' : ''}><strong>{currentRepairSummary.failed}</strong><span>{t('audit.repairs.failedRecords', 'fehlgeschlagen')}</span></div>
                </div>

                <div className="audit-repair-action-list">
                  {currentRepairActions.length === 0 ? <div className="empty-state compact">{t('audit.repairs.noActions', 'Für diesen Reparaturlauf wurden keine Aktionsdetails gespeichert.')}</div> : currentRepairActions.map((action) => (
                    <article className="audit-repair-action-card" key={action}>
                      <div>
                        <CheckCircle2 size={17} />
                        <strong>{repairActionLabel(action, t)}</strong>
                      </div>
                      <details>
                        <summary>{t('audit.repairs.actionDetails', 'Ergebnisdetails')}</summary>
                        <pre>{JSON.stringify(repairActionResult(report, action), null, 2)}</pre>
                      </details>
                    </article>
                  ))}
                </div>

                <div className="audit-repair-metadata">
                  <div><span>{t('audit.repairs.backup', 'Datenbank-Backup')}</span><code>{report.backup_path || '—'}</code></div>
                  <div><span>{t('audit.repairs.report', 'Reparaturreport')}</span><code>{report.report_path || '—'}</code></div>
                </div>

                {String(currentRun.status || '').toUpperCase() === 'SUCCESS' && <div className="audit-verification-callout">
                  <ShieldCheck size={20} />
                  <div>
                    <strong>{t('audit.repairs.verifyTitle', 'Änderungen verifizieren')}</strong>
                    <p>{t('audit.repairs.verifyHint', 'Starte dieselben Prüfungen erneut, um verbleibende Befunde nach der Reparatur zu ermitteln.')}</p>
                  </div>
                  <button className="primary" type="button" onClick={startVerification} disabled={verifying}><RefreshCw size={15} className={verifying ? 'spin-icon' : ''} /> {verifying ? t('audit.actions.verifying', 'Startet…') : t('audit.actions.verify', 'Ergebnis erneut prüfen')}</button>
                </div>}
              </section>
            </> : <>
              {verificationRun && <div className="audit-verification-banner"><ShieldCheck size={17} /><div><strong>{t('audit.run.verification', 'Verifikation')}</strong><span>{t('audit.run.verificationHint', 'Dieser Dry-Run prüft den Zustand nach einer Reparatur erneut.')}</span></div></div>}

              <div className="audit-stat-grid">
                <button type="button" className={severityFilter === 'all' ? 'active' : ''} onClick={() => setSeverityFilter('all')}><strong>{visibleProblemGroups.length}</strong><span>{t('audit.stats.problemTypes', 'Problemtypen')}</span></button>
                <div><strong>{visibleFindingCount}</strong><span>{t('audit.stats.affectedRecords', 'betroffene Datensätze')}</span></div>
                {SEVERITIES.map((level) => <button type="button" key={level} className={`${level} ${severityFilter === level ? 'active' : ''}`} onClick={() => setSeverityFilter(level)}><strong>{Number(counts[level] || 0)}</strong><span>{severityLabel(level, t)}</span></button>)}
                <div><strong>{Number(report.repairable_count || 0)}</strong><span>{t('audit.stats.repairable', 'reparierbar')}</span></div>
              </div>

              {availableRepairActions.length > 0 && <div className="audit-repair-selection-summary">
                <div><Wrench size={15} /><strong>{t('audit.repairs.title', 'Reparaturauswahl')}</strong><span>{selectedRepairActions.size} / {availableRepairActions.length} {t('audit.repairs.selected', 'Problemgruppen ausgewählt')}</span></div>
                <button type="button" onClick={() => setSelectedRepairActions(new Set(availableRepairActions))}>{t('audit.repairs.selectAll', 'Alle auswählen')}</button>
                <button type="button" onClick={() => setSelectedRepairActions(new Set())}>{t('audit.repairs.clear', 'Auswahl aufheben')}</button>
              </div>}

              <div className="audit-result-groups">
                {results.map((result) => (
                  <article className={`audit-result-card severity-${result.max_severity || 'info'}`} key={result.check_id}>
                    <button type="button" className="audit-result-header" onClick={() => setExpandedCheck((current) => current === result.check_id ? null : result.check_id)}>
                      <div><strong>{result.title}</strong><span>{result.finding_count} {t('audit.stats.affectedRecords', 'betroffene Datensätze')} · {severityLabel(result.max_severity || 'info', t)}</span></div>
                      <span>{expandedCheck === result.check_id ? '−' : '+'}</span>
                    </button>
                    {expandedCheck === result.check_id && <pre className="audit-summary-pre">{JSON.stringify(result.summary || {}, null, 2)}</pre>}
                  </article>
                ))}
              </div>

              <section className="audit-problem-section" aria-labelledby="audit-problem-groups-title">
                <div className="audit-problem-section-heading">
                  <div>
                    <span className="eyebrow">{t('audit.groups.eyebrow', 'Verdichtete Ergebnisse')}</span>
                    <h3 id="audit-problem-groups-title">{t('audit.groups.title', 'Problemgruppen')}</h3>
                    <p>{t('audit.groups.hint', 'Gleiche Befunde werden zusammengefasst. Einzelne Datensätze und technische Details erscheinen erst nach dem Öffnen einer Gruppe.')}</p>
                  </div>
                  <div className="audit-problem-filter-summary">{visibleProblemGroups.length} {t('audit.stats.problemTypes', 'Problemtypen')} · {visibleFindingCount} {t('audit.stats.affectedRecords', 'betroffene Datensätze')}</div>
                </div>

                <div className="audit-problem-groups">
                  {visibleProblemGroups.length === 0 ? <div className="empty-state compact">{t('audit.findings.none', 'Für diesen Filter liegen keine Befunde vor.')}</div> : visibleProblemGroups.map((group) => {
                    const statusBreakdown = findingStatusBreakdown(group.findings);
                    const examples = group.findings.slice(0, 3);
                    return (
                      <article className={`audit-problem-group severity-${group.severity}`} key={group.key}>
                        <div className="audit-problem-group-main">
                          <div className="audit-problem-group-title-row">
                            {group.repairActions.length > 0 && <label className="audit-repair-group-toggle">
                              <input
                                type="checkbox"
                                checked={group.repairActions.every((action) => selectedRepairActions.has(action))}
                                onChange={() => toggleRepairGroup(group)}
                              />
                              <span>{t('audit.repairs.include', 'Reparieren')}</span>
                            </label>}
                            <span className={`severity-chip ${group.severity}`}>{severityLabel(group.severity, t)}</span>
                            <code>{group.code}</code>
                            {group.repairableCount > 0 && <span className="repairable-label"><Wrench size={12} /> {group.repairableCount} {t('audit.catalog.repairable', 'Reparaturfähig')}</span>}
                          </div>
                          <h4>{group.title}</h4>
                          <p className="audit-problem-check-name">{group.checkTitle}</p>
                          {statusBreakdown.length > 0 && <div className="audit-problem-facets">{statusBreakdown.map(([status, count]) => <span key={status}>{status}: {count}</span>)}</div>}
                          <div className="audit-problem-examples">
                            {examples.map((finding, index) => (
                              <div className="audit-problem-example" key={`${finding.entity_type}-${finding.entity_id}-${index}`}>
                                <strong>{findingEntityLabel(finding) || t('audit.groups.example', 'Beispiel')}</strong>
                                <span>{finding.message}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                        <div className="audit-problem-group-side">
                          <div className="audit-problem-count"><strong>{group.findings.length}</strong><span>{t('audit.groups.affected', 'betroffen')}</span></div>
                          <button type="button" onClick={() => openFindingGroup(group)}>{group.findings.length > 1 ? t('audit.groups.showAll', 'Alle anzeigen') : t('audit.groups.showDetails', 'Details anzeigen')}</button>
                        </div>
                      </article>
                    );
                  })}
                </div>
              </section>
            </>)}
          </>}
        </section>

        <section className="audit-history panel-card">
          <div className="audit-section-heading"><div><span className="eyebrow">{t('audit.history.eyebrow', 'Historie')}</span><h3>{t('audit.history.title', 'Letzte Audit- und Reparaturläufe')}</h3></div></div>
          <div className="audit-history-list">
            {runs.length === 0 ? <div className="empty-state compact">{t('audit.history.empty', 'Noch keine Audit-Läufe vorhanden.')}</div> : runs.map((run) => (
              <button type="button" className={`audit-history-row ${currentRun?.id === run.id ? 'active' : ''}`} key={run.id} onClick={() => openRun(run.id)}>
                <span className={`audit-status-dot ${statusClass(run.status)}`} />
                <div><strong>#{run.id} · {runKindLabel(run, t)}</strong><small>{formatDate(run.created_at)}</small></div>
                <span>{run.status}</span>
                <span>{runHistorySummary(run, t)}</span>
              </button>
            ))}
          </div>
        </section>
      </div>


      <Modal
        open={repairConfirmOpen}
        title={t('audit.repairs.confirmTitle', 'Reparatur bestätigen')}
        onClose={closeRepairConfirmation}
        cardClassName="audit-repair-confirm-modal"
        contentClassName="audit-repair-confirm-content"
      >
        <form className="audit-repair-confirm-form" onSubmit={applyRepairs}>
          <div className="audit-repair-confirm-warning">
            <AlertTriangle size={20} />
            <div>
              <strong>{t('audit.repairs.confirmWarningTitle', 'Kontrollierte Datenänderung')}</strong>
              <p>{t('audit.messages.confirmRepairPrompt', 'Die Reparatur erzeugt vorher ein Datenbank-Backup und prüft den Dry-Run erneut. Gib exakt „REPARATUR ANWENDEN“ ein:')}</p>
            </div>
          </div>

          <div className="audit-repair-confirm-summary">
            <span>{t('audit.repairs.selectedActions', 'Ausgewählte Reparaturaktionen')}</span>
            <strong>{selectedRepairActions.size}</strong>
          </div>

          <label className="audit-repair-confirm-field">
            <span>{t('audit.repairs.confirmLabel', 'Bestätigungstext')}</span>
            <code>{REPAIR_CONFIRMATION_TEXT}</code>
            <input
              type="text"
              value={repairConfirmText}
              onChange={(event) => { setRepairConfirmText(event.target.value); setRepairConfirmError(''); }}
              autoFocus
              autoComplete="off"
              spellCheck={false}
              aria-invalid={Boolean(repairConfirmError)}
              aria-describedby={repairConfirmError ? 'audit-repair-confirm-error' : undefined}
              disabled={applying}
            />
          </label>

          {repairConfirmError && <p id="audit-repair-confirm-error" className="audit-repair-confirm-error" role="alert">{repairConfirmError}</p>}

          <div className="audit-repair-confirm-actions">
            <button type="button" onClick={closeRepairConfirmation} disabled={applying}>{t('common.cancel', 'Abbrechen')}</button>
            <button className="danger-soft" type="submit" disabled={applying || !repairConfirmText.trim()}>
              <Wrench size={15} />
              {applying ? t('audit.actions.applying', 'Startet…') : t('audit.actions.applySelected', 'Ausgewählte reparieren')}
            </button>
          </div>
        </form>
      </Modal>

      <Modal
        open={Boolean(selectedGroup)}
        title={selectedGroup ? `${selectedGroup.title} · ${selectedGroup.findings.length} ${t('audit.groups.affected', 'betroffen')}` : ''}
        onClose={() => setSelectedGroup(null)}
        wide={!compactFindingsModal}
        cardClassName={`audit-findings-modal ${compactFindingsModal ? 'compact' : ''}`}
        contentClassName="audit-findings-modal-content"
      >
        {selectedGroup && <>
          {(showGroupSearch || selectedGroupCount > 1) && <div className="audit-modal-toolbar">
            {showGroupSearch && <label className="audit-modal-search">
                <Search size={16} />
                <input
                  type="search"
                  value={groupSearch}
                  onChange={(event) => { setGroupSearch(event.target.value); setGroupPage(1); }}
                  placeholder={t('audit.groups.searchPlaceholder', 'Task-ID, Audio-ID, Nachricht oder Detail suchen…')}
                />
              </label>}
            <div className="audit-modal-count">{selectedGroupFindings.length} {t('audit.stats.affectedRecords', 'betroffene Datensätze')}</div>
          </div>}

          <div className="audit-modal-finding-list">
            {pagedGroupFindings.length === 0 ? <div className="empty-state compact">{t('audit.groups.searchEmpty', 'Keine passenden Datensätze gefunden.')}</div> : pagedGroupFindings.map((finding, index) => (
              <article className={`audit-modal-finding severity-${finding.severity || 'info'}`} key={`${finding.code}-${finding.entity_type}-${finding.entity_id}-${index}`}>
                <div className="audit-modal-finding-header">
                  <div>
                    <div className="audit-modal-finding-meta"><span className={`severity-chip ${finding.severity || 'info'}`}>{severityLabel(finding.severity || 'info', t)}</span><code>{finding.code}</code></div>
                    <strong>{findingEntityLabel(finding) || finding.title}</strong>
                    <span>{finding.message}</span>
                  </div>
                  {finding.repairable && <span className="repairable-label"><Wrench size={12} /> {t('audit.catalog.repairable', 'Reparaturfähig')}</span>}
                </div>
                {findingGuidance(finding, t) && <div className="audit-finding-guidance">
                  <ShieldCheck size={18} />
                  <div>
                    <strong>{findingGuidance(finding, t).title}</strong>
                    <p>{findingGuidance(finding, t).text}</p>
                    <span>{findingGuidance(finding, t).source}</span>
                    <code>{findingGuidance(finding, t).example}</code>
                  </div>
                </div>}
                {finding.details && Object.keys(finding.details).length > 0 && <details><summary>{t('audit.findings.details', 'Technische Details')}</summary><pre>{JSON.stringify(finding.details, null, 2)}</pre></details>}
              </article>
            ))}
          </div>

          {showGroupPagination && <div className="audit-modal-pagination">
            <button type="button" onClick={() => setGroupPage((value) => Math.max(1, value - 1))} disabled={normalizedGroupPage <= 1}><ChevronLeft size={16} /> {t('common.previous', 'Zurück')}</button>
            <span>{t('audit.groups.page', 'Seite')} {normalizedGroupPage} / {groupPageCount}</span>
            <button type="button" onClick={() => setGroupPage((value) => Math.min(groupPageCount, value + 1))} disabled={normalizedGroupPage >= groupPageCount}>{t('common.next', 'Weiter')} <ChevronRight size={16} /></button>
          </div>}
        </>}
      </Modal>
    </section>
  );
}
