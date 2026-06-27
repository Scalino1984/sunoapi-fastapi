# Suno Song Studio – Entwicklerhandbuch für konsistente Weiterentwicklung

## 1. Grundprinzip

Die lokale App ist das führende Zielsystem.

Der VServer ist nur ein späteres Deployment-Ziel. Entwicklung, Datenkorrektur, Tests und Validierung erfolgen zuerst lokal.

Die App folgt diesem Zielmodell:

```text
audio_assets   = zentrale Wahrheit für alles Abspielbare
suno_tasks     = Prozess-, Status- und Task-Log
songs          = Metadaten, Lyrics, Prompt, Style, Modell
audio_projects = logische Projekt-/Song-Gruppierung
```

Jede Funktion, die mit einer konkreten Audiodatei arbeitet, muss über `audio_asset_id` laufen.

---

## 2. Zentrale Datenregeln

### Pflicht

Diese Bereiche müssen primär an `audio_assets.id` hängen:

```text
Player
Download
SRT
Stems
WAV
Cover
Favoriten
Songdetails
Production
Playlists
Library
```

### Verboten

Neue Funktionen dürfen nicht nur über `song_id` arbeiten, wenn eine konkrete Audiodatei oder Variante betroffen ist.

Falsch:

```text
song_id -> irgendein letztes AudioAsset suchen
```

Richtig:

```text
audio_asset_id -> exakt diese Variante verwenden
```

### `songs`

`songs` ist nur ergänzende Metadatenebene:

```text
title
lyrics
prompt
style
model
task_id
raw metadata
```

`songs` ist nicht die Library-Wahrheit.

### `suno_tasks`

`suno_tasks` ist nur Prozesslog:

```text
task_type
status
request_payload
response_payload
result_payload
error
progress
external task id
```

`suno_tasks` darf nicht als direkte Library-Quelle missbraucht werden.

---

## 3. Task-Success-Vertrag

Jeder Task, der Audio erzeugt oder importiert, muss nach erfolgreichem Abschluss diesen Ablauf erfüllen:

```text
Task SUCCESS
→ SunoTask aktualisieren
→ Song/Projekt aktualisieren
→ AudioAssets materialisieren
→ lokale Dateien optional cachen
→ Notification mit Ziel erzeugen
→ Frontend kann Library direkt aktualisieren
```

Pflicht für Audio-erzeugende Funktionen:

```text
generate_music
extend
cover_song
add_vocals
add_instrumental
sunoapi_import
opencli_import
manual_import
batch_import
```

Nach `SUCCESS` muss mindestens ein gültiger `audio_assets`-Eintrag existieren, sobald eine echte Audio-URL vorhanden ist.

---

## 4. AudioAsset-Materialisierung

AudioAsset-Erzeugung darf nicht vom lokalen Cache abhängen.

Richtig:

```text
Audio-URL vorhanden
→ AudioAsset erzeugen mit status=remote
→ optional lokal downloaden
→ bei Erfolg status=cached
```

Falsch:

```text
Nur AudioAsset erzeugen, wenn lokaler Download erfolgreich war
```

Der zentrale Service für diese Aufgabe ist:

```text
app/services/audio_asset_materialization_service.py
```

Neue Funktionen müssen diesen Service nutzen oder dessen Regeln exakt einhalten.

---

## 5. Portable Pfade

Die Datenbank darf keine hostabhängigen Absolutpfade als dauerhafte Referenz speichern.

Falsch:

```text
/home/astier/Projekte/sunoapi-fastapi/storage/audio/file.mp3
/opt/songstudio/storage/audio/file.mp3
```

Richtig:

```text
storage/audio/file.mp3
storage/covers/file.jpg
storage/transcripts/file.srt
storage/stems/...
```

Dateiauflösung erfolgt zur Laufzeit über Projektpfad und Storage-Konfiguration.

Neue lokale Inhalte müssen standardmäßig lokal gespeichert werden.

Default:

```env
SUNO_AUDIO_CACHE_MODE=on_success
LOCAL_CONTENT_STORAGE_ENABLED=true
```

Remote-only ist nur erlaubt, wenn explizit deaktiviert:

```env
SUNO_AUDIO_CACHE_MODE=off
LOCAL_CONTENT_STORAGE_ENABLED=false
```

---

## 6. Backup- und Restore-Regel

Portable Backups müssen enthalten:

```text
manifest.json
database/suno_fastapi_app.db
files/audio/**
files/covers/**
files/transcripts/**
files/stems/**
files/exports/**
```

Import-Regel:

```text
1. Vor Import aktuellen Ist-Stand automatisch sichern
2. Backup prüfen
3. DB übernehmen
4. lokale Dateien übernehmen
5. Pfade normalisieren
6. App danach mit importiertem Stand betreiben
```

Während Import/Restore dürfen keine laufenden Tasks, SRT-, Stem-, WAV- oder Cover-Jobs aktiv sein.

---

## 7. Frontend-Regeln

Listen dürfen Fehler nicht als leere Ansicht tarnen.

Jede Hauptansicht braucht getrennte Zustände:

```text
loading
loaded_empty
loaded_with_data
error
stale
```

Betroffen:

```text
Library
Status
System
Production
Playlists
Songdetails
Admin
```

Buttons und Menüs müssen layout-stabil sein:

```text
keine springenden Hover-Transforms in Menüs
feste Icon-Spalten
feste Aktionsspalten
lange Texte mit ellipsis
Dropdowns als Overlay/Portal statt Layout-Verschiebung
```

---

## 8. Notifications

Erfolgreiche Einzel-Audio-Tasks müssen auf konkrete Inhalte zeigen:

```json
{
  "task_local_id": 123,
  "task_type": "generate_music",
  "status": "SUCCESS",
  "audio_asset_ids": [10, 11],
  "primary_audio_asset_id": 10,
  "song_id": 5,
  "project_id": 2,
  "target_tab": "library"
}
```

Batch-Jobs ohne einzelnes Audio-Ziel zeigen auf Statusdetails:

```json
{
  "task_local_id": 123,
  "task_type": "bulk_generate_srt",
  "status": "SUCCESS",
  "notification_scope": "batch_summary",
  "click_target": "status_detail",
  "target_tab": "status"
}
```

---

## 9. SRT-Regeln

SRT muss über `audio_asset_id` laufen.

Falsch:

```text
/api/songs/{song_id}/srt
→ letztes Asset suchen
```

Richtig:

```text
/api/audio-assets/{audio_asset_id}/srt
```

Mehrere SRT-Versionen pro Asset sind erlaubt, aber das UI muss bewusst damit umgehen:

```text
latest completed
version history
error entries ausblenden oder separat anzeigen
aktive Version markieren
```

---

## 10. Stems, WAV, Cover

Diese Funktionen erzeugen Zusatzdaten zu einem konkreten Asset.

Sie dürfen keine neue Song-Wahrheit erzeugen.

Richtig:

```text
audio_asset_id
→ Stems in metadata_json / storage/stems
→ WAV in metadata_json / storage/exports
→ Cover in image_url / cover_path / metadata_json
```

Falsch:

```text
neuen Song erzeugen
Asset über song_id erraten
lokale Datei mit Fullpath fest in DB schreiben
```

---

## 11. SQLite- und Background-Task-Regeln

SQLite bleibt lokal erlaubt, aber mit Disziplin.

Pflicht:

```text
kurze Transaktionen
eigene DB-Session pro Background-Task
keine langen Downloads innerhalb offener DB-Transaktion
kein Repair im normalen Read-Pfad
WAL nur beim Init setzen
busy_timeout aktiv
```

Nicht erlaubt:

```text
Read-Endpoint repariert nebenbei große Datenmengen
Task hält DB-Lock während externem API-Call
Polling triggert schwere DB-Rekonstruktionen
```

---

## 12. Read-Path vs. Write-Path

Read-Endpoints dürfen lesen und formatieren.

Write-/Task-Endpunkte müssen Daten korrekt erzeugen.

Falsch:

```text
Library öffnen
→ fehlende AudioAssets reparieren
```

Richtig:

```text
Task SUCCESS
→ AudioAssets erzeugen
Library öffnen
→ nur audio_assets lesen
```

Repair-Skripte sind nur für Altbestand, Wartung und Migration erlaubt.

---

## 13. Pflichtprüfungen nach jeder Änderung

Nach jeder Änderung ausführen:

```bash
python3 -m compileall -q app scripts
```

Wenn Frontend betroffen ist:

```bash
cd frontend-react
npm run build
```

Datenmodell prüfen:

```bash
python3 scripts/audit_unified_audio_state.py --database ./suno_fastapi_app.db
python3 scripts/validate_unified_audio_workflow.py --database ./suno_fastapi_app.db
python3 scripts/audit_feature_root_workflows.py --database ./suno_fastapi_app.db --write-report
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

---

## 14. Definition of Done

Eine Änderung ist erst fertig, wenn gilt:

```text
compileall OK
Frontend Build OK, falls Frontend betroffen
SQLite integrity_check OK
keine neuen CRITICAL/HIGH/MEDIUM im Feature Root Audit
keine neuen Fullpaths in audio_assets.local_path
neue Audio-Funktionen erzeugen AudioAssets direkt
Notifications zeigen auf korrekte Ziele
Library zeigt Daten ohne F5/FastAPI-Neustart
```

---

## 15. KI-Arbeitsauftrag für künftige Änderungen

Verwende diesen Auftrag für neue Änderungen:

```text
Analysiere die bestehende React/FastAPI/SQLite-App zuerst entlang des zentralen Zielmodells:

audio_assets = zentrale Wahrheit für alles Abspielbare
suno_tasks = Prozess-/Statuslog
songs = Metadaten/Lyrics/Prompt
audio_projects = logische Gruppierung

Ändere keine Funktion isoliert. Prüfe immer:
1. Welche Route wird im Frontend aufgerufen?
2. Welche FastAPI-Route verarbeitet die Aktion?
3. Welcher Service enthält die Fachlogik?
4. Welche Tabellen werden gelesen oder geschrieben?
5. Wird eine konkrete Audiodatei verwendet? Dann muss audio_asset_id führend sein.
6. Werden lokale Dateien erzeugt? Dann dürfen keine absoluten Fullpaths in der DB landen.
7. Erzeugt die Funktion Audio? Dann muss nach SUCCESS ein AudioAsset existieren.
8. Gibt es Notifications? Dann müssen sie auf audio_asset_id, project_id oder Statusdetail zeigen.
9. Gibt es Altcode über song_id-only? Dann nicht erweitern, sondern auf audio_asset_id umstellen oder als Legacy belassen.
10. Nach der Änderung müssen compileall, Frontend-Build und die Audit-Skripte erfolgreich laufen.

Liefere nur vollständige geänderte Dateien oder ein Patch-ZIP mit ausschließlich geänderten Dateien.
Keine Symptom-Fixes, wenn ein Root-Problem sichtbar ist.
Keine Server-Migration als ersten Schritt. Lokale App ist Master.
```

---

## 16. Verbotene Schnellfixes

Nicht akzeptieren:

```text
nach F5 reparieren
beim Öffnen der Library Daten rekonstruieren
song_id als Ersatz für audio_asset_id nutzen
Fullpaths in DB schreiben
Fehler als leere Liste anzeigen
Background-Task ohne Abschlussstatus
SUCCESS ohne AudioAsset bei Audio-Ergebnis
Notification ohne Ziel
neue Sonderlogik statt zentralem Service
```

---

## 17. Roter Faden

Jede neue Funktion muss diese Kette einhalten:

```text
Frontend-Aktion
→ API-Route
→ Service
→ Task/DB
→ AudioAsset als Wahrheit
→ portable lokale Datei
→ Notification
→ UI-Refresh
→ Audit sauber
```

Wenn diese Kette nicht vollständig ist, ist die Änderung nicht fertig.
