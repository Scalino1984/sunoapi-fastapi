from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)
# Swagger UI kann mit OAuth2 Password Flow direkt einloggen.
# Das ist nur eine zusätzliche Dokumentations-/Client-Auth-Variante;
# zur Laufzeit wird weiterhin derselbe Bearer-JWT akzeptiert.
docs_oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/auth/docs-token",
    scheme_name="EmailPasswordLogin",
    auto_error=False,
)


def _extract_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
    oauth_token: str | None = None,
) -> str | None:
    if credentials and credentials.scheme.lower() == "bearer" and credentials.credentials:
        return credentials.credentials

    if oauth_token:
        return oauth_token.strip()

    cookie_value = request.cookies.get("access_token")
    if cookie_value:
        if cookie_value.startswith("Bearer "):
            return cookie_value.split(" ", 1)[1].strip()
        return cookie_value.strip()

    return None


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    oauth_token: str | None = Depends(docs_oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    token = _extract_token(request, credentials, oauth_token)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(token)
        subject = payload.get("sub")
        token_type = payload.get("type")
        if not subject or token_type != "access":
            raise JWTError("Invalid token payload")
        user_id = int(subject)
    except (JWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive.")
    return current_user


def get_current_admin_user(current_user: User = Depends(get_current_active_user)) -> User:
    if not getattr(current_user, "is_admin", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required.")
    return current_user
