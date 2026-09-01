from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import Engine

from sentry_atm.infrastructure.persistence import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)


def test_database_settings_builds_sqlite_url_from_path(tmp_path: Path) -> None:
    database_path = tmp_path / "database with spaces.db"

    settings = DatabaseSettings(database_path=database_path)

    assert settings.database_path == database_path
    assert settings.url.drivername == "sqlite+pysqlite"
    assert Path(settings.url.database) == database_path
    assert settings.is_memory is False


def test_database_settings_supports_in_memory_database() -> None:
    settings = DatabaseSettings(database_path=":memory:")

    assert settings.is_memory is True
    assert settings.url.database == ":memory:"


def test_database_settings_loads_path_from_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "environment.db"
    monkeypatch.setenv("TEST_SQLITE_PATH", str(database_path))

    settings = DatabaseSettings.from_env(variable_name="TEST_SQLITE_PATH")

    assert settings.database_path == database_path


def test_database_settings_rejects_blank_or_wrong_path_type() -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        DatabaseSettings(database_path="  ")
    with pytest.raises(TypeError, match="path or string"):
        DatabaseSettings(database_path=cast(Path, 123))


def test_database_engine_creates_parent_and_session_factory(tmp_path: Path) -> None:
    database_path = tmp_path / "nested" / "sentry.db"

    engine = create_database_engine(DatabaseSettings(database_path=database_path))
    session_factory = create_session_factory(engine)

    assert database_path.parent.is_dir()
    assert engine.url.drivername == "sqlite+pysqlite"
    assert session_factory.kw["bind"] is engine
    engine.dispose()


def test_database_factory_rejects_wrong_types() -> None:
    with pytest.raises(TypeError, match="DatabaseSettings"):
        create_database_engine(cast(DatabaseSettings, "not-settings"))
    with pytest.raises(TypeError, match="SQLAlchemy Engine"):
        create_session_factory(cast(Engine, "not-engine"))
