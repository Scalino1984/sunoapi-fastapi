from __future__ import annotations

import getpass
import logging
import os
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings, get_settings
from app.database import SessionLocal
from app.models import User
from app.security import get_password_hash

logger = logging.getLogger("songstudio.startup.db_guard")


@dataclass(slots=True)
class InitialAdminCredentials:
    email: str
    password: str
    nickname: str | None = None


def sqlite_database_path(settings: Settings | None = None) -> Path | None:
    settings = settings or get_settings()
    url = make_url(str(settings.database_url or ""))
    if not url.drivername.startswith("sqlite"):
        return None
    if not url.database or url.database == ":memory:":
        return None
    return Path(url.database).expanduser().resolve()


def prepare_initial_database_credentials(settings: Settings | None = None) -> InitialAdminCredentials | None:
    settings = settings or get_settings()
    db_path = sqlite_database_path(settings)
    if db_path is None:
        return None
    if db_path.exists():
        return None

    env_email = str(getattr(settings, "initial_admin_email", "") or os.getenv("INITIAL_ADMIN_EMAIL", "")).strip().lower()
    env_password = str(getattr(settings, "initial_admin_password", "") or os.getenv("INITIAL_ADMIN_PASSWORD", ""))
    env_nickname = str(getattr(settings, "initial_admin_nickname", "") or os.getenv("INITIAL_ADMIN_NICKNAME", "")).strip() or None
    if env_email and env_password:
        logger.warning("SQLite-Datenbank %s existiert nicht. Initialer Admin wird aus INITIAL_ADMIN_EMAIL/INITIAL_ADMIN_PASSWORD angelegt.", db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return InitialAdminCredentials(email=env_email, password=env_password, nickname=env_nickname)

    if not sys.stdin.isatty():
        message = (
            f"SQLite-Datenbank existiert nicht: {db_path}. "
            "Starte die App einmal interaktiv im Terminal oder setze INITIAL_ADMIN_EMAIL und INITIAL_ADMIN_PASSWORD in der .env, "
            "damit der erste Admin-Benutzer sicher angelegt werden kann."
        )
        logger.critical(message)
        raise RuntimeError(message)

    print("\n" + "=" * 76)
    print("Suno Song Studio · Ersteinrichtung")
    print("=" * 76)
    print(f"Die konfigurierte SQLite-Datenbank existiert noch nicht:\n  {db_path}")
    print("Es wird jetzt ein erster lokaler Admin-Benutzer angelegt.")
    print("Der Server startet erst danach weiter.\n")

    email = ""
    while not email or "@" not in email:
        email = input("Admin-E-Mail / Benutzername: ").strip().lower()
        if not email or "@" not in email:
            print("Bitte eine gültige E-Mail-Adresse eingeben.")

    nickname = input("Anzeigename optional: ").strip() or None
    while True:
        password = getpass.getpass("Admin-Passwort: ")
        password_repeat = getpass.getpass("Admin-Passwort wiederholen: ")
        if len(password) < 10:
            print("Passwort muss mindestens 10 Zeichen haben.")
            continue
        if password != password_repeat:
            print("Passwörter stimmen nicht überein.")
            continue
        break

    db_path.parent.mkdir(parents=True, exist_ok=True)
    return InitialAdminCredentials(email=email, password=password, nickname=nickname)


def ensure_jwt_secret(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if getattr(settings, "jwt_secret_key", ""):
        return
    if not sys.stdin.isatty():
        raise RuntimeError("JWT_SECRET_KEY ist nicht konfiguriert. Bitte in der .env setzen.")
    generated = secrets.token_urlsafe(48)
    print("\nWARNUNG: JWT_SECRET_KEY ist nicht gesetzt.")
    print("Trage dauerhaft in deine .env ein:")
    print(f"JWT_SECRET_KEY={generated}\n")
    raise RuntimeError("JWT_SECRET_KEY fehlt. Aus Sicherheitsgründen wurde nur ein Vorschlag erzeugt; bitte .env setzen und erneut starten.")


def create_initial_admin_if_needed(credentials: InitialAdminCredentials | None) -> None:
    if credentials is None:
        return
    db = SessionLocal()
    try:
        existing_count = db.query(User).count()
        if existing_count > 0:
            logger.info("Initialer Admin wird nicht angelegt, weil bereits Benutzer vorhanden sind.")
            return
        user = User(
            email=credentials.email.strip().lower(),
            nickname=(credentials.nickname or credentials.email.split("@", 1)[0]).strip()[:120] or None,
            hashed_password=get_password_hash(credentials.password),
            is_active=True,
            is_admin=True,
        )
        db.add(user)
        db.commit()
        logger.warning("Initialer Admin-Benutzer wurde angelegt: %s", user.email)
        print("\nInitialer Admin wurde angelegt. FastAPI startet jetzt weiter.\n")
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Initialer Admin konnte nicht angelegt werden.")
        raise
    finally:
        db.close()
