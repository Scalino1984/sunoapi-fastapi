#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.database import init_db, SessionLocal  # noqa: E402
from app.models import User  # noqa: E402
from app.security import get_password_hash  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Erstellt oder repariert einen Admin-Benutzer, ohne bestehende App-Daten zu löschen."
    )
    parser.add_argument("--email", required=True, help="E-Mail-Adresse des Admin-Benutzers")
    parser.add_argument("--password", help="Neues Passwort. Wenn leer, wird sicher abgefragt.")
    parser.add_argument("--nickname", default="Admin", help="Anzeigename/Nickname")
    parser.add_argument(
        "--no-reset-password",
        action="store_true",
        help="Passwort eines bestehenden Benutzers nicht ändern, nur Admin/aktiv setzen.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    email = args.email.strip().lower()
    if not email or "@" not in email:
        print("FEHLER: Bitte eine gültige E-Mail-Adresse angeben.", file=sys.stderr)
        return 2

    password = args.password
    if not args.no_reset_password and not password:
        password = getpass.getpass("Neues Admin-Passwort: ")
        password_repeat = getpass.getpass("Passwort wiederholen: ")
        if password != password_repeat:
            print("FEHLER: Passwörter stimmen nicht überein.", file=sys.stderr)
            return 2

    if not args.no_reset_password and (not password or len(password) < 8):
        print("FEHLER: Passwort muss mindestens 8 Zeichen haben.", file=sys.stderr)
        return 2

    init_db()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user:
            user.is_active = True
            user.is_admin = True
            if args.nickname and not user.nickname:
                user.nickname = args.nickname.strip()[:120]
            if not args.no_reset_password:
                user.hashed_password = get_password_hash(password)
            action = "repariert"
        else:
            user = User(
                email=email,
                nickname=args.nickname.strip()[:120] if args.nickname else None,
                hashed_password=get_password_hash(password),
                is_active=True,
                is_admin=True,
            )
            db.add(user)
            action = "erstellt"

        db.commit()
        db.refresh(user)
        print(f"OK: Admin-Benutzer wurde {action}: {user.email} (ID {user.id})")
        print("Hinweis: Es wurden keine Songs, Projekte oder Audio-Dateien gelöscht.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
