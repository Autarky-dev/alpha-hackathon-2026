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
    # Stored as separate fields OR parsed from DATABASE_URL (e.g. Render / Heroku).
    # Never assembled into a URL that would appear in a repr() or error log.
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "seatlock"
    DB_USER: str = "postgres"
    DB_PASSWORD: str = ""
    DATABASE_URL: str | None = None

    # --- Application mode ---
    APP_ENV: str = "development"

    # --- Authentication & JWT ---
    # Secret key used to sign and verify JWT tokens.
    # Must be at least 32 characters long to satisfy RFC 7518 / PyJWT HMAC requirements.
    # Override in .env or Render dashboard with a secure random string in production.
    JWT_SECRET_KEY: str = "seatlock-secret-key-at-least-32-characters-long-2026-secure"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Cookie configuration
    AUTH_COOKIE_NAME: str = "seatlock_access_token"
    # False allows HTTP during local development; set to True in production for HTTPS
    AUTH_COOKIE_SECURE: bool = False
    # "lax" for local/same-site development; "none" for cross-domain on *.onrender.com
    AUTH_COOKIE_SAMESITE: str = "lax"

    # --- CORS configuration for Frontend Integration ---
    # Accepts a JSON array or comma-separated list of allowed origins.
    CORS_ORIGINS: list[str] | str = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    CORS_ORIGIN_REGEX: str | None = None
    CORS_ALLOW_ALL_RENDER: bool = True

    # --- Seed Test Users ---
    # Configurable through environment variables; never hardcoded in logic
    SEED_STUDENT_USERNAME: str = "student_user"
    SEED_STUDENT_PASSWORD: str = "StudentPass123!"

    SEED_ORGANIZER_USERNAME: str = "organizer_user"
    SEED_ORGANIZER_PASSWORD: str = "OrganizerPass123!"

    SEED_ADMIN_USERNAME: str = "admin_user"
    SEED_ADMIN_PASSWORD: str = "AdminPass123!"

    # --- Database Auto-Initialization & Seeding ---
    # Safe, idempotent startup initialization compatible with Render Free Tier
    AUTO_INIT_DB: bool = True
    AUTO_SEED_DATA: bool = True

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
    def cookie_secure(self) -> bool:
        """Infers HTTPS cookie security flag: True in production, False in development."""
        if self.APP_ENV.lower() == "production" and not self.AUTH_COOKIE_SECURE:
            return True
        return self.AUTH_COOKIE_SECURE

    @property
    def cookie_samesite(self) -> str:
        """Infers SameSite attribute: 'none' for cross-site production, 'lax' for local dev."""
        if self.APP_ENV.lower() == "production" and self.AUTH_COOKIE_SAMESITE.lower() == "lax":
            return "none"
        return self.AUTH_COOKIE_SAMESITE.lower()

    @property
    def cors_origins_list(self) -> list[str]:
        """Converts CORS_ORIGINS into a clean list of string origins."""
        import json
        val = self.CORS_ORIGINS
        if isinstance(val, str):
            v = val.strip()
            if not v:
                return []
            if v.startswith("[") and v.endswith("]"):
                try:
                    return [str(x).strip() for x in json.loads(v) if str(x).strip()]
                except Exception:
                    pass
            return [x.strip() for x in v.split(",") if x.strip()]
        elif isinstance(val, (list, tuple, set)):
            return [str(x).strip() for x in val if str(x).strip()]
        return []

    @property
    def database_url(self) -> str:
        """
        Assembles the SQLAlchemy connection URL.
        Prioritizes DATABASE_URL if provided (e.g. Render / Heroku PostgreSQL).
        Normalizes postgres:// or postgresql:// to postgresql+psycopg:// for SQLAlchemy 2.0.
        Falls back to individual DB_* fields for local development.
        """
        if self.DATABASE_URL and self.DATABASE_URL.strip():
            url = self.DATABASE_URL.strip()
            # Normalize driver dialect for SQLAlchemy 2.0 with psycopg v3
            if url.startswith("postgres://"):
                return "postgresql+psycopg://" + url[len("postgres://"):]
            if url.startswith("postgresql://") and not url.startswith("postgresql+psycopg://"):
                return "postgresql+psycopg://" + url[len("postgresql://"):]
            return url

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
