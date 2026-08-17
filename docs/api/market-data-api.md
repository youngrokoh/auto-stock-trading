# 시장 데이터 읽기 API

- 상태: 구현됨
- 구현일: 2026-08-14
- 기준 경로: `/api/market-data/instruments`
- 관련 정책: [시장 데이터 및 시점 정책](../spec/market-data-policy.md)

## 범위

2단계 첫 수직 슬라이스는 KIS 국내주식 시세 응답을 정규화해 종목정보, 최신 현재가, 버전된 비수정 일봉을 읽기 전용으로 제공한다. 2026-08-17에 [기업행사·수정주가 데이터 계약](../data/corporate-action-adjusted-price-data-contract.md)의 필수 조회 계약을 따르는 기업행사·수정주가 읽기 API를 추가했다. 시장 달력은 worker와 내부 저장소까지 구현했으며 아직 HTTP 읽기 API로 노출하지 않는다. 주문·계좌·실시간 스트림·분봉 API는 포함하지 않는다.

| 메서드 | 경로 | 응답 |
|---|---|---|
| `GET` | `/api/market-data/instruments` | 수집 대상 종목 목록 (종목코드 순) |
| `GET` | `/api/market-data/instruments/{symbol}` | 종목 기본정보와 상품 유형 |
| `GET` | `/api/market-data/instruments/{symbol}/quote` | 저장된 최신 현재가 |
| `GET` | `/api/market-data/instruments/{symbol}/daily-bars` | 거래일 오름차순 비수정 일봉 |
| `GET` | `/api/market-data/instruments/{symbol}/minute-bars` | 거래일별 시각 오름차순 비수정 1분봉 |
| `GET` | `/api/market-data/instruments/{symbol}/investor-flows` | 일자별 개인·외국인·기관 순매수 (거래일 내림차순, `limit` 기본 30) |
| `GET` | `/api/market-data/instruments/{symbol}/corporate-actions` | 기업행사 사실 버전 (현재·이력·시점 조회) |
| `GET` | `/api/market-data/instruments/{symbol}/adjusted-daily-bars` | 최신 발행 수정주가 데이터셋과 파생 일봉 |
| `GET` | `/api/market-data/adjusted-datasets/{dataset_id}` | 데이터셋 ID로 수정 일봉·계수·기업행사 계보 |
| `GET` | `/api/market-data/corporate-actions/{action_key}/adjusted-datasets` | 기업행사가 반영된 데이터셋 목록 |

일봉 조회는 선택적인 `start_date`, `end_date` 쿼리를 `YYYY-MM-DD` 형식으로 받는다. 시작일이 종료일보다 늦으면 `422`, 종목이 없으면 `404`를 반환한다. 등록된 종목에 조회 구간 데이터가 없으면 빈 `bars`를 반환한다.

분봉 조회는 필수 쿼리 `trading_date`를 받으며 [국내 분봉 데이터 계약](../data/minute-bar-data-contract.md)을 따른다. 검증된 시장 달력 세션 창 안의 비수정 1분봉 현재 버전을 `bar_started_at` 오름차순으로 반환하고, 각 분봉은 `version`, `valid_from`, `finality`, `confirmed_at`과 원본이 제공하는 당일 누적 거래대금(`cumulative_trading_value`)을 노출한다. `pending` 분봉은 재관측 확정 전 값으로 전략 입력에 사용할 수 없다. 종가 단일가(15:30) 행의 분당 거래량은 원본 특성상 실제 체결량의 2배로 반환되며 보정 없이 그대로 저장·노출된다.

## 기업행사·수정주가 읽기

기업행사 조회는 선택적인 `start_date`, `end_date`와 함께 다음 모드를 지원한다.

- 기본은 `action_key`별 현재 버전만 반환한다.
- `knowledge_cutoff_at`(시간대 오프셋 필수)은 `available_at <= knowledge_cutoff_at`에서 당시 알 수 있었던 최신 버전을 선택한다. 시간대 없는 값은 `422`다.
- `include_history=true`는 정정·취소 이력 전체를 버전 순으로 반환하며 `knowledge_cutoff_at`과 함께 쓰면 `422`다.
- 각 항목은 `action_key`, `version`, `valid_from`, `superseded_at`, 생애주기·품질 상태, 출처와 `available_at`을 포함한다. 락일 확정 전 버전은 `ex_date`가 없어 기간 필터(`coalesce(ex_date, effective_date)`)에 걸리지 않으므로 이력 확인은 기간 없이 조회한다.

수정주가 조회는 `method` 쿼리로 `split_adjusted` 또는 `total_return`을 요구하며 다른 값은 `422`다. 응답의 `dataset`은 `method`, `interval`, `range_start`, `price_cutoff_date`, `knowledge_cutoff_at`, `algorithm_version`, 두 입력 해시(`input_bar_version_hash`, `action_version_hash`), 상태와 생성·대체 시각을 항상 포함한다. 원본·수정 여부는 불리언 하나로 표현하지 않고 데이터셋 메타데이터로만 구분한다. 발행된 데이터셋이 없으면 `404`다.

- `bars`의 각 일봉은 수정 OHLCV·거래량·거래대금과 개별 `price_factor`·`volume_factor`, 근거 비수정 일봉의 `source`, `source_bar_id`, `source_bar_version` 계보를 노출한다.
- `applied_actions`는 반영된 기업행사의 `action_key`, `action_version`, 사건일, 사건 계수와 출처를 노출한다.
- 데이터셋 ID 조회는 감사·재현을 위해 `failed`·`superseded` 상태도 반환한다. 기업행사별 데이터셋 목록은 해당 사실 버전이 반영된 발행 이력을 생성 시각 순으로 반환한다.
- `split_adjusted`는 주식 수 변화 사건만 반영해 사건일 이전 가격에 1/주식수승수, 거래량에 주식수승수를 누적 적용한다. `total_return`은 여기에 현금배당·ETF 분배금을 락일 직전 종가 기준 `(P - D) / P` 가격계수로 추가 반영한다. 두 계열 모두 비수정 확정 일봉의 파생값이며 체결가로 사용할 수 없다. 계산식은 OpenAPI 경로 설명에도 명시된다.

## 투자자별 매매(수급)

[수급·공시 연결 데이터 계약](../data/investor-flow-disclosure-contract.md)을 따른다. 행마다
개인·외국인·기관의 순매수 수량(주, `quantity_unit: share`)과 대금(백만원,
`value_unit: million_krw`)을 원본 그대로 제공하며, 세 주체 합계는 기타 주체가 없어 0이
아니다. 서울 기준 당일 데이터는 잠정치라 저장하지 않고, 출처는 KIS이며 최근 약 30거래일만
제공되므로 수집 시점부터 축적한다. 행은 `received_at`·`version`을 포함한다.

## 출처와 시각

- 모든 응답은 `source` 또는 개별 bar의 `source`로 `KIS`를 노출한다.
- 종목정보의 `source_as_of`는 종목 식별정보의 근거 응답을 수신한 한국 거래일이다. 실전환경은 종목 상세 응답, 모의환경은 일봉 요약 응답을 사용한다.
- 현재가 REST 응답에는 거래소 체결시각이 없으므로 `as_of`와 `received_at`은 서버가 응답을 수신한 UTC 시각이다.
- 일봉의 `trading_date`는 거래일, `received_at`은 서버 수신 UTC 시각이다.
- `adjusted=false`는 KIS 요청의 `FID_ORG_ADJ_PRC=1`, 즉 비수정 원본 가격임을 뜻한다.
- 일봉은 현재 사실의 `version`, 채택 시각 `valid_from`, `finality`와 `confirmed_at`을 함께 노출한다.
- `pending`은 전략 입력에 사용할 수 없는 검증 대기 값이고, `confirmed`는 같은 사실을 명시적으로 재확인한 값이다. 정정으로 새 버전이 생기면 새 현재 버전은 다시 `pending`이다.

가격과 금액은 내부에서 `Decimal`로 처리하며 JSON에서는 정밀도를 보존하는 문자열로 직렬화된다. 시각은 UTC ISO 8601 형식이다.

## 내부 저장 계약

외부 응답은 `operations.raw_api_response`에 append-only로 저장하고 정규화 데이터는 다음 식별·버전 규칙으로 저장한다.

- 종목: 국가·거래소·종목코드·상품유형·통화
- 최신 현재가: 종목·출처
- 일봉 버전: 종목·주기·거래일·출처·버전
- 일봉 현재 사실: 종목·주기·거래일·출처별 `superseded_at IS NULL`인 행 최대 1개
- 수집 상태: 출처·작업·종목코드

현재가와 일봉은 원본 응답 식별자를 참조한다. 같은 일봉 사실을 다시 받으면 버전을 늘리지 않고 최신 수신 근거만 갱신한다. OHLCV·거래량·거래대금·정정 정보가 달라지면서 최신 근거보다 나중에 수신된 경우 기존 행에 `superseded_at`을 기록하고 `pending`인 다음 버전을 만든다. 오래된 정정 응답은 현재 사실을 되돌리지 않는다. 일반 일봉 조회는 현재 버전만 반환하며 과거 버전은 감사·재현을 위해 DB에 남긴다. 원본 응답에는 인증 헤더, 앱 키, 앱 시크릿과 계좌번호를 저장하지 않는다.

## 수집 작업

삼성전자 `005930`과 KODEX 200 `069500`을 기본 대상으로 수집한다.

```bash
cd backend
uv run python -m auto_stock_trading.worker.market_data \
  --start-date 2026-08-01 \
  --end-date 2026-08-14
```

Taskiq 등록 이름은 `collect_seed_market_data`다. 실행 서버에는 `AUTO_STOCK_KIS_APP_KEY`·`AUTO_STOCK_KIS_APP_SECRET` 직접 값 또는 대응하는 `_FILE` 경로가 필요하며 기본 환경은 모의투자다. 값은 문서·Git·브라우저 번들·로그에 기록하지 않는다. Docker 실행은 [KIS 모의환경 검증 런북](../operations/kis-paper-verification.md)을 따른다.

시장 달력 수동 CLI는 KIS 자격증명 없이 KRX 연간 휴장일과 보도자료의 임시 거래시간 PDF를 합성하거나 실전 KIS로 당일 일정을 확인한다. KIS 국내휴장일조회는 실전 전용이므로 `AUTO_STOCK_KIS_ENVIRONMENT=live`와 분리된 실전 자격증명이 필요하다. KRX 원본 범위가 일부라도 빠지거나 지원 대상 임시 공지의 PDF 계약이 다르면 정규화 행을 저장하지 않고 실패 상태를 남긴다. 수동 CLI도 자동 예약과 같은 PostgreSQL claim을 사용한다.

자동 실행 등록 이름은 `scheduled_krx_market_calendar`와 `scheduled_kis_market_calendar_confirmation`이다. 예약 메시지는 외부 호출 전에 `operations.scheduled_job_run`을 claim하며 동일 날짜·대상·버전의 성공 또는 충돌 결과는 이후 tick에서 건너뛴다. KRX 예약은 `calendar-scheduler` Compose 프로필에서 켜고, KIS 예약은 실전 환경과 `AUTO_STOCK_KIS_CALENDAR_SCHEDULE_ENABLED=true`가 모두 필요하다.

사용자가 승인한 자동 KIS 확인은 `infra/compose.kis-live-calendar.yaml`을 기본 Compose와 함께 적용할 때만 활성화된다. scheduler는 예약 플래그만 받고, 실제 자격증명과 읽기 전용 외부 호출은 worker 경계에만 존재한다.

## 현재 제한

- KIS 모의환경은 종목 상세 `CTPF1002R`을 지원하지 않아 종목명·상품유형만 구성한다. 상장·상장폐지일과 영문명은 후속 종목 마스터 수집 전까지 제공하지 않는다.
- 모의투자 REST 요청은 현재 초당 1건 제한에 맞춰 최소 1.05초 간격으로 실행한다.
- 접근 토큰과 호출 간격은 Valkey에서 같은 자격증명의 worker가 공유한다.
- 현재가 `as_of`는 체결시각이 아니라 수신시각이다. 향후 실시간 스트림에서는 거래소 시각을 별도 저장한다.
- 시장 달력 HTTP API는 아직 구현하지 않았다. 분봉·수정주가·기업행사 읽기 API는 구현했으며 KIS 수정주가 대조는 분할 이력 종목 확보 시 수행한다.
- 분봉 수집은 모의환경 당일분봉 API의 한계로 최신 거래 세션만 가능하다. 수집하지 않은 과거 거래일은 영구 결손으로 남으며 직전 값으로 채우지 않는다. KRX 임시 거래시간 공지는 수능일·연초 개장일 형식을 지원하며 새로운 임시 변경 유형은 계약과 테스트를 추가하기 전 fail-closed로 처리한다.
