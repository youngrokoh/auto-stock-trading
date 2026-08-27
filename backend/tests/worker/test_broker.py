"""Taskiq 브로커. 큐 이름이 워커 프로세스 경계와 일치해야 한다.

같은 큐를 여러 워커가 소비하면 **자기가 모르는 작업을 집어 조용히 버린다.** 2026-08-27 실측:
주문 제출 슬롯이 시장데이터 워커에 잡혀 사라졌고(어제 6개 중 4개, 오늘 1개 중 0개), 로그에는
`task ... is not found` 한 줄만 남았다. 예약이 발행됐다는 기록과 실행되지 않았다는 사실 사이에
아무 연결이 없다.
"""

from unittest.mock import patch

from pydantic import SecretStr

from auto_stock_trading.settings.runtime import Settings
from auto_stock_trading.worker import (
    investor_flow_schedule,
    market_calendar_schedule,
    market_data,
)
from auto_stock_trading.worker.broker import (
    DEFAULT_QUEUE,
    ORDER_SUBMISSION_QUEUE,
    create_broker,
)
from auto_stock_trading.worker.broker import broker as default_broker
from auto_stock_trading.worker.execution.submission_schedule import (
    broker as submission_broker,
)


def test_create_broker_disables_read_timeout_for_blocking_queue() -> None:
    settings = Settings(valkey_url=SecretStr("redis://queue.example:6379/2"))

    with patch("auto_stock_trading.worker.broker.ListQueueBroker") as broker_type:
        _ = create_broker(settings)

    broker_type.assert_called_once_with(
        url="redis://queue.example:6379/2",
        socket_timeout=None,
        queue_name="taskiq",
    )


def test_a_named_queue_is_passed_through() -> None:
    settings = Settings(valkey_url=SecretStr("redis://queue.example:6379/2"))

    with patch("auto_stock_trading.worker.broker.ListQueueBroker") as broker_type:
        _ = create_broker(settings, queue_name=ORDER_SUBMISSION_QUEUE)

    broker_type.assert_called_once_with(
        url="redis://queue.example:6379/2",
        socket_timeout=None,
        queue_name=ORDER_SUBMISSION_QUEUE,
    )


def test_the_order_path_does_not_share_a_queue_with_the_default_worker() -> None:
    """주문 제출 슬롯이 다른 워커에 잡히면 조용히 사라진다(2026-08-27 실측)."""
    assert submission_broker.queue_name == ORDER_SUBMISSION_QUEUE
    assert submission_broker.queue_name != default_broker.queue_name
    assert submission_broker is not default_broker


def test_jobs_served_by_the_same_worker_share_one_queue() -> None:
    """한 워커가 함께 소비하는 작업은 같은 큐여야 한다. 나뉘면 한쪽이 굶는다.

    시장 데이터·시장 달력·투자자별 수급은 한 프로세스에서 돌므로 기본 큐를 공유한다.
    """
    assert default_broker.queue_name == DEFAULT_QUEUE
    assert market_data.broker is default_broker
    assert market_calendar_schedule.broker is default_broker
    assert investor_flow_schedule.broker is default_broker
