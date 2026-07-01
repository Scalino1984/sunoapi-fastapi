import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Bot, Check, Copy, FileText, Maximize2, Minimize2, Redo2, Save, Sparkles, Trash2, Undo2 } from 'lucide-react';
import { Modal } from '../components/Modal.jsx';
import { api } from '../api/client.js';
import { SectionHeader } from '../components/SectionHeader.jsx';
import { FormattedMessage } from '../components/FormattedMessage.jsx';
import { copyToClipboard, lineCount, pickLyrics, pickPrompt, pickTitle, safeArray } from '../utils.js';
import { useAppAssistant } from '../context/AppAssistantContext.jsx';
import { useI18n } from '../i18n/I18nContext.jsx';

function getQuickPrompts(t) {
  return [
    [t('lyricsStudio.prompts.hook.label', 'Hook verbessern'), t('lyricsStudio.prompts.hook.prompt', 'Verbessere die Hook im Canvas mit mehr Wiedererkennungswert, klarer Melodieidee und Suno-kompatibler Struktur.'), 'lyrics_hook'],
    [t('lyricsStudio.prompts.harder.label', 'Verse härter machen'), t('lyricsStudio.prompts.harder.prompt', 'Überarbeite die Verse härter, direkter und druckvoller, ohne die Kernaussage zu verlieren.'), 'lyrics_make_harder'],
    [t('lyricsStudio.prompts.rhymes.label', 'Mehr Reime'), t('lyricsStudio.prompts.rhymes.prompt', 'Erhöhe die Reimdichte mit Binnenreimen, Doppelreimen und Kettenreimen.'), 'lyrics_rhyme'],
    [t('lyricsStudio.prompts.doubletime.label', 'Mehr Doubletime'), t('lyricsStudio.prompts.doubletime.prompt', 'Formatiere geeignete Stellen für schnelleren Rap/Doubletime und achte auf saubere Atempausen.'), 'lyrics_doubletime'],
    [t('lyricsStudio.prompts.emotion.label', 'Mehr Emotion'), t('lyricsStudio.prompts.emotion.prompt', 'Verstärke die emotionale Wirkung, Bilder und Spannungsbögen.'), null],
    [t('lyricsStudio.prompts.punchlines.label', 'Mehr Punchlines'), t('lyricsStudio.prompts.punchlines.prompt', 'Baue stärkere humorvolle oder harte Punchlines ein, passend zum vorhandenen Thema.'), 'lyrics_make_harder'],
    [t('lyricsStudio.prompts.sunoReady.label', 'Suno-kompatibel'), t('lyricsStudio.prompts.sunoReady.prompt', 'Formatiere den Canvas Suno-freundlich mit klaren Sections, Vocal Tags und sinnvollen Energieangaben.'), 'lyrics_suno_ready'],
    [t('lyricsStudio.prompts.vocalTags.label', 'Vocal Tags einfügen'), t('lyricsStudio.prompts.vocalTags.prompt', 'Ergänze passende Vocal Tags wie [Verse], [Chorus], [Bridge], Delivery, Energy und Stimmung.'), null],
    [t('lyricsStudio.prompts.structure.label', 'Songstruktur prüfen'), t('lyricsStudio.prompts.structure.prompt', 'Prüfe die Songstruktur und gib direkt eine verbesserte, verwendbare Version zurück.'), null],
    [t('lyricsStudio.prompts.bridge.label', 'Bridge ergänzen'), t('lyricsStudio.prompts.bridge.prompt', 'Ergänze eine passende Bridge mit Kontrast zur Hook.'), null],
    [t('lyricsStudio.prompts.shorten.label', 'Text kürzen'), t('lyricsStudio.prompts.shorten.prompt', 'Kürze den Canvas auf eine kompaktere, Suno-taugliche Version ohne Wirkung zu verlieren.'), null],
    [t('lyricsStudio.prompts.extend.label', 'Text verlängern'), t('lyricsStudio.prompts.extend.prompt', 'Erweitere den Song um sinnvolle Parts und behalte den roten Faden bei.'), null],
    [t('lyricsStudio.prompts.style.label', 'Style vorschlagen'), t('lyricsStudio.prompts.style.prompt', 'Schlage einen konkreten Suno Music Style mit Genre, BPM, Instrumentierung, Vocal-Vibe und Stimmung vor.'), null]
  ];
}

function getInstrumentalQuickPrompts(t) {
  return [
    [t('lyricsStudio.instrumentalPrompts.create.label', 'Bauplan erstellen'), t('lyricsStudio.instrumentalPrompts.create.prompt', 'Erstelle einen vollständigen instrumental nutzbaren Suno-Bauplan mit Timecodes, Abschnitten, Instrumentierung, Sounddesign, Builds, Drops, Breakdown und Outro. Keine Lyrics, keine gesungenen Zeilen.')],
    [t('lyricsStudio.instrumentalPrompts.dramaturgy.label', 'Mehr Dramaturgie'), t('lyricsStudio.instrumentalPrompts.dramaturgy.prompt', 'Verstärke den Spannungsbogen des Instrumental-Bauplans mit klaren Energiephasen, Breaks, Builds und Drops. Keine Lyrics.')],
    [t('lyricsStudio.instrumentalPrompts.sounddesign.label', 'Sounddesign ausbauen'), t('lyricsStudio.instrumentalPrompts.sounddesign.prompt', 'Erweitere den Bauplan um konkrete Sounddesign-Hinweise, Texturen, Drums, Bass, Lead-Instrumente und Übergänge. Keine Lyrics.')],
    [t('lyricsStudio.instrumentalPrompts.sunoReady.label', 'Suno-ready Instrumental'), t('lyricsStudio.instrumentalPrompts.sunoReady.prompt', 'Formatiere den Canvas als Suno-tauglichen Instrumental-Bauplan mit eckigen Timecode-Sektionen und kurzen präzisen Sound-Anweisungen. Keine Lyrics.')],
    [t('lyricsStudio.instrumentalPrompts.drops.label', 'Drops optimieren'), t('lyricsStudio.instrumentalPrompts.drops.prompt', 'Optimiere Drop-, Build-up- und Peak-Time-Abschnitte für maximale Wirkung und klare Instrumental-Struktur. Keine Lyrics.')],
    [t('lyricsStudio.instrumentalPrompts.shorten.label', 'Kürzer machen'), t('lyricsStudio.instrumentalPrompts.shorten.prompt', 'Kürze den Instrumental-Bauplan auf eine kompaktere, Suno-taugliche Version, ohne den Verlauf zu verlieren. Keine Lyrics.')]
  ];
}

function getStudioModes(t) {
  return {
  lyrics: {
    label: t('lyricsStudio.modes.lyrics.label', 'Songtext'),
    title: t('lyricsStudio.modes.lyrics.title', 'Songtext Studio'),
    chatTitle: t('lyricsStudio.modes.lyrics.chatTitle', 'KI-Chat zum Songtext'),
    canvasNoun: t('lyricsStudio.modes.lyrics.canvasNoun', 'Songtext'),
    saveLabel: t('lyricsStudio.modes.lyrics.saveLabel', 'Als Songtext speichern'),
    directMusicLabel: t('lyricsStudio.modes.lyrics.directMusicLabel', 'Direkt Musik generieren'),
    emptyHint: t('lyricsStudio.modes.lyrics.emptyHint', 'Frag nach Reimen, Struktur, Hook-Ideen, Suno-Tauglichkeit oder diskutiere erst den roten Faden. Der Canvas bleibt unverändert, bis du bewusst ausführst.'),
    placeholder: t('lyricsStudio.modes.lyrics.placeholder', 'Songtext hier schreiben oder KI bitten, den Canvas zu erstellen…'),
    chatPlaceholder: t('lyricsStudio.modes.lyrics.chatPlaceholder', 'Frei mit der KI diskutieren… Mit Strg+Enter senden, Strg+Shift+Enter als Canvas-Befehl ausführen.'),
    chapterEmpty: t('lyricsStudio.modes.lyrics.chapterEmpty', 'Vocal Tags wie [Verse], [Hook], [Chorus] oder [Bridge] werden hier automatisch als Sprungmarken angezeigt.'),
    chapterText: t('lyricsStudio.modes.lyrics.chapterText', 'erkannte Vocal-Tag-Kapitel'),
    saveNotice: t('lyricsStudio.modes.lyrics.saveNotice', 'Songtext und KI-Chat wurden gespeichert.'),
    musicNotice: t('lyricsStudio.modes.lyrics.musicNotice', 'Songtext wurde für Musik übernommen.')
  },
  instrumental_blueprint: {
    label: t('lyricsStudio.modes.instrumental.label', 'Instrumental-Bauplan'),
    title: t('lyricsStudio.modes.instrumental.title', 'Instrumental-Bauplan Studio'),
    chatTitle: t('lyricsStudio.modes.instrumental.chatTitle', 'KI-Chat zum Instrumental-Bauplan'),
    canvasNoun: t('lyricsStudio.modes.instrumental.canvasNoun', 'Bauplan'),
    saveLabel: t('lyricsStudio.modes.instrumental.saveLabel', 'Als Bauplan speichern'),
    directMusicLabel: t('lyricsStudio.modes.instrumental.directMusicLabel', 'Als Instrumental generieren'),
    emptyHint: t('lyricsStudio.modes.instrumental.emptyHint', 'Plane Arrangement, Timecodes, Instrumente, Sounddesign, Builds, Drops und Breakdowns. Der Canvas bleibt unverändert, bis du bewusst ausführst.'),
    placeholder: t('lyricsStudio.modes.instrumental.placeholder', 'Instrumental-Bauplan hier schreiben oder KI bitten, einen Timecode-Bauplan ohne Lyrics zu erstellen…'),
    chatPlaceholder: t('lyricsStudio.modes.instrumental.chatPlaceholder', 'Instrumental-Ideen diskutieren… Mit Strg+Enter senden, Strg+Shift+Enter als Canvas-Befehl ausführen.'),
    chapterEmpty: t('lyricsStudio.modes.instrumental.chapterEmpty', 'Timecode-Tags wie [0:00 - Intro], [1:00 - Build-up] oder [3:30 - Drop] werden hier automatisch als Sprungmarken angezeigt.'),
    chapterText: t('lyricsStudio.modes.instrumental.chapterText', 'erkannte Bauplan-Kapitel'),
    saveNotice: t('lyricsStudio.modes.instrumental.saveNotice', 'Instrumental-Bauplan und KI-Chat wurden gespeichert.'),
    musicNotice: t('lyricsStudio.modes.instrumental.musicNotice', 'Instrumental-Bauplan wurde für Musik übernommen.')
  }
  };
}

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

function buildCanvasImportSources(lyrics = [], assets = [], t = null) {
  const draftSources = safeArray(lyrics, ['lyrics', 'items'])
    .map((item) => {
      const content = sourceContentFromLyricDraft(item);
      if (!content) return null;
      return {
        id: `lyric-${item.id}`,
        sourceType: 'lyric',
        sourceId: item.id,
        title: item.title || t?.('lyricsStudio.import.savedLyrics', 'Gespeicherter Songtext') || 'Gespeicherter Songtext',
        label: `${t?.('lyricsStudio.modes.lyrics.label', 'Songtext') || 'Songtext'} · ${item.title || `#${item.id}`}`,
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

function CanvasSectionMap({ sections, onJump, modeConfig, t }) {
  if (!sections.length) {
    return (
      <div className="canvas-section-map empty">
        <div>
          <strong>{t('lyricsStudio.chapterMiniView', 'Kapitel-Miniansicht')}</strong>
          <p className="muted">{modeConfig.chapterEmpty}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="canvas-section-map">
      <div className="canvas-section-map-head">
        <div>
          <strong>{t('lyricsStudio.chapterMiniView', 'Kapitel-Miniansicht')}</strong>
          <p className="muted">{sections.length} {modeConfig.chapterText} · {t('lyricsStudio.jumpHint', 'Klick springt direkt zur Stelle im Canvas.')}</p>
        </div>
        <div className="canvas-section-legend" aria-label={t('lyricsStudio.colorGroups', 'Farbgruppen')}>
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
            title={`${section.fullTag} · ${t('lyricsStudio.lineShort', 'Zeile')} ${section.line + 1}`}
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
  const { t } = useI18n();
  const [sessions, setSessions] = useState([]);
  const [profiles, setProfiles] = useState([]);
  const [aiConfig, setAiConfig] = useState(null);
  const [vocalTags, setVocalTags] = useState([]);
  const [session, setSession] = useState(null);
  const [canvas, setCanvas] = useState('');
  const [message, setMessage] = useState('');
  const [sessionTitle, setSessionTitle] = useState(t('lyricsStudio.newSession', 'Neue Session'));
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
  const studioModes = useMemo(() => getStudioModes(t), [t]);
  const studioModeConfig = studioModes[studioMode] || studioModes.lyrics;
  const activeQuickPrompts = useMemo(() => studioMode === 'instrumental_blueprint' ? getInstrumentalQuickPrompts(t) : getQuickPrompts(t), [studioMode, t]);
  const canvasImportSources = useMemo(() => buildCanvasImportSources(lyrics, assets, t), [lyrics, assets, t]);
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
        summary: event.detail?.changeSummary || event.detail?.summary || t('lyricsStudio.messages.previewPrepared', 'KI-Vorschau vorbereitet'),
        createdAt: event.detail?.createdAt || new Date().toISOString(),
        sourceMessage: event.detail?.sourceMessage || ''
      });
      notify(t('lyricsStudio.messages.previewReady', 'KI-Vorschau liegt direkt am Canvas bereit.'), 'success');
    }
    async function handleApplyPreview(event) {
      const proposed = event.detail?.proposedCanvas || event.detail?.text || assistantPreview?.text || '';
      if (!proposed.trim()) return;
      await applyAssistantPreview(proposed, event.detail?.changeSummary || event.detail?.summary || assistantPreview?.summary || t('lyricsStudio.messages.previewAppliedSummary', 'KI-Vorschau übernommen'));
    }
    function handleDiscardPreview() {
      setAssistantPreview(null);
      notify(t('lyricsStudio.messages.previewDiscardedTextIntact', 'KI-Vorschau verworfen. Der Songtext bleibt unverändert.'), 'info');
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
    notify(t('lyricsStudio.messages.sessionSaved', 'Session gespeichert.'), 'success');
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
    const updated = await api.ai.updateCanvas(session.id, canvas, { source: 'manual', change_summary: t('lyricsStudio.changeSummary.manualSaved', 'Manuell gespeichert') });
    setSession(updated);
    notify(t('lyricsStudio.messages.canvasSaved', 'Canvas gespeichert.'), 'success');
  }

  async function ensureSessionForCanvas() {
    if (session) {
      return await api.ai.updateCanvas(session.id, canvas, { source: 'manual', change_summary: t('lyricsStudio.changeSummary.beforeAiApply', 'Stand vor KI-Übernahme gesichert') });
    }
    const created = await api.ai.createSession({
      title: sessionTitle || t('lyricsStudio.aiCanvasSession', 'KI-Canvas-Session'),
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
      const updated = await api.ai.updateCanvas(active.id, proposed, { source: 'global_ai_assistant', change_summary: summary || t('lyricsStudio.messages.previewAppliedSummary', 'KI-Vorschau übernommen') });
      setSession(updated);
      setCanvas(updated.canvas_content || proposed);
      setAssistantPreview(null);
      notify(t('lyricsStudio.messages.previewApplied', 'KI-Vorschau wurde übernommen. Undo/Redo ist jetzt verfügbar.'), 'success');
      await load();
    } catch (err) {
      notify(err.message || t('lyricsStudio.messages.previewApplyFailed', 'KI-Vorschau konnte nicht übernommen werden.'), 'error');
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
        notify(t('lyricsStudio.messages.aiUpdatedCanvas', 'KI hat den Canvas aktualisiert.'), 'success');
      }
      setMessage('');
      await load();
    } catch (err) {
      notify(err.message || t('lyricsStudio.messages.aiRequestFailed', 'KI-Anfrage fehlgeschlagen.'), 'error');
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
        title: sessionTitle || (studioMode === 'instrumental_blueprint' ? studioModes.instrumental_blueprint.canvasNoun : studioModes.lyrics.canvasNoun),
        content: canvas,
        status: 'draft',
        language: 'de',
        tags: studioMode === 'instrumental_blueprint' ? 'instrumental,bauplan,no-lyrics' : undefined
      };
      const draft = draftId ? await api.library.updateLyric(draftId, payload) : await api.library.createLyric(payload);
      setDraftId(draft.id);
      if (session?.id) {
        const linked = await api.ai.updateSession(session.id, {
          title: sessionTitle || draft.title || t('lyricsStudio.songtextChat', 'Songtext-Chat'),
          lyric_draft_id: draft.id,
          canvas_content: canvas,
          work_mode: studioMode
        });
        setSession(linked);
      }
      notify(studioModeConfig.saveNotice, 'success');
      await onRefresh?.();
    } catch (err) {
      notify(err.message || t('lyricsStudio.messages.saveDraftFailed', 'Songtext konnte nicht gespeichert werden.'), 'error');
    }
  }

  async function clearLocalChat() {
    if (!session?.id) {
      setMessage('');
      notify(t('lyricsStudio.messages.noSavedSession', 'Noch keine gespeicherte KI-Session vorhanden.'), 'info');
      return;
    }
    try {
      const cleared = await api.ai.clearMessages(session.id);
      setSession(cleared);
      setMessage('');
      notify(t('lyricsStudio.messages.localChatCleared', 'Lokaler KI-Chat wurde geleert.'), 'success');
    } catch (err) {
      notify(err.message || t('lyricsStudio.messages.localChatClearFailed', 'Chat konnte nicht geleert werden.'), 'error');
    }
  }

  async function generateLyricsWithSunoAPI() {
    const sourcePrompt = String(message || canvas || sessionTitle || '').trim();
    if (!sourcePrompt) {
      notify(t('lyricsStudio.messages.promptMissing', 'Bitte gib zuerst ein Thema, eine Idee oder vorhandenen Text ein.'), 'error');
      return;
    }

    setSunoLyricsLoading(true);
    try {
      const task = await api.lyrics.generate({ prompt: sourcePrompt });
      notify(t('lyricsStudio.messages.sunoLyricsStarted', 'SunoAPI Lyrics-Generierung gestartet. Task: {{task}}…', { task: String(task?.task_id || task?.id || '').slice(0, 16) }), 'success');
      await onRefresh?.();
    } catch (err) {
      notify(err?.message || t('lyricsStudio.messages.sunoLyricsFailed', 'SunoAPI Lyrics-Generierung fehlgeschlagen.'), 'error');
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
        // Mode remains usable locally; it is sent again on the next save.
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
      notify(t('lyricsStudio.messages.noImportSource', 'Kein Songtext zum Übernehmen ausgewählt.'), 'error');
      return;
    }

    const currentText = String(canvas || '').trim();
    const nextCanvas = mode === 'append' && currentText
      ? `${canvas.replace(/\s*$/u, '')}\n\n${sourceText}`
      : sourceText;
    const nextTitle = source?.title || sessionTitle || studioModes.lyrics.canvasNoun;

    try {
      if (studioMode !== 'lyrics') setStudioMode('lyrics');
      setDraftId(source.sourceType === 'lyric' ? source.sourceId : null);
      if (!sessionTitle || sessionTitle === t('lyricsStudio.newSession', 'Neue Session')) setSessionTitle(nextTitle);

      if (session?.id) {
        const updated = await api.ai.updateCanvas(session.id, nextCanvas, {
          source: source.sourceType === 'asset' ? 'audio_asset_lyrics_import' : 'lyric_draft_import',
          change_summary: `${mode === 'append' ? t('lyricsStudio.changeSummary.lyricsAppended', 'Songtext angehängt') : t('lyricsStudio.changeSummary.lyricsImported', 'Songtext übernommen')}: ${nextTitle}`
        });
        setSession(updated);
        setCanvas(updated.canvas_content || nextCanvas);
      } else {
        setCanvas(nextCanvas);
      }
      notify(mode === 'append' ? t('lyricsStudio.messages.lyricsAppended', 'Songtext wurde an den Canvas angehängt.') : t('lyricsStudio.messages.lyricsImported', 'Songtext wurde in den Canvas übernommen.'), 'success');
    } catch (err) {
      notify(err.message || t('lyricsStudio.messages.lyricsImportFailed', 'Songtext konnte nicht in den Canvas übernommen werden.'), 'error');
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
          title={t('lyricsStudio.import.selectTitle', 'Gespeicherten Songtext oder Library-Songtext auswählen')}
        >
          {!canvasImportSources.length && <option value="">{t('lyricsStudio.import.empty', 'Keine Songtexte vorhanden')}</option>}
          {canvasImportSources.map((source) => (
            <option key={source.id} value={source.id}>{source.label}</option>
          ))}
        </select>
        <button type="button" onClick={() => applySelectedSongtextToCanvas('replace')} disabled={disabled}>
          <FileText size={15} /> {t('lyricsStudio.import.replaceButton', 'Songtext in Canvas')}
        </button>
        {!compact && (
          <button type="button" onClick={() => applySelectedSongtextToCanvas('append')} disabled={disabled}>
            {t('lyricsStudio.import.appendButton', 'Anhängen')}
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
      <div className="text-size-control" aria-label={t('lyricsStudio.textSizeAria', '{{kind}} Textgröße', { kind: kind === 'canvas' ? 'Canvas' : studioModeConfig.chatTitle })}>
        <button type="button" onClick={() => change(-1)} aria-label={t('lyricsStudio.textSmaller', 'Text kleiner')}>−</button>
        <span>{value}px</span>
        <button type="button" onClick={() => change(1)} aria-label={t('lyricsStudio.textLarger', 'Text größer')}>+</button>
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
            <p className="muted">{t('lyricsStudio.localChatIntro', 'Freie Diskussion wird gespeichert. Erst „Befehl ausführen“ verändert den Canvas und nutzt alle erarbeiteten Chat-Infos. Aktiver Modus: {{mode}}.', { mode: studioModeConfig.label })}</p>
          </div>
          <div className="button-row wrap local-chat-tools">
            {renderTextSizeControls('chat')}
            {!modal && (
              <>
                <button type="button" onClick={() => openChatModal('chat')}><Maximize2 size={15} /> {t('lyricsStudio.onlyAiChat', 'Nur KI-Chat')}</button>
                <button type="button" onClick={() => openChatModal('workbench')}><Maximize2 size={15} /> {t('lyricsStudio.canvasPlusChat', 'Canvas + Chat')}</button>
              </>
            )}
            {modal && <button type="button" onClick={resetChatModalSize}>{t('lyricsStudio.resetSize', 'Größe zurücksetzen')}</button>}
            <button type="button" onClick={clearLocalChat} disabled={!session}><Trash2 size={15} /> {t('lyricsStudio.clearChat', 'Chat leeren')}</button>
          </div>
        </div>

        <div className="chat-log local-chat-log">
          {messages.length === 0 && (
            <div className="chat-message assistant">
              <strong>{t('lyricsStudio.readyForIdeas', 'Bereit für freie Ideenarbeit.')}</strong>
              <p>{studioModeConfig.emptyHint}</p>
            </div>
          )}
          {messages.map((item) => (
            <div key={item.id} className={`chat-message ${item.role === 'user' ? 'user' : 'assistant'}`}>
              <strong>{item.role === 'user' ? t('lyricsStudio.you', 'Du') : t('lyricsStudio.ai', 'KI')}</strong>
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
          <button type="button" onClick={() => send(null, false)} disabled={loading || !message.trim()}>{t('lyricsStudio.sendChat', 'Chat senden')}</button>
          <button type="button" className="primary" onClick={() => send(null, true)} disabled={loading || !message.trim()}><Sparkles size={15} /> {t('lyricsStudio.executeCommand', 'Befehl ausführen')}</button>
          <button type="button" onClick={saveAsDraft}><Save size={15} /> {t('lyricsStudio.saveCanvasAndChat', '{{noun}} + Chat speichern', { noun: studioModeConfig.canvasNoun })}</button>
        </div>
      </div>
    );
  }

  return (
    <section className={`page stack lyrics-page ${focusMode ? 'focus-mode' : ''} ${focusMode ? `focus-layout-${focusLayout}` : ''}`}>
      <SectionHeader eyebrow={t('lyricsStudio.canvas', 'Canvas')} title={studioModeConfig.title}>
        <button type="button" onClick={() => setFocusMode(!focusMode)}>{focusMode ? <Minimize2 size={16} /> : <Maximize2 size={16} />} {focusMode ? t('lyricsStudio.studioView', 'Studio-Ansicht') : t('lyricsStudio.focusView', 'Fokus-Ansicht')}</button>
        {focusMode && (
          <button type="button" onClick={() => setFocusLayout(focusLayout === 'side' ? 'stack' : 'side')}>
            {focusLayout === 'side' ? t('lyricsStudio.chatBottom', 'Chat unten') : t('lyricsStudio.chatRight', 'Chat rechts')}
          </button>
        )}
      </SectionHeader>

      <div className="session-toolbar panel slim-panel">
        <input value={sessionTitle} onChange={(event) => setSessionTitle(event.target.value)} placeholder={t('lyricsStudio.sessionTitle', 'Session Titel')} />
        <div className="segmented-control studio-mode-toggle" role="group" aria-label={t('lyricsStudio.studioMode', 'Studio-Modus')}>
          {Object.entries(studioModes).map(([key, config]) => (
            <button key={key} type="button" className={studioMode === key ? 'active' : ''} onClick={() => switchStudioMode(key)}>{config.label}</button>
          ))}
        </div>
        <select value={session?.id || ''} onChange={(event) => openSession(event.target.value)}>
          <option value="">{t('lyricsStudio.openSession', 'Session öffnen…')}</option>
          {sessions.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
        </select>
        <button type="button" onClick={createSession}>{t('lyricsStudio.newSave', 'Neu/Speichern')}</button>
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
            <div><h2>Canvas · {studioModeConfig.label}</h2><p className="muted">{t('lyricsStudio.canvasStats', '{{chars}} Zeichen · {{lines}} Zeilen', { chars: canvas.length, lines: lineCount(canvas) })}</p></div>
            <div className="button-row wrap canvas-tools">
              {renderTextSizeControls('canvas')}
              {renderSongtextImportControls({ compact: true })}
              <button type="button" onClick={async () => { await copyToClipboard(canvas); notify(t('lyricsStudio.messages.canvasCopied', 'Canvas kopiert.'), 'success'); }}><Copy size={16} /> {t('common.copy', 'Kopieren')}</button>
            </div>
          </div>
          {assistantPreview && (
            <div className="canvas-ai-preview">
              <div className="row between">
                <div>
                  <strong>{t('lyricsStudio.aiPreviewAtCanvas', 'KI-Vorschau am Canvas')}</strong>
                  <p className="muted">{assistantPreview.summary}</p>
                </div>
                <div className="row wrap">
                  <button className="primary" type="button" onClick={() => applyAssistantPreview()}><Check size={15} /> {t('lyricsStudio.apply', 'Übernehmen')}</button>
                  <button type="button" onClick={() => { setAssistantPreview(null); notify(t('lyricsStudio.messages.previewDiscarded', 'KI-Vorschau verworfen.'), 'info'); }}><Trash2 size={15} /> {t('lyricsStudio.discard', 'Verwerfen')}</button>
                </div>
              </div>
              <textarea className="lyrics-canvas preview-canvas" style={{ fontSize: `${canvasFontSize}px` }} value={assistantPreview.text} onChange={(event) => setAssistantPreview((current) => ({ ...(current || {}), text: event.target.value }))} />
            </div>
          )}
          <CanvasSectionMap sections={canvasSections} onJump={jumpToCanvasSection} modeConfig={studioModeConfig} t={t} />
          <textarea ref={canvasRef} className="lyrics-canvas" style={{ fontSize: `${canvasFontSize}px` }} value={canvas} onChange={(event) => setCanvas(event.target.value)} placeholder={studioModeConfig.placeholder} />

          {!(focusMode && focusLayout === 'side') && renderLocalChat()}
        </div>

        {focusMode && focusLayout === 'side' && (
          <div className="focus-side-chat-panel">
            {renderLocalChat()}
          </div>
        )}

        <aside className="chat-panel improved-chat-panel global-helper-card">
          <div className="chat-topline"><Bot size={18} /><strong>{t('lyricsStudio.globalAiHelp', 'Globale KI-Hilfe')}</strong></div>
          <p className="muted">{t('lyricsStudio.globalAiIntro', 'Für freie Arbeit am {{noun}} nutzt du den gespeicherten KI-Chat direkt am Canvas. Die globale Hilfe bleibt für seitenübergreifende Aktionen verfügbar.', { noun: studioModeConfig.canvasNoun })}</p>
          <details className="advanced-ai-settings">
            <summary>{t('lyricsStudio.advancedAiSettings', 'Erweiterte KI-Einstellungen')}</summary>
            <div className="form-grid compact-grid">
              <label>Profil<select value={profileId} onChange={(event) => setProfileId(event.target.value)}><option value="">Default</option>{profiles.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
              <label>Provider
                <select value={provider} onChange={(event) => changeAiProvider(event.target.value)}>
                  {aiProviderOptions.map((item) => {
                    const configured = aiConfig?.providers?.[item]?.configured;
                    return <option key={item} value={item}>{providerLabels[item] || item}{configured ? '' : ` · ${t('lyricsStudio.noKey', 'kein Key')}`}</option>;
                  })}
                </select>
              </label>
              <label className="wide">{t('admin.assistant.model', 'Modell')}
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
            {activeQuickPrompts.map(([label, prompt, actionId]) => (
              <button key={label} type="button" onClick={() => askGlobalAssistant(prompt, actionId)}><Sparkles size={14} /> {label}</button>
            ))}
          </div>
          <div className="panel slim-panel helper-note">
            <strong>{studioMode === 'instrumental_blueprint' ? t('lyricsStudio.instrumentalHintTitle', 'Hinweis zum Instrumental-Modus') : 'SunoAPI Lyrics'}</strong>
            <p>{studioMode === 'instrumental_blueprint' ? t('lyricsStudio.instrumentalHintText', 'Dieser Modus erstellt Baupläne für Instrumentals ohne Lyrics. Zum direkten SunoAPI-Lyrics-Generator wechselst du in den Songtext-Modus.') : t('lyricsStudio.sunoLyricsIntro', 'Optional kannst du Songtexte direkt über die SunoAPI erzeugen. Verwendet wird zuerst das Nachrichtenfeld, sonst der Canvas oder der Session-Titel.')}</p>
            {studioMode !== 'instrumental_blueprint' && (
              <button type="button" className="primary" disabled={sunoLyricsLoading} onClick={generateLyricsWithSunoAPI}>
                <Sparkles size={14} /> {sunoLyricsLoading ? t('lyricsStudio.sunoLyricsStarting', 'Lyrics werden gestartet…') : t('lyricsStudio.createSunoLyrics', 'Lyrics über SunoAPI erstellen')}
              </button>
            )}
          </div>
          <div className="panel slim-panel helper-note">
            <strong>{t('lyricsStudio.dummyMode', 'Dummy-Modus')}</strong>
            <p>{t('lyricsStudio.dummyModeText', 'Schreibe unten rechts einfach: „Mach den Song Suno-ready“ oder „Was ist der nächste Schritt?“. Änderungen erscheinen direkt als Canvas-Vorschau mit Übernehmen/Verwerfen. Nach dem Übernehmen funktionieren Undo und Redo über die Session-Historie.')}</p>
          </div>
          {messages.length > 0 && <p className="muted">{t('lyricsStudio.oldSessionsHint', 'Alte Session-Verläufe bleiben erhalten und können weiterhin über „Session öffnen“ geladen werden.')}</p>}
        </aside>
      </div>

      <Modal
        open={chatModalOpen}
        title={chatModalMode === 'workbench' ? t('lyricsStudio.focusWorkbenchTitle', 'Fokus-Arbeitsplatz: Canvas + KI-Chat · {{mode}}', { mode: studioModeConfig.label }) : studioModeConfig.chatTitle}
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
                  <p className="muted">{t('lyricsStudio.canvasStats', '{{chars}} Zeichen · {{lines}} Zeilen', { chars: canvas.length, lines: lineCount(canvas) })}</p>
                </div>
                <div className="button-row wrap canvas-tools">
                  {renderTextSizeControls('canvas')}
                  {renderSongtextImportControls({ compact: true })}
                  <button type="button" onClick={async () => { await copyToClipboard(canvas); notify(t('lyricsStudio.messages.canvasCopied', 'Canvas kopiert.'), 'success'); }}><Copy size={15} /> {t('common.copy', 'Kopieren')}</button>
                </div>
              </div>
              <CanvasSectionMap sections={canvasSections} onJump={(section) => jumpToCanvasSection(section, modalCanvasRef)} modeConfig={studioModeConfig} t={t} />
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
          <div><h2>Vocal Tags</h2><p className="muted">{studioMode === 'instrumental_blueprint' ? t('lyricsStudio.vocalTagsInstrumentalHint', 'Im Instrumental-Bauplan-Modus bleiben Vocal Tags optional. Nutze sie nur, wenn sie als Strukturhilfe dienen.') : t('lyricsStudio.vocalTagsHint', 'Klick fügt den Tag direkt in den Canvas ein.')}</p></div>
          <input className="search small-search" placeholder={t('lyricsStudio.filterTags', 'Tags filtern…')} value={tagFilter} onChange={(event) => setTagFilter(event.target.value)} />
        </div>
        <div className="tag-cloud">
          {filteredTags.map((tag) => <button key={tag.id || tag.tag} type="button" onClick={() => insertTag(tag)} title={tag.description || tag.tag}>{tag.label || tag.tag}</button>)}
        </div>
      </section>
    </section>
  );
}
