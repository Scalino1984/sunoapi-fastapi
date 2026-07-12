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
    assert "Alle SRT" in library
    assert "Alle Stems" in library
    assert "generateSrt" in library
    assert "bulk" in library.lower()


def test_api_client_exposes_safe_srt_and_audio_asset_methods():
    client = _read("frontend-react/src/api/client.js")

    assert "archive:" in client
    assert "generateSrt" in client
    assert "bulkGenerateSrt" in client
    assert "/api/audio-assets/${id}/srt" in client
    assert "detail" in client


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
    assert "setStyle('');" in clear_block
    assert "setNegativeTags('');" in clear_block
    assert "setStyleWeight('');" in clear_block
    assert "setWeirdnessConstraint('');" in clear_block
    assert "setAudioWeight('');" in clear_block
    assert "onClick={clearMusicForm}" in music


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


def test_library_add_vocals_and_instrumental_reuse_saved_payload_options():
    library = _read("frontend-react/src/pages/LibraryPage.jsx")

    run_action_block = library.split("async function runAction", 1)[1].split("async function exportProjectJson", 1)[0]
    assert "const generationOptions = getGenerationOptions(asset);" in run_action_block
    assert "if (typeName === 'Add Vocals')" in run_action_block
    assert "payload.prompt = pickPrompt(asset) || pickLyrics(asset) || title;" in run_action_block
    assert "payload.style = pickStyle(asset) || 'studio vocals';" in run_action_block
    assert "payload.negativeTags = generationOptions.negativeTags || 'low quality, distorted, off key';" in run_action_block
    assert "payload.tags = pickStyle(asset) || 'studio instrumental';" in run_action_block
    assert "payload.negativeTags = generationOptions.negativeTags || 'low quality, distorted, noisy';" in run_action_block
    assert "vocalGender: generationOptions.vocalGender || undefined" in run_action_block
    assert "styleWeight: optionalGenerationNumber(generationOptions.styleWeight)" in run_action_block
    assert "weirdnessConstraint: optionalGenerationNumber(generationOptions.weirdnessConstraint)" in run_action_block
    assert "audioWeight: optionalGenerationNumber(generationOptions.audioWeight)" in run_action_block


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
    assert "}, [user, refreshPendingAndReload]);" in app


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
    project_list = library.split("className={`project-audio-action-pill", 1)[1].split("className=\"project-actions\"", 1)[0]
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


def test_audit_repair_confirmation_is_visible_and_never_fails_silently():
    audit_page = _read("frontend-react/src/pages/AuditPage.jsx")

    assert "window.prompt" not in audit_page
    assert "REPAIR_CONFIRMATION_TEXT" in audit_page
    assert "repairConfirmOpen" in audit_page
    assert "repairConfirmError" in audit_page
    assert "repairConfirmText.trim().toUpperCase()" in audit_page
    assert "setRepairConfirmError(message)" in audit_page
    assert "audit-repair-confirm-modal" in audit_page


def test_audit_repairs_have_dedicated_summary_verification_and_compact_details():
    audit_page = _read("frontend-react/src/pages/AuditPage.jsx")
    audit_css = _read("frontend-react/src/styles/app.css")

    assert "audit-repair-result" in audit_page
    assert "currentRepairSummary.changed" in audit_page
    assert "startVerification" in audit_page
    assert "verification_of_repair_task_id" in audit_page
    assert "runHistorySummary(run, t)" in audit_page
    assert "compactFindingsModal" in audit_page
    assert "showGroupSearch" in audit_page
    assert "showGroupPagination" in audit_page
    assert "TRUSTED_HOSTS_WILDCARD" in audit_page
    assert ".audit-findings-modal.compact" in audit_css
    assert ".audit-repair-stat-grid" in audit_css


def test_admin_ai_assistant_explains_effective_runtime_and_usage_boundaries():
    admin = _read("frontend-react/src/pages/AdminPage.jsx")

    assert "assistant-section-tabs" in admin
    assert "loadRuntimePreview" in admin
    assert "api.assistant.runtime" in admin
    assert "Wo greift welche Konfiguration?" in admin
    assert "Globaler KI-Assistent" in admin
    assert "Style-Engine auf /music" in admin
    assert "Songtext-Studio" in admin
    assert "Library-Suchindex" in admin
    assert "DAW-KI" in admin
    assert "KI-Profile und Wissensdateien greifen hier derzeit nicht" in admin
    assert "Transkription, Alignment und lokale Modellanalyse werden nicht durch KI-Profile gesteuert" in admin


def test_admin_ai_profiles_and_instruction_files_are_transparently_manageable():
    admin = _read("frontend-react/src/pages/AdminPage.jsx")
    client = _read("frontend-react/src/api/client.js")

    assert "instructionFiles(true)" in admin
    assert "openProfileEditor" in admin
    assert "saveProfileEditor" in admin
    assert "duplicateProfile" in admin
    assert "openInstructionEditor" in admin
    assert "saveInstructionEditor" in admin
    assert "toggleInstructionFile" in admin
    assert "profileUsageLabels" in admin
    assert "linkedProfilesForFile" in admin
    assert "updateInstructionFile" in client
    assert "include_content=${includeContent ? 'true' : 'false'}" in client


def test_admin_ai_assistant_transparency_has_complete_bilingual_labels():
    de = _read("frontend-react/src/i18n/de.js")
    en = _read("frontend-react/src/i18n/en.js")

    for source in (de, en):
        assert "sections: {" in source
        assert "standards: {" in source
        assert "usage: {" in source
        assert "runtime: {" in source
        assert "warnings: {" in source
        assert "knowledgeTitle:" in source
        assert "profileDuplicated:" in source
        assert "instructionUpdated:" in source


def test_admin_ai_runtime_sources_are_explicit_and_library_profile_is_directly_reachable():
    admin = _read("frontend-react/src/pages/AdminPage.jsx")
    css = _read("frontend-react/src/styles/app.css")
    de = _read("frontend-react/src/i18n/de.js")
    en = _read("frontend-react/src/i18n/en.js")

    assert "runtimeCompositionRows" in admin
    assert "runtimeStatusLabel" in admin
    assert "profileOverridesFallback ? 'overridden' : 'active'" in admin
    assert "assistant-runtime-source-list" in admin
    assert "assistant-runtime-state" in admin
    assert "openLibraryTaggingSettings" in admin
    assert "assistant-library-tagging-settings" in admin
    assert "Profil auswählen" in admin
    assert "assistant-warning-action" in css
    assert "assistant-runtime-source-row" in css
    assert "statusNotUsed" in de
    assert "statusNotUsed" in en
    assert "compositionHint" in de
    assert "compositionHint" in en
