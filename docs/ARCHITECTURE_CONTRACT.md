# Architekturvertrag

## Projektübersicht

Suno Song Studio ist eine FastAPI + React/Vite + SQLite/SQLAlchemy Anwendung zur Musikproduktion, Library-Verwaltung, SRT-Erzeugung, Waveform-Anzeige, Statusüberwachung und KI-gestützten Style-/Lyrics-Funktionen.

Aktueller verbindlicher Basisstand:

- `sunoapi-fastapi-vserver-2-stylefixed-no-storage-db-2026-06-24.zip`
- Basis-SHA256: `7ea2ceda8a73a025d6588bce309b70bcbd676ab44a8caeab38af4ca2b218bf9b`
- Zusätzlich bestätigter guter Zustand: `suno_patch_library_route_source_guard_srt_dedupe_2026-06-24.zip`

## Kernarchitektur

### Frontend

- React/Vite
- zentrale Navigation und globale Player-/Library-State-Kopplung in `frontend-react/src/App.jsx`
- Library-Detailansichten in `frontend-react/src/pages/LibraryPage.jsx`
- MiniPlayer in `frontend-react/src/components/MiniPlayer.jsx`
- Music/Styles in `frontend-react/src/pages/MusicPage.jsx`
- API-Client in `frontend-react/src/api/client.js`

### Backend

- FastAPI-Router unter `app/routers/`
- Fachlogik unter `app/services/`
- lange Jobs als lokale `suno_tasks` und Background-Worker
- Statusmeldungen über `StatusNotification`

### Datenbank

- SQLite
- SQLAlchemy-Modelle in `app/models.py`

## Zentrale Datenmodelle

### audio_assets

Verantwortung:

- einzige Wahrheit für abspielbare Inhalte
- alle konkreten Audiofunktionen laufen über `audio_asset_id`

Verboten:

- Wiedergabe oder Dateioperationen nur über `song_id`

### songs

Verantwortung:

- Metadaten, Titel, Lyrics, Style, Prompt

Verboten:

- technische Audioidentität

### audio_projects

Verantwortung:

- logische Gruppierung von Varianten

### suno_tasks

Verantwortung:

- Prozessstatus, Importstatus, Taskhistorie
- lokale Tasks müssen terminal enden: `SUCCESS`, `FAILED`, `CANCELLED` oder `PARTIAL_SUCCESS`

### audio_transcripts

Verantwortung:

- SRT/Half-SRT, Segmentdaten, Providerstatus
- `status=running` darf nicht dauerhaft ohne Task-Finalisierung verbleiben

## Geschützte Funktionen

### Library Routing

Dateien:

- `frontend-react/src/App.jsx`
- `frontend-react/src/pages/LibraryPage.jsx`

Regeln:

- eindeutige URLs wie `/library/Titel-119` öffnen exakt `project-119`
- Titel ist Anzeige, nicht technische Identität
- Route-/SRT-Dedupe-Schutz aus `suno_patch_library_route_source_guard_srt_dedupe_2026-06-24.zip` nicht überschreiben

### SRT-Erzeugung

Dateien:

- `app/services/srt_transcript_service.py`
- `app/routers/audio_assets.py`
- `app/services/task_lifecycle_service.py`

Regeln:

- SRT startet über `audio_asset_id`
- Read-Endpunkte erzeugen keine SRT nebenbei
- Lyrics-Cleanup darf Transkription nicht blockieren
- Providerfehler und Timeouts müssen `suno_tasks.status=FAILED` und `audio_transcripts.status=error` setzen
- `response_payload.progress.phase` muss den aktuellen Schritt zeigen
- `response_payload.steps_log` dokumentiert die Pipeline-Schritte

### SRT → Waveform-Struktursegmente

Dateien:

- `app/services/srt_transcript_service.py`
- `app/services/waveform_service.py`
- `frontend-react/src/components/Waveform.jsx`

Regeln:

- SRT-Zeiten können bessere `structure_segments_json` erzeugen
- Waveform-Anzeige bevorzugt Struktursegmente vor Roh-Tags
- Vocal-/FX-/Style-Tags sind keine technischen Abschnitte

### MiniPlayer

Dateien:

- `frontend-react/src/components/MiniPlayer.jsx`

Regeln:

- Playback darf keine Refresh- oder Scroll-Schleifen erzeugen
- SRT-Fertigstellung muss ohne Browserrefresh erkennbar sein

### MusicPage / Styles generieren

Dateien:

- `frontend-react/src/pages/MusicPage.jsx`
- `frontend-react/src/api/client.js`
- `app/services/global_assistant_service.py`
- `app/routers/assistant.py`

Regeln:

- Toggle-Buttons und Songtext-Tag-Vorschau erhalten
- Style-Limits und Batching-Settings nicht entfernen

## Bekannte Architekturentscheidungen

### Titel dürfen niemals technische Identität sein

Grund:

- Titel können doppelt vorkommen und geändert werden

Verwendet wird:

- `audio_asset_id`
- `project.id`
- `song_id` nur für Metadaten

### SRT-Provider müssen harte Timeouts haben

Grund:

- externe Provider wie Groq können bei Audio-Uploads hängen oder timeouten
- UI darf nie dauerhaft `RUNNING` zeigen, ohne Phase oder Terminalstatus

## Änderungsverlauf

### 2026-06-24 – SRT-Statusphasen und Provider-Timeouts

Betroffene Dateien:

- `app/config.py`
- `app/services/srt_transcript_service.py`
- `tests/test_srt_status_contract.py`
- `docs/ARCHITECTURE_CONTRACT.md`
- `docs/PROTECTED_FUNCTIONS.md`
- `docs/CHANGELOG_PROTECTION.md`

Grund:

- `generate_srt` Tasks konnten nach Lyrics-Cleanup bei Provider-/Transkriptionsaufrufen lange als `RUNNING` wirken.
- Statusdetails zeigten nicht genug Phasen, um den Hänger einzugrenzen.

Kernänderungen:

- detaillierte SRT-Phasen in `response_payload.progress`
- `steps_log` im Task-Response-Payload
- harte Provider-/Transkriptions-Timeouts über Settings
- finale Task-Finalisierung mit `completed_at`, `heartbeat_at`, finaler Phase und Notification

Nicht verändert:

- Library-Routing
- MiniPlayer
- Waveform
- MusicPage/Styles
- DB-Modelle
- FastAPI-Routen

Validierung:

- `python3 -m compileall -q app scripts`
- `python3 -m py_compile tests/test_srt_status_contract.py`

Ergebnis:

- erfolgreich
