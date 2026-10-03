"""
Phase 3 demo helper: backdate a file so it shows up in the stale-file
prompt without waiting a year.

    python scripts/make_file_stale.py <username-or-email> <filename> [days]

Sets the matching (non-deleted) file's updated_at and last_accessed_at to
`days` ago (default 400) and clears any "keep" snooze. Run it, then refresh
the frontend and log back in -- the prompt appears on the file browser.
Talks to the database directly (same pattern as test_dedup.py); the API
deliberately has no way to fake a file's age.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.models import File, User  # noqa: E402


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    identifier, filename = sys.argv[1], sys.argv[2]
    days = int(sys.argv[3]) if len(sys.argv) > 3 else 400
    backdated = datetime.now(timezone.utc) - timedelta(days=days)

    engine = create_engine(settings.sync_database_url, future=True, connect_args=settings.psycopg2_connect_args)
    with Session(engine) as session:
        user = session.execute(
            select(User).where((User.email == identifier) | (User.username == identifier))
        ).scalar_one_or_none()
        if user is None:
            sys.exit(f"No user '{identifier}'")
        result = session.execute(
            update(File)
            .where(File.owner_id == user.id, File.filename == filename, File.is_deleted == False)  # noqa: E712
            .values(updated_at=backdated, last_accessed_at=backdated, stale_prompt_snoozed_until=None)
        )
        session.commit()
        if result.rowcount == 0:
            sys.exit(f"No live file named '{filename}' owned by {user.username}")
        print(f"Backdated {result.rowcount} file(s) named '{filename}' to {backdated:%Y-%m-%d} ({days} days ago).")


if __name__ == "__main__":
    main()
