from enum import StrEnum
from pathlib import Path
from typing import ClassVar

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class KisEnvironment(StrEnum):
    PAPER = "paper"
    LIVE = "live"


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
    kis_environment: KisEnvironment = KisEnvironment.PAPER
    kis_app_key: SecretStr | None = None
    kis_app_secret: SecretStr | None = None
    kis_app_key_file: Path | None = None
    kis_app_secret_file: Path | None = None
    krx_base_url: str = "https://global.krx.co.kr"

    @property
    def kis_base_url(self) -> str:
        if self.kis_environment is KisEnvironment.PAPER:
            return "https://openapivts.koreainvestment.com:29443"
        return "https://openapi.koreainvestment.com:9443"
