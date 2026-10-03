"""
Centralized application settings, loaded from environment variables (and a
.env file) via pydantic-settings. Every other module imports `settings`
instead of calling os.getenv() ad hoc.
"""
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

# The repo keeps a single .env at the project root. This file lives at
# backend/app/config.py, so three ".parent" hops get back to the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_ROOT_ENV_FILE = _REPO_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ROOT_ENV_FILE), extra="ignore")

    # --- Database -----------------------------------------------------------
    # The database is a Supabase-hosted Postgres instance (no local
    # Postgres/Docker involved) -- see README.md for how to get this URL
    # from your Supabase project's "Connect" dialog. Use the *session
    # pooler* (port 5432, username "postgres.<project-ref>"). Not the direct
    # connection: db.<ref>.supabase.co is IPv6-only, so it's unreachable from
    # any network without IPv6. Not the transaction pooler (6543) either:
    # this is a long-running server holding persistent connections, which is
    # what session mode is for.
    #
    # Plain "postgresql://" URL with no driver in the scheme; app code and
    # Alembic each append the driver they actually need (see the two
    # properties below) so this one value drives both.
    #
    # Deliberately has NO default: it embeds the database password, so it
    # must only ever come from .env (gitignored), never from source. Startup
    # fails with "DATABASE_URL Field required" if .env is missing it.
    DATABASE_URL: str
    # Supabase requires SSL on every connection. True by default (correct
    # for Supabase); set DATABASE_SSL=false in .env only if you're pointing
    # this at a local/non-Supabase Postgres that doesn't have SSL set up,
    # so local testing against a plain local instance still works.
    DATABASE_SSL: bool = True

    # --- JWT ------------------------------------------------------------------
    JWT_SECRET: str = "dev-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    # --- Account lockout --------------------------------------------------------
    MAX_FAILED_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_MINUTES: int = 15

    # --- Storage ------------------------------------------------------------------
    STORAGE_ROOT: str = "./storage"
    DEFAULT_STORAGE_QUOTA_BYTES: int = 5 * 1024 * 1024 * 1024  # 5 GiB

    # --- Phase 2: uploads -----------------------------------------------------
    # Files at or under this size go through the simple single-shot /files/upload
    # endpoint (kept from Phase 1); larger files are expected to use the
    # chunked upload flow (/files/upload/init + /chunk + /complete) instead.
    # This is enforced server-side too (single-shot rejects anything bigger)
    # so the split isn't purely a frontend convention.
    SINGLE_SHOT_UPLOAD_MAX_BYTES: int = 5 * 1024 * 1024  # 5 MiB
    UPLOAD_CHUNK_SIZE_HINT_BYTES: int = 2 * 1024 * 1024  # 2 MiB, advisory only

    # Bounded worker pool that all upload-finalization jobs (dedup check,
    # disk write, DB update) are queued through -- see app/workers.py.
    UPLOAD_WORKER_THREADS: int = 4

    # --- Phase 2: recycle bin --------------------------------------------------
    RECYCLE_BIN_RETENTION_DAYS: int = 30

    # --- Phase 2: 2FA -----------------------------------------------------------
    OTP_ISSUER_NAME: str = "CoreVault"
    OTP_PENDING_TOKEN_EXPIRE_MINUTES: int = 5

    # --- Phase 2: sharing --------------------------------------------------------
    # Used only to build a human-shareable URL in ShareLinkOut.url; the API
    # itself never redirects anywhere -- the frontend's /shared/:token route
    # is what actually renders at this origin.
    FRONTEND_URL: str = "http://localhost:5173"
    # Extra browser origins allowed to call the API, comma-separated (e.g. a
    # custom domain alongside the Vercel URL). FRONTEND_URL is always allowed
    # automatically -- see app/main.py.
    CORS_ORIGINS: str = ""

    # --- Phase 3: storage dashboard / stale-file review ---------------------
    # A file the owner hasn't opened (downloaded) or re-uploaded in this many
    # days is offered for deletion in the frontend's stale-file prompt. Set
    # STALE_FILE_DAYS=0 in .env to see the prompt immediately while testing.
    STALE_FILE_DAYS: int = 365
    # Answering "keep" to that prompt silences it for this file for this long.
    STALE_PROMPT_SNOOZE_DAYS: int = 365
    # How many entries GET /analytics/storage returns in its largest-files list.
    ANALYTICS_TOP_FILES: int = 10
    # GET /analytics/forecast fits its growth trend over this many past days.
    FORECAST_WINDOW_DAYS: int = 90

    @property
    def async_database_url(self) -> str:
        """Used by the running FastAPI app (app/database.py)."""
        return self.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

    @property
    def sync_database_url(self) -> str:
        """Used by Alembic (alembic/env.py) and the sync worker pool
        (app/workers.py) -- migrations and upload finalization both run over
        a plain sync connection since neither is async-aware."""
        return self.DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

    @property
    def asyncpg_connect_args(self) -> dict[str, Any]:
        """Passed as create_async_engine(..., connect_args=...). We
        deliberately do NOT pass an explicit `ssl` kwarg here: asyncpg's
        ssl=True forces strict certificate-chain verification via
        ssl.create_default_context(), which fails against Supabase with "self signed certificate in certificate chain" (a
        known asyncpg+Supabase interaction, not a real security issue).
        Supabase requires SSL on every connection regardless, so asyncpg
        auto-negotiates it even with no ssl kwarg specified -- confirmed
        working via a standalone connection test with no connect_args at
        all. Returning an empty dict when DATABASE_SSL is True reflects
        that "SSL is used automatically because Supabase requires it," not
        "SSL is disabled.\""""
        return {}

    @property
    def psycopg2_connect_args(self) -> dict[str, Any]:
        """Passed as create_engine(..., connect_args=...) for the sync
        engines (Alembic, app/workers.py, and the scripts/ that talk to the
        DB directly). psycopg2 takes `sslmode`, not `ssl`."""
        return {"sslmode": "require"} if self.DATABASE_SSL else {}


settings = Settings()
