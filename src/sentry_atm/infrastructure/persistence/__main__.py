"""Small command-line entry point for local SQLite setup."""

from argparse import ArgumentParser
from collections.abc import Sequence

from sentry_atm.infrastructure.persistence import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
    initialize_database,
    seed_poc_reference_data,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = ArgumentParser(description="SENTRY ATM SQLite persistence utility")
    parser.add_argument(
        "command",
        choices=("init", "seed"),
        help="initialize the schema or add missing PoC reference data",
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
        if arguments.command == "seed":
            session_factory = create_session_factory(engine)
            with session_factory.begin() as session:
                result = seed_poc_reference_data(session)
    finally:
        engine.dispose()
    if arguments.command == "init":
        print(f"SQLite database initialized: {settings.database_path.resolve()}")
    else:
        print(
            "SQLite reference data seeded: "
            f"types={result.aircraft_types_added}, "
            f"profiles={result.performance_profiles_added}, "
            f"path={settings.database_path.resolve()}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
