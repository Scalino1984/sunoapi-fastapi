# Geschützte Funktionen

## Library Routing

Zweck:

- stabile Songdetailseiten ohne URL-Flackern

Betroffene Dateien:

- `frontend-react/src/App.jsx`
- `frontend-react/src/pages/LibraryPage.jsx`

Bekannte Fehlerbilder:

- Detailansicht springt zwischen gleichnamigen Songs
- viele `/srt` Requests durch Detailseiten-Flackern

Schutzmaßnahmen:

- Route-ID ist Quelle der Wahrheit
- `routeSourceGuard`
- SRT-Request-Dedupe pro `audio_asset_id`

Testverfahren:

- `/library/Teil-der-Nacht-2-119` direkt öffnen
- Player/Library/Status Ziel öffnen testen
- Network prüfen: keine Request-Flut

## SRT-Erzeugung

Zweck:

- SRT/Half-SRT aus Lyrics Source of Truth und Audio-Transkription erzeugen

Betroffene Dateien:

- `app/services/srt_transcript_service.py`
- `app/routers/audio_assets.py`
- `app/services/task_lifecycle_service.py`
- `app/models.py`

Bekannte Fehlerbilder:

- Task bleibt `RUNNING`
- Groq/Provider-Audio-Upload timeoutet
- `audio_transcripts.status=running` bleibt ohne Abschluss
- Statusdetails zeigen nur `1/1`, aber keine Phase

Schutzmaßnahmen:

- `SRT_STATUS_PHASES`
- `response_payload.progress.phase`
- `response_payload.steps_log`
- `transcript_groq_request_timeout_seconds`
- `transcript_groq_max_retries`
- `srt_transcription_timeout_seconds`
- `_finish_srt_status_task()` setzt `completed_at`, finalen Status und Notification

Testverfahren:

- SRT für vorhandenes AudioAsset starten
- Statusdetails beobachten: Phasen müssen sichtbar wechseln
- Providerfehler simulieren: Task muss `FAILED` werden
- SRT nach Erfolg im Songdetail ohne Browserrefresh prüfen

## MiniPlayer SRT Auto-Finish

Zweck:

- SRT-Fertigstellung im Player und in Details automatisch übernehmen

Betroffene Dateien:

- `frontend-react/src/components/MiniPlayer.jsx`
- `frontend-react/src/pages/LibraryPage.jsx`

Bekannte Fehlerbilder:

- `SRT-Erzeugung läuft im Hintergrund` bleibt stehen
- SRT erst nach erneutem Klick sichtbar

Schutzmaßnahmen:

- `srt:updated` Event
- erneutes Nachladen von `api.archive.getSrt(audio_asset_id)` nach Task-Erfolg

Testverfahren:

- SRT aus MiniPlayer erzeugen
- ohne Browserrefresh SRT-Ansicht prüfen

## Waveform-Struktursegmente

Zweck:

- sinnvolle Abschnitte aus SRT-Zeiten/Struktur-Tags anzeigen

Betroffene Dateien:

- `app/services/srt_transcript_service.py`
- `app/services/waveform_service.py`
- `frontend-react/src/components/Waveform.jsx`

Bekannte Fehlerbilder:

- Vocal-Tags werden als Waveform-Segmente angezeigt
- Segmentlabels sind abgehackt oder nur am Anfang verteilt

Schutzmaßnahmen:

- `structure_segments_json` bevorzugen
- SRT-Alignment speichert Struktursegmente
- Descriptor-/FX-Tags ignorieren

Testverfahren:

- alte und neue Songs vergleichen
- Waveform nach SRT-Erzeugung prüfen

## MusicPage / Styles generieren

Zweck:

- Style-Vorschläge, Toggle-Buttons und Songtext-Tag-Vorschau erzeugen

Betroffene Dateien:

- `frontend-react/src/pages/MusicPage.jsx`
- `frontend-react/src/api/client.js`
- `app/routers/assistant.py`
- `app/services/global_assistant_service.py`
- `app/config.py`

Bekannte Fehlerbilder:

- Toggle-Buttons fehlen
- `styleTaggedLyrics is not a function`
- Styles generieren startet nicht wegen fehlender Settings

Schutzmaßnahmen:

- Style-Settings-Vertrag
- API-Client-Methode `styleTaggedLyrics`
- UI-Toggles erhalten

Testverfahren:

- `/music` öffnen
- Styles generieren
- Songtext-Tags-Vorschau öffnen
- Leeren-Button prüft alle Felder
