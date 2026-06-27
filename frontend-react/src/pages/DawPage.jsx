import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Bot, Clock3, Download, Headphones, Loader2, Play, Save, Scissors, SlidersHorizontal, Sparkles, Wand2 } from 'lucide-react';
import { api } from '../api/client.js';
import { Waveform } from '../components/Waveform.jsx';
import { SectionHeader } from '../components/SectionHeader.jsx';
import { formatDuration, handleCoverImageError, pickCover, pickTitle } from '../utils.js';

function assetLabel(asset) {
  if (!asset) return 'Audio wählen…';
  const title = asset.display_title || asset.title || `Audio #${asset.id}`;
  const version = asset.version_label || asset.operation_label || asset.status || '';
  return `${title}${version ? ` · ${version}` : ''}`;
}

function secondsToTime(value) {
  const total = Math.max(0, Math.round(Number(value || 0)));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function parseTime(value) {
  const text = String(value || '').trim().replace(',', '.');
  if (!text) return 0;
  if (text.includes(':')) {
    const [m, s] = text.split(':').map((item) => Number(item || 0));
    return Math.max(0, (Number.isFinite(m) ? m : 0) * 60 + (Number.isFinite(s) ? s : 0));
  }
  const n = Number(text);
  return Number.isFinite(n) ? Math.max(0, n) : 0;
}

function operationText(operations) {
  if (!operations?.length) return 'Noch keine Operationen im Plan.';
  return operations.map((op) => {
    if (op.type === 'trim') return `Trim ${secondsToTime(op.start)} – ${secondsToTime(op.end)}`;
    if (op.type === 'fade_out') return `Fade-out ${op.duration}s`;
    if (op.type === 'fade_in') return `Fade-in ${op.duration}s`;
    if (op.type === 'gain') return `Lautstärke ${op.gain_db > 0 ? '+' : ''}${op.gain_db} dB`;
    if (op.type === 'normalize') return `Normalisieren ${op.target_lufs || -14} LUFS`;
    if (op.type === 'preset') return `Preset ${op.preset}`;
    return op.type;
  }).join(' · ');
}

export function DawPage({ assets = [], selectedAssetId = null, onSelectedHandled, onPlay, notify, onReload }) {
  const playable = useMemo(() => (assets || []).filter((asset) => asset?.id && (asset.public_url || asset.local_path || asset.source_url)), [assets]);
  const initial = selectedAssetId || localStorage.getItem('react-daw-asset-id') || playable[0]?.id || '';
  const [assetId, setAssetId] = useState(initial);
  const [project, setProject] = useState(null);
  const [loadingProject, setLoadingProject] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [command, setCommand] = useState('');
  const [commandResult, setCommandResult] = useState(null);
  const [activeTab, setActiveTab] = useState('schnitt');
  const [trimStart, setTrimStart] = useState('0:00');
  const [trimEnd, setTrimEnd] = useState('');
  const [fadeIn, setFadeIn] = useState('0');
  const [fadeOut, setFadeOut] = useState('2');
  const [gainDb, setGainDb] = useState('0');
  const [preset, setPreset] = useState('');
  const [shortLength, setShortLength] = useState('30');
  const [markerLabel, setMarkerLabel] = useState('Hook');
  const [markerTime, setMarkerTime] = useState('0:00');
  const [analysis, setAnalysis] = useState(null);
  const audioRef = useRef(null);

  const currentAsset = project?.asset || playable.find((asset) => String(asset.id) === String(assetId));
  const audioUrl = currentAsset?.public_url ? api.archive.streamUrl(currentAsset.id) : currentAsset?.source_url;
  const duration = Number(currentAsset?.duration_seconds || analysis?.duration_seconds || 0);

  useEffect(() => {
    if (!selectedAssetId) return;
    setAssetId(selectedAssetId);
    localStorage.setItem('react-daw-asset-id', String(selectedAssetId));
    onSelectedHandled?.();
  }, [selectedAssetId, onSelectedHandled]);

  useEffect(() => {
    if (!assetId) return;
    localStorage.setItem('react-daw-asset-id', String(assetId));
    setLoadingProject(true);
    api.daw.project(assetId)
      .then(setProject)
      .catch((err) => notify?.(err.message || 'DAW-Projekt konnte nicht geladen werden.', 'error'))
      .finally(() => setLoadingProject(false));
  }, [assetId]);

  function buildPlan(extra = {}) {
    const operations = [];
    const end = parseTime(trimEnd) || duration || null;
    const start = parseTime(trimStart);
    if (end && (start > 0 || end < duration || activeTab === 'schnitt')) operations.push({ type: 'trim', start, end });
    const fadeInSeconds = Number(fadeIn || 0);
    const fadeOutSeconds = Number(fadeOut || 0);
    if (fadeInSeconds > 0) operations.push({ type: 'fade_in', duration: fadeInSeconds });
    if (fadeOutSeconds > 0) operations.push({ type: 'fade_out', duration: fadeOutSeconds });
    const gain = Number(gainDb || 0);
    if (gain) operations.push({ type: 'gain', gain_db: gain });
    if (preset === 'youtube') operations.push({ type: 'normalize', target_lufs: -14 });
    else if (preset) operations.push({ type: 'preset', preset });
    return {
      source_audio_id: Number(assetId),
      operations,
      version_label: extra.version_label || `DAW Edit ${new Date().toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' })}`,
      output_format: extra.output_format || 'mp3',
      create_notification: true,
    };
  }

  async function renderPlan(plan = null) {
    if (!assetId && !plan?.source_audio_id) return notify?.('Bitte zuerst ein Audio auswählen.', 'error');
    setRendering(true);
    try {
      const result = await api.daw.render(plan || buildPlan());
      notify?.(`DAW-Version gespeichert: ${result.version_label || result.display_title || result.id}`, 'success');
      setAssetId(result.id);
      await onReload?.();
    } catch (err) {
      notify?.(err.message || 'DAW-Render fehlgeschlagen.', 'error');
    } finally {
      setRendering(false);
    }
  }

  async function resolveCommand(execute = false) {
    if (!command.trim()) return;
    setRendering(true);
    try {
      const result = await api.daw.resolveCommand({ message: command, execute });
      setCommandResult(result);
      notify?.(result.message || 'Audio-Befehl wurde ausgewertet.', result.rendered_asset ? 'success' : 'info');
      if (result.rendered_asset) {
        setAssetId(result.rendered_asset.id);
        await onReload?.();
      }
    } catch (err) {
      notify?.(err.message || 'Audio-Befehl konnte nicht ausgeführt werden.', 'error');
    } finally {
      setRendering(false);
    }
  }

  async function addMarker() {
    if (!assetId || !markerLabel.trim()) return;
    try {
      const result = await api.daw.addMarker(assetId, { label: markerLabel.trim(), time: parseTime(markerTime), type: 'marker' });
      setProject((current) => current ? { ...current, markers: result.markers || [] } : current);
      notify?.('Marker gespeichert.', 'success');
    } catch (err) {
      notify?.(err.message || 'Marker konnte nicht gespeichert werden.', 'error');
    }
  }

  async function analyze() {
    if (!assetId) return;
    try {
      const result = await api.daw.analyze({ source_audio_id: Number(assetId) });
      setAnalysis(result);
      notify?.('Audioanalyse erstellt.', 'success');
    } catch (err) {
      notify?.(err.message || 'Analyse fehlgeschlagen.', 'error');
    }
  }

  function createShort(length) {
    const audio = audioRef.current;
    const start = audio?.currentTime || 0;
    const end = Math.min(duration || start + Number(length), start + Number(length));
    renderPlan({ source_audio_id: Number(assetId), operations: [{ type: 'trim', start, end }, { type: 'fade_out', duration: 1.5 }], version_label: `Short ${length}s ab ${secondsToTime(start)}`, output_format: 'mp3', create_notification: true });
  }

  return (
    <section className="page stack daw-page">
      <SectionHeader eyebrow="Mini-DAW" title="Audio bearbeiten">
        <button type="button" onClick={analyze}><Sparkles size={15} /> Analysieren</button>
        <button className="primary" type="button" onClick={() => renderPlan()} disabled={rendering || !assetId}>{rendering ? <Loader2 className="spin-icon" size={15} /> : <Save size={15} />} Als neue Version speichern</button>
      </SectionHeader>

      <section className="panel daw-hero-panel">
        <div className="daw-cover"><img src={pickCover(currentAsset) || '/static/favicon.ico'} alt="Cover" onError={handleCoverImageError} /></div>
        <div className="stack">
          <label>Library-Song / Version
            <select value={assetId || ''} onChange={(event) => setAssetId(event.target.value)}>
              {playable.map((asset) => <option key={asset.id} value={asset.id}>{assetLabel(asset)}</option>)}
            </select>
          </label>
          <h2>{currentAsset ? pickTitle(currentAsset) : 'Kein Audio ausgewählt'}</h2>
          <p className="muted">{currentAsset?.version_label || currentAsset?.operation_label || 'Original'} · {formatDuration(duration || currentAsset?.duration_seconds)} · Original bleibt unverändert.</p>
          <div className="button-row wrap">
            <button type="button" onClick={() => currentAsset && onPlay?.([currentAsset], 0)}><Headphones size={15} /> Im Player</button>
            {currentAsset && <a className="button" href={api.archive.downloadUrl(currentAsset.id)}><Download size={15} /> Download</a>}
          </div>
        </div>
      </section>

      {currentAsset && <section className="panel daw-timeline-panel">
        <audio ref={audioRef} controls src={audioUrl || ''} preload="metadata" />
        <Waveform asset={currentAsset} audioRef={audioRef} />
        <div className="daw-marker-strip">
          {(project?.markers || []).map((marker, index) => <button key={`${marker.label}-${index}`} type="button" onClick={() => { if (audioRef.current) audioRef.current.currentTime = Number(marker.time || 0); }}>{marker.label} · {secondsToTime(marker.time)}</button>)}
        </div>
      </section>}

      <section className="panel daw-tools-panel">
        <div className="daw-tool-tabs">
          {[['schnitt', 'Schnitt'], ['laut', 'Lautstärke'], ['verbessern', 'Verbessern'], ['shorts', 'Shorts'], ['marker', 'Marker'], ['ki', 'KI-Befehl'], ['versionen', 'Versionen']].map(([key, label]) => <button key={key} className={activeTab === key ? 'active' : ''} type="button" onClick={() => setActiveTab(key)}>{label}</button>)}
        </div>

        {activeTab === 'schnitt' && <div className="form-grid">
          <label>Start<input value={trimStart} onChange={(event) => setTrimStart(event.target.value)} placeholder="0:00" /></label>
          <label>Ende<input value={trimEnd} onChange={(event) => setTrimEnd(event.target.value)} placeholder={duration ? secondsToTime(duration) : '3:15'} /></label>
          <label>Fade-in Sekunden<input type="number" step="0.1" value={fadeIn} onChange={(event) => setFadeIn(event.target.value)} /></label>
          <label>Fade-out Sekunden<input type="number" step="0.1" value={fadeOut} onChange={(event) => setFadeOut(event.target.value)} /></label>
          <div className="wide muted">Plan: {operationText(buildPlan().operations)}</div>
        </div>}

        {activeTab === 'laut' && <div className="form-grid">
          <label>Lautstärke dB<input type="number" step="0.5" value={gainDb} onChange={(event) => setGainDb(event.target.value)} /></label>
          <button type="button" onClick={() => setGainDb('2')}>+2 dB</button>
          <button type="button" onClick={() => setGainDb('-2')}>-2 dB</button>
          <button type="button" onClick={() => setPreset('youtube')}>YouTube -14 LUFS</button>
        </div>}

        {activeTab === 'verbessern' && <div className="button-grid compact-buttons">
          {[['klarer', 'Klarer'], ['mehr_druck', 'Mehr Druck'], ['bass', 'Mehr Bass'], ['hoehen', 'Mehr Höhen'], ['youtube', 'YouTube Master']].map(([key, label]) => <button key={key} className={preset === key ? 'active' : ''} type="button" onClick={() => setPreset(key)}><Wand2 size={15} /> {label}</button>)}
        </div>}

        {activeTab === 'shorts' && <div className="form-grid">
          <label>Short-Länge<input type="number" value={shortLength} onChange={(event) => setShortLength(event.target.value)} /></label>
          <button type="button" onClick={() => createShort(15)}>15 Sekunden ab Playhead</button>
          <button type="button" onClick={() => createShort(30)}>30 Sekunden ab Playhead</button>
          <button type="button" onClick={() => createShort(60)}>60 Sekunden ab Playhead</button>
        </div>}

        {activeTab === 'marker' && <div className="form-grid">
          <label>Marker-Name<input value={markerLabel} onChange={(event) => setMarkerLabel(event.target.value)} /></label>
          <label>Zeit<input value={markerTime} onChange={(event) => setMarkerTime(event.target.value)} /></label>
          <button type="button" onClick={() => setMarkerTime(secondsToTime(audioRef.current?.currentTime || 0))}><Clock3 size={15} /> Playhead übernehmen</button>
          <button type="button" className="primary" onClick={addMarker}>Marker speichern</button>
        </div>}

        {activeTab === 'ki' && <div className="stack">
          <p className="muted">Beispiel: „Schneide den Song Zeitlos Variante 1 bei 3:15 min und lege einen 2 Sekunden Fade-out drauf.“</p>
          <textarea className="large" value={command} onChange={(event) => setCommand(event.target.value)} placeholder="Audio-Befehl eingeben…" />
          <div className="button-row wrap"><button type="button" onClick={() => resolveCommand(false)}><Bot size={15} /> Plan prüfen</button><button className="primary" type="button" onClick={() => resolveCommand(true)} disabled={rendering}><Scissors size={15} /> Direkt rendern</button></div>
          {commandResult && <pre className="large-pre">{JSON.stringify(commandResult, null, 2)}</pre>}
        </div>}

        {activeTab === 'versionen' && <div className="variant-grid compact-variants">
          {(project?.versions || []).map((asset) => <article className="variant-card" key={asset.id}><strong>{assetLabel(asset)}</strong><p className="muted">{formatDuration(asset.duration_seconds)} · {asset.status}</p><div className="button-row wrap"><button type="button" onClick={() => setAssetId(asset.id)}><SlidersHorizontal size={15} /> Laden</button><button type="button" onClick={() => onPlay?.([asset], 0)}><Play size={15} /> Play</button></div></article>)}
        </div>}
      </section>
    </section>
  );
}
