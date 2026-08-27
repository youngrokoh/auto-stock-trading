"""Taskiq 브로커. 큐 이름은 워커 프로세스 경계와 일치해야 한다.

`ListQueueBroker`는 큐 하나를 여러 소비자가 나눠 갖는다. 서로 다른 워커가 같은 큐를 보면 자기가
등록하지 않은 작업을 집어 **조용히 버린다** — 로그에 `task ... is not found` 한 줄만 남고, 예약이
발행됐다는 기록과 실행되지 않았다는 사실 사이에 아무 연결이 없다.

2026-08-27 실측: 주문 제출 슬롯이 시장데이터 워커에 잡혀 사라졌다(어제 6개 중 4개만, 오늘은
1개 중 0개). ADR-0015 결정 6이 "차단은 조용히 지나가지 않는다"로 만든 안전장치는 **도둑맞은
작업에는 닿지 않는다** — 차단 검사에 도달조차 못 하기 때문이다.

규칙은 하나다. **같은 워커 프로세스가 소비하는 작업은 같은 큐, 다른 워커가 소비하면 다른 큐.**
나누는 기준은 작업의 성격이 아니라 누가 꺼내는가다.
"""

from typing import Final

from taskiq_redis import ListQueueBroker

from auto_stock_trading.settings.runtime import Settings

# 기본 워커(`market_data:broker`)가 소비한다. 시장 데이터·시장 달력·투자자별 수급이 한 프로세스에서
# 돌므로 같은 큐를 쓴다.
DEFAULT_QUEUE: Final = "taskiq"
# 주문 제출 워커 전용. 주문 경로가 다른 워커에 잡히면 슬롯이 사라진다.
ORDER_SUBMISSION_QUEUE: Final = "taskiq-order-submission"


def create_broker(
    settings: Settings | None = None,
    queue_name: str = DEFAULT_QUEUE,
) -> ListQueueBroker:
    runtime_settings = settings or Settings()
    valkey_url = runtime_settings.valkey_url.get_secret_value()
    return ListQueueBroker(url=valkey_url, socket_timeout=None, queue_name=queue_name)


broker = create_broker()
