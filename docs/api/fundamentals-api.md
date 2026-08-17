# 기업 재무 읽기 API

- 상태: 구현됨
- 구현일: 2026-08-17
- 기준 경로: `/api/fundamentals`
- 관련 계약: [재무제표 데이터 계약](../data/financial-statement-data-contract.md)

## 범위

OpenDART에서 수집한 재무제표 사실 버전을 읽기 전용으로 제공한다. 재무비율·성장성 지표 계산과 수급·공시 연결 API는 후속 단계다.

| 메서드 | 경로 | 응답 |
|---|---|---|
| `GET` | `/api/fundamentals/instruments/{symbol}/financial-reports` | 현재 버전 보고서 목록 (사업연도·유형·연결구분 순) |
| `GET` | `/api/fundamentals/instruments/{symbol}/financial-reports/history` | 논리 보고서의 정정 이력 전체 (`bsns_year`·`reprt_code`·`fs_div` 쿼리 필수) |
| `GET` | `/api/fundamentals/financial-reports/{report_id}` | 보고서 버전의 계정 라인 (원문 순번 순) |

## 출처와 버전

- 모든 보고서는 근거 공시 접수번호(`rcept_no`), 연결·개별 구분(`fs_div`: `CFS`·`OFS`), 보고서 유형(`reprt_code`: `11011` 사업보고서, `11012` 반기, `11013` 1분기, `11014` 3분기), 통화와 `version`·`valid_from`·`superseded_at`을 노출한다. 출처는 `DART`다.
- 정정 공시는 이전 버전을 보존한 새 버전으로 나타나고 이력 조회로 확인한다.
- 계정 라인은 재무제표 구분(`sj_div`: BS·IS·CIS·CF·SCE), IFRS 표준 `account_id`(미사용 계정 `null`), 원문 응답 순번(`line_seq`)과 표시 순서(`ord`), 당기·전기·전전기 명칭과 금액을 원문 그대로 노출한다. 금액은 정밀도를 보존하는 문자열로 직렬화된다.
- 파생·환산 값은 없다. 지표 계산은 이 사실을 입력으로 수식·기준일·출처와 함께 별도 정의한다.

## 수집 작업

```bash
cd backend
AUTO_STOCK_DART_API_KEY_FILE=../.secrets/dart-api-key \
  uv run python -m auto_stock_trading.worker.fundamentals
```

기본 대상은 삼성전자(`005930`, 고유번호 `00126380`)이며 승인 범위(최근 5개년 사업보고서 + 당해 분·반기 × 연결·개별)를 수집한다. 미제출 기간은 건너뛰고, 같은 접수번호 재수집은 버전을 늘리지 않는다. API 키는 문서·Git·로그에 기록하지 않는다.

## 현재 제한

- 수집 대상은 명시 매핑된 종목뿐이다. 전체 종목코드·고유번호 매핑은 종목 마스터 확장 시 다룬다.
- ETF는 재무제표 대상이 아니다.
