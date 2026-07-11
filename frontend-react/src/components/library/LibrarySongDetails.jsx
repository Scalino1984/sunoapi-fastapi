import React from 'react';
import { ArrowLeft, Download, FileText, Headphones, Maximize2, Pause, Play, ThumbsUp, Trash2 } from 'lucide-react';
import { api } from '../../api/client.js';
import { LibraryVariantDetails } from './LibraryVariantDetails.jsx';
import { formatDate, handleCoverImageError, isPlayable, pickStyle, summarizeStyle } from '../../utils.js';

export function LibrarySongDetails({ ctx }) {
  const {
    activeProject,
    playbackState,
    closeProjectDetails,
    previousProject,
    nextProject,
    openProjectDetails,
    isCurrentProject,
    isPlayingProject,
    preservePlaybackClick,
    playProject,
    projectCoverAsset,
    openPictureViewer,
    downloadCoverImage,
    isAssetFavorite,
    toggleAssetFavorite,
    favoriteSavingIds,
    exportProjectJson,
    exportProjectText,
    saveProjectLyrics,
    reuseProjectPrompt,
    bulkActionBusy,
    generateProjectSrt,
    generateProjectStems,
    selectedIds,
    setSelectedIds,
    openAllVariants,
    collapseAllVariants,
    deleteSelected,
    dossierStats,
    onPlay,
    withVariantPlaybackMeta,
    voiceLabelForAsset,
    InlineRenameTitle,
    t,
  } = ctx;

  const projectQueue = activeProject.assets.filter(isPlayable).map((asset) => withVariantPlaybackMeta(asset, activeProject));

  return (
    <section className={`page stack library-detail-page ${playbackState?.isPlaying ? 'is-playback-stable' : ''}`}>
      <div className="detail-navigation-bar">
        <button className="ghost compact" type="button" onClick={closeProjectDetails}><ArrowLeft size={16} /> {t('library.detail.backToLibrary', 'Zurück zur Library')}</button>
        <div className="detail-navigation-actions">
          <button className="ghost compact" type="button" disabled={!previousProject} onClick={(event) => previousProject && openProjectDetails(previousProject, event)}>← {t('library.detail.previousSong', 'Vorheriger Song')}</button>
          <button className="ghost compact" type="button" disabled={!nextProject} onClick={(event) => nextProject && openProjectDetails(nextProject, event)}>{t('library.detail.nextSong', 'Nächster Song')} →</button>
        </div>
      </div>
      <div className="detail-hero library-hero">
        <button className={`hero-cover-button ${isCurrentProject(activeProject) ? 'is-active-cover' : ''}`} type="button" onClick={(event) => preservePlaybackClick(event, () => playProject(activeProject))} title={isPlayingProject(activeProject) ? t('player.pause', 'Pause') : t('library.detail.playBestVersion', 'Beste Version abspielen')}>
          <img src={activeProject.cover || '/static/favicon.ico'} alt="Cover" onError={handleCoverImageError} />
          <span>{isPlayingProject(activeProject) ? <Pause size={18} /> : <Play size={18} fill="currentColor" />}</span>
        </button>
        <div>
          <p className="eyebrow">{t('library.detail.projectSong', 'Projekt / Song')}</p>
          <InlineRenameTitle asset={activeProject.assets[0]} title={activeProject.title} className="detail-hero-title" heading />
          <p className="muted">{t('library.detail.projectMeta', '{{variants}} Varianten · {{operations}} Vorgänge · erstellt {{created}} · aktualisiert {{updated}}', { variants: activeProject.assets.length, operations: activeProject.operations.length, created: formatDate(activeProject.created_at), updated: formatDate(activeProject.updated_at) })}</p>
          <p className="muted">{summarizeStyle(pickStyle(activeProject.assets.find((asset) => pickStyle(asset))), 220, t)}</p>
          {activeProject.assets.some((asset) => voiceLabelForAsset(asset)) && <p className="muted voice-detail-line">{t('library.detail.voice', 'Stimme')}: <strong>{voiceLabelForAsset(activeProject.assets.find((asset) => voiceLabelForAsset(asset)))}</strong></p>}
          <div className="library-hero-actions">
            <div className="library-hero-primary-actions button-row wrap">
              <button type="button" onClick={() => openPictureViewer(projectCoverAsset)} disabled={!projectCoverAsset}><Maximize2 size={16} /> {t('library.actions.viewCoverLarge', 'Cover groß anzeigen')}</button>
              <button type="button" onClick={() => { const best = activeProject.assets.find((item) => isAssetFavorite(item)) || activeProject.playable?.[0] || activeProject.assets[0]; if (best) toggleAssetFavorite(best, !isAssetFavorite(best)); }} disabled={!activeProject.assets.length || Boolean(favoriteSavingIds.size)}><ThumbsUp size={16} fill={activeProject.assets.some((item) => isAssetFavorite(item)) ? 'currentColor' : 'none'} /> {activeProject.assets.some((item) => isAssetFavorite(item)) ? t('library.actions.removeFavorite', 'Favorit entfernen') : t('library.actions.saveFavorite', 'Als Favorit speichern')}</button>
              <button type="button" onClick={() => generateProjectSrt(activeProject)} disabled={Boolean(bulkActionBusy)}><FileText size={16} /> {bulkActionBusy === 'srt' ? t('library.bulk.srtRunning', 'SRT läuft…') : t('library.detail.createAllSrt', 'Alle SRT erzeugen')}</button>
              <button type="button" onClick={() => generateProjectStems(activeProject)} disabled={Boolean(bulkActionBusy)}><Headphones size={16} /> {bulkActionBusy === 'stems' ? t('library.bulk.stemsRunning', 'Stems laufen…') : t('library.detail.createAllStems', 'Alle Stems erzeugen')}</button>
              <a className="button primary" href={api.archive.bulkAssetBundleUrl(activeProject.assets.map((asset) => asset.id))}><Download size={16} /> {t('library.detail.allAsZip', 'Alle als ZIP')}</a>
            </div>
            <details className="library-hero-action-details">
              <summary>{t('library.actions.moreActions', 'Weitere Aktionen')}</summary>
              <div className="library-hero-action-menu-grid">
                <div className="library-hero-action-menu-group">
                  <strong>{t('library.detail.contentAndExports', 'Inhalte & Export')}</strong>
                  <div className="button-row wrap compact-actions">
                    <button type="button" onClick={() => downloadCoverImage(projectCoverAsset)} disabled={!projectCoverAsset}><Download size={16} /> {t('library.actions.downloadCover', 'Cover herunterladen')}</button>
                    <button type="button" onClick={() => exportProjectJson(activeProject)}>Projekt JSON</button>
                    <button type="button" onClick={() => exportProjectText(activeProject)}>TXT Export</button>
                    <button type="button" onClick={() => saveProjectLyrics(activeProject)}>{t('library.actions.saveLyrics', 'Songtext speichern')}</button>
                    <button type="button" onClick={() => reuseProjectPrompt(activeProject)}>{t('library.actions.reuse', 'Reuse Prompt')}</button>
                  </div>
                </div>
                <div className="library-hero-action-menu-group">
                  <strong>{t('library.detail.variantManagement', 'Varianten verwalten')}</strong>
                  <div className="button-row wrap compact-actions">
                    <button type="button" onClick={() => setSelectedIds(new Set(activeProject.assets.map((asset) => asset.id)))}>{t('library.detail.selectAll', 'Alle auswählen')}</button>
                    <button type="button" onClick={() => setSelectedIds(new Set())}>{t('library.bulk.clearSelection', 'Auswahl aufheben')}</button>
                    <button type="button" onClick={() => openAllVariants(activeProject)}>{t('library.detail.openAllVariants', 'Alle Varianten öffnen')}</button>
                    <button type="button" onClick={() => collapseAllVariants(activeProject)}>{t('library.detail.collapseAllVariants', 'Alle Varianten zuklappen')}</button>
                    <button className="danger" type="button" onClick={() => deleteSelected(activeProject)} disabled={!selectedIds.size}><Trash2 size={16} /> {t('library.detail.deleteSelection', 'Auswahl löschen')}</button>
                  </div>
                </div>
              </div>
            </details>
          </div>
        </div>
      </div>

      <section className="panel project-dossier-panel">
        <div>
          <p className="eyebrow">{t('library.detail.songOverviewEyebrow', 'Übersicht')}</p>
          <h2>{t('library.detail.filesAvailability', 'Dateien & Verfügbarkeit')}</h2>
          <p className="muted">{t('library.detail.filesAvailabilityText', 'Varianten, lokale Dateien und Produktionsstatus dieses Songs kompakt zusammengefasst.')}</p>
        </div>
        <div className="live-status-grid dossier-grid">
          <span><strong>{dossierStats.audioLocal}/{activeProject.assets.length}</strong><small>{t('library.localFilter.audioLocal', 'Audio lokal')}</small></span>
          <span><strong>{dossierStats.coverLocal}/{activeProject.assets.length}</strong><small>{t('library.localFilter.coverLocal', 'Cover lokal')}</small></span>
          <span><strong>{dossierStats.prompts}</strong><small>Prompts/Lyrics</small></span>
          <span><strong>{dossierStats.payloads}</strong><small>Payloads</small></span>
          <span><strong>{dossierStats.favorite}</strong><small>{t('library.favorites', 'Favoriten')}</small></span>
          <span><strong>{dossierStats.final ? t('common.yes', 'Ja') : t('common.no', 'Nein')}</strong><small>{t('library.detail.finalMarked', 'Final markiert')}</small></span>
        </div>
      </section>

      <article className="operation-section" key={`${activeProject.id}-variants`}>
        <header className="operation-header">
          <div>
            <p className="eyebrow">{t('library.stats.variants', 'Varianten')}</p>
            <h2>{activeProject.title} · {t('library.detail.variantCount', '{{count}} Variante(n)', { count: activeProject.assets.length })}</h2>
            <p className="muted">{t('library.detail.operationsCreatedUpdated', '{{operations}} Vorgänge · erstellt {{created}} · zuletzt aktualisiert {{updated}}', { operations: activeProject.operations.length, created: formatDate(activeProject.created_at), updated: formatDate(activeProject.updated_at) })}</p>
          </div>
          <button type="button" onClick={() => onPlay(projectQueue, 0)} disabled={!projectQueue.length}>{t('library.detail.playAllVariants', 'Alle Varianten abspielen')}</button>
        </header>
        <div className="variant-grid compact-variants">
          {activeProject.assets.map((asset, index) => (
            <LibraryVariantDetails
              key={asset.id}
              ctx={ctx}
              asset={asset}
              index={index}
              activeProject={activeProject}
              projectQueue={projectQueue}
            />
          ))}
        </div>
      </article>
    </section>
  );
}
