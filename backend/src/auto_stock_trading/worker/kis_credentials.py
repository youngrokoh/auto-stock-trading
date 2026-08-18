from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import SecretStr

from auto_stock_trading.adapters.brokers.kis_account import KisAccount
from auto_stock_trading.adapters.brokers.kis_http import KisConfigurationError, KisCredentials

if TYPE_CHECKING:
    from pathlib import Path

    from auto_stock_trading.settings.runtime import Settings


def load_kis_credentials(settings: Settings) -> KisCredentials:
    return KisCredentials(
        _secret_from(settings.kis_app_key, settings.kis_app_key_file, "AUTO_STOCK_KIS_APP_KEY"),
        _secret_from(
            settings.kis_app_secret,
            settings.kis_app_secret_file,
            "AUTO_STOCK_KIS_APP_SECRET",
        ),
    )


def load_kis_account(settings: Settings) -> KisAccount:
    """계좌번호는 secret 파일로만 주입한다. 없으면 fail-closed."""
    return KisAccount(
        number=_secret_from(
            settings.kis_account_number,
            settings.kis_account_number_file,
            "AUTO_STOCK_KIS_ACCOUNT_NUMBER",
        ),
        product_code=_secret_from(
            settings.kis_account_product_code,
            settings.kis_account_product_code_file,
            "AUTO_STOCK_KIS_ACCOUNT_PRODUCT_CODE",
        ),
    )


def _secret_from(direct: SecretStr | None, file_path: Path | None, setting_name: str) -> SecretStr:
    if direct is not None and direct.get_secret_value():
        return direct
    if file_path is not None:
        try:
            value = file_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as error:
            message = f"{setting_name} or {setting_name}_FILE is required"
            raise KisConfigurationError(message) from error
        if value:
            return SecretStr(value)
    message = f"{setting_name} or {setting_name}_FILE is required"
    raise KisConfigurationError(message)
