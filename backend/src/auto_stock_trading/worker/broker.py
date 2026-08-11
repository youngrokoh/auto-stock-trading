from taskiq_redis import ListQueueBroker

from auto_stock_trading.settings.runtime import Settings


def create_broker(settings: Settings | None = None) -> ListQueueBroker:
    runtime_settings = settings or Settings()
    valkey_url = runtime_settings.valkey_url.get_secret_value()
    return ListQueueBroker(url=valkey_url, socket_timeout=None)


broker = create_broker()
