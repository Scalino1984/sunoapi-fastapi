# Scripts Overview

Kompakte Übersicht der aktuell vorhandenen Skripte im Ordner `scripts/`.

| Skript | Kurzbeschreibung | Bewertung |
| --- | --- | --- |
| `audit_feature_root_workflows.py` | Read-only Audit für SRT, Stems, WAV, Player, Download, Favoriten, Cover, Songdetails und Production gegen `audio_assets`. | Nützlich für Integritätsprüfung, sicher. |
| `audit_unified_audio_state.py` | Prüft SQLite-DB auf Unified-Audio-Abweichungen, fehlende Links, lokale Audio-/Bild-Zustände. | Nützlich, read-only. |
| `backup-srv.sh` | Server-Backup von `/opt/songstudio` nach `/root/.backups`, inkl. Rotation. | Server-only, sinnvoll vor Deploys. |
| `backup.sh` | Lokales Mini-ZIP mit DB, `storage/audio`, `.env`, README. | Enthält echte `.env`, nicht für Public-Zwecke. |
| `create-public-release-copy.sh` | Erstellt bereinigte Public-Kopie unter `~/.public-apps/<projekt>`. | Sinnvoll für GitHub-Veröffentlichung. |
| `create-zip` | Erstellt hart kodiertes ZIP nach `~/sunoapi-fastapi-srv.zip`. | Veraltet/fragil; `rm` scheitert, wenn ZIP fehlt. |
| `create_ai_test_zip.sh` | Erstellt KI-Test-ZIP mit Projektdateien und Storage-Inventar statt echten Storage-Dateien. | Speziell für Testgenerierung/Analyse. |
| `export_unified_audio_report.py` | Baut Markdown-Report aus Unified-Audio-Audit. | Nützlich für Dokumentation/Audit. |
| `local_unified_audio_master_check.sh` | Führt Compile, Audit, Migration-Dry-Run, Validierung und Report nacheinander aus. | Guter lokaler Healthcheck. |
| `logs-dev.sh` | Tailt FastAPI- und React-Logs aus `.runtime/logs`. | Einfaches Dev-Logging. |
| `migrate_unified_audio_library.py` | Migriert bestehende DB-Daten in den vereinheitlichten `audio_assets`-Workflow. | Wichtig, aber nur mit Backup/`--dry-run` nutzen. |
| `normalize_suno_source_dates.py` | Normalisiert lokale Importdaten auf Suno/SunoAPI-Erstelldatum. | DB-verändernd; vorsichtig mit `--backup`. |
| `publish-react.sh` | Server-Skript für React-Build, Deploy nach `/var/www/songstudio-react`, Apache reload, Rollback/Status. | Server-only, produktionsrelevant. |
| `repair-admin-user.py` | Erstellt/repariert Admin-User ohne Datenbank zu löschen. | Nützlich für Login-Recovery. |
| `repair_feature_root_workflow_findings.py` | Repariert Audit-Befunde für Feature-Root-Workflows, ohne Jobs zu starten. | DB-verändernd; mit `--dry-run`/Backup nutzen. |
| `repair_waveform_segments.py` | Repariert Waveform-Segment-Overlays aus Lyrics-/Prompt-Struktur. | Gezielt, DB-verändernd, Dry-Run vorhanden. |
| `rsync-to-vserver.sh` | Synchronisiert Code per rsync auf VServer `/opt/songstudio`; optional Build/Publish/Restart. | Deploy-Hauptskript. |
| `smoke_test.sh` | Prüft `/health/live`, `/health/ready`, `/api/system/diagnostics`. | Schneller Verfügbarkeitstest. |
| `sqlite_to_postgres.py` | Kopiert SQLite-Daten in PostgreSQL, mit Dry-Run und Tabellenfiltern. | Migrationswerkzeug, destruktiv bei `--clear-target`. |
| `start-dev.sh` | Startet FastAPI und React/Vite lokal im Hintergrund. | Dev-Startskript. |
| `status-dev.sh` | Prüft lokale Dev-Prozesse/PID-Dateien/Ports. | Dev-Diagnose. |
| `stop-dev.sh` | Stoppt lokale FastAPI-/React-Prozesse inkl. Port-Prozesssuche. | Dev-Stopskript. |
| `upgrade_db.sh` | Führt `alembic upgrade head` aus. | Standard DB-Migration. |
| `validate_unified_audio_workflow.py` | Validiert lokalen Unified-Audio-Zielstand nach Migration/Patch. | Read-only/Validierung. |
| `zip-app.sh` | Altes ZIP-Skript mit hart kodiertem Ziel. | Wahrscheinlich defekt: Backslash mit Leerzeichen bei `zip -r "$PFAD/$ZIPNAME" \ `. Besser ersetzen. |

## Kurzfazit

Aktiv sinnvoll:

- `rsync-to-vserver.sh`
- `create-public-release-copy.sh`
- `start-dev.sh`
- `stop-dev.sh`
- `status-dev.sh`
- `publish-react.sh`
- `backup-srv.sh`
- Audit-/Repair-/Validate-Skripte

Mit Vorsicht oder als veraltet betrachten:

- `backup.sh`: enthält echte `.env` im Backup.
- `create-zip`: harte Pfade und fragile Löschlogik.
- `zip-app.sh`: harte Pfade und wahrscheinlich fehlerhafte Shell-Syntax.
