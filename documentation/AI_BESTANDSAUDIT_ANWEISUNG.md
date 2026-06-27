# KI-Anweisung – Bestandsaudit vor jeder Änderung

Nutze diese Anweisung, bevor du Änderungen an der App vornimmst.

## Auftrag

Führe zuerst ein vollständiges Bestandsaudit der bestehenden React/FastAPI/SQLite-App durch, bevor du Code änderst. Ziel ist, die App, ihre Datenflüsse und ihre bestehenden Root-Regeln zu verstehen, damit keine neuen Abweichungen entstehen.

## Zentrales Zielmodell

Die App folgt diesem Zielmodell:

```text
audio_assets   = zentrale Wahrheit für alles Abspielbare
suno_tasks     = Prozess-, Status- und Task-Log
songs          = Metadaten, Lyrics, Prompt, Style, Modell
audio_projects = logische Projekt-/Song-Gruppierung
```

Jede konkrete Audio-Funktion muss über `audio_asset_id` laufen.

`song_id` darf nur für Metadaten und Gruppierung verwendet werden, nicht als alleiniger Bezug auf eine konkrete Audio-Variante.

## Vor jeder Änderung prüfen

Analysiere zuerst diese Ebenen:

```text
1. Frontend-Komponente
2. API-Client im Frontend
3. FastAPI-Route
4. Service/Fachlogik
5. SQLAlchemy-Modelle
6. SQLite-Tabellen
7. Background-Tasks
8. StatusNotifications
9. lokale Storage-Dateien
10. Audit-/Validierungsskripte
```

## Pflichtfragen

Beantworte vor jeder Änderung schriftlich:

```text
1. Welche Funktion soll geändert werden?
2. Welche Frontend-Dateien sind beteiligt?
3. Welche API-Routen werden genutzt?
4. Welche Services enthalten die eigentliche Logik?
5. Welche Tabellen werden gelesen?
6. Welche Tabellen werden geschrieben?
7. Ist eine konkrete Audiodatei betroffen?
8. Wenn ja: Wird audio_asset_id konsequent verwendet?
9. Entstehen lokale Dateien?
10. Wenn ja: Werden portable relative Pfade statt Fullpaths gespeichert?
11. Entsteht ein Task?
12. Wenn ja: Gibt es einen sauberen SUCCESS/FAILED/CANCELLED-Abschluss?
13. Entsteht Audio?
14. Wenn ja: Wird nach SUCCESS ein AudioAsset materialisiert?
15. Entsteht eine Notification?
16. Wenn ja: Zeigt sie auf Library-Asset, Projekt oder Statusdetail?
17. Kann ein Fehler fälschlich als leere Liste angezeigt werden?
18. Gibt es Legacy-Code, der song_id-only arbeitet?
19. Welche Tests/Audits müssen nach Änderung laufen?
20. Kann die Änderung bestehende Daten beschädigen?
```

## Bereiche gezielt prüfen

Prüfe je nach Änderung mindestens diese Dateien/Pfade:

```text
app/models.py
app/database.py
app/config.py
app/routers/music.py
app/routers/archive.py
app/routers/audio_assets.py
app/routers/system.py
app/services/music_service.py
app/services/audio_asset_materialization_service.py
app/services/audio_cache_service.py
app/services/portable_path_service.py
app/services/portable_backup_service.py
app/services/srt_transcript_service.py
app/services/task_lifecycle_service.py
frontend-react/src/App.jsx
frontend-react/src/api/client.js
frontend-react/src/pages/LibraryPage.jsx
frontend-react/src/pages/MusicPage.jsx
frontend-react/src/pages/SystemPage.jsx
frontend-react/src/pages/StatusPage.jsx
frontend-react/src/styles/app.css
scripts/audit_unified_audio_state.py
scripts/validate_unified_audio_workflow.py
scripts/audit_feature_root_workflows.py
```

## Verbotene Arbeitsweise

Nicht erlaubt:

```text
isolierter Symptom-Fix ohne Datenflussprüfung
Read-Endpoint repariert Daten nebenbei
song_id-only für konkrete Audiodateien
Fullpaths in DB speichern
Audio erzeugen ohne AudioAsset zu materialisieren
Task SUCCESS ohne Notification-Ziel
Fehler als leere Liste anzeigen
neue Sonderlogik statt zentralem Service
Server-Migration als ersten Schritt
```

## Erwarteter Audit-Bericht vor Codeänderung

Erstelle zuerst eine kompakte Bestandsübersicht:

```text
1. Kurzbeschreibung der betroffenen Funktion
2. Frontend → API → Service → DB Ablauf
3. Beteiligte Dateien
4. Beteiligte Tabellen/Felder
5. Aktueller Ist-Zustand
6. Erkannte Risiken oder Root-Abweichungen
7. Empfohlene Änderung am zentralen roten Faden
8. Test- und Validierungsplan
```

## Danach erst ändern

Ändere erst danach den Code.

Bei jeder Änderung gilt:

```text
- vollständige geänderte Dateien liefern
- keine Code-Schnipsel
- keine unnötigen Alternativen
- keine ungeprüften Annahmen
- bestehende Funktionen nicht beschädigen
- nur Patch mit geänderten Dateien erstellen
```

## Pflichtvalidierung nach Änderung

Führe nach der Änderung aus:

```bash
python3 -m compileall -q app scripts
python3 scripts/audit_unified_audio_state.py --database ./suno_fastapi_app.db
python3 scripts/validate_unified_audio_workflow.py --database ./suno_fastapi_app.db
python3 scripts/audit_feature_root_workflows.py --database ./suno_fastapi_app.db --write-report
```

Wenn Frontend betroffen ist:

```bash
cd frontend-react
npm run build
```

Portable Pfade prüfen:

```bash
sqlite3 suno_fastapi_app.db "
SELECT COUNT(*)
FROM audio_assets
WHERE is_deleted=0
  AND local_path LIKE '/%';
"
```

Erwartung:

```text
0
```

## Definition of Done

Die Aufgabe ist erst abgeschlossen, wenn gilt:

```text
Bestandsaudit durchgeführt
Datenfluss verstanden
Änderung folgt dem Zielmodell
compileall OK
Frontend-Build OK, falls betroffen
Feature Root Audit ohne neue CRITICAL/HIGH/MEDIUM
Unified Audio Validation OK
keine neuen Fullpaths in DB
Patch-ZIP enthält nur geänderte Dateien
```
