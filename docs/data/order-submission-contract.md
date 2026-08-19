# 주문 제출·체결 동기화 계약

- 상태: 구현 기준
- 작성일: 2026-08-18
- 승인: 사용자가 2026-08-18에 [ADR-0008](../decisions/0008-paper-order-submission.md)의 네 가지 결정을 승인
- 관련 결정: [ADR-0008](../decisions/0008-paper-order-submission.md), [ADR-0007](../decisions/0007-paper-order-planning-and-risk.md)
- 관련 정책: [거래 안전 정책](../spec/trading-safety-policy.md), [모의투자·실전투자 전환 게이트](../spec/paper-to-live-gate.md)
- 관련 계약: [주문 계획·위험검사 데이터 계약](order-planning-risk-contract.md), [실시간 체결통보 계약](realtime-fill-notification-contract.md)
- 관련 API: [모의투자 주문 계획 읽기 API](../api/trading-api.md)

## 목적

위험검사를 통과해 저장된 `PLANNED` 주문을 KIS 모의환경에 제출하고, 증권사 사실로 체결·취소·거절
상태를 확정하는 경로의 정의를 고정한다. 실전 환경은 이 계약의 범위가 아니며 전환 게이트를 따른다.

## 원칙

1. **사람이 실행할 때만 주문이 나간다.** 제출·취소는 worker CLI 명령으로만 수행하고 HTTP 쓰기
   경로를 만들지 않는다. 자동 스케줄 제출은 별도 승인 사항이다.
2. **증권사가 체결의 근거다.** 체결 수량·평균단가·취소 여부는 증권사 응답으로만 갱신하고 내부에서
   추정하지 않는다.
3. **설명할 수 없는 불일치는 차단한다.** 자동으로 정리하지 않고 사유를 남기고 자동매매를 멈춘다.
4. **원본은 append-only.** 제출·취소·조회 응답 원본을 그대로 보존하고 정규화 상태와 분리한다.
5. **상태는 전이로만 바뀐다.** 주문당 현재 상태 1행과 append-only 이벤트 로그를 유지한다.
6. **계좌번호 원문은 남기지 않는다.** 요청 지문·저장 원본·응답·로그에 12자 해시 참조만 쓴다.

## 사용하는 KIS 모의 TR

| 용도 | 엔드포인트 | 모의 TR | 확인 |
|---|---|---|---|
| 현금 매수 | `/uapi/domestic-stock/v1/trading/order-cash` | `VTTC0802U` | 실주문 검증 대기 |
| 현금 매도 | `/uapi/domestic-stock/v1/trading/order-cash` | `VTTC0801U` | 실주문 검증 대기 |
| 정정·취소 | `/uapi/domestic-stock/v1/trading/order-rvsecncl` | `VTTC0803U` | 실주문 검증 대기 |
| 일별주문체결 조회 | `/uapi/domestic-stock/v1/trading/inquire-daily-ccld` | `VTTC8001R` | 2026-08-18 실호출 확인 |

실측 한계(그대로 기록한다):

- 정정취소가능주문조회(`VTTC8036R`)는 모의투자에서 제공되지 않는다(`rt_cd=1`,
  `msg_cd=90000000`). 미체결 목록은 일별주문체결조회의 잔여 수량으로만 판정한다.
- 일별주문체결조회에 내역이 없으면 `rt_cd=0`, `msg_cd=70070000`, `output1`은 빈 배열이고
  `output2`는 `tot_ord_qty`·`tot_ccld_qty`·`tot_ccld_amt`·`prsm_tlex_smtl`·`pchs_avg_pric`를 준다.
- **모의환경에서는 시각과 무관하게 `output1`이 빈 배열이다.** 2026-08-19에 체결된 주문이 있는 상태로
  장중 6가지(`CCLD_DVSN`·`INQR_DVSN`·`INQR_DVSN_1`·`INQR_DVSN_3`·`SLL_BUY_DVSN_CD` 조합)와 마감 후
  3가지(`CCLD_DVSN=01`, `INQR_DVSN_3=01`, `INQR_DVSN=01`+`PDNO`) 조합을 시도했고 9가지 모두
  `rt_cd=0`, `msg_cd=70070000`("조회할 내역(자료)이 없습니다"), `output1` 길이 0이었다. 같은 응답의
  `output2`는 그날 체결을 정확히 집계했다(`tot_ord_qty=5`, `tot_ccld_qty=5`,
  `tot_ccld_amt=1244250`, `pchs_avg_pric=248850`).
- 따라서 **이 TR로는 주문별 체결을 확정할 수 없다**(장중만의 문제가 아니다). 장중 확정은 2026-08-19에
  [ADR-0009](../decisions/0009-realtime-fill-notification.md)로 도입한
  [실시간 체결통보](realtime-fill-notification-contract.md)가 담당한다. **ADR-0009 결정 1이 예정한
  "마감 후 이 조회로 재대조"는 모의환경에서 수행할 수 없다.** 대체 수단(집계 `output2` 기반 교차 확인
  또는 사람이 확인한 관리 전이)은 사용자 결정 사항이며 이 계약에 아직 없다.
- 동기화가 이 응답을 받으면 대조할 행이 없으므로 상태를 바꾸지 않고 문제도 만들지 않는다(fail-safe).
  값을 추정해 `FILLED`로 바꾸지 않는다.
- 제출 응답 계약은 실주문으로 검증됐다: `rt_cd=0`, `msg_cd=40600000`, `output`에
  `KRX_FWDG_ORD_ORGNO`·`ODNO`·`ORD_TMD`가 모두 존재한다. 취소 실패도 사실로 기록된다
  (`rt_cd=1`, `msg_cd=40330000` "모의투자 정정/취소할 수량이 없습니다").

## 제출

제출 전 다음을 모두 만족해야 한다. 하나라도 어긋나면 주문을 보내지 않는다.

- 실행 환경이 모의(`paper`)다.
- 자동매매 상태가 `RUNNING`이다.
- 서울 기준 오늘이 검증된 달력의 거래일이고 정책 §4의 주문 허용시간(09:05~15:15) 안이다.
- 대상 주문이 `PLANNED` 상태이고 수량·지정가가 모두 양수다.
- 계획의 거래일이 오늘이다. 지난 거래일의 계획은 제출하지 않는다.
- 같은 환경의 체결통보 리스너가 부착돼 있다. 어긋나면 `LISTENER_NOT_ATTACHED`로 차단한다
  ([실시간 체결통보 계약](realtime-fill-notification-contract.md)).

요청 본문은 `CANO`, `ACNT_PRDT_CD`, `PDNO`(6자리), `ORD_DVSN`(`00` 지정가), `ORD_QTY`, `ORD_UNPR`
이다. 응답 `output`의 `KRX_FWDG_ORD_ORGNO`(지점번호), `ODNO`(주문번호), `ORD_TMD`(주문시각)를
주문 행에 저장한다.

| 응답 | 처리 |
|---|---|
| `rt_cd = 0` | `PLANNED → SUBMITTED` 전이, 주문번호·지점번호·제출 시각 저장 |
| `rt_cd ≠ 0` | `PLANNED → REJECTED` 전이, 사유 코드는 증권사 `msg_cd` |
| 파싱 실패·주문번호 없음 | 상태를 바꾸지 않고 실패로 기록한다. 주문번호를 저장하지 못하면 동기화가 그 증권사 주문을 내부와 맞출 수 없으므로 대조 불일치(`UNKNOWN_BROKER_ORDER`)로 차단된다 |
| 전송 실패(타임아웃 등) | `api_failure` 이벤트 기록. 5분 내 3회면 정책 §3의 `RISK_API_FAILURES`로 일시정지 |

## 체결 동기화

일별주문체결조회를 거래일 단위로 조회해 주문번호(`odno`)로 내부 주문과 맞춘다.

| 증권사 상태 | 내부 전이 |
|---|---|
| 체결 수량 0, 잔여 있음 | 전이 없음(`SUBMITTED` 유지) |
| 0 < 체결 수량 < 주문 수량 | `PARTIALLY_FILLED` |
| 체결 수량 = 주문 수량 | `FILLED` |
| 취소 표시(`cncl_yn = Y`)이고 체결 수량 0 | `CANCELED` |
| 거절 수량이 주문 수량과 같음 | `REJECTED` |

체결 수량과 평균 체결가는 증권사 값으로 갱신한다. 체결 수량은 줄어들 수 없으며 감소가 관측되면
불일치로 판정한다.

## 대조와 차단

다음은 설명할 수 없는 불일치이며 자동으로 정리하지 않는다.

| 상황 | 처리 |
|---|---|
| 증권사에 있으나 내부에 없는 주문번호 | `ACCOUNT_NOT_RECONCILED` 사유로 자동매매 `PAUSED`, 신규 주문 차단 |
| 내부 주문 수량을 초과하는 체결 수량 | 같음 |
| 체결 수량 감소 | 같음 |
| 종결 상태 주문의 체결 수량 변경 | 같음 |

차단 상태에서 조회는 계속 가능하다. 재개는 사람이 원인을 확인한 뒤 CLI로 상태를 전이한다.

## 취소

취소 요청 본문은 `CANO`, `ACNT_PRDT_CD`, `KRX_FWDG_ORD_ORGNO`, `ORGN_ODNO`, `ORD_DVSN`,
`RVSE_CNCL_DVSN_CD`(`02` 취소), `ORD_QTY`, `ORD_UNPR`(`0`), `QTY_ALL_ORD_YN`(`Y`)이다.

- 대상은 `SUBMITTED`·`PARTIALLY_FILLED` 상태이고 증권사 주문번호가 있는 주문이다. 이미 전량
  체결된 주문의 취소는 증권사가 거절하며(`40330000`) 실패로 기록된다.
- `rt_cd = 0`이면 취소 요청 사실을 이벤트로 남기고, 상태 확정은 동기화가 증권사 사실로 한다.
- `rt_cd ≠ 0`이면 실패를 사유 코드와 함께 남기고 상태를 바꾸지 않는다.
- `EMERGENCY_STOP` 전이 시 위 대상 전체에 취소를 시도한다. 실패가 하나라도 있으면 차단 상태를
  유지한다. 보유 종목 청산은 하지 않는다.

## 저장

기존 `trading` 스키마를 확장한다(리비전 `20260818_0015`).

| 컬럼 | 의미 |
|---|---|
| `order.broker_org_no` | 증권사 지점번호(`KRX_FWDG_ORD_ORGNO`). 정정·취소의 필수 입력 |
| `order.broker_order_time` | 증권사 주문시각(`ORD_TMD`) 원문 |
| `order.submitted_at` | 제출 성공 시각(UTC) |
| `order.average_fill_price` | 증권사 평균 체결가. 체결 전에는 비어 있다 |

`order.broker_order_id`(`ODNO`)는 기존 컬럼을 쓰고, 같은 주문번호가 두 주문에 저장되지 않도록
`(broker_order_id)` 부분 유일 인덱스를 둔다. `automation_event.event_type`에 `reconcile_problem`을
추가해 대조 불일치를 상태 전이·API 실패와 구분한다. 제출·취소·조회 원본은
`operations.raw_api_response`에 append-only로 남기고(`order_submit`·`order_cancel`·`order_fills`),
요청 지문에는 계좌 해시 참조만 쓴다.

## 읽기 계약

`GET /api/trading/orders`는 제출 이후 정보를 함께 반환한다: `broker_order_id`, `submitted_at`,
`filled_quantity`, `average_fill_price`. 값이 없으면 `null`이며 만들지 않는다. 계좌번호 원문은
어떤 응답에도 포함되지 않는다.

## 검증 조건

- 주문 허용시간 밖, 비활성 상태, 다른 거래일 계획, 이미 제출된 주문에서는 증권사 호출이 발생하지
  않는다.
- 같은 제출 명령을 두 번 실행해도 증권사 주문이 하나만 생긴다.
- 체결 수량 증가, 부분체결, 전량 체결, 취소, 거절이 각각 정확한 상태 전이를 만든다.
- 내부에 없는 주문번호가 조회되면 자동매매가 `PAUSED`로 전이하고 사유가 `ACCOUNT_NOT_RECONCILED`다.
- 실제 모의계좌에서 주문 제출 → 체결 동기화 → 취소가 한 거래일 안에 관측된다.

## 이 단계의 한계 (기록)

- 정정(수량·가격 변경)은 취소 후 재계획으로 대체한다. 정정 TR은 취소와 같은 엔드포인트지만 목표
  포지션 재계산 규칙이 필요해 후속으로 둔다.
- 실시간 체결통보(웹소켓)는 2026-08-19에 [ADR-0009](../decisions/0009-realtime-fill-notification.md)로
  도입했다. 체결 확정은 그 경로가 담당한다. 이 문서의 동기화 명령은 남겨두지만, 모의환경에서는
  대조할 주문별 행이 오지 않으므로 실질적으로 아무 상태도 바꾸지 않는다(위 실측 한계 참조).
- 자동 스케줄 제출이 없으므로 신호 발생과 제출 사이 지연은 사람의 실행 시점에 의존한다.
- `output1` 필드명(`odno`·`pdno`·`ord_qty`·`tot_ccld_qty`·`rmn_qty`·`rjct_qty`·`cncl_yn`·`avg_prvs`)은
  모의환경에서 대조할 수 없다. 체결된 주문이 있는 날에도 행이 오지 않기 때문이다. 이 매핑은 실전
  전환 게이트에서 실전 TR로 확인한다.
- 제출·취소 응답은 2026-08-19 실주문으로 대조를 마쳤다.
- 부분 유일 인덱스는 주문번호가 거래일마다 재사용되지 않는다는 가정에 기댄다. 재사용이 관측되면
  계약을 고쳐 거래일을 포함한 유일성으로 바꾼다.
