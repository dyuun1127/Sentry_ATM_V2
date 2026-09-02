"""Timezone policy for domain timestamps."""

from datetime import UTC, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9), name="KST")


def is_timezone_aware(value: datetime) -> bool:
    """Return whether a datetime has a usable UTC offset."""

    return value.tzinfo is not None and value.utcoffset() is not None


def require_timezone_aware(value: datetime, *, field_name: str = "timestamp") -> datetime:
    """Reject naive datetimes instead of guessing their timezone."""

    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if not is_timezone_aware(value):
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def to_utc(value: datetime, *, field_name: str = "timestamp") -> datetime:
    """Validate and normalize a timestamp to UTC."""

    return require_timezone_aware(value, field_name=field_name).astimezone(UTC)


def to_kst(value: datetime, *, field_name: str = "timestamp") -> datetime:
    """Convert an aware timestamp to KST for presentation."""

    return require_timezone_aware(value, field_name=field_name).astimezone(KST)
