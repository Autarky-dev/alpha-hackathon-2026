"""
backend/app/api/deps.py
-----------------------
Reusable FastAPI dependency injection functions for authentication and RBAC.

1. get_current_user:
   - Extracts the signed JWT from the incoming request's HttpOnly cookie.
   - Validates the token's cryptographic signature and expiration.
   - Loads the corresponding User record from the database.
   - Raises HTTP 401 Unauthorized if missing, expired, invalid, or user not found.

2. require_roles:
   - Dependency factory enforcing Role-Based Access Control (RBAC).
   - Verifies the authenticated user holds one of the specified allowed roles.
   - Raises HTTP 403 Forbidden if the user lacks the required role.
"""

import uuid
from typing import Callable

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User, UserRole


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """
    FastAPI dependency to retrieve and authenticate the current user from the HttpOnly cookie.

    Returns:
        User: The authenticated SQLAlchemy User model instance.

    Raises:
        HTTPException(401): If unauthenticated, token is missing/expired/invalid, or user not found.
    """
    token = request.cookies.get(settings.AUTH_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated: missing authentication cookie",
        )

    try:
        payload = decode_access_token(token)
        user_id_raw = payload.get("sub")
        if not user_id_raw:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token: missing user identity",
            )
        user_id = uuid.UUID(str(user_id_raw))
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired: please log in again",
        )
    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user


def require_roles(*allowed_roles: UserRole) -> Callable[[User], User]:
    """
    Dependency factory that restricts endpoint access to specified UserRole(s).

    Usage:
        @router.get("/admin-only")
        def admin_endpoint(user: User = Depends(require_roles(UserRole.ADMIN))):
            ...

        @router.get("/organizer-area")
        def organizer_endpoint(user: User = Depends(require_roles(UserRole.ORGANIZER, UserRole.ADMIN))):
            ...
    """
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            role_names = [r.value for r in allowed_roles]
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden: requires one of the following roles: {role_names}",
            )
        return current_user

    return role_checker
