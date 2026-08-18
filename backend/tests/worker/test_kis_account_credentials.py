from typing import TYPE_CHECKING

import pytest

from auto_stock_trading.adapters.brokers.kis_http import KisConfigurationError
from auto_stock_trading.settings.runtime import Settings
from auto_stock_trading.worker.kis_credentials import load_kis_account

if TYPE_CHECKING:
    from pathlib import Path


def _settings(tmp_path: Path, number: str, product_code: str) -> Settings:
    number_file = tmp_path / "account-number"
    product_file = tmp_path / "account-product"
    _ = number_file.write_text(number, encoding="utf-8")
    _ = product_file.write_text(product_code, encoding="utf-8")
    return Settings(
        kis_account_number_file=number_file,
        kis_account_product_code_file=product_file,
    )


def test_account_secrets_are_loaded_and_hashed(tmp_path: Path) -> None:
    account = load_kis_account(_settings(tmp_path, "50123456", "01"))

    assert account.number.get_secret_value() == "50123456"
    assert account.product_code.get_secret_value() == "01"
    assert len(account.reference) == 12
    assert "50123456" not in account.reference


@pytest.mark.parametrize(
    ("number", "product_code"),
    [
        ("<계좌번호8자리>", "01"),
        ("5012345", "01"),
        ("501234567", "01"),
        ("5012345a", "01"),
        ("50123456", "1"),
        ("50123456", "0a"),
    ],
)
def test_account_secrets_reject_wrong_formats(
    tmp_path: Path,
    number: str,
    product_code: str,
) -> None:
    with pytest.raises(KisConfigurationError) as raised:
        _ = load_kis_account(_settings(tmp_path, number, product_code))

    assert number not in str(raised.value)


def test_missing_account_secret_fails_closed() -> None:
    with pytest.raises(KisConfigurationError):
        _ = load_kis_account(Settings())
