"""
backend/app/schemas/auth.py
---------------------------
Pydantic schemas for authentication requests, responses, and user profiles.

Ensures:
  - Input validation for incoming login requests.
  - Strict output filtering — password hashes are NEVER included in response models.
"""

import uuid
from pydantic import BaseModel, ConfigDict, Field

from app.models.user import UserRole


class LoginRequest(BaseModel):
    """Payload for POST /auth/login."""
    username: str = Field(..., min_length=1, max_length=50, description="User's login username")
    password: str = Field(..., min_length=1, description="User's plain-text password")


class UserResponse(BaseModel):
    """
    Public representation of a User.
    Explicitly omits password_hash for security.
    """
    id: uuid.UUID
    username: str
    role: UserRole

    model_config = ConfigDict(from_attributes=True)


class LoginResponse(BaseModel):
    """Response returned upon successful login."""
    message: str = "Login successful"
    user: UserResponse


class MessageResponse(BaseModel):
    """Generic status response message."""
    message: str
