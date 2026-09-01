from pathlib import Path

from sentry_atm.infrastructure.persistence.__main__ import main


def test_sqlite_cli_initializes_requested_database(
    tmp_path: Path,
    capsys: object,
) -> None:
    database_path = tmp_path / "cli.db"

    exit_code = main(("init", "--path", str(database_path)))

    assert exit_code == 0
    assert database_path.is_file()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "SQLite database initialized" in captured.out
