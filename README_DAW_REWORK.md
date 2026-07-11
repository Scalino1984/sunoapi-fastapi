# DAW-Rework – KlangNeural Studio `/daw`

Vollständige Überarbeitung der React-DAW-Seite mit modularer Architektur,
Web-Audio-Echtzeit-Wiedergabe und serverseitiger DAW-KI. **Alle bestehenden
Endpunkte, Schemas, Tabellen und die Audio-Lade-Logik bleiben unverändert –
alle Erweiterungen sind additiv/kompatibel.**

---

## 1. Datei-Änderungsliste (19 Dateien)

### Frontend – NEU: `frontend-react/src/daw/`
| Datei | Inhalt |
|---|---|
| `timeUtils.js` | Pure Zeit-/Arrangement-Helfer (Verbatim-Port aus dem Monolithen: clamp, clipDuration, Signaturen, Fade-Normalisierung, parseMaybeJson, …) |
| `musicalTime.js` | Takt-/Beat-Mathematik: BPM-Erkennung, Beatgrid-Snapping (bar/beat/half/quarter), Bar-Map-Bereiche für Abschnitte, Ruler-Ticks (Verbatim-Port) |
| `sections.js` | Songstruktur-Auflösung (Intro/Verse/Hook/…) aus `structure_segments_json`, Markern, Beatgrid-Segmenten (Verbatim-Port) |
| `arrangement.js` | Arrangement-Modell (`normalizeArrangement`, Default) + **`createDawCommandPlan` als pure, testbare Funktion** – der eine Ort für alle Timeline-Mutationen (Split, Duplizieren, Trim, Bereich löschen, Abschnitts-Ops, Lücken schließen). Track-Limit im Frontend auf **8 Spuren** erweitert |
| `aiParser.js` | Lokaler, deterministischer DAW-KI-Parser (Deutsch) – läuft sofort/offline; als pure Funktion mit Kontext-Objekt |
| `audioEngine.js` | **NEU: Web-Audio-Engine** – Echtzeit-Multi-Clip-Playback (BufferSource → Clip-Gain/Fades → Track-Gain/Mute/Solo → Master). Kein Server-Preview mehr nötig, um Änderungen zu hören; Buffer-Cache pro `source_audio_id` über die bestehende Stream-Route |
| `store.js` | zustand-Store: Arrangement, Undo/Redo (60 Schritte), Auswahl, Werkzeuge, Transport, Kommandovorschau |
| `daw.css` | Styles der neuen Komponenten (nutzt die bestehenden App-Design-Tokens) |
| `components/TransportBar.jsx` | Play/Pause/Stop, Zeit + Takt-Anzeige, BPM/Taktart, Snap + Einheit, Werkzeuge, Zoom, Undo/Redo, Volume, DAW-KI-Button |
| `components/TimelineRuler.jsx` | Ticks, Bar-Grid (Beatgrid oder BPM-Fallback), Marker, Bereichsauswahl, Snap-Guide, Playhead |
| `components/SectionRail.jsx` | Songabschnitts-Leiste mit Aktionen (duplizieren / ans Ende / entfernen) |
| `components/TrackLane.jsx` | Spuren (Header: Name, Mute/Solo/Volume, Spur ±) + Clips (Move/Trim/Fade-Handles, Schere, **Clip-KI-Textfeld** direkt am Clip) |
| `components/ClipWaveform.jsx` | Clip-Waveform als SVG aus vorhandenen `waveform_json`-Peaks (proportional auf den Quellbereich zugeschnitten – kein Server-Roundtrip) |
| `components/DawPanels.jsx` | Globales KI-Panel (Verlauf, Beispiele, Server-KI-Toggle), Kommandovorschau-Modal, Clip-Inspector, Empty-State |

### Frontend – GEÄNDERT
| Datei | Änderung |
|---|---|
| `src/pages/DawPage.jsx` | **6.266 → 994 Zeilen.** Nur noch Orchestrator: Laden (Arrangement/Projekt/Beatgrid), Engine ↔ Store-Verdrahtung, Drag-Interaktionen, Shortcuts, Save/Export/Render-Task-Polling. Props-Signatur unverändert (App.jsx muss nicht angefasst werden). localStorage-Keys bleiben gleich. **Auto-Save 2,5 s nach jeder Änderung** |
| `src/api/client.js` | Nur ergänzt: `api.daw.arrangementAiCommand(id, payload)` |

### Backend – additiv
| Datei | Änderung |
|---|---|
| `app/models.py` | NEU: Tabelle **`daw_ai_actions`** (`DawAiAction`) – dauerhaftes SQLite-Protokoll aller DAW-KI-Befehle (Eingabe, Interpretation, Operationen, Status, Provider). Wird von `Base.metadata.create_all` automatisch angelegt |
| `app/services/daw_ai_command_service.py` | NEU: **Server-KI-Planer + deterministischer Executor.** Baut Kontext (Arrangement, Songstruktur, Beatgrid, Playhead, Auswahl), lässt den konfigurierten Provider (`AiChatService.run_json_task`) einen Plan aus einer **Operations-Whitelist** erzeugen (split_clip, duplicate_clip, move_clip mit `delta_bars`, trim_clip mit `target_bars`, set_fade/gain, duplicate/append/delete_section, range_delete, close_gaps, create_loop) und wendet ihn serverseitig taktgenau an. Regex-Fallback, falls der Provider ausfällt |
| `app/routers/daw.py` | (a) Track-Limit in `_sanitize_arrangement` kompatibel **3 → 8** (Defaults bleiben 3). (b) NEU: `POST /api/daw/assets/{id}/arrangement/ai-command` – mit `execute=true` wird das Ergebnis über die bestehende `_save_arrangement_to_asset`-Persistenz in SQLite gespeichert; jeder Befehl landet zusätzlich in `daw_ai_actions` |

---

## 2. Was sich für dich ändert (UX)

- **Sofort hörbar:** Multi-Clip-Arrangements spielen direkt im Browser (Web Audio),
  inkl. Fades, Clip-Gain, Track-Volume, Mute/Solo. Bei laufender Wiedergabe folgen
  Undo/Drag/KI-Änderungen ohne Positionsverlust. ffmpeg-Render bleibt für
  „Export“ und „Als Version speichern“ (Hintergrund-Task mit Fortschritt).
- **Echte DAW-Interaktion:** Clips verschieben (mit Magnet-Snap an Clip-Kanten +
  Beatgrid/BPM-Raster), Ränder trimmen, Fade-Handles ziehen, Schere, bis zu
  8 Spuren mit Mute/Solo/Volume, Bereichsauswahl, Marker 1–9, volle Shortcuts.
- **DAW-KI zweistufig:** Jeder Clip hat ein 🤖-Textfeld; dazu das globale
  KI-Panel. Befehle werden zuerst lokal (sofort, offline) geparst; komplexe
  Befehle gehen an den neuen FastAPI-Planer mit Beatgrid-/Struktur-Kontext
  („Setze die erste Hook doppelt“, „Schneide exakt nach 4 Takten“, „Kürze das
  Intro auf 8 Takte“, „Verschiebe den Clip einen Takt nach rechts“, Loops).
  **Jede Aktion wird vor dem Anwenden als prüfbarer Plan angezeigt.**
- **Persistenz:** Arrangement wie bisher in
  `audio_assets.metadata_json.daw_arrangement` (Auto-Save), KI-Befehle neu in
  `daw_ai_actions`.

---

## 3. Installation (WSL2/Debian)

Keine neuen Pakete nötig – `zustand`, `react-hotkeys-hook`, `lucide-react`
sind bereits in der `package.json`. Web Audio ist Browser-nativ.

```bash
# 1) Dateien aus dem ZIP über das Projekt kopieren (Pfade sind identisch):
cd /home/astier/Projekte/<dein-projekt>
unzip -o daw_rework_delta.zip -d .

# 2) Frontend
cd frontend-react
npm install            # nur zur Sicherheit (Lockfile unverändert)
npm run dev            # Vite auf 0.0.0.0:5173

# 3) Backend – neue Tabelle daw_ai_actions wird beim Start automatisch angelegt
cd ..
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Smoke-Test des neuen Endpoints:**
```bash
curl -s -X POST http://localhost:8000/api/daw/assets/<ASSET_ID>/arrangement/ai-command \
  -H 'Content-Type: application/json' \
  -d '{"message": "Setze die erste Hook doppelt", "execute": false}' | python3 -m json.tool
```

---

## 4. Verifiziert

- `esbuild`-Bundle-Check aller neuen JS/JSX-Module: fehlerfrei.
- Node-Smoke-Test des puren Kommandoplaners: Split (1→2 Clips), Hook-Duplikat
  (120 s → 135 s), Lücken schließen, lokaler KI-Parser („Setze die erste Hook
  doppelt“ → `section_duplicate`).
- Python-Syntax (`py_compile`) für `models.py`, `daw.py`, Service: OK.
- Backend-Executor-Test: Split nach 4 Takten @90 BPM → Schnitt bei 10,7 s;
  Hook-Duplikat taktgenau (5 Takte); Fallback-Parser für Takt-Befehle.

## 5. Bewusst NICHT angefasst

- Alle bestehenden `/api/daw`-Endpunkte, `DawArrangementState`-Schema,
  ffmpeg-Render/Preview/Render-Task, Beatgrid-Service, Marker-Endpunkte.
- `_resolve_audio_path` / Audio-Lade-Logik, SQLite-Spalten, `App.jsx`.
- Der alte `/chat`- und `/commands/resolve`-Flow (bleibt funktionsfähig).


---

# v2 – Rendering-Optimierung & Skalierung (dieses ZIP enthält v1 + v2)

## Neu / geändert in v2

### Performance (skaliert jetzt mit vielen Clips)
- **Selector-basierte Store-Subscriptions:** Die DawPage abonniert `currentTime`
  nicht mehr – Zeit-Ticks rendern nur noch zwei Mini-Komponenten
  (`TimeReadout`, `PlayheadLayer`) statt der gesamten Seite. Vorher: kompletter
  React-Tree mit 60 fps neu gerendert; jetzt: 0 Re-Renders pro Frame.
- **`PlayheadLayer.jsx` (neu):** Playhead läuft per `requestAnimationFrame`
  direkt aus der Audio-Engine ins DOM (butterweich), Store-Updates auf ~11 Hz
  gedrosselt (`audioEngine.js`). Inkl. **Auto-Follow**: die Timeline scrollt
  bei Wiedergabe mit (Toggle-Button in der Transportleiste).
- **Memoisierung:** `ClipView`, `TrackLanes`, `TimelineRuler`, `SectionRail`
  via `React.memo` – Clips rendern nur bei echten Arrangement-Änderungen.

### Darstellung
- **Hochauflösende Waveforms:** `audioEngine.peaksFor(id, 1600)` berechnet
  Peaks direkt aus dem dekodierten AudioBuffer (gecacht) und ersetzt die
  groben 180-Punkte-Peaks aus `waveform_json`, sobald die Buffers geladen sind.
- **Kompakter Transport:** eine dichte Zeile statt großflächigem Panel,
  Spurhöhe 84 → 72 px (zentrale CSS-Variable `--daw-lane-height`),
  Ruler-Labels entzerrt (Taktnummern oben, Zeitlabels mit Hintergrund unten).
- **Zoom:** 9 Stufen (4–160 px/s) statt 5, **Strg+Mausrad zoomt auf die
  Cursor-Position** (Zeitpunkt unter dem Cursor bleibt stabil).

### DAW-KI-Panel
- **Papierkorb-Button** im Panel-Kopf: leert Verlauf, Status und Eingabe.
- **Deutlich größer und sichtbarer:** 480 px breit, bis 84 vh hoch,
  Accent-Rahmen mit Glow, Blur-Hintergrund, größere Schrift, klar getrennte
  Kopfzeile.

### CSS-Hygiene (`styles/app.css`)
- **680 tote `.daw-*`-Regeln des alten Monolithen entfernt** (387 → 290 KB),
  zusätzlich 811 `.daw-*`-Selektoren aus geteilten Selektorlisten
  herausgelöst – geteilte Regeln (`.style-preset-tabs`, `.workspace-focus …`,
  `.improved-studio` usw.) bleiben vollständig intakt (verifiziert).
- Damit existiert jede `daw-*`-Klasse nur noch einmal: in `src/daw/daw.css`.
  Die 5 vorherigen Kollisionen (`daw-transport`, `daw-play-button`,
  `daw-time-display`, `daw-transport-group`, `daw-ai-panel`) sind aufgelöst.

## Welche KI wird angesprochen?
Das Endpoint `POST /api/daw/assets/{id}/arrangement/ai-command` nutzt exakt
dieselbe Provider-Kette wie der bestehende DAW-Chat:

1. **Admin-Einstellungen aus SQLite** (`app.routers.admin.get_ai_admin_settings`):
   `default_provider` + `default_model` – also das, was im Admin-Panel der App
   eingestellt ist.
2. **Fallback `.env`/Settings:** `ai_default_provider` (Default: `openai`) und
   `ai_default_model` (Default: `GPT-5.4-mini`).
3. Der Aufruf läuft über `AiChatService.run_json_task()` – unterstützte
   Provider: **openai, openrouter, gemini, groq** (strikter JSON-Modus,
   temperature 0.1, max. 1600 Output-Tokens).
4. **Ohne erreichbaren Provider** greift der deterministische Regex-Fallback
   im Service; Provider/Model + Quelle (`daw_arrangement_ai` vs.
   `daw_arrangement_fallback`) werden pro Befehl in `daw_ai_actions` geloggt.
