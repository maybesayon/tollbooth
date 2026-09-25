import argparse
import asyncio
import sys

from tollbooth.copydb import CopyError, copy_database


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

    args = parser.parse_args(argv)
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


if __name__ == "__main__":
    raise SystemExit(main())
