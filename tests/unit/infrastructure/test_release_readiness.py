from pathlib import Path

import pytest

import sentry_atm.infrastructure.release as release
from sentry_atm.infrastructure.release import (
    MainMergeReadinessFailure,
    MainMergeReadinessReport,
    main,
    print_main_merge_readiness_report,
    run_main_merge_readiness,
)


def _successful_runner(command: tuple[str, ...], repository: Path) -> release._CommandResult:
    del repository
    responses = {
        ("git", "rev-parse", "--show-toplevel"): "C:/repo\n",
        ("git", "branch", "--show-current"): "phase12/runtime-composition\n",
        ("git", "rev-list", "--count", "origin/main..HEAD"): "42\n",
        ("git", "ls-files", "-z"): "README.md\0src/sentry_atm/__init__.py\0",
        (
            "git",
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
        ): "brief.pdf\0forms/template.hwp\0",
        (
            "git",
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{upstream}",
        ): "origin/phase12/runtime-composition\n",
        (
            "git",
            "rev-list",
            "--left-right",
            "--count",
            "origin/phase12/runtime-composition...HEAD",
        ): "0\t0\n",
    }
    if command == (release.sys.executable, "-m", "pytest", "-q"):
        return release._CommandResult(0, "818 passed in 4.00s\n")
    if command == (
        release.sys.executable,
        "-m",
        "sentry_atm.infrastructure.http",
        "--check",
    ):
        return release._CommandResult(
            0,
            "SENTRY ATM RELEASE PREFLIGHT PASSED (5 checks)\n"
            "SENTRY ATM DEMO CHECK PASSED (10 checkpoints)\n",
        )
    return release._CommandResult(0, responses.get(command, ""))


def test_merge_readiness_produces_complete_evidence(monkeypatch) -> None:
    monkeypatch.setattr(release, "_run_command", _successful_runner)

    report = run_main_merge_readiness("C:/repo")

    assert tuple(check.code for check in report.checks) == (
        "BRANCH",
        "BASE",
        "WORKTREE",
        "ARTIFACTS",
        "UPSTREAM",
        "RUFF",
        "PYTEST",
        "DEMO",
    )
    assert report.checks[0].detail == "phase12/runtime-composition is 42 commits ahead"
    assert report.checks[3].detail.endswith("2 kept local")
    assert report.checks[-1].detail == "5 preflight checks and 10 checkpoints passed"


@pytest.mark.parametrize(
    ("failed_command", "message"),
    [
        (("git", "merge-base", "--is-ancestor", "origin/main", "HEAD"), "must descend"),
        (("git", "diff", "--quiet"), "worktree changes"),
        (("git", "diff", "--cached", "--quiet"), "staged changes"),
    ],
)
def test_merge_readiness_rejects_unsafe_repository_state(
    monkeypatch,
    failed_command,
    message,
) -> None:
    def runner(command, repository):
        result = _successful_runner(command, repository)
        if command == failed_command:
            return release._CommandResult(1)
        return result

    monkeypatch.setattr(release, "_run_command", runner)

    with pytest.raises(MainMergeReadinessFailure, match=message):
        run_main_merge_readiness("C:/repo")


def test_merge_readiness_rejects_tracked_documents_untracked_source_and_divergence(
    monkeypatch,
) -> None:
    def with_response(target, stdout):
        def runner(command, repository):
            if command == target:
                return release._CommandResult(0, stdout)
            return _successful_runner(command, repository)

        return runner

    monkeypatch.setattr(
        release,
        "_run_command",
        with_response(("git", "ls-files", "-z"), "README.md\0secret.pdf\0"),
    )
    with pytest.raises(MainMergeReadinessFailure, match="must not be tracked"):
        run_main_merge_readiness("C:/repo")

    monkeypatch.setattr(
        release,
        "_run_command",
        with_response(
            ("git", "ls-files", "--others", "--exclude-standard", "-z"),
            "new_module.py\0",
        ),
    )
    with pytest.raises(MainMergeReadinessFailure, match="unexpected untracked"):
        run_main_merge_readiness("C:/repo")

    divergence_command = (
        "git",
        "rev-list",
        "--left-right",
        "--count",
        "origin/phase12/runtime-composition...HEAD",
    )
    monkeypatch.setattr(
        release,
        "_run_command",
        with_response(divergence_command, "1\t2\n"),
    )
    with pytest.raises(MainMergeReadinessFailure, match="must match"):
        run_main_merge_readiness("C:/repo")


def test_merge_readiness_requires_both_demo_success_markers(monkeypatch) -> None:
    demo_command = (
        release.sys.executable,
        "-m",
        "sentry_atm.infrastructure.http",
        "--check",
    )

    def runner(command, repository):
        if command == demo_command:
            return release._CommandResult(0, "SENTRY ATM RELEASE PREFLIGHT PASSED (5 checks)\n")
        return _successful_runner(command, repository)

    monkeypatch.setattr(release, "_run_command", runner)

    with pytest.raises(MainMergeReadinessFailure, match="regression success evidence"):
        run_main_merge_readiness("C:/repo")


def test_report_printer_and_cli_are_stable(monkeypatch, capsys) -> None:
    monkeypatch.setattr(release, "_run_command", _successful_runner)
    report = run_main_merge_readiness("C:/repo")

    print_main_merge_readiness_report(report)

    output = capsys.readouterr().out
    assert "[PASS] BRANCH" in output
    assert "[PASS] DEMO" in output
    assert "MAIN MERGE READY (8 checks)" in output
    with pytest.raises(TypeError, match="MainMergeReadinessReport"):
        print_main_merge_readiness_report(object())  # type: ignore[arg-type]

    monkeypatch.setattr(release, "run_main_merge_readiness", lambda: report)
    assert main([]) == 0
    assert main(["unexpected"]) == 2
    assert "does not accept arguments" in capsys.readouterr().out
    assert isinstance(report, MainMergeReadinessReport)
