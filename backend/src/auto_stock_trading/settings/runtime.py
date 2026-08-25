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
    kis_account_number: SecretStr | None = None
    kis_account_number_file: Path | None = None
    kis_account_product_code: SecretStr | None = None
    kis_account_product_code_file: Path | None = None
    kis_hts_id: SecretStr | None = None
    kis_hts_id_file: Path | None = None
    # 외부 알림(ADR-0014). 토큰과 chat_id 둘 다 secret 파일로만 주입한다.
    telegram_bot_token: SecretStr | None = None
    telegram_bot_token_file: Path | None = None
    telegram_chat_id: SecretStr | None = None
    telegram_chat_id_file: Path | None = None
    telegram_base_url: str = "https://api.telegram.org"
    # 한 폴에서 개별 전송할 최대 건수. 넘으면 요약 한 건으로 대체한다(계약 §폴 상한).
    notification_poll_cap: int = 20
    dart_api_key: SecretStr | None = None
    dart_api_key_file: Path | None = None
    dart_base_url: str = "https://opendart.fss.or.kr"
    kis_master_base_url: str = "https://new.real.download.dws.co.kr"
    kodex_base_url: str = "https://www.samsungfund.com"
    krx_base_url: str = "https://global.krx.co.kr"
    krx_open_base_url: str = "https://open.krx.co.kr"
    krx_attachment_base_url: str = "https://inc.krx.co.kr/attach/"
    krx_calendar_schedule_enabled: bool = False
    kis_calendar_schedule_enabled: bool = False
    # 유니버스 수급 일일 예약. 기본은 꺼져 있고 Compose 오버라이드에서만 켠다.
    investor_flow_schedule_enabled: bool = False
    # 자동 스케줄 주문 제출(ADR-0015). 기본은 꺼져 있고 Compose 오버라이드에서만 켠다.
    order_submission_schedule_enabled: bool = False

    @property
    def kis_base_url(self) -> str:
        if self.kis_environment is KisEnvironment.PAPER:
            return "https://openapivts.koreainvestment.com:29443"
        return "https://openapi.koreainvestment.com:9443"

    @property
    def kis_websocket_url(self) -> str:
        if self.kis_environment is KisEnvironment.PAPER:
            return "ws://ops.koreainvestment.com:31000"
        return "ws://ops.koreainvestment.com:21000"
