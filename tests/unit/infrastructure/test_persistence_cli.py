from pathlib import Path

from sentry_atm.infrastructure.persistence.__main__ import main
from sentry_atm.reference_data import POC_AIRCRAFT_TYPES, POC_PERFORMANCE_PROFILES


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
    # 개수를 숫자로 박아 두면 참조자료가 늘어날 때마다 시험이 거짓으로 깨진다.
    # 실제로 기종이 합성 3종에서 실제 15종으로 늘었을 때 이 시험만 남아 있었다.
    # 여기서 보려는 것은 개수가 아니라 **두 번째 실행이 아무것도 더 넣지 않는가**다.
    expected = f"types={len(POC_AIRCRAFT_TYPES)}, profiles={len(POC_PERFORMANCE_PROFILES)}"
    assert expected in first_output
    assert "types=0, profiles=0" in second_output
