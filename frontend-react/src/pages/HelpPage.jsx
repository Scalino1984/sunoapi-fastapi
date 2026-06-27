import React, { useMemo, useState } from 'react';

const shortcutGroups = [
  {
    title: 'Player',
    shortcuts: [
      ['Leertaste', 'Play/Pause, sofern kein Textfeld aktiv ist'],
      ['P', 'Play/Pause'],
      ['K', 'Play/Pause'],
      ['W', 'Nächster Track'],
      ['N', 'Nächster Track'],
      ['Z', 'Vorheriger Track'],
      ['J / Pfeil links', '5 Sekunden zurück'],
      ['L / Pfeil rechts', '5 Sekunden vor'],
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
      ['H oder ?', 'Diese Hilfe öffnen']
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
    text: 'Die Statusseite zeigt laufende Tasks, Import-Backfills und Detailprotokolle. Workflow und Mini-DAW bereiten Exporte, Pakete und Bearbeitung vor.',
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

function HelpCard({ title, children, className = '' }) {
  return (
    <section className={`help-card ${className}`.trim()}>
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function CopyButton({ value, notify }) {
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      notify?.('In Zwischenablage kopiert.', 'success');
    } catch {
      notify?.('Kopieren nicht möglich.', 'error');
    }
  }

  return <button type="button" className="btn-secondary help-copy-button" onClick={copy}>Kopieren</button>;
}

export function HelpPage({ onNavigate, notify }) {
  const [query, setQuery] = useState('');
  const normalizedQuery = query.trim().toLowerCase();

  const filteredFaq = useMemo(() => {
    if (!normalizedQuery) return faqItems;
    return faqItems.filter((item) => `${item.question} ${item.answer}`.toLowerCase().includes(normalizedQuery));
  }, [normalizedQuery]);

  return (
    <div className="page-stack help-page">
      <section className="hero-panel help-hero">
        <div>
          <span className="eyebrow">Hilfe & Arbeitsweise</span>
          <h1>Suno Song Studio verstehen</h1>
          <p>
            Diese Seite bündelt Schnellstart, Workflows, Tastenkombinationen, FAQ und Fehlerhilfe direkt in der App.
            Sie ist bewusst einfach gehalten, damit du während der Produktion schnell nachschlagen kannst.
          </p>
        </div>
        <div className="help-hero-actions">
          <button type="button" onClick={() => onNavigate?.('music', { wizard: true })}>Song erstellen</button>
          <button type="button" className="btn-secondary" onClick={() => onNavigate?.('library')}>Library öffnen</button>
        </div>
      </section>

      <section className="help-search-card">
        <div>
          <strong>FAQ durchsuchen</strong>
          <span>Begriffe wie SRT, KI-Tags, Audioanalyse, Wiedergabe, Status oder Library eingeben.</span>
        </div>
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="FAQ durchsuchen …" />
      </section>

      <HelpCard title="Schnellstart">
        <div className="help-step-grid">
          {quickStartSteps.map((step) => (
            <article className="help-step" key={step.title}>
              <h3>{step.title}</h3>
              <p>{step.text}</p>
              <button type="button" className="btn-secondary" onClick={() => onNavigate?.(step.target)}>{step.action}</button>
            </article>
          ))}
        </div>
      </HelpCard>

      <HelpCard title="Tastenkombinationen">
        <div className="help-shortcut-grid">
          {shortcutGroups.map((group) => (
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
        <p className="muted help-note">Shortcuts werden blockiert, sobald ein Eingabefeld, Textarea, Select, Modal, Canvas-Editor oder contenteditable-Feld aktiv ist.</p>
      </HelpCard>

      <HelpCard title="Arbeitsabläufe">
        <div className="help-workflow-grid">
          {workflows.map((workflow) => (
            <article className="help-workflow" key={workflow.title}>
              <h3>{workflow.title}</h3>
              <ol>
                {workflow.items.map((item) => <li key={item}>{item}</li>)}
              </ol>
            </article>
          ))}
        </div>
      </HelpCard>

      <HelpCard title="Direktlinks">
        <div className="help-link-grid">
          {[
            ['/', 'Home'],
            ['/music', 'Musik generieren'],
            ['/library', 'Library'],
            ['/lyrics', 'Songstudio'],
            ['/production', 'Workflow'],
            ['/texts', 'Songtexte'],
            ['/playlists', 'Playlists'],
            ['/styles', 'Styles'],
            ['/daw', 'Mini-DAW'],
            ['/status', 'Status'],
            ['/admin', 'Admin'],
            ['/system', 'System'],
            ['/help', 'Hilfe']
          ].map(([path, label]) => (
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

      <HelpCard title="FAQ">
        <div className="help-faq-list">
          {filteredFaq.map((item) => (
            <details key={item.question} className="help-faq-item">
              <summary>{item.question}</summary>
              <p>{item.answer}</p>
            </details>
          ))}
          {!filteredFaq.length && <p className="muted">Keine FAQ-Treffer gefunden.</p>}
        </div>
      </HelpCard>

      <HelpCard title="Fehlerhilfe">
        <div className="help-troubleshooting-grid">
          {troubleshootingItems.map(([title, text]) => (
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
