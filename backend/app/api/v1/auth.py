"""
backend/app/api/v1/auth.py
--------------------------
FastAPI router for authentication and role verification endpoints.

Endpoints:
  - POST /auth/login              : Authenticate with username/password, set HttpOnly JWT cookie
  - POST /auth/logout             : Clear HttpOnly JWT cookie
  - GET  /auth/me                 : Return current authenticated user profile
  - GET  /auth/test/authenticated : Test endpoint requiring any valid authenticated user
  - GET  /auth/test/student       : Test endpoint restricted to STUDENT role
  - GET  /auth/test/organizer     : Test endpoint restricted to ORGANIZER or ADMIN role
  - GET  /auth/test/admin         : Test endpoint restricted to ADMIN role
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, verify_password
from app.models.user import User, UserRole
from app.schemas.auth import LoginRequest, LoginResponse, MessageResponse, UserResponse
from app.services.audit_service import log_audit

router = APIRouter()


# ---------------------------------------------------------------------------
# 1. Login & Logout
# ---------------------------------------------------------------------------

@router.post(
    "/login",
    response_model=LoginResponse,
    summary="User login",
    description="Authenticates credentials and sets a signed JWT in an HttpOnly cookie.",
)
def login(
    credentials: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> LoginResponse:
    # 1. Lookup user by username
    user = db.query(User).filter(User.username == credentials.username).first()

    # 2. Verify password securely using bcrypt
    # Return generic 401 error to prevent username enumeration
    if not user or not verify_password(credentials.password, user.password_hash):
        log_audit(
            db=db,
            action="LOGIN_FAILED",
            actor_id=user.id if user else None,
            actor_role=user.role.value if user else None,
            details={"attempted_username": credentials.username},
            commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    # 3. Create signed JWT access token containing identity claims
    token_data = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
    }
    access_token = create_access_token(data=token_data)

    # 4. Attach token in HttpOnly, secure (in prod), SameSite cookie
    max_age_seconds = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=access_token,
        max_age=max_age_seconds,
        expires=max_age_seconds,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path="/",
    )

    # 5. Log successful login
    log_audit(
        db=db,
        action="LOGIN",
        actor_id=user.id,
        actor_role=user.role.value,
        details={"username": user.username},
        commit=True,
    )

    return LoginResponse(
        message="Login successful",
        user=UserResponse.model_validate(user),
    )


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="User logout",
    description="Clears the HttpOnly JWT cookie to invalidate the client session.",
)
def logout(response: Response) -> MessageResponse:
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )
    return MessageResponse(message="Logout successful")


# ---------------------------------------------------------------------------
# 2. Profile & RBAC Verification Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/me",
    response_model=UserResponse,
    summary="Current user profile",
    description="Returns the profile of the currently authenticated user.",
)
def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.get(
    "/test/authenticated",
    summary="Test authenticated access",
    description="Accessible to any valid authenticated user regardless of role.",
)
def test_authenticated(current_user: User = Depends(get_current_user)):
    return {
        "status": "ok",
        "message": "Authenticated access granted",
        "username": current_user.username,
        "role": current_user.role.value,
    }


@router.get(
    "/test/student",
    summary="Test student access",
    description="Accessible ONLY to users with the STUDENT role.",
)
def test_student(current_user: User = Depends(require_roles(UserRole.STUDENT))):
    return {
        "status": "ok",
        "message": "Student access granted",
        "username": current_user.username,
        "role": current_user.role.value,
    }


@router.get(
    "/test/organizer",
    summary="Test organizer/admin access",
    description="Accessible to users with ORGANIZER or ADMIN role.",
)
def test_organizer(current_user: User = Depends(require_roles(UserRole.ORGANIZER, UserRole.ADMIN))):
    return {
        "status": "ok",
        "message": "Organizer access granted",
        "username": current_user.username,
        "role": current_user.role.value,
    }


@router.get(
    "/test/admin",
    summary="Test admin access",
    description="Accessible ONLY to users with the ADMIN role.",
)
def test_admin(current_user: User = Depends(require_roles(UserRole.ADMIN))):
    return {
        "status": "ok",
        "message": "Admin access granted",
        "username": current_user.username,
        "role": current_user.role.value,
    }
