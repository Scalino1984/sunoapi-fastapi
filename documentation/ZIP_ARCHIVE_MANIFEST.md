# ZIP-Archiv Manifest

Diese Datei sammelt die relevanten Projektdateien und Verzeichnisse fuer ein
komplettes ZIP-Archiv, das als Grundlage fuer Analyse, Testgenerierung und
spätere Fixes durch eine KI dienen kann.

## Ziel

Das Archiv soll genug Kontext enthalten, um:

- die Backend- und Frontend-Funktionen zu verstehen,
- automatisierte Tests im `tests/`-Ordner zu erweitern,
- bestehende Regressionen zu erkennen,
- lokale Testdaten zu verwenden,
- ohne echte Suno- oder andere Live-API-Aufrufe arbeiten zu koennen.

## Pflichtbestandteile

Diese Teile sollten im ZIP enthalten sein:

- `app/`
- `frontend-react/src/`
- `frontend-react/public/`
- `frontend-react/index.html`
- `frontend-react/package.json`
- `frontend-react/package-lock.json`
- `frontend-react/vite.config.js`
- `tests/`
- `migrations/`
- `alembic.ini`
- `requirements.txt`
- `requirements-whisperx.txt`
- `requirements-stems.txt`
- `pytest.ini`
- `docker-compose.yml`
- `Dockerfile`
- `scripts/`
- `documentation/`
- Root-Markdown-Dateien im Projektstamm

## Wichtige Dokumentation

Diese Dateien sind besonders wichtig fuer Kontext, Teststrategie und bekannte
Entwicklungsentscheidungen:

- `documentation/TEST_GENERATION_PROMPT.md`
- `documentation/LIBRARY_FRONTEND_IST_STAND.md`
- `documentation/README_DEVELOPER_WORKFLOW.md`
- `documentation/PATCH_DEVELOPER_WORKFLOW_DOCS_2026-06-22.md`
- `README.md`
- `GIT-README.md`
- `PROJECT_BASELINE_SUNOAPI_2026-06-20.md`
- `RELEASE_FINALIZED.md`

Wenn moeglich, sollten auch die relevanten `PATCH_*.md` und `RELEASE_*.md`
Dateien mit aufgenommen werden, da sie funktionale Aenderungen und bekannte
Fixes dokumentieren.

## Relevante Test- und Analyse-Dateien

Folgende Dateien sind fuer die Testgenerierung und Analyse besonders wertvoll:

- `tests/test_auth.py`
- `tests/test_ai_chat.py`
- `tests/test_audio_asset_schema.py`
- `tests/test_audio_cache_task_types.py`
- `tests/test_library_delete_orphan_import_links.py`
- `tests/test_srt_editor_utils.py`
- `tests/test_srt_structure_segments.py`
- `tests/test_task_watchdog.py`
- `scripts/audit_feature_root_workflows.py`
- `scripts/audit_unified_audio_state.py`
- `scripts/export_unified_audio_report.py`
- `scripts/validate_unified_audio_workflow.py`
- `scripts/repair_waveform_segments.py`

## Lokale Daten und Fixtures

Fuer realistische, aber lokale Tests sind diese Datenquellen wertvoll:

- `documentation/storage_snapshot.txt` im Archiv als Textabbild der vorhandenen `storage/`-Inhalte
- `tests/`-Fixtures
- kleine, lokale JSON-/SRT-/Markdown-Beispiele in der Dokumentation oder Testordnern

Wichtig:

- keine echten `storage/`-Binärdateien in das Test-ZIP aufnehmen,
- stattdessen die Inhalte von `storage/` in einer Textdatei zusammenfassen,
- reale Audio- oder Medienfixtures nur dann verwenden, wenn sie zwingend noetig und klein genug sind.

## Eher auslassen, wenn Platz gespart werden soll

Diese Dateien sind fuer die reine Codeanalyse meist nicht notwendig:

- `frontend-react/dist/`
- `frontend-react/node_modules/`
- `__pycache__/`
- generierte temporäre Dateien
- grosse Medienartefakte ohne Testbezug

## Empfehlung fuer eine gute Archivstruktur

Ein sinnvolles ZIP sollte folgende Logik haben:

1. Code, Tests und Konfiguration vollstaendig mitnehmen.
2. Dokumentation und Patch-Historie mitnehmen.
3. Kleine, reale Fixture-Daten mitnehmen.
4. Grosse Laufzeit- oder Build-Artefakte weglassen.
5. Alles so anordnen, dass eine KI die Projektstruktur direkt erkennen kann.

## Erzeugungsscript

Das Projekt enthaelt jetzt ein dediziertes Script fuer solche ZIP-Archive:

- `scripts/create_ai_test_zip.sh`

Standardmaessig erstellt es ein kuratiertes Archiv mit Code, Tests, Dokumentation und einer Text-Snapshot-Datei fuer `storage/`.
Es werden keine echten `storage/`-Binärdateien mitgenommen.

## Hinweis

Wenn das Archiv fuer eine KI zur Testgenerierung gedacht ist, ist ein
mittelschweres, gut kuratiertes Archiv besser als ein maximal grosses Archiv.
Die wichtigsten Dinge sind: Quellcode, Tests, Konfiguration, Dokumentation und
eine kleine Menge an realistischen Datenfixtures.
