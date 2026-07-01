# React Frontend

Dieses React-Frontend läuft zusätzlich zum bestehenden Vanilla-Frontend.

## Start Entwicklung

Empfohlen ist der Start aus dem Projektwurzelverzeichnis, weil dadurch FastAPI und React gemeinsam gestartet werden:

```bash
cd ..
npm run install:react
npm run start
```

Die Dienste laufen auf:

```text
React:   http://127.0.0.1:5173
FastAPI: http://127.0.0.1:8000
```

FastAPI nicht direkt mit `uvicorn` starten, wenn die vollstaendige App genutzt werden soll. `uvicorn` startet nur das Backend; `npm run start` startet Backend und React zusammen.

## Produktiv-Build

```bash
npm run build:react
```

Danach kann FastAPI den Build unter `/react` ausliefern, wenn die vorhandene React-Static-Route aktiv ist.

## Ausbaustand

- moderne Library-Projektansicht
- Song-Detailansicht mit Vorgängen und Varianten
- Mini-Player mit Queue, Vor/Zurück, Loop und Download
- Songtext Studio mit KI Canvas Assist
- Fokus-/Studio-Ansicht
- Vocal-Tag-Einfügung
- Songtext-Archiv mit Bearbeitung
- Styles-Verwaltung
- Playlists
- Adminbereich für Benutzer, KI-Defaults, Profile, Instructions und Vocal Tags
- Systemdiagnose
