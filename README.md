# Suno Song Studio

Self-hosted AI music production suite for SunoAPI.org workflows, local archiving, lyrics, covers, transcription, stems, playlists and production-ready song management.

Installation: see [INSTALLATION.md](INSTALLATION.md) for a copy-and-paste setup guide including WhisperX, Demucs, ffmpeg and all Python requirements.

![Suno Song Studio dashboard](documentation/images/home-dashboard.png)

## Why This Exists

Suno Song Studio is built for creators who do not want their music workflow to disappear inside temporary provider links, scattered downloads and manual spreadsheets.

It turns AI music generation into a local-first production workspace:

- generate songs through SunoAPI.org
- import existing Suno tasks and public Suno songs
- cache audio, covers, lyrics, metadata and production assets locally
- manage song variants like real projects
- create SRT subtitles, stems, WAV exports, covers and analysis reports
- keep every important task visible through a dedicated status system

The result is a private studio dashboard for AI-assisted music production, designed to keep your library usable even when remote URLs expire.

## Highlights

### End-to-End Music Generation

![Music generator expert form](documentation/images/music-generator-expert-form.png)

Create new tracks with full access to production controls:

- Generate Music
- Generate Lyrics
- Extend
- Upload and Extend Audio
- Upload and Cover Song
- Add Vocals
- Add Instrumental
- Generate Sounds
- Stem Separation
- Convert to WAV
- Generate MIDI from Audio
- Create Music Video
- Cover images from existing tasks
- Replace Music Section
- Persona creation
- Style improvement
- Mashup workflows

Advanced Suno options such as negative tags, vocal gender, style weight, weirdness, audio weight, persona ID and persona model are carried through supported workflows and stored locally for later inspection.

### Local-First Library

![Library grouped list view](documentation/images/library-grouped-list-view.png)

The Library is the central workspace for finished tracks, variants and follow-up production.

- grouped project view for songs and variants
- title list view for direct access to every generated audio
- cover gallery view for visual browsing
- local audio and cover status badges
- favorites and multi-select actions
- local backup checks and metadata repair
- single central search from the header
- three-dot menus with all relevant follow-up actions

### Song Details Built for Production

![Library song details production workflow](documentation/images/library-song-details-production-workflow.png)

Each song detail page collects the information that usually gets lost:

- generated variants
- original task IDs and audio IDs
- used options and advanced Suno settings
- prompt, lyrics and style text
- local audio, cover and waveform status
- SRT subtitles and segment tools
- stems, WAV conversion and ZIP exports
- local audio analysis reports
- cover upload, cover generation, preview and download

### AI Style Engine

![Music style engine results](documentation/images/music-style-engine-results.png)

The integrated style engine turns lyrics and intent into structured Suno-ready production prompts.

It can generate:

- style prompts
- negative tags
- vocal and section tags
- risk and fit scoring
- multiple creative variants
- directly reusable style packages

The goal is not random prompt decoration. It is repeatable, production-oriented prompting for songs that need a clear identity.

### Songtext Studio

![Songtext Studio canvas](documentation/images/songtext-studio-canvas.png)

Write, revise and structure lyrics directly inside the app.

- canvas-based lyric writing
- local AI help for hooks, verses, structure and phrasing
- vocal tags and section markers
- direct transfer into music generation
- saved lyric library
- Suno-compatible formatting helpers

### Status, Imports and Backfills

![Status tasks and Suno imports](documentation/images/status-tasks-and-suno-imports.png)

Long-running AI tasks need visibility. The Status page keeps production transparent.

- live task overview
- task details with request, response and result payloads
- SunoAPI.org task import
- public Suno song import
- batch imports
- optional SRT and stem generation after import
- cache and metadata backfills
- safe task cancellation and cleanup

### Mini-DAW and Waveform Editing

![Mini DAW waveform editor](documentation/images/mini-daw-waveform-editor.png)

The Mini-DAW gives quick access to practical audio edits without leaving the app.

- waveform and section display
- trim and fade controls
- marker and version workflows
- save edited audio as a new library version
- keep the original file untouched

### Admin Controls for Real Workflows

![Admin AI assistant and audio analysis](documentation/images/admin-ai-assistant-and-audio-analysis.png)

The Admin area centralizes the behavior that should not be hard-coded.

- AI provider and model configuration
- reusable AI profiles and instruction files
- 1-click SRT settings
- optional automatic Extend `continueAt` analysis
- optional local audio analysis
- optional KI-Library-Tags
- vocal tag management
- user and profile controls

## Screenshot Gallery

The screenshots below use development/demo data and show the current product areas.

| Area | Preview |
| --- | --- |
| Home dashboard | ![Home dashboard](documentation/images/home-dashboard.png) |
| Music operation selector | ![Music operation selector](documentation/images/music-operation-selector.png) |
| Music generator expert form | ![Music generator expert form](documentation/images/music-generator-expert-form.png) |
| Music style engine empty state | ![Music style engine empty state](documentation/images/music-style-engine-empty-state.png) |
| Music style engine results | ![Music style engine results](documentation/images/music-style-engine-results.png) |
| Music style applied to generator | ![Music style applied to generator](documentation/images/music-style-engine-applied-style.png) |
| Songtext tag preview modal | ![Songtext tag preview modal](documentation/images/songtext-tags-preview-modal.png) |
| Library grouped list view | ![Library grouped list view](documentation/images/library-grouped-list-view.png) |
| Library title list view | ![Library title list view](documentation/images/library-title-list-view.png) |
| Library cover gallery view | ![Library cover gallery view](documentation/images/library-cover-gallery-view.png) |
| Library song details and production workflow | ![Library song details production workflow](documentation/images/library-song-details-production-workflow.png) |
| Songtext Studio canvas | ![Songtext Studio canvas](documentation/images/songtext-studio-canvas.png) |
| Mini-DAW waveform editor | ![Mini DAW waveform editor](documentation/images/mini-daw-waveform-editor.png) |
| Status, tasks and Suno imports | ![Status tasks and Suno imports](documentation/images/status-tasks-and-suno-imports.png) |
| System maintenance and backup | ![System maintenance and backup](documentation/images/system-maintenance-and-backup.png) |
| Admin AI assistant and audio analysis | ![Admin AI assistant and audio analysis](documentation/images/admin-ai-assistant-and-audio-analysis.png) |
| Admin vocal tags management | ![Admin vocal tags management](documentation/images/admin-vocal-tags-management.png) |
| Admin users management | ![Admin users management](documentation/images/admin-users-management.png) |
| Profile and voice management | ![Profile and voice management](documentation/images/profile-and-voice-management.png) |
| Help and shortcuts page | ![Help and shortcuts page](documentation/images/help-and-shortcuts-page.png) |

## Core Workflows

### 1. Generate

Start with lyrics, a prompt, a saved style or an AI-generated style package. Choose the Suno model, set advanced controls and generate through SunoAPI.org.

### 2. Capture

Successful generations are imported into the local database. Depending on configuration, audio files, covers, lyrics, payloads and metadata are stored locally.

### 3. Curate

Review variants in Library views, mark favorites, compare versions, rename local titles and organize songs into playlists.

### 4. Produce

Generate SRT files, stems, WAV exports, cover images, local audio analysis reports or edited Mini-DAW versions.

### 5. Preserve

Use local backup, content checks and metadata repair so the catalog remains usable outside temporary provider URLs.

## Technical Stack

- Backend: FastAPI, SQLAlchemy, Pydantic, Alembic
- Frontend: React, Vite, lucide-react
- Database: SQLite by default through `DATABASE_URL`
- Audio metadata: Mutagen
- External providers: SunoAPI.org, optional OpenAI/OpenRouter/Gemini/Groq/Mistral/Voxtral/Replicate depending on enabled features
- Deployment: self-hosted Python app with React build publishing scripts

## Quick Start

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env

npm run install:react
npm run build:react

npm run start
```

Open:

```text
React:   http://127.0.0.1:5173
FastAPI: http://127.0.0.1:8000
```

The full app is started through the root npm helper. A direct `uvicorn` start only launches FastAPI, not the React frontend.

For local control:

```bash
npm run stop
npm run restart
```

## Important Configuration

At minimum, configure:

```env
SUNO_API_KEY=...
DATABASE_URL=sqlite:///./suno_fastapi_app.db
PUBLIC_BASE_URL=http://localhost:8000
JWT_SECRET_KEY=change-this-to-a-long-random-secret
```

For local audio and cover preservation:

```env
SUNO_AUDIO_CACHE_MODE=on_success
SUNO_AUDIO_STORAGE_DIR=storage/audio
SUNO_COVER_CACHE_ENABLED=true
SUNO_COVER_STORAGE_DIR=storage/covers
```

Optional AI providers and transcription services are configured in `.env.example`.

## Self-Hosting Notes

This project is designed for private, self-hosted use.

Before publishing or deploying:

- do not commit `.env`, `.env.server`, databases, `storage/`, `node_modules/`, `venv/` or `.venv/`
- review `.env.example` and document your own required provider keys
- use the included publishing/deploy scripts only after checking their target paths
- remember that real SunoAPI, transcription, cover and AI calls can create provider costs

## What Makes It Different

Suno Song Studio is not just a button for generation. It is a production archive around generation:

- task payloads stay inspectable
- generated audio can become local assets
- covers can be replaced, generated, opened and downloaded
- SRT timing and song sections become part of playback
- library search works across useful metadata
- follow-up actions stay attached to the actual track variant
- status reporting is built into the workflow instead of hidden in logs

## Disclaimer

This project is an independent self-hosted application and is not affiliated with Suno. SunoAPI.org, Suno, OpenAI, Groq, Replicate and other provider names belong to their respective owners. Use external services according to their terms and pricing.

## License

This project is licensed under the GNU Affero General Public License v3.0. See [LICENSE](LICENSE).
