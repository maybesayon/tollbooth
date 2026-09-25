import argparse
import asyncio
import getpass
import os
import re
import sys

from tollbooth.accounts import create_user
from tollbooth.auth import EMAIL_PATTERN, normalize_email, password_problem
from tollbooth.copydb import CopyError, copy_database
from tollbooth.db import create_engine, run_migrations
from tollbooth.domain import Role
from tollbooth.repositories.base import DuplicateNameError
from tollbooth.repositories.sql_auth import SqlUserRepository

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./data/tollbooth.db"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tollbooth", description="Tollbooth administration")
    commands = parser.add_subparsers(dest="command", required=True)

    copy = commands.add_parser(
        "copy-db",
        help="copy all data to another database (e.g. SQLite to Postgres)",
        description="Copy all Tollbooth data into an empty database. Stop Tollbooth first.",
    )
    copy.add_argument("source", help="e.g. sqlite+aiosqlite:///./data/tollbooth.db")
    copy.add_argument("target", help="e.g. postgresql+asyncpg://user:pass@host/tollbooth")

    user = commands.add_parser(
        "create-user",
        help="create a dashboard user (e.g. the first admin)",
        description="Create a user. Prompts for the password unless --password-stdin is given.",
    )
    user.add_argument("--email", required=True)
    user.add_argument("--name", required=True)
    user.add_argument("--role", choices=[r.value for r in Role], default=Role.ADMIN.value)
    user.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
    user.add_argument(
        "--database-url",
        default=os.environ.get("TOLLBOOTH_DATABASE_URL", DEFAULT_DATABASE_URL),
        help="defaults to $TOLLBOOTH_DATABASE_URL",
    )

    args = parser.parse_args(argv)
    if args.command == "create-user":
        return _create_user(args)
    if args.command == "copy-db":
        try:
            copied = asyncio.run(copy_database(args.source, args.target))
        except CopyError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        for table, count in copied.items():
            print(f"{table}: {count} rows")
        print("done")
    return 0


def _create_user(args: argparse.Namespace) -> int:
    email = normalize_email(args.email)
    if not re.match(EMAIL_PATTERN, email):
        print("error: invalid email address", file=sys.stderr)
        return 1
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("Password: ")
        if getpass.getpass("Repeat password: ") != password:
            print("error: passwords do not match", file=sys.stderr)
            return 1
    if problem := password_problem(password, email):
        print(f"error: {problem}", file=sys.stderr)
        return 1

    async def run() -> None:
        await asyncio.to_thread(run_migrations, args.database_url)
        engine = create_engine(args.database_url)
        try:
            await create_user(
                SqlUserRepository(engine), email, args.name.strip(), Role(args.role), password
            )
        finally:
            await engine.dispose()

    try:
        asyncio.run(run())
    except DuplicateNameError:
        print(f"error: a user with email {email} already exists", file=sys.stderr)
        return 1
    print(f"created {args.role} {email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
