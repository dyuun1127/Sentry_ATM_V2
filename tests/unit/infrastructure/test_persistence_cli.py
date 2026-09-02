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


def test_sqlite_cli_seeds_requested_database_idempotently(
    tmp_path: Path,
    capsys: object,
) -> None:
    database_path = tmp_path / "seed-cli.db"

    first_exit_code = main(("seed", "--path", str(database_path)))
    first_output = capsys.readouterr().out  # type: ignore[attr-defined]
    second_exit_code = main(("seed", "--path", str(database_path)))
    second_output = capsys.readouterr().out  # type: ignore[attr-defined]

    assert first_exit_code == 0
    assert second_exit_code == 0
    assert "types=3, profiles=3" in first_output
    assert "types=0, profiles=0" in second_output
