# Änderungsschutz-Protokoll

## 2026-06-24 – SRT-Statusphasen und Provider-Timeouts

### IST-STAND

Aktueller Basisstand:

- `sunoapi-fastapi-vserver-2-stylefixed-no-storage-db-2026-06-24.zip`
- bestätigter Route-/SRT-Dedupe-Schutz vorhanden

Beteiligte Dateien:

- `app/services/srt_transcript_service.py`
- `app/config.py`
- `tests/test_srt_status_contract.py`
- `docs/ARCHITECTURE_CONTRACT.md`
- `docs/PROTECTED_FUNCTIONS.md`
- `docs/CHANGELOG_PROTECTION.md`

### GEPLANTE ÄNDERUNG

Erlaubt:

- SRT-Task-Status detaillierter machen
- Provider-/Transkriptions-Timeouts ergänzen
- Task-Finalisierung robuster dokumentieren
- Dokumentation erweitern

### AUSDRÜCKLICH GESCHÜTZTE BEREICHE

Nicht ändern:

- `frontend-react/src/App.jsx`
- `frontend-react/src/pages/LibraryPage.jsx`
- `frontend-react/src/components/MiniPlayer.jsx`
- `frontend-react/src/components/Waveform.jsx`
- `frontend-react/src/pages/MusicPage.jsx`
- `frontend-react/src/api/client.js`
- `app/routers/audio_assets.py`
- DB-Modelle
- Library-Layout
- Style-Generator
- Bulk-Auswahl/Löschen

### VALIDIERUNG

Pflicht:

- `python3 -m compileall -q app scripts`
- `python3 -m py_compile tests/test_srt_status_contract.py`
- optional `pytest tests/test_srt_status_contract.py`

### ERGEBNIS

- detaillierte SRT-Statusphasen ergänzt
- Groq-/Transkriptions-Timeouts konfigurierbar ergänzt
- finale Task-Finalisierung schreibt Status, completed_at, progress und steps_log
