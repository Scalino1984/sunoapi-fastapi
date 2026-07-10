# DAW-KI: technische Funktionsbeschreibung und Prompt-Aufhaenger

Dieses Dokument beschreibt die aktuelle DAW-KI der React-Seite `/daw` und
skizziert eine robuste Erweiterung fuer wiederkehrende Prompt-Aufhaenger, die
nicht hardcoded im Parser liegen sollen.

## Zielbild

Die DAW-KI arbeitet DAW-zentriert und nicht generator-zentriert:

- KI-Befehle veraendern zuerst das lokale Arrangement in der Timeline.
- Jede Aenderung bleibt nicht-destruktiv, undo-faehig und per Auto-Save im
  `daw_arrangement` des AudioAssets persistiert.
- Playback nutzt die Web-Audio-Engine und ist nach Timeline-Aenderungen sofort
  hoerbar.
- Externe Musikgenerierung, z. B. Suno Extend, wird nicht automatisch aus der
  DAW-KI gestartet. Die vorhandenen Extend-Funktionen in Library/Music bleiben
  getrennte Workflows.
- Eine finale Audio-Version entsteht erst ueber Export oder "Als Version
  speichern".

## Frontend-Architektur

Die DAW-Seite ist in modulare Bausteine unter `frontend-react/src/daw/`
aufgeteilt.

Wichtige Dateien:

- `pages/DawPage.jsx`: Orchestriert Laden, Playback, KI-Eingaben, Auto-Save,
  Export und Render-Task-Polling.
- `daw/aiParser.js`: Lokaler deterministischer Parser fuer haeufige deutsche
  DAW-Befehle. Er erzeugt strukturierte Command-Objekte.
- `daw/arrangement.js`: Pure Arrangement-Engine. `createDawCommandPlan()`
  erzeugt aus Commands konkrete Timeline-Mutationen.
- `daw/store.js`: Zustand-Store mit Arrangement, Undo/Redo, Auswahl, Transport
  und Command-Anwendung.
- `daw/audioEngine.js`: Web-Audio-Playback fuer Multi-Clip-Arrangements.
- `daw/musicalTime.js`: Beatgrid-, Downbeat- und Taktlogik.
- `daw/sections.js`: Songstruktur-Aufloesung aus SRT/Lyrics/Struktursegmenten,
  Markern und Beatgrid-Information.

## Datenmodell

Das Arrangement bleibt im bestehenden AudioAsset:

```text
audio_assets.metadata_json.daw_arrangement
```

Der relevante Shape:

```json
{
  "version": 1,
  "source_audio_id": 123,
  "duration_seconds": 180.2,
  "bpm": 92,
  "time_signature": "4/4",
  "snap_enabled": true,
  "snap_unit": "bar",
  "tracks": [
    { "id": "track-1", "name": "Spur 1", "muted": false, "solo": false, "volume_db": 0 }
  ],
  "clips": [
    {
      "id": "clip-...",
      "track_id": "track-1",
      "source_audio_id": 123,
      "timeline_start": 44.0,
      "source_start": 44.0,
      "source_end": 52.0,
      "gain_db": 0,
      "fade_in": 0,
      "fade_out": 0,
      "label": "Hook Kopie",
      "muted": false,
      "locked": false,
      "color": "cyan"
    }
  ],
  "markers": []
}
```

Ein Clip ist eine nicht-destruktive Referenz auf eine Quelle:

- `timeline_start`: Position in der DAW-Timeline.
- `source_audio_id`: AudioAsset, aus dem gelesen wird.
- `source_start` / `source_end`: Ausschnitt in der Quelle.
- Fades, Gain, Mute, Lock und Track bleiben Clip-Eigenschaften.

## Ablauf eines DAW-KI-Befehls

1. Der Nutzer schreibt einen Befehl im globalen DAW-KI-Panel oder im Clip-KI-
   Popover.
2. `runDawAiCommand()` in `DawPage.jsx` sammelt Kontext:
   - Arrangement
   - erkannte Songabschnitte
   - ausgewahlter Clip
   - ausgewahlter Abschnitt
   - Auswahlbereich
   - Playhead
   - Close-Gap-Option
3. `parseDawAiCommand()` versucht den Befehl lokal zu strukturieren.
4. Fuer bekannte lokale Befehle entsteht ein Command wie:
   - `clip_split`
   - `clip_duplicate`
   - `clip_trim`
   - `clip_fade`
   - `section_duplicate`
   - `section_append_to_end`
   - `range_delete`
   - `gap_close`
   - `duplicate_musical_range`
5. `createDawCommandPlan()` berechnet daraus:
   - `originalArrangement`
   - `nextArrangement`
   - Actions/Warnungen
   - neue Auswahl
   - `guideTime` fuer Playhead/Snap-Hinweis
6. `applyCommandPlan()` schreibt das neue Arrangement in den Store, legt Undo-
   History an und setzt `dirty=true`.
7. `DawPage` springt bei KI-Aktionen an `guideTime`, damit die Aenderung sofort
   kontrolliert werden kann.
8. Die Web-Audio-Engine refreshed bei laufendem Playback das geaenderte
   Arrangement. Bei gestopptem Playback wird beim naechsten Play das aktuelle
   Arrangement gespielt.
9. Auto-Save persistiert die Timeline-Aenderung nach kurzer Ruhezeit.

## Lokaler Parser

Der lokale Parser ist bewusst deterministisch. Er ist fuer schnelle, haeufige
Editor-Aktionen zustaendig und darf keine externen Audio-Generierungsflows
starten.

Beispiele:

```text
Fade-out 2 Sekunden
Schneide am Playhead
Dupliziere diesen Clip
Loesche die zweite Hook
Setze die erste Hook doppelt
Kopiere die ersten 4 Takte der Hook direkt danach
Schliesse alle Luecken
```

Der Parser ist kein vollstaendiges Sprachmodell. Er klassifiziert Absichten in
einen begrenzten Operationsvertrag. Wenn er keinen sicheren lokalen Befehl
erkennt, kann der Server-KI-Planer verwendet werden.

## Server-KI-Planer

`POST /api/daw/assets/{asset_id}/arrangement/ai-command` nutzt
`DawAiCommandService`. Er baut serverseitig einen kompakten Kontext aus:

- Arrangement
- Clips/Tracks/Marker
- Songstruktur
- Beatgrid/Bar-Map
- Playhead/Auswahl
- erlaubter Operations-Whitelist

Die KI darf nicht beliebig JSON veraendern. Sie liefert nur geplante Operationen
aus einer Whitelist. Der deterministische Executor wendet diese Operationen
serverseitig an.

Der Frontend-Flow kann diesen Plan direkt anwenden. Er bleibt trotzdem eine
Timeline-Operation und kein finaler Render.

## Praezise musikalische Bereiche

Fuer taktgenaue Bereichsedits gibt es `duplicate_musical_range`.

Der Command deckt eine Klasse von Anweisungen ab, nicht nur einen einzelnen
Beispielsatz:

```json
{
  "type": "duplicate_musical_range",
  "sectionId": "hook-1",
  "bars": 4,
  "anchor": "first_full_bar",
  "insert": "after_range",
  "ripple": true,
  "excludeTransitionPickup": true
}
```

Der Executor:

1. loest den Abschnitt auf, z. B. erste Hook;
2. bestimmt den ersten vollstaendigen Takt per Beatgrid/Downbeats;
3. setzt `rangeEnd = rangeStart + bars`;
4. extrahiert alle Clip-Teile, die den Bereich ueberlappen;
5. fuegt die Kopie direkt nach dem Bereich ein;
6. schiebt nachfolgenden Songverlauf bei `ripple=true` nach rechts;
7. setzt Auswahl und Playhead auf die eingefuegte Kopie.

Dadurch wird z. B. "erste 4 vollstaendige Takte der Hook kopieren" als lokaler
DAW-Edit umgesetzt, ohne Uebergangsauftakt oder nachfolgenden Verse
mitzukopieren.

## Playback-Verhalten

Die Web-Audio-Engine spielt das aktuelle Arrangement direkt:

- Buffers werden pro `source_audio_id` geladen und gecacht.
- Jeder Clip wird beim Playback als eigener `AudioBufferSourceNode` gescheduled.
- Clip-Gain, Fade-in, Fade-out, Track-Volume, Mute und Solo werden im Browser
  angewendet.
- Wenn sich das Arrangement waehrend laufendem Playback aendert, ruft die Seite
  `engine.refresh(arrangement)` auf und scheduled ab der aktuellen Position neu.
- Nach KI-Edits springt der Playhead zur relevanten Stelle, damit der Nutzer
  sofort hoeren kann, ob der Edit stimmt.

## Persistenz und finale Versionen

Timeline-Aenderungen sind Session-/Arrangement-Aenderungen. Sie erzeugen nicht
automatisch ein neues AudioAsset.

- Auto-Save: schreibt `daw_arrangement`.
- Export: rendert eine Datei als Download.
- Als Version speichern: startet einen lokalen Render-Task und erzeugt ein neues
  AudioAsset mit dem aktuellen Arrangement.

## Abgrenzung zu Extend

Extend bleibt ein separater Workflow in Music/Library:

- MusicPage und LibraryPage duerfen `api.archive.extend(...)` nutzen.
- Die DAW-KI ruft diesen Endpoint nicht automatisch auf.
- Wenn spaeter eine bewusste "extern generieren und als Clip einsetzen"-
  Funktion gewuenscht ist, sollte sie als eigener expliziter DAW-Befehl mit
  sichtbarem Status, Platzhalter-Clip und Abbruchmoeglichkeit implementiert
  werden, nicht als implizite Interpretation eines Timeline-Edits.

## Wiederkehrende Prompt-Aufhaenger

Wiederkehrende komplexe Anweisungen sollten nicht hardcoded im Parser landen.
Stattdessen sollte die DAW-KI eine kleine Prompt-Bibliothek fuer
Geschaefts-/Workflow-Aufhaenger bekommen.

### Ziel

Der Nutzer kann Aufhaenger speichern:

```json
{
  "id": "hook-4-bars-repeat",
  "title": "Hook: erste 4 Takte doppeln",
  "prompt": "Verdopple die erste Hook. Nutze nur die ersten 4 vollstaendigen Takte ...",
  "scope": "daw",
  "tags": ["hook", "takt", "repeat"],
  "created_at": "..."
}
```

Im DAW-KI-Eingabefeld:

- `/prompts` zeigt gespeicherte Aufhaenger im Antwortfenster.
- Die Antwort listet die Titel klickbar auf.
- Klick auf einen Titel kopiert den gespeicherten Prompt ins Nachrichtenfeld.
- Danach kann der Nutzer ihn bearbeiten und abschicken.

### Warum das besser ist als Hardcoding

Hardcoding ist fuer generische Operationslogik sinnvoll, aber nicht fuer
persoenliche Formulierungen, Stilregeln oder Arbeitsweisen.

Hardcoded bleiben sollte:

- Operationsvertrag
- Parser fuer allgemeine Befehle
- Executor fuer sichere Timeline-Mutationen
- Validierung, Beatgrid- und Ripple-Logik

Speicherbar sein sollte:

- lange Beispielprompts
- eigene Formulierungen
- wiederkehrende Edit-Workflows
- projektspezifische Erinnerungen
- Qualitaetsregeln wie "keinen Uebergangsauftakt mitkopieren"

### UI-Konzept

Im DAW-KI-Panel:

1. Nutzer tippt `/prompts`.
2. `runDawAiCommand()` erkennt Slash-Befehl und fuehrt keinen DAW-Edit aus.
3. Das Assistant-Antwortfenster zeigt:

```text
Gespeicherte DAW-Aufhaenger:
- Hook: erste 4 Takte doppeln
- Hook ans Ende als Outro
- Verse-Start auf Downbeat schneiden
```

4. Jeder Eintrag ist ein Button.
5. Klick setzt `aiCommandText` auf den gespeicherten Prompt.
6. Optional kann der Nutzer den Prompt direkt ausfuehren oder erst editieren.

### Datenhaltung

Minimal lokal:

```text
localStorage["daw_prompt_hooks"]
```

Vorteile:

- keine Migration
- sofort nutzbar
- nutzerspezifisch im Browser

Empfohlene spaetere Server-Variante:

```text
Table: daw_prompt_hooks
```

Felder:

- `id`
- `user_id`
- `scope`
- `title`
- `prompt`
- `tags_json`
- `is_deleted`
- `created_at`
- `updated_at`

API:

```text
GET    /api/daw/prompt-hooks
POST   /api/daw/prompt-hooks
PUT    /api/daw/prompt-hooks/{id}
DELETE /api/daw/prompt-hooks/{id}
```

### Frontend-Implementierung

Neue Helferdatei:

```text
frontend-react/src/daw/promptHooks.js
```

Aufgaben:

- `loadDawPromptHooks()`
- `saveDawPromptHook({ title, prompt, tags })`
- `deleteDawPromptHook(id)`
- `normalizeDawPromptHook(value)`

Erweiterung in `DawPage.jsx`:

- State `promptHooks`
- Slash-Command-Erkennung vor `parseDawAiCommand()`
- Spezialfall `/prompts`
- Klickhandler `insertPromptHook(hook)`

Erweiterung in `DawPanels.jsx`:

- AI-History-Eintraege koennen `meta.promptHooks` enthalten.
- Wenn vorhanden, werden Buttons statt nur Text gerendert.
- Button ruft `onInsertPromptHook(hook)` auf.

Beispiel-History-Eintrag:

```js
appendAiHistory('assistant', 'Gespeicherte DAW-Aufhaenger:', {
  promptHooks: hooks.map(({ id, title, prompt }) => ({ id, title, prompt }))
});
```

### Speichern eines Aufhaengers

Moegliche Bedienung:

- Button im DAW-KI-Panel: "Aufhaenger speichern"
- speichert aktuellen Text aus dem Eingabefeld
- fragt Titel per kleinem Inline-Input oder Dialog ab

Alternative Slash-Kommandos:

```text
/saveprompt Hook: erste 4 Takte doppeln
```

Speichert den aktuellen Eingabetext oder den zuletzt ausgefuehrten Befehl unter
dem Titel nach `/saveprompt`.

### Sicherheitsregeln

Gespeicherte Aufhaenger sind keine ausfuehrbaren Makros. Sie sind nur Text, der
ins Eingabefeld eingefuegt wird.

Vorteile:

- Der Nutzer sieht und kann den Prompt vor dem Absenden bearbeiten.
- Kein verstecktes Ausfuehren alter Befehle.
- Keine Sonderrechte fuer gespeicherte Inhalte.
- Parser/Executor bleiben die einzige Stelle, die echte Timeline-Aenderungen
  erzeugt.

### Empfohlene erste Ausbaustufe

1. `localStorage`-basierte Prompt-Hooks.
2. `/prompts` zeigt klickbare Titel.
3. "Aufhaenger speichern"-Button fuer aktuellen Eingabetext.
4. Keine Server-Migration.

Danach:

1. Backend-Tabelle fuer nutzeruebergreifende Persistenz.
2. Import/Export von Prompt-Hooks.
3. Tags/Suche.
4. Optional Projektscope: globale Hooks vs. Hooks pro AudioAsset/Projekt.

