import argparse
import getpass
import logging
import signal
import sys
import threading
from collections.abc import Sequence
from pathlib import Path

from neurotlon_server.backup import BackupError, backup_once, restore, run_loop
from neurotlon_server.config import Settings
from neurotlon_server.db import create_engine_from_settings, create_session_factory
from neurotlon_server.users import LoginTakenError, create_user

MIN_PASSWORD_LENGTH = 8


def _create_superuser(login: str) -> int:
    password = getpass.getpass("Password: ")
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"Password must be at least {MIN_PASSWORD_LENGTH} characters", file=sys.stderr)
        return 1
    if getpass.getpass("Repeat password: ") != password:
        print("Passwords do not match", file=sys.stderr)
        return 1
    engine = create_engine_from_settings(Settings())
    try:
        with create_session_factory(engine)() as db:
            create_user(
                db,
                login=login,
                password=password,
                role="superuser",
                discipline=None,
                actor_id=None,
            )
    except LoginTakenError:
        print(f"Login '{login}' already exists", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(f"Superuser '{login}' created")
    return 0


def _backup(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db, to = Path(args.db), Path(args.to)
    if args.once:
        try:
            path = backup_once(db, to, args.keep)
        except BackupError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"Backup written: {path}")
        return 0
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    run_loop(db, to, args.every, args.keep, stop=stop)
    return 0


def _restore(args: argparse.Namespace) -> int:
    try:
        kept = restore(Path(args.source), Path(args.db))
    except BackupError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Restored {args.db} from {args.source}")
    if kept is not None:
        print(f"Previous database kept as {kept}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="neurotlon-server")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-superuser", help="create a superuser (password is prompted)")
    create.add_argument("--login", required=True)
    backup = sub.add_parser("backup", help="copy the database to a folder, once or every N s")
    backup.add_argument("--db", required=True, help="path to the SQLite file")
    backup.add_argument("--to", required=True, help="folder for timestamped copies")
    backup.add_argument("--every", type=float, default=60, help="seconds between copies")
    backup.add_argument("--keep", type=int, default=120, help="how many copies to keep")
    backup.add_argument("--once", action="store_true", help="one copy and exit")
    rest = sub.add_parser("restore", help="replace the database with a backup (server stopped)")
    rest.add_argument("--from", dest="source", required=True, help="backup file")
    rest.add_argument("--db", required=True, help="path to the SQLite file to replace")
    args = parser.parse_args(argv)
    if args.command == "backup":
        return _backup(args)
    if args.command == "restore":
        return _restore(args)
    return _create_superuser(args.login)


if __name__ == "__main__":
    sys.exit(main())
