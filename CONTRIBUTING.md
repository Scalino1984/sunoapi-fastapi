# Contributing

Thanks for considering a contribution.

This project is a self-hosted production workspace for AI music workflows. Changes should preserve local-first behavior, avoid hidden provider calls and keep user data under explicit control.

## Development Setup

Follow [INSTALLATION.md](INSTALLATION.md) for the full setup.

For a basic local check:

```bash
source venv/bin/activate
python -m pytest
npm run build:react
```

Do not run real SunoAPI.org, transcription, cover or AI provider workflows in automated tests. Use fixtures, mocks or local-only test data.

## Pull Request Guidelines

- Keep changes focused.
- Do not commit `.env`, `.env.*`, databases, `storage/`, `node_modules/`, virtual environments or generated media.
- Preserve existing workflow contracts unless the PR explicitly documents a migration.
- Add or update tests for backend routes, payload contracts or frontend regressions when behavior changes.
- For UI changes, include screenshots when practical.

## Code Style

- Backend: prefer explicit service functions and SQLAlchemy models already used by the app.
- Frontend: follow the existing React component and i18n patterns.
- Keep public scripts generic. Personal deployment, sync and server maintenance helpers should stay local and ignored.

## Provider Safety

Any feature that can spend money through external APIs must be explicit in the UI, visible in status logs and testable without real provider calls.
