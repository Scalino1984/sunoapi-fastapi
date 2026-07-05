export const assistantActionRegistry = {
  navigate_home: { id: 'navigate_home', label: 'Zur Startseite', type: 'frontend', requires_confirmation: false },
  navigate_library: { id: 'navigate_library', label: 'Library öffnen', type: 'frontend', requires_confirmation: false },
  navigate_lyrics: { id: 'navigate_lyrics', label: 'Songtext-Studio öffnen', type: 'frontend', requires_confirmation: false },
  navigate_music_wizard: { id: 'navigate_music_wizard', label: 'Neuen Song starten', type: 'frontend', requires_confirmation: false },
  navigate_daw: { id: 'navigate_daw', label: 'Mini-DAW öffnen', type: 'frontend', requires_confirmation: false },
  navigate_export: { id: 'navigate_export', label: 'Exportbereich öffnen', type: 'frontend', requires_confirmation: false },
  srt_focus_editor: { id: 'srt_focus_editor', label: 'SRT-Editor öffnen', type: 'frontend', requires_confirmation: false },
  srt_add_segment: { id: 'srt_add_segment', label: 'SRT-Segment hinzufügen', type: 'frontend', requires_confirmation: false },
  srt_shift_from_here: { id: 'srt_shift_from_here', label: 'SRT ab hier verschieben', type: 'frontend', requires_confirmation: false },
  srt_extend_selected: { id: 'srt_extend_selected', label: 'SRT-Segment verlängern', type: 'frontend', requires_confirmation: false },
  refresh_app: { id: 'refresh_app', label: 'Aktualisieren', type: 'frontend', requires_confirmation: false },
  play_latest_audio: { id: 'play_latest_audio', label: 'Neuesten Song abspielen', type: 'frontend', requires_confirmation: false },
  lyrics_create_new: { id: 'lyrics_create_new', label: 'Songtext erstellen', type: 'ai_canvas', requires_confirmation: true },
  lyrics_make_harder: { id: 'lyrics_make_harder', label: 'Text härter machen', type: 'ai_canvas', requires_confirmation: true },
  lyrics_suno_ready: { id: 'lyrics_suno_ready', label: 'Suno-ready machen', type: 'ai_canvas', requires_confirmation: true },
  lyrics_doubletime: { id: 'lyrics_doubletime', label: 'Doubletime prüfen', type: 'ai_canvas', requires_confirmation: true },
  lyrics_vocal_tags: { id: 'lyrics_vocal_tags', label: 'Vocal Tags optimieren', type: 'ai_canvas', requires_confirmation: true },
  lyrics_hook: { id: 'lyrics_hook', label: 'Hook verbessern', type: 'ai_canvas', requires_confirmation: true },
  lyrics_rhyme: { id: 'lyrics_rhyme', label: 'Reimdichte erhöhen', type: 'ai_canvas', requires_confirmation: true },
  lyrics_save: { id: 'lyrics_save', label: 'Songtext speichern', type: 'frontend', requires_confirmation: false },
  lyrics_apply_preview: { id: 'lyrics_apply_preview', label: 'Vorschau übernehmen', type: 'frontend', requires_confirmation: false },
  lyrics_discard_preview: { id: 'lyrics_discard_preview', label: 'Vorschau verwerfen', type: 'frontend', requires_confirmation: false },
  music_open_wizard: { id: 'music_open_wizard', label: 'Song-Wizard öffnen', type: 'frontend', requires_confirmation: false },
  music_generate_styles: { id: 'music_generate_styles', label: 'KI-Styles vorschlagen', type: 'frontend', requires_confirmation: false },
  admin_open_assistant: { id: 'admin_open_assistant', label: 'KI-Anweisungen verwalten', type: 'frontend', requires_confirmation: false },
  admin_create_prompt: { id: 'admin_create_prompt', label: 'Prompt-Baustein erstellen', type: 'frontend', requires_confirmation: false }
};

export const assistantActionLabels = Object.fromEntries(
  Object.values(assistantActionRegistry).map((action) => [action.id, action.label])
);

function cloneAction(id, overrides = {}) {
  const base = assistantActionRegistry[id] || {
    id,
    label: String(id || '').replaceAll('_', ' '),
    type: String(id || '').startsWith('lyrics_') ? 'ai_canvas' : 'frontend',
    requires_confirmation: String(id || '').startsWith('lyrics_')
  };
  return { ...base, ...overrides };
}

export function buildAvailableAssistantActions(activeTab, lyricsState = {}, context = {}) {
  const tab = String(activeTab || 'home');
  const studioMode = String(lyricsState?.studioMode || 'lyrics');

  if (tab === 'lyrics') {
    if (studioMode === 'instrumental_blueprint') {
      return [
        cloneAction('lyrics_create_new', { label: 'Instrumental-Bauplan erstellen' }),
        cloneAction('lyrics_suno_ready', { label: 'Bauplan Suno-ready machen' }),
        cloneAction('lyrics_make_harder', { label: 'Sounddesign verstärken' }),
        cloneAction('lyrics_save', { label: 'Bauplan speichern' })
      ];
    }
    return [
      cloneAction('lyrics_create_new', { label: 'Neuen Songtext erstellen' }),
      cloneAction('lyrics_make_harder'),
      cloneAction('lyrics_suno_ready'),
      cloneAction('lyrics_doubletime'),
      cloneAction('lyrics_save')
    ];
  }

  if (tab === 'home') {
    return [
      cloneAction('navigate_music_wizard'),
      cloneAction('lyrics_create_new'),
      cloneAction('navigate_lyrics', { label: 'Songtext verbessern' }),
      cloneAction('navigate_library')
    ];
  }

  if (tab === 'music') {
    return [
      cloneAction('music_generate_styles'),
      cloneAction('refresh_app', { label: 'Audio-Liste aktualisieren' }),
      cloneAction('navigate_lyrics'),
      cloneAction('play_latest_audio'),
      cloneAction('navigate_daw')
    ];
  }

  if (tab === 'library') {
    return [
      cloneAction('play_latest_audio'),
      cloneAction('srt_focus_editor'),
      cloneAction('srt_add_segment'),
      cloneAction('srt_shift_from_here'),
      cloneAction('srt_extend_selected'),
      cloneAction('navigate_export'),
      cloneAction('navigate_lyrics', { label: 'Text weiterbearbeiten' }),
      cloneAction('navigate_music_wizard', { label: 'Neue Musik erstellen' }),
      cloneAction('navigate_daw', { label: 'Song in Mini-DAW bearbeiten' })
    ];
  }

  if (tab === 'admin') {
    return [cloneAction('admin_open_assistant'), cloneAction('admin_create_prompt')];
  }

  if (tab === 'status') {
    return [cloneAction('refresh_app'), cloneAction('navigate_library')];
  }

  if (tab === 'daw') {
    return [cloneAction('navigate_daw'), cloneAction('play_latest_audio'), cloneAction('refresh_app'), cloneAction('navigate_library')];
  }

  return [cloneAction('navigate_home'), cloneAction('navigate_lyrics'), cloneAction('refresh_app')];
}

function emitAssistantEvent(name, detail = {}) {
  window.dispatchEvent(new CustomEvent(name, { detail }));
}

export function createAssistantActions({ openMainTab, openAssetInDaw, play, assets, refreshAll, notify, playerState }) {
  return async function executeFrontendAction(actionId, payload = {}) {
    const id = String(actionId || '');
    if (id === 'navigate_home') {
      openMainTab('home');
      return true;
    }
    if (id === 'navigate_library') {
      openMainTab('library');
      return true;
    }
    if (id === 'navigate_export') {
      openMainTab('library');
      window.setTimeout(() => emitAssistantEvent('assistant:library-export-focus', payload), 120);
      notify?.('Exportbereich liegt in den Songdetails der Library. Öffne einen Song und nutze Projekt JSON oder TXT Export.', 'info');
      return true;
    }
    if (id === 'srt_focus_editor' || id === 'srt_add_segment' || id === 'srt_shift_from_here' || id === 'srt_extend_selected') {
      const audioAssetId = payload?.audio_asset_id || payload?.asset_id || payload?.id || playerState?.currentAssetId || null;
      openMainTab('library');
      if (id === 'srt_add_segment' || id === 'srt_focus_editor') {
        window.setTimeout(() => emitAssistantEvent(id === 'srt_add_segment' ? 'assistant:srt-add-segment' : 'assistant:srt-focus-editor', {
          ...(payload || {}),
          audio_asset_id: audioAssetId,
          start: payload?.start ?? playerState?.currentTime ?? null
        }), 160);
      } else {
        window.setTimeout(() => emitAssistantEvent('assistant:srt-focus-editor', { audio_asset_id: audioAssetId }), 80);
        window.setTimeout(() => emitAssistantEvent('assistant:srt-editor-command', {
          ...(payload || {}),
          audio_asset_id: audioAssetId,
          command: id === 'srt_shift_from_here' ? 'shift_from_here' : 'extend_selected',
          delta: Number(payload?.delta ?? payload?.seconds ?? 5),
          ripple: payload?.ripple ?? true
        }), 260);
      }
      notify?.('SRT-Editor-Aktion wird in der Library vorbereitet.', 'info');
      return true;
    }
    if (id === 'navigate_lyrics') {
      openMainTab('lyrics');
      return true;
    }
    if (id === 'navigate_music_wizard' || id === 'music_open_wizard') {
      openMainTab('music', { wizard: true });
      return true;
    }
    if (id === 'music_generate_styles') {
      openMainTab('music');
      window.setTimeout(() => emitAssistantEvent('assistant:music-generate-styles'), 120);
      return true;
    }
    if (id === 'navigate_daw') {
      const assetId = payload?.audio_asset_id || payload?.asset_id || payload?.id || playerState?.currentAssetId || null;
      if (assetId) {
        openAssetInDaw?.(assetId);
      } else {
        openMainTab('daw');
      }
      return true;
    }
    if (id === 'play_latest_audio') {
      const sorted = [...(assets || [])].sort((a, b) => new Date(b.created_at || b.updated_at || 0) - new Date(a.created_at || a.updated_at || 0));
      if (!sorted.length) {
        notify?.('Es wurde noch keine Audiodatei gefunden.', 'error');
        return false;
      }
      play(sorted, 0);
      return true;
    }
    if (id === 'lyrics_save') {
      emitAssistantEvent('assistant:lyrics-save');
      return true;
    }
    if (id === 'lyrics_apply_preview') {
      openMainTab('lyrics');
      window.setTimeout(() => emitAssistantEvent('assistant:lyrics-apply-preview', payload), 120);
      return true;
    }
    if (id === 'lyrics_discard_preview') {
      emitAssistantEvent('assistant:lyrics-discard-preview');
      return true;
    }
    if (id === 'refresh_app') {
      await refreshAll?.();
      notify?.('Ansicht wurde aktualisiert.', 'success');
      return true;
    }
    if (id === 'admin_open_assistant' || id === 'admin_create_prompt') {
      openMainTab('admin');
      window.setTimeout(() => emitAssistantEvent('assistant:admin-open-prompts', { create: id === 'admin_create_prompt' }), 80);
      return true;
    }
    return false;
  };
}
