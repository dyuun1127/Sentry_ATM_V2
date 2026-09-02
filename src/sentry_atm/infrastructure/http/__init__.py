"""Framework-independent HTTP adapters."""

from sentry_atm.infrastructure.http.exception_queue import ExceptionQueueWsgiApp

__all__ = ["ExceptionQueueWsgiApp"]
