from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_react_app_keeps_route_state_for_library_song_titles():
    app = _read("frontend-react/src/App.jsx")

    assert "libraryRouteTitle" in app
    assert "history.pushState" in app
    assert "'library'" in app
    assert "popstate" in app


def test_keyboard_contract_separates_escape_from_audio_player_close():
    app = _read("frontend-react/src/App.jsx")
    help_page = _read("frontend-react/src/pages/HelpPage.jsx")
    mini_player = _read("frontend-react/src/components/MiniPlayer.jsx")
    profile_menu = _read("frontend-react/src/components/ProfileMenu.jsx")

    assert "const closeAudioPlayer = useCallback" in app
    assert "const closeLibraryDetails = useCallback" in app
    assert "lastPlayedAsset" in app
    assert "const replayLastPlayedAsset = useCallback" in app
    assert "if (key === 'Escape')" in app
    escape_block = app.split("if (key === 'Escape')", 1)[1].split("if (key === ' '", 1)[0]
    assert "closeAudioPlayer();" not in escape_block
    assert "mobileSearchOpen || topbarMenuOpen" in escape_block
    assert "hasTransientUiOverlay()" in escape_block
    assert "closeLibraryDetails();" in escape_block
    assert "if (lower === 'x' && hasLibraryDetails)" in app
    assert "closeAudioPlayer();" in app
    assert "if (lower === 'c')" in app
    assert "sendPlayerCommand('stop-playback')" in app
    assert "if (action === 'stop-playback') { stopPlaybackOnly(); return; }" in mini_player
    assert "function onEscape(event)" in profile_menu
    assert "event.key !== 'Escape'" in profile_menu
    assert "routeDetailSegment(routePathname, 'library')" in app
    assert "if (lower === 'b')" in app
    assert "replayLastPlayedAsset();" in app
    assert "onClose={closeAudioPlayer}" in app
    assert "Audio-Player schließen und Wiedergabe stoppen" in help_page
    assert "Wiedergabe stoppen, Player bleibt offen" in help_page
    assert "Oberstes Modal, Menü oder Suche schließen" in help_page
    assert "Zuletzt gespielten Song erneut öffnen und wiedergeben" in help_page
    assert "Songdetails schließen und zurück zur Library" in help_page
    assert "auch wenn der Audio-Player läuft" in help_page


def test_library_page_keeps_audio_action_menu_and_srt_bulk_actions():
    library = _read("frontend-react/src/pages/LibraryPage.jsx")

    assert "AudioActionMenu" in library
    assert "bulkGenerateSrt" in library
    assert "generateSelectedSrt" in library
    assert "generateSrt" in library
    assert "bulk" in library.lower()


def test_api_client_exposes_safe_srt_and_audio_asset_methods():
    client = _read("frontend-react/src/api/client.js")

    assert "archive:" in client
    assert "generateSrt" in client
    assert "bulkGenerateSrt" in client
    assert "/api/audio-assets/${id}/srt" in client
    assert "detail" in client


def test_library_unplayed_indicator_is_persisted_and_rendered_in_all_asset_views():
    app = _read("frontend-react/src/App.jsx")
    library = _read("frontend-react/src/pages/LibraryPage.jsx")
    client = _read("frontend-react/src/api/client.js")

    assert "markAssetPlayed" in app
    assert "markPlayed" in client
    assert "/mark-played" in client
    assert "function UnplayedIndicator" in library
    assert "gallery-unplayed-indicator" in library
    assert "flat-unplayed-indicator" in library
    assert "pill-unplayed-indicator" in library
    assert "variant-unplayed-indicator" in library


def test_library_layer_actions_prepare_music_instead_of_starting_tasks_directly():
    app = _read("frontend-react/src/App.jsx")
    library = _read("frontend-react/src/pages/LibraryPage.jsx")
    music = _read("frontend-react/src/pages/MusicPage.jsx")

    assert "function prepareAssetLayerSwapInMusic" in library
    layer_block = library.split("function prepareAssetLayerSwapInMusic", 1)[1].split("async function saveAssetLyricsToArchive", 1)[0]
    assert "operationMode: isAddInstrumental ? 'add-instrumental' : 'add-vocals'" in layer_block
    assert "selectedAssetId: String(asset.id)" in layer_block
    assert "instrumental: false" in layer_block
    run_action_block = library.split("async function runAction", 1)[1].split("async function exportProjectJson", 1)[0]
    assert "prepareAssetLayerSwapInMusic(asset, typeName);" in run_action_block
    assert "api.archive.addVocals" not in run_action_block
    assert "api.archive.addInstrumental" not in run_action_block
    assert "...(payload || {})" in app
    assert "setOperationMode(draft.operationMode)" in music
    assert "setSelectedAssetId(String(draft.selectedAssetId ?? draft.assetId ?? ''))" in music
    assert "setWizard(!draft.forceAdvanced);" in music


def test_music_page_defaults_to_expert_form_instead_of_restoring_the_wizard():
    music = _read("frontend-react/src/pages/MusicPage.jsx")

    assert "const [wizard, setWizard] = useState(() => Boolean(initialWizard));" in music
    assert "storedMusicState.wizard !== undefined ? Boolean(storedMusicState.wizard) : initialWizard" not in music


def test_lyrics_studio_recovers_unsaved_canvas_without_server_overwrite():
    lyrics_studio = _read("frontend-react/src/pages/LyricsStudioPage.jsx")

    assert "LYRICS_STUDIO_RECOVERY_KEY = 'react-lyrics-studio-recovery'" in lyrics_studio
    assert "const recoveryRef = useRef(readLyricsStudioRecovery());" in lyrics_studio
    assert "const [canvas, setCanvas] = useState(() => recovery?.canvas || '');" in lyrics_studio
    assert "useLayoutEffect(() => {" in lyrics_studio
    assert "localStorage.setItem(LYRICS_STUDIO_RECOVERY_KEY, JSON.stringify(payload));" in lyrics_studio
    assert "if (!recovery.canvas) setCanvas(restored.canvas_content || '');" in lyrics_studio


def test_music_generate_submit_uses_official_suno_advanced_option_names():
    music = _read("frontend-react/src/pages/MusicPage.jsx")

    submit_block = music.split("async function submit", 1)[1].split("await startTask", 1)[0]
    assert "negativeTags: negativeTags || undefined" in submit_block
    assert "vocalGender: vocalGender || undefined" in submit_block
    assert "styleWeight: numberOrNull(styleWeight)" in submit_block
    assert "weirdnessConstraint: numberOrNull(weirdnessConstraint)" in submit_block
    assert "audioWeight: numberOrNull(audioWeight)" in submit_block


def test_music_clear_button_resets_advanced_suno_fields():
    music = _read("frontend-react/src/pages/MusicPage.jsx")

    clear_block = music.split("function clearMusicForm", 1)[1].split("async function runSafeCheck", 1)[0]
    assert "setOperationMode('generate');" in clear_block
    assert "setStyle('');" in clear_block
    assert "setNegativeTags('');" in clear_block
    assert "setStyleWeight('');" in clear_block
    assert "setWeirdnessConstraint('');" in clear_block
    assert "setAudioWeight('');" in clear_block
    assert "onClick={clearMusicForm}" in music


def test_music_master_style_replaces_negative_tags_but_append_action_merges_them():
    music = _read("frontend-react/src/pages/MusicPage.jsx")

    apply_style_block = music.split("function applyAiStyle", 1)[1].split("function applySuggestedSongTitle", 1)[0]
    assert "const negativeMode = options.negativeMode === 'append' ? 'append' : 'replace';" in apply_style_block
    assert "negativeMode === 'replace' ? nextNegative : mergeCommaTags(current, nextNegative)" in apply_style_block
    assert "applyAiStyle(suggestion, { negativeMode: 'replace' })" in music
    assert "applyNegativeTagsOnly(suggestion, 'append')" in music


def test_music_extend_submit_uses_official_suno_payload_names_and_continue_at():
    music = _read("frontend-react/src/pages/MusicPage.jsx")

    extend_block = music.split("if (operationMode === 'extend')", 1)[1].split("if (operationMode === 'upload-extend')", 1)[0]
    upload_extend_block = music.split("if (operationMode === 'upload-extend')", 1)[1].split("if (operationMode === 'upload-cover')", 1)[0]
    assert "buildAdvancedPayload({ officialSunoNames: true })" in extend_block
    assert "defaultParamFlag: true" in extend_block
    assert "continueAt: continueAtValue || undefined" in extend_block
    assert "autoContinueAt: useAutoContinueAt || undefined" in extend_block
    assert "Bitte eine gültige Extend-Startzeit in Sekunden angeben." in extend_block
    assert "buildAdvancedPayload({ officialSunoNames: true })" in upload_extend_block
    assert "uploadUrl: selectedAudioUrl()" in upload_extend_block
    assert "continueAt: continueAtValue || undefined" in upload_extend_block
    assert "autoContinueAt: useAutoContinueAt || undefined" in upload_extend_block
    assert "Extend ab Sekunde (continueAt)" in music
    assert "continueAt automatisch per Audioanalyse berechnen" in music


def test_music_followup_operations_offer_and_send_official_payload_fields():
    music = _read("frontend-react/src/pages/MusicPage.jsx")

    sounds_block = music.split("if (operationMode === 'sounds')", 1)[1].split("if (operationMode === 'extend')", 1)[0]
    replace_block = music.split("if (operationMode === 'replace-section')", 1)[1].split("if (operationMode === 'persona')", 1)[0]
    persona_block = music.split("if (operationMode === 'persona')", 1)[1].split("if (operationMode === 'boost-style')", 1)[0]
    mashup_block = music.split("if (operationMode === 'mashup')", 1)[1].split("if (operationMode === 'add-instrumental')", 1)[0]

    assert "soundLoop" in sounds_block
    assert "soundTempo: numberOrNull(soundTempo)" in sounds_block
    assert "soundKey: soundKey || undefined" in sounds_block
    assert "grabLyrics" in sounds_block
    assert "taskId" in replace_block
    assert "audioId" in replace_block
    assert "fullLyrics" in replace_block
    assert "infillStartS: numberOrNull(replaceStart)" in replace_block
    assert "infillEndS: numberOrNull(replaceEnd)" in replace_block
    assert "negativeTags: negativeTags || undefined" in replace_block
    assert "Negative Tags optional" in music
    assert "taskId" in persona_block
    assert "audioId" in persona_block
    assert "uploadUrlList: urls" in mashup_block
    assert "vocalGender: vocalGender || undefined" in mashup_block
    assert "domainName: videoDomain || undefined" in music


def test_library_extend_prepare_reuses_generation_options():
    library = _read("frontend-react/src/pages/LibraryPage.jsx")
    client = _read("frontend-react/src/api/client.js")
    utils = _read("frontend-react/src/utils.js")

    form_block = library.split("function defaultAudioOperationForm", 1)[1].split("function openAudioOperationModal", 1)[0]
    submit_block = library.split("async function submitAudioOperation", 1)[1].split("function prepareQuickOperation", 1)[0]
    prepare_block = library.split("function prepareAssetExtendInMusic", 1)[1].split("async function saveAssetLyricsToArchive", 1)[0]
    modal_block = library.split("function AudioOperationModal", 1)[1].split("function renderAudioProjectDossier", 1)[0]
    assert "const generationOptions = getGenerationOptions(asset);" in form_block
    assert "negative_tags: String(generationOptions.negative_tags || '')" in form_block
    assert "const generationOptions = getGenerationOptions(asset);" in prepare_block
    assert "negativeTags: generationOptions.negativeTags || undefined" in prepare_block
    assert "vocalGender: generationOptions.vocalGender || undefined" in prepare_block
    assert "styleWeight: generationOptions.styleWeight !== '' ? generationOptions.styleWeight : undefined" in prepare_block
    assert "weirdnessConstraint: generationOptions.weirdnessConstraint !== '' ? generationOptions.weirdnessConstraint : undefined" in prepare_block
    assert "audioWeight: generationOptions.audioWeight !== '' ? generationOptions.audioWeight : undefined" in prepare_block
    assert "analyzeAudioOperationContinueAt" in library
    assert "Automatisch ermitteln" in modal_block
    assert "analyzeExtendContinueAt" in client
    assert "/extend/analyze-continue-at" in client
    assert "react-library-extend-continue-at-overrides" in library
    assert "readExtendContinueAtOverrides" in form_block
    assert "writeExtendContinueAtOverride(asset.id, continueAt)" in library
    assert "const generationOptions = getGenerationOptions(asset);" in submit_block
    assert "const voiceInfo = voiceInfoForAsset(asset);" in submit_block
    assert "vocal_gender: generationOptions.vocalGender || undefined" in submit_block
    assert "styleWeight: optionalGenerationNumber(generationOptions.styleWeight)" in submit_block
    assert "weirdnessConstraint: optionalGenerationNumber(generationOptions.weirdnessConstraint)" in submit_block
    assert "audioWeight: optionalGenerationNumber(generationOptions.audioWeight)" in submit_block
    assert "persona_id: voiceInfo.id" in submit_block
    assert "persona_model: voiceInfo.source_type === 'persona' ? 'style_persona' : 'voice_persona'" in submit_block
    assert "personaId: ['personaId', 'persona_id', 'voiceId', 'voice_id']" in utils
    assert "personaModel: ['personaModel', 'persona_model']" in utils
    assert "Persona ID" in library
    assert "Persona Model" in library
    assert "function generationOptionsRows(asset)" in library
    assert "negative-tags-row" in library
    assert "main-options-row" in library
    assert "persona-options-row" in library
    assert "generation-option-copy" in library
    assert "`${label} kopieren`" in library
    assert "copyValue: options.personaId || ''" in library


def test_header_search_is_single_source_for_archive_pages_and_library_view_persists():
    app = _read("frontend-react/src/App.jsx")
    playlists = _read("frontend-react/src/pages/PlaylistsPage.jsx")
    styles = _read("frontend-react/src/pages/StylesPage.jsx")
    texts = _read("frontend-react/src/pages/LibraryTextPage.jsx")
    library = _read("frontend-react/src/pages/LibraryPage.jsx")

    assert "<LibraryTextPage lyrics={lyrics} notify={notify} onReload={refreshAll} useForMusic={useLyricForMusic} searchQuery={commandQuery}" in app
    assert "<PlaylistsPage playlists={playlists} assets={assets} notify={notify} onReload={refreshAll} onPlay={play} searchQuery={commandQuery}" in app
    assert "<StylesPage styles={styles} notify={notify} onReload={refreshAll} searchQuery={commandQuery}" in app
    assert "Playlists suchen" not in playlists
    assert "Styles suchen" not in styles
    assert "Songtexte durchsuchen" not in texts
    assert "searchQuery = ''" in playlists
    assert "searchQuery = ''" in styles
    assert "searchQuery = ''" in texts
    assert "readStoredChoice(libraryViewStorageKey, libraryViewModes, 'list')" in library
    assert "writeStoredChoice(libraryViewStorageKey, value, libraryViewModes)" in library


def test_library_add_vocals_and_instrumental_prepare_saved_payload_options_for_music():
    library = _read("frontend-react/src/pages/LibraryPage.jsx")

    layer_block = library.split("function prepareAssetLayerSwapInMusic", 1)[1].split("async function saveAssetLyricsToArchive", 1)[0]
    assert "const generationOptions = getGenerationOptions(asset);" in layer_block
    assert "prompt: sourceText" in layer_block
    assert "style: sourceStyle" in layer_block
    assert "operationTags: sourceStyle" in layer_block
    assert "negativeTags: generationOptions.negativeTags" in layer_block
    assert "vocalGender: generationOptions.vocalGender || ''" in layer_block
    assert "styleWeight: generationOptions.styleWeight" in layer_block
    assert "weirdnessConstraint: generationOptions.weirdnessConstraint" in layer_block
    assert "audioWeight: generationOptions.audioWeight" in layer_block
    assert "selectedAssetId: String(asset.id)" in layer_block


def test_music_add_vocals_requires_an_instrumental_source_preflight():
    music = _read("frontend-react/src/pages/MusicPage.jsx")

    assert "function instrumentalStatusForAsset(asset)" in music
    assert "const addVocalsSourceStatus" in music
    assert "addVocalsSourceStatus === false" in music
    assert "addVocalsInstrumentalConfirmed" in music
    assert "sourceIsInstrumental: addVocalsSourceStatus === true || addVocalsInstrumentalConfirmed" in music
    assert "Instrumentalquelle erforderlich" in music
    assert "if (assetId && !directAudioUrl && !hasUploadedUrl) return startTask(() => api.archive.addVocals" in music


def test_library_song_details_offer_clean_lyrics_clipboard_copy():
    library = _read("frontend-react/src/pages/LibraryPage.jsx")
    utils = _read("frontend-react/src/utils.js")

    assert "cleanLyricsSectionTags" in utils
    assert "textWithoutSectionTags = cleanLyricsSectionTags(text)" in library
    assert "copyWithoutSectionTags" in library
    assert "textWithoutSectionTagsCopied" in library


def test_library_audio_ai_analysis_is_isolated_and_available_in_song_details():
    library = _read("frontend-react/src/pages/LibraryPage.jsx")
    client = _read("frontend-react/src/api/client.js")
    service = _read("app/services/audio_ai_analysis_service.py")
    router = _read("app/routers/audio_assets.py")

    assert "AUDIO AI ANALYSIS CONTRACT" in service
    assert "Nicht koppeln an: Suno-Payloads" in service
    assert "metadata[ANALYSIS_METADATA_KEY]" in service
    assert "storage/analysis" in _read("app/config.py")
    assert "storage/models/huggingface" in _read("app/config.py")
    assert "/home/astier/Projekte/audio_ai_analyzer" not in _read("app/config.py")
    assert "/home/astier/Projekte/audio_ai_analyzer" not in service
    assert "_run_internal_model_analysis" in service
    assert "_analyze_copyright_acoustid" in service
    assert "load_audio_ai_analysis_admin_settings" in service
    assert "getAudioAiAnalysis" in client
    assert "generateAudioAiAnalysis" in client
    assert "audioAiAnalysisExportUrl" in client
    assert "/api/audio-assets/${id}/analysis/generate" in client
    assert "AudioAiAnalysisCard" in library
    assert "AudioAiAnalysisReportModal" in library
    assert "Audioanalyse starten" in library
    assert "Audioanalyse-Report öffnen" in library
    assert "Beatgrid CSV" in library
    assert "def generate_audio_ai_analysis" in router
    assert "def download_audio_ai_analysis_export" in router
    admin = _read("frontend-react/src/pages/AdminPage.jsx")
    schemas = _read("app/schemas.py")
    assert "Lokale Audioanalyse" in admin
    assert "audio_ai_analysis_enabled" in admin
    assert "audio_ai_model_analysis_enabled" in admin
    assert "audio_ai_analysis_enabled" in schemas


def test_library_ai_tagging_is_optional_and_searchable():
    library = _read("frontend-react/src/pages/LibraryPage.jsx")
    client = _read("frontend-react/src/api/client.js")
    utils = _read("frontend-react/src/utils.js")
    admin = _read("frontend-react/src/pages/AdminPage.jsx")
    schemas = _read("app/schemas.py")
    service = _read("app/services/library_ai_tagging_service.py")

    assert "generateAiTags" in client
    assert "bulkGenerateAiTags" in client
    assert "LibraryAiTagsCard" in library
    assert "generateLibraryAiTags" in library
    assert "bulkGenerateAiTags" in library
    assert "metadata_json.ai_tags" in utils
    assert "library_ai_tagging_enabled" in admin
    assert "library_ai_tagging_enabled" in schemas
    assert 'metadata_json["ai_tags"]' in service
    assert "AiChatService" in service


def test_library_audio_ai_report_uses_human_readable_summary_cards():
    library = _read("frontend-react/src/pages/LibraryPage.jsx")
    styles = _read("frontend-react/src/styles/app.css")
    service = _read("app/services/audio_ai_analysis_service.py")

    assert "function audioAiCopyrightSummary" in library
    assert "Kein AcoustID-Treffer" in library
    assert "copyright.risk_level || 'unknown'" not in library
    assert "function audioAiAnalysisMethodLabel" in library
    assert "audioAiReportLead" in library
    assert "audio-ai-cover-frame" in library
    assert "audio-ai-lead-card" in library
    assert "audio-ai-block-text" in library
    assert ".audio-ai-cover-frame" in styles
    assert ".audio-ai-report-block.tone-copyright" in styles
    assert "def _render_html(report: dict[str, Any], asset: AudioAsset)" in service
    assert "def _render_pdf(report: dict[str, Any], asset: AudioAsset)" in service
    assert "def _pdf_cover_image(asset: AudioAsset)" in service
    assert "/Subtype /Image" in service
    assert "/WinAnsiEncoding" in service
    assert "encode(\"cp1252\", \"replace\")" in service
    assert "\"pdf\": {\"path\":" in service
    assert "application/pdf" in service
    assert "regenerated = _write_report_files(asset, analysis)" in service
    assert "audioAiAnalysisExportUrl(asset.id, 'pdf')" in library


def test_react_status_polling_is_rate_limited_and_skips_credit_fetches():
    app = _read("frontend-react/src/App.jsx")

    assert "MIN_STATUS_POLL_INTERVAL_MS" in app
    assert "tasksRef.current" in app
    assert "pollingUntilRef.current" in app
    assert "lastStatusPollAtRef.current" in app
    assert "credits = manual" in app
    assert "refreshPendingAndReload({ silent: true, credits: false })" in app
    assert "shouldFetchCredits ? api.credits() : skippedContent" in app
    assert "shouldFetchNotifications ? api.notifications.list(true) : skippedContent" in app
    assert "const refreshNotificationsOnly = useCallback" in app
    assert "content: false" in app
    assert "tasks: false" in app
    assert "credits: false" in app
    assert "await refreshNotificationsOnly();" in app
    assert "document.addEventListener('visibilitychange', onVisible)" in app
    assert "}, [user, refreshPendingAndReload, refreshNotificationsOnly]);" in app


def test_library_refreshes_when_first_playable_task_variant_arrives():
    app = _read("frontend-react/src/App.jsx")

    assert "function isLibraryContentReadyTaskStatus(status)" in app
    assert "normalized === 'FIRST_SUCCESS' || isTerminalSuccessStatus(normalized)" in app
    assert "successContentRefreshTaskStatesRef" in app
    assert "const taskStateKey = `${taskKey}:${status}`;" in app
    assert "deferContentWhilePlaying: !libraryIsVisible" in app
    assert "ignorePlaybackLock: libraryIsVisible" in app


def test_library_extended_assets_open_original_from_audio_action_menu_only():
    library = _read("frontend-react/src/pages/LibraryPage.jsx")

    assert "function isExtendedAsset(asset)" in library
    assert "function extendSourceAudioId(asset)" in library
    assert "function ExtendSourceBadge" not in library
    assert "const assetByAudioId = useMemo" in library
    assert "const projectByAssetId = useMemo" in library
    assert "openExtendOriginal(asset, event)" in library
    assert "const extendInfo = extendInfoForAsset(asset);" in library
    assert "Original öffnen" in library
    assert "Original nicht lokal gefunden" in library

    gallery_tile = library.split("function AssetGalleryTile", 1)[1].split("function AssetFlatListRow", 1)[0]
    flat_list = library.split("function AssetFlatListRow", 1)[1].split("function LibraryFlatListView", 1)[0]
    project_gallery = library.split("function ProjectGalleryCard", 1)[1].split("function LibraryGalleryView", 1)[0]
    project_list = library.split("className=\"library-variant-list\"", 1)[1].split("function ActionModal", 1)[0]
    menu = library.split("function AudioActionMenu", 1)[1].split("function SparklesIconFallback", 1)[0]

    assert "ExtendSourceBadge" not in gallery_tile
    assert "ExtendSourceBadge" not in flat_list
    assert "ExtendSourceBadge" not in project_gallery
    assert "ExtendSourceBadge" not in project_list
    assert "extendInfo.isExtended" in menu
    assert "openExtendOriginal(asset, event)" in menu


def test_ai_cover_modal_blocks_page_shortcuts_and_sends_reference_image():
    app = _read("frontend-react/src/App.jsx")
    modal = _read("frontend-react/src/components/Modal.jsx")
    library = _read("frontend-react/src/pages/LibraryPage.jsx")

    assert "app-modal-open" in app
    assert "onKeyDownCapture={(event) => event.stopPropagation()}" in modal
    assert "handleAiCoverReferenceFileChange" in library
    assert "formData.append('reference_image', aiCoverForm.referenceFile, aiCoverForm.referenceFile.name" in library
    assert "Referenz übernommen" in library
    assert "function AiCoverModal" not in library
    assert "<AiCoverModal" not in library
    assert "{renderAiCoverModal()}" in library
    assert "{renderCoverReplaceModal()}" in library
    assert "Textfelder verlieren nach jedem Buchstaben den Fokus" in library


def test_song_details_offer_cover_viewer_and_download_actions():
    library = _read("frontend-react/src/pages/LibraryPage.jsx")
    css = _read("frontend-react/src/styles/app.css")

    assert "function renderPictureViewerModal()" in library
    assert "{renderPictureViewerModal()}" in library
    assert "openPictureViewer" in library
    assert "downloadCoverImage" in library
    assert "Cover groß anzeigen" in library
    assert "Cover herunterladen" in library
    assert "pictureViewerZoom" in library
    assert "picture-viewer-modal" in css
    assert "picture-viewer-stage" in css


def test_manual_cover_upload_updates_library_cover_state_immediately():
    library = _read("frontend-react/src/pages/LibraryPage.jsx")

    assert "coverOverrides" in library
    assert "setCoverOverrides" in library
    assert "result?.cover?.public_url" in library
    assert "result?.updated_audio_asset_ids" in library
    assert "image_url: coverUrl" in library
    assert "cover_local_url: coverUrl" in library


def test_library_ui_actions_preserve_scroll_position():
    library = _read("frontend-react/src/pages/LibraryPage.jsx")

    assert "function preserveWindowScroll" in library
    assert "async function preserveWindowScrollAsync" in library
    assert "await preserveWindowScrollAsync(() => onReload?.())" in library
    assert "preserveWindowScroll(() => setLocalFilter" in library
    assert "preserveWindowScroll(() => {" in library
    assert "setOpenAudioMenuId" in library


def test_css_contains_modal_and_player_safety_hooks():
    css = _read("frontend-react/src/styles/app.css")

    assert "asset-menu" in css
    assert "mini-player" in css
    assert "z-index" in css

def test_library_content_check_uses_background_task_start_callback():
    source = (ROOT / "frontend-react/src/pages/LibraryPage.jsx").read_text(encoding="utf-8")
    assert "onTaskStarted" in source
    assert "result?.queued && onTaskStarted" in source
    assert "await onTaskStarted(result)" in source
    assert "forceContentRefresh: true" not in source[source.index("async function cacheMissingLibraryContent"):source.index("function audioMenuKey")]


def test_app_enables_polling_window_for_library_background_tasks():
    source = (ROOT / "frontend-react/src/App.jsx").read_text(encoding="utf-8")
    assert "const handleBackgroundTaskStarted = useCallback" in source
    assert "setPollingUntil(Date.now() + POLLING_AFTER_CREATE_MS)" in source
    assert "onTaskStarted={handleBackgroundTaskStarted}" in source
