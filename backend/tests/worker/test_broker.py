from unittest.mock import patch

from pydantic import SecretStr

from auto_stock_trading.settings.runtime import Settings
from auto_stock_trading.worker.broker import create_broker


def test_create_broker_disables_read_timeout_for_blocking_queue() -> None:
    settings = Settings(valkey_url=SecretStr("redis://queue.example:6379/2"))

    with patch("auto_stock_trading.worker.broker.ListQueueBroker") as broker_type:
        _ = create_broker(settings)

    broker_type.assert_called_once_with(
        url="redis://queue.example:6379/2",
        socket_timeout=None,
    )
