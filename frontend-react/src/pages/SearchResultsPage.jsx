import React, { useEffect, useMemo, useState } from 'react';
import { FileText, ListMusic, Music2, Palette } from 'lucide-react';
import { api } from '../api/client.js';
import { EmptyState } from '../components/EmptyState.jsx';
import { SectionHeader } from '../components/SectionHeader.jsx';
import { assetSearchText, matchesSearchQuery, pickTitle, safeArray } from '../utils.js';
import { useI18n } from '../i18n/I18nContext.jsx';

const RESULT_LIMIT = 12;

function textSearchValue(item) {
  return [item?.title, item?.content, item?.lyrics, item?.prompt, item?.tags, item?.structure_template].filter(Boolean).join(' ');
}

function styleSearchValue(item) {
  return [item?.name, item?.style_text, item?.content, item?.description, item?.genre, item?.tags].filter(Boolean).join(' ');
}

function playlistSearchValue(item) {
  return [
    item?.name,
    item?.description,
    ...(item?.items || []).flatMap((row) => [row?.audio_asset?.title, row?.audio_asset?.display_title, row?.song?.title]),
  ].filter(Boolean).join(' ');
}

function mergeSearchItems(remoteItems = [], localItems = []) {
  // Der Server kennt auch Inhalte außerhalb der geladenen Library-Seite. Die
  // lokale Kopie enthält dagegen vollständige Metadaten. Beides muss sichtbar
  // bleiben; eine erfolgreiche Serverantwort darf lokale Treffer nicht löschen.
  const byId = new Map();
  remoteItems.forEach((item) => {
    if (item?.id != null) byId.set(String(item.id), item);
  });
  localItems.forEach((item) => {
    if (item?.id != null) byId.set(String(item.id), item);
  });
  return [...byId.values()].slice(0, RESULT_LIMIT);
}

function ResultSection({ icon: Icon, title, items, empty, children }) {
  return (
    <section className="panel stack search-result-section">
      <div className="row align-center gap-sm"><Icon size={18} /><h2>{title}</h2><span className="muted">{items.length}</span></div>
      {items.length ? <div className="mini-list search-result-list">{children}</div> : <p className="muted">{empty}</p>}
    </section>
  );
}

export function SearchResultsPage({ query = '', assets = [], lyrics = [], styles = [], playlists = [], onNavigate, onOpenAsset }) {
  const { t } = useI18n();
  const normalizedQuery = String(query || '').trim();
  const [remoteResults, setRemoteResults] = useState(null);
  const [remoteError, setRemoteError] = useState('');
  const localResults = useMemo(() => ({
    assets: safeArray(assets, ['assets', 'audio_assets', 'items']).filter((asset) => matchesSearchQuery(assetSearchText(asset), normalizedQuery)).slice(0, RESULT_LIMIT),
    lyrics: safeArray(lyrics, ['lyrics', 'items']).filter((item) => matchesSearchQuery(textSearchValue(item), normalizedQuery)).slice(0, RESULT_LIMIT),
    styles: safeArray(styles, ['styles', 'items']).filter((item) => matchesSearchQuery(styleSearchValue(item), normalizedQuery)).slice(0, RESULT_LIMIT),
    playlists: safeArray(playlists, ['playlists', 'items']).filter((item) => matchesSearchQuery(playlistSearchValue(item), normalizedQuery)).slice(0, RESULT_LIMIT),
  }), [assets, lyrics, styles, playlists, normalizedQuery]);
  useEffect(() => {
    let cancelled = false;
    if (!normalizedQuery) {
      setRemoteResults(null);
      setRemoteError('');
      return undefined;
    }
    setRemoteError('');
    api.library.search(normalizedQuery, { pageSize: RESULT_LIMIT })
      .then((result) => {
        if (!cancelled) setRemoteResults(result);
      })
      .catch((error) => {
        if (!cancelled) setRemoteError(error?.message || '');
      });
    return () => { cancelled = true; };
  }, [normalizedQuery]);
  const results = remoteResults ? {
    assets: mergeSearchItems(remoteResults.assets?.items, localResults.assets),
    lyrics: mergeSearchItems(remoteResults.lyrics?.items, localResults.lyrics),
    styles: mergeSearchItems(remoteResults.styles?.items, localResults.styles),
    playlists: mergeSearchItems(remoteResults.playlists?.items, localResults.playlists),
  } : localResults;
  const total = results.assets.length + results.lyrics.length + results.styles.length + results.playlists.length;

  return (
    <section className="page stack search-results-page">
      <SectionHeader eyebrow={t('topbar.search', 'Suche')} title={normalizedQuery ? t('search.resultsFor', 'Treffer für „{{query}}“', { query: normalizedQuery }) : t('search.title', 'Suche')} />
      {!normalizedQuery ? <EmptyState title={t('search.emptyQueryTitle', 'Suchbegriff eingeben')} text={t('search.emptyQueryText', 'Die Header-Suche durchsucht Songs, Songtexte, Styles und Playlists.')} /> : <>
        <p className="muted">{t('search.total', '{{count}} direkte Treffer', { count: total })}</p>
        {remoteError && <p className="warning-text">{t('search.serverFallback', 'Server-Suche nicht verfügbar; es werden die bereits geladenen Inhalte durchsucht.')}</p>}
        {!total && <EmptyState title={t('search.emptyTitle', 'Keine passenden Inhalte')} text={t('search.emptyText', 'Probiere einzelne Begriffe oder entferne Filterwörter.')} />}
        <ResultSection icon={Music2} title={t('search.songs', 'Songs')} items={results.assets} empty={t('search.songsEmpty', 'Keine Songs gefunden.')}>
          {results.assets.map((asset) => <button key={asset.id} type="button" className="mini-list-row" onClick={() => onOpenAsset(asset.id)}><strong>{pickTitle(asset)}</strong><small>{asset.style || asset.tags || asset.operation_label || t('search.songFallback', 'Audio-Variante')}</small></button>)}
        </ResultSection>
        <ResultSection icon={FileText} title={t('search.lyrics', 'Songtexte')} items={results.lyrics} empty={t('search.lyricsEmpty', 'Keine Songtexte gefunden.')}>
          {results.lyrics.map((item) => <button key={item.id} type="button" className="mini-list-row" onClick={() => onNavigate('texts')}><strong>{item.title || t('search.untitledLyric', 'Ohne Titel')}</strong><small>{String(item.content || item.lyrics || '').replace(/\s+/g, ' ').slice(0, 130)}</small></button>)}
        </ResultSection>
        <ResultSection icon={Palette} title={t('search.styles', 'Styles')} items={results.styles} empty={t('search.stylesEmpty', 'Keine Styles gefunden.')}>
          {results.styles.map((item) => <button key={item.id} type="button" className="mini-list-row" onClick={() => onNavigate('styles')}><strong>{item.name || t('search.untitledStyle', 'Ohne Namen')}</strong><small>{item.genre || item.tags || item.description || ''}</small></button>)}
        </ResultSection>
        <ResultSection icon={ListMusic} title={t('search.playlists', 'Playlists')} items={results.playlists} empty={t('search.playlistsEmpty', 'Keine Playlists gefunden.')}>
          {results.playlists.map((item) => <button key={item.id} type="button" className="mini-list-row" onClick={() => onNavigate('playlists')}><strong>{item.name || t('search.untitledPlaylist', 'Ohne Namen')}</strong><small>{item.description || t('search.tracks', '{{count}} Tracks', { count: item.items?.length || 0 })}</small></button>)}
        </ResultSection>
      </>}
    </section>
  );
}
