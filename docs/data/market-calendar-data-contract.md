# 국내 시장 달력 데이터 계약

- 상태: 구현 기준
- 기준일: 2026-08-16
- 초기 범위: 국내주식·국내 ETF의 `XKRX` 정규장
- 관련 정책: [시장 데이터 및 시점 정책](../spec/market-data-policy.md)
- 관련 결정: [ADR-0003](../decisions/0003-data-architecture.md)

## 목적

시장 달력은 수집기와 향후 전략 실행기가 특정 날짜를 거래일로 취급해도 되는지 판단하는 기준 데이터다. 평일 여부로 거래일을 추정하지 않고 KRX 공식 일정과 당일 확인 결과를 사용한다. 휴장, 임시 휴장과 단축장 정정은 기존 사실을 덮어쓰지 않고 버전으로 보존한다.

이 계약은 승인된 시장 데이터 정책을 구현 가능한 필드와 불변조건으로 구체화한다. 거래 가능 시간이나 실패 시 차단 원칙을 변경하지 않으며, 이 문서와 승인 정책이 충돌하면 승인 정책을 우선하고 구현을 중단한다.

## 범위

초기 구현은 다음만 포함한다.

- 국가 `KR`, 거래소 MIC `XKRX`
- 국내주식과 국내 ETF가 공유하는 정규장 `regular`
- 정상 거래일, 휴장일과 정규장 시간이 달라지는 단축장
- KRX를 1차 출처로 한 일정 수집과 KIS 거래 가능 상태를 이용한 당일 보완 확인
- 수집 스케줄이 사용할 현재 세션, 다음·이전 거래일 조회

시간외시장, 파생상품, 미국 시장, 주문 가능 시간 `09:05~15:15`와 종목별 거래정지는 이 계약에 포함하지 않는다. 주문 가능 시간은 거래 안전 정책의 실행 규칙이고, 종목별 거래정지는 종목 상태나 기업행사 데이터에서 관리한다.

## 저장 위치와 식별자

정규화 테이블 이름은 `reference.market_calendar`로 한다. 한 논리 세션의 식별자는 다음 조합이다.

```text
CalendarSessionKey
= country + exchange + trading_date + session_type
```

초기 값은 `country=KR`, `exchange=XKRX`, `session_type=regular`이다. 같은 식별자에 대한 정정은 `version`을 증가시킨 새 행으로 저장한다.

## 필드 계약

| 필드 | DB 타입 | 필수 | 의미 |
|---|---|---|---|
| `id` | `UUID` | 예 | 행 식별자 |
| `country` | `VARCHAR(2)` | 예 | ISO 국가 코드, 초기값 `KR` |
| `exchange` | `VARCHAR(12)` | 예 | 거래소 MIC, 초기값 `XKRX` |
| `trading_date` | `DATE` | 예 | `exchange_timezone` 기준 거래일 |
| `session_type` | `VARCHAR(16)` | 예 | 초기에는 `regular`만 허용 |
| `session_status` | `VARCHAR(16)` | 예 | `open`, `closed`, `shortened` 중 하나 |
| `opens_at` | `TIMESTAMPTZ` | 조건부 | 정규 세션 시작시각, UTC 저장 |
| `closes_at` | `TIMESTAMPTZ` | 조건부 | 정규 세션 종료시각, UTC 저장 |
| `exchange_timezone` | `VARCHAR(64)` | 예 | 초기값 `Asia/Seoul` |
| `reason` | `VARCHAR(240)` | 아니요 | 휴장·단축장 사유. 출처에 사유가 없으면 `NULL` |
| `source` | `VARCHAR(32)` | 예 | 현재 사실을 채택한 1차 출처, 초기값 `KRX` |
| `source_reference` | `VARCHAR(240)` | 예 | 공개 문서 식별자나 공식 페이지 경로. 인증 쿼리는 저장 금지 |
| `source_as_of` | `DATE` | 예 | 출처가 기준으로 삼은 날짜 |
| `received_at` | `TIMESTAMPTZ` | 예 | 해당 원본을 받은 UTC 시각 |
| `verification_state` | `VARCHAR(16)` | 예 | `pending`, `confirmed`, `conflict` 중 하나 |
| `confirmed_at` | `TIMESTAMPTZ` | 조건부 | 현재 세션을 마지막으로 당일 확인한 UTC 시각 |
| `version` | `INTEGER` | 예 | 논리 세션별 1부터 증가하는 사실 버전 |
| `valid_from` | `TIMESTAMPTZ` | 예 | 이 버전을 현재 사실로 채택한 UTC 시각 |
| `superseded_at` | `TIMESTAMPTZ` | 아니요 | 후속 버전으로 대체된 UTC 시각. 현재 버전은 `NULL` |
| `raw_response_id` | `UUID` | 예 | `operations.raw_api_response.id` 외래키 |
| `created_at` | `TIMESTAMPTZ` | 예 | 행 생성 UTC 시각 |
| `updated_at` | `TIMESTAMPTZ` | 예 | 확인 상태와 최신 근거를 갱신한 UTC 시각 |

`received_at`, `confirmed_at`, `valid_from`, `superseded_at`, `created_at`, `updated_at`은 모두 timezone-aware 값이어야 한다. 사용자 표시와 거래일 판정에서만 `exchange_timezone`으로 변환한다.

## 값과 불변조건

### 세션 상태

| `session_status` | 시작·종료시각 | 의미 |
|---|---|---|
| `open` | 둘 다 필수 | 정책의 정상 정규장 시간과 일치하는 거래일 |
| `closed` | 둘 다 `NULL` | 정규 세션이 없는 휴장일 |
| `shortened` | 둘 다 필수 | 공식 정규장 시작 또는 종료시각이 정상 시간과 다른 거래일 |

`open`과 `shortened`는 `opens_at < closes_at`이어야 하며 두 시각을 `exchange_timezone`으로 변환한 날짜가 `trading_date`와 같아야 한다. 정상 시간 `09:00~15:30`은 도메인 검증 기준으로 사용하고 DB 제약조건에 하드코딩하지 않는다. 제도 변경은 정책과 계약을 먼저 갱신한 뒤 코드에 반영한다.

### 확인 상태

- `pending`: 미래 일정으로 적재됐지만 해당 거래일의 운영 확인을 아직 완료하지 않았다.
- `confirmed`: KRX 현재 일정과 필요한 보완 확인이 현재 버전과 일치한다.
- `conflict`: KRX, KIS 또는 기존 현재 버전 사이에 거래 여부나 세션 시각 충돌이 있다.
- `confirmed_at`은 `confirmed`일 때만 값이 있어야 한다.
- `conflict`는 한 출처의 값으로 자동 덮어쓰지 않고 원본과 동기화 오류를 남긴다.

`stale`은 저장 값이 아니라 조회 시점에 계산하는 상태다. 열린 거래일의 `confirmed_at`을 `Asia/Seoul`로 변환한 날짜가 `trading_date`와 다르면 당일 확인이 오래된 것으로 판단한다.

## 키, 제약조건과 인덱스

- 기본키: `id`
- 버전 유일성: `(country, exchange, trading_date, session_type, version)`
- 현재 버전 유일성: `(country, exchange, trading_date, session_type)`에서 `superseded_at IS NULL`인 행은 최대 1개
- 범위 조회 인덱스: `(exchange, trading_date)`
- 현재 거래일 조회 인덱스: `(exchange, trading_date, session_type)`에서 `superseded_at IS NULL`
- `version >= 1`
- `superseded_at IS NULL OR superseded_at > valid_from`
- `raw_response_id`는 삭제 연쇄 없이 원본 응답을 참조한다.

열거 값은 PostgreSQL 전용 enum 대신 문자열과 애플리케이션 `StrEnum`으로 검증한다. 현재 프로젝트의 기존 테이블과 같은 방식이며 값 변경을 위해 DB enum 마이그레이션에 결합되지 않는다.

## 수집과 버전 규칙

1. 외부 응답을 인증정보 없이 `operations.raw_api_response`에 먼저 append-only로 저장한다.
2. 현재 버전이 없으면 `version=1`로 생성한다.
3. 거래 여부, 시작·종료시각, 시간대 또는 사유가 현재 버전과 다르면 한 트랜잭션에서 기존 행의 `superseded_at`을 설정하고 `version + 1` 행을 만든다.
4. 사실이 같으면 새 버전을 만들지 않고 `received_at`, `raw_response_id`, 확인 상태와 `updated_at`만 최신 근거로 갱신한다.
5. 낮은 우선순위 출처가 KRX 현재 버전과 충돌하면 사실 버전을 바꾸지 않고 `verification_state=conflict`로 표시한다.
6. 같은 원본을 반복 처리해도 현재 버전과 행 수가 증가하지 않아야 한다.

출처 우선순위는 KRX가 1차이고 KIS 거래 가능 상태가 보완이다. 출처가 충돌하면 자동 수집과 향후 전략 실행을 허용하지 않는다.

## 당일 확인과 스케줄 판정

예정된 자동 수집 작업은 다음 순서로 판정한다.

```text
현재 XKRX 정규 세션 조회
→ 현재 버전이 없으면 차단
→ conflict 또는 pending이면 차단
→ confirmed_at의 서울 날짜가 trading_date와 다르면 차단
→ confirmed 상태의 closed이면 실행하지 않음
→ open 또는 shortened이면 opens_at·closes_at 범위로 작업 예약
```

당일 07:00 이전 확인이 없으면 데이터 신선도 상태를 지연으로 표시한다. 07:00 이후라도 확인이 완료되기 전까지 스케줄 실행은 계속 차단하며, 뒤늦게 `confirmed`가 되면 이후 작업만 허용한다. 누락된 달력을 평일 규칙이나 직전 거래일 값으로 보완하지 않는다.

## 필수 조회 계약

저장소는 다음 유스케이스를 지원해야 한다.

- 거래소와 날짜로 현재 정규 세션 1건 조회
- 시작일·종료일 범위의 현재 세션 목록 조회
- 기준일보다 엄격히 이후인 다음 `open` 또는 `shortened` 거래일 조회
- 기준일보다 엄격히 이전인 직전 `open` 또는 `shortened` 거래일 조회
- 특정 시각의 수집 스케줄 실행 가능 여부와 차단 사유 반환

조회 결과에는 `source`, `source_as_of`, `received_at`, `verification_state`, `confirmed_at`, `version`을 포함해 호출자가 근거와 신선도를 표시할 수 있어야 한다.

## 데이터 품질과 실패 처리

- 현재 버전이 둘 이상이면 데이터 무결성 오류로 처리한다.
- 열린 세션에 시작·종료시각이 없거나 휴장 세션에 시각이 있으면 저장을 거부한다.
- 세션 시각이 거래일과 다른 서울 날짜로 변환되면 저장을 거부한다.
- 원본 응답 없이 정규화 행만 생성하지 않는다.
- 출처 충돌, 파싱 실패와 DB 실패는 `operations.api_sync_status`에 비밀정보 없는 오류 코드로 기록한다.
- 부분 범위 수집을 전체 성공으로 표시하지 않는다.

## 저장 계층 구현 결과

2026-08-16에 마이그레이션·도메인·PostgreSQL 저장소를 구현해 다음 기준을 충족했다.

- 위 필드와 제약조건을 Alembic 리비전으로 재현할 수 있다.
- 정상 거래일, 휴장일, 단축장과 잘못된 시각 조합을 도메인 테스트로 검증한다.
- 동일 원본 재처리는 멱등이고 정정 입력은 이전 버전을 보존한다.
- 다음·이전 거래일과 당일 스케줄 차단 사유를 PostgreSQL 통합 테스트로 검증한다.
- 기존 시장 데이터 마이그레이션과 수집 테스트가 계속 통과한다.

`20260816_0003` 리비전이 필드, CHECK 제약조건, 버전 유일성과 현재 행 부분 유일 인덱스를 생성한다. 저장소는 원본을 append-only로 남기고 동일 사실 재수신, KRX 정정, 낮은 우선순위 출처 충돌과 동기화 오류 기록을 한 트랜잭션에서 처리한다. KRX 공식 일정 수집과 KIS 당일 보완 확인을 실제 외부 응답에 연결하는 작업은 다음 단계다.
