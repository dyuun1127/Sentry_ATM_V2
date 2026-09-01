"""File-backed SQLite configuration."""

from dataclasses import dataclass
from os import environ
from pathlib import Path

from sqlalchemy.engine import URL

DEFAULT_DATABASE_PATH = Path("data/sentry_atm.db")


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    """SQLite database path with an explicit in-memory test option."""

    database_path: Path | str = DEFAULT_DATABASE_PATH

    def __post_init__(self) -> None:
        if not isinstance(self.database_path, (Path, str)):
            raise TypeError("database_path must be a path or string")
        if isinstance(self.database_path, str) and not self.database_path.strip():
            raise ValueError("database_path must not be blank")
        object.__setattr__(self, "database_path", Path(self.database_path).expanduser())

    @classmethod
    def from_env(cls, *, variable_name: str = "SENTRY_DB_PATH") -> "DatabaseSettings":
        """Load the optional SQLite path from the process environment."""

        return cls(database_path=environ.get(variable_name, str(DEFAULT_DATABASE_PATH)))

    @property
    def is_memory(self) -> bool:
        return str(self.database_path) == ":memory:"

    @property
    def url(self) -> URL:
        """Return a SQLAlchemy URL without user, password, host, or port."""

        database = ":memory:" if self.is_memory else str(self.database_path.resolve())
        return URL.create("sqlite+pysqlite", database=database)
