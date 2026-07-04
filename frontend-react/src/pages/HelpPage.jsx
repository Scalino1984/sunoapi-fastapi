import React, { useMemo, useState } from 'react';
import { useI18n } from '../i18n/I18nContext.jsx';

const shortcutGroups = [
  {
    title: 'Player',
    shortcuts: [
      ['Leertaste', 'Play/Pause, sofern kein Textfeld aktiv ist'],
      ['P', 'Play/Pause'],
      ['K', 'Play/Pause'],
      ['V', 'Aktuellen Song von vorne spielen'],
      ['W', 'Nächster Track'],
      ['N', 'Nächster Track'],
      ['Z', 'Vorheriger Track'],
      ['J / Pfeil links', '10 Sekunden zurück'],
      ['L / Pfeil rechts', '10 Sekunden vor'],
      ['Shift + Pfeil links/rechts', 'Vorheriger/nächster Track'],
      ['R', 'Loop ein/aus'],
      ['S', 'Wiedergabe stoppen, Player bleibt offen'],
      ['C', 'Audio-Player schließen und Wiedergabe stoppen'],
      ['B', 'Zuletzt gespielten Song erneut öffnen und wiedergeben'],
      ['D', 'Aktiven Track in der Library öffnen']
    ]
  },
  {
    title: 'Oberfläche',
    shortcuts: [
      ['ESC', 'Oberstes Modal, Menü oder Suche schließen, danach Songdetails Schritt für Schritt zurück'],
      ['X', 'Songdetails schließen und zurück zur Library, auch wenn der Audio-Player läuft'],
      ['M', 'Sidebar-Modus umschalten: offen → Symbole → weg'],
      ['H oder ?', 'Hilfe als Schnellübersicht öffnen']
    ]
  }
];

const quickStartSteps = [
  {
    title: '1. Song erstellen oder importieren',
    text: 'Nutze Musik für SunoAPI-Generierung, optionale OpenCLI-Generierung oder Suno-Importe. Bereits vorhandene Audios kannst du in der Library oder über die Statusseite importieren.',
    target: 'music',
    action: 'Musik öffnen'
  },
  {
    title: '2. Library prüfen und sichern',
    text: 'In der Library hörst du Varianten an, wechselst zwischen Listen- und Cover-Ansichten, prüfst lokale Audio-/Cover-Sicherung und öffnest Songdetails.',
    target: 'library',
    action: 'Library öffnen'
  },
  {
    title: '3. Folgeaktionen starten',
    text: 'Über die Drei-Punkt-Menüs startest du SRT, Stems, WAV, Extend, Cover, Audioanalyse, KI-Tags, Mini-DAW, Playlists oder Löschaktionen.',
    target: 'library',
    action: 'Aktionen nutzen'
  },
  {
    title: '4. Status und Exporte kontrollieren',
    text: 'Die Statusseite zeigt laufende Tasks und Detailprotokolle. Mini-DAW, Library-ZIP und einzelne Exportfunktionen übernehmen Pakete und Bearbeitung.',
    target: 'status',
    action: 'Status öffnen'
  }
];

const workflows = [
  {
    title: 'Songproduktion',
    items: [
      'Musik: SunoAPI ist der Standard, OpenCLI ist optional und nur aktiv, wenn es serverseitig verfügbar ist.',
      'Generate, Extend, Upload And Extend, Upload And Cover, Add Vocals, Add Instrumental, Cover-Bilder, Persona und weitere Operationen laufen über die jeweilige Auswahl.',
      'Erweiterte Felder wie Negative Tags, Vocal Gender, Style Weight, Weirdness, Audio Weight und Persona-Daten werden bei unterstützten SunoAPI-Operationen mitgeführt.',
      'Nach dem Start laufen Statusprüfung und Library-Aktualisierung im Hintergrund; Detailprotokolle findest du auf /status.'
    ]
  },
  {
    title: 'Library-Workflow',
    items: [
      'Die zentrale Header-Suche filtert Library, Playlists, Styles und Songtexte; eigene Suchleisten auf diesen Seiten sind bewusst entfernt.',
      'Library-Ansichten: gruppierte Listenansicht, Titelliste sowie Cover-Ansicht jeweils mit einfacher oder erweiterter Darstellung.',
      'Das Drei-Punkt-Menü pro Audio enthält SRT, Stems, Cover-Aktionen, Extend, Wiederverwenden, Audioanalyse, KI-Tags, Mini-DAW, Playlist und Papierkorb.',
      'Mehrfachauswahl zeigt passende Sammelaktionen oberhalb der Library, ohne die einzelnen Songdetails öffnen zu müssen.'
    ]
  },
  {
    title: 'SRT-Korrektur',
    items: [
      'Gespeicherte Lyrics in Songdetails bearbeiten, wenn gesungene Stellen, Wiederholungen oder bereinigte Klammerteile angepasst werden müssen.',
      'SRT-Erzeugung läuft als lokaler Status-Task; Groq/OpenAI/WhisperX-Details und Fehler stehen in den Statusdetails.',
      'Songsegmente und Untertitel werden in der Wiedergabe angezeigt; bei Bedarf SRT neu erzeugen oder im Editor nacharbeiten.',
      'Audio-Player und Library werden bei laufender Wiedergabe möglichst stabil gehalten, damit Scrollposition, Auswahl und Menüs nicht springen.'
    ]
  },
  {
    title: 'Optionale KI-Funktionen',
    items: [
      'Admin: Lokale Audioanalyse kann aktiviert werden; in der Library startet sie pro Audio über das Drei-Punkt-Menü und öffnet danach einen Report.',
      'Admin: KI-Library-Tags können aktiviert werden; sie erscheinen in Songdetails und verbessern die zentrale Header-Suche.',
      'Admin: Extend kann continueAt optional automatisch per Audioanalyse berechnen; ohne Aktivierung bleibt die manuelle Zeitangabe maßgeblich.',
      'Der globale KI-Assistent bleibt ein separates Hilfswerkzeug und nutzt die im Adminbereich konfigurierte KI.'
    ]
  }
];

const faqItems = [
  {
    question: 'Warum erscheinen alte Statusmeldungen nicht mehr als Toast-Flut?',
    answer: 'Beim App-Start werden vorhandene alte Meldungen nur als Verlauf geladen. Toasts erscheinen nur noch für neue Meldungen der aktuellen Session.'
  },
  {
    question: 'Warum aktualisiert sich die Library während Wiedergabe nicht sofort?',
    answer: 'Damit Menüs, Scrollpositionen und Buttons während aktiver Wiedergabe stabil bleiben. Manuelle Aktionen wie Löschen oder explizites Aktualisieren dürfen weiterhin gezielt neu laden.'
  },
  {
    question: 'Was mache ich, wenn SRT-Zeilen falsch sind?',
    answer: 'Zuerst gespeicherte Lyrics in den Songdetails prüfen. Fehlende Wiederholungen oder Klammertexte ergänzen, speichern und danach SRT neu erzeugen.'
  },
  {
    question: 'Wo finde ich KI-Library-Tags nach Aktivierung?',
    answer: 'In der Library in den Songdetails als Karte „KI-Library-Tags“, im Drei-Punkt-Menü einzelner Varianten und bei Mehrfachauswahl als Sammelaktion „KI-Tags“.'
  },
  {
    question: 'Wo finde ich die lokale Audioanalyse?',
    answer: 'Nach Aktivierung im Adminbereich in der Library über das Drei-Punkt-Menü eines lokalen Audios. Der Report kann danach direkt aus dem Menü oder aus den Songdetails geöffnet werden.'
  },
  {
    question: 'Wie komme ich direkt zu einer Seite?',
    answer: 'Die React-Tabs sind per URL erreichbar, zum Beispiel /library, /music, /status oder /help. Bei Songdetails steht der Titel hinter /library.'
  },
  {
    question: 'Welche Suche ist maßgeblich?',
    answer: 'Die zentrale Suche im Header ist die maßgebliche Suche für Inhalte und Bereiche. Library, Playlists, Styles und Songtexte übernehmen diese Suche direkt.'
  },
  {
    question: 'Was tun, wenn Mobile komisch aussieht?',
    answer: 'Nach einem neuen Build auf dem Handy den Browser-Cache leeren oder im privaten Tab testen. Alte CSS-Bundles bleiben auf Mobile-Browsern oft länger hängen.'
  }
];

const troubleshootingItems = [
  ['Status hängt', 'Öffne /status und prüfe den Task im Detailmodal. Dort stehen Request, Response, Progress und die letzten Schritte.'],
  ['Audio spielt nicht', 'Prüfe, ob das Audio noch vorhanden ist und nicht bereits in den Papierkorb verschoben wurde.'],
  ['Lokale Sicherung fehlt', 'Nutze in der Library „Inhalte prüfen“. Die Funktion lädt cachebare Audios/Cover nach und ergänzt fehlende SunoAPI-Metadaten, wenn sie abrufbar sind.'],
  ['Cover fehlt oder ist alt', 'Nutze Upload-Cover ersetzen, KI-Coverbild generieren oder Inhalte prüfen. Cover können zusätzlich groß angezeigt oder heruntergeladen werden.'],
  ['Buttons reagieren nicht', 'Bei aktiver Wiedergabe sollten globale Refreshes keine Inhaltsbereiche blockieren. Falls doch, zuerst prüfen, ob der aktuelle Build wirklich neu geladen wurde.']
];

const directLinks = [
  ['/', 'Home'],
  ['/music', 'Musik generieren'],
  ['/library', 'Library'],
  ['/lyrics', 'Songstudio'],
  ['/texts', 'Songtexte'],
  ['/playlists', 'Playlists'],
  ['/styles', 'Styles'],
  ['/daw', 'Mini-DAW'],
  ['/status', 'Status'],
  ['/admin', 'Admin'],
  ['/system', 'System'],
  ['/help', 'Hilfe']
];

const helpContentDe = {
  eyebrow: 'Hilfe & Arbeitsweise',
  title: 'Suno Song Studio verstehen',
  intro: 'Diese Seite bündelt Schnellstart, Workflows, Tastenkombinationen, FAQ und Fehlerhilfe direkt in der App. Sie ist bewusst einfach gehalten, damit du während der Produktion schnell nachschlagen kannst.',
  createSong: 'Song erstellen',
  openLibrary: 'Library öffnen',
  searchTitle: 'FAQ durchsuchen',
  searchText: 'Begriffe wie SRT, KI-Tags, Audioanalyse, Wiedergabe, Status oder Library eingeben.',
  searchPlaceholder: 'FAQ durchsuchen …',
  quickStartTitle: 'Schnellstart',
  shortcutsTitle: 'Tastenkombinationen',
  shortcutsNote: 'Shortcuts werden blockiert, sobald ein Eingabefeld, Textarea, Select, Modal, Canvas-Editor oder contenteditable-Feld aktiv ist.',
  workflowsTitle: 'Arbeitsabläufe',
  directLinksTitle: 'Direktlinks',
  faqTitle: 'FAQ',
  noFaqResults: 'Keine FAQ-Treffer gefunden.',
  troubleshootingTitle: 'Fehlerhilfe',
  shortcutGroups,
  quickStartSteps,
  workflows,
  faqItems,
  troubleshootingItems,
  directLinks
};

const helpContentEn = {
  eyebrow: 'Help & workflow',
  title: 'Understand Suno Song Studio',
  intro: 'This page collects quick start steps, workflows, keyboard shortcuts, FAQ and troubleshooting directly inside the app. It stays concise so you can check it while producing.',
  createSong: 'Create song',
  openLibrary: 'Open library',
  searchTitle: 'Search FAQ',
  searchText: 'Enter terms such as SRT, AI tags, audio analysis, playback, status or library.',
  searchPlaceholder: 'Search FAQ …',
  quickStartTitle: 'Quick start',
  shortcutsTitle: 'Keyboard shortcuts',
  shortcutsNote: 'Shortcuts are blocked while an input, textarea, select, modal, canvas editor or contenteditable field is active.',
  workflowsTitle: 'Workflows',
  directLinksTitle: 'Direct links',
  faqTitle: 'FAQ',
  noFaqResults: 'No FAQ matches found.',
  troubleshootingTitle: 'Troubleshooting',
  shortcutGroups: [
    {
      title: 'Player',
      shortcuts: [
        ['Space', 'Play/pause if no text field is active'],
        ['P', 'Play/pause'],
        ['K', 'Play/pause'],
        ['V', 'Replay current song from start'],
        ['W', 'Next track'],
        ['N', 'Next track'],
        ['Z', 'Previous track'],
        ['J / Arrow left', 'Back 10 seconds'],
        ['L / Arrow right', 'Forward 10 seconds'],
        ['Shift + Arrow left/right', 'Previous/next track'],
        ['R', 'Toggle loop'],
        ['S', 'Stop playback, keep player open'],
        ['C', 'Close audio player and stop playback'],
        ['B', 'Reopen and play the last played song'],
        ['D', 'Open active track in the library']
      ]
    },
    {
      title: 'Interface',
      shortcuts: [
        ['ESC', 'Close the topmost modal, menu or search, then step back through song details'],
        ['X', 'Close song details and return to the library, even while the audio player is running'],
        ['M', 'Toggle sidebar mode: open → icons → hidden'],
        ['H or ?', 'Open help as a quick overview']
      ]
    }
  ],
  quickStartSteps: [
    {
      title: '1. Create or import a song',
      text: 'Use Music for SunoAPI generation, optional OpenCLI generation or Suno imports. Existing audio can be imported through the library or status page.',
      target: 'music',
      action: 'Open music'
    },
    {
      title: '2. Check and secure the library',
      text: 'In the library you can listen to variants, switch between list and cover views, verify local audio/cover storage and open song details.',
      target: 'library',
      action: 'Open library'
    },
    {
      title: '3. Start follow-up actions',
      text: 'Use the three-dot menus for SRT, stems, WAV, extend, cover, audio analysis, AI tags, Mini DAW, playlists or delete actions.',
      target: 'library',
      action: 'Use actions'
    },
    {
      title: '4. Check status and exports',
      text: 'The status page shows running tasks and detailed logs. Mini DAW, library ZIP and dedicated export actions handle packages and edits.',
      target: 'status',
      action: 'Open status'
    }
  ],
  workflows: [
    {
      title: 'Song production',
      items: [
        'Music: SunoAPI is the default provider; OpenCLI is optional and only active when available on the server.',
        'Generate, Extend, Upload And Extend, Upload And Cover, Add Vocals, Add Instrumental, cover images, Persona and other operations run through the selected workflow.',
        'Advanced fields such as negative tags, vocal gender, style weight, weirdness, audio weight and persona data are carried through supported SunoAPI operations.',
        'After starting a task, status checks and library refreshes run in the background; detailed logs are available on /status.'
      ]
    },
    {
      title: 'Library workflow',
      items: [
        'The central header search filters library, playlists, styles and lyrics; separate search bars on those pages are intentionally removed.',
        'Library views: grouped list, title list and cover view, each with compact or expanded display where available.',
        'Each audio three-dot menu contains SRT, stems, cover actions, extend, reuse, audio analysis, AI tags, Mini DAW, playlist and trash actions.',
        'Multi-select shows matching bulk actions above the library without opening each song detail page.'
      ]
    },
    {
      title: 'SRT correction',
      items: [
        'Edit saved lyrics in song details when sung lines, repetitions or cleaned bracket parts need correction.',
        'SRT generation runs as a local status task; Groq/OpenAI/WhisperX details and errors are visible in status details.',
        'Song segments and subtitles are shown during playback; regenerate SRT or edit it in the editor when needed.',
        'Audio player and library are kept as stable as possible during playback so scroll position, selection and menus do not jump.'
      ]
    },
    {
      title: 'Optional AI features',
      items: [
        'Admin: Local audio analysis can be enabled; in the library it starts per audio through the three-dot menu and opens a report afterwards.',
        'Admin: AI library tags can be enabled; they appear in song details and improve the central header search.',
        'Admin: Extend can optionally calculate continueAt automatically through audio analysis; without activation, the manual time remains authoritative.',
        'The global AI assistant remains a separate helper and uses the AI provider configured in admin.'
      ]
    }
  ],
  faqItems: [
    {
      question: 'Why do old status messages no longer flood the screen as toasts?',
      answer: 'On app start, old messages are loaded as history only. Toasts appear only for new messages from the current session.'
    },
    {
      question: 'Why does the library not refresh immediately during playback?',
      answer: 'This keeps menus, scroll positions and buttons stable during active playback. Manual actions such as delete or explicit refresh can still reload intentionally.'
    },
    {
      question: 'What should I do when SRT lines are wrong?',
      answer: 'First check saved lyrics in song details. Add missing repetitions or bracket text, save, then regenerate SRT.'
    },
    {
      question: 'Where do I find AI library tags after enabling them?',
      answer: 'In library song details as the "AI library tags" card, in the three-dot menu of individual variants and as a bulk action for selected tracks.'
    },
    {
      question: 'Where do I find local audio analysis?',
      answer: 'After enabling it in admin, open it from the library through the three-dot menu of a local audio. The report can then be opened from the menu or song details.'
    },
    {
      question: 'How do I open a page directly?',
      answer: 'React tabs are reachable by URL, for example /library, /music, /status or /help. Song details place the title after /library.'
    },
    {
      question: 'Which search is authoritative?',
      answer: 'The central header search is the authoritative search for content and sections. Library, playlists, styles and lyrics consume that search directly.'
    },
    {
      question: 'What should I do if mobile layout looks odd?',
      answer: 'After a new build, clear the browser cache on the phone or test in a private tab. Mobile browsers often keep old CSS bundles longer.'
    }
  ],
  troubleshootingItems: [
    ['Status is stuck', 'Open /status and inspect the task detail modal. It contains request, response, progress and the latest steps.'],
    ['Audio does not play', 'Check whether the audio still exists and was not already moved to trash.'],
    ['Local storage is missing', 'Use "Check content" in the library. It downloads cacheable audio/covers and backfills missing SunoAPI metadata when available.'],
    ['Cover is missing or old', 'Use replace upload cover, generate AI cover image or check content. Covers can also be opened large or downloaded.'],
    ['Buttons do not react', 'During active playback, global refreshes should not block content areas. If they still do, first verify that the current build was really reloaded.']
  ],
  directLinks: [
    ['/', 'Home'],
    ['/music', 'Generate music'],
    ['/library', 'Library'],
    ['/lyrics', 'Song studio'],
    ['/texts', 'Lyrics'],
    ['/playlists', 'Playlists'],
    ['/styles', 'Styles'],
    ['/daw', 'Mini DAW'],
    ['/status', 'Status'],
    ['/admin', 'Admin'],
    ['/system', 'System'],
    ['/help', 'Help']
  ]
};

function HelpCard({ title, children, className = '' }) {
  return (
    <section className={`help-card ${className}`.trim()}>
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function CopyButton({ value, notify }) {
  const { t } = useI18n();
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      notify?.(t('common.copied', 'In Zwischenablage kopiert.'), 'success');
    } catch {
      notify?.(t('common.copyFailed', 'Kopieren nicht möglich.'), 'error');
    }
  }

  return <button type="button" className="btn-secondary help-copy-button" onClick={copy}>{t('common.copy', 'Kopieren')}</button>;
}

export function HelpPage({ onNavigate, notify }) {
  const { language } = useI18n();
  const content = language === 'en' ? helpContentEn : helpContentDe;
  const [query, setQuery] = useState('');
  const normalizedQuery = query.trim().toLowerCase();

  const filteredFaq = useMemo(() => {
    if (!normalizedQuery) return content.faqItems;
    return content.faqItems.filter((item) => `${item.question} ${item.answer}`.toLowerCase().includes(normalizedQuery));
  }, [content.faqItems, normalizedQuery]);

  return (
    <div className="page-stack help-page">
      <section className="hero-panel help-hero">
        <div>
          <span className="eyebrow">{content.eyebrow}</span>
          <h1>{content.title}</h1>
          <p>{content.intro}</p>
        </div>
        <div className="help-hero-actions">
          <button type="button" onClick={() => onNavigate?.('music', { wizard: true })}>{content.createSong}</button>
          <button type="button" className="btn-secondary" onClick={() => onNavigate?.('library')}>{content.openLibrary}</button>
        </div>
      </section>

      <section className="help-search-card">
        <div>
          <strong>{content.searchTitle}</strong>
          <span>{content.searchText}</span>
        </div>
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={content.searchPlaceholder} />
      </section>

      <HelpCard title={content.quickStartTitle}>
        <div className="help-step-grid">
          {content.quickStartSteps.map((step) => (
            <article className="help-step" key={step.title}>
              <h3>{step.title}</h3>
              <p>{step.text}</p>
              <button type="button" className="btn-secondary" onClick={() => onNavigate?.(step.target)}>{step.action}</button>
            </article>
          ))}
        </div>
      </HelpCard>

      <HelpCard title={content.shortcutsTitle}>
        <div className="help-shortcut-grid">
          {content.shortcutGroups.map((group) => (
            <article className="help-shortcut-group" key={group.title}>
              <h3>{group.title}</h3>
              <div className="help-shortcut-list">
                {group.shortcuts.map(([shortcut, description]) => (
                  <div className="help-shortcut-row" key={`${group.title}-${shortcut}`}>
                    <kbd>{shortcut}</kbd>
                    <span>{description}</span>
                  </div>
                ))}
              </div>
            </article>
          ))}
        </div>
        <p className="muted help-note">{content.shortcutsNote}</p>
      </HelpCard>

      <HelpCard title={content.workflowsTitle}>
        <div className="help-workflow-grid">
          {content.workflows.map((workflow) => (
            <article className="help-workflow" key={workflow.title}>
              <h3>{workflow.title}</h3>
              <ol>
                {workflow.items.map((item) => <li key={item}>{item}</li>)}
              </ol>
            </article>
          ))}
        </div>
      </HelpCard>

      <HelpCard title={content.directLinksTitle}>
        <div className="help-link-grid">
          {content.directLinks.map(([path, label]) => (
            <div className="help-link-row" key={path}>
              <div>
                <strong>{label}</strong>
                <code>{path}</code>
              </div>
              <CopyButton value={path} notify={notify} />
            </div>
          ))}
        </div>
      </HelpCard>

      <HelpCard title={content.faqTitle}>
        <div className="help-faq-list">
          {filteredFaq.map((item) => (
            <details key={item.question} className="help-faq-item">
              <summary>{item.question}</summary>
              <p>{item.answer}</p>
            </details>
          ))}
          {!filteredFaq.length && <p className="muted">{content.noFaqResults}</p>}
        </div>
      </HelpCard>

      <HelpCard title={content.troubleshootingTitle}>
        <div className="help-troubleshooting-grid">
          {content.troubleshootingItems.map(([title, text]) => (
            <article className="help-troubleshooting-item" key={title}>
              <strong>{title}</strong>
              <p>{text}</p>
            </article>
          ))}
        </div>
      </HelpCard>
    </div>
  );
}
