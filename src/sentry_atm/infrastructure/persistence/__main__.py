"""Small command-line entry point for local SQLite setup."""

from argparse import ArgumentParser
from collections.abc import Sequence

from sentry_atm.infrastructure.persistence import (
    DatabaseSettings,
    create_database_engine,
    initialize_database,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = ArgumentParser(description="SENTRY ATM SQLite persistence utility")
    parser.add_argument(
        "command",
        choices=("init",),
        help="initialize the local database schema",
    )
    parser.add_argument(
        "--path",
        default=None,
        help="SQLite file path; defaults to SENTRY_DB_PATH or data/sentry_atm.db",
    )
    arguments = parser.parse_args(argv)

    settings = (
        DatabaseSettings(database_path=arguments.path)
        if arguments.path is not None
        else DatabaseSettings.from_env()
    )
    engine = create_database_engine(settings)
    try:
        initialize_database(engine)
    finally:
        engine.dispose()
    print(f"SQLite database initialized: {settings.database_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
