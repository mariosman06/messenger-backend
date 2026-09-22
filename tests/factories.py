"""Test model factories for generating authenticated users."""

from dataclasses import dataclass
from uuid import uuid4

from src.api.schemas import TokenPairResponse
from src.database.models import User
from src.main import app
from src.services.auth import AuthService


@dataclass(slots=True, frozen=True)
class TestUser:
    """Encapsulates a generated test user with credentials and auth headers."""

    __test__ = False

    user: User
    password: str
    tokens: TokenPairResponse

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens.access_token}"}


class UserFactory:
    """Factory for instantiating registered users in the test database."""

    __test__ = False

    @staticmethod
    async def create(
        username: str | None = None,
        password: str = "Password123!",
    ) -> TestUser:
        """Registers and returns a TestUser with valid authentication headers."""
        handle = username or f"user_{uuid4().hex[:8]}"

        # Resolve services directly from initialized test app state
        auth_service = AuthService(
            db=app.state.db,
            redis=app.state.redis.client,
            cache=app.state.auth_cache,
        )
        user, tokens = await auth_service.register(username=handle, password=password)

        return TestUser(
            user=user,
            password=password,
            tokens=TokenPairResponse.model_validate(tokens, from_attributes=True),
        )
