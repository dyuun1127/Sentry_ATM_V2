import pytest

from sentry_atm.infrastructure.http.demo_check import (
    GoldenDemoRegressionCheckpoint,
    GoldenDemoRegressionReport,
    print_golden_demo_regression_report,
    run_golden_demo_regression,
)


def test_real_loopback_regression_verifies_complete_golden_demo() -> None:
    report = run_golden_demo_regression()

    assert report.initial_session_id == "RKTU_GOLDEN_DEMO_V1-RUN-000000"
    assert report.reset_session_id == "RKTU_GOLDEN_DEMO_V1-RUN-000001"
    assert tuple(item.code for item in report.checkpoints) == (
        "UI_READY",
        "MONITORING",
        "CONFLICT",
        "RECOMMENDATION",
        "DECISION",
        "REVALIDATION",
        "RESET",
    )
    assert tuple(item.stage for item in report.checkpoints) == (
        "READY",
        "MONITORING",
        "CONFLICT_DETECTED",
        "RECOMMENDATION_AVAILABLE",
        "DECISION_ACCEPTED",
        "CONFLICT_RESOLVED",
        "READY",
    )
    assert report.checkpoints[-2].detail == "applied 9,000 ft | SAFE / LOW / RESOLVED"


@pytest.mark.parametrize("value", [0, -1, -0.5])
def test_regression_rejects_non_positive_timeout(value: float) -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        run_golden_demo_regression(timeout_seconds=value)


@pytest.mark.parametrize("value", [True, "3"])
def test_regression_rejects_non_numeric_timeout(value: object) -> None:
    with pytest.raises(TypeError, match="positive number"):
        run_golden_demo_regression(timeout_seconds=value)  # type: ignore[arg-type]


def test_report_printer_is_stable_and_validates_input(capsys) -> None:
    report = GoldenDemoRegressionReport(
        initial_session_id="RUN-0",
        reset_session_id="RUN-1",
        checkpoints=(
            GoldenDemoRegressionCheckpoint(
                code="READY",
                stage="READY",
                elapsed_seconds=0.0,
                detail="ready",
            ),
        ),
    )

    print_golden_demo_regression_report(report)

    output = capsys.readouterr().out
    assert "[PASS] READY" in output
    assert "T+000.0" in output
    assert "PASSED (1 checkpoints)" in output
    with pytest.raises(TypeError, match="GoldenDemoRegressionReport"):
        print_golden_demo_regression_report(object())  # type: ignore[arg-type]
