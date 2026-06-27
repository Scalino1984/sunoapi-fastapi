from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.auth import get_current_active_user
from app.config import get_settings
from app.database import get_db
from app.models import User
from app.schemas import Token, UserCreate, UserLogin, UserRead, UserPasswordChange, UserProfileUpdate
from app.security import create_access_token, get_password_hash, verify_password
from app.services.rate_limit_service import client_key, rate_limiter

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_auth_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
    )


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register_user(payload: UserCreate, request: Request, db: Session = Depends(get_db)) -> User:
    settings = get_settings()
    rate_limiter.check(
        client_key(request, "auth-register"),
        limit=settings.auth_rate_limit_register_requests,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )

    if not settings.registration_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is currently disabled.",
        )

    normalized_email = payload.email.strip().lower()
    existing_user = db.query(User).filter(User.email == normalized_email).first()
    if existing_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Registration failed.")

    first_user = db.query(User).count() == 0
    user = User(
        email=normalized_email,
        nickname=(payload.nickname or normalized_email.split("@", 1)[0]).strip()[:120] or None,
        hashed_password=get_password_hash(payload.password),
        is_active=True,
        is_admin=first_user,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _issue_login_token(email: str, password: str, request: Request, response: Response, db: Session) -> Token:
    settings = get_settings()
    rate_limiter.check(
        client_key(request, "auth-login"),
        limit=settings.auth_rate_limit_login_requests,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )

    normalized_email = email.strip().lower()
    user = db.query(User).filter(User.email == normalized_email).first()
    if not user or not user.is_active or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")

    expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(str(user.id), expires_delta=expires_delta)
    _set_auth_cookie(response, access_token)
    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/login", response_model=Token)
def login_user(payload: UserLogin, request: Request, response: Response, db: Session = Depends(get_db)) -> Token:
    return _issue_login_token(payload.email, payload.password, request, response, db)


@router.post(
    "/docs-token",
    response_model=Token,
    summary="Swagger-/Docs-Login mit E-Mail und Passwort",
    description=(
        "OAuth2-kompatibler Login nur für Swagger UI /docs. "
        "Im Feld username bitte die E-Mail-Adresse eintragen. "
        "Der zurückgegebene JWT ist derselbe Bearer-Token wie bei /auth/login."
    ),
)
def docs_login_token(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    return _issue_login_token(form_data.username, form_data.password, request, response, db)


@router.get("/me", response_model=UserRead)
def read_me(current_user: User = Depends(get_current_active_user)) -> User:
    return current_user


@router.put("/profile", response_model=UserRead)
def update_profile(
    payload: UserProfileUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> User:
    nickname = (payload.nickname or "").strip()
    current_user.nickname = nickname[:120] if nickname else None
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/change-password")
def change_password(
    payload: UserPasswordChange,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password change failed.")
    current_user.hashed_password = get_password_hash(payload.new_password)
    db.add(current_user)
    db.commit()
    return {"ok": True}


@router.post("/refresh", response_model=Token)
def refresh_token(response: Response, current_user: User = Depends(get_current_active_user)) -> Token:
    settings = get_settings()
    expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(str(current_user.id), expires_delta=expires_delta)
    _set_auth_cookie(response, access_token)
    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    settings = get_settings()
    response.delete_cookie(key=settings.auth_cookie_name, path="/")
    return {"ok": True}
