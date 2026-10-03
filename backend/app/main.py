"""FastAPI application entrypoint. Run with:
    uvicorn app.main:app --reload --port 8000
(from inside backend/, with the venv active -- see README.md)."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import admin, analytics, auth, files, folders, permissions, recycle_bin, shared, system

app = FastAPI(title="CoreVault API", version="0.3.0")

# Browsers may call this API from: the local Vite dev server (port 5173),
# the deployed frontend (FRONTEND_URL -- the same setting share links are
# built from, so a deployment only sets it once), and anything extra listed
# comma-separated in CORS_ORIGINS (e.g. a custom domain).
_cors_origins = {"http://localhost:5173", "http://127.0.0.1:5173", settings.FRONTEND_URL.rstrip("/")}
_cors_origins.update(o.strip().rstrip("/") for o in settings.CORS_ORIGINS.split(",") if o.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(_cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(folders.router)
app.include_router(files.router)
app.include_router(permissions.router)
app.include_router(recycle_bin.router)
app.include_router(shared.router)
app.include_router(system.router)
app.include_router(analytics.router)
app.include_router(admin.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
