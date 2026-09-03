"""Repository and regression checks required before merging the demo branch."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

_MERGE_BASE = "origin/main"
_LOCAL_ARTIFACT_SUFFIXES = frozenset(
    {".docx", ".hwp", ".hwpx", ".pdf", ".pptx", ".xls", ".xlsx"}
)


class MainMergeReadinessFailure(RuntimeError):
    """Raised when the current checkout is not safe to merge into main."""


@dataclass(frozen=True, slots=True)
class MainMergeReadinessCheck:
    """One successful merge-readiness check."""

    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class MainMergeReadinessReport:
    """Ordered evidence required before the final main merge."""

    checks: tuple[MainMergeReadinessCheck, ...]


@dataclass(frozen=True, slots=True)
class _CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


def run_main_merge_readiness(
    repository: Path | str | None = None,
) -> MainMergeReadinessReport:
    """Run repository safety checks and the complete release verification suite."""

    requested_root = Path(repository or Path.cwd()).resolve()
    repository_root = _require_repository_root(requested_root)
    branch = _require_output(
        ("git", "branch", "--show-current"),
        repository_root,
        "current branch could not be determined",
    )
    if not branch:
        raise MainMergeReadinessFailure("detached HEAD is not eligible for the final merge")

    _require_success(
        ("git", "merge-base", "--is-ancestor", _MERGE_BASE, "HEAD"),
        repository_root,
        f"HEAD must descend from the latest {_MERGE_BASE}",
    )
    commit_count = _require_output(
        ("git", "rev-list", "--count", f"{_MERGE_BASE}..HEAD"),
        repository_root,
        "release commit count could not be determined",
    )
    if not commit_count.isdecimal() or int(commit_count) < 1:
        raise MainMergeReadinessFailure(f"HEAD has no release commits beyond {_MERGE_BASE}")

    _require_success(
        ("git", "diff", "--quiet"),
        repository_root,
        "tracked worktree changes must be committed",
    )
    _require_success(
        ("git", "diff", "--cached", "--quiet"),
        repository_root,
        "staged changes must be committed",
    )

    tracked_files = _nul_items(
        _require_output(
            ("git", "ls-files", "-z"),
            repository_root,
            "tracked files could not be inspected",
            strip=False,
        )
    )
    forbidden = tuple(
        name for name in tracked_files if Path(name).suffix.casefold() in _LOCAL_ARTIFACT_SUFFIXES
    )
    if forbidden:
        raise MainMergeReadinessFailure(
            "reference documents must not be tracked: " + ", ".join(forbidden)
        )

    untracked_files = _nul_items(
        _require_output(
            ("git", "ls-files", "--others", "--exclude-standard", "-z"),
            repository_root,
            "untracked files could not be inspected",
            strip=False,
        )
    )
    unexpected = tuple(
        name
        for name in untracked_files
        if Path(name).suffix.casefold() not in _LOCAL_ARTIFACT_SUFFIXES
    )
    if unexpected:
        raise MainMergeReadinessFailure(
            "unexpected untracked files must be committed or ignored: " + ", ".join(unexpected)
        )

    upstream = _require_output(
        ("git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"),
        repository_root,
        "current branch has no upstream",
    )
    divergence = _require_output(
        ("git", "rev-list", "--left-right", "--count", f"{upstream}...HEAD"),
        repository_root,
        "upstream divergence could not be determined",
    ).split()
    if divergence != ["0", "0"]:
        raise MainMergeReadinessFailure(
            f"HEAD must match {upstream}; found remote/local divergence {divergence}"
        )

    _require_success(
        (sys.executable, "-m", "ruff", "check", "."),
        repository_root,
        "Ruff validation failed",
    )
    pytest_result = _require_success(
        (sys.executable, "-m", "pytest", "-q"),
        repository_root,
        "test suite failed",
    )
    demo_result = _require_success(
        (sys.executable, "-m", "sentry_atm.infrastructure.http", "--check"),
        repository_root,
        "Golden Demo release check failed",
    )
    if "SENTRY ATM RELEASE PREFLIGHT PASSED (5 checks)" not in demo_result.stdout:
        raise MainMergeReadinessFailure("Golden Demo preflight success evidence is missing")
    if "SENTRY ATM DEMO CHECK PASSED (10 checkpoints)" not in demo_result.stdout:
        raise MainMergeReadinessFailure("Golden Demo regression success evidence is missing")

    pytest_summary = _last_nonempty_line(pytest_result.stdout)
    checks = (
        MainMergeReadinessCheck("BRANCH", f"{branch} is {commit_count} commits ahead"),
        MainMergeReadinessCheck("BASE", f"HEAD descends from {_MERGE_BASE}"),
        MainMergeReadinessCheck("WORKTREE", "tracked and staged changes are clean"),
        MainMergeReadinessCheck(
            "ARTIFACTS",
            f"no reference documents tracked; {len(untracked_files)} kept local",
        ),
        MainMergeReadinessCheck("UPSTREAM", f"HEAD matches {upstream}"),
        MainMergeReadinessCheck("RUFF", "all checks passed"),
        MainMergeReadinessCheck("PYTEST", pytest_summary),
        MainMergeReadinessCheck("DEMO", "5 preflight checks and 10 checkpoints passed"),
    )
    return MainMergeReadinessReport(checks=checks)


def print_main_merge_readiness_report(report: MainMergeReadinessReport) -> None:
    """Print stable evidence suitable for the final merge checklist."""

    if not isinstance(report, MainMergeReadinessReport):
        raise TypeError("report must be a MainMergeReadinessReport")
    for item in report.checks:
        print(f"[PASS] {item.code:<14} {item.detail}")
    print(f"SENTRY ATM MAIN MERGE READY ({len(report.checks)} checks)")


def main(argv: Sequence[str] | None = None) -> int:
    """Run merge readiness from the current repository root."""

    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if arguments:
        print("[FAIL] this command does not accept arguments")
        return 2
    try:
        report = run_main_merge_readiness()
    except MainMergeReadinessFailure as error:
        print(f"[FAIL] {error}")
        return 1
    print_main_merge_readiness_report(report)
    return 0


def _require_repository_root(requested_root: Path) -> Path:
    root = _require_output(
        ("git", "rev-parse", "--show-toplevel"),
        requested_root,
        "command must run inside the SENTRY ATM Git repository",
    )
    return Path(root).resolve()


def _require_success(
    command: tuple[str, ...],
    repository_root: Path,
    failure_message: str,
) -> _CommandResult:
    result = _run_command(command, repository_root)
    if result.returncode != 0:
        detail = _last_nonempty_line(result.stderr) or _last_nonempty_line(result.stdout)
        suffix = f": {detail}" if detail else ""
        raise MainMergeReadinessFailure(f"{failure_message}{suffix}")
    return result


def _require_output(
    command: tuple[str, ...],
    repository_root: Path,
    failure_message: str,
    *,
    strip: bool = True,
) -> str:
    output = _require_success(command, repository_root, failure_message).stdout
    return output.strip() if strip else output


def _run_command(command: tuple[str, ...], repository_root: Path) -> _CommandResult:
    try:
        completed = subprocess.run(
            command,
            cwd=repository_root,
            capture_output=True,
            check=False,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MainMergeReadinessFailure(f"command could not complete: {command[0]}") from error
    return _CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _nul_items(value: str) -> tuple[str, ...]:
    return tuple(item for item in value.split("\0") if item)


def _last_nonempty_line(value: str) -> str:
    return next((line.strip() for line in reversed(value.splitlines()) if line.strip()), "")


if __name__ == "__main__":
    raise SystemExit(main())
