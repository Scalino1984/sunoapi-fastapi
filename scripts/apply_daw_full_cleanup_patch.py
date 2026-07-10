#!/usr/bin/env python3
"""
Apply the DAW full cleanup patch for sunoapi-fastapi-analyse4.zip.

Scope:
- Replaces frontend-react/src/pages/DawPage.jsx only.
- No database, backend, API, storage, media or dependency changes.
- Verifies the expected analyse4 source hash before replacing the file.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
from datetime import datetime
from pathlib import Path

EXPECTED_ORIGINAL_SHA256 = "f15d2a3e631e971457385244745430b1e6cbae87b4cd22d7e22dcd97d004208a"
PATCHED_SHA256 = "6b8615e480e6eb8e81db0a73d934d5df515d662cb1e37d9c4e1140705110317d"
TARGET_RELATIVE = Path("frontend-react/src/pages/DawPage.jsx")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def find_repo_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / "frontend-react" / "src" / "pages" / "DawPage.jsx").exists():
            return candidate
    raise SystemExit("Projektroot nicht gefunden. Script bitte im sunoapi-fastapi-Projektroot ausführen.")


def main() -> int:
    repo_root = find_repo_root(Path.cwd())
    target = repo_root / TARGET_RELATIVE
    patch_file = Path(__file__).resolve().parents[1] / TARGET_RELATIVE
    if not target.exists():
        raise SystemExit(f"Zieldatei fehlt: {target}")
    if not patch_file.exists():
        raise SystemExit(f"Patch-Datei fehlt: {patch_file}")

    current_hash = sha256(target)
    if current_hash == PATCHED_SHA256:
        print("DAW Full Cleanup ist bereits angewendet.")
        return 0
    if current_hash != EXPECTED_ORIGINAL_SHA256:
        print("ABBRUCH: DawPage.jsx passt nicht zum erwarteten analyse4-Originalstand.", file=sys.stderr)
        print(f"Erwartet: {EXPECTED_ORIGINAL_SHA256}", file=sys.stderr)
        print(f"Gefunden:  {current_hash}", file=sys.stderr)
        print("Bitte zuerst den Projektstand aus sunoapi-fastapi-analyse4.zip verwenden oder die Datei manuell vergleichen.", file=sys.stderr)
        return 2

    patched_hash = sha256(patch_file)
    if patched_hash != PATCHED_SHA256:
        raise SystemExit(f"Patch-Datei ist beschädigt: {patched_hash}")

    backup = target.with_suffix(target.suffix + f".bak-daw-full-cleanup-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(target, backup)
    shutil.copy2(patch_file, target)

    print("DAW Full Cleanup angewendet.")
    print(f"Backup: {backup}")
    print(f"Aktualisiert: {target}")
    print("Nächster Check:")
    print("  cd frontend-react && npm ci --ignore-scripts --no-audit --no-fund && npm run build")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
