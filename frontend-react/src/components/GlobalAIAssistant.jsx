import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Bot, Check, ChevronDown, ChevronUp, Cpu, Loader2, MessageCircle, Send, Sparkles, Trash2, X } from 'lucide-react';
import { api } from '../api/client.js';
import { FormattedMessage } from './FormattedMessage.jsx';
import { useAppAssistant } from '../context/AppAssistantContext.jsx';
import { useI18n } from '../i18n/I18nContext.jsx';

function shortCanvas(text, t = null) {
  const value = String(text || '');
  if (value.length <= 900) return value;
  return `${value.slice(0, 900)}\n\n${t?.('globalAi.truncatedCanvas', '… gekürzt ({{count}} Zeichen insgesamt)', { count: value.length }) || `… gekürzt (${value.length} Zeichen insgesamt)`}`;
}


function looksLikeCanvasCommand(text, context = {}) {
  const value = String(text || '').toLowerCase();
  if (!value.trim()) return false;
  const isLyricsArea = String(context?.active_tab || '') === 'lyrics';
  const hasCanvas = String(context?.current_canvas || '').trim().length > 0;
  const createIntent = /(erstelle|erstellen|schreib|schreibe|generiere|bau|baue).*(songtext|lyrics|hook|refrain|strophe|verse|instrumental|bauplan)/.test(value);
  const editIntent = /(suno-ready|suno ready|überarbeite|ueberarbeite|verbessere|ändere|aendere|ersetze|mach die hook|mach den text|mach den songtext|formatiere|vocal tags|doubletime)/.test(value);
  return createIntent || (isLyricsArea && hasCanvas && editIntent);
}

function isCanvasAction(actionId, action = null) {
  const id = String(actionId || '');
  if (!id.startsWith('lyrics_')) return false;
  if (['lyrics_save', 'lyrics_apply_preview', 'lyrics_discard_preview'].includes(id)) return false;
  return action?.type === 'ai_canvas' || true;
}

function looksLikeAudioCommand(text) {
  const value = String(text || '').toLowerCase();
  return /(schneide|trimme|fade|normalis|master|lauter|leiser|short|cut|daw|audio bearbeiten)/.test(value);
}

function looksLikeSrtCommand(text) {
  const value = String(text || '').toLowerCase();
  return /(srt|untertitel|subtitle|segment|timing|zeitstempel)/.test(value);
}

function wantsNewSrtSegment(text) {
  const value = String(text || '').toLowerCase();
  return /(segment).*(hinzuf|neu|ergänz|add)|(?:hinzuf|neu|ergänz|add).*(segment)/.test(value);
}

function parseSrtDelta(text, fallback = 5) {
  const match = String(text || '').replace(',', '.').match(/([+-]?\d+(?:\.\d+)?)\s*(?:s|sek|sekunden|seconds)?/i);
  const value = match ? Number(match[1]) : fallback;
  return Number.isFinite(value) ? value : fallback;
}

function wantsSrtShift(text) {
  const value = String(text || '').toLowerCase();
  return /(ab hier|ab segment|folgende|alle folgenden|verschieb|ripple)/.test(value);
}

function wantsSrtExtend(text) {
  const value = String(text || '').toLowerCase();
  return /(verlänger|verlaenger|länger|laenger|ende.*später|endzeit.*später)/.test(value);
}

function describeDawPlan(plan, t = null) {
  const operations = Array.isArray(plan?.operations) ? plan.operations : [];
  if (!operations.length) return t?.('globalAi.dawPlanEmpty', 'Kein Bearbeitungsplan erkannt.') || 'Kein Bearbeitungsplan erkannt.';
  return operations.map((op) => {
    if (op.type === 'trim') return `Trim bis ${Math.round(Number(op.end || 0))}s`;
    if (op.type === 'fade_out') return `Fade-out ${op.duration || 2}s`;
    if (op.type === 'fade_in') return `Fade-in ${op.duration || 1}s`;
    if (op.type === 'gain') return `${t?.('daw.volume', 'Lautstärke') || 'Lautstärke'} ${op.gain_db || 0} dB`;
    if (op.type === 'normalize') return `${t?.('daw.normalize', 'Normalisieren') || 'Normalisieren'} ${op.target_lufs || -14} LUFS`;
    if (op.type === 'preset') return `Preset ${op.preset}`;
    return op.type || 'Operation';
  }).join(' · ');
}

function normalizeAssistantText(value, t = null) {
  const prepared = t?.('globalAi.answerPrepared', 'Ich habe die Antwort vorbereitet.') || 'Ich habe die Antwort vorbereitet.';
  const canvasPrepared = t?.('globalAi.canvasPreparedInStudio', 'Ich habe eine Canvas-Vorschau direkt im Songtext-Studio vorbereitet.') || 'Ich habe eine Canvas-Vorschau direkt im Songtext-Studio vorbereitet.';
  if (value === null || value === undefined) return prepared;
  if (typeof value === 'string') {
    const trimmed = value.trim();
    if (!trimmed) return prepared;
    try {
      const parsed = JSON.parse(trimmed);
      return normalizeAssistantText(parsed, t);
    } catch (_) {
      return trimmed;
    }
  }
  if (typeof value === 'object') {
    const direct = value.assistant_message || value.message || value.reply || value.text || value.summary || value.change_summary;
    if (direct && typeof direct === 'string') return direct.trim();
    if (value.canvas_text || value.proposed_canvas) return canvasPrepared;
    return prepared;
  }
  return String(value || '').trim() || prepared;
}

export function GlobalAIAssistant({ notify }) {
  const { t } = useI18n();
  const assistant = useAppAssistant();
  const [open, setOpen] = useState(false);
  const [minimized, setMinimized] = useState(false);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [chat, setChat] = useState(() => {
    try { return JSON.parse(localStorage.getItem('global-ai-chat') || '[]'); } catch (_) { return []; }
  });
  const [pendingCanvas, setPendingCanvas] = useState(null);
  const [runtimeInfo, setRuntimeInfo] = useState(null);
  const [runtimeError, setRuntimeError] = useState('');
  const [quickPanelCollapsed, setQuickPanelCollapsed] = useState(() => {
    try {
      const saved = localStorage.getItem('global-ai-quick-panel-collapsed');
      if (saved !== null) return saved === 'true';
      return window.matchMedia?.('(max-width: 760px)')?.matches || false;
    } catch (_) {
      return false;
    }
  });
  const logRef = useRef(null);

  useEffect(() => localStorage.setItem('global-ai-chat', JSON.stringify(chat.slice(-40))), [chat]);
  useEffect(() => {
    try { localStorage.setItem('global-ai-quick-panel-collapsed', String(quickPanelCollapsed)); } catch (_) {}
  }, [quickPanelCollapsed]);
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [chat, open, pendingCanvas]);


  async function refreshRuntimeInfo() {
    try {
      const context = assistant.buildAssistantContext();
      const info = await api.assistant.runtime(context?.assistant_profile_id || null);
      setRuntimeInfo(info || null);
      setRuntimeError('');
    } catch (err) {
      setRuntimeInfo(null);
      setRuntimeError(err.message || t('globalAi.runtimeConfigUnreadable', 'KI-Konfiguration nicht lesbar'));
    }
  }

  useEffect(() => {
    if (!open || minimized) return;
    refreshRuntimeInfo();
  }, [open, minimized, assistant?.activeTab, assistant?.pageState]);

  function formatRuntimeLabel(info) {
    if (!info?.provider && !info?.model) return t('globalAi.modelLoading', 'KI-Modell wird geladen …');
    const provider = info?.provider || t('globalAi.providerOpen', 'Provider offen');
    const model = info?.model || t('globalAi.modelOpen', 'Modell offen');
    return `${provider} · ${model}`;
  }

  function formatRuntimeDetail(info) {
    if (!info) return runtimeError || t('globalAi.adminConfigChecking', 'Admin-Konfiguration wird geprüft.');
    const chunks = [];
    if (info.profile_name) chunks.push(t('globalAi.profileName', 'Profil: {{name}}', { name: info.profile_name }));
    else chunks.push(t('globalAi.profileDefaults', 'Profil: Admin-Defaults'));
    if (info.instruction_files_count !== undefined) chunks.push(t('globalAi.promptBlocks', '{{count}} Prompt-Baustein(e)', { count: info.instruction_files_count }));
    if (info.vocal_tags_count !== undefined) chunks.push(t('globalAi.vocalTags', '{{count}} Vocal Tag(s)', { count: info.vocal_tags_count }));
    return chunks.join(' · ');
  }

  useEffect(() => {
    function handleExternalSend(event) {
      setOpen(true);
      const detail = event.detail || {};
      send(detail.message || '', detail.actionId || null);
    }
    window.addEventListener('assistant:send', handleExternalSend);
    return () => window.removeEventListener('assistant:send', handleExternalSend);
  }, [assistant?.activeTab, assistant?.pageState]);

  const pageLabel = assistant?.buildAssistantContext?.()?.page_label || assistant?.activeTab || 'App';
  const pageActions = useMemo(() => assistant?.buildAssistantContext?.()?.available_actions || [], [assistant?.activeTab, assistant?.pageState]);

  async function send(finalMessage = message, actionId = null, options = {}) {
    const clean = String(finalMessage || '').trim();
    if (!clean && !actionId) return;
    const context = assistant.buildAssistantContext();
    const matchingAction = (context?.available_actions || []).find((item) => item?.id === actionId) || null;
    const applyToCanvas = Boolean(options.applyToCanvas ?? (isCanvasAction(actionId, matchingAction) || looksLikeCanvasCommand(clean, context)));
    const requestContext = applyToCanvas
      ? context
      : {
          ...context,
          current_canvas_full_chars: String(context?.current_canvas || '').length,
          current_canvas: shortCanvas(context?.current_canvas || '', t)
        };
    const entryId = Date.now();
    if (clean) setChat((items) => [...items, { id: entryId, role: 'user', text: clean }]);
    setBusy(true);
    try {
      if (looksLikeSrtCommand(clean)) {
        const addSegment = wantsNewSrtSegment(clean);
        const shiftSegments = wantsSrtShift(clean);
        const extendSegment = wantsSrtExtend(clean);
        const seconds = Math.abs(parseSrtDelta(clean, 5));
        const actions = [{ id: 'srt_focus_editor', label: t('globalAi.srtOpenEditor', 'SRT-Editor öffnen') }];
        if (addSegment) actions.unshift({ id: 'srt_add_segment', label: t('globalAi.srtAddSegment', 'Segment jetzt hinzufügen'), payload: { start: context?.current_audio_time || null } });
        if (shiftSegments) actions.unshift({ id: 'srt_shift_from_here', label: t('globalAi.srtShiftFromHere', 'Ab hier um {{seconds}}s verschieben', { seconds }), payload: { seconds, delta: seconds, include_current: true } });
        if (extendSegment) actions.unshift({ id: 'srt_extend_selected', label: t('globalAi.srtExtendSegment', 'Segment um {{seconds}}s verlängern', { seconds }), payload: { seconds, delta: seconds, ripple: true } });
        setChat((items) => [...items, {
          id: entryId + 1,
          role: 'assistant',
          text: shiftSegments || extendSegment
            ? t('globalAi.srtCommandWithSeconds', 'SRT-Befehl erkannt. Ich kann den Editor öffnen und die Aktion mit {{seconds}}s vorbereiten. Bitte kontrolliere die Vorschau vor dem Speichern.', { seconds })
            : addSegment
              ? t('globalAi.srtCommandAddSegment', 'SRT-Befehl erkannt. Ich kann im Songdetail den Segment-Editor öffnen und an der aktuellen Wiedergabezeit ein neues Segment vorbereiten.')
              : t('globalAi.srtCommandOpenEditor', 'SRT-Befehl erkannt. Ich kann den Live-Untertitel-Container und den Segment-Editor im aktuellen Library-Song öffnen.'),
          actions
        }]);
        setMessage('');
        return;
      }
      if (looksLikeAudioCommand(clean)) {
        const dawResult = await api.daw.resolveCommand({ message: clean, execute: false }).catch(() => null);
        if (dawResult?.is_audio_command) {
          const text = dawResult.plan
            ? `${dawResult.message || t('globalAi.audioCommandRecognized', 'Audio-Befehl erkannt.')}

${t('globalAi.plannedDawEdit', 'Geplanter DAW-Eingriff')}: ${describeDawPlan(dawResult.plan, t)}

${t('globalAi.originalUntouchedRenderHint', 'Original bleibt unverändert. Beim Rendern wird eine neue Library-Version erstellt.')}`
            : (dawResult.message || t('globalAi.audioCommandNeedsSelection', 'Audio-Befehl erkannt, aber es fehlt noch eine eindeutige Auswahl.'));
          setChat((items) => [...items, {
            id: entryId + 1,
            role: 'assistant',
            text,
            actions: dawResult.plan ? [
              { id: 'daw_execute_plan', label: t('daw.renderDirectly', 'Direkt rendern'), payload: dawResult.plan },
              { id: 'navigate_daw', label: t('globalAi.openInMiniDaw', 'In Mini-DAW öffnen'), payload: { audio_asset_id: dawResult.asset?.id || dawResult.plan?.source_audio_id } }
            ] : [{ id: 'navigate_daw', label: t('globalAi.openMiniDaw', 'Mini-DAW öffnen') }],
          }]);
          setMessage('');
          return;
        }
      }
      const chatHistory = chat.slice(-12).map((item) => ({
        role: item.role && String(item.role).startsWith('user') ? 'user' : 'assistant',
        content: String(item.text || '')
      })).filter((item) => item.content.trim());
      const response = await api.assistant.chat({
        message: clean,
        action_id: actionId,
        app_context: requestContext,
        profile_id: context?.assistant_profile_id || null,
        apply_to_canvas: applyToCanvas,
        chat_history: chatHistory
      });
      if (response.runtime_info) {
        setRuntimeInfo(response.runtime_info);
        setRuntimeError('');
      }
      let replyText = normalizeAssistantText(response.reply, t);
      const proposed = response.proposed_canvas || null;
      if (proposed) {
        const previewPayload = {
          text: proposed,
          summary: response.change_summary || t('globalAi.previewPrepared', 'KI-Vorschau vorbereitet'),
          createdAt: new Date().toISOString(),
          sourceMessage: clean,
          actionId
        };
        setPendingCanvas(previewPayload);
        await assistant.executeFrontendAction?.('navigate_lyrics');
        window.setTimeout(() => window.dispatchEvent(new CustomEvent('assistant:lyrics-preview', { detail: previewPayload })), 140);
        replyText = replyText && !replyText.includes('canvas_text') ? replyText : t('globalAi.canvasPreparedInStudio', 'Ich habe eine Canvas-Vorschau direkt im Songtext-Studio vorbereitet.');
      }
      const assistantEntry = {
        id: entryId + 1,
        role: 'assistant',
        text: replyText,
        actions: response.suggested_actions || [],
        contextSummary: response.context_summary,
        changeSummary: proposed ? (response.change_summary || t('globalAi.previewReady', 'Vorschau liegt im Canvas bereit.')) : response.change_summary
      };
      setChat((items) => [...items, assistantEntry]);
      setMessage('');
    } catch (err) {
      const text = err.message || t('globalAi.assistantFailed', 'Der KI-Assistent konnte nicht antworten.');
      setChat((items) => [...items, { id: entryId + 2, role: 'assistant error', text }]);
      notify?.(text, 'error');
    } finally {
      setBusy(false);
    }
  }

  async function runAction(action) {
    const actionId = action?.id || action;
    if (!actionId) return;
    if (String(actionId) === 'daw_execute_plan') {
      try {
        const result = await api.daw.render(action.payload || {});
        notify?.(`DAW-Version gespeichert: ${result.version_label || result.display_title || result.id}`, 'success');
        await assistant.executeFrontendAction?.('navigate_daw', { audio_asset_id: result.id });
        await assistant.executeFrontendAction?.('refresh_app');
        setChat((items) => [...items, { id: Date.now(), role: 'assistant', text: t('globalAi.dawSaved', 'Erledigt: Neue DAW-Version "{{label}}" wurde gespeichert.', { label: result.version_label || result.display_title || result.id }) }]);
      } catch (err) {
        const text = err.message || t('daw.messages.renderFailed', 'DAW-Render fehlgeschlagen.');
        notify?.(text, 'error');
        setChat((items) => [...items, { id: Date.now(), role: 'assistant error', text }]);
      }
      return;
    }
    if (String(actionId).startsWith('lyrics_') && actionId !== 'lyrics_save' && actionId !== 'lyrics_apply_preview' && actionId !== 'lyrics_discard_preview') {
      await send(action?.label || t('globalAi.editLyrics', 'Songtext bearbeiten'), actionId, { applyToCanvas: true });
      return;
    }
    const ok = await assistant.executeFrontendAction?.(actionId, { ...(action?.payload || {}), proposedCanvas: pendingCanvas?.text, changeSummary: pendingCanvas?.summary });
    if (ok) {
      if (actionId === 'lyrics_apply_preview' || actionId === 'lyrics_discard_preview') setPendingCanvas(null);
      notify?.(t('globalAi.actionDone', 'Aktion ausgeführt.'), 'success');
      setChat((items) => [...items, { id: Date.now(), role: 'assistant', text: t('globalAi.done', 'Erledigt: {{label}}', { label: action?.label || actionId }) }]);
    } else {
      notify?.(t('globalAi.actionNotExecutable', 'Diese Aktion ist hier noch nicht direkt ausführbar.'), 'error');
    }
  }

  if (!open) {
    return (
      <button type="button" className="global-ai-toggle" onClick={() => setOpen(true)} title={t('globalAi.open', 'KI-Assistent öffnen')}>
        <MessageCircle size={22} />
        <span>{t('globalAi.help', 'KI-Hilfe')}</span>
      </button>
    );
  }

  return (
    <aside className={`global-ai-panel ${minimized ? 'is-minimized' : ''}`}>
      <div className="global-ai-header">
        <div>
          <strong><Bot size={18} /> {t('globalAi.title', 'KI-Assistent')}</strong>
          <span>{pageLabel}</span>
          <div className="global-ai-runtime-inline" title={formatRuntimeDetail(runtimeInfo)}>
            <Cpu size={13} /> {formatRuntimeLabel(runtimeInfo)}
          </div>
        </div>
        <div className="global-ai-header-actions">
          <button type="button" onClick={() => { setChat([]); setPendingCanvas(null); setMessage(''); localStorage.removeItem('global-ai-chat'); notify?.(t('globalAi.chatCleared', 'Chatfenster wurde geleert.'), 'success'); }} title={t('globalAi.clearChat', 'Chat leeren')}><Trash2 size={16} /></button>
          <button type="button" onClick={() => setMinimized(!minimized)} title={minimized ? t('globalAi.expand', 'Ausklappen') : t('globalAi.collapse', 'Einklappen')}>{minimized ? <ChevronUp size={16} /> : <ChevronDown size={16} />}</button>
          <button type="button" onClick={() => setOpen(false)} title={t('globalAi.close', 'Schließen')}><X size={16} /></button>
        </div>
      </div>

      {!minimized && (
        <>
          <section className={`global-ai-top-container ${quickPanelCollapsed ? 'is-collapsed' : ''}`}>
            <button
              type="button"
              className="global-ai-top-toggle"
              onClick={() => setQuickPanelCollapsed((value) => !value)}
              aria-expanded={!quickPanelCollapsed}
              title={quickPanelCollapsed ? t('globalAi.showContext', 'Kontext und Schnellaktionen anzeigen') : t('globalAi.hideContext', 'Kontext und Schnellaktionen einklappen')}
            >
              <span>{t('globalAi.contextTitle', 'Kontext & Schnellaktionen')}</span>
              <small>{formatRuntimeLabel(runtimeInfo)} · {t('globalAi.actionsCount', '{{count}} Aktion(en)', { count: pageActions.length || 0 })}</small>
              {quickPanelCollapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
            </button>

            {!quickPanelCollapsed && (
              <div className="global-ai-top-content">
                <div className="global-ai-context">
                  <span>{t('globalAi.contextHint', 'Ich erkenne automatisch, wo du gerade bist, und biete passende Schritte an.')}</span>
                  <div className="global-ai-runtime-box">
                    <strong>{t('globalAi.activeAi', 'Aktive KI')}</strong>
                    <span>{formatRuntimeLabel(runtimeInfo)}</span>
                    <small>{formatRuntimeDetail(runtimeInfo)}</small>
                  </div>
                </div>

                <div className="global-ai-suggestions">
                  {(pageActions.length ? pageActions : []).slice(0, 4).map((action) => (
                    <button key={action.id} type="button" onClick={() => runAction(action)}><Sparkles size={13} /> {action.label}</button>
                  ))}
                </div>
              </div>
            )}
          </section>

          <div className="global-ai-log" ref={logRef}>
            {!chat.length && (
              <div className="global-ai-empty">
                <strong>{t('globalAi.newSession', 'Neue Session')}</strong>
                <p>{t('globalAi.empty', 'Das Nachrichtenfeld ist leer. Du kannst frei schreiben oder einen passenden Befehl für den aktuellen Schritt nutzen.')}</p>
                {pageActions.length > 0 && (
                  <div className="global-ai-hints">
                    {pageActions.slice(0, 8).map((action) => <button key={action.id} type="button" onClick={() => runAction(action)}>{action.label}</button>)}
                  </div>
                )}
              </div>
            )}
            {chat.map((item) => (
              <div key={item.id} className={`global-ai-message ${item.role}`}>
                <strong>{item.role.startsWith('user') ? t('globalAi.you', 'Du') : t('globalAi.assistant', 'Assistent')}</strong>
                <FormattedMessage text={item.text} />
                {item.changeSummary && <small>{item.changeSummary}</small>}
                {item.actions?.length > 0 && (
                  <div className="global-ai-message-actions">
                    {item.actions.slice(0, 5).map((action) => <button key={action.id} type="button" onClick={() => runAction(action)}>{action.label}</button>)}
                  </div>
                )}
              </div>
            ))}
            {pendingCanvas && (
              <div className="global-ai-preview compact-preview">
                <strong>{t('globalAi.canvasPrepared', 'Canvas-Vorschau vorbereitet')}</strong>
                <p className="muted">{pendingCanvas.summary}</p>
                <p>{t('globalAi.canvasHidden', 'Der Songtext wird nicht im Chat angezeigt. Prüfe ihn direkt im Canvas des Songtext-Studios.')}</p>
                <div className="global-ai-preview-actions">
                  <button className="primary" type="button" onClick={() => runAction({ id: 'lyrics_apply_preview', label: t('globalAi.applyCanvas', 'Canvas übernehmen') })}><Check size={15} /> {t('globalAi.apply', 'Übernehmen')}</button>
                  <button type="button" onClick={() => runAction({ id: 'lyrics_discard_preview', label: t('globalAi.discard', 'Verwerfen') })}><Trash2 size={15} /> {t('globalAi.discard', 'Verwerfen')}</button>
                </div>
              </div>
            )}
          </div>

          <form className="global-ai-input" onSubmit={(event) => { event.preventDefault(); send(); }}>
            <textarea value={message} onChange={(event) => setMessage(event.target.value)} placeholder={t('globalAi.placeholder', 'Frag nach Lyrics, Styles, SRT-Segmenten, Projekten oder einfachen Audio-Bearbeitungen …')} rows={3} onKeyDown={(event) => { if (event.ctrlKey && event.key === 'Enter') send(); }} />
            <button className="primary" type="submit" disabled={busy}>{busy ? <Loader2 className="spin-icon" size={16} /> : <Send size={16} />} {t('globalAi.send', 'Senden')}</button>
          </form>
        </>
      )}
    </aside>
  );
}
