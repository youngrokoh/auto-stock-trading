# 7단계 주문 계획·위험검사 검증

- 상태: 검증 완료 (계획 계층 범위, 실계좌 잔고 조회 포함) · 주문 허용시간 내 계획 생성만 다음 거래일 대기
- 검증일: 2026-08-18
- 관련 결정: [ADR-0007](../decisions/0007-paper-order-planning-and-risk.md)
- 관련 계약: [주문 계획·위험검사 데이터 계약](../data/order-planning-risk-contract.md)
- 관련 API: [모의투자 주문 계획 읽기 API](../api/trading-api.md)

## 범위

이 단계는 증권사에 주문을 보내지 않는다. `PLANNED` 주문 생성까지의 경로(계좌 조회 → 목표 포지션 →
결정적 위험검사 → 주문 계획 저장 → 자동매매 상태 머신)만 검증한다.

## 자동 검증 (2026-08-18)

| 항목 | 결과 |
|---|---|
| 위험검사 경계값 | 정책 §3·§4의 16개 규칙을 41개 테스트로 검증. 일일 손실(−1.99%/−2.00%/−2.01%), 고점 낙폭(−4.99%/−5.00%/−5.01%), 하루 주문 시도(19/20/21), 연속 거절(2/3/4), 주문 허용시간(09:04/09:05/15:15/15:16), 기준가 신선도(10초/11초) 모두 아래·같음·초과를 확인 |
| 주문 상태 머신 | 승인 그래프의 허용 전이와 금지 전이(계획→체결, 종결 상태에서의 전이 등)를 29개 테스트로 고정. 자동매매 전이도 정책 §6대로 검증(`PAUSED→RUNNING` 금지, `PAUSED→ARMED` 허용, 어느 상태에서든 비상정지 허용) |
| 호가단위·지정가 | KRX 7개 구간 경계와 ETF 5원 고정, 반올림, ±1% 밴드 검증 |
| 계획 유스케이스 | 16개 테스트. 정상 계획(분할 2건), 재계획 시 동일 `client_order_id`, 비활성·장마감·미조정·정지 규칙 차단, 소스 실패의 `api_failure` 기록과 전파, 매도 전량 분할 |
| 저장·조회 | PostgreSQL 통합 8건. 계획·주문·위험판정 왕복, 중복 `client_order_id`가 두 번째 주문을 만들지 않음, 거절 주문 보존, 상태 전이·이벤트 영속, 잘못된 전이 거부, API 실패 5분 창 집계, 스냅샷·장시작/고점 NAV, 카운터 집계 |
| 읽기 API | 5건. 상태·이벤트, 스냅샷(해시 참조만), 계획 목록·상세, 404·422 |
| 백엔드 전체 | 363건 통과, ruff·basedpyright 무경고 |

## 실환경 검증 (2026-08-18, 서울 14:24~14:26 · 주문 허용시간 내)

worker CLI와 실제 PostgreSQL로 확인했다.

| 시나리오 | 결과 |
|---|---|
| 자동매매 기본 비활성 상태에서 계획 실행 | `blocked block_code=AUTOMATION_NOT_RUNNING` 계획 행이 저장됨. 계좌·시세 외부 호출이 전혀 발생하지 않음(계좌 secret 없이도 차단 경로가 동작) |
| 상태 전이 | `disabled → armed → running → paused → disabled` 전이가 모두 저장되고 `automation_event`에 이전·현재 상태와 사유 코드(`USER_COMMAND`)로 남음 |
| `RUNNING`에서 계좌 secret 없이 계획 | 계좌 조회 실패를 `api_failure`(`account_balance:KisConfigurationError`)로 기록한 뒤 실행 중단. 계획 행을 만들지 않음(계약의 fail-closed 그대로) |
| 읽기 API | `GET /api/trading/automation`과 `/order-plans`를 실제 HTTP로 조회해 상태·이벤트 5건·차단 계획 1건을 확인. 응답에 계좌번호 원문이 없음 |
| 종료 상태 | 검증 후 자동매매를 `disabled`로 되돌렸다 |

## 실계좌 잔고 조회 검증 (2026-08-18 17:16~17:22 KST)

사용자가 `.secrets/kis-paper-account-number`(8자리)와 `.secrets/kis-paper-account-product`(`01`)를
제공한 뒤 실제 KIS 모의계좌로 검증했다.

| 항목 | 결과 |
|---|---|
| 잔고 조회 | `VTTC8434R` 첫 호출에 성공. 계약이 요구하는 `dnca_tot_amt`·`prvs_rcdl_excc_amt`·`scts_evlu_amt`·`tot_evlu_amt`·`nass_amt`가 실제 응답에 모두 존재해 엄격 파싱을 통과했다(응답 `output2`는 24개 필드 제공) |
| 스냅샷 값 | 예수금 10,000,000원 · 주문가능현금 10,000,000원 · 보유 평가금액 0원 · NAV 10,000,000원. 우리 계산 NAV와 증권사 보고 순자산금액(`nass_amt`)이 일치 |
| 계좌번호 비노출 | 저장된 원본 응답(945바이트)에 계좌번호와 `계좌번호+상품코드` 문자열이 모두 없음을 프로그램으로 확인. 저장·요청 지문·API 응답에는 해시 참조 `4aec6939a6d3`만 남는다 |
| 형식 검증 | 자리표시자(`<계좌번호8자리>`)가 파일에 들어간 실수를 재현했고, 계좌번호 8자리·상품코드 2자리 숫자 계약을 로드 시점에 검사해 KIS 호출 전에 실패하도록 고쳤다(값은 오류 메시지에 넣지 않음, 오형식 8건 테스트) |
| 읽기 API | `GET /api/trading/account-snapshots`가 해시 참조·현금·NAV·보유 목록을 반환 |
| 주문 허용시간 밖 계획 | 17:22 KST(허용시간 09:05~15:15 밖)에 자동매매를 `RUNNING`으로 두고 실행해도 `MARKET_CLOSED`로 차단되고 계좌·시세 외부 호출이 발생하지 않음. 검증 후 `disabled`로 되돌렸다 |

실측에서 발견해 고친 결함: asyncpg가 `numeric(24,0)`의 trailing zero를 지수 표기 `Decimal('1.000E+7')`로
돌려주어 API가 금액을 `1.000E+7`로 직렬화했다. 읽기 어댑터에서 원화 금액을 정수 표기로 정규화하고
통합 테스트에 문자열 단언을 추가했다.

## 다음 거래일 대기 항목

- **주문 허용시간 내 계획 생성**: 09:05~15:15 KST의 거래일에 아래를 실행하면 `PLANNED` 주문이 생성된다.
  현재 NAV 10,000,000원 기준 기대값은 종목 한도 10%(1,000,000원)와 주문 1건 한도 5%(500,000원)에 따라
  삼성전자 1주씩 3건이다.

  ```bash
  cd backend
  export AUTO_STOCK_KIS_APP_KEY_FILE=../.secrets/kis-paper-app-key
  export AUTO_STOCK_KIS_APP_SECRET_FILE=../.secrets/kis-paper-app-secret
  export AUTO_STOCK_KIS_ACCOUNT_NUMBER_FILE=../.secrets/kis-paper-account-number
  export AUTO_STOCK_KIS_ACCOUNT_PRODUCT_CODE_FILE=../.secrets/kis-paper-account-product
  uv run python -m auto_stock_trading.worker.execution.planning --account-snapshot
  uv run python -m auto_stock_trading.worker.execution.planning --automation armed
  uv run python -m auto_stock_trading.worker.execution.planning --automation running
  uv run python -m auto_stock_trading.worker.execution.planning --symbol 005930 --side buy
  uv run python -m auto_stock_trading.worker.execution.planning --automation disabled
  ```

- **보유 종목 정규화**: 모의계좌에 보유 종목이 없어 잔고 응답 `output1`(보유 수량·평균단가·평가금액)
  정규화는 fixture 계약 테스트로만 검증됐다. 주문 제출 단계에서 실제 체결이 생기면 실데이터로 대조한다.

## 정책 해석 기록

- 업종 분류 원천 데이터가 없어 두 종목 모두 미분류로 판정된다. 정책 §3의 "분류되지 않은 종목 합계
  NAV의 10%"가 적용되므로 **총 노출의 실질 상한이 NAV의 10%**다. 정책을 완화하지 않은 결과이며,
  지수 ETF를 미분류에서 제외할지는 사용자 결정과 업종 분류 수집이 필요하다.
- 백테스트(가용 현금 전량 매수)와 모의매매 계획(종목 10%·주문 5% 분할)의 사이징이 다르다. 백테스트에
  같은 사이징을 적용하는 작업은 후속이다.
- 배치 시세는 정책 §4의 10초 규칙을 만족할 수 없어 계획 시점에 현재가를 새로 조회한다.
- 시장 달력은 분봉 수집과 같은 기준으로 판정한다(누락·충돌은 차단, `pending` 검증은 허용). 모의
  환경에서 KIS 당일 확인이 꺼져 있는 동안 `CONFIRMED`를 요구하면 계획이 영구 차단되기 때문이다.

## 자동 검증 명령

```bash
cd backend
uv run pytest tests/risk tests/trading tests/brokers/test_kis_account.py \
  tests/api/test_trading_api.py tests/migrations
```

## 남은 범위

- 주문 제출·정정·취소·체결 동기화와 증권사 미체결 대조(`ACCOUNT_NOT_RECONCILED`의 실제 판정)
- 모의매매 콘솔 화면(승인 시안 4a)
- 서버 재시작 후 상태 복구 시나리오 테스트(현재는 거래일 변경 복귀만 검증)
- 주문·위험 이벤트 알림(웹·메신저)
