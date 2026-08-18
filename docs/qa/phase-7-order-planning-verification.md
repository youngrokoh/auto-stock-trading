# 7단계 주문 계획·위험검사 검증

- 상태: 검증 완료 (계획 계층, 실계좌 잔고 조회, 모의매매 콘솔 화면, 주문 제출 계층의 차단·동기화 경로) · 실제 주문 제출·체결은 다음 거래일 장중 대기
- 검증일: 2026-08-18
- 관련 결정: [ADR-0007](../decisions/0007-paper-order-planning-and-risk.md), [ADR-0008](../decisions/0008-paper-order-submission.md)
- 관련 계약: [주문 계획·위험검사 데이터 계약](../data/order-planning-risk-contract.md), [주문 제출·체결 동기화 계약](../data/order-submission-contract.md)
- 관련 API: [모의투자 주문 계획 읽기 API](../api/trading-api.md)

## 범위

계획 계층(계좌 조회 → 목표 포지션 → 결정적 위험검사 → 주문 계획 저장 → 자동매매 상태 머신)과
모의매매 콘솔 화면, 그리고 주문 제출 계층(제출·체결 동기화·취소)의 검증을 함께 기록한다. 실제 주문
전송은 주문 허용시간 안에서만 가능하므로 아래에 절차와 대기 항목으로 남긴다.

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

## 모의매매 콘솔 화면 검증 (2026-08-18 21:05~21:20 KST)

승인 시안 4a를 구현하고 Chromium 실브라우저로 390·768·1360px과 다크 모드를 확인했다.

| 항목 | 결과 |
|---|---|
| 읽기 API 확장 | `GET /api/trading/risk-limits`가 실제 모의계좌 스냅샷(NAV 10,000,000원)으로 13개 한도를 반환. 최소 현금 비중 현재값 1.000000·소진율 0.200000, 업종별 비중은 `MISSING_SECTOR_DATA`, 카운터 항목은 0. `GET /api/trading/orders`는 아직 계획된 주문이 없어 빈 배열 |
| 빈 데이터베이스(CI 동등) | 마이그레이션만 적용한 새 DB에 붙여 조회하면 금액 기준 한도 7종이 `MISSING_SNAPSHOT`·`MISSING_SESSION_OPEN_NAV`로, 카운터 4종은 0으로 응답하고 화면은 값 대신 사유 코드와 점선 막대를 표시 |
| 실브라우저 QA | 라이트·다크 × 390/768/1360px 6개 조합에서 콘솔 오류 0건, 가로 오버플로 없음, `postgresql://`·`redis://` 문자열 없음. 태블릿은 승인 접기 규칙(52px 레일 유지·내비 패널 숨김·1열·KPI 3열)대로 접힘 |
| 모바일 탭바 | 운영·시장·기업·ETF·전략·매매 6개로 확장. 390px에서 탭 폭 65px·높이 58px로 터치 대상 44px 규칙 유지 |
| 계좌번호 비노출 | 화면 텍스트에 계좌번호 8자리 패턴이 없고 해시 참조 `4aec6939a6d3`만 표시. e2e에 정규식 단언 추가 |
| 표 레이아웃 | 계획·거절 주문과 보유 종목이 있는 상태의 표 레이아웃은 주입 fixture로 확인했다(제품 코드는 실제 API만 사용). 체결 열은 줄표, 거절 행은 `거절 · RISK_UNCLASSIFIED_EXPOSURE` 배지로 표시된다. 실데이터 대조는 아래 다음 거래일 항목에서 수행한다 |
| 자동화 검증 | 백엔드 396건(위험 소진율 20건·주문 목록·`risk_state` 통합 3건 포함), 프런트 vitest 51건(trading 10건), e2e 24건 × 실데이터·빈 DB 두 모드 |

제어 경계는 사용자 결정대로 유지했다. 화면에는 일시정지·비상정지 버튼이 없고 자동매매 상태와
전이 이력만 표시하며, 상태 변경은 `worker/execution/planning.py --automation <state>` 안내로만 남긴다.

## 주문 제출 계층 검증 (2026-08-18 21:50~22:10 KST · 주문 미전송)

승인된 [ADR-0008](../decisions/0008-paper-order-submission.md)에 따라 제출·동기화·취소를 구현하고,
장 마감 시간이라 **증권사에 주문을 보내지 않는 경로만** 실환경에서 확인했다.

| 항목 | 결과 |
|---|---|
| 모의 TR 실측 | 일별주문체결조회 `VTTC8001R`은 모의환경에서 동작(`rt_cd=0`, 내역 없으면 `msg_cd=70070000`, `output1` 빈 배열, `output2` 5개 합계 필드). 정정취소가능주문조회 `VTTC8036R`은 **모의 미지원**(`rt_cd=1`, `msg_cd=90000000`)이라 미체결 판정을 일별주문체결의 잔여 수량으로 설계했다 |
| 비활성 상태 제출 | `blocked block_code=AUTOMATION_NOT_RUNNING submitted=0`. 증권사 호출 없음 |
| 허용시간 밖 제출 | 자동매매를 `RUNNING`으로 두고 22:04 KST에 실행해도 `blocked block_code=MARKET_CLOSED submitted=0`. 증권사 호출 없음 |
| 체결 동기화 (실호출) | `updated=0 problems=0 paused=False`. 조회 원본이 `operations.raw_api_response`(`order_fills`, 274바이트)에 저장되고 요청 지문은 계좌 해시 `4aec6939a6d3`만 포함. 저장된 원본에 계좌번호·계좌번호+상품코드 문자열이 없음을 프로그램으로 확인 |
| 비상정지 | `state=emergency_stop cancel_requested=0 cancel_failed=0`(미체결 주문 없음). 보유 청산 시도 없음. 검증 후 `disabled`로 되돌렸다 |
| 자동화 검증 | 백엔드 439건(체결 동기화 순수 함수 14건, 제출 유스케이스 17건, 주문 어댑터 9건, 저장 통합 4건 추가), 프런트 vitest 54건 |

### 다음 거래일 장중 검증 절차 (주문 전송 포함)

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
uv run python -m auto_stock_trading.worker.execution.submission --submit --plan-id <plan_id>
uv run python -m auto_stock_trading.worker.execution.submission --submit --plan-id <plan_id>   # 재실행이 두 번 보내지 않음
uv run python -m auto_stock_trading.worker.execution.submission --sync
uv run python -m auto_stock_trading.worker.execution.submission --emergency-stop   # 미체결 취소 시도
uv run python -m auto_stock_trading.worker.execution.submission --sync             # 취소 확정
uv run python -m auto_stock_trading.worker.execution.planning --automation disabled
```

확인할 것: 제출 응답의 `ODNO`·`KRX_FWDG_ORD_ORGNO` 저장, `output1` 필드명 계약 일치, 부분체결·전량
체결·취소의 상태 전이, 재실행 시 주문 수 불변, 콘솔 화면 B·C 표의 실데이터 표시.

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

- 실제 주문 전송·체결·취소의 장중 검증(위 절차)과 콘솔 화면 B·C 표 실데이터 대조
- 주문 정정(수량·가격 변경)과 실시간 체결통보(웹소켓), 자동 스케줄 제출
- 서버 재시작 후 상태 복구 시나리오 테스트(현재는 거래일 변경 복귀만 검증)
- 주문·위험 이벤트 알림(웹·메신저)
