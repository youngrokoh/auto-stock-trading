import sys
from unittest.mock import AsyncMock, patch

import anyio
import pytest

from auto_stock_trading.adapters.disclosures.opendart_http import DartConfigurationError
from auto_stock_trading.settings.runtime import Environment, Settings
from auto_stock_trading.worker import fundamentals


def test_financial_collection_requires_a_server_side_dart_key() -> None:
    settings = Settings(
        environment=Environment.TEST,
        dart_api_key=None,
        dart_api_key_file=None,
    )

    with (
        patch("auto_stock_trading.worker.fundamentals.Settings", return_value=settings),
        pytest.raises(DartConfigurationError, match="AUTO_STOCK_DART_API_KEY"),
    ):
        _ = anyio.run(fundamentals.collect_financial_statements)


def test_cli_routes_financial_statement_collection() -> None:
    collect = AsyncMock(return_value=(16, 2))
    argv = ["fundamentals", "--symbol", "005930", "--corp-code", "00126380"]

    with (
        patch.object(fundamentals, "collect_financial_statements", new=collect),
        patch.object(sys, "argv", argv),
    ):
        fundamentals.main()

    collect.assert_awaited_once_with("005930", "00126380")
