# 주문·위험 이벤트 외부 알림 계약

- 상태: 승인
- 승인일: 2026-08-24
- 관련 결정: [ADR-0014 주문·위험 이벤트 외부 알림 경계](../decisions/0014-outbound-event-notification.md), [ADR-0009 실시간 체결통보 수신 경계](../decisions/0009-realtime-fill-notification.md), [ADR-0008 모의투자 주문 제출·체결 동기화 경계](../decisions/0008-paper-order-submission.md)
- 관련 정책: [거래 안전 정책](../spec/trading-safety-policy.md)
- 관련 계약: [주문 제출·체결 동기화 계약](order-submission-contract.md), [주문 계획·위험검사 데이터 계약](order-planning-risk-contract.md)

## 범위

이미 `trading` 스키마에 저장된 이벤트를 외부 메신저(Telegram)로 내보내는 경로를 정의한다. 새로운 사실을
만들지 않고, 조회·계산을 추가하지 않는다.

## 불변식

1. **알림은 사본이다.** 메신저로 나가는 모든 값은 저장된 행에서 파생한다.
2. **매매 경로는 알림을 모른다.** 아웃박스 행은 폴러가 투영하며, 주문·자동매매 쓰기 경로는 변경되지
   않는다.
3. **전송 실패는 매매를 막지 않는다.** 대신 실패가 사실로 남고 조회에 드러난다.
4. **금지 필드는 어떤 경로로도 나가지 않는다.** 아래 §공개 범위의 금지 목록은 코드로 강제한다.
5. **at-least-once.** 같은 이벤트가 두 번 전달될 수 있으나(전송 후 커밋 실패), 아웃박스 유일 제약이
   중복 투영을 막는다. 메시지는 이벤트 식별자를 포함해 사람이 중복을 알아볼 수 있다.

## 원천과 선별 (ADR-0014 결정 3-1)

| 원천 | 대상 | 알림 종류 |
|---|---|---|
| `trading.order_event` | `previous_state != state`인 행 | `order_state` |
| `trading.automation_event` | `event_type = 'state_change'` | `automation_state` |
| `trading.automation_event` | `event_type = 'reconcile_problem'` | `reconcile_problem` |
| `trading.automation_event` | `event_type = 'api_failure'` | `api_failure` |
| `trading.automation_event` | `event_type = 'attestation'` | `attestation` |
| `trading.automation_event` | `event_type = 'schedule_blocked'` | `schedule_blocked` |
| `trading.risk_decision` | 차단 판정(통과하지 않은 행) | `risk_block` |

제외: `listener_state`(부착·해제 반복), 상태가 바뀌지 않는 주문 이벤트(부분 취소 요청·취소 실패 등
정보성 행), 통과한 위험 판정.

**심각도**는 두 단계다. `warning`: `reconcile_problem`, `api_failure`, `risk_block`,
`schedule_blocked`, `automation_state`가 `paused`·`emergency_stop`으로 갈 때. `info`: 나머지.

`schedule_blocked`는 자동 스케줄 제출이 차단된 사실이다(ADR-0015 결정 6). `listener_state`는 사람이
있을 때 정상 흐름이라 제외하지만, **그 때문에 자동 제출이 멈춘 사실은 알려야 한다** — 주문이 없는 것과
구분되지 않으면 감시가 성립하지 않는다.

## 공개 범위 (ADR-0014 결정 3)

보내는 필드:

| 필드 | 예 |
|---|---|
| 종목코드·종목명 | `005930 삼성전자` |
| 매매구분 | `매수`/`매도` |
| 수량 | `2주` |
| 지정가 | `250,000원` |
| 주문 상태 전이 | `submitted → filled` |
| 사유 코드 | `40600000`, `FILL_NOTIFICATION`, `RISK_SYMBOL_EXPOSURE` |
| 증권사 주문번호 | `0000117057` |
| 이벤트 시각 | `14:03:11 KST` |
| 자동매매 상태 | `running → paused` |

**금지 필드 (코드로 강제, 위반 시 전송하지 않고 실패로 기록):**

- 계좌번호와 그 해시 참조
- NAV, 현금 잔고, 결제잔액, 보유 종목 전체, 평가금액
- 노출 비율과 한도 사용률(분모가 NAV이므로)
- 자격증명(봇 토큰, `chat_id`, KIS·DART 키), 증권사 원본 응답
- 고객ID·계좌명(체결통보 원본에만 존재하며 저장 시 이미 마스킹됨)

위험 알림은 **위반한 규칙 코드와 거절 사실**만 보낸다. 초과 금액·비율은 보내지 않는다.

## 저장 (리비전 `20260824_0028`)

### `trading.notification_outbox`

| 열 | 규칙 |
|---|---|
| `id` | uuid |
| `environment` | `paper`/`live` |
| `source` | `order_event`/`automation_event`/`risk_decision` |
| `source_id` | 원천 행의 uuid |
| `kind` | 위 표의 알림 종류 |
| `severity` | `info`/`warning` |
| `body` | 실제로 보낼 최종 문자열. 금지 필드 검사를 통과한 결과만 저장한다 |
| `state` | `pending`/`sent`/`failed` |
| `attempts` | 전송 시도 횟수 |
| `last_error` | 마지막 실패의 코드·설명(토큰·URL 미포함) |
| `event_occurred_at` | 원천 이벤트 시각 — 정렬 기준 |
| `created_at`, `sent_at` | |

- UNIQUE `(environment, source, source_id)` — 중복 투영을 DB가 막는다.
- `state IN ('pending','sent','failed')`, `severity IN ('info','warning')` CHECK.
- `body`에 금지 문자열이 들어가는 것을 DB가 막을 수는 없다. 검사는 도메인 순수 함수가 하고, 통과하지
  못한 이벤트는 `failed`로 남기며 사유를 `last_error`에 적는다 — 조용히 버리지 않는다.

### `trading.notification_watermark`

| 열 | 규칙 |
|---|---|
| `environment` | UNIQUE |
| `projected_from` | 이 시각 이후 이벤트만 투영한다 |
| `created_at`, `updated_at` | |

첫 실행에서 당일 00:00 KST를 `projected_from`으로 기록한다. 과거 전체가 한꺼번에 알림이 되지 않게
하려는 것이며, 이후에는 워터마크를 옮기지 않는다 — 프로세스가 멈춰 있던 기간의 이벤트도 다시 켜면
투영된다.

## 전송

- `POST https://api.telegram.org/bot<token>/sendMessage`, 본문 `chat_id`·`text`.
- 성공 판정은 HTTP 200 **그리고** 응답 `ok=true`다. 200에 `ok=false`가 오는 경우를 성공으로 보지 않는다.
- 실패는 `error_code`와 `description`을 `last_error`에 기록한다. **URL은 로그·기록에 남기지 않는다 —
  토큰이 경로에 들어간다.**
- 단일 대화 초당 1건을 넘지 않도록 직렬 전송하며 최소 간격을 둔다(공식 FAQ: "avoid sending more than
  one message per second").
- `429`는 재시도 대상이다. 응답에 `parameters.retry_after`가 있으면 그 값을, 없으면 기본 백오프를 쓴다.
- 재시도 상한은 **5회**다. 상한에 닿으면 `failed`로 남기고 자동 삭제하지 않으며 다음 폴의 대상이
  아니다(ADR-0014 결정 8). 상한이 없으면 도달 불가능한 알림이 매 폴마다 초당 1건 한도를 소모한다.
  상태 판정은 시도 횟수를 올리는 같은 `UPDATE` 안에서 한다 — 읽고 나서 쓰면 폴이 겹칠 때 횟수가
  어긋난다.

### 폴 상한과 요약 대체 (ADR-0014 결정 7)

한 번의 폴에서 보낼 개별 메시지 수에 상한을 둔다. 대상이 상한을 넘으면 **개별 전송을 하지 않고 요약 한
건**을 보낸다.

- 요약은 종류별 건수와 가장 심각한 항목, 그리고 **생략된 건수**를 명시한다.
- 요약으로 대체된 아웃박스 행은 `sent`가 아니라 그대로 `pending`으로 남기지 않는다: 같은 알림이 다음
  폴에서 다시 개별 전송되면 요약의 의미가 없다. 대체된 행은 `sent`로 표시하고 `last_error`에
  `SUMMARIZED`를 남겨 개별 전달되지 않았음을 사실로 보존한다.

## 조회

`GET /api/trading/notifications` — 발신 현황.

| 필드 | 내용 |
|---|---|
| `pending` | 미발신 건수 |
| `failed` | 실패 건수 |
| `sent_today` | 당일 발신 건수 |
| `oldest_pending_at` | 가장 오래된 미발신 이벤트 시각(없으면 `null`) |
| `recent` | 최근 항목(종류·심각도·상태·시각·사유) |

이 응답에도 §공개 범위의 금지 필드는 담지 않는다. 콘솔은 `pending`·`failed`를 드러내 "알림이 조용한
것"과 "보낼 것이 없는 것"을 구분한다.

## 실행

```bash
# 자격증명이 있을 때만 동작한다
uv run python -m auto_stock_trading.worker.notifications --dispatch   # 한 번 투영 + 전송
uv run python -m auto_stock_trading.worker.notifications --status     # 발신 현황만 출력
```

기본 Compose에는 없다. `infra/compose.notifications.yaml` 오버라이드로만 켠다(ADR-0014 결정 6).

자격증명: `AUTO_STOCK_TELEGRAM_BOT_TOKEN_FILE`, `AUTO_STOCK_TELEGRAM_CHAT_ID_FILE`. 둘 중 하나라도 없으면
전송을 시도하지 않고 그 사실을 출력한다(투영은 자격증명 없이도 가능하지만, 자격증명 없는 실행은 아무
것도 하지 않는다 — 워터마크만 기록하고 끝나면 그 사이 이벤트가 조용히 지나간다).

## 미실측 (봇 토큰 확보 후 실측해 이 절을 교체한다)

봇 토큰이 없어 실제 호출을 하지 못했다. 다음은 **문서 기준**이며 단정하지 않는다.

1. `429` 응답이 `parameters.retry_after`를 항상 싣는지.
2. `text` 길이 상한(4096자로 알려져 있으나 공식 문서에서 해당 절을 확인하지 못했다). 구현은 상한을
   넘지 않도록 잘라내고 잘라낸 사실을 표시한다.
3. 전송 후 응답 유실 시 재시도가 중복 메시지를 만드는지(at-least-once의 실제 결과).
4. 한글 메시지의 인코딩·줄바꿈 처리.

## 완료 조건

- 선별 규칙이 실제 이벤트 표본에서 대상과 제외를 정확히 가른다.
- 금지 필드가 포함된 메시지는 전송되지 않고 실패로 기록된다.
- 같은 이벤트를 두 번 투영하지 않는다(DB 유일 제약으로 확인).
- 전송 실패가 매매 경로를 막지 않는다.
- 폴 상한 초과 시 요약 한 건으로 대체되고 생략 건수가 표시된다.
- 자격증명이 없으면 전송을 시도하지 않고 워터마크를 옮기지 않는다.
