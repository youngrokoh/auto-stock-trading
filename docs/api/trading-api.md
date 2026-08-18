# 모의투자 주문 계획 읽기 API

- 상태: 구현됨
- 구현일: 2026-08-18
- 기준 경로: `/api/trading`
- 관련 결정: [ADR-0007](../decisions/0007-paper-order-planning-and-risk.md)
- 관련 계약: [주문 계획·위험검사 데이터 계약](../data/order-planning-risk-contract.md)

## 범위

자동매매 상태, 계좌 스냅샷, 주문 계획과 위험검사 판정을 읽기 전용으로 제공한다. 계획 생성과 상태
전이는 worker CLI(`uv run python -m auto_stock_trading.worker.execution.planning`)로만 수행하며,
HTTP로 주문을 만들거나 상태를 바꾸는 엔드포인트는 제공하지 않는다. 증권사 주문 제출은 이 단계의
범위가 아니다.

| 메서드 | 경로 | 응답 |
|---|---|---|
| `GET` | `/api/trading/automation` | 현재 자동매매 상태와 최근 이벤트 20건 |
| `GET` | `/api/trading/account-snapshots` | 계좌 스냅샷 목록 (`limit` 기본 20 · 1~100) |
| `GET` | `/api/trading/order-plans` | 주문 계획 목록 (`limit` 기본 20 · 1~100) |
| `GET` | `/api/trading/order-plans/{plan_id}` | 계획 상세와 주문·위험검사 판정 전체 |

`environment`는 서버 설정(`AUTO_STOCK_KIS_ENVIRONMENT`)의 값이며 응답에 항상 포함된다.

## 응답 계약

- **계좌번호 원문을 노출하지 않는다.** 스냅샷은 `account_reference`(계좌번호+상품코드 sha256의 앞
  12자)만 포함한다. `nav`는 우리 계산값이고 `broker_net_asset`은 증권사 보고값(대조용)이다.
- 자동매매 상태 행이 없으면 정책 기본값 `disabled`로 응답하고 `changed_at`은 `null`이다. 이벤트에는
  상태 전이(`state_change`)와 외부 API 실패(`api_failure`)가 함께 시간 역순으로 담긴다.
- 계획 목록은 차단된 계획도 포함하며 `status`(`created`·`blocked`), `block_code`, 주문 수와 거절
  수를 준다. 계획 상세는 각 주문의 기준가·출처·수신 시각과 적용된 모든 규칙의 한도값·예상값·통과
  여부(`risk_decisions`)를 포함한다.
- 거절 주문은 `state="rejected"`와 `reject_code`(정책 §7.2 차단 코드 또는 `RISK_*` 규칙 코드)를
  가지며, 기준가를 얻지 못한 주문은 `limit_price`·`reference_price`가 `null`이다. 값을 만들지 않는다.
- 없는 `plan_id`는 `404`, UUID가 아닌 `plan_id`와 범위를 벗어난 `limit`은 `422`다.
