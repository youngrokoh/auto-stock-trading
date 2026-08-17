# 재무제표 데이터 계약

- 상태: 구현 기준
- 작성일: 2026-08-17
- 승인: 사용자가 2026-08-17에 연결·개별 동시 저장, 최근 5개년 사업보고서 + 당해 분·반기 수집 범위와 이 계약을 구현 기준으로 승인
- 관련 정책: [시장 데이터 및 시점 정책](../spec/market-data-policy.md)
- 관련 계약: [기업행사·수정주가 데이터 계약](corporate-action-adjusted-price-data-contract.md), [재무 지표 정의 계약](financial-indicator-contract.md)
- 관련 로드맵: [구현 로드맵](../plan/implementation-roadmap.md) 4단계

## 목적

국내 상장기업의 공시 재무제표를 원문 근거와 함께 버전 관리하며 저장하고, 정정 공시가 과거 사실을 지우지 않는 point-in-time 기반을 4단계 기업 분석에 제공한다.

## 범위

- 초기 대상은 삼성전자 `005930`이다. ETF(KODEX 200)는 재무제표 대상이 아니며 화면에서 주식만 기업 분석을 제공한다.
- 수집 단위는 OpenDART 단일회사 전체 재무제표(`fnlttSinglAcntAll`)의 보고서(사업연도 × 보고서 유형 × 연결·개별)다. 연결(CFS)과 개별(OFS)을 모두 저장하고, 후속 지표 계산은 연결 기준을 기본으로 하되 기준을 항상 명시한다.
- 기본 수집 범위는 최근 5개년 사업보고서와 당해 분·반기 보고서다. 미제출 기간은 건너뛴다.
- 재무비율·성장성 지표 계산, 외국인·기관 수급, 공시 연결과 기업 분석 화면은 이 계약의 후속 단계이며 별도 정의를 따른다. 저장 사실에서 지표를 파생할 때는 수식·기준일·원문 출처를 함께 제공해야 한다.
- 종목코드와 DART 고유번호 매핑은 현재 수집 대상별 명시 매핑(`005930` ↔ `00126380`)을 사용한다. 전체 `corpCode` 매핑 수집은 종목 마스터 확장 시 별도 계약으로 다룬다.

## 출처와 실측 확인 (2026-08-17)

- 출처는 OpenDART `GET /api/fnlttSinglAcntAll.json`이며 파라미터는 `corp_code`, `bsns_year`, `reprt_code`(11013 1분기, 11012 반기, 11014 3분기, 11011 사업보고서), `fs_div`(CFS 연결, OFS 개별)다.
- 실제 키로 삼성전자 2025 사업보고서(연결 229행), 2026 반기(연결 223행, 접수번호 `20260814003699`), 2026 1분기(개별 137행)를 확인했다.
- 행은 재무제표 구분(`sj_div`: BS·IS·CIS·CF·SCE), IFRS 표준 `account_id`(미사용 계정은 표준 ID 없음), 계정명, 당기·전기·전전기 명칭과 금액, 표시 순서(`ord`), 통화, 그리고 근거 접수번호(`rcept_no`)를 포함한다. 분·반기 보고서에는 전전기 금액이 없다.
- 정정 공시는 같은 보고서 기간에 새 접수번호를 부여하며 API는 최신 상태만 반환한다. 과거 상태는 재조회할 수 없으므로 수집 시점의 사실을 버전으로 보존한다.
- `status=000`이 정상, `013`은 해당 보고서 없음(미제출 기간)이다. 그 외 상태 코드는 fail-closed로 처리한다.
- 원문 표시 순서(`ord`)는 보고서 안에서 유일하지 않다. 자본변동표(SCE)는 같은 `ord`를 자본 구성요소별 여러 행이 공유함을 실수집으로 확인했다(예: 2021 사업보고서의 `기말자본`). 따라서 라인 식별은 응답 내 순번(`line_seq`)을 사용하고 `ord`는 원문 데이터로만 보존한다. (사용자가 2026-08-17 실측 기반 수정을 승인)

## 저장 위치와 식별자

PostgreSQL `fundamental` 스키마에 보고서와 계정 라인을 분리해 저장한다.

```text
논리 보고서 = instrument_id + bsns_year + reprt_code + fs_div
```

## 필드 계약

### `fundamental.financial_report`

| 필드 | DB 타입 | 필수 | 의미 |
|---|---|---|---|
| `id` | `UUID` | 예 | 보고서 버전 식별자 |
| `instrument_id` | `UUID` | 예 | `reference.instrument` 참조 |
| `corp_code` | `VARCHAR(8)` | 예 | DART 고유번호 |
| `bsns_year` | `INTEGER` | 예 | 사업연도 |
| `reprt_code` | `VARCHAR(5)` | 예 | `11011`·`11012`·`11013`·`11014` |
| `fs_div` | `VARCHAR(3)` | 예 | `CFS` 연결, `OFS` 개별 |
| `rcept_no` | `VARCHAR(14)` | 예 | 근거 공시 접수번호 |
| `currency` | `VARCHAR(3)` | 예 | 통화 (실측 `KRW`) |
| `received_at` | `TIMESTAMPTZ` | 예 | 서버 수신 UTC 시각 |
| `version` | `INTEGER` | 예 | 논리 보고서별 사실 버전 |
| `valid_from` | `TIMESTAMPTZ` | 예 | 버전 채택 시각 |
| `superseded_at` | `TIMESTAMPTZ` | 아니요 | 대체 시각, 현재 버전은 `NULL` |
| `raw_response_id` | `UUID` | 예 | `operations.raw_api_response` 참조 |

### `fundamental.financial_statement_line`

| 필드 | DB 타입 | 필수 | 의미 |
|---|---|---|---|
| `id` | `UUID` | 예 | 라인 식별자 |
| `report_id` | `UUID` | 예 | 보고서 버전 참조 (`ON DELETE CASCADE` 없음) |
| `line_seq` | `INTEGER` | 예 | 원문 응답 내 순번 (1부터) |
| `sj_div` | `VARCHAR(3)` | 예 | `BS`·`IS`·`CIS`·`CF`·`SCE` |
| `account_id` | `VARCHAR(255)` | 아니요 | IFRS 표준 계정 ID, 미사용 계정은 `NULL` (실측 최대 180자) |
| `account_nm` | `VARCHAR(200)` | 예 | 계정명 |
| `account_detail` | `VARCHAR(200)` | 아니요 | 계정 상세 (자본변동표 구성요소 등) |
| `ord` | `INTEGER` | 예 | 원문 표시 순서 (유일하지 않음) |
| `thstrm_nm` | `VARCHAR(40)` | 예 | 당기 명칭 |
| `thstrm_amount` | `NUMERIC(32,4)` | 아니요 | 당기 금액, 원문이 비어 있으면 `NULL` |
| `frmtrm_nm` | `VARCHAR(40)` | 아니요 | 전기 명칭 |
| `frmtrm_amount` | `NUMERIC(32,4)` | 아니요 | 전기 금액 |
| `bfefrmtrm_nm` | `VARCHAR(40)` | 아니요 | 전전기 명칭 |
| `bfefrmtrm_amount` | `NUMERIC(32,4)` | 아니요 | 전전기 금액 |

라인은 보고서 버전에 속하는 불변 사실이며 개별 갱신하지 않는다. 금액을 보정·환산·파생하지 않고 원문 그대로 저장한다.

## 키, 제약조건과 인덱스

- 보고서 버전 유일키: `(instrument_id, bsns_year, reprt_code, fs_div, version)`
- 현재 사실: `(instrument_id, bsns_year, reprt_code, fs_div)`별 `superseded_at IS NULL` 행 최대 1개 (부분 유일 인덱스)
- 접수번호 유일키: `(instrument_id, bsns_year, reprt_code, fs_div, rcept_no)` — 같은 접수번호로 두 버전을 만들지 않는다
- 라인 유일키: `(report_id, line_seq)` — 원문 `ord`는 자본변동표에서 중복되므로 키로 쓰지 않는다
- 제약: `bsns_year`는 2000 이상, `reprt_code`·`fs_div`·`sj_div`는 열거값, `version >= 1`, 유효기간 규칙은 기존 버전 테이블과 동일

## 수집과 버전 규칙

1. 외부 응답을 인증정보 없이(`crtfc_key` 제거) `operations.raw_api_response`에 보고서 호출 단위로 append-only 저장한다.
2. 같은 논리 보고서의 같은 `rcept_no` 재수집은 버전을 늘리지 않고 최신 수신 근거만 갱신한다. 라인은 다시 쓰지 않는다.
3. 새 `rcept_no`(정정 공시)를 수신하면 이전 버전에 `superseded_at`을 기록하고 라인 전체를 포함한 새 버전을 만든다. 과거 버전과 라인, 원본은 삭제하지 않는다.
4. 현재 버전보다 오래된 `rcept_no`(접수번호는 접수일 기준 단조 증가)는 현재 사실을 되돌리지 않고 거부한다.
5. `status=013`(보고서 없음)은 정규화 저장 없이 건너뛰고 수집 결과에 개수로 보고한다. 그 외 비정상 상태·서식 위반은 정규화 저장 없이 `operations.api_sync_status`에 비밀정보 없는 오류로 기록한다(fail-closed).
6. 보고서 저장은 보고서 행과 전체 라인을 한 트랜잭션에서 원자적으로 만든다. 부분 저장을 남기지 않는다.

## 필수 조회 계약

- 종목별 현재 버전 보고서 목록을 사업연도·보고서 유형 순으로 조회한다. 응답은 `bsns_year`, `reprt_code`, `fs_div`, `rcept_no`, `currency`, `version`, `valid_from`, 출처를 포함한다.
- 보고서(현재 버전)의 계정 라인을 원문 순번(`line_seq`) 순으로 조회한다.
- 논리 보고서의 정정 이력(전체 버전)을 조회한다.
- 파생 지표는 이 계약의 저장 사실을 입력으로만 계산하며 수식·기준일·`rcept_no` 출처 없이 노출하지 않는다.

## 데이터 품질과 실패 처리

- 금액 문자열이 수가 아니면 해당 보고서 전체를 저장하지 않는다. 빈 문자열만 `NULL`로 저장한다.
- 원문에 없는 기간·계정을 추정해 채우지 않는다.
- 통화가 `KRW`가 아니면 저장은 하되 조회 응답에 통화를 항상 노출해 무단 환산을 막는다.
- API 키는 원본·로그·문서에 저장하지 않는다.

## 검증 시나리오

1. 같은 보고서 재수집은 버전과 라인 수를 늘리지 않는다.
2. 새 접수번호 수신은 이전 버전과 라인을 보존한 채 새 버전을 만들고, 오래된 접수번호는 거부된다.
3. `status=013`은 아무것도 저장하지 않고 건너뛴 개수로 보고된다.
4. 실제 키로 삼성전자 최근 사업보고서와 당해 분·반기 보고서를 수집해 자산총계·매출·영업이익 등 주요 계정을 DART 원문 뷰어와 대조한다.
5. 멱등 재수집과 읽기 API의 보고서 목록·라인·이력 응답을 실제 PostgreSQL에서 검증한다.

## 구현 결과 (2026-08-17)

- Alembic `20260817_0009`가 두 테이블을 계약의 유일키(`version`·`rcept_no`·`line_seq`)와 제약조건으로 생성한다.
- `DartFinancialStatementAdapter`가 엄격 파싱(단일 접수번호·통화 검증, 금액 검증, 미사용 표준계정 `NULL` 정규화)으로 보고서를 만들고, `PostgresFinancialReportStore`가 원본 append-only 저장과 접수번호 기반 버전 규칙(같은 접수번호 멱등, 새 접수번호 정정 버전, 오래된 접수번호 거부)을 구현한다. 조회는 별도 `PostgresFinancialReportReader`가 담당한다.
- worker `python -m auto_stock_trading.worker.fundamentals`가 승인 범위(최근 5개년 사업보고서 + 당해 분·반기 × 연결·개별)를 수집한다.
- 실제 키로 삼성전자 14개 보고서(2021~2025 사업보고서, 2026 1분기·반기 × 연결·개별)를 수집했고 2026 3분기 2건은 미제출로 건너뛰었다. 재수집은 버전을 늘리지 않았고, 자산총계(2025 연결 566,942,110,000,000 / 2026 반기 연결 759,480,516,000,000 / 2026 1분기 개별 404,509,604,000,000)와 라인 수(229·223·137 등)가 DART 원문 응답과 일치했다.
- 읽기 API는 보고서 목록·라인·정정 이력을 접수번호 근거와 함께 제공하며 미등록 종목은 404다.

## 구현 순서

1. 완료: `fundamental.financial_report`·`financial_statement_line` Alembic 마이그레이션
2. 완료: OpenDART 전체 재무제표 어댑터(엄격 파싱)와 수집 유스케이스
3. 완료: 버전 저장소와 worker 수동 CLI
4. 완료: 읽기 API (보고서 목록·라인·이력)
5. 완료: fixture·PostgreSQL 통합 테스트와 실제 원문 대조
6. 완료: 영향 문서 갱신
