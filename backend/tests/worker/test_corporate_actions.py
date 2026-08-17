import sys
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import anyio
import pytest

from auto_stock_trading.adapters.disclosures.opendart_http import DartConfigurationError
from auto_stock_trading.settings.runtime import Environment, Settings
from auto_stock_trading.worker import corporate_actions

if TYPE_CHECKING:
    from pathlib import Path


def test_dart_collection_requires_server_side_api_key() -> None:
    settings = Settings(environment=Environment.TEST, dart_api_key=None)

    with (
        patch("auto_stock_trading.worker.corporate_actions.Settings", return_value=settings),
        pytest.raises(DartConfigurationError, match="AUTO_STOCK_DART_API_KEY"),
    ):
        _ = anyio.run(
            corporate_actions.collect_dart_cash_dividends,
            "005930",
            "00126380",
            "2026-04-01",
            "2026-05-31",
        )


def test_dart_api_key_is_loaded_from_docker_secret_file(tmp_path: Path) -> None:
    key_file = tmp_path / "dart_api_key"
    _ = key_file.write_text("dart-secret-key\n", encoding="utf-8")
    settings = Settings(
        environment=Environment.TEST,
        dart_api_key=None,
        dart_api_key_file=key_file,
    )

    key = corporate_actions.load_dart_api_key(settings)

    assert key.get_secret_value() == "dart-secret-key"


def test_cli_routes_etf_distribution_collection() -> None:
    collect = AsyncMock(return_value=3)
    argv = [
        "corporate_actions",
        "--etf-distributions",
        "--start-date",
        "2026-01-01",
        "--end-date",
        "2026-08-17",
    ]

    with (
        patch.object(corporate_actions, "collect_kodex_distributions", new=collect),
        patch.object(sys, "argv", argv),
    ):
        corporate_actions.main()

    collect.assert_awaited_once_with("069500", "2ETF01", "2026-01-01", "2026-08-17")


def test_cli_routes_dart_dividend_collection_by_default() -> None:
    collect = AsyncMock(return_value=3)
    argv = ["corporate_actions", "--start-date", "2026-01-01", "--end-date", "2026-08-17"]

    with (
        patch.object(corporate_actions, "collect_dart_cash_dividends", new=collect),
        patch.object(sys, "argv", argv),
    ):
        corporate_actions.main()

    collect.assert_awaited_once_with("005930", "00126380", "2026-01-01", "2026-08-17")


def test_cli_routes_ex_date_confirmation() -> None:
    confirm = AsyncMock(return_value=(2, 1))
    argv = ["corporate_actions", "--confirm-ex-dates"]

    with (
        patch.object(corporate_actions, "confirm_corporate_action_ex_dates", new=confirm),
        patch.object(sys, "argv", argv),
    ):
        corporate_actions.main()

    confirm.assert_awaited_once_with(("005930", "069500"))


def test_cli_routes_adjusted_dataset_build() -> None:
    build = AsyncMock(return_value="dataset-id")
    argv = [
        "corporate_actions",
        "--build-adjusted",
        "total_return",
        "--symbol",
        "069500",
        "--start-date",
        "2026-08-03",
        "--end-date",
        "2026-08-14",
        "--knowledge-cutoff",
        "2026-08-17T00:00:00+00:00",
    ]

    with (
        patch.object(corporate_actions, "build_adjusted_dataset", new=build),
        patch.object(sys, "argv", argv),
    ):
        corporate_actions.main()

    build.assert_awaited_once_with(
        "069500",
        "total_return",
        "2026-08-03",
        "2026-08-14",
        "2026-08-17T00:00:00+00:00",
    )


def test_dart_key_file_error_does_not_expose_the_file_path(tmp_path: Path) -> None:
    settings = Settings(
        environment=Environment.TEST,
        dart_api_key=None,
        dart_api_key_file=tmp_path / "missing",
    )

    with pytest.raises(DartConfigurationError) as error:
        _ = corporate_actions.load_dart_api_key(settings)

    assert str(tmp_path) not in str(error.value)
