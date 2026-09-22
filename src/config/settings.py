"""Application settings and configuration loader."""

import os
from functools import lru_cache

import yaml
from pydantic import BaseModel, PostgresDsn


class LoggingConfig(BaseModel):
    """Logging system settings including log verbosity levels."""

    level: str = "DEBUG"


class AuthConfig(BaseModel):
    """Authentication and token expiration configuration settings."""

    access_token_ttl: int = 900
    refresh_token_ttl: int = 604800


class DatabaseConfig(BaseModel):
    """PostgreSQL database connection parameters and DSN builder."""

    host: str = "localhost"
    port: int = 5432
    user: str = "postgres"
    password: str = ""
    database: str = "app_db"
    min_pool_size: int = 5
    max_pool_size: int = 70
    command_timeout: float = 60.0

    @property
    def dsn(self) -> str:
        """Constructs a standard PostgreSQL connection DSN string."""
        return str(
            PostgresDsn.build(
                scheme="postgresql",
                username=self.user,
                password=self.password,
                host=self.host,
                port=self.port,
                path=self.database,
            )
        )


class RedisConfig(BaseModel):
    """Redis connection parameters and URI configuration."""

    url: str = "redis://localhost:6379/0"
    max_connections: int = 100


class AppConfig(BaseModel):
    """Root application configuration aggregating logging, database, and auth settings."""

    logging: LoggingConfig = LoggingConfig()
    database: DatabaseConfig = DatabaseConfig()
    auth: AuthConfig = AuthConfig()
    redis: RedisConfig = RedisConfig()


def load_config_file(config_path: str) -> dict:
    """Loads and parses a YAML configuration file from disk."""
    if not os.path.isfile(config_path):
        return {}
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache
def get_settings() -> AppConfig:
    """Retrieves cached application settings from YAML configuration with environment overrides."""
    default_path = "config/messenger.yaml"
    path = os.getenv("APP_CONFIG_PATH") or default_path
    return AppConfig(**load_config_file(path))
