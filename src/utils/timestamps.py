"""UTC timestamp and expiration/TTL."""

from datetime import UTC, datetime, timedelta


def current_ts() -> datetime:
    return datetime.now(UTC)


def expiration_ts(ttl: timedelta | int | float) -> datetime:
    if isinstance(ttl, (int, float)):
        ttl = timedelta(seconds=ttl)
    return current_ts() + ttl
