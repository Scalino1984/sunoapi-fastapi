import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, BookOpen, Bot, CheckCircle2, ChevronDown, ChevronUp, Copy, Cpu, Download, Eye, FileCog, FileText, Info, Layers3, Music2, Pencil, Plus, RefreshCcw, Save, Search, Settings2, Sparkles, Tag, TestTube2, Trash2, Upload, UserRound, X } from 'lucide-react';
import { api } from '../api/client.js';
import { SectionHeader } from '../components/SectionHeader.jsx';
import { downloadTextFile } from '../utils.js';
import { useI18n } from '../i18n/I18nContext.jsx';
import { LibrarySearchIndexAdmin } from '../components/admin/LibrarySearchIndexAdmin.jsx';

function defaultModelForProvider(settings, provider) {
  const models = settings?.allowed_models?.[provider] || [];
  if (models.includes(settings?.default_model)) return settings.default_model;
  return models[0] || '';
}

function providerOptions(settings) {
  return Object.keys(settings?.allowed_models || { openai: [], openrouter: [], gemini: [], groq: [] });
}

function providerLabel(settings, provider, t = null) {
  const configured = settings?.providers?.[provider]?.configured;
  const state = configured === true
    ? t?.('admin.provider.ready', 'bereit') || 'bereit'
    : configured === false
      ? t?.('admin.provider.notConfigured', 'nicht konfiguriert') || 'nicht konfiguriert'
      : t?.('admin.provider.unknown', 'unbekannt') || 'unbekannt';
  return `${provider} · ${state}`;
}

export function AdminPage({ notify, onReload }) {
  const { t } = useI18n();
  const [users, setUsers] = useState([]);
  const [settings, setSettings] = useState(null);
  const [profiles, setProfiles] = useState([]);
  const [instructionFiles, setInstructionFiles] = useState([]);
  const [vocalTags, setVocalTags] = useState([]);
  const [dawPromptHooks, setDawPromptHooks] = useState([]);
  const [activePanel, setActivePanel] = useState('assistant');
  const [saving, setSaving] = useState(false);
  const [newTag, setNewTag] = useState({ label: '', tag: '', category: 'Vocal Tags', description: '', sort_order: 100, is_active: true });
  const [newDawPromptHook, setNewDawPromptHook] = useState({ title: '', prompt: '', description: '', scope: 'daw', sort_order: 100, is_active: true });
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
  const [assistantSection, setAssistantSection] = useState('overview');
  const [runtimeProfileId, setRuntimeProfileId] = useState('');
  const [runtimeInfo, setRuntimeInfo] = useState(null);
  const [runtimeLoading, setRuntimeLoading] = useState(false);
  const [runtimeError, setRuntimeError] = useState('');
  const [expandedProfileId, setExpandedProfileId] = useState(null);
  const [expandedFileId, setExpandedFileId] = useState(null);
  const [editingProfileId, setEditingProfileId] = useState(null);
  const [profileDraft, setProfileDraft] = useState(null);
  const [editingFileId, setEditingFileId] = useState(null);
  const [fileDraft, setFileDraft] = useState(null);


  useEffect(() => { load(); }, []);
  useEffect(() => {
    function handleOpenPrompts() {
      setActivePanel('assistant');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
    window.addEventListener('assistant:admin-open-prompts', handleOpenPrompts);
    return () => window.removeEventListener('assistant:admin-open-prompts', handleOpenPrompts);
  }, []);


  useEffect(() => {
    if (activePanel !== 'assistant' || !settings) return;
    loadRuntimePreview(runtimeProfileId);
  }, [activePanel, runtimeProfileId, settings?.default_assistant_profile_id]);

  async function load() {
    const [u, s, p, files, tags, dawHooks] = await Promise.all([
      api.admin.users(),
      api.admin.aiSettings(),
      api.admin.profiles(),
      api.admin.instructionFiles(true),
      api.admin.vocalTags(),
      api.admin.dawPromptHooks()
    ]);
    const safeSettings = s || {};
    setUsers(u || []);
    setSettings(safeSettings);
    setProfiles(p || []);
    setInstructionFiles(files || []);
    setVocalTags(tags || []);
    setDawPromptHooks(dawHooks || []);
    setNewProfile((prev) => {
      const provider = prev.provider || safeSettings.default_provider || 'openai';
      const model = prev.model || defaultModelForProvider(safeSettings, provider);
      return { ...prev, provider, model };
    });
  }

  async function toggleUser(user) {
    await api.admin.updateUser(user.id, { is_active: !user.is_active });
    notify(t('admin.messages.userUpdated', 'Benutzer aktualisiert.'), 'success');
    load();
  }

  async function renameUser(user) {
    const nickname = prompt(t('admin.users.nickname', 'Spitzname'), user.nickname || user.email.split('@')[0]);
    if (nickname === null) return;
    await api.admin.updateUser(user.id, { nickname: nickname.trim() || null });
    notify(t('admin.messages.nicknameUpdated', 'Spitzname aktualisiert.'), 'success');
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
        srt_alignment_engine: next.srt_alignment_engine === 'forced_alignment' ? 'forced_alignment' : 'heuristic',
        srt_quality_gate_enabled: Boolean(next.srt_quality_gate_enabled),
        srt_quality_gate_min_score: Math.max(0.3, Math.min(0.95, Number(next.srt_quality_gate_min_score || 0.7))),
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
      notify(t('admin.messages.assistantSaved', 'KI-Assistent gespeichert.'), 'success');
      await load();
    } finally {
      setSaving(false);
    }
  }

  async function testProvider(provider = settings?.default_provider, model = settings?.default_model) {
    const result = await api.admin.testAi({ provider, model });
    notify(result.ok ? t('admin.messages.providerTestOk', 'Provider-Test erfolgreich.') : result.error || t('admin.messages.providerTestFailed', 'Provider-Test fehlgeschlagen.'), result.ok ? 'success' : 'error');
  }

  async function loadRuntimePreview(profileId = '') {
    setRuntimeLoading(true);
    setRuntimeError('');
    try {
      const result = await api.assistant.runtime(profileId ? Number(profileId) : null);
      setRuntimeInfo(result || null);
    } catch (err) {
      setRuntimeInfo(null);
      setRuntimeError(err?.message || t('admin.assistant.runtimeLoadFailed', 'Effektive KI-Konfiguration konnte nicht geladen werden.'));
    } finally {
      setRuntimeLoading(false);
    }
  }

  function openProfileEditor(profile) {
    setEditingProfileId(profile.id);
    setProfileDraft({
      name: profile.name || '',
      description: profile.description || '',
      provider: profile.provider || settings?.default_provider || 'openai',
      model: profile.model || '',
      system_instruction: profile.system_instruction || '',
      response_format_instruction: profile.response_format_instruction || '',
      temperature: profile.temperature ?? '',
      max_output_tokens: profile.max_output_tokens ?? '',
      is_default: Boolean(profile.is_default),
      is_active: profile.is_active !== false,
      linked_file_ids: (profile.linked_file_ids || []).map(Number)
    });
    setExpandedProfileId(profile.id);
  }

  async function saveProfileEditor(profile) {
    if (!profileDraft?.name?.trim()) return notify(t('admin.messages.profileNameMissing', 'Profilname fehlt.'), 'error');
    const payload = {
      ...profileDraft,
      name: profileDraft.name.trim(),
      description: profileDraft.description?.trim() || null,
      system_instruction: profileDraft.system_instruction || null,
      response_format_instruction: profileDraft.response_format_instruction || null,
      temperature: profileDraft.temperature === '' ? null : Number(profileDraft.temperature),
      max_output_tokens: profileDraft.max_output_tokens === '' ? null : Number(profileDraft.max_output_tokens),
      linked_file_ids: (profileDraft.linked_file_ids || []).map(Number)
    };
    await api.admin.updateProfile(profile.id, payload);
    setEditingProfileId(null);
    setProfileDraft(null);
    notify(t('admin.messages.profileUpdated', 'KI-Profil aktualisiert.'), 'success');
    await load();
  }

  async function duplicateProfile(profile) {
    const created = await api.admin.createProfile({
      name: `${profile.name} (Kopie)`,
      description: profile.description || null,
      provider: profile.provider,
      model: profile.model,
      system_instruction: profile.system_instruction || null,
      response_format_instruction: profile.response_format_instruction || null,
      temperature: profile.temperature ?? null,
      max_output_tokens: profile.max_output_tokens ?? null,
      is_default: false,
      is_active: false,
      linked_file_ids: (profile.linked_file_ids || []).map(Number)
    });
    notify(t('admin.messages.profileDuplicated', 'KI-Profil wurde als inaktive Kopie angelegt.'), 'success');
    await load();
    if (created?.id) setExpandedProfileId(created.id);
  }

  function openInstructionEditor(file) {
    setEditingFileId(file.id);
    setFileDraft({
      title: file.title || '',
      description: file.description || '',
      content: file.content || '',
      is_active: file.is_active !== false
    });
    setExpandedFileId(file.id);
  }

  async function saveInstructionEditor(file) {
    if (!fileDraft?.title?.trim() || !fileDraft?.content?.trim()) {
      return notify(t('admin.messages.titleContentRequired', 'Titel und Inhalt sind erforderlich.'), 'error');
    }
    await api.admin.updateInstructionFile(file.id, {
      title: fileDraft.title.trim(),
      description: fileDraft.description?.trim() || null,
      content: fileDraft.content,
      is_active: Boolean(fileDraft.is_active)
    });
    setEditingFileId(null);
    setFileDraft(null);
    notify(t('admin.messages.instructionUpdated', 'Wissens- und Regeldatei aktualisiert.'), 'success');
    await load();
  }

  async function toggleInstructionFile(file) {
    await api.admin.updateInstructionFile(file.id, { is_active: !file.is_active });
    notify(t('admin.messages.instructionUpdated', 'Wissens- und Regeldatei aktualisiert.'), 'success');
    await load();
  }


  async function exportVocalTags(format = 'csv', mode = 'extended') {
    try {
      const content = await api.library.exportVocalTags(format, mode);
      const extension = format === 'markdown' || format === 'md' ? 'md' : 'csv';
      const mime = extension === 'md' ? 'text/markdown;charset=utf-8' : 'text/csv;charset=utf-8';
      downloadTextFile(`suno-vocal-tags-${mode}.${extension}`, content, mime);
      notify(t('admin.messages.vocalTagsExported', 'Vocal-Tags-{{mode}}export wurde erstellt.', { mode: mode === 'extended' ? t('admin.detail', 'Detail') : t('admin.basic', 'Basis') }), 'success');
    } catch (err) {
      notify(err?.message || t('admin.messages.vocalTagsExportFailed', 'Vocal-Tags-Export fehlgeschlagen.'), 'error');
    }
  }

  async function importVocalTagsFile(event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    try {
      const result = await api.library.importVocalTags(file);
      notify(t('admin.messages.vocalTagsImported', 'Vocal Tags importiert: {{imported}}, übersprungen: {{skipped}}.', { imported: result.imported || 0, skipped: result.skipped || 0 }), result.errors?.length ? 'info' : 'success');
      await load();
    } catch (err) {
      notify(err?.message || t('admin.messages.vocalTagsImportFailed', 'Vocal-Tags-Import fehlgeschlagen.'), 'error');
    }
  }

  async function createTag() {
    if (!newTag.label || !newTag.tag) return notify(t('admin.messages.labelTagRequired', 'Label und Tag sind erforderlich.'), 'error');
    await api.admin.createVocalTag(newTag);
    setNewTag({ label: '', tag: '', category: 'Vocal Tags', description: '', sort_order: 100, is_active: true });
    notify(t('admin.messages.vocalTagCreated', 'Vocal Tag erstellt.'), 'success');
    load();
  }

  async function updateTag(tag, patch) {
    await api.admin.updateVocalTag(tag.id, { ...tag, ...patch });
    notify(t('admin.messages.vocalTagUpdated', 'Vocal Tag aktualisiert.'), 'success');
    load();
  }

  async function deleteTag(tag) {
    if (!confirm(t('admin.messages.confirmDeleteVocalTag', 'Vocal Tag wirklich löschen?\n\n{{label}}', { label: tag.label }))) return;
    await api.admin.deleteVocalTag(tag.id);
    notify(t('admin.messages.vocalTagDeleted', 'Vocal Tag gelöscht.'), 'success');
    load();
  }

  async function createDawPromptHook() {
    if (!newDawPromptHook.title || !newDawPromptHook.prompt) return notify('Titel und Prompt sind erforderlich.', 'error');
    await api.admin.createDawPromptHook(newDawPromptHook);
    setNewDawPromptHook({ title: '', prompt: '', description: '', scope: 'daw', sort_order: 100, is_active: true });
    notify('DAW-Prompt gespeichert.', 'success');
    load();
  }

  async function updateDawPromptHook(hook, patch) {
    await api.admin.updateDawPromptHook(hook.id, { ...patch });
    notify('DAW-Prompt aktualisiert.', 'success');
    load();
  }

  function patchDawPromptHookState(hookId, patch) {
    setDawPromptHooks((items) => items.map((item) => (item.id === hookId ? { ...item, ...patch } : item)));
  }

  async function duplicateDawPromptHook(hook) {
    await api.admin.duplicateDawPromptHook(hook.id);
    notify('DAW-Prompt dupliziert.', 'success');
    load();
  }

  async function deleteDawPromptHook(hook) {
    if (!confirm(`DAW-Prompt wirklich löschen?\n\n${hook.title}`)) return;
    await api.admin.deleteDawPromptHook(hook.id);
    notify('DAW-Prompt gelöscht.', 'success');
    load();
  }

  async function createFile() {
    if (!newFile.title || !newFile.content) return notify(t('admin.messages.titleContentRequired', 'Titel und Inhalt sind erforderlich.'), 'error');
    await api.admin.createInstructionFile(newFile);
    setNewFile({ title: '', content: '', description: '', is_active: true });
    notify(t('admin.messages.instructionSaved', 'Instruction-Datei gespeichert.'), 'success');
    load();
  }

  async function deleteFile(file) {
    if (!confirm(t('admin.messages.confirmDeleteInstruction', 'Instruction-Datei wirklich löschen?\n\n{{title}}', { title: file.title }))) return;
    await api.admin.deleteInstructionFile(file.id);
    notify(t('admin.messages.instructionDeleted', 'Instruction-Datei gelöscht.'), 'success');
    load();
  }

  async function createProfile() {
    if (!newProfile.name) return notify(t('admin.messages.profileNameMissing', 'Profilname fehlt.'), 'error');
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
    notify(t('admin.messages.profileCreated', 'KI-Profil erstellt.'), 'success');
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
    notify(t('admin.messages.profileUpdated', 'KI-Profil aktualisiert.'), 'success');
    load();
  }

  async function deleteProfile(profile) {
    if (!confirm(t('admin.messages.confirmDeleteProfile', 'KI-Profil wirklich löschen?\n\n{{name}}', { name: profile.name }))) return;
    await api.admin.deleteProfile(profile.id);
    notify(t('admin.messages.profileDeleted', 'KI-Profil gelöscht.'), 'success');
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
    ['assistant', t('admin.tabs.assistant', 'KI-Assistent'), Bot],
    ['library-search-index', t('admin.tabs.librarySearchIndex', 'Library-Suchindex'), Search],
    ['daw-prompts', 'DAW-Prompts', Music2],
    ['tags', t('admin.tabs.vocalTags', 'Vocal Tags'), Tag],
    ['users', t('admin.tabs.users', 'Benutzer'), UserRound]
  ], [t]);

  const defaultProfile = profiles.find((item) => Number(item.id) === Number(settings?.default_assistant_profile_id)) || profiles.find((item) => item.is_default);
  const usableDefaultProfile = defaultProfile?.is_active === false ? null : defaultProfile;
  const configuredLibraryProfile = profiles.find((profile) => Number(profile.id) === Number(settings?.library_ai_tagging_profile_id)) || null;
  const usableLibraryProfile = configuredLibraryProfile?.is_active === false ? null : configuredLibraryProfile;
  const libraryProfileMisconfigured = Boolean(
    settings?.library_ai_tagging_enabled
      && (settings?.library_ai_tagging_profile_id ? !usableLibraryProfile : !usableDefaultProfile)
  );

  const assistantSections = useMemo(() => [
    ['overview', t('admin.assistant.sections.overview', 'Übersicht'), Layers3],
    ['standards', t('admin.assistant.sections.standards', 'Globale Standards'), Settings2],
    ['profiles', t('admin.assistant.sections.profiles', 'KI-Profile'), Bot],
    ['knowledge', t('admin.assistant.sections.knowledge', 'Wissensdateien'), BookOpen],
    ['related', t('admin.assistant.sections.related', 'Weitere KI-Funktionen'), FileCog]
  ], [t]);

  const activeProfiles = useMemo(() => profiles.filter((profile) => profile.is_active !== false), [profiles]);
  const activeInstructionFiles = useMemo(() => instructionFiles.filter((file) => file.is_active !== false), [instructionFiles]);
  const linkedFileIds = useMemo(() => new Set(profiles.flatMap((profile) => (profile.linked_file_ids || []).map(Number))), [profiles]);
  const unusedInstructionFiles = useMemo(() => activeInstructionFiles.filter((file) => !linkedFileIds.has(Number(file.id))), [activeInstructionFiles, linkedFileIds]);
  const inactiveLinkedFiles = useMemo(() => instructionFiles.filter((file) => file.is_active === false && linkedFileIds.has(Number(file.id))), [instructionFiles, linkedFileIds]);

  const assistantWarnings = useMemo(() => {
    if (!settings) return [];
    const rows = [];
    const configuredDefault = profiles.find((profile) => Number(profile.id) === Number(settings.default_assistant_profile_id));
    if (settings.default_assistant_profile_id && !configuredDefault) {
      rows.push({ severity: 'error', text: t('admin.assistant.warnings.defaultMissing', 'Das gespeicherte Standardprofil existiert nicht mehr.') });
    } else if (configuredDefault?.is_active === false) {
      rows.push({ severity: 'error', text: t('admin.assistant.warnings.defaultInactive', 'Das gespeicherte Standardprofil ist deaktiviert und wird zur Laufzeit übersprungen.') });
    }
    const profileDefault = profiles.find((profile) => profile.is_default);
    if (configuredDefault && profileDefault && Number(configuredDefault.id) !== Number(profileDefault.id)) {
      rows.push({ severity: 'warning', text: t('admin.assistant.warnings.defaultMismatch', 'Globales Standardprofil und Profil-Markierung „Standard“ zeigen auf unterschiedliche Profile.') });
    }
    if (libraryProfileMisconfigured) {
      rows.push({
        severity: 'error',
        text: t('admin.assistant.warnings.libraryProfileMissing', 'Der Library-Suchindex verweist auf ein nicht verfügbares oder deaktiviertes KI-Profil.'),
        action: 'open-library-profile'
      });
    }
    for (const profile of profiles) {
      if (profile.is_active !== false && settings.providers?.[profile.provider]?.configured === false) {
        rows.push({ severity: 'error', text: t('admin.assistant.warnings.providerMissing', 'Profil „{{name}}“ verwendet den nicht konfigurierten Provider {{provider}}.', { name: profile.name, provider: profile.provider }) });
      }
    }
    if (unusedInstructionFiles.length) {
      rows.push({ severity: 'warning', text: t('admin.assistant.warnings.unusedFiles', '{{count}} aktive Wissensdatei(en) sind mit keinem Profil verknüpft und haben derzeit keine Wirkung.', { count: unusedInstructionFiles.length }) });
    }
    if (inactiveLinkedFiles.length) {
      rows.push({ severity: 'warning', text: t('admin.assistant.warnings.inactiveLinkedFiles', '{{count}} deaktivierte Wissensdatei(en) sind noch mit Profilen verknüpft und werden zur Laufzeit ignoriert.', { count: inactiveLinkedFiles.length }) });
    }
    return rows.slice(0, 12);
  }, [settings, profiles, defaultProfile, libraryProfileMisconfigured, unusedInstructionFiles, inactiveLinkedFiles, t]);

  const resolvedLibraryProfile = usableLibraryProfile || (!settings?.library_ai_tagging_profile_id ? usableDefaultProfile : null);
  const usageRows = useMemo(() => [
    {
      key: 'global-assistant',
      title: t('admin.assistant.usage.globalAssistant', 'Globaler KI-Assistent'),
      profile: defaultProfile?.name || t('admin.assistant.usage.globalDefaults', 'Globale Defaults'),
      scope: t('admin.assistant.usage.globalAssistantScope', 'Globale Grundanweisung, Standardprofil, verknüpfte Wissensdateien und Vocal Tags.')
    },
    {
      key: 'style-engine',
      title: t('admin.assistant.usage.styleEngine', 'Style-Engine auf /music'),
      profile: defaultProfile?.name || t('admin.assistant.usage.globalDefaults', 'Globale Defaults'),
      scope: t('admin.assistant.usage.styleEngineScope', 'Verwendet dieselbe effektive Runtime wie der globale Assistent plus fest programmierte Style-Regeln.')
    },
    {
      key: 'lyrics-studio',
      title: t('admin.assistant.usage.lyricsStudio', 'Songtext-Studio'),
      profile: t('admin.assistant.usage.perSession', 'Pro Session auswählbar'),
      scope: t('admin.assistant.usage.lyricsStudioScope', 'Das gewählte Profil wird in der Session gespeichert; ohne Auswahl greift das Standardprofil.')
    },
    {
      key: 'library-index',
      title: t('admin.assistant.usage.libraryIndex', 'Library-Suchindex'),
      profile: resolvedLibraryProfile?.name || t('admin.assistant.usage.noProfile', 'Kein gültiges Profil'),
      scope: settings?.library_ai_tagging_profile_id
        ? t('admin.assistant.usage.libraryDedicated', 'Verwendet das separat zugewiesene Tagging-Profil.')
        : t('admin.assistant.usage.libraryFallback', 'Verwendet das Standardprofil als Fallback.'),
      action: 'open-library-profile'
    },
    {
      key: 'daw-ai',
      title: t('admin.assistant.usage.dawAi', 'DAW-KI'),
      profile: t('admin.assistant.usage.providerModelOnly', 'Nur globaler Provider / Modell'),
      scope: t('admin.assistant.usage.dawAiScope', 'KI-Profile und Wissensdateien greifen hier derzeit nicht; DAW-Prompts werden separat verwaltet.')
    },
    {
      key: 'media-ai',
      title: t('admin.assistant.usage.mediaAi', 'SRT und lokale Audioanalyse'),
      profile: t('admin.assistant.usage.separateSettings', 'Separate Einstellungen'),
      scope: t('admin.assistant.usage.mediaAiScope', 'Transkription, Alignment und lokale Modellanalyse werden nicht durch KI-Profile gesteuert.')
    }
  ], [defaultProfile, resolvedLibraryProfile, settings?.library_ai_tagging_profile_id, t]);

  const runtimeResolvedProfile = profiles.find((profile) => Number(profile.id) === Number(runtimeInfo?.profile_id)) || null;
  const runtimeLinkedFiles = runtimeResolvedProfile?.linked_files || [];
  const runtimeFileDetails = useMemo(() => runtimeLinkedFiles.map((linkedFile) => {
    const fullFile = instructionFiles.find((file) => Number(file.id) === Number(linkedFile.id));
    return {
      id: linkedFile.id,
      title: linkedFile.title || fullFile?.title || `#${linkedFile.id}`,
      characters: String(fullFile?.content || linkedFile.content || '').length,
      is_active: fullFile?.is_active !== false && linkedFile.is_active !== false
    };
  }), [runtimeLinkedFiles, instructionFiles]);
  const runtimeContextCharacters = useMemo(() => {
    const profile = runtimeResolvedProfile;
    const fileCharacters = runtimeFileDetails.reduce((sum, file) => sum + file.characters, 0);
    return String(settings?.system_instruction || '').length
      + String(profile?.system_instruction || '').length
      + String(profile?.response_format_instruction || '').length
      + fileCharacters;
  }, [runtimeResolvedProfile, runtimeFileDetails, settings?.system_instruction]);

  const runtimeCompositionRows = useMemo(() => {
    if (!runtimeInfo) return [];
    const globalCharacters = String(settings?.system_instruction || '').length;
    const profileCharacters = String(runtimeResolvedProfile?.system_instruction || '').length;
    const responseCharacters = String(runtimeResolvedProfile?.response_format_instruction || '').length;
    const fileCharacters = runtimeFileDetails.reduce((sum, file) => sum + file.characters, 0);
    const profileActive = Boolean(runtimeResolvedProfile);
    const profileOverridesFallback = runtimeInfo.source === 'assistant_profile';
    return [
      {
        key: 'fixed-rules',
        label: t('admin.assistant.runtime.fixedRules', 'Feste Laufzeitregeln'),
        source: t('admin.assistant.runtime.sourceBackend', 'Fest in der Assistant-Runtime hinterlegt'),
        value: t('admin.assistant.runtime.alwaysIncluded', 'Immer enthalten'),
        status: 'active'
      },
      {
        key: 'global-instruction',
        label: t('admin.assistant.runtime.globalInstruction', 'Globale Grundanweisung'),
        source: t('admin.assistant.runtime.sourceGlobalSettings', 'Globale KI-Standards'),
        value: globalCharacters
          ? t('admin.assistant.runtime.characterCount', '{{count}} Zeichen', { count: globalCharacters.toLocaleString() })
          : t('admin.assistant.runtime.noContent', 'Kein Inhalt hinterlegt'),
        status: globalCharacters ? 'active' : 'not-set'
      },
      {
        key: 'profile-instruction',
        label: t('admin.assistant.runtime.profileInstruction', 'Profil-Grundverhalten'),
        source: profileActive
          ? t('admin.assistant.runtime.sourceProfile', 'Profil „{{name}}“', { name: runtimeResolvedProfile.name })
          : t('admin.assistant.runtime.noProfileSource', 'Kein Profil wirksam'),
        value: profileActive
          ? (profileCharacters
            ? t('admin.assistant.runtime.characterCount', '{{count}} Zeichen', { count: profileCharacters.toLocaleString() })
            : t('admin.assistant.runtime.noContent', 'Kein Inhalt hinterlegt'))
          : t('admin.assistant.runtime.notUsedForRuntime', 'In dieser Runtime nicht verwendet'),
        status: profileActive ? (profileCharacters ? 'active' : 'not-set') : 'not-used'
      },
      {
        key: 'response-format',
        label: t('admin.assistant.runtime.responseFormat', 'Antwortformat'),
        source: profileActive
          ? t('admin.assistant.runtime.sourceProfile', 'Profil „{{name}}“', { name: runtimeResolvedProfile.name })
          : t('admin.assistant.runtime.noProfileSource', 'Kein Profil wirksam'),
        value: profileActive
          ? (responseCharacters
            ? t('admin.assistant.runtime.characterCount', '{{count}} Zeichen', { count: responseCharacters.toLocaleString() })
            : t('admin.assistant.runtime.noContent', 'Kein Inhalt hinterlegt'))
          : t('admin.assistant.runtime.notUsedForRuntime', 'In dieser Runtime nicht verwendet'),
        status: profileActive ? (responseCharacters ? 'active' : 'not-set') : 'not-used'
      },
      {
        key: 'knowledge-files',
        label: t('admin.assistant.runtime.linkedFiles', 'Wissensdateien'),
        source: profileActive
          ? t('admin.assistant.runtime.sourceProfile', 'Profil „{{name}}“', { name: runtimeResolvedProfile.name })
          : t('admin.assistant.runtime.noProfileSource', 'Kein Profil wirksam'),
        value: profileActive
          ? (runtimeFileDetails.length
            ? t('admin.assistant.runtime.fileCharacterCount', '{{files}} Datei(en) · {{characters}} Zeichen', { files: runtimeFileDetails.length, characters: fileCharacters.toLocaleString() })
            : t('admin.assistant.runtime.noFilesLinked', 'Keine Datei verknüpft'))
          : t('admin.assistant.runtime.notUsedForRuntime', 'In dieser Runtime nicht verwendet'),
        status: profileActive ? (runtimeFileDetails.length ? 'active' : 'not-set') : 'not-used',
        details: runtimeFileDetails.map((file) => `${file.title} · ${file.characters.toLocaleString()} ${t('admin.assistant.runtime.charactersLabel', 'Zeichen')}`).join(' · ')
      },
      {
        key: 'vocal-tags',
        label: t('admin.assistant.runtime.vocalTags', 'Vocal Tags'),
        source: t('admin.assistant.runtime.sourceVocalTags', 'Aktive Vocal-Tags aus der Verwaltung'),
        value: runtimeInfo.vocal_tags_count
          ? t('admin.assistant.runtime.itemCount', '{{count}} Einträge', { count: runtimeInfo.vocal_tags_count })
          : t('admin.assistant.runtime.noEntries', 'Keine aktiven Einträge'),
        status: runtimeInfo.vocal_tags_count ? 'active' : 'not-set'
      },
      {
        key: 'provider-fallback',
        label: t('admin.assistant.runtime.providerModelFallback', 'Globaler Provider-/Modell-Fallback'),
        source: t('admin.assistant.runtime.sourceGlobalSettings', 'Globale KI-Standards'),
        value: profileOverridesFallback
          ? t('admin.assistant.runtime.overriddenByProfile', 'Durch Profil „{{name}}“ überschrieben', { name: runtimeResolvedProfile?.name || runtimeInfo.profile_name || '—' })
          : `${runtimeInfo.provider || '—'} / ${runtimeInfo.model || '—'}`,
        status: profileOverridesFallback ? 'overridden' : 'active'
      }
    ];
  }, [runtimeInfo, runtimeResolvedProfile, runtimeFileDetails, settings?.system_instruction, t]);

  function profileUsageLabels(profile) {
    const labels = [];
    if (Number(profile.id) === Number(defaultProfile?.id)) {
      labels.push(t('admin.assistant.usage.defaultFallback', 'Globaler Fallback'));
      labels.push(t('admin.assistant.usage.styleFallback', 'Style-Engine'));
      labels.push(t('admin.assistant.usage.chatFallback', 'Songtext-Fallback'));
      if (!settings?.library_ai_tagging_profile_id) labels.push(t('admin.assistant.usage.libraryFallbackShort', 'Library-Fallback'));
    }
    if (Number(profile.id) === Number(settings?.library_ai_tagging_profile_id)) labels.push(t('admin.assistant.usage.libraryDedicatedShort', 'Library-Suchindex'));
    labels.push(t('admin.assistant.usage.lyricsSelectable', 'Im Songtext-Studio auswählbar'));
    return [...new Set(labels)];
  }

  function linkedProfilesForFile(fileId) {
    return profiles.filter((profile) => (profile.linked_file_ids || []).map(Number).includes(Number(fileId)));
  }

  function openLibraryTaggingSettings() {
    setActivePanel('assistant');
    setAssistantSection('related');
    window.setTimeout(() => {
      const section = document.getElementById('assistant-library-tagging-settings');
      if (!section) return;
      section.open = true;
      section.scrollIntoView({ behavior: 'smooth', block: 'center' });
      window.setTimeout(() => section.querySelector('select')?.focus(), 350);
    }, 60);
  }

  function runtimeStatusLabel(status) {
    const labels = {
      active: t('admin.assistant.runtime.statusActive', 'Aktiv'),
      'not-set': t('admin.assistant.runtime.statusNotSet', 'Nicht gesetzt'),
      'not-used': t('admin.assistant.runtime.statusNotUsed', 'Nicht verwendet'),
      overridden: t('admin.assistant.runtime.statusOverridden', 'Überschrieben')
    };
    return labels[status] || status;
  }

  return (
    <section className="page stack admin-page">
      <SectionHeader eyebrow={t('nav.groups.administration', 'Administration')} title={t('admin.title', 'Verwaltung')} />
      <div className="admin-tabs panel slim-panel">
        {panels.map(([key, label, Icon]) => (
          <button key={key} className={activePanel === key ? 'active' : ''} type="button" onClick={() => setActivePanel(key)}><Icon size={16} /> {label}</button>
        ))}
      </div>

      {activePanel === 'users' && (
        <article className="panel">
          <h2>{t('admin.users.title', 'Benutzer')}</h2>
          <p className="muted">{t('admin.users.text', 'Jeder aktive Benutzer kann alle Bereiche nutzen. Es gibt keine rollenbasierte Sichtbarkeit.')}</p>
          <div className="admin-table">
            {users.map((user) => (
              <div className="admin-table-row" key={user.id}>
                <span><strong>{user.nickname || user.email.split('@')[0]}</strong><br /><small className="muted">{user.email}</small></span>
                <span className={`status ${user.is_active ? 'cached' : ''}`}>{user.is_active ? t('system.state.active', 'aktiv') : t('admin.state.inactive', 'inaktiv')}</span>
                <button type="button" onClick={() => renameUser(user)}>{t('admin.users.nickname', 'Spitzname')}</button>
                <button type="button" onClick={() => toggleUser(user)}>{user.is_active ? t('admin.actions.deactivate', 'Deaktivieren') : t('admin.actions.activate', 'Aktivieren')}</button>
              </div>
            ))}
          </div>
        </article>
      )}

      {activePanel === 'assistant' && settings && (
        <div className="assistant-admin-shell stack">
          <article className="panel assistant-admin-hero">
            <div className="panel-title-row">
              <div>
                <span className="eyebrow">{t('admin.assistant.eyebrow', 'KI-Konfiguration')}</span>
                <h2>{t('admin.assistant.title', 'KI-Assistent')}</h2>
                <p className="muted">{t('admin.assistant.text', 'Globale Standards, wiederverwendbare KI-Profile und zusätzliche Wissensdateien. Die Übersicht zeigt transparent, welche Konfiguration in welcher Funktion tatsächlich greift.')}</p>
              </div>
              <button type="button" onClick={load}><RefreshCcw size={16} /> {t('topbar.refresh', 'Aktualisieren')}</button>
            </div>
            <div className="assistant-section-tabs" role="tablist" aria-label={t('admin.assistant.sections.label', 'Bereiche des KI-Assistenten')}>
              {assistantSections.map(([key, label, Icon]) => (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={assistantSection === key}
                  className={assistantSection === key ? 'active' : ''}
                  onClick={() => setAssistantSection(key)}
                >
                  <Icon size={16} /> {label}
                </button>
              ))}
            </div>
          </article>

          {assistantSection === 'overview' && (
            <>
              <div className="assistant-overview-stats">
                <div className="panel assistant-stat-card"><strong>{activeProfiles.length}</strong><span>{t('admin.assistant.stats.activeProfiles', 'aktive Profile')}</span></div>
                <div className="panel assistant-stat-card"><strong>{activeInstructionFiles.length}</strong><span>{t('admin.assistant.stats.activeFiles', 'aktive Wissensdateien')}</span></div>
                <div className={`panel assistant-stat-card ${unusedInstructionFiles.length ? 'warning' : ''}`}><strong>{unusedInstructionFiles.length}</strong><span>{t('admin.assistant.stats.unusedFiles', 'ohne Verknüpfung')}</span></div>
                <div className={`panel assistant-stat-card ${assistantWarnings.length ? 'warning' : 'ok'}`}><strong>{assistantWarnings.length}</strong><span>{t('admin.assistant.stats.warnings', 'Konfigurationshinweise')}</span></div>
              </div>

              {assistantWarnings.length > 0 && (
                <article className="panel stack assistant-warning-panel">
                  <div className="assistant-section-heading">
                    <AlertTriangle size={19} />
                    <div>
                      <h3>{t('admin.assistant.warnings.title', 'Konfigurationshinweise')}</h3>
                      <p className="muted">{t('admin.assistant.warnings.text', 'Diese Hinweise verändern nichts automatisch. Sie zeigen Konstellationen, die zur Laufzeit anders wirken können als erwartet.')}</p>
                    </div>
                  </div>
                  <div className="assistant-warning-list">
                    {assistantWarnings.map((warning, index) => (
                      <div className={`assistant-warning-item ${warning.severity}`} key={`${warning.text}-${index}`}>
                        {warning.severity === 'error' ? <AlertTriangle size={16} /> : <Info size={16} />}
                        <span>{warning.text}</span>
                        {warning.action === 'open-library-profile' && (
                          <button type="button" className="assistant-warning-action" onClick={openLibraryTaggingSettings}>
                            <Settings2 size={14} /> {t('admin.assistant.warnings.selectProfile', 'Profil auswählen')}
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                </article>
              )}

              <article className="panel stack wide-panel">
                <div className="assistant-section-heading">
                  <Layers3 size={19} />
                  <div>
                    <h3>{t('admin.assistant.usage.title', 'Wo greift welche Konfiguration?')}</h3>
                    <p className="muted">{t('admin.assistant.usage.text', 'Die Zuordnung basiert auf den tatsächlich verwendeten Services und Fallback-Regeln des aktuellen Projektstands.')}</p>
                  </div>
                </div>
                <div className="assistant-usage-table">
                  <div className="assistant-usage-head">
                    <span>{t('admin.assistant.usage.function', 'Funktion')}</span>
                    <span>{t('admin.assistant.usage.effectiveProfile', 'Effektives Profil')}</span>
                    <span>{t('admin.assistant.usage.effect', 'Tatsächliche Wirkung')}</span>
                  </div>
                  {usageRows.map((row) => (
                    <div className="assistant-usage-row" key={row.key}>
                      <strong>{row.title}</strong>
                      <div className="assistant-usage-profile-cell">
                        <span className="assistant-usage-profile">{row.profile}</span>
                        {row.action === 'open-library-profile' && (
                          <button type="button" className="assistant-usage-action" onClick={openLibraryTaggingSettings}>
                            <Settings2 size={13} /> {t('admin.assistant.usage.openSettings', 'Einstellungen öffnen')}
                          </button>
                        )}
                      </div>
                      <span className="muted">{row.scope}</span>
                    </div>
                  ))}
                </div>
              </article>

              <article className="panel stack assistant-runtime-panel">
                <div className="panel-title-row">
                  <div className="assistant-section-heading">
                    <Cpu size={19} />
                    <div>
                      <h3>{t('admin.assistant.runtime.title', 'Effektive Runtime-Vorschau')}</h3>
                      <p className="muted">{t('admin.assistant.runtime.text', 'Zeigt die Konfiguration, die der globale Assistent und die Style-Engine bei einem Aufruf tatsächlich auflösen.')}</p>
                    </div>
                  </div>
                  <button type="button" onClick={() => loadRuntimePreview(runtimeProfileId)} disabled={runtimeLoading}><RefreshCcw size={15} /> {runtimeLoading ? t('common.loading', 'Lädt…') : t('common.refresh', 'Aktualisieren')}</button>
                </div>
                <label className="assistant-runtime-select">{t('admin.assistant.runtime.previewProfile', 'Runtime für Profil prüfen')}
                  <select value={runtimeProfileId} onChange={(event) => setRuntimeProfileId(event.target.value)}>
                    <option value="">{t('admin.assistant.runtime.activeFallback', 'Aktiver Standard / Fallback')}</option>
                    {activeProfiles.map((profile) => <option value={profile.id} key={profile.id}>{profile.name} · {profile.provider} / {profile.model}</option>)}
                  </select>
                </label>
                {runtimeError && <div className="alert error">{runtimeError}</div>}
                {runtimeInfo && (
                  <>
                    <div className="assistant-runtime-grid">
                      <div><span>{t('admin.assistant.runtime.source', 'Quelle')}</span><strong>{runtimeInfo.source === 'assistant_profile' ? runtimeInfo.profile_name : t('admin.assistant.runtime.globalDefaults', 'Globale Defaults')}</strong></div>
                      <div><span>Provider</span><strong>{runtimeInfo.provider || '—'}</strong></div>
                      <div><span>{t('admin.assistant.model', 'Modell')}</span><strong>{runtimeInfo.model || '—'}</strong></div>
                      <div><span>{t('admin.assistant.runtime.temperature', 'Kreativität')}</span><strong>{runtimeInfo.temperature ?? t('admin.assistant.runtime.providerDefault', 'Provider-Standard')}</strong></div>
                      <div><span>{t('admin.assistant.runtime.maxOutput', 'Max. Ausgabe')}</span><strong>{runtimeInfo.max_output_tokens || t('admin.assistant.runtime.providerDefault', 'Provider-Standard')}</strong></div>
                      <div><span>{t('admin.assistant.runtime.files', 'Wissensdateien')}</span><strong>{runtimeInfo.instruction_files_count || 0}</strong></div>
                      <div><span>{t('admin.assistant.runtime.vocalTags', 'Vocal Tags')}</span><strong>{runtimeInfo.vocal_tags_count || 0}</strong></div>
                      <div><span>{t('admin.assistant.runtime.contextSize', 'Zusätzlicher Kontext')}</span><strong>{runtimeContextCharacters.toLocaleString()} {t('admin.assistant.runtime.characters', 'Zeichen')}</strong></div>
                    </div>
                    <div className="assistant-runtime-composition">
                      <div className="assistant-runtime-composition-heading">
                        <div>
                          <h4>{t('admin.assistant.runtime.composition', 'Zusammensetzung')}</h4>
                          <p className="muted">{t('admin.assistant.runtime.compositionHint', 'Nur als „Aktiv“ markierte Quellen tragen Inhalt zu dieser Runtime bei. „Überschrieben“ betrifft ausschließlich den jeweiligen Fallback.')}</p>
                        </div>
                        <span className="assistant-runtime-readonly"><Eye size={13} /> {t('admin.assistant.runtime.readOnly', 'Nur Vorschau')}</span>
                      </div>
                      <div className="assistant-runtime-source-list">
                        {runtimeCompositionRows.map((row) => (
                          <div className={`assistant-runtime-source-row ${row.status}`} key={row.key}>
                            <div className="assistant-runtime-source-main">
                              <strong>{row.label}</strong>
                              <span className="muted">{row.source}</span>
                              {row.details && <small>{row.details}</small>}
                            </div>
                            <div className="assistant-runtime-source-value">
                              <span>{row.value}</span>
                              <span className={`assistant-runtime-state ${row.status}`}>{runtimeStatusLabel(row.status)}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                    <div className="inline-actions">
                      <button type="button" onClick={() => testProvider(runtimeInfo.provider, runtimeInfo.model)}><TestTube2 size={15} /> {t('admin.assistant.testProvider', 'Provider testen')}</button>
                      <button type="button" onClick={() => setAssistantSection(runtimeResolvedProfile ? 'profiles' : 'standards')}><Eye size={15} /> {t('admin.assistant.runtime.openConfiguration', 'Konfiguration öffnen')}</button>
                    </div>
                  </>
                )}
              </article>
            </>
          )}

          {assistantSection === 'standards' && (
            <article className="panel stack assistant-settings-panel">
              <div className="assistant-section-heading">
                <Settings2 size={19} />
                <div>
                  <h3>{t('admin.assistant.standards.title', 'Globale KI-Standards')}</h3>
                  <p className="muted">{t('admin.assistant.standards.text', 'Fallback-Einstellungen für KI-Funktionen, wenn kein konkretes Profil ausgewählt wurde. Ein Profil überschreibt Provider, Modell und Profilparameter.')}</p>
                </div>
              </div>
              <div className="assistant-info-callout">
                <Info size={17} />
                <span>{t('admin.assistant.standards.hint', 'Diese Werte steuern den globalen Assistenten, die Style-Engine, den Fallback im Songtext-Studio und Provider/Modell der DAW-KI. SRT und lokale Audioanalyse besitzen eigene Einstellungen.')}</span>
              </div>
              <div className="form-grid compact-grid">
                <label>{t('admin.assistant.defaultProfile', 'Standardprofil')}
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
                    <option value="">{t('admin.assistant.noProfile', 'Kein Profil / globale Defaults')}</option>
                    {activeProfiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name} · {profile.provider} / {profile.model}</option>)}
                  </select>
                  <small>{t('admin.assistant.standards.defaultProfileHint', 'Wird verwendet, wenn ein KI-Aufruf kein Profil ausdrücklich vorgibt.')}</small>
                </label>
                <label>Provider
                  <select value={settings.default_provider || 'openai'} onChange={(event) => changeDefaultProvider(event.target.value)}>
                    {providerOptions(settings).map((provider) => <option key={provider} value={provider}>{providerLabel(settings, provider, t)}</option>)}
                  </select>
                  <small>{t('admin.assistant.standards.providerHint', 'Fallback-Anbieter und Provider der DAW-KI.')}</small>
                </label>
                <label>{t('admin.assistant.model', 'Modell')}
                  <select value={settings.default_model || ''} onChange={(event) => setSettings({ ...settings, default_model: event.target.value })}>
                    {(settings.allowed_models?.[settings.default_provider || 'openai'] || []).map((model) => <option key={model} value={model}>{model}</option>)}
                  </select>
                  <small>{t('admin.assistant.standards.modelHint', 'Fallback-Modell. Ein verwendetes Profil überschreibt diesen Wert.')}</small>
                </label>
                <label className="wide">{t('admin.assistant.globalSystemInstruction', 'Globale Grundanweisung')}
                  <textarea className="large assistant-instruction-textarea" value={settings.system_instruction || ''} onChange={(event) => setSettings({ ...settings, system_instruction: event.target.value })} placeholder={t('admin.assistant.globalSystemInstructionPlaceholder', 'Zusätzliche Regeln, die vor jeder profilbasierten Anweisung gelten.')} />
                  <small>{t('admin.assistant.standards.globalInstructionHint', 'Wird zusätzlich zu festen Sicherheitsregeln und zur Profilanweisung in den globalen Assistant-/Style-Prompt aufgenommen.')}</small>
                </label>
              </div>
              {defaultProfile && <div className="assistant-current-default"><CheckCircle2 size={16} /><span>{t('admin.assistant.activeDefaultProfile', 'Aktives Standardprofil')}: <strong>{defaultProfile.name}</strong> · {defaultProfile.provider} / {defaultProfile.model}</span></div>}
              <div className="form-actions">
                <button className="primary" type="button" onClick={() => saveAssistantSettings()} disabled={saving}><Save size={16} /> {saving ? t('common.saving', 'Speichert…') : t('stylesPage.save', 'Speichern')}</button>
                <button type="button" onClick={() => testProvider()}><TestTube2 size={16} /> {t('admin.assistant.testProvider', 'Provider testen')}</button>
              </div>
            </article>
          )}

          {assistantSection === 'profiles' && (
            <>
              <article className="panel stack assistant-create-panel">
                <details>
                  <summary><Plus size={17} /> <strong>{t('admin.profiles.createTitle', 'Neues KI-Profil erstellen')}</strong><span className="muted">{t('admin.profiles.createHint', 'Provider, Verhalten, Ausgabeformat und Wissensdateien als wiederverwendbares Paket speichern.')}</span></summary>
                  <div className="form-grid assistant-editor-form">
                    <label>{t('admin.profiles.namePlaceholder', 'Profilname')}<input value={newProfile.name} onChange={(event) => setNewProfile({ ...newProfile, name: event.target.value })} /></label>
                    <label>{t('admin.common.description', 'Beschreibung')}<input value={newProfile.description} onChange={(event) => setNewProfile({ ...newProfile, description: event.target.value })} /></label>
                    <label>Provider<select value={newProfile.provider} onChange={(event) => changeNewProfileProvider(event.target.value)}>{providerOptions(settings).map((provider) => <option key={provider} value={provider}>{providerLabel(settings, provider, t)}</option>)}</select></label>
                    <label>{t('admin.assistant.model', 'Modell')}<select value={newProfile.model} onChange={(event) => setNewProfile({ ...newProfile, model: event.target.value })}>{(settings.allowed_models?.[newProfile.provider] || []).map((model) => <option key={model} value={model}>{model}</option>)}</select></label>
                    <label>{t('admin.profiles.temperatureLabel', 'Kreativität / Temperatur')}<input type="number" step="0.1" min="0" max="2" placeholder={t('admin.profiles.optional', 'Optional')} value={newProfile.temperature} onChange={(event) => setNewProfile({ ...newProfile, temperature: event.target.value })} /></label>
                    <label>{t('admin.profiles.maxTokensLabel', 'Maximale Antwortlänge')}<input type="number" min="1" placeholder={t('admin.profiles.optional', 'Optional')} value={newProfile.max_output_tokens} onChange={(event) => setNewProfile({ ...newProfile, max_output_tokens: event.target.value })} /></label>
                    <label className="wide">{t('admin.profiles.systemInstructionFriendly', 'Grundverhalten der KI')}<textarea rows={7} value={newProfile.system_instruction} onChange={(event) => setNewProfile({ ...newProfile, system_instruction: event.target.value })} /><small>{t('admin.profiles.systemInstructionHint', 'Fachliche Rolle, Regeln und gewünschtes Verhalten dieses Profils.')}</small></label>
                    <label className="wide">{t('admin.profiles.responseFormatFriendly', 'Erwartetes Antwortformat')}<textarea rows={4} value={newProfile.response_format_instruction} onChange={(event) => setNewProfile({ ...newProfile, response_format_instruction: event.target.value })} /><small>{t('admin.profiles.responseFormatHint', 'Technische Form der Antwort, beispielsweise JSON-Felder oder eine feste Gliederung.')}</small></label>
                    <label className="wide">{t('admin.profiles.knowledgeFiles', 'Wissens- und Regeldateien')}
                      <select multiple value={newProfile.linked_file_ids.map(String)} onChange={(event) => setNewProfile({ ...newProfile, linked_file_ids: Array.from(event.target.selectedOptions).map((option) => option.value) })}>
                        {activeInstructionFiles.map((file) => <option key={file.id} value={file.id}>{file.title}</option>)}
                      </select>
                      <small>{t('admin.profiles.knowledgeFilesHint', 'Nur aktive und verknüpfte Dateien werden bei einem Aufruf in den KI-Kontext aufgenommen.')}</small>
                    </label>
                    <label className="check"><input type="checkbox" checked={newProfile.is_default} onChange={(event) => setNewProfile({ ...newProfile, is_default: event.target.checked })} /> {t('admin.profiles.useAsDefault', 'Als Standard verwenden')}</label>
                    <label className="check"><input type="checkbox" checked={newProfile.is_active} onChange={(event) => setNewProfile({ ...newProfile, is_active: event.target.checked })} /> {t('admin.state.activeLabel', 'Aktiv')}</label>
                    <button className="primary" type="button" onClick={createProfile}>{t('admin.profiles.createButton', 'Profil erstellen')}</button>
                  </div>
                </details>
              </article>

              <article className="panel stack wide-panel">
                <div className="assistant-section-heading">
                  <Bot size={19} />
                  <div><h3>{t('admin.profiles.title', 'KI-Profile')}</h3><p className="muted">{t('admin.profiles.text', 'Ein Profil bündelt Provider, Modell, Verhalten, Antwortformat und Wissensdateien. Es wirkt nur, wenn es ausgewählt oder als Fallback verwendet wird.')}</p></div>
                </div>
                <div className="assistant-profile-grid">
                  {profiles.map((profile) => {
                    const expanded = expandedProfileId === profile.id;
                    const editing = editingProfileId === profile.id && profileDraft;
                    const usage = profileUsageLabels(profile);
                    return (
                      <div className={`assistant-profile-card ${profile.is_active === false ? 'inactive' : ''}`} key={profile.id}>
                        <div className="assistant-card-header">
                          <div>
                            <div className="assistant-card-title-row"><strong>{profile.name}</strong>{profile.is_default && <span className="assistant-status-pill default">{t('admin.profiles.defaultBadge', 'Standard')}</span>}{profile.is_active === false && <span className="assistant-status-pill inactive">{t('admin.state.inactive', 'inaktiv')}</span>}</div>
                            <p className="muted">{profile.provider} · {profile.model}</p>
                          </div>
                          <button type="button" className="icon-button" aria-label={expanded ? t('common.close', 'Schließen') : t('admin.profiles.showConfiguration', 'Konfiguration anzeigen')} onClick={() => setExpandedProfileId(expanded ? null : profile.id)}>{expanded ? <ChevronUp size={17} /> : <ChevronDown size={17} />}</button>
                        </div>
                        {profile.description && <p>{profile.description}</p>}
                        <div className="assistant-chip-row">{usage.map((label) => <span className="assistant-scope-chip" key={label}>{label}</span>)}</div>
                        <div className="assistant-profile-facts">
                          <span><strong>{profile.linked_files?.length || 0}</strong> {t('admin.profiles.filesShort', 'Dateien')}</span>
                          <span><strong>{profile.temperature ?? '—'}</strong> {t('admin.profiles.temperatureShort', 'Temperatur')}</span>
                          <span><strong>{profile.max_output_tokens || '—'}</strong> {t('admin.profiles.tokensShort', 'Tokens')}</span>
                        </div>
                        {expanded && !editing && (
                          <div className="assistant-card-details">
                            <div><span>{t('admin.profiles.systemInstructionFriendly', 'Grundverhalten der KI')}</span><pre>{profile.system_instruction || t('admin.profiles.notConfigured', 'Nicht konfiguriert')}</pre></div>
                            <div><span>{t('admin.profiles.responseFormatFriendly', 'Erwartetes Antwortformat')}</span><pre>{profile.response_format_instruction || t('admin.profiles.notConfigured', 'Nicht konfiguriert')}</pre></div>
                            <div><span>{t('admin.profiles.knowledgeFiles', 'Wissens- und Regeldateien')}</span><p>{profile.linked_files?.length ? profile.linked_files.map((file) => file.title).join(' · ') : t('admin.profiles.noFiles', 'Keine Dateien verknüpft')}</p></div>
                          </div>
                        )}
                        {editing && (
                          <div className="assistant-card-editor form-grid compact-grid">
                            <label>{t('admin.profiles.namePlaceholder', 'Profilname')}<input value={profileDraft.name} onChange={(event) => setProfileDraft({ ...profileDraft, name: event.target.value })} /></label>
                            <label>{t('admin.common.description', 'Beschreibung')}<input value={profileDraft.description} onChange={(event) => setProfileDraft({ ...profileDraft, description: event.target.value })} /></label>
                            <label>Provider<select value={profileDraft.provider} onChange={(event) => setProfileDraft({ ...profileDraft, provider: event.target.value, model: defaultModelForProvider(settings, event.target.value) })}>{providerOptions(settings).map((provider) => <option key={provider} value={provider}>{providerLabel(settings, provider, t)}</option>)}</select></label>
                            <label>{t('admin.assistant.model', 'Modell')}<select value={profileDraft.model} onChange={(event) => setProfileDraft({ ...profileDraft, model: event.target.value })}>{(settings.allowed_models?.[profileDraft.provider] || []).map((model) => <option key={model} value={model}>{model}</option>)}</select></label>
                            <label>{t('admin.profiles.temperatureLabel', 'Kreativität / Temperatur')}<input type="number" min="0" max="2" step="0.1" value={profileDraft.temperature} onChange={(event) => setProfileDraft({ ...profileDraft, temperature: event.target.value })} /></label>
                            <label>{t('admin.profiles.maxTokensLabel', 'Maximale Antwortlänge')}<input type="number" min="1" value={profileDraft.max_output_tokens} onChange={(event) => setProfileDraft({ ...profileDraft, max_output_tokens: event.target.value })} /></label>
                            <label className="wide">{t('admin.profiles.systemInstructionFriendly', 'Grundverhalten der KI')}<textarea rows={6} value={profileDraft.system_instruction} onChange={(event) => setProfileDraft({ ...profileDraft, system_instruction: event.target.value })} /></label>
                            <label className="wide">{t('admin.profiles.responseFormatFriendly', 'Erwartetes Antwortformat')}<textarea rows={4} value={profileDraft.response_format_instruction} onChange={(event) => setProfileDraft({ ...profileDraft, response_format_instruction: event.target.value })} /></label>
                            <label className="wide">{t('admin.profiles.knowledgeFiles', 'Wissens- und Regeldateien')}<select multiple value={(profileDraft.linked_file_ids || []).map(String)} onChange={(event) => setProfileDraft({ ...profileDraft, linked_file_ids: Array.from(event.target.selectedOptions).map((option) => Number(option.value)) })}>{instructionFiles.map((file) => <option key={file.id} value={file.id}>{file.title}{file.is_active === false ? ` · ${t('admin.state.inactive', 'inaktiv')}` : ''}</option>)}</select></label>
                            <label className="check"><input type="checkbox" checked={profileDraft.is_default} onChange={(event) => setProfileDraft({ ...profileDraft, is_default: event.target.checked })} /> {t('admin.profiles.useAsDefault', 'Als Standard verwenden')}</label>
                            <label className="check"><input type="checkbox" checked={profileDraft.is_active} onChange={(event) => setProfileDraft({ ...profileDraft, is_active: event.target.checked })} /> {t('admin.state.activeLabel', 'Aktiv')}</label>
                            <div className="form-actions wide"><button className="primary" type="button" onClick={() => saveProfileEditor(profile)}><Save size={15} /> {t('common.save', 'Speichern')}</button><button type="button" onClick={() => { setEditingProfileId(null); setProfileDraft(null); }}><X size={15} /> {t('common.cancel', 'Abbrechen')}</button></div>
                          </div>
                        )}
                        <div className="inline-actions">
                          <button type="button" onClick={() => { setRuntimeProfileId(String(profile.id)); setAssistantSection('overview'); }}><Cpu size={15} /> {t('admin.profiles.runtime', 'Runtime')}</button>
                          <button type="button" onClick={() => openProfileEditor(profile)}><Pencil size={15} /> {t('texts.edit', 'Bearbeiten')}</button>
                          <button type="button" onClick={() => duplicateProfile(profile)}><Copy size={15} /> {t('admin.profiles.duplicate', 'Duplizieren')}</button>
                          <button type="button" onClick={() => setProfileDefault(profile)}><CheckCircle2 size={15} /> {t('admin.assistant.setDefault', 'Standard')}</button>
                          <button type="button" onClick={() => testProvider(profile.provider, profile.model)}><TestTube2 size={15} /> {t('admin.assistant.test', 'Test')}</button>
                          <button type="button" onClick={() => toggleProfile(profile)}>{profile.is_active ? t('admin.actions.deactivate', 'Deaktivieren') : t('admin.actions.activate', 'Aktivieren')}</button>
                          <button type="button" className="danger" onClick={() => deleteProfile(profile)}><Trash2 size={15} /> {t('texts.delete', 'Löschen')}</button>
                        </div>
                      </div>
                    );
                  })}
                  {!profiles.length && <div className="empty-state"><h3>{t('admin.profiles.empty', 'Noch keine KI-Profile')}</h3><p>{t('admin.profiles.emptyHint', 'Erstelle ein Profil, um Provider, Verhalten und Wissensdateien gemeinsam zu konfigurieren.')}</p></div>}
                </div>
              </article>
            </>
          )}

          {assistantSection === 'knowledge' && (
            <>
              <article className="panel stack assistant-create-panel">
                <details>
                  <summary><Plus size={17} /> <strong>{t('admin.instructions.createTitle', 'Neue Wissens- und Regeldatei')}</strong><span className="muted">{t('admin.instructions.createHint', 'Dokumentation, Regeln und Beispiele speichern und anschließend gezielt mit Profilen verknüpfen.')}</span></summary>
                  <div className="form-grid assistant-editor-form">
                    <label>{t('texts.titlePlaceholder', 'Titel')}<input value={newFile.title} onChange={(event) => setNewFile({ ...newFile, title: event.target.value })} /></label>
                    <label>{t('admin.common.description', 'Beschreibung')}<input value={newFile.description} onChange={(event) => setNewFile({ ...newFile, description: event.target.value })} /></label>
                    <label className="wide">{t('admin.instructions.content', 'Inhalt')}<textarea className="large assistant-instruction-textarea" placeholder={t('admin.instructions.contentPlaceholder', 'Regeln, Referenzwissen, Beispiele oder Ausgabevorgaben…')} value={newFile.content} onChange={(event) => setNewFile({ ...newFile, content: event.target.value })} /></label>
                    <label className="check"><input type="checkbox" checked={newFile.is_active} onChange={(event) => setNewFile({ ...newFile, is_active: event.target.checked })} /> {t('admin.state.activeLabel', 'Aktiv')}</label>
                    <button className="primary" type="button" onClick={createFile}><Plus size={16} /> {t('admin.instructions.saveFile', 'Datei speichern')}</button>
                  </div>
                </details>
              </article>

              <article className="panel stack wide-panel">
                <div className="assistant-section-heading">
                  <BookOpen size={19} />
                  <div><h3>{t('admin.instructions.knowledgeTitle', 'Wissens- und Regeldateien')}</h3><p className="muted">{t('admin.instructions.knowledgeText', 'Eine Datei wirkt nur, wenn sie aktiv und mit einem verwendeten KI-Profil verknüpft ist. Reines Speichern verändert keinen KI-Aufruf.')}</p></div>
                </div>
                <div className="assistant-knowledge-grid">
                  {instructionFiles.map((file) => {
                    const linkedProfiles = linkedProfilesForFile(file.id);
                    const expanded = expandedFileId === file.id;
                    const editing = editingFileId === file.id && fileDraft;
                    const charCount = String(file.content || '').length;
                    const unused = file.is_active !== false && linkedProfiles.length === 0;
                    const inactiveLinked = file.is_active === false && linkedProfiles.length > 0;
                    return (
                      <div className={`assistant-knowledge-card ${file.is_active === false ? 'inactive' : ''} ${unused || inactiveLinked ? 'warning' : ''}`} key={file.id}>
                        <div className="assistant-card-header">
                          <div>
                            <div className="assistant-card-title-row"><strong>{file.title}</strong>{file.is_active === false && <span className="assistant-status-pill inactive">{t('admin.state.inactive', 'inaktiv')}</span>}{unused && <span className="assistant-status-pill warning">{t('admin.instructions.unused', 'ohne Wirkung')}</span>}</div>
                            <p className="muted">{charCount.toLocaleString()} {t('admin.assistant.runtime.characters', 'Zeichen')} · {linkedProfiles.length} {t('admin.instructions.linkedProfilesCount', 'Profil(e)')}</p>
                          </div>
                          <button type="button" className="icon-button" aria-label={expanded ? t('common.close', 'Schließen') : t('admin.instructions.showContent', 'Inhalt anzeigen')} onClick={() => setExpandedFileId(expanded ? null : file.id)}>{expanded ? <ChevronUp size={17} /> : <ChevronDown size={17} />}</button>
                        </div>
                        <p>{file.description || t('admin.common.noDescription', 'Keine Beschreibung')}</p>
                        <div className="assistant-chip-row">{linkedProfiles.map((profile) => <span className="assistant-scope-chip" key={profile.id}>{profile.name}</span>)}{!linkedProfiles.length && <span className="assistant-scope-chip muted">{t('admin.instructions.notLinked', 'Mit keinem Profil verknüpft')}</span>}</div>
                        {inactiveLinked && <div className="assistant-inline-warning"><AlertTriangle size={15} /> {t('admin.instructions.inactiveLinked', 'Die Datei ist verknüpft, aber deaktiviert und wird deshalb ignoriert.')}</div>}
                        {expanded && !editing && <pre className="assistant-file-preview">{file.content || t('admin.instructions.contentUnavailable', 'Inhalt wurde nicht geladen.')}</pre>}
                        {editing && (
                          <div className="assistant-card-editor form-grid compact-grid">
                            <label>{t('texts.titlePlaceholder', 'Titel')}<input value={fileDraft.title} onChange={(event) => setFileDraft({ ...fileDraft, title: event.target.value })} /></label>
                            <label>{t('admin.common.description', 'Beschreibung')}<input value={fileDraft.description} onChange={(event) => setFileDraft({ ...fileDraft, description: event.target.value })} /></label>
                            <label className="wide">{t('admin.instructions.content', 'Inhalt')}<textarea rows={12} value={fileDraft.content} onChange={(event) => setFileDraft({ ...fileDraft, content: event.target.value })} /></label>
                            <label className="check"><input type="checkbox" checked={fileDraft.is_active} onChange={(event) => setFileDraft({ ...fileDraft, is_active: event.target.checked })} /> {t('admin.state.activeLabel', 'Aktiv')}</label>
                            <div className="form-actions wide"><button className="primary" type="button" onClick={() => saveInstructionEditor(file)}><Save size={15} /> {t('common.save', 'Speichern')}</button><button type="button" onClick={() => { setEditingFileId(null); setFileDraft(null); }}><X size={15} /> {t('common.cancel', 'Abbrechen')}</button></div>
                          </div>
                        )}
                        <div className="inline-actions">
                          <button type="button" onClick={() => openInstructionEditor(file)}><Pencil size={15} /> {t('texts.edit', 'Bearbeiten')}</button>
                          <button type="button" onClick={() => toggleInstructionFile(file)}>{file.is_active ? t('admin.actions.deactivate', 'Deaktivieren') : t('admin.actions.activate', 'Aktivieren')}</button>
                          <button type="button" className="danger" onClick={() => deleteFile(file)}><Trash2 size={15} /> {t('texts.delete', 'Löschen')}</button>
                        </div>
                      </div>
                    );
                  })}
                  {!instructionFiles.length && <div className="empty-state"><h3>{t('admin.instructions.empty', 'Noch keine Wissensdateien')}</h3><p>{t('admin.instructions.emptyHint', 'Lege Regeln oder Referenzwissen an und verknüpfe die Datei anschließend mit einem KI-Profil.')}</p></div>}
                </div>
              </article>
            </>
          )}

          {assistantSection === 'related' && (
            <article className="panel stack assistant-related-panel">
              <div className="assistant-section-heading">
                <FileCog size={19} />
                <div><h3>{t('admin.assistant.related.title', 'Weitere KI-nahe Funktionen')}</h3><p className="muted">{t('admin.assistant.related.text', 'Diese Einstellungen werden technisch über denselben Admin-Endpunkt gespeichert, gehören aber nicht vollständig zum Profil- und Wissensdatei-System.')}</p></div>
              </div>
              <div className="assistant-info-callout"><Info size={17} /><span>{t('admin.assistant.related.hint', 'Änderungen an KI-Profilen beeinflussen SRT, lokale Modellanalyse und DAW-Prompts nicht automatisch. Der Library-Suchindex kann dagegen ein eigenes Profil oder das Standardprofil verwenden.')}</span></div>

              <details className="assistant-related-details" open>
                <summary><FileText size={17} /> <strong>{t('admin.srt.title', '1-Click-SRT-Erzeugung')}</strong><span className="muted">{t('admin.assistant.related.srtScope', 'Separate Transkriptions-, Alignment- und Bereinigungslogik')}</span></summary>
                <div className="form-grid compact-grid">
                  <label>{t('admin.srt.transcriptionModel', 'Transkriptionsmodell')}<select value={settings.transcription_backend || 'voxtral'} onChange={(event) => setSettings({ ...settings, transcription_backend: event.target.value })}>{(settings.transcription_backends || ['groq', 'whisperx', 'openai_whisper_api', 'voxtral']).map((backend) => { const configured = settings.transcription_runtime?.[backend]?.configured; return <option key={backend} value={backend}>{backend}{configured ? ` · ${t('admin.provider.ready', 'bereit')}` : ` · ${t('admin.provider.notConfigured', 'nicht konfiguriert')}`}</option>; })}</select></label>
                  <label>{t('profile.language', 'Sprache')}<select value={settings.transcription_language || 'de'} onChange={(event) => setSettings({ ...settings, transcription_language: event.target.value })}>{(settings.transcription_languages || ['auto', 'de', 'en']).map((language) => <option key={language} value={language}>{language}</option>)}</select></label>
                  <label>Template Mode<input value="Source of Truth" readOnly /></label>
                  <label>Match Mode<input value="Lenient" readOnly /></label>
                  <label className="check"><input type="checkbox" checked={settings.srt_output_enabled !== false} onChange={(event) => setSettings({ ...settings, srt_output_enabled: event.target.checked })} /> {t('admin.srt.enabled', 'SRT-Erzeugung aktiv')}</label>
                  <label className="check"><input type="checkbox" checked={Boolean(settings.srt_auto_regenerate)} onChange={(event) => setSettings({ ...settings, srt_auto_regenerate: event.target.checked })} /> {t('admin.srt.autoRegenerate', 'Bestehende SRTs bei Bedarf überschreiben')}</label>
                  <label className="check"><input type="checkbox" checked={Boolean(settings.srt_generate_vocal_stems_before_transcription)} onChange={(event) => setSettings({ ...settings, srt_generate_vocal_stems_before_transcription: event.target.checked })} /> {t('admin.srt.generateVocalStems', 'Vocal-Stems vor SRT automatisch erzeugen')}</label>
                  <label>{t('admin.srt.alignmentEngine', 'Alignment-Engine')}<select value={settings.srt_alignment_engine === 'forced_alignment' ? 'forced_alignment' : 'heuristic'} onChange={(event) => setSettings({ ...settings, srt_alignment_engine: event.target.value })}><option value="heuristic">{t('admin.srt.engineHeuristic', 'Heuristik (ASR-Anker + Interpolation)')}</option><option value="forced_alignment">{t('admin.srt.engineForced', 'Forced Alignment (MMS/CTC, benötigt torch/torchaudio)')}</option></select></label>
                  <label className="check"><input type="checkbox" checked={Boolean(settings.srt_quality_gate_enabled)} onChange={(event) => setSettings({ ...settings, srt_quality_gate_enabled: event.target.checked })} /> {t('admin.srt.qualityGate', 'Quality-Gate mit Auto-Eskalation')}</label>
                  <label>{t('admin.srt.qualityGateMinScore', 'Quality-Gate Mindest-Score')}<input type="number" min="0.3" max="0.95" step="0.05" value={settings.srt_quality_gate_min_score ?? 0.7} onChange={(event) => setSettings({ ...settings, srt_quality_gate_min_score: Number(event.target.value) })} /></label>
                  <label className="check srt-ai-display-option"><input type="checkbox" checked={settings.srt_ai_display_optimization_enabled !== false && settings.srt_ai_cleanup_enabled !== false} onChange={(event) => setSettings({ ...settings, srt_ai_cleanup_enabled: event.target.checked, srt_ai_display_optimization_enabled: event.target.checked })} /><span>{t('admin.srt.aiCleanup', 'Songtexte extra für SRT-Anzeige per KI optimieren')}<small>{t('admin.srt.aiCleanupHint', 'Entfernt Regie-, SFX-, Struktur- und Prompt-Hinweise und normalisiert Suno-Schreibweisen.')}</small></span></label>
                  <label className="check"><input type="checkbox" checked={Boolean(settings.library_content_polling_enabled)} onChange={(event) => setSettings({ ...settings, library_content_polling_enabled: event.target.checked })} /> {t('admin.srt.libraryPolling', 'Fehlende Library-Inhalte im Hintergrund prüfen')}</label>
                  <label>{t('admin.srt.pollingInterval', 'Polling-Intervall Minuten')}<input type="number" min="1" max="1440" value={settings.library_content_polling_interval_minutes || 15} onChange={(event) => setSettings({ ...settings, library_content_polling_interval_minutes: event.target.value })} /></label>
                  <label>{t('admin.srt.pollingLimit', 'Polling-Limit Inhalte')}<input type="number" min="10" max="5000" value={settings.library_content_polling_limit || 500} onChange={(event) => setSettings({ ...settings, library_content_polling_limit: event.target.value })} /></label>
                  <label className="check"><input type="checkbox" checked={Boolean(settings.extend_auto_continue_at_enabled)} onChange={(event) => setSettings({ ...settings, extend_auto_continue_at_enabled: event.target.checked })} /> {t('admin.srt.extendAutoContinue', 'Extend: continueAt automatisch per Audioanalyse berechnen')}</label>
                  <label>{t('admin.srt.extendSearchWindow', 'Extend-Suchfenster Sekunden')}<input type="number" min="5" max="60" value={settings.extend_auto_continue_at_search_window_seconds || 15} onChange={(event) => setSettings({ ...settings, extend_auto_continue_at_search_window_seconds: event.target.value })} /></label>
                  <label>{t('admin.srt.vocalThreshold', 'Vocal-Schwelle')}<input type="number" min="0.005" max="0.25" step="0.005" value={settings.extend_auto_continue_at_vocal_threshold_ratio || 0.03} onChange={(event) => setSettings({ ...settings, extend_auto_continue_at_vocal_threshold_ratio: event.target.value })} /></label>
                  <label>{t('admin.srt.fallbackBeforeEnd', 'Fallback vor Ende Sekunden')}<input type="number" min="1" max="30" step="0.5" value={settings.extend_auto_continue_at_fallback_offset_seconds || 4} onChange={(event) => setSettings({ ...settings, extend_auto_continue_at_fallback_offset_seconds: event.target.value })} /></label>
                  <label>{t('admin.srt.analysisTimeout', 'Analyse-Timeout Sekunden')}<input type="number" min="30" max="1200" value={settings.extend_auto_continue_at_timeout_seconds || 180} onChange={(event) => setSettings({ ...settings, extend_auto_continue_at_timeout_seconds: event.target.value })} /></label>
                </div>
              </details>

              <details className="assistant-related-details">
                <summary><Cpu size={17} /> <strong>{t('admin.audioAi.title', 'Lokale Audioanalyse')}</strong><span className="muted">{t('admin.assistant.related.audioScope', 'Lokale Heuristiken und optionale Modellanalyse')}</span></summary>
                <div className="form-grid compact-grid">
                  <label className="check"><input type="checkbox" checked={settings.audio_ai_analysis_enabled !== false} onChange={(event) => setSettings({ ...settings, audio_ai_analysis_enabled: event.target.checked })} /> {t('admin.audioAi.enable', 'Audioanalyse in der Library aktivieren')}</label>
                  <label className="check"><input type="checkbox" checked={settings.audio_ai_analysis_ai_summary_enabled !== false} onChange={(event) => setSettings({ ...settings, audio_ai_analysis_ai_summary_enabled: event.target.checked })} /> {t('admin.audioAi.aiSummary', 'Report durch bestehendes KI-System aufbereiten')}</label>
                  <label className="check"><input type="checkbox" checked={Boolean(settings.audio_ai_model_analysis_enabled)} onChange={(event) => setSettings({ ...settings, audio_ai_model_analysis_enabled: event.target.checked })} /> {t('admin.audioAi.modelAnalysis', 'Interne Modellanalyse aktivieren')}</label>
                  <label className="check"><input type="checkbox" checked={Boolean(settings.audio_ai_acoustid_configured)} readOnly /> AcoustID API-Key {settings.audio_ai_acoustid_configured ? t('admin.provider.configured', 'konfiguriert') : t('admin.provider.notConfigured', 'nicht konfiguriert')}</label>
                  <label>{t('admin.audioAi.maxSeconds', 'Basisanalyse max. Sekunden')}<input type="number" min="30" max="1200" value={settings.audio_ai_analysis_max_seconds || 240} onChange={(event) => setSettings({ ...settings, audio_ai_analysis_max_seconds: event.target.value })} /></label>
                  <label>{t('admin.audioAi.modelSeconds', 'Modellanalyse Clip-Sekunden')}<input type="number" min="8" max="90" value={settings.audio_ai_model_analysis_seconds || 30} onChange={(event) => setSettings({ ...settings, audio_ai_model_analysis_seconds: event.target.value })} /></label>
                  <label>{t('admin.audioAi.topK', 'Modell Top-K Treffer')}<input type="number" min="5" max="25" value={settings.audio_ai_model_analysis_top_k || 8} onChange={(event) => setSettings({ ...settings, audio_ai_model_analysis_top_k: event.target.value })} /></label>
                  <p className="muted wide">{t('admin.audioAi.hint', 'Bei deaktivierter Modellanalyse bleiben Tempo, Signal, Copyright-Fingerprint und lokale Heuristiken erhalten.')}</p>
                </div>
              </details>

              <details className="assistant-related-details" id="assistant-library-tagging-settings">
                <summary><Search size={17} /> <strong>{t('admin.libraryTags.title', 'KI-Library-Tags')}</strong><span className="muted">{t('admin.assistant.related.libraryScope', 'Manuell gestarteter Suchindex mit eigener Profilzuordnung')}</span></summary>
                <div className="form-grid compact-grid">
                  <label className="check"><input type="checkbox" checked={Boolean(settings.library_ai_tagging_enabled)} onChange={(event) => setSettings({ ...settings, library_ai_tagging_enabled: event.target.checked })} /> {t('admin.libraryTags.enable', 'KI-Tags in der Library aktivieren')}</label>
                  <label>{t('admin.libraryTags.profile', 'Tagging-Profil')}<select value={settings.library_ai_tagging_profile_id || ''} onChange={(event) => setSettings({ ...settings, library_ai_tagging_profile_id: event.target.value ? Number(event.target.value) : null })}><option value="">{t('admin.libraryTags.defaultProfile', 'Standardprofil / globale KI-Einstellung')}</option>{activeProfiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name} · {profile.provider} / {profile.model}</option>)}</select><small>{t('admin.assistant.related.libraryProfileHint', 'Bei leerer Auswahl greift das globale Standardprofil. Die Verarbeitung wird weiterhin ausschließlich manuell gestartet.')}</small></label>
                  <label>{t('admin.libraryTags.maxTags', 'Max. Tags pro Audio-Variante')}<input type="number" min="2" max="8" value={settings.library_ai_tagging_max_tags_per_asset || 5} onChange={(event) => setSettings({ ...settings, library_ai_tagging_max_tags_per_asset: event.target.value })} /></label>
                  <p className="muted wide">{t('admin.libraryTags.hint', 'Die Tags werden über die zentrale Header-Suche gefunden. Einzel- und Sammelläufe werden ausschließlich manuell gestartet und erscheinen auf der Statusseite.')}</p>
                </div>
              </details>

              <div className="form-actions">
                <button className="primary" type="button" onClick={() => saveAssistantSettings()} disabled={saving}><Save size={16} /> {saving ? t('common.saving', 'Speichert…') : t('stylesPage.save', 'Speichern')}</button>
              </div>
            </article>
          )}
        </div>
      )}

      {activePanel === 'library-search-index' && (
        <LibrarySearchIndexAdmin notify={notify} onTasksChanged={onReload} />
      )}

      {activePanel === 'daw-prompts' && (
        <article className="panel stack">
          <div className="panel-title-row">
            <div>
              <h2>DAW-Prompts</h2>
              <p className="muted">Wiederverwendbare Gesprächsaufhänger für die DAW-KI. In der DAW werden aktive Einträge über <code>/prompts</code> angezeigt und per Klick in das Nachrichtenfeld übernommen.</p>
            </div>
            <button type="button" onClick={load}><RefreshCcw size={16} /> {t('topbar.refresh', 'Aktualisieren')}</button>
          </div>

          <div className="form-grid compact-grid">
            <input
              placeholder="Titel"
              value={newDawPromptHook.title}
              onChange={(event) => setNewDawPromptHook({ ...newDawPromptHook, title: event.target.value })}
            />
            <input
              placeholder="Beschreibung"
              value={newDawPromptHook.description}
              onChange={(event) => setNewDawPromptHook({ ...newDawPromptHook, description: event.target.value })}
            />
            <label>Sortierung
              <input
                type="number"
                value={newDawPromptHook.sort_order}
                onChange={(event) => setNewDawPromptHook({ ...newDawPromptHook, sort_order: Number(event.target.value || 0) })}
              />
            </label>
            <label className="check"><input type="checkbox" checked={newDawPromptHook.is_active} onChange={(event) => setNewDawPromptHook({ ...newDawPromptHook, is_active: event.target.checked })} /> Aktiv</label>
            <label className="wide">Prompt
              <textarea
                className="large"
                placeholder="z. B. Verdopple die erste Hook anhand von Lyrics-/SRT-Struktur und BeatNet+-Downbeats..."
                value={newDawPromptHook.prompt}
                onChange={(event) => setNewDawPromptHook({ ...newDawPromptHook, prompt: event.target.value })}
              />
            </label>
            <button className="primary" type="button" onClick={createDawPromptHook}><Plus size={16} /> Prompt speichern</button>
          </div>

          <div className="instruction-grid">
            {dawPromptHooks.map((hook) => (
              <div className="panel slim-panel stack" key={hook.id}>
                <div className="form-grid compact-grid">
                  <label>Titel
                    <input
                      value={hook.title || ''}
                      onChange={(event) => patchDawPromptHookState(hook.id, { title: event.target.value })}
                      onBlur={(event) => updateDawPromptHook(hook, { title: event.target.value })}
                    />
                  </label>
                  <label>Beschreibung
                    <input
                      value={hook.description || ''}
                      onChange={(event) => patchDawPromptHookState(hook.id, { description: event.target.value })}
                      onBlur={(event) => updateDawPromptHook(hook, { description: event.target.value })}
                    />
                  </label>
                  <label>Sortierung
                    <input
                      type="number"
                      value={hook.sort_order ?? 0}
                      onChange={(event) => patchDawPromptHookState(hook.id, { sort_order: Number(event.target.value || 0) })}
                      onBlur={(event) => updateDawPromptHook(hook, { sort_order: Number(event.target.value || 0) })}
                    />
                  </label>
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={hook.is_active !== false}
                      onChange={(event) => updateDawPromptHook(hook, { is_active: event.target.checked })}
                    />
                    Aktiv
                  </label>
                  <label className="wide">Prompt
                    <textarea
                      rows={6}
                      value={hook.prompt || ''}
                      onChange={(event) => patchDawPromptHookState(hook.id, { prompt: event.target.value })}
                      onBlur={(event) => updateDawPromptHook(hook, { prompt: event.target.value })}
                    />
                  </label>
                </div>
                <div className="inline-actions">
                  <button type="button" onClick={() => duplicateDawPromptHook(hook)}><Copy size={15} /> Duplizieren</button>
                  <button type="button" className="danger" onClick={() => deleteDawPromptHook(hook)}><Trash2 size={15} /> {t('texts.delete', 'Löschen')}</button>
                </div>
              </div>
            ))}
            {!dawPromptHooks.length && <p className="muted">Noch keine DAW-Prompts gespeichert.</p>}
          </div>
        </article>
      )}

      {activePanel === 'tags' && (
        <article className="panel stack">
          <div className="panel-title-row">
            <div>
              <h2>{t('admin.vocalTags.title', 'Vocal Tags')}</h2>
              <p className="muted">{t('admin.vocalTags.text', 'Aktive Tags erscheinen im Songtext Studio und werden dem KI-Assistenten als strukturierter Kontext mitgegeben.')}</p>
            </div>
            <div className="inline-actions">
              <button type="button" onClick={() => exportVocalTags('csv', 'simple')}><Download size={15} /> {t('admin.vocalTags.exportBasicCsv', 'Basis CSV')}</button>
              <button type="button" onClick={() => exportVocalTags('markdown', 'extended')}><FileText size={15} /> {t('admin.vocalTags.exportDetailsMd', 'Details MD')}</button>
              <label className="button"><Upload size={15} /> {t('admin.vocalTags.import', 'Import')}<input type="file" accept=".csv,.md,.markdown,text/csv,text/markdown,text/plain" hidden onChange={importVocalTagsFile} /></label>
            </div>
          </div>
          <div className="form-grid compact-grid">
            <input placeholder={t('admin.vocalTags.labelPlaceholder', 'Label')} value={newTag.label} onChange={(event) => setNewTag({ ...newTag, label: event.target.value })} />
            <input placeholder={t('admin.vocalTags.tagPlaceholder', '[Verse 1 | German Male Rap | powerful]')} value={newTag.tag} onChange={(event) => setNewTag({ ...newTag, tag: event.target.value })} />
            <input placeholder={t('admin.vocalTags.category', 'Kategorie')} value={newTag.category} onChange={(event) => setNewTag({ ...newTag, category: event.target.value })} />
            <input placeholder={t('admin.common.description', 'Beschreibung')} value={newTag.description} onChange={(event) => setNewTag({ ...newTag, description: event.target.value })} />
            <button className="primary" type="button" onClick={createTag}><Plus size={16} /> {t('admin.vocalTags.addTag', 'Tag hinzufügen')}</button>
          </div>
          <div className="tag-admin-list compact-vocal-tags">
            {vocalTags.map((tag) => (
              <div className="tag-admin-row compact-vocal-tag-row" key={tag.id}>
                <div className="vocal-tag-main"><strong>{tag.label}</strong><small className="muted">{tag.category}</small></div>
                <code title={tag.tag}>{tag.tag}</code>
                {tag.description && <small className="muted vocal-tag-description">{tag.description}</small>}
                <div className="inline-actions vocal-tag-actions">
                  <button type="button" onClick={() => updateTag(tag, { is_active: !tag.is_active })}>{tag.is_active ? t('admin.actions.deactivate', 'Deaktivieren') : t('admin.actions.activate', 'Aktivieren')}</button>
                  <button type="button" className="danger" onClick={() => deleteTag(tag)}><Trash2 size={15} /> {t('texts.delete', 'Löschen')}</button>
                </div>
              </div>
            ))}
          </div>
        </article>
      )}
    </section>
  );
}
