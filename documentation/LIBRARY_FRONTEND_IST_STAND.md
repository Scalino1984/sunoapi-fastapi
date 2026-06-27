# Library Frontend Ist-Stand

Stand: 2026-06-24

Diese Datei beschreibt den aktuellen Sollzustand der React-Library. Sie dient als Referenz, damit kuenftige UI-Aenderungen nur an den wirklich betroffenen Stellen passieren.

## Grundlayout

Die Library-Seite rendert oben einen `SectionHeader` mit `eyebrow="Library"` und dem Titel `Meine Songs`. Wenn der Favoritenfilter aktiv ist, lautet der Titel `Favoriten`.

Im `SectionHeader` stehen aktuell keine Aktionsbuttons mehr.

Direkt darunter folgt genau ein gemeinsamer Optionscontainer:

- `library-controls-panel panel slim-panel`
- Datei: `frontend-react/src/pages/LibraryPage.jsx`
- Einstieg: `LibraryPage` Return-Block

Dieser Container ist bewusst etwas heller als die Library-Inhaltscontainer und ist als zentrale Steuerflaeche gedacht.

## Optionscontainer

Der Optionscontainer enthaelt eine `library-toolbar`.

In dieser Toolbar stehen zuerst zwei Dropdowns:

1. Sortierung
   - `Neueste zuerst`
   - `Aelteste zuerst`
   - `Zuletzt aktualisiert`
   - `Titel A-Z`
   - `Meiste Varianten`

2. Sicherung/Local-Status
   - `Sicherung: alle`
   - `Audio lokal`
   - `Cover lokal`
   - `Backup fehlt`
   - `Favoriten`

Danach folgt in derselben Toolbar die Chip-/Button-Zeile `filter-chips library-command-chips`.

Sichtbare Filterchips:

- `Alle`
- `Generiert`
- Dropdown `Weitere`

Im Dropdown `Weitere`:

- `Importiert`
- `Extended`
- `Cover`
- `Vocals`
- `Instrumental`
- `Mashup`
- `Sounds`

Weiterer Chip:

- `Favoriten`

Aktionsbuttons in derselben Zeile:

- `Audio importieren`
- `Inhalte pruefen`
- `Aktualisieren`

Wenn mindestens ein Library-Asset ausgewaehlt ist, erscheint direkt unter der Toolbar im selben Optionscontainer die Sammelaktionsleiste `selected-bulk-actions`.

Sie zeigt:

- Anzahl der ausgewaehlten Tracks
- `Loeschen`
- `In Playlist`
- `SRT erzeugen`
- `Stems erzeugen`
- `WAV erzeugen`
- `Auswahl ZIP`
- `Auswahl aufheben`

Diese Leiste ist nur sichtbar, solange `selectedAssets.length > 0` ist.

## Eingebettete Ansichts- und Pagination-Leiste

Unterhalb der Toolbar, aber weiterhin im selben Optionscontainer, wird `LibraryPaginationControls({ embedded: true })` gerendert.

Diese Leiste ist kein eigener aeusserer Panel-Container. Sie nutzt:

- `library-pagination-bar embedded-pagination`

Sie enthaelt:

- Umschalter `Listenansicht` / `Titelliste` / `Cover-Ansicht`
- Statistik-Pill fuer Songgruppen, Varianten und abspielbare Eintraege
- bei aktivem Favoritenfilter zusaetzlich Favoriten
- bei Titelliste den Modus `Einfach` / `Erweitert`
- bei Cover-Ansicht den Modus `Einfach` / `Erweitert`
- bei einfacher Cover-Ansicht die Grid-Auswahl `3`, `5`, `8`, `10`
- Anzahl-Auswahl `25`, `50`, `100`, `alle`
- Seitennavigation, sofern Anzahl nicht `alle` ist

Am unteren Ende der Library wird `LibraryPaginationControls()` weiterhin ohne `embedded` gerendert. Dieser untere Controls-Block bleibt ein eigenes Panel.

## Suche

Auf der Library-Seite gibt es keine eigene Suchleiste.

Die Suche kommt ausschliesslich aus der zentralen Header-Suche in `App.jsx` und wird als `searchQuery` an `LibraryPage` uebergeben.

Die Library filtert damit:

- Listenansicht
- Titelliste
- Cover-Ansicht
- Pagination

Der Suchtext wird in `filteredProjects` gegen Projekttitel und `assetSearchText(asset)` gematcht.

## Ansichten

Die Library hat drei Hauptansichten:

- `libraryViewMode === 'list'`: bestehende gruppierte Listenansicht nach Songgruppe/Projekt. Sie rendert `pagedProjects`.
- `libraryViewMode === 'flat-list'`: neue Titelliste. Sie rendert einzelne AudioAssets flach ueber `pagedGalleryAssets`.
- `libraryViewMode === 'gallery'`: Cover-Ansicht mit `libraryGalleryMode === 'simple'` oder `advanced`.

Die Titelliste verwendet dieselbe flache Datenquelle wie die einfache Cover-Ansicht:

- `filteredGalleryAssets`
- `pagedGalleryAssets`

Dadurch zeigen Titelliste und einfache Cover-Ansicht alle Titel/Varianten direkt an, ohne sie erst unter einer Songgruppe aufzuklappen.

Die Pagination zaehlt in flachen Asset-Ansichten nach Varianten:

- `flat-list`
- `gallery` + `simple`

In der gruppierten Listenansicht und in der erweiterten Cover-Ansicht zaehlt die Pagination nach `filteredProjects`.

Jede Zeile der Titelliste enthaelt:

- Auswahl-Checkbox fuer `selectedIds`
- Cover mit Play/Pause
- Titel und Projekt-/Variantenhinweis
- Favoritenbutton
- Drei-Punkt-Menue ueber `AudioActionMenu`

Die Titelliste hat eigene Untermodi:

- `libraryFlatListMode === 'simple'`: kompakte Zeilen mit Cover, Titel, Variante, Dauer, Audio-Status, Favorit und Drei-Punkt-Menue.
- `libraryFlatListMode === 'advanced'`: groessere Zeilen mit Projekt-/Operationstext, Dauer, Audio-Status, `audio_assets.id`, kurzer Audio-ID, lokalen Inhaltsbadges und Inline-Waveform fuer den aktuell laufenden Track.

Zusaetzlich hat die Titelliste eine Spaltengroessen-Steuerung mit `-` / `+`:

- State: `libraryFlatListScale`
- Persistenz: `react-library-flat-list-scale`
- Stufen: `0 = Kompakt`, `1 = Normal`, `2 = Breit`
- Die Steuerung veraendert Covergroesse und Titel-/Metaspalte der Titelliste. Auf Tablet/Mobile werden die Stufen auf sichere responsive Spalten geklemmt.

Play-Buttons und das Drei-Punkt-Menue in der Titelliste nutzen die flache Queue aus `visibleGalleryPlayableQueue()`, damit die Wiedergabe der angezeigten Reihenfolge folgt.

## SRT, Songabschnitte und Waveform

Die SRT-Erzeugung darf Lyrics weiterhin vor dem Alignment bereinigen. Dabei werden Struktur-, Prompt-, SFX- und Klammer-Tags aus dem sichtbaren SRT-Text entfernt.

Wichtig fuer Songabschnitte:

- `source_lyrics` bleibt als Originaltext erhalten.
- `lyrics` ist der bereinigte Text fuer SRT/Alignment.
- Nach erfolgreichem SRT-Alignment erzeugt `app/services/srt_transcript_service.py` aus `source_lyrics` und den fertigen SRT-Zeiten neue `structure_segments_json`.
- Die SRT-Segmente selbst werden dadurch nicht veraendert.
- Die Struktursegmente werden auf `AudioAsset.structure_segments_json` gespeichert.
- Falls vorhanden, wird auch `AudioAsset.waveform_json.segments` aktualisiert.
- Bei verknuepftem Song wird dieselbe Struktur auf `Song.structure_segments_json` und vorhandene `Song.waveform_json.segments` uebertragen.
- Abschnittsstarts bekommen bis zu 2 Sekunden Vorlauf vor der ersten zugeordneten SRT-Zeile, ohne die vorherige gesungene Zeile zu ueberlappen.
- Abschnittsenden werden bis zum Start des naechsten Abschnitts bzw. beim letzten Abschnitt bis zur Audiodauer gezogen, damit die Waveform-Anzeige nicht nachtraeglich skaliert.

Dadurch koennen `[Verse]`, `[Chorus]`, `[Bridge]` usw. im Originalsongtext bleiben, obwohl sie nicht in der SRT erscheinen. Die Waveform-/Player-Anzeige nutzt danach praezisere Abschnittszeiten aus dem SRT-Alignment statt nur grobe promptbasierte Dauerverteilung.

## Filterlogik

Die Operationstypen sind in `typeFilters` definiert.

Primaere, direkt sichtbare Filter:

- `all`
- `generate`

Sekundaere Filter im Dropdown `Weitere`:

- `manual`
- `extend`
- `cover`
- `vocals`
- `instrumental`
- `mashup`
- `sounds`

Der Local-/Sicherungsfilter ist getrennt davon und wird ueber `localFilter` gesteuert.

## Inhaltsbereich

Nach dem Optionscontainer folgen nur zustandsabhaengige Hinweise und Inhalte:

- Favoriten-Hinweis, wenn `localFilter === 'favorites'`
- Fehlerpanel, wenn `loadError`
- Empty State, wenn keine Treffer vorhanden sind
- danach entweder Gallery-Ansicht oder Listenansicht

## Detailseite, Mehrfachauswahl und Loeschen

Die Mehrfachauswahl ist in zwei Bereichen sichtbar:

- in der normalen Listenansicht direkt pro Varianten-Pill
- in der einfachen Cover-Ansicht direkt pro Cover-Kachel
- in der erweiterten Cover-Ansicht pro Projektkarte in `Creative Matches`
- in der Songdetail-/Projektansicht pro Variantenkarte

Zentraler State:

- `selectedIds`
- Typ: `Set`
- initial leer
- verwaltet ausgewaehlte `audio_assets.id`

Bereinigung des Auswahlzustands:

- Wenn Assets nach Reload/Filter nicht mehr sichtbar sind, werden nicht mehr erlaubte IDs aus `selectedIds` entfernt.
- Wenn geloeschte Assets lokal ausgeblendet werden, werden diese IDs ebenfalls aus `selectedIds` entfernt.

### Wo die Auswahl sichtbar ist

In der normalen Listenansicht wird pro Variante innerhalb von `project-audio-action-pill` eine Checkbox gerendert:

- Checkbox-Wrapper: `project-audio-select-mini`
- Checkbox-Zustand: `checked={selectedIds.has(asset.id)}`
- Umschalten: `toggleSelected(asset.id)`
- ausgewaehlte Pills erhalten `is-selected`

In der einfachen Cover-Ansicht wird pro Variante innerhalb von `gallery-single-cover-wrap` eine Checkbox gerendert:

- Checkbox-Wrapper: `gallery-select-checkbox`
- Checkbox-Zustand: `checked={selectedIds.has(asset.id)}`
- Umschalten: `toggleSelected(asset.id)`
- ausgewaehlte Kacheln erhalten `is-selected`

In der erweiterten Cover-Ansicht wird in `ProjectGalleryCard` eine Projekt-Checkbox gerendert:

- Checkbox-Wrapper: `gallery-select-checkbox project-select-checkbox`
- Checkbox-Zustand: `checked={isProjectSelectionComplete(project)}`
- Umschalten: `toggleProjectSelected(project)`
- ein Projekt gilt als ausgewaehlt, wenn alle `project.assets` in `selectedIds` enthalten sind
- ausgewaehlte Projektkarten erhalten `is-selected`

In der Detailansicht wird pro Variante eine Checkbox gerendert:

- Variante: `variant-card horizontal variant-accordion-card`
- Datenanker: `data-react-asset-row={asset.id}`
- Checkbox-Wrapper: `select-box`
- Checkbox-Zustand: `checked={selectedIds.has(asset.id)}`
- Umschalten: `toggleSelected(asset.id)`

`toggleSelected(assetId)` arbeitet rein lokal:

- vorhandene ID aus `selectedIds` entfernen
- fehlende ID zu `selectedIds` hinzufuegen

### Projektweite Auswahl-Aktionen

In der Aktionsleiste der Songdetailseite gibt es:

- `Alle auswaehlen`
- `Auswahl aufheben`
- `Auswahl loeschen`

`Alle auswaehlen` setzt:

- `selectedIds = new Set(activeProject.assets.map((asset) => asset.id))`

`Auswahl aufheben` setzt:

- `selectedIds = new Set()`

`Auswahl loeschen` ist deaktiviert, solange `selectedIds.size === 0`.

### Uebersichtsweite Auswahl-Aktionen

In der Library-Uebersicht zeigt der Optionscontainer die Leiste `selected-bulk-actions`, sobald Assets ausgewaehlt sind.

Die Aktionen nutzen die vorhandenen IDs aus `selectedAssets`:

- `Loeschen` ruft `deleteSelected()` auf.
- `In Playlist` oeffnet den Sammel-Playlist-Dialog und fuegt die ausgewaehlten Tracks per `api.library.addPlaylistItem(...)` hinzu.
- `SRT erzeugen` ruft `api.archive.bulkGenerateSrt(ids, { force: true })` auf.
- `Stems erzeugen` nutzt nur lokal gespeicherte Audios und ruft `api.archive.bulkGenerateStems(ids)` auf.
- `WAV erzeugen` nutzt konvertierbare Audios und ruft fuer jede ID `api.archive.convertToWav(id, { force: false })` auf.
- `Auswahl ZIP` verlinkt auf `api.archive.bulkAssetBundleUrl(ids)`.
- `Auswahl aufheben` setzt `selectedIds = new Set()`.

### Bulk-Loeschen

`Auswahl loeschen` ruft `deleteSelected(activeProject)` auf.

Ablauf:

1. Wenn keine Auswahl vorhanden ist, passiert nichts.
2. Die IDs werden aus `selectedIds` gelesen.
3. Es erscheint eine Browser-Confirm-Abfrage:
   - `{n} ausgewaehlte Audiodateien in den Papierkorb verschieben?`
4. Payload:
   - `items: ids.map((id) => ({ type: 'audio', id }))`
   - `delete_files: false`
5. Primaer wird `api.library.bulkDeleteContent(payload)` genutzt.
6. Fallback: einzelne `api.library.deleteContent('audio', id)` Calls.
7. Aus der API-Antwort werden `deletedIds` ermittelt.
8. Falls eines der geloeschten Assets gerade abgespielt wird, wird Playback gestoppt.
9. Geloeschte Assets werden lokal sofort ausgeblendet.
10. Toast:
    - `{n} ausgewaehlte Audio(s) wurden in den Papierkorb verschoben.`
11. `selectedIds` wird geleert.
12. `reloadAfterLibraryMutation()` laedt die Library mit `forceContentRefresh`.

Backend-Verhalten bei SunoAPI.org-Generierungen:

- Eine Suno-Generierung kann zwei AudioAssets mit derselben `suno_task_id` erzeugen.
- Die einzelnen Varianten werden ueber ihre `audio_id` unterschieden.
- Wird nur eine Variante geloescht, bleibt die zugehoerige `suno_tasks.task_id` aktiv, weil noch eine aktive Variante existiert.
- Wird die letzte aktive Variante zu dieser `suno_task_id` geloescht, werden verwaiste `Song`- und `SunoTask`-Zeilen ebenfalls soft-deleted.
- Danach darf dieselbe externe SunoAPI.org-Task-ID wieder importiert werden.
- Fuer Altfaelle, bei denen die AudioAssets bereits geloescht wurden, aber eine abgeschlossene `SunoTask` aktiv blieb, gibt die Import-Deduplizierung diese verwaiste Task-Zeile beim Re-Import frei.
- Laufende Tasks mit Status wie `RUNNING`, `PROCESSING`, `PENDING` oder `QUEUED` bleiben weiterhin gegen doppelte Imports geschuetzt.

API-Pfad:

- `POST /api/library/content/bulk-delete`

Client-Methode:

- `api.library.bulkDeleteContent(payload)`

Wichtig: Bulk-Loeschen verschiebt Library-Eintraege in den Papierkorb und setzt `delete_files: false`. Lokale Dateien werden dabei nicht direkt hart geloescht.

## Listenansicht

Die Listenansicht rendert Songgruppen als:

- `project-row suno-row`

Jede Songgruppe zeigt:

- Coverbutton mit Play/Pause
- Titelbutton mit Detailoeffnung
- Varianten-/Vorgangs-/Abspielbar-Zusammenfassung
- Style-Zusammenfassung
- optional Inline-Waveform fuer den aktuell spielenden/bereiten Track
- Mini-Aktionsstreifen fuer Varianten
- Statusbadges und Aktionen rechts

## Cover-Ansicht

Die Cover-Ansicht nutzt `LibraryGalleryView`.

Modus `Einfach`:

- kompakte Coveruebersicht ueber alle Varianten
- Klick auf Cover startet Wiedergabe
- Details oeffnen Songdetails

Modus `Erweitert`:

- `Creative Matches`
- Gruppierung nach Tag
- Gruppierung nach Jahr

## Cover Erstellen Und Ersetzen

In den Drei-Punkt-Menues der Library und der Songdetail-/Projektansicht gibt es Cover-Aktionen fuer einzelne AudioAssets:

- `Cover Song generieren`: startet eine SunoAPI.org Cover-Song-Folgeaktion.
- `Suno-Coverbild generieren`: startet die SunoAPI.org Coverbild-Erzeugung.
- `KI-Coverbild generieren`: startet die lokale Replicate-Cover-Erzeugung mit optionalem Referenzbild.
- `Upload-Cover ersetzen`: oeffnet das manuelle Upload-Modal zum Austauschen des bestehenden Coverbildes.

`Upload-Cover ersetzen` nutzt:

- Modal-Komponente: `CoverReplaceModal`
- Frontend-API: `api.library.updateCover('audio', asset.id, formData)`
- Upload-Feld im `FormData`: `cover`
- Backend-Pfad: `POST /api/library/content/audio/{audio_asset_id}/cover`

Das Backend speichert das Bild lokal unter `storage/covers`, setzt `audio_assets.image_url` auf `/media/covers/...` und aktualisiert bei verknuepften Inhalten auch Song-/Projekt-Cover.

## Relevante CSS-Klassen

Die zentrale Struktur liegt in `frontend-react/src/styles/app.css`.

Wichtige Klassen:

- `library-controls-panel`
- `library-toolbar`
- `library-command-chips`
- `chip-select`
- `library-chip-spacer`
- `library-pagination-bar`
- `embedded-pagination`

`library-controls-panel` ist heller als normale Inhaltscontainer:

- `background: color-mix(in srgb, var(--panel) 88%, white 12%)`
- `border-color: color-mix(in srgb, var(--line) 72%, white 28%)`

## Leitplanken fuer kuenftige Aenderungen

- Keine zweite Suchleiste in der Library einfuehren.
- Filter/Aktionen/Ansichtssteuerung oben als einen gemeinsamen Optionscontainer erhalten.
- `Importiert`, `Extended`, `Cover`, `Vocals`, `Instrumental`, `Mashup`, `Sounds` bleiben im Dropdown `Weitere`.
- `Alle`, `Generiert`, `Weitere`, `Favoriten` bleiben als direkte Steuerung sichtbar.
- Die untere Pagination darf als eigenes Panel bestehen bleiben.
- Inhaltskarten, Listenansicht und Gallery nicht anfassen, wenn nur der Optionsbereich geaendert werden soll.
- Mehrfachauswahl bleibt in Listenansicht, einfacher Cover-Ansicht, erweiterter Cover-Ansicht und Detailansicht sichtbar.
- Bulk-Loeschen muss weiter ueber Papierkorb/Bulk-Delete laufen und darf lokale Dateien nicht direkt entfernen, solange `delete_files: false` der definierte Ist-Stand ist.
