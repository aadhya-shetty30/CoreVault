"""
Grant (or revoke) access to the admin storage overview.

    python scripts/make_admin.py <username-or-email>            # grant
    python scripts/make_admin.py <username-or-email> --revoke   # revoke
    python scripts/make_admin.py --list                         # who has it

There's deliberately no API for this -- whoever can run this script already
has the database credentials in .env, which is exactly the trust level an
admin flag should require. The user needs to log out and back in to see the
Admin page.
"""
import sys
from pathlib import Path

from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.models import User  # noqa: E402


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    engine = create_engine(settings.sync_database_url, future=True, connect_args=settings.psycopg2_connect_args)
    with Session(engine) as session:
        if args[0] == "--list":
            admins = session.execute(select(User.username, User.email).where(User.is_admin == True)).all()  # noqa: E712
            print("\n".join(f"{u} <{e}>" for u, e in admins) or "No admins yet.")
            return

        identifier, revoke = args[0], "--revoke" in args
        user = session.execute(
            select(User).where((User.email == identifier) | (User.username == identifier))
        ).scalar_one_or_none()
        if user is None:
            sys.exit(f"No user '{identifier}'")
        session.execute(update(User).where(User.id == user.id).values(is_admin=not revoke))
        session.commit()
        print(f"{user.username} <{user.email}> is {'no longer' if revoke else 'now'} an admin.")


if __name__ == "__main__":
    main()
