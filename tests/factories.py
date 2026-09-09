from dataclasses import dataclass
from uuid import uuid4

from src.api.schemas import TokenPairResponse
from src.database.models import User
from src.services import auth as auth_service


@dataclass(slots=True, frozen=True)
class TestUser:
    __test__ = False

    user: User
    password: str
    tokens: TokenPairResponse

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens.access_token}"}


class UserFactory:
    __test__ = False

    @staticmethod
    async def create(
        username: str | None = None,
        password: str = "Password123!",
    ) -> TestUser:
        handle = username or f"user_{uuid4().hex[:8]}"
        user, tokens = await auth_service.register(username=handle, password=password)

        return TestUser(
            user=user,
            password=password,
            tokens=TokenPairResponse.model_validate(tokens, from_attributes=True),
        )
