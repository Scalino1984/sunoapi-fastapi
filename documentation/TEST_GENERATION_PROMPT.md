# Prompt Fuer Testgenerierung

Nutze diese Anweisung, wenn eine KI aus einem aktuellen ZIP-Archiv dieses Projekts vollstaendige automatisierte Tests erzeugen soll.

## Aktuelles Analyse-Archiv

Verwende als Projektquelle das Archiv `sunoapi-fastapi-ai-test-20260624_084814.zip`.

Wichtig zum Archiv:

- Echte Dateien aus `storage/` sind nicht enthalten.
- Stattdessen enthaelt das Archiv die Textdatei `documentation/storage_snapshot.txt`.
- Diese Textdatei dokumentiert vorhandene Storage-Inhalte als Inventar mit Dateipfaden, Groessen, Hashes und bei Textdateien mit Inhaltsauszuegen bzw. Volltext.
- Die Zusammenstellung des Archivs ist in `documentation/ZIP_ARCHIVE_MANIFEST.md` beschrieben.
- Nutze diese Textdateien als Kontext, aber fuehre daraus keine echten Audio-, Suno-, Groq-, OpenAI- oder sonstigen Provider-Aufrufe aus.

## Ziel

Erstelle im Ordner `tests/` eine moeglichst vollstaendige Test-Suite fuer alle relevanten Funktionen, Routen, Services und Hilfsfunktionen des Projekts.

Wichtig:

- Keine echten Suno-API-Aufrufe.
- Keine echten externen API-Aufrufe.
- Keine kostspieligen Live-Requests.
- Keine Tests schreiben, die Geld kosten oder unnoetig lange laufen.
- Simulierte Testdaten, Mocks, Fakes und Monkeypatching aktiv verwenden.

## Arbeitsauftrag

1. Erfass zuerst die Struktur des Projekts vollstaendig.
2. Identifiziere alle zentralen Funktionsbereiche:
   - FastAPI-Routen
   - Services
   - Modelle
   - Hilfsfunktionen
   - Import-/Exportpfade
   - Library-/Audio-/SRT-/Waveform-/Cover-/Playlist-/Task-/Auth-Logik
3. Lege fuer jeden Bereich passende Tests an oder ergaenze bestehende Tests.
4. Nutze fuer jeden Test nur lokale, deterministische Daten.
5. Erzeuge Tests so, dass sie ohne Netzwerk, ohne echte Suno-Requests und ohne externe Anbieter lauffaehig sind.

## Harte Regeln

- Verwende keine echten HTTP-Calls nach aussen.
- Verwende keine echten Suno-Requests.
- Verwende keine echten OpenAI-, Groq-, Whisper- oder sonstigen Live-Provider-Aufrufe.
- Verwende keine echten Zahlungs- oder Abrechnungsrelevanten Aktionen.
- Verwende keine realen Produktionsdaten.
- Vermeide Side Effects ausserhalb von Temp-Verzeichnissen oder Testdatenbanken.
- Aendere Produktionscode nur dann, wenn es fuer saubere Testbarkeit unvermeidbar ist, und dann nur minimal.

## Erwartete Testtechnik

Nutze wo passend:

- `pytest`
- `monkeypatch`
- `unittest.mock`
- `fastapi.testclient.TestClient`
- temporäre SQLite-Datenbanken
- temporäre Dateien in `tmp_path`
- gefakte Audio-Dateien
- simulierte SRT-/Waveform-/Metadata-Daten
- Stub-Antworten fuer externe Dienste
- in-memory oder temporäre Testfixtures

## Was abgedeckt werden soll

Schreibe Tests, die mindestens diese Bereiche systematisch abdecken:

- Authentifizierung und Autorisierung
- Library-Ansichten und Library-Filterlogik
- Importpfade
- Exportpfade
- Delete-/Restore-Verhalten
- Bulk-Aktionen
- SRT-Erzeugung und SRT-Editor-Logik
- Waveform- und Struktursegment-Logik
- Cover-Handling und Cover-Upload
- Audio-Konvertierung und lokale Datei-Logik
- Task-/Status-Handling
- Playlist-Logik
- Hilfsfunktionen mit Verhaltensrelevanz

## Qualitaetsanforderungen

- Teste Happy Paths und wichtige Fehlerfaelle.
- Teste Randfaelle, bei denen Daten fehlen, leer sind oder inkonsistent sind.
- Teste Regressionen, die durch bestehende Bugfixes entstehen koennten.
- Halte die Tests deterministisch.
- Vermeide fragile Tests, die nur auf exakte UI-Details oder zufaellige Daten reagieren.
- Bevorzuge fachliche Verhaltensaussagen statt Implementation-Details.

## Logdateien

Waehrend der Analyse und Testgenerierung sollen spezielle Logdateien geschrieben werden, die Fehler, Unsicherheiten und offene Testluecken festhalten.

Diese Logs sollen spaeter von einer KI zum Fixen und zur gezielten Nacharbeit verwendet werden koennen.

Anforderungen an die Logs:

- schreibe sie lokal in einen klar benannten Ordner im Projekt, zum Beispiel `documentation/test-audit-logs/` oder einen aehnlichen nachvollziehbaren Pfad,
- dokumentiere pro Problemstelle den betroffenen Bereich, die beobachtete Ursache, den aktuellen Teststatus und die naechsten Fix-Hinweise,
- halte Fehlermeldungen, Stacktraces oder relevante Auszuege moeglichst konkret fest,
- unterscheide zwischen echten Fehlern, vermuteten Risiken und bewusst offenen Luecken,
- vermeide unnoetig lange Protokolle, aber halte genug Kontext fest, damit eine KI den Fix spaeter reproduzieren kann.

## Fuer APIs und Provider

Wenn eine Funktion normalerweise einen externen Provider aufruft, dann:

- ersetze den Provider-Aufruf durch ein Stub-Objekt oder Monkeypatch,
- liefere realistische, aber lokale Beispielantworten,
- simuliere Fehlerfaelle ebenso wie Erfolg,
- pruefe, dass Fehler sauber behandelt werden.

## Fuer Audio und Medien

Wenn Audio, Waveform oder SRT beteiligt sind:

- nutze kleine, lokale Beispieldateien oder generierte Testdateien,
- mocke teure oder externe Verarbeitung, wenn noetig,
- pruefe strukturierte Ausgaben statt grosser Binärdateien,
- validiere Zeitachsen, Segmentlogik und gespeicherte Metadaten.

## Fuer die Ausgabe

Gib am Ende nur das Ergebnis der Testarbeit aus:

- welche Testdateien neu erstellt oder ergaenzt wurden,
- welche Bereiche abgedeckt sind,
- ob noch bekannte Luecken bleiben,
- welche Tests ausgefuehrt wurden.

Wenn Produktionscode angepasst werden musste, dokumentiere:

- warum,
- was genau geaendert wurde,
- wie dadurch die Tests moeglich wurden.

## Prioritaet

Wenn nicht alles auf einmal testbar ist, dann priorisiere:

1. Sicherheitskritische oder regressionsgefaehrdete Pfade.
2. Extern kostspielige oder schwer ersetzbare Integrationen.
3. Kernfunktionen der Library und Audio-Verarbeitung.
4. Hilfsfunktionen und reine UI-nahe Logik.

## Abschlusskriterium

Die Arbeit ist erst fertig, wenn der Testbestand moeglichst die gesamte fachliche Funktionalitaet des Projekts gegen Regressionen absichert, ohne echte Suno- oder andere externe API-Aufrufe auszufuehren.
