from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import SecretStr

from auto_stock_trading.adapters.brokers.kis_account import KisAccount
from auto_stock_trading.adapters.brokers.kis_http import KisConfigurationError, KisCredentials

if TYPE_CHECKING:
    from pathlib import Path

    from auto_stock_trading.settings.runtime import Settings


_ACCOUNT_NUMBER_LENGTH = 8
_PRODUCT_CODE_LENGTH = 2
_HTS_ID_MAX_LENGTH = 20


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
    """계좌번호는 secret 파일로만 주입한다. 없거나 형식이 다르면 fail-closed."""
    return KisAccount(
        number=_digits(
            _secret_from(
                settings.kis_account_number,
                settings.kis_account_number_file,
                "AUTO_STOCK_KIS_ACCOUNT_NUMBER",
            ),
            _ACCOUNT_NUMBER_LENGTH,
            "AUTO_STOCK_KIS_ACCOUNT_NUMBER",
        ),
        product_code=_digits(
            _secret_from(
                settings.kis_account_product_code,
                settings.kis_account_product_code_file,
                "AUTO_STOCK_KIS_ACCOUNT_PRODUCT_CODE",
            ),
            _PRODUCT_CODE_LENGTH,
            "AUTO_STOCK_KIS_ACCOUNT_PRODUCT_CODE",
        ),
    )


def load_kis_hts_id(settings: Settings) -> SecretStr:
    """체결통보 구독의 `tr_key`. secret 파일로만 주입하고 값은 메시지에 넣지 않는다."""
    secret = _secret_from(settings.kis_hts_id, settings.kis_hts_id_file, "AUTO_STOCK_KIS_HTS_ID")
    value = secret.get_secret_value()
    if not value.isalnum() or len(value) > _HTS_ID_MAX_LENGTH:
        message = f"AUTO_STOCK_KIS_HTS_ID must be alphanumeric and at most {_HTS_ID_MAX_LENGTH}"
        raise KisConfigurationError(message)
    return secret


def _digits(secret: SecretStr, length: int, setting_name: str) -> SecretStr:
    """값 자체는 메시지에 넣지 않고 자릿수 계약만 검사한다."""
    value = secret.get_secret_value()
    if len(value) != length or not value.isdigit():
        message = f"{setting_name} must be exactly {length} digits"
        raise KisConfigurationError(message)
    return secret


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
