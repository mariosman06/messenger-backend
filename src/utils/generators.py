"""UUID generation."""

from uuid import UUID, uuid4


def uuid_v4() -> UUID:
    """Returns a fresh random UUIDv4 identifier."""
    return uuid4()
