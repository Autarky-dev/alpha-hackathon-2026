"""
backend/app/core/config.py
--------------------------
Application settings loaded from environment variables (via .env).

We use pydantic-settings so every variable is:
  - Declared with its expected Python type.
  - Validated at startup — the app refuses to start if something is missing.
  - Never hard-coded anywhere in the codebase.

Why pydantic-settings instead of os.getenv()?
  os.getenv() silently returns None for missing values.
  pydantic-settings raises a clear error at import time, so you catch
  misconfiguration before the first request hits the database.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Resolve the .env file path relative to THIS file's location, not relative
# to whatever the current working directory happens to be when the app starts.
#
# __file__  = .../backend/app/core/config.py
# .parent   = .../backend/app/core/
# .parent   = .../backend/app/
# .parent   = .../backend/
# .parent   = .../  (project root — where .env lives)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """
    Every field here maps to an environment variable with the same name
    (case-insensitive). pydantic-settings reads them from the OS environment
    or from the .env file at the project root, whichever is present.
    """

    # --- Database credentials ---
    # Stored as separate fields — never assembled into a URL that would
    # appear in a repr(), log line, or error message.
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str
    DB_USER: str
    DB_PASSWORD: str

    # --- Application mode ---
    APP_ENV: str = "development"

    # --- Authentication & JWT ---
    # Secret key used to sign and verify JWT tokens.
    # Must be at least 32 characters long to satisfy RFC 7518 / PyJWT HMAC requirements.
    # Override in .env with a secure random string in production.
    JWT_SECRET_KEY: str = "seatlock-secret-key-at-least-32-characters-long-2026-secure"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Cookie configuration
    AUTH_COOKIE_NAME: str = "seatlock_access_token"
    # False allows HTTP during local development; set to True in production for HTTPS
    AUTH_COOKIE_SECURE: bool = False
    AUTH_COOKIE_SAMESITE: str = "lax"

    # --- CORS configuration for Frontend Integration ---
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]

    # --- Seed Test Users ---
    # Configurable through environment variables; never hardcoded in logic
    SEED_STUDENT_USERNAME: str = "student_user"
    SEED_STUDENT_PASSWORD: str = "StudentPass123!"

    SEED_ORGANIZER_USERNAME: str = "organizer_user"
    SEED_ORGANIZER_PASSWORD: str = "OrganizerPass123!"

    SEED_ADMIN_USERNAME: str = "admin_user"
    SEED_ADMIN_PASSWORD: str = "AdminPass123!"

    # _ENV_FILE is an absolute path, so pydantic-settings finds .env correctly
    # regardless of which directory the process was launched from.
    # extra="ignore" means unknown variables in .env are silently skipped
    # instead of raising a validation error.
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def database_url(self) -> str:
        """
        Assembles the SQLAlchemy connection URL from individual fields.

        Format:  postgresql+psycopg://user:password@host:port/dbname
          - "postgresql+psycopg" tells SQLAlchemy to use psycopg (v3).
          - The password is percent-encoded via urllib.parse.quote_plus so that
            special characters (e.g. @, #, %) inside the password are not
            misinterpreted as URL delimiters.
          - This property is computed on demand — it is never stored as an
            attribute, so it won't accidentally appear in a Settings repr().
        """
        from urllib.parse import quote_plus
        encoded_password = quote_plus(self.DB_PASSWORD)
        return (
            f"postgresql+psycopg://{self.DB_USER}:{encoded_password}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )


# ---------------------------------------------------------------------------
# Single, module-level instance.
# Import this object wherever settings are needed:
#   from app.core.config import settings
# ---------------------------------------------------------------------------
settings = Settings()
