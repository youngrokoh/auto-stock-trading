# 7단계 주문 계획·위험검사 검증

- 상태: 검증 완료 (계획·제출·체결·취소를 실제 모의계좌에서 확인) · 장중 주문별 체결 조회 한계는 후속 결정 대기
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

## 장중 실주문 검증 (2026-08-19 09:06~09:30 KST · 실제 모의주문 전송)

사용자 승인(범위: 계획→제출→동기화→취소, 규모 종목 한도 10%)으로 실제 모의계좌에 주문을 보냈다.

| 단계 | 결과 |
|---|---|
| 계좌 스냅샷 | 09:06 NAV 10,000,000원으로 장 시작 NAV 고정 |
| 삼성전자 계획 | 기준가 249,750원(계획 시점 새 조회) → 지정가 250,000원(호가단위 500원 반올림, ±1% 밴드 통과). 주문 1건 한도 5%에 맞춰 2주씩 2건 = 1,000,000원, 종목 한도 10%와 정확히 일치 |
| 제출 (실주문) | `rt_cd=0`, `msg_cd=40600000` "모의투자 매수주문이 완료 되었습니다". 주문번호 `0000008637`·`0000008645`, 지점번호 `00950`, 주문시각 `092002`·`092004`를 저장. **제출 응답 계약(`KRX_FWDG_ORD_ORGNO`·`ODNO`·`ORD_TMD`)이 실데이터로 검증됐다** |
| 재실행 멱등성 | 같은 명령 재실행 시 `submitted=0`. 이미 `SUBMITTED` 상태라 증권사에 두 번 나가지 않는다 |
| 체결 사실 | 잔고조회로 삼성전자 4주 보유, 평균 248,750원, 매수금액 995,000원, 제세금 140원 확인. 일별주문체결 `output2`도 `tot_ccld_qty=4`로 전량 체결을 보고 |
| 보유 종목 정규화 | 잔고 응답 `output1`의 `hldg_qty=4`·`ord_psbl_qty=4`·`pchs_avg_pric=248750.0000`·`prpr=248500`·`evlu_amt=994000`·`evlu_pfls_amt=-1000`을 실데이터로 확인해 fixture로 승격했다(대기 항목 해소) |
| 취소 시도 | 비상정지 후 미체결 취소를 시도했으나 `rt_cd=1`, `msg_cd=40330000` "모의투자 정정/취소할 수량이 없습니다" — 이미 전량 체결됐기 때문이다. 취소 실패가 주문 이벤트로 기록되고 차단 상태가 유지됐다 |
| 화면 | 콘솔 B 좌표에 5건(철회 3·제출 2, 증권사 주문번호 표시), C 좌표에 삼성전자 4주 실데이터, KPI에 실제 NAV·현금·투자 비중·미체결 2건이 표시됐다. 1360·390px 콘솔 오류 0건, 가로 오버플로 없음, 계좌번호 미노출 |
| 종료 상태 | 자동매매를 `disabled`로 되돌렸다 |

### 실주문에서 발견해 고친 결함 3건

| 결함 | 증거 | 수정 |
|---|---|---|
| **예상 노출에 미체결·계획 주문 미반영** (정책 §2 위반) | 삼성 계획 1,000,000원이 있는데도 KODEX 계획의 `RISK_UNCLASSIFIED_EXPOSURE` 예상값이 0에서 시작해 3건이 추가 계획됨. 미분류 합계 1,916,470원 = NAV의 19.2%로 한도 10%를 초과 | 위험검사에 `PendingExposure` 입력을 추가해 그 거래일의 `planned`·`submitted`·`partially_filled` 주문의 미체결 금액(수량−체결수량 × 지정가)을 노출에 포함. 실데이터 재계획에서 KODEX가 `RISK_UNCLASSIFIED_EXPOSURE`로 거절됨을 확인. 잘못 만든 계획은 `--withdraw`로 철회(3건 `canceled`, 이력 보존) |
| **NAV가 예수금 총액 기준** (정책 §2 위반) | 체결 후 우리 NAV 10,995,000원 vs 증권사 순자산금액 9,999,860원. 예수금 총액은 미결제 매수분을 차감하지 않아 이중 계산 | NAV를 가수도정산금액(D+2 예수금) + 평가금액으로 계산. 수정 후 9,994,860원 = 증권사 값과 정확히 일치. 추가로 두 값이 다르면 `ACCOUNT_NOT_RECONCILED`로 주문 생성을 차단하는 가드를 넣었다 |
| **최소 현금 비중이 예수금 총액 기준** | 소진율 API가 현금 비중 100.05%를 보고(현금 100.05% + 주식 9.91% = 110%) | 판정·표시 모두 정산 기준 현금을 쓰도록 `AccountState.settled_cash`로 이름과 의미를 고정. 수정 후 90.09%로 현금+주식=100% |

### 미해결: 장중 주문별 체결 조회

일별주문체결조회(`VTTC8001R`)가 모의환경에서 **`output1`을 빈 배열로 반환**한다(`msg_cd=70070000`).
`CCLD_DVSN`·`INQR_DVSN`·`INQR_DVSN_1`·`INQR_DVSN_3`·`SLL_BUY_DVSN_CD` 조합 6가지를 모두 시도해도
같았고, `output2` 합계만 채워진다. 따라서 장중에는 주문별 체결을 증권사 사실로 확정할 수 없다.

- 내부 주문은 `SUBMITTED`로 남고 값을 만들지 않는다. 미체결이 존재하므로 이후 계획은
  `ACCOUNT_NOT_RECONCILED`로 차단된다(fail-closed 설계 그대로 동작).
- **마감 후 재확인 결과(2026-08-19 15:42 KST): 여전히 비어 있다.** 체결된 주문 3건(우리 2건 4주 +
  사용자 수동 1주)이 있는 상태에서 `--sync`를 실행했고 `updated=0 problems=0`이었다. 저장된 원본은
  `rt_cd=0`, `msg_cd=70070000`("조회할 내역(자료)이 없습니다"), `output1` 길이 0이고 `output2`만
  `tot_ord_qty=5`·`tot_ccld_qty=5`·`tot_ccld_amt=1244250`·`pchs_avg_pric=248850`으로 집계했다.
  파라미터 3가지(`CCLD_DVSN=01`, `INQR_DVSN_3=01`, `INQR_DVSN=01`+`PDNO=005930`)를 더 시도해도 같았다.
  장중 6가지를 합쳐 **9가지 조합에서 모두 동일**하므로, 이 TR은 모의환경에서 주문별 행을 주지 않는다고
  기록한다(장중만의 문제가 아니다).
- **해소 결정**: 2026-08-19에 사용자가 실시간 체결통보 도입을 승인했다
  ([ADR-0009](../decisions/0009-realtime-fill-notification.md)). 장중 확정은 웹소켓 통보가 맡는다.
  다만 ADR-0009 결정 1이 예정한 "마감 후 이 조회로 재대조"는 위 실측 때문에 모의환경에서 수행할 수
  없다. 대체 재대조 수단은 사용자 결정 대기다(아래 참조).
- 동기화가 상태를 추측해 바꾸지 않은 점은 설계대로다: 대조할 행이 없으면 전이도 문제도 만들지 않는다.

## 사용자 결정 대기: 남은 미체결 2건과 재대조 수단

2026-08-19 오전 주문 2건(`0000008637`, `0000008645`, 각 2주)은 실제로 전량 체결됐지만 내부에서
`SUBMITTED`로 남아 있다. 이 TR로는 확정할 수 없으므로 **계획은 계속 `ACCOUNT_NOT_RECONCILED`로
차단된다**. 웹소켓 통보는 리스너가 붙은 뒤 발생한 체결만 주므로 이 두 건을 소급 확정하지 못한다.

**결정: 2026-08-19에 사용자가 ㉡(사람이 확인한 관리 전이)을 승인했다**
([ADR-0010](../decisions/0010-human-attested-order-reconciliation.md)). 검토한 대안은 다음과 같다.

| 방안 | 내용 | 판단 |
|---|---|---|
| ㉠ 집계 기반 교차 확인 | `output2`의 합계로 그날 우리 주문을 대조 | 계좌에 외부(수동) 주문이 섞이면 합계가 우리 주문만을 뜻하지 않는다. 2026-08-19에 실제로 그런 사례가 관측돼 미채택 |
| **㉡ 사람이 확인한 관리 전이** | KIS 화면에서 확인한 뒤 CLI로 확정하고 근거·실행자를 남긴다 | **채택.** 범위를 "리스너 부착 전 제출 주문"으로 닫아 정상 확정 경로를 우회할 수 없게 했다 |
| ㉢ 웹소켓 단독 | 재대조 포기 | 막힌 두 주문을 풀지 못하고 유실 발견 경로도 없어져 미채택 |

승인된 세부 결정 4건: ① 리스너 부착 전 제출 주문만, ② 체결·취소 모두 확정 가능, ③ 수량·평균단가를
사람이 명시 입력, ④ 실행자·근거를 필수 인자로 받아 `attestation` 이벤트에 기록.

### 실행 명령

```bash
cd backend
# 환경변수는 위 리스너 검증 절과 같다(계좌 secret 필요)
uv run python -m auto_stock_trading.worker.execution.submission --attest \
  --broker-order-id 0000008637 --state filled --quantity 2 --price <KIS 화면의 평균단가> \
  --operator <실행자> --evidence "<무엇을 보고 확인했는지>"
```

수량·평균단가는 KIS 화면에서 읽은 값을 넣는다. 시스템은 값을 만들지 않는다. 교차 확인용으로 증권사
당일 집계는 `tot_ccld_amt=1244250`(우리 4주 + 사용자 수동 1주 249,250)이므로 우리 4주 합계는
995,000원, 주당 248,750원이다. 이 값은 참고용이며 근거는 사람이 본 화면이다.

이 경로는 자동매매를 재개하지 않는다. 두 주문을 종결한 뒤 다음 계획 실행이 차단 해제를 스스로
판단한다.

### 실행 결과 (2026-08-19 16:46~16:52 KST)

사용자가 KIS 모의투자 앱의 체결/예약>체결 화면에서 주문별 값을 확인해 알려주고, 그 값으로 두 건을
종결했다.

| 주문번호 | 주문단가 | 주문수량 | 체결평균 | 결과 |
|---|---|---|---|---|
| `0000008637` | 250,000 | 2 | 249,000 | `submitted → filled`, 평균단가 249,000 저장 |
| `0000008645` | 250,000 | 2 | 248,500 | `submitted → filled`, 평균단가 248,500 저장 |

확인 항목: 주문 이벤트 사유 `HUMAN_ATTESTED`(전이 `submitted → filled`), `attestation` 감사 이벤트에
`operator=yroh1`과 근거 문자열, 미체결 주문 0건, 자동매매 `disabled` 유지, 증권사 호출 없음.

**집계 역산이 주문별로는 틀렸다(기록해 둘 만한 사실).** 잔고 화면의 매입금액(1,244,250)에서 체결통보로
확인된 수동 매수 1주(249,250)를 빼면 우리 4주 합계 995,000원, 주당 248,750원이 나온다. 합계는 맞지만
두 주문의 실제 체결평균은 249,000과 248,500으로 **각각 250원씩 어긋났다**. 248,750은 두 값의 평균일
뿐이다. 잔고 화면의 매입단가(248,850)도 수동 1주가 섞인 5주 포지션 평균이라 주문별 값이 아니다.

이 관측은 ADR-0010이 집계 기반 확정(㉠)을 채택하지 않고 "사람이 주문별 화면 값을 읽어 넣는다"로 정한
근거를 실측으로 뒷받침한다. 집계에서 역산한 값을 주문별 사실로 쓰면 안 된다.

## 실시간 체결통보 리스너 검증 (2026-08-19)

절차와 결과는 아래 순서로 기록한다. 리스너는 읽기 전용이며 이 절차에서 새 주문을 만들지 않는다.

```bash
cd backend
export AUTO_STOCK_KIS_ENVIRONMENT=paper
export AUTO_STOCK_KIS_APP_KEY_FILE=../.secrets/kis-paper-app-key
export AUTO_STOCK_KIS_APP_SECRET_FILE=../.secrets/kis-paper-app-secret
export AUTO_STOCK_KIS_ACCOUNT_NUMBER_FILE=../.secrets/kis-paper-account-number
export AUTO_STOCK_KIS_ACCOUNT_PRODUCT_CODE_FILE=../.secrets/kis-paper-account-product
export AUTO_STOCK_KIS_HTS_ID_FILE=../.secrets/kis-paper-hts-id

# 1) 부착 판정 (리스너 없이 실행하면 attached=False)
uv run python -m auto_stock_trading.worker.execution.notifications --status

# 2) 한 세션만 붙여 구독·복호화 확인 (Ctrl-C로 종료)
uv run python -m auto_stock_trading.worker.execution.notifications --listen --max-sessions 1

# 3) 리스너를 끈 상태에서 제출 시도 → 증권사 호출 없이 차단되어야 한다
uv run python -m auto_stock_trading.worker.execution.submission --submit
```

확인 항목:

| 항목 | 기대 |
|---|---|
| 접속키 발급 | `/oauth2/Approval`이 `approval_key`를 주고 Valkey 공유 키에 캐시된다 |
| 구독 응답 | `rt_cd=0`이며 `output.key`·`output.iv`가 온다 |
| 연결 유지 | `PINGPONG`에 같은 프레임으로 응답해 세션이 유지된다 |
| 통보 필드 | 복호화 본문의 23개 필드 순서가 계약의 표와 일치한다 |
| 상태 확정 | 실제 체결이 장중에 `PARTIALLY_FILLED`/`FILLED`로 전이된다 |
| 개인정보 | 저장된 통보·API 응답·로그에 계좌번호·계좌명·고객ID·HTS ID·접속키가 없다 |
| 제출 게이트 | 리스너 미부착 시 `blocked block_code=LISTENER_NOT_ATTACHED submitted=0` |
| 단절 복구 | 미체결 주문이 있는 상태로 재부착하면 자동매매가 `PAUSED`로 전이한다 |

결과 (2026-08-19 11:40~12:05 KST, 실제 모의환경):

| 항목 | 결과 |
|---|---|
| 접속키 발급 | `/oauth2/Approval`이 36자 `approval_key`를 반환. Valkey 공유 키에 캐시되고 재호출은 발급하지 않음 |
| 구독 응답 | `rt_cd=0`, `msg_cd=OPSP0000`, `msg1=SUBSCRIBE SUCCESS`, `output.key` 32자·`output.iv` 16자 — 계약의 복호화 표와 일치 |
| 연결 유지 | `PINGPONG` 제어 프레임이 약 10초 간격으로 도착하고 같은 프레임을 되돌려 세션 유지 |
| 세션·심박 | `notification_session` 행이 `connected`로 생기고 10초마다 `last_heartbeat_at` 갱신. `--status`가 `attached=True` |
| 단절 구간 차단 | 미체결 주문 2건이 있는 상태로 부착하니 주문번호별 `NOTIFICATION_GAP` 2건 기록. 자동매매가 `disabled`라 전이는 시도하지 않고 기록만 남음(정지 가능 상태에서만 전이) |
| 정상 종료 | SIGINT·SIGTERM 모두 세션을 `disconnected`/`STOPPED`로 닫고 `LISTENER_DETACHED` 이벤트 기록. 다음 기동은 남은 연결 세션을 `SUPERSEDED`로 정리 |
| 제출 게이트 | 리스너를 끈 상태에서 자동매매 `RUNNING`으로 제출 → `blocked block_code=LISTENER_NOT_ATTACHED submitted=0`, 증권사 호출 없음. 확인 후 즉시 `disabled` 복귀 |
| 개인정보 | 원본 응답·요청 지문·자동매매 이벤트에서 HTS ID·계좌번호 문자열 검색 결과 0건 |

이 실행에서 고친 결함 2건(둘 다 정책·계약 변경 없음):

1. 프레임 오류가 태스크 그룹에 묶여 예외 그룹이 되면서 세션 재연결이 아니라 프로세스가 죽었다.
   프레임 오류를 수신 루프 프레임에서 처리하도록 바꿨다.
2. 운영자 중단과 컨테이너 정지(SIGTERM)가 세션을 닫지 못해 `connected` 행이 남았다. 신호를 받아
   같은 종료 경로로 모으고 취소 중에도 종료 기록을 남기도록(`CancelScope(shield=True)`) 바꿨다.

### 실제 통보 수신 대조 (2026-08-19 12:07 KST)

오전 실주문 2건이 내부 `SUBMITTED`로 남아 우리 계획 경로가 `ACCOUNT_NOT_RECONCILED`로 차단된
상태였으므로, 사용자가 KIS 모의투자 앱에서 삼성전자 1주를 직접 주문해 통보만 관측했다. 리스너는
읽기 전용이므로 이 확인에서 우리 시스템은 아무 주문도 보내지 않았다.

| 항목 | 결과 |
|---|---|
| 수신 | 12:07:25에 통보 2건(주문 접수 → 전량 체결). 둘 다 암호화 프레임이 복호화됐다 |
| 필드 수 | 23개. 인덱스 0~17·22가 계약 표와 일치 |
| 통보 종류 | `CNTG_YN` `1`(주문) → `2`(체결), `ACPT_YN` `1` → `2` |
| 단가 | 주문 통보는 지정가 249,500, 체결 통보는 체결가 249,250 — 같은 필드가 통보 종류에 따라 다른 값이다 |
| 마스킹 | 저장된 두 본문 모두 `***^***^`로 시작하고 계좌명 자리도 `***`. HTS ID·계좌번호 검색 0건 |
| 대조 | 우리 DB에 없는 주문번호라 두 건 모두 `UNKNOWN_BROKER_ORDER` 기록(설계된 fail-closed). 자동매매가 `disabled`여서 전이는 시도하지 않고 기록만 남음 |

이 실행에서 결함 1건을 더 고쳤다: 리스너 종료 요약이 통보 2건을 처리했는데도
`notifications=0`으로 보고했다. 신호로 세션이 취소되면 세션 안에서 세던 값이 유실됐기 때문이다.
집계를 세션 밖 객체(`SessionTotals`)로 옮겨 취소 후에도 사실대로 보고한다.

이 대조로 계약의 필드 표를 고쳤다: 인덱스 18~20은 문서의 이름(체결종목명·신용구분·신용대출일자)과
실측값(`1Y`·`10`·공백)이 맞지 않고 종목명은 인덱스 21에 있었다. 세 자리 모두 어떤 판정에도 쓰지
않으므로 이름을 추정하지 않고 미확인으로 남겼다(구현 변경 없음).

미완료 1항목:

- **우리 제출 경로로 낸 주문의 장중 확정**: 오전 미체결 2건의 대조가 마감 후 일별주문체결조회로만
  풀리므로 다음 거래일에 리스너를 먼저 붙인 뒤 수행한다. 부분체결 관측도 같이 한다.

## 다음 거래일 장중 검증 계획 (2026-08-20)

목표는 세 가지다: ① 우리 제출 경로로 낸 주문이 장중에 체결 통보로 확정되는지, ② 부분체결·취소
경로, ③ 리스너 단절 후 재부착의 `PAUSED` 전이(2026-08-19에는 자동매매가 `disabled`여서 전이 분기를
관측하지 못했다).

### 계좌 상태와 그에 따른 주문 방향 (2026-08-19 12:20 실측)

| 값 | 금액 |
|---|---|
| NAV(결제기준 현금 + 평가금액) | 9,993,080원 |
| 결제기준 현금 | 8,755,580원 |
| 삼성전자 5주 평가금액 | 1,237,500원 (NAV의 12.38%) |
| 증권사 순자산금액 | 9,993,080원 (우리 NAV와 일치) |

정책 §3의 종목 노출 상한은 NAV의 10%(999,308원)이고, 업종 분류 원천이 없어 미분류 상한 10%가 실효
총노출 상한이다. **현재 보유가 이미 상한을 넘었으므로 매수 계획은 목표 수량이 0이 되어 주문을 만들지
않는다.** 따라서 검증 주문은 **매도**여야 하며, 이는 상한 초과 상태를 정상으로 되돌리는 방향이기도
하다. 매도 수량은 계획기가 주문가능수량 안에서 산출하며, 실행 전에 산출 금액을 사용자에게 확인받는다.

### 0단계 — 전제 확인

- **해소됨(2026-08-19 16:52).** 미체결 2건을 ADR-0010 경로로 종결해 미체결 주문이 0건이 됐다. 계획의
  `ACCOUNT_NOT_RECONCILED` 차단 조건 중 미체결 항목은 풀렸다.
- 남은 조건은 NAV와 증권사 순자산금액 일치다. 2026-08-19 기준 둘 다 9,993,080원으로 일치했으며,
  내일 계좌 스냅샷에서 다시 확인한다.
- 매수 계획은 여전히 종목 상한 초과로 주문을 만들지 못한다(보유 5주 = NAV의 12.38%). 검증 주문은
  매도다.
- NAV와 증권사 순자산금액이 일치해야 한다. 다르면 계획이 차단된다(2026-08-19의 결함 수정 결과).

### 1단계 — 리스너 선부착 (08:50~09:04 KST)

```bash
cd backend
# 환경변수는 위 "실시간 체결통보 리스너 검증" 절과 같다
uv run python -m auto_stock_trading.worker.execution.notifications --listen &
uv run python -m auto_stock_trading.worker.execution.notifications --status   # attached=True
uv run python -m auto_stock_trading.worker.execution.planning --account-snapshot
uv run python -m auto_stock_trading.worker.execution.planning --automation armed
uv run python -m auto_stock_trading.worker.execution.planning --automation running
```

리스너를 제출보다 먼저 붙이는 것이 ADR-0009 결정 3의 요구사항이다. 통보는 재생되지 않으므로 순서가
바뀌면 그 주문의 체결을 놓친다.

### 실행 결과 (2026-08-20)

1단계와 2단계를 완료했다. 3·4단계는 지정가 옵션이 선행돼야 한다(아래 참조).

| 단계 | 결과 |
|---|---|
| 1 리스너 선부착 | 08:42 부착(`attached=True`), 미체결 0건이라 `NOTIFICATION_GAP` 미발생. 스냅샷 NAV 9,993,080 = 순자산금액 |
| 2 즉시 체결 확정 | 09:26 매도 5건(각 1주, 지정가 258,500) 제출 → 통보 10건 수신 → **5건 전량 `submitted → filled`**(사유 `FILL_NOTIFICATION`). 체결가 259,000·259,500, 일별주문체결조회 미사용 |
| 결과 | 삼성전자 0주, NAV 10,049,308 = 순자산금액. 종목 상한 초과 해소 |

계획기가 5건으로 쪼갠 이유는 주문 1건 금액 상한(NAV 5% = 502,529원)이다. 2주면 517,000원으로 넘는다.

### 이 실행에서 발견해 고친 결함 3건

정책·계약을 완화하지 않고 구현만 고쳤다. 세 건 모두 어제 작업이 남긴 문제다.

1. **거래일을 UTC 날짜로 찍었다.** 자동매매 전이가 `datetime.now(UTC).date()`를 쓰는데 계획기는 서울
   날짜와 비교한다. 08:43에 `running`으로 올린 상태가 거래일 `2026-08-19`로 저장돼, 09:05 계획에서
   거래일 변경으로 판정되며 `DISABLED`로 복귀했다(`AUTOMATION_NOT_RUNNING` 차단). **00:00~09:00 KST에
   자동매매를 올리면 항상 조용히 되돌아갔다** — 이 문서의 1단계 절차가 구조적으로 동작할 수 없었다.
   `seoul_trading_date()` 공용 헬퍼로 3곳(자동매매 전이·신호일자·비상정지)을 고쳤다.
2. **NAV 일치 검사가 장중에 성립하지 않았다.** 2026-08-19에 넣은 exact equality가 장중 계획을 항상
   차단했다. 원인은 증권사 응답 내부의 시세 시점 차이다(`output1` 252,500 vs `output2` 253,000, 5주에
   2,500원). 사용자 승인으로 대조 기준을 `판정 현금 + 증권사 평가합계 = 순자산금액` 항등식으로 바꿨다
   (허용 오차 없음, 현금 기준 오류는 그대로 차단).
3. **통보가 우리 커밋보다 먼저 도착했다.** 증권사는 접수 HTTP 응답 전에 통보를 밀어준다. 5건 중
   2건(`0000009970`, `0000009973`)이 오탐 `UNKNOWN_BROKER_ORDER`로 기록되고 자동매매가 일시정지됐다.
   150~400ms 뒤 체결통보는 같은 주문번호로 정상 대조됐다. 주문번호를 못 찾으면 0.2초 간격 최대 5회
   재조회한 뒤에만 불일치로 판정하도록 고쳤다.

### 3단계 — 미체결과 취소 (2026-08-20 10:07~10:36)

지정가 버전트 옵션(`--price-offset-pct`, 사용자 승인)을 먼저 구현했다. 계획기가 지정가를 항상
기준가로 잡던 제약 때문에 미체결을 만들 수 없었다.

| 항목 | 결과 |
|---|---|
| 계획 | 매수 3건 각 1주, 기준가 265,500 → 버전트 −0.8% → 지정가 263,500, 합계 790,500원 |
| 제출 | 10:24 접수 3건. **3건 모두 `submitted`(체결 0)** — 버전트가 의도대로 미체결을 만들었다 |
| 취소 | 10:25 `--emergency-stop` → `cancel_requested=3 cancel_failed=0`, 자동매매 `emergency_stop` |
| 취소 통보 | 새 주문번호(`0000017468`·`17469`·`17471`) + 원주문번호, `RCTF_CLS=2`·`ACPT_YN=2`, 단가 0 |
| 재반영 | 10:35 `--replay` → 3건 `canceled` 확정, 미체결 0건 |

**부분체결은 관측하지 못했다.** 버전트를 준 주문은 아예 체결되지 않았고, 부분체결을 결정적으로
만들 방법이 없다. 사용자 승인(2026-08-20)으로 **상시 관측 항목**으로 남긴다: 구현과 테스트는 이미
있으므로 7단계 완료를 막지 않고, 실제로 관측되면 이 문서와 계약의 실측 기록에 추가한다.

### 3단계에서 발견해 고친 결함 2건

1. **취소 통보는 구조적으로 대조되지 않았다.** 취소 요청이 자체 주문번호를 받으므로 `ODER_NO`로만
   맞추던 대조가 3건 모두 실패했다(`UNKNOWN_BROKER_ORDER`). 계약의 "주문번호로 내부 주문을 찾는다"가
   취소·정정 통보에는 틀렸다. 정정구분이 `0`이 아니면 원주문번호로 맞추도록 고치고, 실측한
   `RCTF_CLS=2`·`ACPT_YN=2` 조합으로 취소 전이를 넣었다(계약이 실측 후 채우라고 미뤄둔 규칙이다).
2. **재조회 창 1초가 부족했다.** 제출 3건 중 1건이 여전히 오탐이었다. 5초(0.5초 × 10회)로 넓혔다.

전이가 적용되지 않은 3건은 사용자 승인으로 **저장된 통보 재반영**(`--replay`)을 구현해 정리했다.
증권사 사실이 이미 저장돼 있으므로 사람의 진술이 아니라 원래 처리를 마치는 경로이며, `resolved_at`
열로 중복 반영을 막는다(리비전 `20260820_0019`). ADR-0010 종결 경로는 리스너 부착 전 주문만
허용하므로 이 3건에는 쓸 수 없었다.

### 2단계 — 즉시 체결 경로 (09:05 이후)

매도 신호로 계획을 만들고 제출한 뒤, 체결 통보가 장중에 상태를 확정하는지 본다.

| 확인 지점 | 기대 |
|---|---|
| `trading.fill_notification` | `order_id`가 채워진 `execution` 통보. `problem`은 비어 있다 |
| `trading.order` | `filled`(또는 `partially_filled`), `average_fill_price`가 통보 값 |
| `trading.order_event` | 사유 `FILL_NOTIFICATION`의 전이 기록 |
| `GET /api/trading/orders` | 체결 수량과 평균 체결가가 통보와 같다 |
| 모의매매 콘솔 `/trading` | B 좌표 체결 열이 `수량 @ 단가`로 표시된다 |

### 3단계 — 부분체결과 취소

지정가를 정책 §4의 ±1% 밴드 상한(매도는 기준가 +1%)에 두어 즉시 체결되지 않는 주문을 만든다.

- 일부만 체결되면 `PARTIALLY_FILLED` 확정과 누적 가산(직전 누적 + 통보 수량)을 확인한다.
- 남은 수량은 `--emergency-stop`으로 취소하고 `CANCELED` 확정 경로를 본다.
- **취소·정정 확인 통보의 `RCTF_CLS`·`ACPT_YN` 조합을 실측한다.** 계약은 이 조합이 확인되기 전까지
  통보로 취소 전이를 하지 않으므로, 관측 결과로 전이 규칙을 채운다.

### 4단계 실행 결과 (2026-08-20 10:48~10:52)

미체결 주문을 만들려면 새 식별자가 필요했다. 같은 거래일·전략·종목·구분·순번은 `client_order_id`가
같아 `on_conflict_do_nothing`이 중복을 막는다(설계대로 동작). 그래서 KODEX 200(069500)으로 계획했다.

| 항목 | 결과 |
|---|---|
| 계획·제출 | 매수 3건(4주·4주·1주, 기준가 108,655 → −0.9% → 지정가 107,675, 합계 969,075원). 3건 모두 미체결, 접수 통보 3건 모두 실시간 대조 성공(오탐 0 — 5초 창 확인) |
| SIGKILL | 정리 경로를 건너뛰어 세션이 `connected`로 남음(최악 상황 재현) |
| 심박 만료 | 마지막 심박 후 약 25초에 `attached=False`로 전환 |
| 제출 차단 | 자동매매가 `running`이고 허용시간 내인데도 `LISTENER_NOT_ATTACHED`, 증권사 호출 0 |
| 재부착 | 이전 세션을 `SUPERSEDED`로 정리하고 새 세션 시작 |
| 유실 구간 | 미체결 3건 각각 `NOTIFICATION_GAP` 기록 |
| **정지 전이** | **`running` → `paused`(`ACCOUNT_NOT_RECONCILED`)** — 2026-08-19에 관측하지 못한 분기를 실측 |
| 정리 | `--emergency-stop` 3건 취소 성공 → **취소 통보가 실시간으로 대조되어 즉시 `canceled` 확정**(원주문번호 대조 수정이 실환경에서 검증됨) → 미체결 0건 → 자동매매 `disabled` |

최종 계좌: 포지션 0, NAV 10,049,308 = 증권사 순자산금액. 이 단계에서 체결된 주문은 없다.

보고 결함 1건을 기록한다(수정 대기): 계획 CLI의 `planned=N`은 엔진이 만든 수를 세고 저장 결과를 세지
않는다. 중복 식별자로 저장이 생략된 계획에서도 `planned=3`으로 보고했다.

### 프로세스 재시작 후 상태 조정 (2026-08-20 12:08~12:09)

정책 §6의 "서버 재시작 시 자동매매는 `DISABLED`로 복귀"가 **구현돼 있지 않았다.** 거래일 변경만
처리하고 프로세스 시작은 아무도 재설정하지 않았다. 자동 제출 경로가 없어 실제 위험은 아직 없었지만
문구는 미구현 상태였다. 사용자 승인으로 **리스너 프로세스 시작을 재시작 기준으로** 구현했다.

| 확인 항목 | 결과 |
|---|---|
| 리스너 시작 | 자동매매 `running` → `disabled`, 사유 `PROCESS_START` |
| 기록 순서 | 재설정이 `LISTENER_ATTACHED`보다 먼저 남는다 |
| 이후 계획 | `blocked block_code=AUTOMATION_NOT_RUNNING` |
| 이미 `disabled`인 경우 | 전이하지 않는다(상태 그래프가 `DISABLED → DISABLED`를 금지) |
| 세션 내부 재연결 | 프로세스 시작이 아니므로 재설정하지 않는다 |

증권사 상태와 내부 상태의 조정 부분은 같은 날 4단계에서 이미 관측했다: 미체결 주문이 있는 상태로
리스너를 다시 붙이면 `NOTIFICATION_GAP`을 기록하고 자동매매가 정지되며, 계좌 대조가 끝나지 않으면
계획이 `ACCOUNT_NOT_RECONCILED`로 차단된다.

운영 순서가 이 구현으로 고정됐다: **리스너를 먼저 붙이고 그다음 `armed`·`running`** 이다. 순서를
바꾸면 리스너 시작이 방금 올린 상태를 되돌린다.

### 4단계 — 단절 복구와 `PAUSED` 전이

리스너를 `SIGKILL`로 죽여 정리 경로를 건너뛰게 만든다(세션 행이 `connected`로 남고 심박이 30초 뒤
낡는다). 미체결 주문이 있는 상태에서 다시 부착하면 `NOTIFICATION_GAP`을 기록하고 자동매매가
`PAUSED`로 전이해야 한다. 이후 재개는 사람이 원인을 확인한 뒤
`--automation armed` → `--automation running`으로 한다.

단절 동안 제출을 시도해 `LISTENER_NOT_ATTACHED` 차단도 다시 확인한다.

### 5단계 — 마감 후 재대조

`--sync`를 실행해 통보로 만든 누적과 일별주문체결조회 합계가 일치하는지 본다. 불일치는 자동으로
고치지 않고 `ACCOUNT_NOT_RECONCILED`로 차단되는 것이 정상이다.

### 기록과 마감

결과를 [실시간 체결통보 계약](../data/realtime-fill-notification-contract.md)의 실측 기록과 이 문서에
남기고, 게이트를 통과시킨 뒤 커밋·푸시하고 CI를 확인한다. 자동매매는 검증 종료 시 `disabled`로
되돌린다.

### 사용자 확인이 필요한 항목

- 매도 검증 주문의 수량·금액(계획기 산출값을 실행 전에 보고한다)
- 3단계의 미체결 유도 주문을 낼지 여부

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
- 주문 정정(수량·가격 변경)과 자동 스케줄 제출
- 서버 재시작 후 상태 복구 시나리오 테스트(현재는 거래일 변경 복귀만 검증)
- 주문·위험 이벤트 알림(웹·메신저)
