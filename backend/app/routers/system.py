"""
Diagnostic endpoint: cross-platform disk usage via the stdlib's
shutil.disk_usage(), NOT os.statvfs() (Unix-only) -- this is what makes it
report correctly on Windows as well as macOS/Linux with zero platform
branching. Full quota cross-checking against this value is Phase 2; for now
this just exposes the raw numbers.
"""
import shutil

from fastapi import APIRouter

from app.schemas import DiskUsageOut
from app.storage import STORAGE_ROOT

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/disk-usage", response_model=DiskUsageOut)
async def disk_usage():
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(STORAGE_ROOT)
    return DiskUsageOut(total_bytes=usage.total, used_bytes=usage.used, free_bytes=usage.free)
