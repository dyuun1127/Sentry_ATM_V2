"""SQLite engine, schema initialization, and session construction."""

from sqlite3 import Connection as SQLiteConnection

from sqlalchemy import Engine, event, select
from sqlalchemy.engine import create_engine
from sqlalchemy.orm import Session, sessionmaker

from sentry_atm.infrastructure.persistence.config import DatabaseSettings
from sentry_atm.infrastructure.persistence.models import AircraftTypeRow, Base


def create_database_engine(
    settings: DatabaseSettings,
    *,
    echo: bool = False,
) -> Engine:
    """Create a local SQLite engine and enable foreign-key enforcement."""

    if not isinstance(settings, DatabaseSettings):
        raise TypeError("settings must be DatabaseSettings")
    if not settings.is_memory:
        settings.database_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        settings.url,
        echo=echo,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(
        dbapi_connection: SQLiteConnection,
        _connection_record: object,
    ) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def initialize_database(engine: Engine) -> None:
    """Create the initial schema idempotently and seed the UNKNOWN type."""

    if not isinstance(engine, Engine):
        raise TypeError("engine must be a SQLAlchemy Engine")
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
        unknown_type = connection.scalar(
            select(AircraftTypeRow.type_code).where(AircraftTypeRow.type_code == "UNKNOWN")
        )
        if unknown_type is None:
            connection.execute(
                AircraftTypeRow.__table__.insert().values(
                    type_code="UNKNOWN",
                    category="UNKNOWN",
                    manufacturer=None,
                    model=None,
                )
            )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create sessions whose transaction boundary is controlled by the caller."""

    if not isinstance(engine, Engine):
        raise TypeError("engine must be a SQLAlchemy Engine")
    return sessionmaker(bind=engine, expire_on_commit=False)
