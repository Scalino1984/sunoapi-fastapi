import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Bot, Check, Copy, FileText, Maximize2, Minimize2, Redo2, Save, Sparkles, Trash2, Undo2 } from 'lucide-react';
import { Modal } from '../components/Modal.jsx';
import { api } from '../api/client.js';
import { SectionHeader } from '../components/SectionHeader.jsx';
import { FormattedMessage } from '../components/FormattedMessage.jsx';
import { copyToClipboard, lineCount, pickLyrics, pickPrompt, pickTitle, safeArray } from '../utils.js';
import { useAppAssistant } from '../context/AppAssistantContext.jsx';

const quickPrompts = [
  ['Hook verbessern', 'Verbessere die Hook im Canvas mit mehr Wiedererkennungswert, klarer Melodieidee und Suno-kompatibler Struktur.'],
  ['Verse härter machen', 'Überarbeite die Verse härter, direkter und druckvoller, ohne die Kernaussage zu verlieren.'],
  ['Mehr Reime', 'Erhöhe die Reimdichte mit Binnenreimen, Doppelreimen und Kettenreimen.'],
  ['Mehr Doubletime', 'Formatiere geeignete Stellen für schnelleren Rap/Doubletime und achte auf saubere Atempausen.'],
  ['Mehr Emotion', 'Verstärke die emotionale Wirkung, Bilder und Spannungsbögen.'],
  ['Mehr Punchlines', 'Baue stärkere humorvolle oder harte Punchlines ein, passend zum vorhandenen Thema.'],
  ['Suno-kompatibel', 'Formatiere den Canvas Suno-freundlich mit klaren Sections, Vocal Tags und sinnvollen Energieangaben.'],
  ['Vocal Tags einfügen', 'Ergänze passende Vocal Tags wie [Verse], [Chorus], [Bridge], Delivery, Energy und Stimmung.'],
  ['Songstruktur prüfen', 'Prüfe die Songstruktur und gib direkt eine verbesserte, verwendbare Version zurück.'],
  ['Bridge ergänzen', 'Ergänze eine passende Bridge mit Kontrast zur Hook.'],
  ['Text kürzen', 'Kürze den Canvas auf eine kompaktere, Suno-taugliche Version ohne Wirkung zu verlieren.'],
  ['Text verlängern', 'Erweitere den Song um sinnvolle Parts und behalte den roten Faden bei.'],
  ['Style vorschlagen', 'Schlage einen konkreten Suno Music Style mit Genre, BPM, Instrumentierung, Vocal-Vibe und Stimmung vor.']
];

const instrumentalQuickPrompts = [
  ['Bauplan erstellen', 'Erstelle einen vollständigen instrumental nutzbaren Suno-Bauplan mit Timecodes, Abschnitten, Instrumentierung, Sounddesign, Builds, Drops, Breakdown und Outro. Keine Lyrics, keine gesungenen Zeilen.'],
  ['Mehr Dramaturgie', 'Verstärke den Spannungsbogen des Instrumental-Bauplans mit klaren Energiephasen, Breaks, Builds und Drops. Keine Lyrics.'],
  ['Sounddesign ausbauen', 'Erweitere den Bauplan um konkrete Sounddesign-Hinweise, Texturen, Drums, Bass, Lead-Instrumente und Übergänge. Keine Lyrics.'],
  ['Suno-ready Instrumental', 'Formatiere den Canvas als Suno-tauglichen Instrumental-Bauplan mit eckigen Timecode-Sektionen und kurzen präzisen Sound-Anweisungen. Keine Lyrics.'],
  ['Drops optimieren', 'Optimiere Drop-, Build-up- und Peak-Time-Abschnitte für maximale Wirkung und klare Instrumental-Struktur. Keine Lyrics.'],
  ['Kürzer machen', 'Kürze den Instrumental-Bauplan auf eine kompaktere, Suno-taugliche Version, ohne den Verlauf zu verlieren. Keine Lyrics.']
];

const STUDIO_MODES = {
  lyrics: {
    label: 'Songtext',
    title: 'Songtext Studio',
    chatTitle: 'KI-Chat zum Songtext',
    canvasNoun: 'Songtext',
    saveLabel: 'Als Songtext speichern',
    directMusicLabel: 'Direkt Musik generieren',
    emptyHint: 'Frag nach Reimen, Struktur, Hook-Ideen, Suno-Tauglichkeit oder diskutiere erst den roten Faden. Der Canvas bleibt unverändert, bis du bewusst ausführst.',
    placeholder: 'Songtext hier schreiben oder KI bitten, den Canvas zu erstellen…',
    chatPlaceholder: 'Frei mit der KI diskutieren… Mit Strg+Enter senden, Strg+Shift+Enter als Canvas-Befehl ausführen.',
    chapterEmpty: 'Vocal Tags wie [Verse], [Hook], [Chorus] oder [Bridge] werden hier automatisch als Sprungmarken angezeigt.',
    chapterText: 'erkannte Vocal-Tag-Kapitel',
    saveNotice: 'Songtext und KI-Chat wurden gespeichert.',
    musicNotice: 'Songtext wurde für Musik übernommen.'
  },
  instrumental_blueprint: {
    label: 'Instrumental-Bauplan',
    title: 'Instrumental-Bauplan Studio',
    chatTitle: 'KI-Chat zum Instrumental-Bauplan',
    canvasNoun: 'Bauplan',
    saveLabel: 'Als Bauplan speichern',
    directMusicLabel: 'Als Instrumental generieren',
    emptyHint: 'Plane Arrangement, Timecodes, Instrumente, Sounddesign, Builds, Drops und Breakdowns. Der Canvas bleibt unverändert, bis du bewusst ausführst.',
    placeholder: 'Instrumental-Bauplan hier schreiben oder KI bitten, einen Timecode-Bauplan ohne Lyrics zu erstellen…',
    chatPlaceholder: 'Instrumental-Ideen diskutieren… Mit Strg+Enter senden, Strg+Shift+Enter als Canvas-Befehl ausführen.',
    chapterEmpty: 'Timecode-Tags wie [0:00 - Intro], [1:00 - Build-up] oder [3:30 - Drop] werden hier automatisch als Sprungmarken angezeigt.',
    chapterText: 'erkannte Bauplan-Kapitel',
    saveNotice: 'Instrumental-Bauplan und KI-Chat wurden gespeichert.',
    musicNotice: 'Instrumental-Bauplan wurde für Musik übernommen.'
  }
};

function normalizeStudioMode(value) {
  const normalized = String(value || '').trim().toLowerCase().replace('-', '_');
  return ['instrumental', 'instrumental_blueprint', 'blueprint', 'sound_blueprint', 'sounds'].includes(normalized) ? 'instrumental_blueprint' : 'lyrics';
}

const SECTION_TYPE_LABELS = {
  intro: 'Intro',
  verse: 'Verse',
  hook: 'Hook',
  chorus: 'Chorus',
  prechorus: 'Pre-Chorus',
  bridge: 'Bridge',
  outro: 'Outro',
  breakdown: 'Break',
  adlib: 'Adlibs',
  other: 'Part'
};

function detectSectionType(rawLabel = '') {
  const value = rawLabel.toLowerCase().replace(/[^a-z0-9äöüß\s-]/g, ' ').trim();
  if (value.startsWith('intro') || value.includes(' intro')) return 'intro';
  if (value.startsWith('verse') || value.startsWith('vers') || value.startsWith('strophe')) return 'verse';
  if (value.startsWith('hook')) return 'hook';
  if (value.startsWith('chorus') || value.startsWith('refrain')) return 'chorus';
  if (value.startsWith('pre chorus') || value.startsWith('pre-chorus') || value.startsWith('prehook') || value.startsWith('pre hook')) return 'prechorus';
  if (value.startsWith('bridge') || value.includes(' bridge')) return 'bridge';
  if (value.startsWith('outro') || value.includes(' outro')) return 'outro';
  if (value.startsWith('break') || value.startsWith('drop') || value.includes(' drop') || value.includes(' build') || value.includes(' breakdown') || value.includes(' peak')) return 'breakdown';
  if (value.startsWith('adlib') || value.startsWith('ad-lib') || value.startsWith('ad libs')) return 'adlib';
  return 'other';
}

function extractEnergy(tagText = '') {
  const match = tagText.match(/energy\s*:\s*([^|\]]+)/i);
  return match ? match[1].trim() : '';
}

function parseCanvasSections(text = '') {
  const source = String(text || '');
  if (!source.trim()) return [];
  const lines = source.split('\n');
  const sections = [];
  let charIndex = 0;

  lines.forEach((line, index) => {
    const match = line.match(/^\s*\[([^\]\n]{2,260})\]\s*$/);
    if (match) {
      const fullTag = `[${match[1].trim()}]`;
      const parts = match[1].split('|').map((part) => part.trim()).filter(Boolean);
      const baseLabel = parts[0] || 'Part';
      const type = detectSectionType(baseLabel);
      const detail = parts.slice(1).filter((part) => !/^energy\s*:/i.test(part)).join(' · ');
      const energy = extractEnergy(match[1]);
      sections.push({
        id: `${index}-${charIndex}`,
        index: sections.length + 1,
        line: index,
        charIndex,
        fullTag,
        baseLabel,
        type,
        typeLabel: SECTION_TYPE_LABELS[type] || SECTION_TYPE_LABELS.other,
        detail,
        energy,
        contentLines: 0,
      });
    }
    charIndex += line.length + 1;
  });

  return sections.map((section, index) => {
    const next = sections[index + 1];
    const endLine = next ? next.line : lines.length;
    const contentLines = Math.max(0, endLine - section.line - 1);
    return { ...section, contentLines };
  });
}


function sourceContentFromLyricDraft(item = {}) {
  return String(item.content || item.lyrics || item.prompt || item.text || '').trim();
}

function buildCanvasImportSources(lyrics = [], assets = []) {
  const draftSources = safeArray(lyrics, ['lyrics', 'items'])
    .map((item) => {
      const content = sourceContentFromLyricDraft(item);
      if (!content) return null;
      return {
        id: `lyric-${item.id}`,
        sourceType: 'lyric',
        sourceId: item.id,
        title: item.title || 'Gespeicherter Songtext',
        label: `Songtext · ${item.title || `#${item.id}`}`,
        content,
        updatedAt: item.updated_at || item.created_at || '',
      };
    })
    .filter(Boolean);

  const assetSources = safeArray(assets, ['assets', 'audio_assets', 'items'])
    .map((asset) => {
      const content = String(pickPrompt(asset) || pickLyrics(asset) || '').trim();
      if (!content) return null;
      const title = pickTitle(asset) || asset.title || asset.filename || `Audio #${asset.id}`;
      return {
        id: `asset-${asset.id}`,
        sourceType: 'asset',
        sourceId: asset.id,
        title,
        label: `Library · ${title}`,
        content,
        updatedAt: asset.updated_at || asset.created_at || '',
      };
    })
    .filter(Boolean);

  return [...draftSources, ...assetSources]
    .sort((left, right) => String(right.updatedAt || '').localeCompare(String(left.updatedAt || '')))
    .slice(0, 250);
}

function CanvasSectionMap({ sections, onJump, modeConfig = STUDIO_MODES.lyrics }) {
  if (!sections.length) {
    return (
      <div className="canvas-section-map empty">
        <div>
          <strong>Kapitel-Miniansicht</strong>
          <p className="muted">{modeConfig.chapterEmpty}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="canvas-section-map">
      <div className="canvas-section-map-head">
        <div>
          <strong>Kapitel-Miniansicht</strong>
          <p className="muted">{sections.length} {modeConfig.chapterText} · Klick springt direkt zur Stelle im Canvas.</p>
        </div>
        <div className="canvas-section-legend" aria-label="Farbgruppen">
          {['intro', 'verse', 'hook', 'chorus', 'bridge', 'outro'].map((type) => (
            <span key={type} className={`section-legend-dot section-type-${type}`}>{SECTION_TYPE_LABELS[type]}</span>
          ))}
        </div>
      </div>
      <div className="canvas-section-grid">
        {sections.map((section) => (
          <button
            key={section.id}
            type="button"
            className={`canvas-section-chip section-type-${section.type}`}
            onClick={() => onJump(section)}
            title={`${section.fullTag} · Zeile ${section.line + 1}`}
          >
            <span className="chapter-index">{String(section.index).padStart(2, '0')}</span>
            <span className="chapter-main">
              <span className="chapter-title">{section.baseLabel}</span>
              {section.detail && <span className="chapter-detail">{section.detail}</span>}
            </span>
            <span className="chapter-meta">
              {section.energy && <span>{section.energy}</span>}
              <span>Z{section.line + 1}</span>
              <span>{section.contentLines}L</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

export function LyricsStudioPage({ notify, onRefresh, useForMusic, lyrics = [], assets = [] }) {
  const [sessions, setSessions] = useState([]);
  const [profiles, setProfiles] = useState([]);
  const [aiConfig, setAiConfig] = useState(null);
  const [vocalTags, setVocalTags] = useState([]);
  const [session, setSession] = useState(null);
  const [canvas, setCanvas] = useState('');
  const [message, setMessage] = useState('');
  const [sessionTitle, setSessionTitle] = useState('Neue Session');
  const [studioMode, setStudioMode] = useState(() => normalizeStudioMode(localStorage.getItem('react-lyrics-studio-mode') || 'lyrics'));
  const [draftId, setDraftId] = useState(null);
  const [provider, setProvider] = useState('openai');
  const [model, setModel] = useState('GPT-5.4-mini');
  const [profileId, setProfileId] = useState('');
  const [loading, setLoading] = useState(false);
  const [assistantPreview, setAssistantPreview] = useState(null);
  const [sunoLyricsLoading, setSunoLyricsLoading] = useState(false);
  const [focusMode, setFocusMode] = useState(() => localStorage.getItem('react-lyrics-focus') === 'true');
  const [focusLayout, setFocusLayout] = useState(() => localStorage.getItem('react-lyrics-focus-layout') || 'stack');
  const [chatModalOpen, setChatModalOpen] = useState(false);
  const [chatModalMode, setChatModalMode] = useState('chat');
  const [chatModalSize, setChatModalSize] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('react-lyrics-chat-modal-size') || '') || { width: 1220, height: 780 };
    } catch {
      return { width: 1220, height: 780 };
    }
  });
  const [canvasFontSize, setCanvasFontSize] = useState(() => Number(localStorage.getItem('react-lyrics-canvas-font-size') || 15));
  const [chatFontSize, setChatFontSize] = useState(() => Number(localStorage.getItem('react-lyrics-chat-font-size') || 14));
  const [tagFilter, setTagFilter] = useState('');
  const [selectedCanvasSourceId, setSelectedCanvasSourceId] = useState('');
  const assistant = useAppAssistant();
  const messages = useMemo(() => session?.messages || [], [session]);
  const canvasRef = useRef(null);
  const modalCanvasRef = useRef(null);
  const canvasSections = useMemo(() => parseCanvasSections(canvas), [canvas]);
  const studioModeConfig = STUDIO_MODES[studioMode] || STUDIO_MODES.lyrics;
  const activeQuickPrompts = studioMode === 'instrumental_blueprint' ? instrumentalQuickPrompts : quickPrompts;
  const canvasImportSources = useMemo(() => buildCanvasImportSources(lyrics, assets), [lyrics, assets]);
  const selectedCanvasSource = useMemo(() => canvasImportSources.find((item) => item.id === selectedCanvasSourceId) || canvasImportSources[0] || null, [canvasImportSources, selectedCanvasSourceId]);

  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (!canvasImportSources.length) {
      if (selectedCanvasSourceId) setSelectedCanvasSourceId('');
      return;
    }
    if (!canvasImportSources.some((item) => item.id === selectedCanvasSourceId)) {
      setSelectedCanvasSourceId(canvasImportSources[0].id);
    }
  }, [canvasImportSources, selectedCanvasSourceId]);
  useEffect(() => localStorage.setItem('react-lyrics-studio-mode', studioMode), [studioMode]);
  useEffect(() => localStorage.setItem('react-lyrics-focus', String(focusMode)), [focusMode]);
  useEffect(() => localStorage.setItem('react-lyrics-focus-layout', focusLayout), [focusLayout]);
  useEffect(() => localStorage.setItem('react-lyrics-chat-modal-size', JSON.stringify(chatModalSize)), [chatModalSize]);
  useEffect(() => localStorage.setItem('react-lyrics-canvas-font-size', String(canvasFontSize)), [canvasFontSize]);
  useEffect(() => localStorage.setItem('react-lyrics-chat-font-size', String(chatFontSize)), [chatFontSize]);
  useEffect(() => {
    const payload = { canvas, sessionTitle, sessionId: session?.id || null, draftId, profileId, studioMode };
    localStorage.setItem('assistant-lyrics-state', JSON.stringify(payload));
    assistant.updatePageState?.('lyrics', payload);
  }, [canvas, sessionTitle, session?.id, draftId, profileId, studioMode]);

  useEffect(() => {
    async function handleSave() {
      await saveAsDraft();
    }
    function handlePreview(event) {
      const proposed = event.detail?.proposedCanvas || event.detail?.text || '';
      if (!proposed.trim()) return;
      setAssistantPreview({
        text: proposed,
        summary: event.detail?.changeSummary || event.detail?.summary || 'KI-Vorschau vorbereitet',
        createdAt: event.detail?.createdAt || new Date().toISOString(),
        sourceMessage: event.detail?.sourceMessage || ''
      });
      notify('KI-Vorschau liegt direkt am Canvas bereit.', 'success');
    }
    async function handleApplyPreview(event) {
      const proposed = event.detail?.proposedCanvas || event.detail?.text || assistantPreview?.text || '';
      if (!proposed.trim()) return;
      await applyAssistantPreview(proposed, event.detail?.changeSummary || event.detail?.summary || assistantPreview?.summary || 'KI-Vorschau übernommen');
    }
    function handleDiscardPreview() {
      setAssistantPreview(null);
      notify('KI-Vorschau verworfen. Der Songtext bleibt unverändert.', 'info');
    }
    window.addEventListener('assistant:lyrics-save', handleSave);
    window.addEventListener('assistant:lyrics-preview', handlePreview);
    window.addEventListener('assistant:lyrics-apply-preview', handleApplyPreview);
    window.addEventListener('assistant:lyrics-discard-preview', handleDiscardPreview);
    return () => {
      window.removeEventListener('assistant:lyrics-save', handleSave);
      window.removeEventListener('assistant:lyrics-preview', handlePreview);
      window.removeEventListener('assistant:lyrics-apply-preview', handleApplyPreview);
      window.removeEventListener('assistant:lyrics-discard-preview', handleDiscardPreview);
    };
  }, [canvas, session, sessionTitle, assistantPreview]);

  async function load() {
    const [sessionRows, config, tags] = await Promise.all([api.ai.sessions(), api.ai.config(), api.library.vocalTags()]);
    const safeConfig = config || {};
    const allowedModels = safeConfig.allowed_models || {};
    const defaultProvider = safeConfig.default_provider || provider;
    const providerModels = allowedModels[defaultProvider] || [];
    setSessions(sessionRows || []);
    setAiConfig(safeConfig);
    setProfiles(safeConfig.assistant_profiles || []);
    setVocalTags(tags || []);
    if (safeConfig.default_provider) setProvider(safeConfig.default_provider);
    if (safeConfig.default_model && (!providerModels.length || providerModels.includes(safeConfig.default_model))) {
      setModel(safeConfig.default_model);
    } else if (providerModels.length) {
      setModel(providerModels[0]);
    }
  }

  const fallbackAllowedModels = { openai: ['GPT-5.4-mini'], openrouter: [], gemini: [], groq: ['Llama 3.1 8B Instant', 'llama-3.3-70b-versatile', 'compound-mini'] };
  const allowedAiModels = aiConfig?.allowed_models || fallbackAllowedModels;
  const aiProviderOptions = Object.keys(allowedAiModels);
  const aiModelOptions = allowedAiModels[provider] || [];
  const providerLabels = { openai: 'OpenAI', openrouter: 'OpenRouter', gemini: 'Gemini', groq: 'Groq' };

  function changeAiProvider(nextProvider) {
    setProvider(nextProvider);
    const models = allowedAiModels[nextProvider] || [];
    if (models.length) setModel(models[0]);
  }

  async function createSession() {
    const created = await api.ai.createSession({ title: sessionTitle, provider, model, lyric_draft_id: draftId ? Number(draftId) : null, assistant_profile_id: profileId ? Number(profileId) : null, canvas_content: canvas, work_mode: studioMode });
    setSession(created);
    setCanvas(created.canvas_content || '');
    notify('Session gespeichert.', 'success');
    await load();
  }

  async function openSession(id) {
    if (!id) return;
    const loaded = await api.ai.getSession(id);
    setSession(loaded);
    setCanvas(loaded.canvas_content || '');
    setSessionTitle(loaded.title || 'Session');
    setProvider(loaded.provider || provider);
    setModel(loaded.model || model);
    setProfileId(loaded.assistant_profile_id || '');
    setStudioMode(normalizeStudioMode(loaded.metadata_json?.work_mode || studioMode));
    setDraftId(loaded.lyric_draft_id || null);
  }

  async function saveCanvas() {
    if (!session) return createSession();
    const updated = await api.ai.updateCanvas(session.id, canvas, { source: 'manual', change_summary: 'Manuell gespeichert' });
    setSession(updated);
    notify('Canvas gespeichert.', 'success');
  }

  async function ensureSessionForCanvas() {
    if (session) {
      return await api.ai.updateCanvas(session.id, canvas, { source: 'manual', change_summary: 'Stand vor KI-Übernahme gesichert' });
    }
    const created = await api.ai.createSession({
      title: sessionTitle || 'KI-Canvas-Session',
      provider,
      model,
      lyric_draft_id: draftId ? Number(draftId) : null,
      assistant_profile_id: profileId ? Number(profileId) : null,
      canvas_content: canvas,
      work_mode: studioMode
    });
    setSession(created);
    await load();
    return created;
  }

  async function applyAssistantPreview(proposedText = assistantPreview?.text, summary = assistantPreview?.summary) {
    const proposed = String(proposedText || '').trim();
    if (!proposed) return;
    try {
      const active = await ensureSessionForCanvas();
      const updated = await api.ai.updateCanvas(active.id, proposed, { source: 'global_ai_assistant', change_summary: summary || 'KI-Vorschau übernommen' });
      setSession(updated);
      setCanvas(updated.canvas_content || proposed);
      setAssistantPreview(null);
      notify('KI-Vorschau wurde übernommen. Undo/Redo ist jetzt verfügbar.', 'success');
      await load();
    } catch (err) {
      notify(err.message || 'KI-Vorschau konnte nicht übernommen werden.', 'error');
    }
  }

  async function send(customMessage = null, applyToCanvas = false) {
    const finalMessage = String(customMessage || message || '').trim();
    if (!finalMessage) return;
    setLoading(true);
    try {
      let active = session;
      if (!active) {
        active = await api.ai.createSession({
          title: sessionTitle,
          provider,
          model,
          lyric_draft_id: draftId ? Number(draftId) : null,
          assistant_profile_id: profileId ? Number(profileId) : null,
          canvas_content: canvas,
          work_mode: studioMode
        });
        setSession(active);
      }
      const response = await api.ai.sendMessage(active.id, finalMessage, {
        canvas_content: canvas,
        apply_to_canvas: applyToCanvas,
        work_mode: studioMode
      });
      setSession(response.session);
      if (response.canvas_changed) {
        setCanvas(response.canvas_content || response.session?.canvas_content || canvas);
        notify('KI hat den Canvas aktualisiert.', 'success');
      }
      setMessage('');
      await load();
    } catch (err) {
      notify(err.message || 'KI-Anfrage fehlgeschlagen.', 'error');
    } finally {
      setLoading(false);
    }
  }

  async function undo() {
    if (!session) return;
    const updated = await api.ai.undo(session.id);
    setSession(updated);
    setCanvas(updated.canvas_content || '');
  }

  async function redo() {
    if (!session) return;
    const updated = await api.ai.redo(session.id);
    setSession(updated);
    setCanvas(updated.canvas_content || '');
  }

  async function saveAsDraft() {
    try {
      const payload = {
        title: sessionTitle || (studioMode === 'instrumental_blueprint' ? 'Instrumental-Bauplan' : 'Songtext'),
        content: canvas,
        status: 'draft',
        language: 'de',
        tags: studioMode === 'instrumental_blueprint' ? 'instrumental,bauplan,no-lyrics' : undefined
      };
      const draft = draftId ? await api.library.updateLyric(draftId, payload) : await api.library.createLyric(payload);
      setDraftId(draft.id);
      if (session?.id) {
        const linked = await api.ai.updateSession(session.id, {
          title: sessionTitle || draft.title || 'Songtext-Chat',
          lyric_draft_id: draft.id,
          canvas_content: canvas,
          work_mode: studioMode
        });
        setSession(linked);
      }
      notify(studioModeConfig.saveNotice, 'success');
      await onRefresh?.();
    } catch (err) {
      notify(err.message || 'Songtext konnte nicht gespeichert werden.', 'error');
    }
  }

  async function clearLocalChat() {
    if (!session?.id) {
      setMessage('');
      notify('Noch keine gespeicherte KI-Session vorhanden.', 'info');
      return;
    }
    try {
      const cleared = await api.ai.clearMessages(session.id);
      setSession(cleared);
      setMessage('');
      notify('Lokaler KI-Chat wurde geleert.', 'success');
    } catch (err) {
      notify(err.message || 'Chat konnte nicht geleert werden.', 'error');
    }
  }

  async function generateLyricsWithSunoAPI() {
    const sourcePrompt = String(message || canvas || sessionTitle || '').trim();
    if (!sourcePrompt) {
      notify('Bitte gib zuerst ein Thema, eine Idee oder vorhandenen Text ein.', 'error');
      return;
    }

    setSunoLyricsLoading(true);
    try {
      const task = await api.lyrics.generate({ prompt: sourcePrompt });
      notify(`SunoAPI Lyrics-Generierung gestartet. Task: ${String(task?.task_id || task?.id || '').slice(0, 16)}…`, 'success');
      await onRefresh?.();
    } catch (err) {
      notify(err?.message || 'SunoAPI Lyrics-Generierung fehlgeschlagen.', 'error');
    } finally {
      setSunoLyricsLoading(false);
    }
  }

  function insertTag(tag) {
    const text = tag.tag || tag.label || '';
    setCanvas((value) => `${value}${value.endsWith('\n') || !value ? '' : '\n'}${text}\n`);
  }

  async function switchStudioMode(nextMode) {
    const normalized = normalizeStudioMode(nextMode);
    setStudioMode(normalized);
    if (session?.id) {
      try {
        const updated = await api.ai.updateSession(session.id, { work_mode: normalized, canvas_content: canvas });
        setSession(updated);
      } catch (_) {
        // Modus bleibt lokal nutzbar; beim nächsten Speichern wird er erneut übertragen.
      }
    }
  }

  function sendCanvasToMusic() {
    useForMusic?.({
      title: sessionTitle || studioModeConfig.canvasNoun,
      content: canvas,
      lyrics: canvas,
      prompt: canvas,
      work_mode: studioMode,
      instrumental: studioMode === 'instrumental_blueprint',
      customMode: true
    });
  }


  async function applySelectedSongtextToCanvas(mode = 'replace') {
    const source = selectedCanvasSource;
    const sourceText = String(source?.content || '').trim();
    if (!sourceText) {
      notify('Kein Songtext zum Übernehmen ausgewählt.', 'error');
      return;
    }

    const currentText = String(canvas || '').trim();
    const nextCanvas = mode === 'append' && currentText
      ? `${canvas.replace(/\s*$/u, '')}\n\n${sourceText}`
      : sourceText;
    const nextTitle = source?.title || sessionTitle || 'Songtext';

    try {
      if (studioMode !== 'lyrics') setStudioMode('lyrics');
      setDraftId(source.sourceType === 'lyric' ? source.sourceId : null);
      if (!sessionTitle || sessionTitle === 'Neue Session') setSessionTitle(nextTitle);

      if (session?.id) {
        const updated = await api.ai.updateCanvas(session.id, nextCanvas, {
          source: source.sourceType === 'asset' ? 'audio_asset_lyrics_import' : 'lyric_draft_import',
          change_summary: `${mode === 'append' ? 'Songtext angehängt' : 'Songtext übernommen'}: ${nextTitle}`
        });
        setSession(updated);
        setCanvas(updated.canvas_content || nextCanvas);
      } else {
        setCanvas(nextCanvas);
      }
      notify(mode === 'append' ? 'Songtext wurde an den Canvas angehängt.' : 'Songtext wurde in den Canvas übernommen.', 'success');
    } catch (err) {
      notify(err.message || 'Songtext konnte nicht in den Canvas übernommen werden.', 'error');
    }
  }

  function renderSongtextImportControls({ compact = false } = {}) {
    const disabled = !selectedCanvasSource;
    return (
      <div className={`lyrics-canvas-import ${compact ? 'compact' : ''}`}>
        <select
          value={selectedCanvasSource?.id || ''}
          onChange={(event) => setSelectedCanvasSourceId(event.target.value)}
          disabled={!canvasImportSources.length}
          title="Gespeicherten Songtext oder Library-Songtext auswählen"
        >
          {!canvasImportSources.length && <option value="">Keine Songtexte vorhanden</option>}
          {canvasImportSources.map((source) => (
            <option key={source.id} value={source.id}>{source.label}</option>
          ))}
        </select>
        <button type="button" onClick={() => applySelectedSongtextToCanvas('replace')} disabled={disabled}>
          <FileText size={15} /> Songtext in Canvas
        </button>
        {!compact && (
          <button type="button" onClick={() => applySelectedSongtextToCanvas('append')} disabled={disabled}>
            Anhängen
          </button>
        )}
      </div>
    );
  }

  const filteredTags = vocalTags.filter((tag) => [tag.label, tag.tag, tag.category, tag.description].filter(Boolean).join(' ').toLowerCase().includes(tagFilter.toLowerCase()));

  function askGlobalAssistant(prompt, actionId = null) {
    window.dispatchEvent(new CustomEvent('assistant:send', { detail: { message: prompt, actionId } }));
  }

  function jumpToCanvasSection(section, targetRef = canvasRef) {
    const field = targetRef.current;
    if (!field || !section) return;
    field.focus();
    const position = Math.max(0, Number(section.charIndex) || 0);
    try {
      field.setSelectionRange(position, position);
    } catch {
      // ignored: older browser selection edge case
    }
    const computed = window.getComputedStyle(field);
    const parsedLineHeight = Number.parseFloat(computed.lineHeight || '');
    const fontSize = Number.parseFloat(computed.fontSize || '16');
    const lineHeight = Number.isFinite(parsedLineHeight) ? parsedLineHeight : fontSize * 1.5;
    field.scrollTop = Math.max(0, (section.line * lineHeight) - 80);
  }

  function changeCanvasFontSize(delta) {
    setCanvasFontSize((value) => Math.min(24, Math.max(12, Number(value || 15) + delta)));
  }

  function changeChatFontSize(delta) {
    setChatFontSize((value) => Math.min(22, Math.max(12, Number(value || 14) + delta)));
  }

  function renderTextSizeControls(kind) {
    const value = kind === 'canvas' ? canvasFontSize : chatFontSize;
    const change = kind === 'canvas' ? changeCanvasFontSize : changeChatFontSize;
    return (
      <div className="text-size-control" aria-label={`${kind === 'canvas' ? 'Canvas' : 'KI-Chat'} Textgröße`}>
        <button type="button" onClick={() => change(-1)} aria-label="Text kleiner">−</button>
        <span>{value}px</span>
        <button type="button" onClick={() => change(1)} aria-label="Text größer">+</button>
      </div>
    );
  }

  function openChatModal(mode = 'chat') {
    setChatModalMode(mode);
    setChatModalOpen(true);
  }

  function resetChatModalSize() {
    setChatModalSize({ width: chatModalMode === 'workbench' ? 1480 : 1220, height: 820 });
  }

  function renderLocalChat({ modal = false } = {}) {
    return (
      <div className={`local-canvas-chat ${modal ? 'local-canvas-chat-modal' : ''}`} style={{ '--local-chat-font-size': `${chatFontSize}px` }}>
        <div className="row between align-start local-chat-header">
          <div>
            <div className="chat-topline"><Bot size={18} /><strong>{studioModeConfig.chatTitle}</strong></div>
            <p className="muted">Freie Diskussion wird gespeichert. Erst „Befehl ausführen“ verändert den Canvas und nutzt alle erarbeiteten Chat-Infos. Aktiver Modus: {studioModeConfig.label}.</p>
          </div>
          <div className="button-row wrap local-chat-tools">
            {renderTextSizeControls('chat')}
            {!modal && (
              <>
                <button type="button" onClick={() => openChatModal('chat')}><Maximize2 size={15} /> Nur KI-Chat</button>
                <button type="button" onClick={() => openChatModal('workbench')}><Maximize2 size={15} /> Canvas + Chat</button>
              </>
            )}
            {modal && <button type="button" onClick={resetChatModalSize}>Größe zurücksetzen</button>}
            <button type="button" onClick={clearLocalChat} disabled={!session}><Trash2 size={15} /> Chat leeren</button>
          </div>
        </div>

        <div className="chat-log local-chat-log">
          {messages.length === 0 && (
            <div className="chat-message assistant">
              <strong>Bereit für freie Ideenarbeit.</strong>
              <p>{studioModeConfig.emptyHint}</p>
            </div>
          )}
          {messages.map((item) => (
            <div key={item.id} className={`chat-message ${item.role === 'user' ? 'user' : 'assistant'}`}>
              <strong>{item.role === 'user' ? 'Du' : 'KI'}</strong>
              <FormattedMessage text={item.content} />
              {item.change_summary && <small>{item.change_summary}</small>}
            </div>
          ))}
        </div>

        <div className="quick-prompts local-chat-prompts">
          {activeQuickPrompts.slice(0, 6).map(([label, prompt]) => (
            <button key={label} type="button" onClick={() => setMessage(prompt)}><Sparkles size={14} /> {label}</button>
          ))}
        </div>

        <textarea
          className="local-chat-input"
          style={{ fontSize: `${chatFontSize}px` }}
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          onKeyDown={(event) => {
            if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
              event.preventDefault();
              send(null, event.shiftKey);
            }
          }}
          placeholder={studioModeConfig.chatPlaceholder}
        />
        <div className="button-row wrap">
          <button type="button" onClick={() => send(null, false)} disabled={loading || !message.trim()}>Chat senden</button>
          <button type="button" className="primary" onClick={() => send(null, true)} disabled={loading || !message.trim()}><Sparkles size={15} /> Befehl ausführen</button>
          <button type="button" onClick={saveAsDraft}><Save size={15} /> {studioModeConfig.canvasNoun} + Chat speichern</button>
        </div>
      </div>
    );
  }

  return (
    <section className={`page stack lyrics-page ${focusMode ? 'focus-mode' : ''} ${focusMode ? `focus-layout-${focusLayout}` : ''}`}>
      <SectionHeader eyebrow="Canvas" title={studioModeConfig.title}>
        <button type="button" onClick={() => setFocusMode(!focusMode)}>{focusMode ? <Minimize2 size={16} /> : <Maximize2 size={16} />} {focusMode ? 'Studio-Ansicht' : 'Fokus-Ansicht'}</button>
        {focusMode && (
          <button type="button" onClick={() => setFocusLayout(focusLayout === 'side' ? 'stack' : 'side')}>
            {focusLayout === 'side' ? 'Chat unten' : 'Chat rechts'}
          </button>
        )}
      </SectionHeader>

      <div className="session-toolbar panel slim-panel">
        <input value={sessionTitle} onChange={(event) => setSessionTitle(event.target.value)} placeholder="Session Titel" />
        <div className="segmented-control studio-mode-toggle" role="group" aria-label="Studio-Modus">
          {Object.entries(STUDIO_MODES).map(([key, config]) => (
            <button key={key} type="button" className={studioMode === key ? 'active' : ''} onClick={() => switchStudioMode(key)}>{config.label}</button>
          ))}
        </div>
        <select value={session?.id || ''} onChange={(event) => openSession(event.target.value)}>
          <option value="">Session öffnen…</option>
          {sessions.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
        </select>
        <button type="button" onClick={createSession}>Neu/Speichern</button>
        <button type="button" onClick={saveCanvas}><Save size={16} /> Canvas</button>
        {renderSongtextImportControls()}
        <button type="button" onClick={undo} disabled={!session}><Undo2 size={16} /> Undo</button>
        <button type="button" onClick={redo} disabled={!session}><Redo2 size={16} /> Redo</button>
        <button type="button" onClick={saveAsDraft}>{studioModeConfig.saveLabel}</button>
        <button type="button" className="primary" onClick={sendCanvasToMusic}>{studioModeConfig.directMusicLabel}</button>
      </div>

      <div className="studio-layout improved-studio">
        <div className="canvas-panel panel">
          <div className="row between align-start canvas-panel-header">
            <div><h2>Canvas · {studioModeConfig.label}</h2><p className="muted">{canvas.length} Zeichen · {lineCount(canvas)} Zeilen</p></div>
            <div className="button-row wrap canvas-tools">
              {renderTextSizeControls('canvas')}
              {renderSongtextImportControls({ compact: true })}
              <button type="button" onClick={async () => { await copyToClipboard(canvas); notify('Canvas kopiert.', 'success'); }}><Copy size={16} /> Kopieren</button>
            </div>
          </div>
          {assistantPreview && (
            <div className="canvas-ai-preview">
              <div className="row between">
                <div>
                  <strong>KI-Vorschau am Canvas</strong>
                  <p className="muted">{assistantPreview.summary}</p>
                </div>
                <div className="row wrap">
                  <button className="primary" type="button" onClick={() => applyAssistantPreview()}><Check size={15} /> Übernehmen</button>
                  <button type="button" onClick={() => { setAssistantPreview(null); notify('KI-Vorschau verworfen.', 'info'); }}><Trash2 size={15} /> Verwerfen</button>
                </div>
              </div>
              <textarea className="lyrics-canvas preview-canvas" style={{ fontSize: `${canvasFontSize}px` }} value={assistantPreview.text} onChange={(event) => setAssistantPreview((current) => ({ ...(current || {}), text: event.target.value }))} />
            </div>
          )}
          <CanvasSectionMap sections={canvasSections} onJump={jumpToCanvasSection} modeConfig={studioModeConfig} />
          <textarea ref={canvasRef} className="lyrics-canvas" style={{ fontSize: `${canvasFontSize}px` }} value={canvas} onChange={(event) => setCanvas(event.target.value)} placeholder={studioModeConfig.placeholder} />

          {!(focusMode && focusLayout === 'side') && renderLocalChat()}
        </div>

        {focusMode && focusLayout === 'side' && (
          <div className="focus-side-chat-panel">
            {renderLocalChat()}
          </div>
        )}

        <aside className="chat-panel improved-chat-panel global-helper-card">
          <div className="chat-topline"><Bot size={18} /><strong>Globale KI-Hilfe</strong></div>
          <p className="muted">Für freie Arbeit am {studioModeConfig.canvasNoun} nutzt du den gespeicherten KI-Chat direkt am Canvas. Die globale Hilfe bleibt für seitenübergreifende Aktionen verfügbar.</p>
          <details className="advanced-ai-settings">
            <summary>Erweiterte KI-Einstellungen</summary>
            <div className="form-grid compact-grid">
              <label>Profil<select value={profileId} onChange={(event) => setProfileId(event.target.value)}><option value="">Default</option>{profiles.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
              <label>Provider
                <select value={provider} onChange={(event) => changeAiProvider(event.target.value)}>
                  {aiProviderOptions.map((item) => {
                    const configured = aiConfig?.providers?.[item]?.configured;
                    return <option key={item} value={item}>{providerLabels[item] || item}{configured ? '' : ' · kein Key'}</option>;
                  })}
                </select>
              </label>
              <label className="wide">Modell
                {aiModelOptions.length ? (
                  <select value={model} onChange={(event) => setModel(event.target.value)}>
                    {aiModelOptions.map((item) => <option key={item} value={item}>{item}</option>)}
                  </select>
                ) : (
                  <input value={model} onChange={(event) => setModel(event.target.value)} />
                )}
              </label>
            </div>
          </details>
          <div className="quick-prompts dummy-action-grid">
            {activeQuickPrompts.map(([label, prompt]) => (
              <button key={label} type="button" onClick={() => askGlobalAssistant(prompt, label.includes('Suno') ? 'lyrics_suno_ready' : label.includes('Doubletime') ? 'lyrics_doubletime' : label.includes('Hook') ? 'lyrics_hook' : label.includes('Reime') ? 'lyrics_rhyme' : label.includes('härter') || label.includes('Punchlines') ? 'lyrics_make_harder' : null)}><Sparkles size={14} /> {label}</button>
            ))}
          </div>
          <div className="panel slim-panel helper-note">
            <strong>{studioMode === 'instrumental_blueprint' ? 'Hinweis zum Instrumental-Modus' : 'SunoAPI Lyrics'}</strong>
            <p>{studioMode === 'instrumental_blueprint' ? 'Dieser Modus erstellt Baupläne für Instrumentals ohne Lyrics. Zum direkten SunoAPI-Lyrics-Generator wechselst du in den Songtext-Modus.' : 'Optional kannst du Songtexte direkt über die SunoAPI erzeugen. Verwendet wird zuerst das Nachrichtenfeld, sonst der Canvas oder der Session-Titel.'}</p>
            {studioMode !== 'instrumental_blueprint' && (
              <button type="button" className="primary" disabled={sunoLyricsLoading} onClick={generateLyricsWithSunoAPI}>
                <Sparkles size={14} /> {sunoLyricsLoading ? 'Lyrics werden gestartet…' : 'Lyrics über SunoAPI erstellen'}
              </button>
            )}
          </div>
          <div className="panel slim-panel helper-note">
            <strong>Dummy-Modus</strong>
            <p>Schreibe unten rechts einfach: „Mach den Song Suno-ready“ oder „Was ist der nächste Schritt?“. Änderungen erscheinen direkt als Canvas-Vorschau mit Übernehmen/Verwerfen. Nach dem Übernehmen funktionieren Undo und Redo über die Session-Historie.</p>
          </div>
          {messages.length > 0 && <p className="muted">Alte Session-Verläufe bleiben erhalten und können weiterhin über „Session öffnen“ geladen werden.</p>}
        </aside>
      </div>

      <Modal
        open={chatModalOpen}
        title={chatModalMode === 'workbench' ? `Fokus-Arbeitsplatz: Canvas + KI-Chat · ${studioModeConfig.label}` : studioModeConfig.chatTitle}
        onClose={() => setChatModalOpen(false)}
        wide
        cardClassName="resizable-lyrics-modal"
        contentClassName="resizable-lyrics-modal-content"
        cardStyle={{
          width: `min(${chatModalSize.width}px, calc(100vw - 32px))`,
          height: `min(${chatModalSize.height}px, calc(100vh - 32px))`,
        }}
      >
        {chatModalMode === 'workbench' ? (
          <div className="lyrics-modal-workbench">
            <section className="lyrics-modal-canvas-pane">
              <div className="row between align-start canvas-panel-header">
                <div>
                  <h3>Canvas · {studioModeConfig.label}</h3>
                  <p className="muted">{canvas.length} Zeichen · {lineCount(canvas)} Zeilen</p>
                </div>
                <div className="button-row wrap canvas-tools">
                  {renderTextSizeControls('canvas')}
                  {renderSongtextImportControls({ compact: true })}
                  <button type="button" onClick={async () => { await copyToClipboard(canvas); notify('Canvas kopiert.', 'success'); }}><Copy size={15} /> Kopieren</button>
                </div>
              </div>
              <CanvasSectionMap sections={canvasSections} onJump={(section) => jumpToCanvasSection(section, modalCanvasRef)} modeConfig={studioModeConfig} />
              <textarea
                ref={modalCanvasRef}
                className="lyrics-canvas lyrics-modal-canvas"
                style={{ fontSize: `${canvasFontSize}px` }}
                value={canvas}
                onChange={(event) => setCanvas(event.target.value)}
                placeholder={studioModeConfig.placeholder}
              />
            </section>
            <section className="lyrics-modal-chat-pane">
              {renderLocalChat({ modal: true })}
            </section>
          </div>
        ) : renderLocalChat({ modal: true })}
      </Modal>

      <section className="panel tag-section">
        <div className="row between">
          <div><h2>{studioMode === 'instrumental_blueprint' ? 'Vocal Tags' : 'Vocal Tags'}</h2><p className="muted">{studioMode === 'instrumental_blueprint' ? 'Im Instrumental-Bauplan-Modus bleiben Vocal Tags optional. Nutze sie nur, wenn sie als Strukturhilfe dienen.' : 'Klick fügt den Tag direkt in den Canvas ein.'}</p></div>
          <input className="search small-search" placeholder="Tags filtern…" value={tagFilter} onChange={(event) => setTagFilter(event.target.value)} />
        </div>
        <div className="tag-cloud">
          {filteredTags.map((tag) => <button key={tag.id || tag.tag} type="button" onClick={() => insertTag(tag)} title={tag.description || tag.tag}>{tag.label || tag.tag}</button>)}
        </div>
      </section>
    </section>
  );
}
