import React, { useMemo, useRef, useState } from 'react';
import { Download, FileText, Headphones, Plus, Repeat, Repeat1, SkipBack, SkipForward, Upload, X } from 'lucide-react';
import { api } from '../api/client.js';
import { EmptyState } from '../components/EmptyState.jsx';
import { Modal } from '../components/Modal.jsx';
import { SectionHeader } from '../components/SectionHeader.jsx';
import { downloadTextFile, formatDuration, handleCoverImageError, pickCover, pickTitle, safeArray } from '../utils.js';
import { useI18n } from '../i18n/I18nContext.jsx';

export function PlaylistsPage({ playlists, assets, notify, onReload, onPlay, searchQuery = '' }) {
  const { t } = useI18n();
  const [name, setName] = useState('');
  const [playerPlaylist, setPlayerPlaylist] = useState(null);
  const query = String(searchQuery || '').trim().toLowerCase();
  const filtered = useMemo(() => safeArray(playlists, ['playlists', 'items']).filter((playlist) => !query || playlist.name?.toLowerCase().includes(query.toLowerCase())), [playlists, query]);

  async function create() {
    if (!name.trim()) return;
    await api.library.createPlaylist({ name: name.trim(), description: '' });
    setName('');
    notify(t('playlists.messages.created', 'Playlist erstellt.'), 'success');
    onReload();
  }


  async function exportPlaylists(format = 'csv', mode = 'extended') {
    try {
      const content = await api.library.exportPlaylists(format, mode);
      const extension = format === 'markdown' || format === 'md' ? 'md' : 'csv';
      const mime = extension === 'md' ? 'text/markdown;charset=utf-8' : 'text/csv;charset=utf-8';
      downloadTextFile(`suno-playlists-${mode}.${extension}`, content, mime);
      notify(t('playlists.messages.exportCreated', 'Playlist-{{mode}}export wurde erstellt.', { mode: mode === 'extended' ? t('playlists.detail', 'Detail') : t('playlists.basic', 'Basis') }), 'success');
    } catch (err) {
      notify(err?.message || t('playlists.messages.exportFailed', 'Playlist-Export fehlgeschlagen.'), 'error');
    }
  }

  async function importPlaylistsFile(event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    try {
      const result = await api.library.importPlaylists(file);
      notify(t('playlists.messages.imported', 'Playlists importiert: {{imported}}, übersprungen: {{skipped}}.', { imported: result.imported || 0, skipped: result.skipped || 0 }), result.errors?.length ? 'info' : 'success');
      await onReload();
    } catch (err) {
      notify(err?.message || t('playlists.messages.importFailed', 'Playlist-Import fehlgeschlagen.'), 'error');
    }
  }

  async function add(playlistId, audioAssetId) {
    if (!audioAssetId) return;
    await api.library.addPlaylistItem(playlistId, { audio_asset_id: Number(audioAssetId) });
    notify(t('playlists.messages.trackAdded', 'Track hinzugefügt.'), 'success');
    onReload();
  }

  return (
    <section className="page stack">
      <SectionHeader eyebrow={t('nav.library', 'Library')} title={t('nav.playlists', 'Playlists')}>
        <button type="button" onClick={() => exportPlaylists('csv', 'simple')}><Download size={15} /> {t('playlists.basicCsv', 'Basis CSV')}</button>
        <button type="button" onClick={() => exportPlaylists('markdown', 'extended')}><FileText size={15} /> {t('playlists.detailsMd', 'Details MD')}</button>
        <label className="button"><Upload size={15} /> {t('playlists.import', 'Import')}<input type="file" accept=".csv,.md,.markdown,text/csv,text/markdown,text/plain" hidden onChange={importPlaylistsFile} /></label>
      </SectionHeader>
      <div className="panel playlist-create-row"><input placeholder={t('playlists.newPlaylist', 'Neue Playlist')} value={name} onChange={(event) => setName(event.target.value)} /><button className="primary" onClick={create}><Plus size={16} /> {t('playlists.create', 'Erstellen')}</button></div>
      {!filtered.length && <EmptyState title={t('playlists.emptyTitle', 'Keine Playlists')} text={t('playlists.emptyText', 'Lege eine Playlist an und sammle deine besten Versionen.')} />}
      <div className="playlist-grid">
        {filtered.map((playlist) => {
          const playable = (playlist.items || []).map((item) => item.audio_asset).filter(Boolean);
          return (
            <article className="panel playlist-card" key={playlist.id}>
              <div className="row between align-start"><div><h2>{playlist.name}</h2><p className="muted">{t('playlists.tracks', '{{count}} Tracks', { count: playlist.items?.length || 0 })}</p></div><div className="button-row wrap"><button disabled={!playable.length} onClick={() => onPlay(playable, 0)}><Headphones size={16} /> Mini-Player</button><button disabled={!playable.length} onClick={() => setPlayerPlaylist(playlist)}><Headphones size={16} /> Playlist-Player</button></div></div>
              <select onChange={(event) => event.target.value && add(playlist.id, event.target.value)} value=""><option value="">{t('playlists.addTrack', 'Track hinzufügen…')}</option>{assets.map((asset) => <option key={asset.id} value={asset.id}>{pickTitle(asset)}</option>)}</select>
              <div className="playlist-track-list">
                {(playlist.items || []).map((item) => <button key={item.id} className="playlist-track" onClick={() => item.audio_asset && onPlay(playable, playable.findIndex((track) => track.id === item.audio_asset.id))}><span>{pickTitle(item.audio_asset || item.song || item)}</span><small>{formatDuration(item.audio_asset?.duration_seconds)}</small></button>)}
              </div>
            </article>
          );
        })}
      </div>
      <PlaylistPlayerModal playlist={playerPlaylist} onClose={() => setPlayerPlaylist(null)} />
    </section>
  );
}

function PlaylistPlayerModal({ playlist, onClose }) {
  const { t } = useI18n();
  const audioRef = useRef(null);
  const [index, setIndex] = useState(0);
  const [loopMode, setLoopMode] = useState('none');
  const tracks = useMemo(() => (playlist?.items || []).map((item) => item.audio_asset).filter(Boolean), [playlist]);
  const current = tracks[index] || null;

  React.useEffect(() => {
    let cancelled = false;

    async function prepareAndPlay() {
      if (!current || !audioRef.current) return;
      await api.auth.refresh().catch(() => null);
      if (cancelled || !audioRef.current) return;
      audioRef.current.src = api.archive.streamUrl(current.id);
      audioRef.current.load();
      audioRef.current.play().catch(() => {});
    }

    prepareAndPlay();

    return () => {
      cancelled = true;
    };
  }, [current]);

  if (!playlist) return null;

  function close() {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.removeAttribute('src');
      audioRef.current.load();
    }
    onClose();
  }

  function prev() { setIndex((value) => Math.max(0, value - 1)); }
  function next() { setIndex((value) => Math.min(tracks.length - 1, value + 1)); }
  function ended() {
    if (loopMode === 'one') {
      audioRef.current?.play().catch(() => {});
      return;
    }
    if (index < tracks.length - 1) setIndex(index + 1);
    else if (loopMode === 'all') setIndex(0);
  }

  return (
    <Modal open={Boolean(playlist)} title={`Playlist Player: ${playlist.name}`} onClose={close} wide>
      <div className="playlist-player-modal stack">
        {current ? <div className="playlist-now-playing">
          <img src={pickCover(current)} alt="Cover" onError={handleCoverImageError} />
          <div><strong>{pickTitle(current)}</strong><p className="muted">{index + 1}/{tracks.length} · {formatDuration(current.duration_seconds)}</p></div>
        </div> : <EmptyState title={t('playlists.noTracksTitle', 'Keine Tracks')} text={t('playlists.noTracksText', 'Diese Playlist enthält keine abspielbaren Audios.')} />}
        <audio ref={audioRef} controls onEnded={ended} preload="metadata" />
        <div className="button-row wrap">
          <button onClick={prev} disabled={index <= 0}><SkipBack size={16} /> {t('playlists.previous', 'Zurück')}</button>
          <button onClick={next} disabled={index >= tracks.length - 1}><SkipForward size={16} /> {t('playlists.next', 'Vor')}</button>
          <button className={loopMode === 'one' ? 'active' : ''} onClick={() => setLoopMode(loopMode === 'one' ? 'none' : 'one')}><Repeat1 size={16} /> Song loop</button>
          <button className={loopMode === 'all' ? 'active' : ''} onClick={() => setLoopMode(loopMode === 'all' ? 'none' : 'all')}><Repeat size={16} /> Playlist loop</button>
          {current && <a className="button" href={api.archive.downloadUrl(current.id)}><Download size={16} /> Download</a>}
          <button onClick={close}><X size={16} /> {t('common.close', 'Schließen')}</button>
        </div>
        <div className="playlist-track-list modal-list">
          {tracks.map((track, trackIndex) => <button key={track.id} className={trackIndex === index ? 'playlist-track active' : 'playlist-track'} onClick={() => setIndex(trackIndex)}><span>{pickTitle(track)}</span><small>{formatDuration(track.duration_seconds)}</small></button>)}
        </div>
      </div>
    </Modal>
  );
}
