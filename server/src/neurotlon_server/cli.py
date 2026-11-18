import argparse
import getpass
import sys
from collections.abc import Sequence

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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="neurotlon-server")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-superuser", help="create a superuser (password is prompted)")
    create.add_argument("--login", required=True)
    args = parser.parse_args(argv)
    return _create_superuser(args.login)


if __name__ == "__main__":
    sys.exit(main())
