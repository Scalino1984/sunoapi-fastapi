import React, { useMemo } from 'react';
import { Bell, BookOpenText, Download, FileText, Headphones, ListMusic, Mic2, Music, Wand2 } from 'lucide-react';
import { EmptyState } from '../components/EmptyState.jsx';
import { formatDate, formatDuration, groupAssetsByProject, pickStyle, safeArray, summarizeStyle } from '../utils.js';
import { useI18n } from '../i18n/I18nContext.jsx';

export function HomePage({ assets = [], lyrics = [], playlists = [], tasks = [], notifications = [], credits, onNavigate, onPlay, onOpenAsset }) {
  const { t } = useI18n();
  const projects = useMemo(() => groupAssetsByProject(safeArray(assets, ['assets', 'items'])).slice(0, 6), [assets]);
  const openTasks = useMemo(() => safeArray(tasks, ['tasks', 'items']).filter((task) => {
    const status = String(task.status || '').trim();
    return ['PENDING', 'PROCESSING', 'RUNNING', 'QUEUED', 'SUBMITTED', 'CREATED', 'TEXT_SUCCESS', 'FIRST_SUCCESS'].includes(status.toUpperCase()) || ['submitted', 'processing'].includes(status);
  }).slice(0, 6), [tasks]);
  const unread = useMemo(() => safeArray(notifications, ['notifications', 'items']).filter((item) => item.status !== 'done').slice(0, 5), [notifications]);

  const cards = [
    { title: t('home.cards.newSong.title', 'Neuen Song erstellen'), text: t('home.cards.newSong.text', 'Geführter Wizard aus Idee, Lyrics oder Instrumental.'), icon: Music, action: () => onNavigate('music', { wizard: true }) },
    { title: t('home.cards.lyrics.title', 'Songtext schreiben'), text: t('home.cards.lyrics.text', 'Canvas, KI-Chat, Vocal Tags und Quick-Actions.'), icon: Mic2, action: () => onNavigate('lyrics') },
    { title: t('home.cards.library.title', 'Library öffnen'), text: t('home.cards.library.text', 'Varianten anhören, vergleichen und weiterbearbeiten.'), icon: ListMusic, action: () => onNavigate('library') },
    { title: t('home.cards.playlist.title', 'Playlist abspielen'), text: t('home.cards.playlist.text', 'Songs sammeln und als Set anhören.'), icon: Headphones, action: () => onNavigate('playlists') },
    { title: t('home.cards.styles.title', 'Styles pflegen'), text: t('home.cards.styles.text', 'Suno-Styles speichern und für Songs übernehmen.'), icon: Wand2, action: () => onNavigate('styles') },
    { title: t('home.cards.status.title', 'Status prüfen'), text: t('home.cards.status.text', 'Fertige und laufende Aufträge im Blick behalten.'), icon: Bell, action: () => onNavigate('status') }
  ];

  return (
    <section className="page stack home-page">
      <section className="home-hero panel">
        <div>
          <p className="eyebrow">{t('home.hero.eyebrow', 'Willkommen zurück')}</p>
          <h1>{t('home.hero.title', 'Was möchtest du heute produzieren?')}</h1>
          <p className="muted">{t('home.hero.text', 'Starte über einen klaren Workflow oder setze direkt an deinen letzten Projekten fort.')}</p>
        </div>
        <div className="home-stats">
          <div><span>{t('home.stats.credits', 'Credits')}</span><strong>{credits ?? '—'}</strong></div>
          <div><span>{t('home.stats.songs', 'Songs')}</span><strong>{projects.length}</strong></div>
          <div><span>{t('home.stats.open', 'Offen')}</span><strong>{openTasks.length}</strong></div>
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
          <div className="row between"><div><p className="eyebrow">{t('home.recent.eyebrow', 'Zuletzt')}</p><h2>{t('home.recent.title', 'Letzte Projekte')}</h2></div><button type="button" onClick={() => onNavigate('library')}>{t('home.openLibrary', 'Library öffnen')}</button></div>
          {!projects.length ? <EmptyState title={t('home.recent.emptyTitle', 'Noch keine Songs')} text={t('home.recent.emptyText', 'Starte deinen ersten Song über den Wizard.')} /> : <div className="compact-project-list">
            {projects.map((project) => (
              <button className="compact-project-row" key={project.id} type="button" onClick={() => onOpenAsset(project.playable[0]?.id || project.assets[0]?.id)}>
                <img src={project.cover || '/static/favicon.ico'} alt="Cover" />
                <span><strong>{project.title}</strong><small>{t('home.recent.variants', '{{count}} Varianten', { count: project.assets.length })} · {formatDuration(project.duration)} · {summarizeStyle(pickStyle(project.assets.find((asset) => pickStyle(asset))), 100, t)}</small></span>
              </button>
            ))}
          </div>}
        </div>

        <div className="panel stack">
          <div className="row between"><div><p className="eyebrow">{t('home.tasks.eyebrow', 'Aufträge')}</p><h2>{t('home.tasks.title', 'Offene Tasks')}</h2></div><button type="button" onClick={() => onNavigate('status')}>{t('nav.status', 'Status')}</button></div>
          {!openTasks.length ? <p className="muted">{t('home.tasks.empty', 'Keine laufenden Tasks.')}</p> : <div className="mini-list">
            {openTasks.map((task) => <div className="mini-list-row" key={task.id}><strong>{task.request_payload?.title || task.task_type}</strong><small>{task.status} · {formatDate(task.updated_at || task.created_at)}</small></div>)}
          </div>}
          <div className="row between"><div><p className="eyebrow">{t('home.notifications.eyebrow', 'Hinweise')}</p><h2>{t('home.notifications.title', 'Benachrichtigungen')}</h2></div></div>
          {!unread.length ? <p className="muted">{t('home.notifications.empty', 'Keine offenen Benachrichtigungen.')}</p> : <div className="mini-list">
            {unread.map((item) => <button className="mini-list-row" key={item.id} type="button" onClick={() => onNavigate('status')}><strong>{item.title}</strong><small>{item.message || t('home.notifications.openDetails', 'Öffnen für Details')}</small></button>)}
          </div>}
        </div>

        <div className="panel stack">
          <div className="row between"><div><p className="eyebrow">{t('home.workflow.eyebrow', 'Schnellstart')}</p><h2>{t('home.workflow.title', 'Produktionsablauf')}</h2></div></div>
          <ol className="workflow-steps-list">
            <li><strong>{t('home.workflow.idea.title', 'Idee oder Lyrics schreiben')}</strong><span>{t('home.workflow.idea.text', 'Canvas + KI-Assistent nutzen.')}</span></li>
            <li><strong>{t('home.workflow.style.title', 'Style auswählen')}</strong><span>{t('home.workflow.style.text', 'Preset, gespeicherter Style oder KI-Vorschlag.')}</span></li>
            <li><strong>{t('home.workflow.generate.title', 'Generieren')}</strong><span>{t('home.workflow.generate.text', 'Wizard starten und Task laufen lassen.')}</span></li>
            <li><strong>{t('home.workflow.variants.title', 'Varianten prüfen')}</strong><span>{t('home.workflow.variants.text', 'Favorit oder Final markieren.')}</span></li>
            <li><strong>{t('home.workflow.export.title', 'Exportieren')}</strong><span>{t('home.workflow.export.text', 'MP3, Songtext oder Projekt sichern.')}</span></li>
          </ol>
        </div>
      </section>
    </section>
  );
}
