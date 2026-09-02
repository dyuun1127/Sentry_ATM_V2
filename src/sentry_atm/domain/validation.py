"""Shared validation helpers for persistence-independent domain models."""


def require_identifier(value: str, *, field_name: str) -> str:
    """Return a trimmed non-blank identifier without guessing its meaning."""

    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def normalize_optional_text(value: str | None, *, field_name: str) -> str | None:
    """Normalize optional text while rejecting present-but-blank values."""

    if value is None:
        return None
    return require_identifier(value, field_name=field_name)
