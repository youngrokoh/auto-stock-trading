from enum import StrEnum
from typing import ClassVar

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="AUTO_STOCK_",
        extra="ignore",
        frozen=True,
    )

    environment: Environment = Environment.DEVELOPMENT
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://auto_stock:auto_stock@localhost:5432/auto_stock_trading"
    )
    valkey_url: SecretStr = SecretStr("redis://localhost:6379/0")
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)
