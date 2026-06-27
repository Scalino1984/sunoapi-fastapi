# Extend Auto-continueAt Protokoll

Stand vor der Erweiterung:
- `/music` sendet fuer Extend einen manuell eingegebenen `continueAt`-Wert.
- Der React-Extend-Pfad ruft `api.archive.extend(assetId, payload)` auf.
- Backend-Endpunkt: `POST /api/archive/audio/{asset_id}/extend` in `app/routers/archive.py`.
- Der Endpunkt setzt `audioId` aus dem lokalen AudioAsset und leitet den Payload an `MusicService.call_task_endpoint("extend_music", ...)` weiter.
- Admin-Settings werden zentral in `app_settings.value` mit Key `ai_chat_settings` gespeichert und ueber `/api/admin/ai-settings` verwaltet.

Ziel der Erweiterung:
- Die automatische Ermittlung von `continueAt` ist optional und standardmaessig deaktiviert.
- Wenn die Admin-Option deaktiviert ist, bleibt der bestehende manuelle Extend-Flow unveraendert.
- Wenn die Admin-Option aktiviert ist, kann das Frontend optional `autoContinueAt: true` senden.
- Nur dann darf das Backend vor dem SunoAPI-Request einen optimierten `continueAt`-Wert berechnen und in den Payload setzen.

Neue/erweiterte Dateien:
- `app/services/extend_continue_at_analysis_service.py`
  - isolierte Analysefunktion fuer den optimierten Extend-Zeitpunkt
  - temporaere Dateien nur in `TemporaryDirectory`
  - Cleanup automatisch durch Kontextmanager
- `app/routers/archive.py`
  - bindet die optionale Analyse ausschliesslich im Archive-Extend-Endpunkt an
- `app/routers/admin.py`
  - speichert und liest Admin-Flags fuer Auto-continueAt
- `app/schemas.py`
  - akzeptiert optionale Payload-Flags und Admin-Settings
- `frontend-react/src/pages/AdminPage.jsx`
  - Admin-Schalter fuer automatische continueAt-Analyse
- `frontend-react/src/pages/MusicPage.jsx`
  - optionaler Schalter im Extend-Formular, nur wenn Runtime/Admin-Config aktiv ist
- `requirements-stems.txt`
  - `librosa` als optionale Analyse-Abhaengigkeit neben Demucs

Status-Protokoll:
- Bei aktivierter Auto-Analyse werden Statusmeldungen fuer Start und Abschluss geschrieben.
- Analyseergebnis und Fallback-Gruende stehen im `target_payload.analysis` der Statusmeldung.
- Diese Analyseinfos werden nicht an sunoapi.org gesendet.

Rueckbaupunkte:
- Admin-Schalter `extend_auto_continue_at_enabled` auf `false` setzen, um Laufzeitverhalten sofort auf den vorherigen Zustand zurueckzusetzen.
- Fuer vollstaendigen Code-Rueckbau die oben gelisteten Aenderungen entfernen.
- Der manuelle `continueAt`-Pfad bleibt als Fallback erhalten.

Sicherheits-/Stabilitaetsregeln:
- Keine Analyse ausfuehren, wenn Admin-Option deaktiviert ist.
- Keine Analyse ausfuehren, wenn `autoContinueAt` nicht explizit gesetzt ist.
- Bei Analysefehlern wird der vorhandene manuelle `continueAt`-Wert weiterverwendet, sofern gueltig.
- SunoAPI erhaelt keine internen Analyseflags wie `autoContinueAt` oder `continueAtAnalysis`.
