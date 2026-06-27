import React, { useMemo } from 'react';
import { Bell, BookOpenText, Download, FileText, Headphones, ListMusic, Mic2, Music, Wand2 } from 'lucide-react';
import { EmptyState } from '../components/EmptyState.jsx';
import { formatDate, formatDuration, groupAssetsByProject, pickStyle, safeArray, summarizeStyle } from '../utils.js';

export function HomePage({ assets = [], lyrics = [], playlists = [], tasks = [], notifications = [], credits, onNavigate, onPlay, onOpenAsset }) {
  const projects = useMemo(() => groupAssetsByProject(safeArray(assets, ['assets', 'items'])).slice(0, 6), [assets]);
  const openTasks = useMemo(() => safeArray(tasks, ['tasks', 'items']).filter((task) => {
    const status = String(task.status || '').trim();
    return ['PENDING', 'PROCESSING', 'RUNNING', 'QUEUED', 'SUBMITTED', 'CREATED', 'TEXT_SUCCESS', 'FIRST_SUCCESS'].includes(status.toUpperCase()) || ['submitted', 'processing'].includes(status);
  }).slice(0, 6), [tasks]);
  const unread = useMemo(() => safeArray(notifications, ['notifications', 'items']).filter((item) => item.status !== 'done').slice(0, 5), [notifications]);

  const cards = [
    { title: 'Neuen Song erstellen', text: 'Geführter Wizard aus Idee, Lyrics oder Instrumental.', icon: Music, action: () => onNavigate('music', { wizard: true }) },
    { title: 'Songtext schreiben', text: 'Canvas, KI-Chat, Vocal Tags und Quick-Actions.', icon: Mic2, action: () => onNavigate('lyrics') },
    { title: 'Library öffnen', text: 'Varianten anhören, vergleichen und weiterbearbeiten.', icon: ListMusic, action: () => onNavigate('library') },
    { title: 'Playlist abspielen', text: 'Songs sammeln und als Set anhören.', icon: Headphones, action: () => onNavigate('playlists') },
    { title: 'Styles pflegen', text: 'Suno-Styles speichern und für Songs übernehmen.', icon: Wand2, action: () => onNavigate('styles') },
    { title: 'Status prüfen', text: 'Fertige und laufende Aufträge im Blick behalten.', icon: Bell, action: () => onNavigate('status') }
  ];

  return (
    <section className="page stack home-page">
      <section className="home-hero panel">
        <div>
          <p className="eyebrow">Willkommen zurück</p>
          <h1>Was möchtest du heute produzieren?</h1>
          <p className="muted">Starte über einen klaren Workflow oder setze direkt an deinen letzten Projekten fort.</p>
        </div>
        <div className="home-stats">
          <div><span>Credits</span><strong>{credits ?? '—'}</strong></div>
          <div><span>Songs</span><strong>{projects.length}</strong></div>
          <div><span>Offen</span><strong>{openTasks.length}</strong></div>
        </div>
      </section>

      <section className="workflow-card-grid">
        {cards.map(({ title, text, icon: Icon, action }) => (
          <button className="workflow-card" key={title} type="button" onClick={action}>
            <Icon size={24} />
            <span><strong>{title}</strong><small>{text}</small></span>
          </button>
        ))}
      </section>

      <section className="dashboard-grid">
        <div className="panel stack">
          <div className="row between"><div><p className="eyebrow">Zuletzt</p><h2>Letzte Projekte</h2></div><button type="button" onClick={() => onNavigate('library')}>Library öffnen</button></div>
          {!projects.length ? <EmptyState title="Noch keine Songs" text="Starte deinen ersten Song über den Wizard." /> : <div className="compact-project-list">
            {projects.map((project) => (
              <button className="compact-project-row" key={project.id} type="button" onClick={() => onOpenAsset(project.playable[0]?.id || project.assets[0]?.id)}>
                <img src={project.cover || '/static/favicon.ico'} alt="Cover" />
                <span><strong>{project.title}</strong><small>{project.assets.length} Varianten · {formatDuration(project.duration)} · {summarizeStyle(pickStyle(project.assets.find((asset) => pickStyle(asset))), 100)}</small></span>
              </button>
            ))}
          </div>}
        </div>

        <div className="panel stack">
          <div className="row between"><div><p className="eyebrow">Aufträge</p><h2>Offene Tasks</h2></div><button type="button" onClick={() => onNavigate('status')}>Status</button></div>
          {!openTasks.length ? <p className="muted">Keine laufenden Tasks.</p> : <div className="mini-list">
            {openTasks.map((task) => <div className="mini-list-row" key={task.id}><strong>{task.request_payload?.title || task.task_type}</strong><small>{task.status} · {formatDate(task.updated_at || task.created_at)}</small></div>)}
          </div>}
          <div className="row between"><div><p className="eyebrow">Hinweise</p><h2>Benachrichtigungen</h2></div></div>
          {!unread.length ? <p className="muted">Keine offenen Benachrichtigungen.</p> : <div className="mini-list">
            {unread.map((item) => <button className="mini-list-row" key={item.id} type="button" onClick={() => onNavigate('status')}><strong>{item.title}</strong><small>{item.message || 'Öffnen für Details'}</small></button>)}
          </div>}
        </div>

        <div className="panel stack">
          <div className="row between"><div><p className="eyebrow">Schnellstart</p><h2>Produktionsablauf</h2></div></div>
          <ol className="workflow-steps-list">
            <li><strong>Idee oder Lyrics schreiben</strong><span>Canvas + KI-Assistent nutzen.</span></li>
            <li><strong>Style auswählen</strong><span>Preset, gespeicherter Style oder KI-Vorschlag.</span></li>
            <li><strong>Generieren</strong><span>Wizard starten und Task laufen lassen.</span></li>
            <li><strong>Varianten prüfen</strong><span>Favorit oder Final markieren.</span></li>
            <li><strong>Exportieren</strong><span>MP3, Songtext oder Projekt sichern.</span></li>
          </ol>
        </div>
      </section>
    </section>
  );
}
