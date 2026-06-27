# Audio AI Analysis Implementation

## Contract

Die lokale Audioanalyse ist ein isoliertes Zusatzfeature fuer bestehende `AudioAsset`-Eintraege.
Sie darf keine Suno-Payloads, Importprozesse, SRT-Erzeugung, Extend-`continueAt`-Logik oder Cover-Workflows veraendern.

## Speicherung

- DB: `audio_assets.metadata_json["audio_ai_analysis"]`
- Optionaler Song-Verweis: `songs.metadata_json["audio_ai_analysis_assets"][audio_asset_id]`
- Dateien: `storage/analysis/audio_<audio_asset_id>/`
- Modellcache: `storage/models/huggingface`
- Exportformate: JSON, Markdown, HTML, Beatgrid CSV

## Backend

- Service: `app/services/audio_ai_analysis_service.py`
- API:
  - `GET /api/audio-assets/{audio_asset_id}/analysis`
  - `POST /api/audio-assets/{audio_asset_id}/analysis/generate`
  - `GET /api/audio-assets/{audio_asset_id}/analysis/export/{kind}`
- Status-Task: `suno_tasks.task_type = "audio_ai_analysis"`
- Notifications:
  - Start zeigt auf `/status`
  - Erfolg zeigt auf die Library mit `audio_asset_id`

## Frontend

- API-Client: `frontend-react/src/api/client.js`
- UI: `frontend-react/src/pages/LibraryPage.jsx`
- Detailbereich: Card `Lokale Audioanalyse`
- Drei-Punkt-Menues:
  - `Audioanalyse starten`
  - `Audioanalyse-Report öffnen`
- Report-Modal: `AudioAiAnalysisReportModal`

## Aktueller Funktionsumfang

- Lokale Dateipruefung und Dateimetadaten
- Dauer, Dateigroesse, Content-Type
- RMS-/Lautheitsheuristik
- Tempo- und Beatgrid-Ermittlung ueber `librosa`, falls installiert
- Copyright-/Bekanntaufnahme-Pruefung ueber Chromaprint/AcoustID, wenn `ACOUSTID_API_KEY` gesetzt und `pyacoustid/fpcalc` verfuegbar sind
- Genre-Klassifikation ueber internes optionales Transformers-Modell `dima806/music_genres_classification`
- Vocal/Speech/Music- und Instrument-Indizien ueber internes optionales AST/AudioSet-Modell
- Deepfake/Synthetic-Indizien ueber interne optionale Audio-Klassifikationsmodelle
- Deterministischer Report-Fallback
- Optionale KI-Aufbereitung ueber den bestehenden `AiChatService`, wenn der konfigurierte Provider verfuegbar ist

Fehlende optionale Analysepakete duerfen die Basisanalyse nicht abbrechen. Der Report muss in diesem Fall den Grund dokumentieren.
Es duerfen keine absoluten Pfade ausserhalb der App verwendet werden; alle Funktionen und Artefakte muessen im Projekt/App-Storage liegen.
