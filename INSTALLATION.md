# Installation Schritt fuer Schritt

Diese Anleitung installiert Suno Song Studio lokal auf Ubuntu/Debian/WSL. Alle Befehle sind zum Kopieren gedacht. Die App besteht aus einem FastAPI-Backend, einer React/Vite-Oberflaeche und lokalen Audio-Werkzeugen.

Persoenliche Wartungs- und Deploy-Skripte gehoeren nicht zur Installation. Dazu zaehlen z. B. VServer-Sync, GitHub-Repo-Manager, Release-Kopierskripte und private Backup-Skripte.

## 1. System vorbereiten

```bash
sudo apt update
sudo apt install -y \
  git curl ca-certificates build-essential pkg-config \
  software-properties-common \
  ffmpeg libsndfile1 libchromaprint-tools \
  sqlite3 lsof rsync
```

## 2. Python 3.11 installieren

Python 3.11 ist fuer WhisperX/Demucs am unproblematischsten. Wenn `python3.11` bereits vorhanden ist, kann dieser Schritt trotzdem ausgefuehrt werden.

```bash
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev
python3.11 --version
```

## 3. Node.js 20 installieren

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
node --version
npm --version
```

## 4. Projekt herunterladen

```bash
cd ~
git clone https://github.com/Scalino1984/sunoapi-fastapi.git
cd sunoapi-fastapi
```

Wenn du das Projekt bereits als ZIP hast:

```bash
cd ~/sunoapi-fastapi
```

## 5. Python-Umgebung erstellen

```bash
python3.11 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

`requirements.txt` enthaelt bewusst auch die Pakete fuer optionale App-Funktionen:

- `whisperx` fuer lokales WhisperX-SRT
- `demucs` fuer Stems und automatische Extend-continueAt-Ermittlung
- `librosa`, `numpy`, `soundfile` fuer Audioanalyse, Beatgrid und Signalwerte
- `pyacoustid` plus `libchromaprint-tools` fuer AcoustID/Copyright-Pruefung
- `replicate` fuer KI-Cover ueber Replicate
- `psycopg[binary]` fuer optionale PostgreSQL-Nutzung oder Migration

## 6. React-Abhaengigkeiten installieren

Die React-Abhaengigkeiten werden ueber den vorhandenen Root-npm-Befehl installiert.

```bash
npm run install:react
```

## 7. Konfiguration anlegen

```bash
cp .env.example .env
```

Oeffne `.env` und setze mindestens diese Werte:

```bash
nano .env
```

Wichtige Pflichtwerte:

```env
SUNO_API_KEY=dein_sunoapi_key
JWT_SECRET_KEY=ersetze_das_durch_einen_langen_zufaelligen_text
PUBLIC_BASE_URL=http://127.0.0.1:8000
AUTH_COOKIE_SECURE=false
SUNO_AUDIO_CACHE_MODE=on_success
```

Optionale API-Keys je nach Funktion:

```env
GROQ_API_KEY=dein_groq_key
OPENAI_API_KEY=dein_openai_key
REPLICATE_API_TOKEN=dein_replicate_token
ACOUSTID_API_KEY=dein_acoustid_key
```

Hinweis: Ohne optionale API-Keys startet die App trotzdem. Die zugehoerigen Funktionen sind dann nicht verfuegbar oder zeigen im Adminbereich "nicht konfiguriert".

## 8. Speicherordner anlegen

```bash
mkdir -p storage/audio storage/covers storage/transcripts storage/backups storage/stems storage/analysis
```

## 9. Datenbank vorbereiten

```bash
source venv/bin/activate
npm run db:upgrade
```

Bei einer frischen SQLite-Installation wird die lokale Datenbank aus `DATABASE_URL` in `.env` verwendet, standardmaessig:

```env
DATABASE_URL=sqlite:///./suno_fastapi_app.db
```

## 10. App starten

Die komplette App wird ueber den Root-npm-Befehl gestartet. Dieser startet FastAPI und React/Vite gemeinsam im Hintergrund. FastAPI nicht direkt mit `uvicorn` starten, sonst laeuft nur das Backend.

```bash
npm run start
```

Danach sind die Dienste erreichbar unter:

```text
React Frontend: http://127.0.0.1:5173
FastAPI API:    http://127.0.0.1:8000
API Docs:       http://127.0.0.1:8000/docs
```

Logs anzeigen:

```bash
npm run logs
```

Stoppen:

```bash
npm run stop
```

Neustarten:

```bash
npm run restart
```

## 11. Funktionstest

```bash
source venv/bin/activate
python -m pytest tests/test_frontend_source_regressions.py
npm run build:react
```

Optionaler Paketcheck fuer lokale Audiofunktionen:

```bash
source venv/bin/activate
python - <<'PY'
import importlib.util
modules = [
    "fastapi",
    "sqlalchemy",
    "httpx",
    "replicate",
    "librosa",
    "numpy",
    "soundfile",
    "acoustid",
    "demucs",
    "whisperx",
]
for name in modules:
    print(f"{name:12} {'OK' if importlib.util.find_spec(name) else 'FEHLT'}")
PY
ffmpeg -version | head -n 1
fpcalc -version
```

## 12. Adminbereich pruefen

Nach dem Start im Frontend einloggen und im Adminbereich pruefen:

- SunoAPI-Key gesetzt
- Groq/OpenAI/Replicate nach Bedarf gesetzt
- Transkriptionsbackend `groq`, `whisperx`, `openai_whisper_api` oder `voxtral`
- Audioanalyse optional aktiviert
- Auto-continueAt optional aktiviert, falls Extend automatisch analysieren soll
- lokale Audio-/Cover-Speicherung aktiviert, damit Inhalte offline verfuegbar bleiben

## 13. Production-Hinweise

Fuer einen echten Server sollten zusaetzlich gesetzt werden:

```env
APP_ENV=production
DEBUG=false
PUBLIC_BASE_URL=https://deine-domain.example
AUTH_COOKIE_SECURE=true
TRUSTED_HOSTS=deine-domain.example
CORS_ALLOW_ORIGINS=https://deine-domain.example
```

Frontend bauen:

```bash
npm run build:react
```

Die persoenlichen Skripte fuer VServer-Sync, GitHub-Verwaltung und private Deployments sind nicht Teil dieser Installationsanleitung. Fuer eine neutrale Installation reichen die oben genannten Befehle.

## Fehlerbehebung

Wenn `npm run start` fehlschlaegt:

```bash
npm run logs
```

Wenn Python-Pakete fehlen:

```bash
source venv/bin/activate
pip install -r requirements.txt
```

Wenn `ffmpeg` fehlt:

```bash
sudo apt install -y ffmpeg
```

Wenn WhisperX/Demucs sehr langsam sind, liegt das meistens an CPU-Betrieb. GPU/CUDA ist optional, muss aber passend zum lokalen System installiert werden.
