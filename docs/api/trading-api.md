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
| `GET` | `/api/trading/orders` | 계획 경계를 넘어 최신 순으로 나열한 주문 (`limit` 기본 50 · 1~200) |
| `GET` | `/api/trading/risk-limits` | 정책 §3 한도 13종의 현재 소진율과 §4 주문 가능 조건 |

`environment`는 서버 설정(`AUTO_STOCK_KIS_ENVIRONMENT`)의 값이며 응답에 항상 포함된다.

## 응답 계약

- **계좌번호 원문을 노출하지 않는다.** 스냅샷은 `account_reference`(계좌번호+상품코드 sha256의 앞
  12자)만 포함한다. `nav`는 우리 계산값이고 `broker_net_asset`은 증권사 보고값(대조용)이다.
- 자동매매 응답은 세 값을 분리한다: `state`(지금 동작을 지배하는 상태), `stored_state`(저장된 사실 그대로), `stale_reason_code`(되돌린 사유, 같으면 `null`). **거래일이 바뀌면 `state`가 `disabled`가 된다** — 거래 안전 정책 §6이 "서버 재시작·거래일 변경·자격증명 환경 변경 시 항상 `DISABLED`"로 정하기 때문이다. 조회는 저장 기록을 고쳐 쓰지 않고 지금 성립하는 값만 계산한다.
- 자동매매 상태 행이 없으면 정책 기본값 `disabled`로 응답하고 `changed_at`은 `null`이다. 이벤트에는
  상태 전이(`state_change`), 외부 API 실패(`api_failure`), 대조 불일치(`reconcile_problem`),
  체결통보 리스너 상태(`listener_state`), 사람이 확인한 대조 종결(`attestation`)이 함께 시간 역순으로
  담긴다. `listener_state`의
  `reason_code`는 `LISTENER_ATTACHED`·`LISTENER_DETACHED`·`LISTENER_ERROR` 또는
  `NOTIFICATION_UNPARSABLE`이며 상세는
  [실시간 체결통보 계약](../data/realtime-fill-notification-contract.md)에 있다. `attestation`의
  `reason_code`는 `HUMAN_ATTESTED`이고 `detail`에 실행자와 근거가 담긴다
  ([ADR-0010](../decisions/0010-human-attested-order-reconciliation.md)).
- 계획 목록은 차단된 계획도 포함하며 `status`(`created`·`blocked`), `block_code`, 주문 수와 거절
  수를 준다. 계획 상세는 각 주문의 기준가·출처·수신 시각과 적용된 모든 규칙의 한도값·예상값·통과
  여부(`risk_decisions`)를 포함한다.
- 거절 주문은 `state="rejected"`와 `reject_code`(정책 §7.2 차단 코드 또는 `RISK_*` 규칙 코드)를
  가지며, 기준가를 얻지 못한 주문은 `limit_price`·`reference_price`가 `null`이다. 값을 만들지 않는다.
- 없는 `plan_id`는 `404`, UUID가 아닌 `plan_id`와 범위를 벗어난 `limit`은 `422`다.

## 주문 목록

`GET /api/trading/orders`는 주문을 생성 시각 역순으로 반환한다. 각 항목은 소속 계획(`plan_id`),
거래일, 생성 시각, 종목, 구분, 수량, 저장된 체결 수량(`filled_quantity`), 지정가와 기준가·출처·수신
시각, 상태, 거절 사유를 포함한다. 위험검사 판정은 포함하지 않고 계획 상세에서 조회한다. 주문 제출
단계가 없는 동안 `filled_quantity`는 항상 0이며 값을 만들지 않는다.

## 위험 한도 소진율

`GET /api/trading/risk-limits`는 [주문 계획·위험검사 데이터 계약](../data/order-planning-risk-contract.md)의
한도 소진율 정의를 그대로 반환한다.

- `items`는 정책 §3 표 순서의 13개 규칙이며 각 항목은 `rule_code`, `basis`, `comparison`,
  `limit_value`, `current_value`, `usage_ratio`, `reason`을 가진다. 소진율은 1.0이 한도 도달이고
  1.0을 넘으면 위반이다.
- 계산 근거는 응답에 함께 담긴다: `evaluated_at`(계산 시각), `basis_date`(일일 카운터 기준 거래일),
  `snapshot_id`·`snapshot_as_of`·`nav_basis`(기준 스냅샷), `session_open_nav`, `peak_nav`.
- 값을 만들 수 없으면 `current_value`·`usage_ratio`가 `null`이고 `reason`에 사유 코드가 담긴다
  (`MISSING_SNAPSHOT`·`MISSING_SESSION_OPEN_NAV`·`MISSING_PEAK_NAV`·`MISSING_SECTOR_DATA`·`ZERO_BASIS`).
  업종별 비중은 업종 분류 원천이 없어 항상 `MISSING_SECTOR_DATA`다.
- `conditions`는 정책 §4의 주문 허용시간·기준가 최대 지연·지정가 허용 범위·API 실패 집계 창이며
  화면이 한도를 하드코딩하지 않도록 서버가 제공한다. 값은 모의투자 한도이고 실전 한도는 전환 게이트
  통과 후 별도로 정의한다.
