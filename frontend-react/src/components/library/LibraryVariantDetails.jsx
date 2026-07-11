import React from 'react';
import { ChevronDown, ChevronRight, Clock3, Copy, Download, Edit3, FileText, Film, Headphones, Maximize2, MoreHorizontal, Pause, Play, Plus, Tag, ThumbsUp } from 'lucide-react';
import { api } from '../../api/client.js';
import { Waveform } from '../Waveform.jsx';
import { LibraryDetailAccordion } from './LibraryDetailAccordion.jsx';
import { LibraryDetailSection } from './LibraryDetailSection.jsx';
import { copyToClipboard, formatDuration, handleCoverImageError, isPlayable, pickCover, pickModel, pickStyle, shortId } from '../../utils.js';

export function LibraryVariantDetails({ ctx, asset, index, activeProject, projectQueue }) {
  const {
    playbackState,
    preservePlaybackClick,
    isAssetFavorite,
    toggleAssetFavorite,
    favoriteSavingIds,
    withVariantPlaybackMeta,
    isVariantAccordionOpen,
    toggleVariantAccordion,
    liveSrtLineForAsset,
    selectedIds,
    toggleSelected,
    playAsset,
    isCurrentAsset,
    isPlayingAsset,
    hasAssetVideo,
    openVideoModalFromEvent,
    variantEyebrow,
    variantTitle,
    isAssetFullyLocal,
    audioStatusClass,
    storageStatusLabel,
    assetContentBadges,
    srtByAsset,
    voiceLabelForAsset,
    setActionAsset,
    openWorkflowWizard,
    setPlaylistAsset,
    renameAsset,
    copyAssetInfo,
    reuseAssetPrompt,
    setTimestampAsset,
    generateSrt,
    srtLoadingIds,
    generateLibraryAiTags,
    convertAssetToWav,
    wavLoadingIds,
    canConvertAssetToWav,
    readAssetWavConversion,
    generateAssetStems,
    stemLoadingIds,
    isAudioLocal,
    songDatabaseId,
    assetDatabaseSummary,
    isFallbackCoverUrl,
    readLibraryAiTags,
    voiceInfoForAsset,
    notify,
    GenerationOptionsCard,
    PromptLyricsCard,
    LibraryAiTagsCard,
    AudioAiAnalysisCard,
    StemCard,
    VideoSummaryCard,
    SrtCard,
    AssetContentManager,
    AudioActionMenu,
    openPictureViewer,
    downloadCoverImage,
    t,
  } = ctx;

  const playbackAsset = withVariantPlaybackMeta(asset, activeProject);
  const variantOpen = isVariantAccordionOpen(asset, index);
  const collapsedSrtLine = !variantOpen ? liveSrtLineForAsset(asset) : null;

  return (
    <article className={`variant-card horizontal variant-accordion-card ${variantOpen ? 'is-open' : 'is-collapsed'} ${isCurrentAsset(asset) ? 'is-playing-row' : ''}`} key={asset.id} data-react-asset-row={asset.id}>
      <label className="select-box"><input type="checkbox" checked={selectedIds.has(asset.id)} onChange={() => toggleSelected(asset.id)} /></label>
      <div className="variant-cover-column">
        <button className={`variant-cover-button ${isCurrentAsset(asset) ? 'is-active-cover' : ''}`} type="button" onClick={(event) => preservePlaybackClick(event, () => playAsset(playbackAsset, projectQueue, index, activeProject))} disabled={!isPlayable(asset)} title={isPlayingAsset(asset) ? t('player.pause', 'Pause') : t('player.play', 'Abspielen')}>
          <img src={pickCover(asset)} alt="Cover" onError={handleCoverImageError} />
          <span>{isPlayingAsset(asset) ? <Pause size={18} /> : <Play size={18} fill="currentColor" />}</span>
        </button>
        {hasAssetVideo(asset) && <button type="button" className="primary mp4-watch-button variant-cover-mp4-button" onClick={(event) => openVideoModalFromEvent(event, asset)}><Film size={14} /> {t('library.video.watchMp4Short', 'MP4')}</button>}
      </div>
      <div className="variant-body">
        <button className="variant-accordion-toggle" type="button" onClick={() => toggleVariantAccordion(asset, index)} aria-expanded={variantOpen}>
          <span className="variant-accordion-title">
            <span className="variant-accordion-icon">{variantOpen ? <ChevronDown size={17} /> : <ChevronRight size={17} />}</span>
            <span>
              <p className="eyebrow">{variantEyebrow(asset, activeProject, t)}</p>
              <h3>{variantTitle(asset, activeProject)}</h3>
            </span>
          </span>
          <span className="variant-accordion-badges">
            <span className={`status ${isAssetFullyLocal(asset) ? 'cached' : audioStatusClass(asset)}`}>{storageStatusLabel(asset, t)}</span>
            {assetContentBadges(asset, srtByAsset).map((badge) => <span key={badge.key} className={`status ${badge.className || 'cached'}`}>{badge.label}</span>)}
            <span className="muted compact-only">{formatDuration(asset.duration_seconds)}</span>
          </span>
        </button>
        <button
          type="button"
          className="variant-title-edit-button inline-title-edit-button"
          onClick={(event) => { event.preventDefault(); event.stopPropagation(); renameAsset(asset); }}
          title={t('library.actions.renameTitle', 'Titel ändern')}
          aria-label={t('library.actions.renameTitle', 'Titel ändern')}
        >
          <Edit3 size={13} />
        </button>
        {variantOpen && (
          <div className="variant-detail-layout">
            <section className="variant-detail-section variant-detail-section--summary variant-product-summary">
              <div className="variant-product-summary-main">
                <div>
                  <p className="eyebrow">{t('library.detail.quickInfo', 'Kurzinfo')}</p>
                  <h4>{formatDuration(asset.duration_seconds)} · {storageStatusLabel(asset, t)}</h4>
                  <p className="muted">{variantTitle(asset, activeProject)}{voiceLabelForAsset(asset) ? ` · ${t('library.detail.voice', 'Stimme')}: ${voiceLabelForAsset(asset)}` : ''}</p>
                </div>
                <div className="variant-detail-status-row">
                  <span className={`status ${isAssetFullyLocal(asset) ? 'cached' : audioStatusClass(asset)}`}>{storageStatusLabel(asset, t)}</span>
                  {assetContentBadges(asset, srtByAsset).map((badge) => <span key={badge.key} className={`status ${badge.className || 'cached'}`}>{badge.label}</span>)}
                </div>
              </div>
              <div className="variant-identity-strip variant-identity-strip--product" aria-label={t('library.detail.variantTechnicalSummary', 'Technische Zusammenfassung dieser Variante')}>
                <span><strong>{formatDuration(asset.duration_seconds)}</strong><small>{t('library.duration', 'Dauer')}</small></span>
                <span><strong>{songDatabaseId(asset) ?? '—'}</strong><small>songs.id</small></span>
                <span><strong>{asset.id}</strong><small>audio_assets.id</small></span>
                <span><strong>{shortId(asset.audio_id, 14)}</strong><small>Audio-ID</small></span>
                <span><strong>{shortId(asset.suno_task_id || asset.task_id, 14) || '—'}</strong><small>Task</small></span>
                {voiceLabelForAsset(asset) && <span><strong>{voiceLabelForAsset(asset)}</strong><small>{t('library.detail.voice', 'Stimme')}</small></span>}
              </div>
              {isCurrentAsset(asset) && <div className="library-inline-waveform"><span>{playbackState?.isPlaying ? t('library.playback.running', 'Läuft') : t('library.playback.ready', 'Bereit')} · {formatDuration(playbackState?.currentTime || 0)} / {formatDuration(playbackState?.duration || asset.duration_seconds)}</span><Waveform asset={asset} compact currentTime={playbackState?.currentTime || 0} durationSeconds={playbackState?.duration || asset.duration_seconds} interactive={false} /></div>}
            </section>

            <LibraryDetailSection
              className="variant-detail-section--actions"
              eyebrow={t('library.detail.actions', 'Aktionen')}
              title={t('library.detail.actionsForVariant', 'Aktionen für diese Audio-Variante')}
              description={t('library.detail.actionsForVariantHint', 'Die wichtigsten Bedien-, Inhalts- und Exportaktionen bleiben hier gebündelt erreichbar.')}
              defaultOpen
            >
              <div className="variant-action-groups variant-action-groups--product">
                <div className="variant-action-group variant-action-group--primary">
                  <strong>{t('library.detail.primaryActions', 'Primär')}</strong>
                  <div className="button-row wrap compact-actions">
                    <button type="button" className={isAssetFavorite(asset) ? 'favorite-action is-favorite' : 'favorite-action'} onClick={() => toggleAssetFavorite(asset)} disabled={favoriteSavingIds.has(asset.id)}><ThumbsUp size={15} fill={isAssetFavorite(asset) ? 'currentColor' : 'none'} /> {t('library.favorites', 'Favoriten')}</button>
                    <AudioActionMenu asset={playbackAsset} compact={false} label={t('library.actions.moreActions', 'Mehr')} dropUp />
                    <button type="button" className="stable-detail-action-button" onClick={() => setActionAsset(playbackAsset)}><MoreHorizontal size={15} /> {t('library.actionModal.title', 'Aktionen')}</button>
                    <button type="button" onClick={() => openWorkflowWizard(asset)}><FileText size={15} /> {t('library.workflow.audioWizard', 'Audio-Wizard')}</button>
                    <button type="button" onClick={() => generateSrt(asset)} disabled={srtLoadingIds.has(asset.id)}><FileText size={15} /> {srtLoadingIds.has(asset.id) ? t('library.bulk.srtRunning', 'SRT läuft…') : t('library.bulk.createSrt', 'SRT erzeugen')}</button>
                    <a className="button primary" href={api.archive.assetBundleUrl(asset.id)}><Download size={15} /> ZIP</a>
                  </div>
                </div>
                <details className="variant-secondary-actions">
                  <summary>{t('library.detail.showDirectActions', 'Direktaktionen anzeigen')}</summary>
                  <div className="variant-secondary-action-grid">
                    <div className="variant-action-group">
                      <strong>{t('library.detail.contentAndAiActions', 'Inhalt & KI')}</strong>
                      <div className="button-row wrap compact-actions">
                        <button type="button" onClick={() => copyAssetInfo(asset)}><Copy size={15} /> {t('common.copy', 'Kopieren')}</button>
                        <button type="button" onClick={() => reuseAssetPrompt(asset)}>{t('library.actions.reusePrompt', 'Reuse Prompt')}</button>
                        <button type="button" onClick={() => setTimestampAsset(asset)}><Clock3 size={15} /> {t('library.timestamped.title', 'Timestamped Lyrics')}</button>
                        <button type="button" onClick={() => generateLibraryAiTags(asset, Boolean(readLibraryAiTags(asset)))}><Tag size={15} /> {t('library.aiTags.title', 'KI-Tags')}</button>
                        <button type="button" onClick={() => setPlaylistAsset(asset)}><Plus size={15} /> {t('nav.playlists', 'Playlists')}</button>
                        <button type="button" onClick={() => renameAsset(asset)}><Edit3 size={15} /> {t('common.title', 'Titel')}</button>
                      </div>
                    </div>
                    <div className="variant-action-group">
                      <strong>{t('library.detail.mediaExportActions', 'Medien & Export')}</strong>
                      <div className="button-row wrap compact-actions">
                        <button type="button" onClick={() => openPictureViewer(asset)} disabled={isFallbackCoverUrl(pickCover(asset))}><Maximize2 size={15} /> {t('library.actions.viewCoverLarge', 'Cover groß anzeigen')}</button>
                        <button type="button" onClick={() => downloadCoverImage(asset)} disabled={isFallbackCoverUrl(pickCover(asset))}><Download size={15} /> {t('library.actions.downloadCover', 'Cover')}</button>
                        <button type="button" onClick={() => convertAssetToWav(asset, { download: true })} disabled={wavLoadingIds.has(asset.id) || !canConvertAssetToWav(asset)}><Download size={15} /> {wavLoadingIds.has(asset.id) ? t('library.actions.converting', 'Konvertiere…') : t('library.actions.convertToWav', 'Convert to WAV')}</button>
                        {readAssetWavConversion(asset).available && <a className="button" href={api.archive.wavDownloadUrl(asset.id)}><Download size={15} /> WAV</a>}
                        <button type="button" onClick={() => generateAssetStems(asset)} disabled={stemLoadingIds.has(asset.id) || !isAudioLocal(asset)}><Headphones size={15} /> {stemLoadingIds.has(asset.id) ? t('library.bulk.stemsRunning', 'Stems laufen…') : t('library.content.stemFiles', 'Stem-Dateien')}</button>
                        <a className="button" href={api.archive.downloadUrl(asset.id)}><Download size={15} /> {t('library.actions.downloadAudio', 'Audio herunterladen')}</a>
                      </div>
                    </div>
                  </div>
                </details>
              </div>
            </LibraryDetailSection>

            <LibraryDetailSection
              className="variant-detail-section--metadata"
              eyebrow={t('library.detail.originAndModel', 'Details & Herkunft')}
              title={t('library.detail.modelAndAssignment', 'Modell, Stimme und Zuordnung')}
              description={t('library.detail.modelAndAssignmentHint', 'Supportrelevante Informationen bleiben erreichbar, ohne die Hauptansicht zu belasten.')}
              defaultOpen={false}
              summarySlot={<span className="library-detail-section-mini-summary">{pickModel(asset) || '—'} · audio_assets.id {asset.id}</span>}
            >
              <div className="variant-meta-grid variant-detail-card-grid variant-detail-card-grid--identity">
                <div className="meta-card"><div className="row between"><h4>{t('library.meta.database', 'Datenbank')}</h4><button type="button" onClick={async () => { await copyToClipboard(assetDatabaseSummary(asset)); notify(t('library.messages.databaseIdsCopied', 'Datenbank-IDs kopiert.'), 'success'); }}><Copy size={14} /></button></div><p>songs.id: {songDatabaseId(asset) ?? '—'}<br />audio_assets.id: {asset.id}</p></div>
                <div className="meta-card"><div className="row between"><h4>{t('library.meta.model', 'Modell')}</h4><button type="button" onClick={async () => { await copyToClipboard(pickModel(asset)); notify(t('library.messages.modelCopied', 'Modell kopiert.'), 'success'); }}><Copy size={14} /></button></div><p>{pickModel(asset) || '—'}</p></div>
                <div className="meta-card"><div className="row between"><h4>Audio-ID</h4><button type="button" onClick={async () => { await copyToClipboard(asset.audio_id); notify(t('library.messages.audioIdCopied', 'Audio-ID kopiert.'), 'success'); }}><Copy size={14} /></button></div><p>{asset.audio_id || '—'}</p></div>
                <div className="meta-card"><div className="row between"><h4>Task-ID</h4><button type="button" onClick={async () => { await copyToClipboard(asset.suno_task_id || asset.task_id); notify(t('library.messages.taskIdCopied', 'Task-ID kopiert.'), 'success'); }}><Copy size={14} /></button></div><p>{asset.suno_task_id || asset.task_id || '—'}</p></div>
                <div className="meta-card"><div className="row between"><h4>{t('library.detail.voice', 'Stimme')}</h4><button type="button" disabled={!voiceInfoForAsset(asset)?.id} onClick={async () => { await copyToClipboard(voiceInfoForAsset(asset)?.id || ''); notify(t('library.messages.voiceIdCopied', 'Voice-ID kopiert.'), 'success'); }}><Copy size={14} /></button></div><p>{voiceLabelForAsset(asset) || '—'}</p></div>
                <GenerationOptionsCard asset={asset} />
              </div>
            </LibraryDetailSection>

            <LibraryDetailSection
              className="variant-detail-section--content"
              eyebrow={t('library.detail.content', 'Inhalte')}
              title={t('library.detail.promptStyleAndTags', 'Style, Prompt, Lyrics und KI-Tags')}
              description={t('library.detail.contentHint', 'Kreative Inhalte bleiben kompakt lesbar und sind bei Bedarf vollständig aufklappbar.')}
              defaultOpen
            >
              <div className="variant-meta-grid variant-detail-card-grid variant-detail-card-grid--content">
                <LibraryDetailAccordion
                  title="Style"
                  description={t('library.detail.stylePreviewHint', 'Kompakte Vorschau des verwendeten Musikstils')}
                  text={pickStyle(asset)}
                  maxPreviewLines={3}
                  className="style-detail-accordion"
                  actionSlot={(
                    <button type="button" onClick={async () => { await copyToClipboard(pickStyle(asset)); notify(t('library.messages.styleCopied', 'Style kopiert.'), 'success'); }} disabled={!pickStyle(asset)}><Copy size={14} /> {t('common.copy', 'Kopieren')}</button>
                  )}
                />
                <PromptLyricsCard asset={asset} />
                <LibraryAiTagsCard asset={asset} />
                <AudioAiAnalysisCard asset={asset} />
              </div>
            </LibraryDetailSection>

            <LibraryDetailSection
              className="variant-detail-section--assets"
              eyebrow={t('library.detail.filesAndDownloads', 'Dateien')}
              title={t('library.detail.filesDownloadsAndExports', 'Dateien, Downloads und Exporte')}
              description={t('library.detail.filesDownloadsAndExportsHint', 'Untertitel, Stems, WAV/MP4 und einzelne Bestandteile dieser Variante sauber gebündelt.')}
              defaultOpen
            >
              <div className="variant-meta-grid variant-detail-card-grid variant-detail-card-grid--assets">
                <StemCard asset={asset} />
                {hasAssetVideo(asset) && <VideoSummaryCard asset={asset} />}
                <SrtCard asset={asset} />
                <AssetContentManager asset={asset} />
              </div>
            </LibraryDetailSection>

            <LibraryDetailSection
              className="variant-detail-section--technical"
              eyebrow={t('library.detail.technical', 'Technisch')}
              title={t('library.meta.rawTechnicalData', 'Technische Rohdaten')}
              description={t('library.detail.technicalHint', 'Debug- und Rohdaten bleiben erreichbar, sind aber standardmäßig eingeklappt.')}
              defaultOpen={false}
              summarySlot={<span className="library-detail-section-mini-summary">audio_assets.id {asset.id} · Task {shortId(asset.suno_task_id || asset.task_id, 10) || '—'}</span>}
            >
              <details className="tech-details"><summary>{t('library.meta.rawTechnicalData', 'Technische Rohdaten')}</summary><pre className="keyboard-scroll-region">{JSON.stringify(asset, null, 2)}</pre></details>
            </LibraryDetailSection>
          </div>
        )}

        {!variantOpen && (
          <div className="variant-collapsed-summary">
            <div className="variant-collapsed-copy">
              <span className="variant-collapsed-meta">{formatDuration(asset.duration_seconds)} · songs.id {songDatabaseId(asset) ?? '—'} · audio_assets.id {asset.id} · Audio-ID {shortId(asset.audio_id, 12)} · Task {shortId(asset.suno_task_id, 12)}</span>
              {collapsedSrtLine?.text && (
                <span className={`variant-collapsed-srt ${collapsedSrtLine.isPlaying ? 'is-live' : ''}`}>
                  <span>SRT</span>
                  <strong>{collapsedSrtLine.text}</strong>
                </span>
              )}
            </div>
            <div className="button-row wrap">
              <button type="button" className={isAssetFavorite(asset) ? 'favorite-action is-favorite' : 'favorite-action'} onClick={() => toggleAssetFavorite(asset)} disabled={favoriteSavingIds.has(asset.id)}><ThumbsUp size={15} fill={isAssetFavorite(asset) ? 'currentColor' : 'none'} /></button>
              <AudioActionMenu asset={playbackAsset} compact label="" dropUp />
              <button type="button" onClick={() => toggleVariantAccordion(asset, index)}>{t('library.detail.showDetails', 'Details anzeigen')}</button>
              <button type="button" onClick={() => openWorkflowWizard(asset)}><FileText size={15} /> Wizard</button>
              <a className="button primary" href={api.archive.assetBundleUrl(asset.id)}><Download size={15} /> ZIP</a>
            </div>
          </div>
        )}
      </div>
    </article>
  );
}
