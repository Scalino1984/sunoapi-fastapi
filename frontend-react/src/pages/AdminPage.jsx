import React, { useEffect, useMemo, useState } from 'react';
import { Bot, CheckCircle2, Download, FileText, Plus, RefreshCcw, Save, Tag, TestTube2, Trash2, Upload, UserRound } from 'lucide-react';
import { api } from '../api/client.js';
import { SectionHeader } from '../components/SectionHeader.jsx';
import { downloadTextFile } from '../utils.js';

function defaultModelForProvider(settings, provider) {
  const models = settings?.allowed_models?.[provider] || [];
  if (models.includes(settings?.default_model)) return settings.default_model;
  return models[0] || '';
}

function providerOptions(settings) {
  return Object.keys(settings?.allowed_models || { openai: [], openrouter: [], gemini: [], groq: [] });
}

function providerLabel(settings, provider) {
  const configured = settings?.providers?.[provider]?.configured;
  const state = configured === true ? 'bereit' : configured === false ? 'nicht konfiguriert' : 'unbekannt';
  return `${provider} · ${state}`;
}

export function AdminPage({ notify }) {
  const [users, setUsers] = useState([]);
  const [settings, setSettings] = useState(null);
  const [profiles, setProfiles] = useState([]);
  const [instructionFiles, setInstructionFiles] = useState([]);
  const [vocalTags, setVocalTags] = useState([]);
  const [activePanel, setActivePanel] = useState('assistant');
  const [saving, setSaving] = useState(false);
  const [newTag, setNewTag] = useState({ label: '', tag: '', category: 'Vocal Tags', description: '', sort_order: 100, is_active: true });
  const [newFile, setNewFile] = useState({ title: '', content: '', description: '', is_active: true });
  const [newProfile, setNewProfile] = useState({
    name: '',
    description: '',
    provider: 'openai',
    model: 'GPT-5.4-mini',
    system_instruction: '',
    response_format_instruction: '',
    temperature: '',
    max_output_tokens: '',
    is_active: true,
    is_default: false,
    linked_file_ids: []
  });

  useEffect(() => { load(); }, []);
  useEffect(() => {
    function handleOpenPrompts() {
      setActivePanel('assistant');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
    window.addEventListener('assistant:admin-open-prompts', handleOpenPrompts);
    return () => window.removeEventListener('assistant:admin-open-prompts', handleOpenPrompts);
  }, []);

  async function load() {
    const [u, s, p, files, tags] = await Promise.all([
      api.admin.users(),
      api.admin.aiSettings(),
      api.admin.profiles(),
      api.admin.instructionFiles(),
      api.admin.vocalTags()
    ]);
    const safeSettings = s || {};
    setUsers(u || []);
    setSettings(safeSettings);
    setProfiles(p || []);
    setInstructionFiles(files || []);
    setVocalTags(tags || []);
    setNewProfile((prev) => {
      const provider = prev.provider || safeSettings.default_provider || 'openai';
      const model = prev.model || defaultModelForProvider(safeSettings, provider);
      return { ...prev, provider, model };
    });
  }

  async function toggleUser(user) {
    await api.admin.updateUser(user.id, { is_active: !user.is_active });
    notify('Benutzer aktualisiert.', 'success');
    load();
  }

  async function renameUser(user) {
    const nickname = prompt('Spitzname', user.nickname || user.email.split('@')[0]);
    if (nickname === null) return;
    await api.admin.updateUser(user.id, { nickname: nickname.trim() || null });
    notify('Spitzname aktualisiert.', 'success');
    load();
  }

  async function saveAssistantSettings(patch = {}) {
    if (!settings) return;
    setSaving(true);
    try {
      const next = { ...settings, ...patch };
      await api.admin.saveAiSettings({
        default_provider: next.default_provider || 'openai',
        default_model: next.default_model || defaultModelForProvider(settings, next.default_provider || 'openai'),
        default_assistant_profile_id: next.default_assistant_profile_id ? Number(next.default_assistant_profile_id) : null,
        system_instruction: next.system_instruction || '',
        transcription_backend: next.transcription_backend || 'voxtral',
        transcription_language: next.transcription_language || 'de',
        lyrics_template_mode: 'lyrics_source_of_truth',
        lyrics_match_mode: 'lenient',
        srt_output_enabled: next.srt_output_enabled !== false,
        srt_auto_regenerate: Boolean(next.srt_auto_regenerate),
        srt_generate_vocal_stems_before_transcription: Boolean(next.srt_generate_vocal_stems_before_transcription),
        srt_ai_cleanup_enabled: next.srt_ai_display_optimization_enabled !== false && next.srt_ai_cleanup_enabled !== false,
        srt_ai_display_optimization_enabled: next.srt_ai_display_optimization_enabled !== false && next.srt_ai_cleanup_enabled !== false,
        library_content_polling_enabled: Boolean(next.library_content_polling_enabled),
        library_content_polling_interval_minutes: Math.max(1, Math.min(1440, Number(next.library_content_polling_interval_minutes || 15))),
        library_content_polling_limit: Math.max(10, Math.min(5000, Number(next.library_content_polling_limit || 500))),
        extend_auto_continue_at_enabled: Boolean(next.extend_auto_continue_at_enabled),
        extend_auto_continue_at_search_window_seconds: Math.max(5, Math.min(60, Number(next.extend_auto_continue_at_search_window_seconds || 15))),
        extend_auto_continue_at_vocal_threshold_ratio: Math.max(0.005, Math.min(0.25, Number(next.extend_auto_continue_at_vocal_threshold_ratio || 0.03))),
        extend_auto_continue_at_fallback_offset_seconds: Math.max(1, Math.min(30, Number(next.extend_auto_continue_at_fallback_offset_seconds || 4))),
        extend_auto_continue_at_timeout_seconds: Math.max(30, Math.min(1200, Number(next.extend_auto_continue_at_timeout_seconds || 180))),
        audio_ai_analysis_enabled: next.audio_ai_analysis_enabled !== false,
        audio_ai_analysis_ai_summary_enabled: next.audio_ai_analysis_ai_summary_enabled !== false,
        audio_ai_model_analysis_enabled: Boolean(next.audio_ai_model_analysis_enabled),
        audio_ai_analysis_max_seconds: Math.max(30, Math.min(1200, Number(next.audio_ai_analysis_max_seconds || 240))),
        audio_ai_model_analysis_seconds: Math.max(8, Math.min(90, Number(next.audio_ai_model_analysis_seconds || 30))),
        audio_ai_model_analysis_top_k: Math.max(5, Math.min(25, Number(next.audio_ai_model_analysis_top_k || 8))),
        library_ai_tagging_enabled: Boolean(next.library_ai_tagging_enabled),
        library_ai_tagging_profile_id: next.library_ai_tagging_profile_id ? Number(next.library_ai_tagging_profile_id) : null,
        library_ai_tagging_max_tags_per_asset: Math.max(2, Math.min(8, Number(next.library_ai_tagging_max_tags_per_asset || 5)))
      });
      notify('KI-Assistent gespeichert.', 'success');
      await load();
    } finally {
      setSaving(false);
    }
  }

  async function testProvider(provider = settings?.default_provider, model = settings?.default_model) {
    const result = await api.admin.testAi({ provider, model });
    notify(result.ok ? 'Provider-Test erfolgreich.' : result.error || 'Provider-Test fehlgeschlagen.', result.ok ? 'success' : 'error');
  }


  async function exportVocalTags(format = 'csv', mode = 'extended') {
    try {
      const content = await api.library.exportVocalTags(format, mode);
      const extension = format === 'markdown' || format === 'md' ? 'md' : 'csv';
      const mime = extension === 'md' ? 'text/markdown;charset=utf-8' : 'text/csv;charset=utf-8';
      downloadTextFile(`suno-vocal-tags-${mode}.${extension}`, content, mime);
      notify(`Vocal-Tags-${mode === 'extended' ? 'Detail' : 'Basis'}export wurde erstellt.`, 'success');
    } catch (err) {
      notify(err?.message || 'Vocal-Tags-Export fehlgeschlagen.', 'error');
    }
  }

  async function importVocalTagsFile(event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    try {
      const result = await api.library.importVocalTags(file);
      notify(`Vocal Tags importiert: ${result.imported || 0}, übersprungen: ${result.skipped || 0}.`, result.errors?.length ? 'info' : 'success');
      await load();
    } catch (err) {
      notify(err?.message || 'Vocal-Tags-Import fehlgeschlagen.', 'error');
    }
  }

  async function createTag() {
    if (!newTag.label || !newTag.tag) return notify('Label und Tag sind erforderlich.', 'error');
    await api.admin.createVocalTag(newTag);
    setNewTag({ label: '', tag: '', category: 'Vocal Tags', description: '', sort_order: 100, is_active: true });
    notify('Vocal Tag erstellt.', 'success');
    load();
  }

  async function updateTag(tag, patch) {
    await api.admin.updateVocalTag(tag.id, { ...tag, ...patch });
    notify('Vocal Tag aktualisiert.', 'success');
    load();
  }

  async function deleteTag(tag) {
    if (!confirm(`Vocal Tag wirklich löschen?\n\n${tag.label}`)) return;
    await api.admin.deleteVocalTag(tag.id);
    notify('Vocal Tag gelöscht.', 'success');
    load();
  }

  async function createFile() {
    if (!newFile.title || !newFile.content) return notify('Titel und Inhalt sind erforderlich.', 'error');
    await api.admin.createInstructionFile(newFile);
    setNewFile({ title: '', content: '', description: '', is_active: true });
    notify('Instruction-Datei gespeichert.', 'success');
    load();
  }

  async function deleteFile(file) {
    if (!confirm(`Instruction-Datei wirklich löschen?\n\n${file.title}`)) return;
    await api.admin.deleteInstructionFile(file.id);
    notify('Instruction-Datei gelöscht.', 'success');
    load();
  }

  async function createProfile() {
    if (!newProfile.name) return notify('Profilname fehlt.', 'error');
    const payload = {
      ...newProfile,
      temperature: newProfile.temperature === '' ? null : Number(newProfile.temperature),
      max_output_tokens: newProfile.max_output_tokens === '' ? null : Number(newProfile.max_output_tokens),
      linked_file_ids: newProfile.linked_file_ids.map(Number)
    };
    const created = await api.admin.createProfile(payload);
    setNewProfile({
      name: '',
      description: '',
      provider: settings?.default_provider || 'openai',
      model: defaultModelForProvider(settings, settings?.default_provider || 'openai') || 'GPT-5.4-mini',
      system_instruction: '',
      response_format_instruction: '',
      temperature: '',
      max_output_tokens: '',
      is_active: true,
      is_default: false,
      linked_file_ids: []
    });
    notify('KI-Profil erstellt.', 'success');
    await load();
    if (created?.is_default) {
      await saveAssistantSettings({ default_provider: created.provider, default_model: created.model, default_assistant_profile_id: created.id });
    }
  }

  async function setProfileDefault(profile) {
    await api.admin.updateProfile(profile.id, { is_default: true });
    await saveAssistantSettings({ default_provider: profile.provider, default_model: profile.model, default_assistant_profile_id: profile.id });
  }

  async function toggleProfile(profile) {
    await api.admin.updateProfile(profile.id, { is_active: !profile.is_active });
    notify('KI-Profil aktualisiert.', 'success');
    load();
  }

  async function deleteProfile(profile) {
    if (!confirm(`KI-Profil wirklich löschen?\n\n${profile.name}`)) return;
    await api.admin.deleteProfile(profile.id);
    notify('KI-Profil gelöscht.', 'success');
    load();
  }

  function changeDefaultProvider(provider) {
    const model = defaultModelForProvider(settings, provider);
    setSettings({ ...settings, default_provider: provider, default_model: model });
  }

  function changeNewProfileProvider(provider) {
    setNewProfile({ ...newProfile, provider, model: defaultModelForProvider(settings, provider) });
  }

  const panels = useMemo(() => [
    ['assistant', 'KI-Assistent', Bot],
    ['tags', 'Vocal Tags', Tag],
    ['users', 'Benutzer', UserRound]
  ], []);

  const defaultProfile = profiles.find((item) => Number(item.id) === Number(settings?.default_assistant_profile_id)) || profiles.find((item) => item.is_default);

  return (
    <section className="page stack admin-page">
      <SectionHeader eyebrow="Administration" title="Verwaltung" />
      <div className="admin-tabs panel slim-panel">
        {panels.map(([key, label, Icon]) => (
          <button key={key} className={activePanel === key ? 'active' : ''} type="button" onClick={() => setActivePanel(key)}><Icon size={16} /> {label}</button>
        ))}
      </div>

      {activePanel === 'users' && (
        <article className="panel">
          <h2>Benutzer</h2>
          <p className="muted">Jeder aktive Benutzer kann alle Bereiche nutzen. Es gibt keine rollenbasierte Sichtbarkeit.</p>
          <div className="admin-table">
            {users.map((user) => (
              <div className="admin-table-row" key={user.id}>
                <span><strong>{user.nickname || user.email.split('@')[0]}</strong><br /><small className="muted">{user.email}</small></span>
                <span className={`status ${user.is_active ? 'cached' : ''}`}>{user.is_active ? 'aktiv' : 'inaktiv'}</span>
                <button type="button" onClick={() => renameUser(user)}>Spitzname</button>
                <button type="button" onClick={() => toggleUser(user)}>{user.is_active ? 'Deaktivieren' : 'Aktivieren'}</button>
              </div>
            ))}
          </div>
        </article>
      )}

      {activePanel === 'assistant' && settings && (
        <div className="admin-unified-grid">
          <article className="panel stack">
            <div className="panel-title-row">
              <div>
                <h2>KI-Assistent</h2>
                <p className="muted">Zentrale Konfiguration für den globalen KI-Assistenten. Provider, Modell, GPT-ähnliche Profile, Prompt-Bausteine und verknüpfte Instructions werden hier gemeinsam verwaltet.</p>
              </div>
              <button type="button" onClick={load}><RefreshCcw size={16} /> Aktualisieren</button>
            </div>

            <div className="form-grid compact-grid">
              <label>Default-Profil
                <select
                  value={settings.default_assistant_profile_id || ''}
                  onChange={(event) => {
                    const value = event.target.value;
                    const profile = profiles.find((item) => String(item.id) === String(value));
                    setSettings({
                      ...settings,
                      default_assistant_profile_id: value ? Number(value) : null,
                      default_provider: profile?.provider || settings.default_provider,
                      default_model: profile?.model || settings.default_model
                    });
                  }}
                >
                  <option value="">Kein Profil / globale Defaults</option>
                  {profiles.filter((item) => item.is_active).map((profile) => <option key={profile.id} value={profile.id}>{profile.name} · {profile.provider} / {profile.model}</option>)}
                </select>
              </label>
              <label>Provider
                <select value={settings.default_provider || 'openai'} onChange={(event) => changeDefaultProvider(event.target.value)}>
                  {providerOptions(settings).map((provider) => <option key={provider} value={provider}>{providerLabel(settings, provider)}</option>)}
                </select>
              </label>
              <label>Modell
                <select value={settings.default_model || ''} onChange={(event) => setSettings({ ...settings, default_model: event.target.value })}>
                  {(settings.allowed_models?.[settings.default_provider || 'openai'] || []).map((model) => <option key={model} value={model}>{model}</option>)}
                </select>
              </label>
              <label className="wide">Globale Systemanweisung
                <textarea className="large" value={settings.system_instruction || ''} onChange={(event) => setSettings({ ...settings, system_instruction: event.target.value })} placeholder="Gilt für alle KI-Profile zusätzlich zu den festen Sicherheits- und Dummy-Regeln des globalen Assistenten." />
              </label>
              <div className="wide transcript-settings-card">
                <div>
                  <h3>1-Click-SRT-Erzeugung</h3>
                  <p className="muted">Zentrale Auswahl für Library-Songs. Lyrics bleiben Source of Truth, Match Mode ist fest auf Lenient gesetzt.</p>
                </div>
                <div className="form-grid compact-grid">
                  <label>Transkriptionsmodell
                    <select value={settings.transcription_backend || 'voxtral'} onChange={(event) => setSettings({ ...settings, transcription_backend: event.target.value })}>
                      {(settings.transcription_backends || ['groq', 'whisperx', 'openai_whisper_api', 'voxtral']).map((backend) => {
                        const configured = settings.transcription_runtime?.[backend]?.configured;
                        return <option key={backend} value={backend}>{backend}{configured ? ' · bereit' : ' · nicht konfiguriert'}</option>;
                      })}
                    </select>
                  </label>
                  <label>Sprache
                    <select value={settings.transcription_language || 'de'} onChange={(event) => setSettings({ ...settings, transcription_language: event.target.value })}>
                      {(settings.transcription_languages || ['auto', 'de', 'en']).map((language) => <option key={language} value={language}>{language}</option>)}
                    </select>
                  </label>
                  <label>Template Mode
                    <input value="Source of Truth" readOnly />
                  </label>
                  <label>Match Mode
                    <input value="Lenient" readOnly />
                  </label>
                  <label className="check"><input type="checkbox" checked={settings.srt_output_enabled !== false} onChange={(event) => setSettings({ ...settings, srt_output_enabled: event.target.checked })} /> SRT-Erzeugung aktiv</label>
                  <label className="check"><input type="checkbox" checked={Boolean(settings.srt_auto_regenerate)} onChange={(event) => setSettings({ ...settings, srt_auto_regenerate: event.target.checked })} /> Bestehende SRTs bei Bedarf überschreiben</label>
                  <label className="check"><input type="checkbox" checked={Boolean(settings.srt_generate_vocal_stems_before_transcription)} onChange={(event) => setSettings({ ...settings, srt_generate_vocal_stems_before_transcription: event.target.checked })} /> Vocal-Stems vor SRT automatisch erzeugen</label>
                  <label className="check srt-ai-display-option">
                    <input
                      type="checkbox"
                      checked={settings.srt_ai_display_optimization_enabled !== false && settings.srt_ai_cleanup_enabled !== false}
                      onChange={(event) => setSettings({ ...settings, srt_ai_cleanup_enabled: event.target.checked, srt_ai_display_optimization_enabled: event.target.checked })}
                    />
                    <span>
                      Songtexte extra für SRT-Anzeige per KI optimieren
                      <small>Entfernt Regie-, SFX-, Struktur- und Prompt-Hinweise; normalisiert außerdem Suno-Dehn-/Phonetik-Schreibweisen wie haaastla, hustlaaa, hust-laa oder romantig für lesbare Untertitel.</small>
                    </span>
                  </label>
                  <label className="check"><input type="checkbox" checked={Boolean(settings.library_content_polling_enabled)} onChange={(event) => setSettings({ ...settings, library_content_polling_enabled: event.target.checked })} /> Fehlende Library-Inhalte im Hintergrund prüfen</label>
                  <label>Polling-Intervall Minuten
                    <input type="number" min="1" max="1440" value={settings.library_content_polling_interval_minutes || 15} onChange={(event) => setSettings({ ...settings, library_content_polling_interval_minutes: event.target.value })} />
                  </label>
                  <label>Polling-Limit Inhalte
                    <input type="number" min="10" max="5000" value={settings.library_content_polling_limit || 500} onChange={(event) => setSettings({ ...settings, library_content_polling_limit: event.target.value })} />
                  </label>
                  <label className="check"><input type="checkbox" checked={Boolean(settings.extend_auto_continue_at_enabled)} onChange={(event) => setSettings({ ...settings, extend_auto_continue_at_enabled: event.target.checked })} /> Extend: continueAt automatisch per Audioanalyse berechnen</label>
                  <label>Extend-Suchfenster Sekunden
                    <input type="number" min="5" max="60" value={settings.extend_auto_continue_at_search_window_seconds || 15} onChange={(event) => setSettings({ ...settings, extend_auto_continue_at_search_window_seconds: event.target.value })} />
                  </label>
                  <label>Vocal-Schwelle
                    <input type="number" min="0.005" max="0.25" step="0.005" value={settings.extend_auto_continue_at_vocal_threshold_ratio || 0.03} onChange={(event) => setSettings({ ...settings, extend_auto_continue_at_vocal_threshold_ratio: event.target.value })} />
                  </label>
                  <label>Fallback vor Ende Sekunden
                    <input type="number" min="1" max="30" step="0.5" value={settings.extend_auto_continue_at_fallback_offset_seconds || 4} onChange={(event) => setSettings({ ...settings, extend_auto_continue_at_fallback_offset_seconds: event.target.value })} />
                  </label>
                  <label>Analyse-Timeout Sekunden
                    <input type="number" min="30" max="1200" value={settings.extend_auto_continue_at_timeout_seconds || 180} onChange={(event) => setSettings({ ...settings, extend_auto_continue_at_timeout_seconds: event.target.value })} />
                  </label>
                </div>
              </div>
              <div className="wide transcript-settings-card audio-ai-admin-card">
                <div>
                  <h3>Lokale Audioanalyse</h3>
                  <p className="muted">Steuert die Analyse-Reports in den Library-Songdetails. Alle Artefakte bleiben im App-Storage; Modellcache: <code>{settings.audio_ai_model_cache_dir || 'storage/models/huggingface'}</code>.</p>
                </div>
                <div className="form-grid compact-grid">
                  <label className="check">
                    <input type="checkbox" checked={settings.audio_ai_analysis_enabled !== false} onChange={(event) => setSettings({ ...settings, audio_ai_analysis_enabled: event.target.checked })} />
                    Audioanalyse in der Library aktivieren
                  </label>
                  <label className="check">
                    <input type="checkbox" checked={settings.audio_ai_analysis_ai_summary_enabled !== false} onChange={(event) => setSettings({ ...settings, audio_ai_analysis_ai_summary_enabled: event.target.checked })} />
                    Report durch bestehendes KI-System aufbereiten
                  </label>
                  <label className="check">
                    <input type="checkbox" checked={Boolean(settings.audio_ai_model_analysis_enabled)} onChange={(event) => setSettings({ ...settings, audio_ai_model_analysis_enabled: event.target.checked })} />
                    Interne Modellanalyse aktivieren
                  </label>
                  <label className="check">
                    <input type="checkbox" checked={Boolean(settings.audio_ai_acoustid_configured)} readOnly />
                    AcoustID API-Key {settings.audio_ai_acoustid_configured ? 'konfiguriert' : 'nicht konfiguriert'}
                  </label>
                  <label>Basisanalyse max. Sekunden
                    <input type="number" min="30" max="1200" value={settings.audio_ai_analysis_max_seconds || 240} onChange={(event) => setSettings({ ...settings, audio_ai_analysis_max_seconds: event.target.value })} />
                  </label>
                  <label>Modellanalyse Clip-Sekunden
                    <input type="number" min="8" max="90" value={settings.audio_ai_model_analysis_seconds || 30} onChange={(event) => setSettings({ ...settings, audio_ai_model_analysis_seconds: event.target.value })} />
                  </label>
                  <label>Modell Top-K Treffer
                    <input type="number" min="5" max="25" value={settings.audio_ai_model_analysis_top_k || 8} onChange={(event) => setSettings({ ...settings, audio_ai_model_analysis_top_k: event.target.value })} />
                  </label>
                  <p className="muted wide">Bei deaktivierter Modellanalyse bleiben Tempo, Signal, Copyright-Fingerprint und lokale Heuristiken erhalten. Bei aktivierter Modellanalyse können erste Läufe länger dauern, weil Modelle in den App-Storage geladen werden.</p>
                </div>
              </div>
              <div className="wide transcript-settings-card">
                <div>
                  <h3>KI-Library-Tags</h3>
                  <p className="muted">Optionales Tagging fuer Library-Suche und Filter. Die Funktion nutzt das bestehende KI-System und speichert nur kompakte Tags in den lokalen AudioAsset-Metadaten.</p>
                </div>
                <div className="form-grid compact-grid">
                  <label className="check">
                    <input type="checkbox" checked={Boolean(settings.library_ai_tagging_enabled)} onChange={(event) => setSettings({ ...settings, library_ai_tagging_enabled: event.target.checked })} />
                    KI-Tags in der Library aktivieren
                  </label>
                  <label>Tagging-Profil
                    <select value={settings.library_ai_tagging_profile_id || ''} onChange={(event) => setSettings({ ...settings, library_ai_tagging_profile_id: event.target.value ? Number(event.target.value) : null })}>
                      <option value="">Default-Profil / globale KI-Einstellung</option>
                      {profiles.filter((item) => item.is_active).map((profile) => <option key={profile.id} value={profile.id}>{profile.name} · {profile.provider} / {profile.model}</option>)}
                    </select>
                  </label>
                  <label>Max. Tags pro Song
                    <input type="number" min="2" max="8" value={settings.library_ai_tagging_max_tags_per_asset || 5} onChange={(event) => setSettings({ ...settings, library_ai_tagging_max_tags_per_asset: event.target.value })} />
                  </label>
                  <p className="muted wide">Die Tags werden bewusst klein gehalten und ueber die zentrale Header-Suche gefunden. Einzel- und Sammellaeufe starten aus der Library und erscheinen auf der Statusseite.</p>
                </div>
              </div>
              <div className="form-actions wide">
                <button className="primary" type="button" onClick={() => saveAssistantSettings()} disabled={saving}><Save size={16} /> Speichern</button>
                <button type="button" onClick={() => testProvider()}><TestTube2 size={16} /> Provider testen</button>
              </div>
            </div>
            {defaultProfile && <p className="muted">Aktives Default-Profil: <strong>{defaultProfile.name}</strong></p>}
          </article>

          <article className="panel stack">
            <h2>KI-Profil erstellen</h2>
            <div className="form-grid">
              <input placeholder="Profilname" value={newProfile.name} onChange={(event) => setNewProfile({ ...newProfile, name: event.target.value })} />
              <input placeholder="Beschreibung" value={newProfile.description} onChange={(event) => setNewProfile({ ...newProfile, description: event.target.value })} />
              <select value={newProfile.provider} onChange={(event) => changeNewProfileProvider(event.target.value)}>
                {providerOptions(settings).map((provider) => <option key={provider} value={provider}>{providerLabel(settings, provider)}</option>)}
              </select>
              <select value={newProfile.model} onChange={(event) => setNewProfile({ ...newProfile, model: event.target.value })}>
                {(settings.allowed_models?.[newProfile.provider] || []).map((model) => <option key={model} value={model}>{model}</option>)}
              </select>
              <input type="number" step="0.1" min="0" max="2" placeholder="Temperature optional" value={newProfile.temperature} onChange={(event) => setNewProfile({ ...newProfile, temperature: event.target.value })} />
              <input type="number" min="1" placeholder="Max Output Tokens optional" value={newProfile.max_output_tokens} onChange={(event) => setNewProfile({ ...newProfile, max_output_tokens: event.target.value })} />
              <label className="wide">Profil-Systemanweisung<textarea rows={7} value={newProfile.system_instruction} onChange={(event) => setNewProfile({ ...newProfile, system_instruction: event.target.value })} /></label>
              <label className="wide">Antwort-/Formatvorgaben<textarea rows={4} value={newProfile.response_format_instruction} onChange={(event) => setNewProfile({ ...newProfile, response_format_instruction: event.target.value })} /></label>
              <label className="wide">Verlinkte Instruction-Dateien
                <select multiple value={newProfile.linked_file_ids.map(String)} onChange={(event) => setNewProfile({ ...newProfile, linked_file_ids: Array.from(event.target.selectedOptions).map((option) => option.value) })}>
                  {instructionFiles.filter((file) => file.is_active).map((file) => <option key={file.id} value={file.id}>{file.title}</option>)}
                </select>
              </label>
              <label className="check"><input type="checkbox" checked={newProfile.is_default} onChange={(event) => setNewProfile({ ...newProfile, is_default: event.target.checked })} /> Als Default verwenden</label>
              <label className="check"><input type="checkbox" checked={newProfile.is_active} onChange={(event) => setNewProfile({ ...newProfile, is_active: event.target.checked })} /> Aktiv</label>
              <button className="primary" type="button" onClick={createProfile}>Profil erstellen</button>
            </div>
          </article>

          <article className="panel stack wide-panel">
            <h2>KI-Profile</h2>
            <div className="profile-grid">
              {profiles.map((profile) => (
                <div className="panel slim-panel" key={profile.id}>
                  <strong>{profile.name}</strong>
                  <p className="muted">{profile.provider} · {profile.model}{profile.is_default ? ' · Default' : ''}{profile.is_active ? '' : ' · inaktiv'}</p>
                  {profile.description && <p>{profile.description}</p>}
                  {profile.linked_files?.length > 0 && <p className="muted">Instructions: {profile.linked_files.map((file) => file.title).join(', ')}</p>}
                  <div className="inline-actions">
                    <button type="button" onClick={() => setProfileDefault(profile)}><CheckCircle2 size={15} /> Default</button>
                    <button type="button" onClick={() => testProvider(profile.provider, profile.model)}><TestTube2 size={15} /> Test</button>
                    <button type="button" onClick={() => toggleProfile(profile)}>{profile.is_active ? 'Deaktivieren' : 'Aktivieren'}</button>
                    <button type="button" className="danger" onClick={() => deleteProfile(profile)}><Trash2 size={15} /> Löschen</button>
                  </div>
                </div>
              ))}
            </div>
          </article>

          <article className="panel stack wide-panel">
            <h2>Instruction-Dateien</h2>
            <p className="muted">Diese Prompt-Bausteine werden mit KI-Profilen verlinkt. So kannst du mehrere Songwriting-Techniken, Befehle und Regeln kombinieren, ohne Code zu ändern.</p>
            <div className="form-grid compact-grid">
              <input placeholder="Titel" value={newFile.title} onChange={(event) => setNewFile({ ...newFile, title: event.target.value })} />
              <input placeholder="Beschreibung" value={newFile.description} onChange={(event) => setNewFile({ ...newFile, description: event.target.value })} />
              <label className="wide">Inhalt<textarea className="large" placeholder="Songwriting-Technik, Befehle, Regeln, Beispiele…" value={newFile.content} onChange={(event) => setNewFile({ ...newFile, content: event.target.value })} /></label>
              <label className="check"><input type="checkbox" checked={newFile.is_active} onChange={(event) => setNewFile({ ...newFile, is_active: event.target.checked })} /> Aktiv</label>
              <button className="primary" type="button" onClick={createFile}><Plus size={16} /> Datei speichern</button>
            </div>
            <div className="instruction-grid">
              {instructionFiles.map((file) => (
                <div className="panel slim-panel" key={file.id}>
                  <strong>{file.title}</strong>
                  <p className="muted">{file.description || 'Keine Beschreibung'}{file.is_active ? '' : ' · inaktiv'}</p>
                  <div className="inline-actions"><button type="button" className="danger" onClick={() => deleteFile(file)}><Trash2 size={15} /> Löschen</button></div>
                </div>
              ))}
            </div>
          </article>
        </div>
      )}

      {activePanel === 'tags' && (
        <article className="panel stack">
          <div className="panel-title-row">
            <div>
              <h2>Vocal Tags</h2>
              <p className="muted">Aktive Tags erscheinen im Songtext Studio und werden dem KI-Assistenten als strukturierter Kontext mitgegeben.</p>
            </div>
            <div className="inline-actions">
              <button type="button" onClick={() => exportVocalTags('csv', 'simple')}><Download size={15} /> Basis CSV</button>
              <button type="button" onClick={() => exportVocalTags('markdown', 'extended')}><FileText size={15} /> Details MD</button>
              <label className="button"><Upload size={15} /> Import<input type="file" accept=".csv,.md,.markdown,text/csv,text/markdown,text/plain" hidden onChange={importVocalTagsFile} /></label>
            </div>
          </div>
          <div className="form-grid compact-grid">
            <input placeholder="Label" value={newTag.label} onChange={(event) => setNewTag({ ...newTag, label: event.target.value })} />
            <input placeholder="[Verse 1 | German Male Rap | powerful]" value={newTag.tag} onChange={(event) => setNewTag({ ...newTag, tag: event.target.value })} />
            <input placeholder="Kategorie" value={newTag.category} onChange={(event) => setNewTag({ ...newTag, category: event.target.value })} />
            <input placeholder="Beschreibung" value={newTag.description} onChange={(event) => setNewTag({ ...newTag, description: event.target.value })} />
            <button className="primary" type="button" onClick={createTag}><Plus size={16} /> Tag hinzufügen</button>
          </div>
          <div className="tag-admin-list compact-vocal-tags">
            {vocalTags.map((tag) => (
              <div className="tag-admin-row compact-vocal-tag-row" key={tag.id}>
                <div className="vocal-tag-main"><strong>{tag.label}</strong><small className="muted">{tag.category}</small></div>
                <code title={tag.tag}>{tag.tag}</code>
                {tag.description && <small className="muted vocal-tag-description">{tag.description}</small>}
                <div className="inline-actions vocal-tag-actions">
                  <button type="button" onClick={() => updateTag(tag, { is_active: !tag.is_active })}>{tag.is_active ? 'Deaktivieren' : 'Aktivieren'}</button>
                  <button type="button" className="danger" onClick={() => deleteTag(tag)}><Trash2 size={15} /> Löschen</button>
                </div>
              </div>
            ))}
          </div>
        </article>
      )}
    </section>
  );
}
