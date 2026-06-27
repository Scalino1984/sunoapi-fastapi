# React Frontend

Dieses React-Frontend läuft zusätzlich zum bestehenden Vanilla-Frontend.

## Start Entwicklung

```bash
cd frontend-react
npm install
npm run dev
```

Vite läuft auf:

```text
http://127.0.0.1:5173
```

FastAPI muss parallel laufen:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Produktiv-Build

```bash
cd frontend-react
npm run build
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
