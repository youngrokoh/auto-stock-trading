from typing import TYPE_CHECKING
from unittest.mock import patch

import anyio
import pytest

from auto_stock_trading.adapters.brokers.kis_http import KisConfigurationError
from auto_stock_trading.settings.runtime import Environment, Settings
from auto_stock_trading.worker import market_data

if TYPE_CHECKING:
    from pathlib import Path


def test_market_data_task_requires_server_side_kis_credentials() -> None:
    settings = Settings(
        environment=Environment.TEST,
        kis_app_key=None,
        kis_app_secret=None,
    )

    with (
        patch("auto_stock_trading.worker.market_data.Settings", return_value=settings),
        pytest.raises(KisConfigurationError, match="AUTO_STOCK_KIS_APP_KEY"),
    ):
        _ = anyio.run(market_data.collect_seed_market_data, "2026-08-12", "2026-08-13")


def test_kis_credentials_are_loaded_from_docker_secret_files(tmp_path: Path) -> None:
    app_key_file = tmp_path / "kis_app_key"
    app_secret_file = tmp_path / "kis_app_secret"
    _ = app_key_file.write_text("paper-app-key\n", encoding="utf-8")
    _ = app_secret_file.write_text("paper-app-secret\n", encoding="utf-8")
    settings = Settings(
        environment=Environment.TEST,
        kis_app_key=None,
        kis_app_secret=None,
        kis_app_key_file=app_key_file,
        kis_app_secret_file=app_secret_file,
    )

    credentials = market_data.load_kis_credentials(settings)

    assert credentials.app_key.get_secret_value() == "paper-app-key"
    assert credentials.app_secret.get_secret_value() == "paper-app-secret"


def test_kis_secret_file_error_does_not_expose_the_file_path(tmp_path: Path) -> None:
    missing_file = tmp_path / "private-key-location"
    settings = Settings(
        environment=Environment.TEST,
        kis_app_key=None,
        kis_app_secret=None,
        kis_app_key_file=missing_file,
        kis_app_secret_file=missing_file,
    )

    with pytest.raises(KisConfigurationError) as error:
        _ = market_data.load_kis_credentials(settings)

    assert str(missing_file) not in str(error.value)


def test_kis_calendar_confirmation_rejects_the_paper_environment() -> None:
    settings = Settings(
        environment=Environment.TEST,
        kis_app_key=None,
        kis_app_secret=None,
    )

    with (
        patch("auto_stock_trading.worker.market_data.Settings", return_value=settings),
        pytest.raises(KisConfigurationError, match="live environment"),
    ):
        _ = anyio.run(market_data.confirm_today_market_calendar)
