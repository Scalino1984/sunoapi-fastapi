import React, { useEffect, useMemo, useState } from 'react';
import { CheckCircle2, ClipboardCopy, Download, FileJson, Film, GitBranch, RefreshCw, Rocket, Save, Sparkles, Star } from 'lucide-react';
import { api } from '../api/client.js';
import { SectionHeader } from '../components/SectionHeader.jsx';
import { formatDate, formatDuration, safeArray } from '../utils.js';

const STATUS_OPTIONS = [
  ['draft', 'Entwurf'],
  ['lyrics', 'Lyrics'],
  ['generated', 'Generiert'],
  ['selection', 'Auswahl'],
  ['edit', 'Bearbeitung'],
  ['srt', 'SRT'],
  ['video', 'Video'],
  ['youtube', 'YouTube'],
  ['release_ready', 'Release-ready'],
  ['archived', 'Archiviert']
];

function assetTitle(asset) {
  return asset?.display_title || asset?.title || asset?.filename || `Audio #${asset?.id || '—'}`;
}

function stateFromAsset(asset) {
  const state = asset?.production || asset?.readiness?.state || {};
  return {
    production_status: state.production_status || 'draft',
    rating: Number(state.rating || 0),
    energy: Number(state.energy || 0),
    hook_strength: Number(state.hook_strength || 0),
    lyrics_quality: Number(state.lyrics_quality || 0),
    mix_quality: Number(state.mix_quality || 0),
    release_ready: Boolean(state.release_ready),
    youtube_ready: Boolean(state.youtube_ready),
    video_ready: Boolean(state.video_ready),
    notes: state.notes || '',
    youtube_title: state.youtube_title || assetTitle(asset),
    youtube_playlist: state.youtube_playlist || '',
    youtube_description: state.youtube_description || '',
    youtube_tags: Array.isArray(state.youtube_tags) ? state.youtube_tags.join(', ') : String(state.youtube_tags || ''),
    genre: state.genre || '',
    mood: state.mood || '',
    todo: Array.isArray(state.todo) ? state.todo.join('\n') : String(state.todo || '')
  };
}

function ScoreBar({ score = 0 }) {
  const safe = Math.max(0, Math.min(100, Number(score || 0)));
  return (
    <div className="production-scorebar" aria-label={`Readiness ${safe}%`}>
      <span style={{ width: `${safe}%` }} />
    </div>
  );
}

function RatingInput({ label, value, onChange }) {
  const current = Number(value || 0);
  return (
    <label className="production-rating-input">
      <span>{label}</span>
      <div className="production-stars" role="group" aria-label={label}>
        {[1, 2, 3, 4, 5].map((item) => (
          <button key={item} type="button" className={item <= current ? 'active' : ''} onClick={() => onChange(item)} aria-label={`${label}: ${item}`}>
            <Star size={16} />
          </button>
        ))}
      </div>
    </label>
  );
}

function RoadmapPanel({ roadmap = [] }) {
  return (
    <section className="production-roadmap-grid">
      {safeArray(roadmap, ['items']).map((item) => (
        <article className="panel production-roadmap-card" key={item.key || item.title}>
          <div className="row between align-start">
            <div>
              <p className="eyebrow">{item.status || 'geplant'}</p>
              <h3>{item.title}</h3>
            </div>
            <CheckCircle2 size={20} />
          </div>
          <ul>
            {safeArray(item.items).map((entry) => <li key={entry}>{entry}</li>)}
          </ul>
        </article>
      ))}
    </section>
  );
}

function AssetReadinessCard({ item, selected, onSelect }) {
  const readiness = item?.readiness || {};
  const state = item?.production || {};
  const missing = safeArray(readiness.missing).slice(0, 3);
  return (
    <button type="button" className={`production-asset-card ${selected ? 'active' : ''}`} onClick={onSelect}>
      <div className="row between align-start">
        <div>
          <strong>{assetTitle(item)}</strong>
          <small>{state.production_status || 'draft'} · {formatDuration(item.duration_seconds)} · {formatDate(item.updated_at || item.created_at)}</small>
        </div>
        <span className={`production-score-pill score-${readiness.level || 'draft'}`}>{Number(readiness.score || 0)}%</span>
      </div>
      <ScoreBar score={readiness.score} />
      <div className="production-mini-flags">
        {safeArray(readiness.checks).map((check) => (
          <span key={check.key} className={check.passed ? 'ok' : 'missing'}>{check.label}</span>
        ))}
      </div>
      {missing.length > 0 && <small className="muted">Fehlt: {missing.join(', ')}</small>}
    </button>
  );
}

function YoutubePackagePanel({ packageData, onCopy, assetId }) {
  if (!packageData) return <p className="muted">Noch kein YouTube-Paket geladen.</p>;
  return (
    <div className="nested-panel soft-panel stack">
      <div className="row between align-start">
        <div>
          <p className="eyebrow">YouTube Export</p>
          <h3>{packageData.title || 'Unbenannt'}</h3>
          <p className="muted">Playlist: {packageData.playlist || '—'} · Tags: {safeArray(packageData.tags).length}</p>
        </div>
        <div className="button-row wrap right">
          <button type="button" onClick={onCopy}><ClipboardCopy size={15} /> Kopieren</button>
          {assetId && <a className="button" href={api.production.youtubePackageTextUrl(assetId)}><Download size={15} /> TXT</a>}
        </div>
      </div>
      <pre className="production-text-preview">{packageData.text || JSON.stringify(packageData, null, 2)}</pre>
    </div>
  );
}

function VideoPlanPanel({ videoPlan }) {
  if (!videoPlan) return <p className="muted">Noch kein Musikvideo-Plan geladen.</p>;
  return (
    <div className="nested-panel soft-panel stack">
      <div>
        <p className="eyebrow">Musikvideo Workflow</p>
        <h3>{videoPlan.scene_count || 0} Szenen aus {videoPlan.source === 'srt' ? 'SRT' : 'Lyrics'}</h3>
        <p className="muted">{videoPlan.export_hint}</p>
      </div>
      <div className="production-scene-list">
        {safeArray(videoPlan.scenes).slice(0, 10).map((scene) => (
          <article key={scene.index}>
            <strong>Szene {scene.index}</strong>
            <small>{scene.start != null ? `${scene.start}s – ${scene.end}s` : 'ohne Zeitstempel'}</small>
            <p>{scene.lyrics_excerpt || scene.prompt_hint}</p>
          </article>
        ))}
      </div>
    </div>
  );
}

export function ProductionPage({ notify, onReload, onNavigate, onOpenAsset }) {
  const [cockpit, setCockpit] = useState(null);
  const [loading, setLoading] = useState(false);
  const [selectedId, setSelectedId] = useState(null);
  const [details, setDetails] = useState(null);
  const [form, setForm] = useState(stateFromAsset(null));
  const [saving, setSaving] = useState(false);
  const [showRoadmap, setShowRoadmap] = useState(true);

  const assets = useMemo(() => safeArray(cockpit?.assets, ['assets']), [cockpit]);
  const selectedAsset = useMemo(() => assets.find((item) => String(item.id) === String(selectedId)) || assets[0] || null, [assets, selectedId]);

  async function load(options = {}) {
    setLoading(true);
    try {
      const result = await api.production.cockpit();
      setCockpit(result);
      if (!selectedId && result?.assets?.[0]?.id) setSelectedId(result.assets[0].id);
      if (!options.silent) notify?.('Production Cockpit aktualisiert.', 'success');
    } catch (err) {
      notify?.(err?.message || 'Production Cockpit konnte nicht geladen werden.', 'error');
    } finally {
      setLoading(false);
    }
  }

  async function loadDetails(assetId) {
    if (!assetId) return;
    try {
      const result = await api.production.workflow(assetId);
      setDetails(result);
      setForm(stateFromAsset(result.asset));
    } catch (err) {
      notify?.(err?.message || 'Produktionsdaten konnten nicht geladen werden.', 'error');
    }
  }

  useEffect(() => { load({ silent: true }); }, []);
  useEffect(() => { if (selectedAsset?.id) loadDetails(selectedAsset.id); }, [selectedAsset?.id]);

  function updateForm(key, value) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function saveWorkflow(event) {
    event?.preventDefault?.();
    const assetId = selectedAsset?.id;
    if (!assetId) return;
    setSaving(true);
    try {
      const payload = {
        ...form,
        rating: Number(form.rating || 0),
        energy: Number(form.energy || 0),
        hook_strength: Number(form.hook_strength || 0),
        lyrics_quality: Number(form.lyrics_quality || 0),
        mix_quality: Number(form.mix_quality || 0),
        youtube_tags: String(form.youtube_tags || '').split(',').map((item) => item.trim()).filter(Boolean),
        todo: String(form.todo || '').split('\n').map((item) => item.trim()).filter(Boolean)
      };
      const result = await api.production.updateWorkflow(assetId, payload);
      setDetails((current) => ({ ...(current || {}), ...result, asset: result.asset, production: result.production, readiness: result.readiness }));
      await load({ silent: true });
      await onReload?.({ silent: true });
      notify?.('Produktionsdaten gespeichert.', 'success');
    } catch (err) {
      notify?.(err?.message || 'Produktionsdaten konnten nicht gespeichert werden.', 'error');
    } finally {
      setSaving(false);
    }
  }

  async function duplicateVersion() {
    if (!selectedAsset?.id) return;
    const label = prompt('Label für die neue Version:', 'Neue Version');
    if (label === null) return;
    try {
      const result = await api.production.duplicateVersion(selectedAsset.id, { label: label || 'Neue Version', notes: form.notes || '' });
      await load({ silent: true });
      await onReload?.({ silent: true });
      setSelectedId(result?.audio_asset?.id || selectedAsset.id);
      notify?.('Neue logische Version wurde angelegt.', 'success');
    } catch (err) {
      notify?.(err?.message || 'Version konnte nicht erstellt werden.', 'error');
    }
  }

  async function seedPresets() {
    try {
      const result = await api.production.seedStylePresets();
      await onReload?.({ silent: true });
      notify?.(`${result.created || 0} Style-Presets erstellt, ${result.existing || 0} bereits vorhanden.`, 'success');
    } catch (err) {
      notify?.(err?.message || 'Style-Presets konnten nicht angelegt werden.', 'error');
    }
  }

  async function copyYoutubePackage() {
    const text = details?.youtube_package?.text || '';
    if (!text.trim()) return notify?.('Kein YouTube-Paket zum Kopieren vorhanden.', 'error');
    await navigator.clipboard?.writeText(text);
    notify?.('YouTube-Paket kopiert.', 'success');
  }

  const counts = cockpit?.counts || {};
  const readiness = details?.readiness || selectedAsset?.readiness || {};

  return (
    <section className="page stack production-page">
      <SectionHeader eyebrow="Production Suite" title="Workflow Cockpit">
        <button type="button" onClick={() => setShowRoadmap((value) => !value)}><FileJson size={16} /> Plan</button>
        <button type="button" onClick={seedPresets}><Sparkles size={16} /> Presets anlegen</button>
        <button type="button" onClick={() => load()} className={loading ? 'spin' : ''}><RefreshCw size={16} /> Aktualisieren</button>
      </SectionHeader>

      <section className="production-kpi-grid">
        <article className="panel"><span>Tracks</span><strong>{counts.audio_assets ?? '—'}</strong><small>Library gesamt</small></article>
        <article className="panel"><span>Release-ready</span><strong>{counts.release_ready ?? '—'}</strong><small>aktuelle Analyse</small></article>
        <article className="panel"><span>YouTube-ready</span><strong>{counts.youtube_ready ?? '—'}</strong><small>Metadaten vorbereitet</small></article>
        <article className="panel"><span>SRT offen</span><strong>{counts.needs_srt ?? '—'}</strong><small>für letzte Tracks</small></article>
        <article className="panel"><span>Stems offen</span><strong>{counts.needs_stems ?? '—'}</strong><small>für letzte Tracks</small></article>
        <article className="panel"><span>Tasks</span><strong>{counts.open_tasks ?? '—'}</strong><small>offen/laufend</small></article>
      </section>

      {showRoadmap && <RoadmapPanel roadmap={cockpit?.roadmap || []} />}

      <section className="production-layout">
        <aside className="panel stack production-asset-list">
          <div className="row between align-start">
            <div>
              <p className="eyebrow">Tracks</p>
              <h2>Readiness</h2>
            </div>
            <Rocket size={22} />
          </div>
          {!assets.length ? <p className="muted">Keine Audios gefunden.</p> : assets.map((item) => (
            <AssetReadinessCard key={item.id} item={item} selected={String(item.id) === String(selectedAsset?.id)} onSelect={() => setSelectedId(item.id)} />
          ))}
        </aside>

        <main className="panel stack production-workbench">
          {!selectedAsset ? <p className="muted">Wähle einen Track aus.</p> : (
            <>
              <div className="row between align-start">
                <div>
                  <p className="eyebrow">Aktueller Track</p>
                  <h2>{assetTitle(selectedAsset)}</h2>
                  <p className="muted">Readiness: {readiness.score || 0}% · {readiness.label || 'Entwurf'} · {formatDuration(selectedAsset.duration_seconds)}</p>
                </div>
                <div className="button-row wrap right">
                  <button type="button" onClick={() => onOpenAsset?.(selectedAsset.id)}><Rocket size={15} /> Library öffnen</button>
                  <button type="button" onClick={duplicateVersion}><GitBranch size={15} /> Version duplizieren</button>
                  <a className="button" href={selectedAsset.project_id ? api.production.projectExportUrl(selectedAsset.project_id, 'zip') : '#'} onClick={(event) => { if (!selectedAsset.project_id) event.preventDefault(); }}><Download size={15} /> Projekt-ZIP</a>
                </div>
              </div>

              <ScoreBar score={readiness.score} />
              <div className="production-check-grid">
                {safeArray(readiness.checks).map((check) => (
                  <span key={check.key} className={check.passed ? 'ok' : 'missing'}>{check.passed ? '✓' : '•'} {check.label}</span>
                ))}
              </div>

              <form className="production-form stack" onSubmit={saveWorkflow}>
                <div className="form-grid three">
                  <label>Status
                    <select value={form.production_status} onChange={(event) => updateForm('production_status', event.target.value)}>
                      {STATUS_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                  </label>
                  <label>Genre<input value={form.genre} onChange={(event) => updateForm('genre', event.target.value)} placeholder="z. B. Deutschrap" /></label>
                  <label>Stimmung<input value={form.mood} onChange={(event) => updateForm('mood', event.target.value)} placeholder="z. B. düster, humorvoll" /></label>
                </div>

                <div className="production-rating-grid">
                  <RatingInput label="Bewertung" value={form.rating} onChange={(value) => updateForm('rating', value)} />
                  <RatingInput label="Energie" value={form.energy} onChange={(value) => updateForm('energy', value)} />
                  <RatingInput label="Hook" value={form.hook_strength} onChange={(value) => updateForm('hook_strength', value)} />
                  <RatingInput label="Lyrics" value={form.lyrics_quality} onChange={(value) => updateForm('lyrics_quality', value)} />
                  <RatingInput label="Mix" value={form.mix_quality} onChange={(value) => updateForm('mix_quality', value)} />
                </div>

                <div className="form-grid three">
                  <label className="checkbox-line"><input type="checkbox" checked={form.release_ready} onChange={(event) => updateForm('release_ready', event.target.checked)} /> Release-ready</label>
                  <label className="checkbox-line"><input type="checkbox" checked={form.youtube_ready} onChange={(event) => updateForm('youtube_ready', event.target.checked)} /> YouTube-ready</label>
                  <label className="checkbox-line"><input type="checkbox" checked={form.video_ready} onChange={(event) => updateForm('video_ready', event.target.checked)} /> Video-ready</label>
                </div>

                <div className="form-grid two">
                  <label>YouTube Titel<input value={form.youtube_title} onChange={(event) => updateForm('youtube_title', event.target.value)} /></label>
                  <label>YouTube Playlist<input value={form.youtube_playlist} onChange={(event) => updateForm('youtube_playlist', event.target.value)} placeholder="z. B. Deutschrap / Boom Bap" /></label>
                  <label className="wide">YouTube Tags<input value={form.youtube_tags} onChange={(event) => updateForm('youtube_tags', event.target.value)} placeholder="Kommagetrennt" /></label>
                  <label className="wide">YouTube Beschreibung<textarea rows={5} value={form.youtube_description} onChange={(event) => updateForm('youtube_description', event.target.value)} /></label>
                  <label className="wide">To-do<textarea rows={4} value={form.todo} onChange={(event) => updateForm('todo', event.target.value)} placeholder="Ein Punkt pro Zeile" /></label>
                  <label className="wide">Notizen<textarea rows={4} value={form.notes} onChange={(event) => updateForm('notes', event.target.value)} /></label>
                </div>

                <div className="button-row wrap right">
                  <button className="primary" type="submit" disabled={saving}><Save size={16} /> {saving ? 'Speichert…' : 'Produktionsdaten speichern'}</button>
                </div>
              </form>

              <section className="production-output-grid">
                <YoutubePackagePanel packageData={details?.youtube_package} onCopy={copyYoutubePackage} assetId={selectedAsset.id} />
                <VideoPlanPanel videoPlan={details?.video_plan} />
              </section>

              <section className="nested-panel soft-panel stack">
                <div className="row between"><div><p className="eyebrow">Audit</p><h3>Track-Verlauf</h3></div><Film size={18} /></div>
                <div className="production-event-list">
                  {safeArray(details?.events).length === 0 ? <p className="muted">Noch keine Ereignisse vorhanden.</p> : safeArray(details?.events).slice(0, 16).map((event) => (
                    <article key={`${event.source}-${event.id}-${event.created_at}`}>
                      <strong>{event.title || event.event_type}</strong>
                      <small>{event.source} · {formatDate(event.created_at)}</small>
                      {event.message && <p>{event.message}</p>}
                    </article>
                  ))}
                </div>
              </section>
            </>
          )}
        </main>
      </section>
    </section>
  );
}
