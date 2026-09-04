"""Authentication, abstracted.

The brief allows a demo user for hackathon simplicity but asks that the
architecture be ready for real auth. So every route depends on
`get_current_user`, never on a hard-coded id: swapping the resolver for a JWT or
session verifier is a change to this file alone.

`DemoUserResolver` still honours an `X-User-Email` header, so multi-user
behaviour — two people with the same watchlist seeing *different* attention
scores because they last reviewed at different times — can be demonstrated
without building a login screen.
"""

from __future__ import annotations

import abc

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User


class UserResolver(abc.ABC):
    @abc.abstractmethod
    def resolve(self, db: Session, *, email: str | None, token: str | None) -> User: ...


class DemoUserResolver(UserResolver):
    """Trusts the caller. Correct for a local demo, never for production."""

    def resolve(self, db: Session, *, email: str | None, token: str | None) -> User:
        email = (email or settings.demo_user_email).strip().lower()
        user = db.scalars(select(User).where(User.email == email)).first()
        if user is None:
            user = User(email=email, display_name=_display_name_for(email))
            db.add(user)
            db.commit()
            db.refresh(user)
        return user


class BearerTokenResolver(UserResolver):  # pragma: no cover - integration point
    """Placeholder for real auth.

    Kept deliberately unimplemented rather than half-implemented: a fake token
    check that always passes would be worse than an honest boundary. Wire a JWT
    library in here and set `AUTH_MODE=bearer`.
    """

    def resolve(self, db: Session, *, email: str | None, token: str | None) -> User:
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Bearer authentication is not configured in this deployment",
        )


def _display_name_for(email: str) -> str:
    local = email.split("@")[0].replace(".", " ").replace("_", " ")
    return local.title() or "Analyst"


def get_user_resolver() -> UserResolver:
    return DemoUserResolver()


def get_current_user(
    db: Session = Depends(get_db),
    x_user_email: str | None = Header(default=None, alias="X-User-Email"),
    authorization: str | None = Header(default=None),
) -> User:
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    return get_user_resolver().resolve(db, email=x_user_email, token=token)
