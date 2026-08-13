from unittest.mock import patch

import anyio
import pytest

from auto_stock_trading.adapters.brokers.kis_http import KisConfigurationError
from auto_stock_trading.settings.runtime import Environment, Settings
from auto_stock_trading.worker.market_data import collect_seed_market_data


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
        _ = anyio.run(collect_seed_market_data, "2026-08-12", "2026-08-13")
