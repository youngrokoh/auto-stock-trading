# 국내 분봉 데이터 계약

- 상태: 구현 기준
- 작성일: 2026-08-17
- 승인: 사용자가 2026-08-17에 재관측 일치 2회 확정, 백필 없는 당일 축적과 이 계약을 구현 기준으로 승인
- 관련 정책: [시장 데이터 및 시점 정책](../spec/market-data-policy.md)
- 관련 계약: [기업행사·수정주가 데이터 계약](corporate-action-adjusted-price-data-contract.md)

## 목적

국내주식과 ETF의 비수정 1분봉을 원본 그대로 버전 관리하며 저장하고, 미확정·누락 분봉을 전략 입력에서 배제할 수 있는 명시적 확정 상태를 제공한다. [시장 데이터 및 시점 정책](../spec/market-data-policy.md) 4장의 "분봉은 해당 구간 종료 후 확정, 미확정·누락 분봉 사용 금지"를 저장소 수준에서 구현한다.

## 범위

- 초기 대상은 삼성전자 `005930`과 KODEX 200 `069500`의 `XKRX` 정규장 1분봉이다.
- 수정 분봉, 5분·틱 등 파생 집계, 실시간 스트림, 시간외 단일가·시간외 종가 구간은 포함하지 않는다. 분봉 조정은 [기업행사·수정주가 데이터 계약](corporate-action-adjusted-price-data-contract.md)이 초기 범위에서 제외한 상태를 유지한다.
- 분봉에서 일봉·지표를 파생 계산하지 않는다. 파생이 필요하면 별도 데이터셋 계약을 먼저 정의한다.

## 출처와 실측 한계 (2026-08-17 모의환경 확인)

출처는 KIS 주식당일분봉조회(`FHKST03010200`, `/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice`)이며 모의투자 환경에서 지원됨을 실제 호출로 확인했다.

- 한 호출은 요청 시각(`FID_INPUT_HOUR_1`)부터 역순으로 최대 30건을 반환하고, 행마다 `stck_bsop_date`(거래일)와 `stck_cntg_hour`(HHMMSS)를 포함한다.
- 시각 파라미터에 날짜가 없어 과거 거래일을 지정할 수 없다. 최신 세션 전체와 역방향 넘침으로 도달하는 직전 세션 꼬리만 조회할 수 있으므로, 모의환경에서 과거 분봉 백필은 불가능하다. 수집하지 않은 거래일의 분봉은 영구 결손이며 직전 값으로 채우지 않는다.
- 휴장일 조회는 최신 거래 세션의 분봉을 반환한다. 저장 대상 거래일은 요청일이 아니라 행의 `stck_bsop_date`로 판정한다.
- 15:30 정규장 종료 이후 행은 종가로 채워진 거래량 0의 패딩이고 시간외 체결이 뒤섞이므로 저장하지 않는다. 정규장 구간 판정은 검증된 `XKRX` 시장 달력의 세션 창(단축장 포함)만 사용한다.
- `cntg_vol`은 해당 분의 거래량이지만 `acml_tr_pbmn`은 당일 누적 거래대금이다. 누적값을 원본 그대로 저장하고 분당 거래대금을 차감 계산으로 파생하지 않는다.
- 분 라벨은 구간 시작이다. 첫 분봉 `090000`의 시가가 확정 일봉 시가와, 마지막 분봉 `153000`의 종가가 일봉 종가와 일치함을 두 종목의 실수집으로 확인했다.
- 종가 단일가(15:30) 행의 `cntg_vol`은 누적 거래대금 증분이 시사하는 실제 체결량의 정확히 2배로 반환됨을 두 종목에서 확인했다. 원본 사실을 보정하지 않고 그대로 저장하며, 이 특성은 소비 측이 해석한다.
- 분봉 요약(`output1`)의 당일 누적 거래량은 확정 일봉 거래량과 정확히 일치한다. 반면 분당 `cntg_vol` 합계와 마지막 누적 거래대금은 종가 단일가 2배 특성과 일봉의 시간외·대량 거래 포함 범위 차이로 일봉과 일치하지 않는다. (사용자가 2026-08-17 실측 기반 검증 조정을 승인)

## 저장 위치와 식별자

PostgreSQL `market.minute_bar`에 저장한다. 논리 분봉의 식별자는 다음과 같다.

```text
논리 분봉 = instrument_id + interval('1m') + bar_started_at + source
```

`bar_started_at`은 `stck_bsop_date`와 `stck_cntg_hour`를 `Asia/Seoul`로 해석해 UTC로 저장한 타임스탬프다. `trading_date`는 시장 달력 결합을 위해 함께 저장한다.

## 필드 계약

| 필드 | DB 타입 | 필수 | 의미 |
|---|---|---|---|
| `id` | `UUID` | 예 | 행 식별자 |
| `instrument_id` | `UUID` | 예 | `reference.instrument` 참조 |
| `interval` | `VARCHAR(8)` | 예 | 초기값 `1m` 고정 |
| `trading_date` | `DATE` | 예 | 거래일 (`stck_bsop_date`) |
| `bar_started_at` | `TIMESTAMPTZ` | 예 | 분 구간 시작 (UTC 저장, 서울 해석) |
| `open_price`·`high_price`·`low_price`·`close_price` | `NUMERIC(24,8)` | 예 | 비수정 시가·고가·저가·종가 |
| `volume` | `BIGINT` | 예 | 해당 분 거래량 (`cntg_vol`) |
| `cumulative_trading_value` | `NUMERIC(32,8)` | 예 | 당일 누적 거래대금 (`acml_tr_pbmn`, 원본 그대로) |
| `source` | `VARCHAR(32)` | 예 | `KIS` |
| `received_at` | `TIMESTAMPTZ` | 예 | 서버 수신 UTC 시각 |
| `finality` | `VARCHAR(16)` | 예 | `pending` 또는 `confirmed` |
| `confirmed_at` | `TIMESTAMPTZ` | 아니요 | 확정 시각 |
| `version` | `INTEGER` | 예 | 논리 분봉별 사실 버전 |
| `valid_from` | `TIMESTAMPTZ` | 예 | 버전 채택 시각 |
| `superseded_at` | `TIMESTAMPTZ` | 아니요 | 대체 시각, 현재 버전은 `NULL` |
| `raw_response_id` | `UUID` | 예 | `operations.raw_api_response` 참조 |

수정 여부 불리언은 두지 않는다. 이 테이블은 비수정 사실만 저장한다.

## 값과 불변조건

- `low_price <= open_price, close_price <= high_price`
- `volume >= 0`, `cumulative_trading_value >= 0`, 가격은 0보다 크다.
- `bar_started_at`은 검증된 시장 달력의 해당 거래일 세션 창 안에 있어야 한다. 세션 창 밖의 행과 달력에 없는 거래일은 저장하지 않는다.
- `trading_date`와 `bar_started_at`의 서울 날짜는 일치해야 한다.

## 키, 제약조건과 인덱스

- 버전 유일키: `(instrument_id, interval, bar_started_at, source, version)`
- 현재 사실: `(instrument_id, interval, bar_started_at, source)`별 `superseded_at IS NULL` 행 최대 1개 (부분 유일 인덱스)
- 조회 인덱스: `(instrument_id, trading_date)`

## 수집과 버전 규칙

1. 외부 응답을 인증정보 없이 `operations.raw_api_response`에 먼저 append-only로 저장한다.
2. 수집 대상 거래일은 검증된 `XKRX` 달력에서 결정한 최신 거래일이며, 달력이 없거나 세션 창을 알 수 없으면 수집을 실패 처리한다(fail-closed).
3. 세션 종료 시각부터 30분씩 역방향으로 호출해 세션 시작까지 채우고, 대상 거래일·세션 창 밖의 행은 폐기한다.
4. 같은 논리 분봉의 동일 사실 재수신은 버전을 늘리지 않고 최신 수신 근거만 갱신한다.
5. OHLC·거래량·누적 거래대금이 바뀌면 이전 버전에 `superseded_at`을 기록하고 새 `pending` 버전을 만든다. 과거 버전과 원본은 삭제하지 않는다.
6. 최신 수신 근거보다 오래된 정정 응답은 현재 사실을 되돌리지 않는다.

## 확정 규칙

일봉 확정 흐름과 같은 재관측 원칙을 분봉에 적용한다.

- 분 구간이 끝나기 전의 관측은 저장하지 않는다(진행 중 분은 미완성 사실이다).
- 구간 종료 후 첫 관측은 `pending`으로 저장한다.
- 구간 종료 후의 두 번째 관측이 저장된 현재 사실과 정확히 일치하면 `confirmed`로 전환한다. 값이 다르면 확정하지 않고 새 `pending` 정정 버전을 만든다.
- 정규장 종료 후 수집·재수집 한 쌍으로 하루치 분봉을 확정하는 것을 기본 운영으로 한다.

## 필수 조회 계약

- 종목·거래일로 현재 버전 분봉을 `bar_started_at` 오름차순으로 조회한다.
- 응답은 분봉 값과 함께 `version`, `valid_from`, `finality`, `confirmed_at`, `source`를 노출한다.
- 시각은 UTC ISO 8601로 직렬화하고 거래소 시간대는 시장 달력이 보존한다.
- `pending` 분봉은 전략 입력에 사용할 수 없는 검증 대기 값이다.

## 데이터 품질과 실패 처리

- 세션 창 내 거래량 0 분봉은 체결 없음 사실로 저장한다. 세션 창 밖 패딩은 저장하지 않는다.
- 누락 분봉을 직전 값·보간으로 채우지 않는다. 미수집 거래일은 결손으로 남기고 조회 결과가 이를 그대로 드러낸다.
- 달력 미검증, 세션 창 불명, 원본 계약 위반(필드 누락·형식 오류)은 정규화 저장 없이 `operations.api_sync_status`에 비밀정보 없는 오류로 기록한다.
- 자격증명·토큰은 원본·로그·문서에 저장하지 않는다.

## 검증 시나리오

1. 구간 종료 후 두 관측이 일치한 분봉만 `confirmed`가 되고, 한 번 관측된 분봉은 `pending`을 유지한다.
2. 재수집 시 동일 사실은 버전이 늘지 않고, 값이 바뀐 분봉은 이전 버전을 보존한 새 `pending` 버전이 된다.
3. 세션 창 밖 패딩 행과 대상 외 거래일 행은 저장되지 않는다.
4. 실제 모의환경 수집으로 세션 분봉 수가 세션 창과 일치하고, 첫 분봉 시가·마지막 분봉 종가·고가·저가 포락선이 같은 날 확정 일봉의 시가·종가·고가·저가와 일치하며, 분봉 원본 요약의 당일 누적 거래량이 일봉 거래량과 일치한다. 분당 거래량 합계와 마지막 누적 거래대금은 출처 계열 차이로 일봉과 일치하지 않으며 그 특성을 실측 한계로 기록한다.
5. 달력이 없는 기간의 수집 요청은 실패 상태만 남기고 아무것도 저장하지 않는다.

## 구현 결과

- Alembic `20260817_0008`이 `market.minute_bar`를 계약의 필드, 버전 유일키, `superseded_at IS NULL` 부분 유일 인덱스와 가격·금액·확정 상태·버전·유효기간 제약조건으로 생성한다.
- `KisMinuteBarAdapter`는 세션 종료 시각부터 30건씩 역방향으로 호출하고, 대상 거래일·세션 창 밖 행과 진행 중 분을 폐기하며, 페이지별 원본을 append-only로 보존한다.
- `MinuteBarCollector`는 검증된 달력에서 최신 거래일과 세션 창을 결정하고(휴장일은 직전 거래일, 달력 누락·충돌은 fail-closed), 구간 종료 후 두 관측이 정확히 일치한 분봉만 `confirmed`로 전환한다. 같은 사실 재수신은 버전을 늘리지 않고 값이 바뀌면 이전 버전을 보존한 새 `pending` 정정 버전을 만든다.
- 읽기 API `GET /api/market-data/instruments/{symbol}/minute-bars?trading_date=`는 현재 버전을 `bar_started_at` 오름차순으로 반환하며 `version`, `valid_from`, `finality`, `confirmed_at`, `source`를 노출한다.
- 2026-08-17에 실제 모의환경에서 삼성전자·KODEX 200의 2026-08-14 세션 분봉 391개씩을 수집(1차 전량 `pending`)하고 재수집으로 전량 `confirmed`를 확인했다. 시가·종가·고저 포락선·원본 누적 거래량이 확정 일봉과 일치했다.

## 구현 순서

1. 완료: `market.minute_bar` Alembic 마이그레이션
2. 완료: KIS 당일분봉 어댑터와 세션 창 필터
3. 완료: 버전 저장소와 재관측 확정 흐름
4. 완료: worker 수동 CLI와 읽기 API
5. 완료: fixture·PostgreSQL 통합 테스트와 실제 모의환경 교차 검증
6. 완료: 영향 문서 갱신
