"""Command-line entry point for the local Golden Demo API server."""

from sentry_atm.infrastructure.http.server import main

if __name__ == "__main__":
    raise SystemExit(main())
