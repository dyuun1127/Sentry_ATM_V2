import sentry_atm


def test_package_exposes_version() -> None:
    assert sentry_atm.__version__ == "0.1.0"
