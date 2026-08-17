# 기업 재무 읽기 API

- 상태: 구현됨
- 구현일: 2026-08-17
- 기준 경로: `/api/fundamentals`
- 관련 계약: [재무제표 데이터 계약](../data/financial-statement-data-contract.md), [재무 지표 정의 계약](../data/financial-indicator-contract.md), [수급·공시 연결 데이터 계약](../data/investor-flow-disclosure-contract.md)

## 범위

OpenDART에서 수집한 재무제표 사실 버전, 그 사실에서 파생한 지표(성장성·수익성·안정성·가치)와 DART 공시 목록을 읽기 전용으로 제공한다.

| 메서드 | 경로 | 응답 |
|---|---|---|
| `GET` | `/api/fundamentals/instruments/{symbol}/financial-reports` | 현재 버전 보고서 목록 (사업연도·유형·연결구분 순) |
| `GET` | `/api/fundamentals/instruments/{symbol}/financial-reports/history` | 논리 보고서의 정정 이력 전체 (`bsns_year`·`reprt_code`·`fs_div` 쿼리 필수) |
| `GET` | `/api/fundamentals/financial-reports/{report_id}` | 보고서 버전의 계정 라인 (원문 순번 순) |
| `GET` | `/api/fundamentals/instruments/{symbol}/indicators` | 연간 보고서별 지표와 실적 원문 값 (사업연도 오름차순, `fs_div` 쿼리 기본 `CFS`) |
| `GET` | `/api/fundamentals/instruments/{symbol}/disclosures` | DART 공시 목록 (접수일 내림차순, `limit` 기본 30) |

## 재무 지표 응답

[재무 지표 정의 계약](../data/financial-indicator-contract.md)을 따른다.

- 연간 사업보고서(`11011`)의 현재 버전에서만 조회 시점에 계산하며 저장하지 않는다.
- 연도 항목은 `bsns_year`, `reprt_code`, `fs_div`, 근거 `rcept_no`, `currency`, `version`을 포함한다.
- 지표 항목은 키·이름·분류(`growth`·`profitability`·`stability`), 단위(`percent`), 수식 문자열, 입력 계정(이름·`sj_div`·`account_id`·기간·금액), 값 또는 실패 사유 코드(`MISSING_ACCOUNT`·`AMBIGUOUS_ACCOUNT`·`MISSING_AMOUNT`·`ZERO_DENOMINATOR`)를 포함한다.
- 실적 원문 값(`figures`)은 매출액·영업이익·당기순이익·지배주주순이익·자산·부채·자본 금액을 계정 출처와 함께 원문 그대로 제공한다.
- 개별(`OFS`) 조회에서 지배주주 계정이 없는 ROE는 계약대로 값 없이 `MISSING_ACCOUNT`를 반환한다.
- `valuation` 블록이 가치지표(기본주당이익 원문 `eps`, `per`, `market_cap`)를 제공한다. 기준이
  서로 다른 세 입력을 결합하므로 가격(값·기준시각·출처), 상장주식수(값·기준시각·출처·버전),
  재무(사업연도·유형·구분·`rcept_no`·버전) 기준을 항상 별도 노출하고, 저장된 시세·주식수가
  없으면 `MISSING_QUOTE`·`MISSING_SHARE_COUNT`로 해당 항목만 빈 값이다. 연간 보고서가 없으면
  (ETF 포함) `valuation`은 `null`이다. BPS·PBR은 우선주 반영 설계 확정 시 추가한다.
- 미등록 종목은 404, 잘못된 `fs_div`는 422다.

## 출처와 버전

- 모든 보고서는 근거 공시 접수번호(`rcept_no`), 연결·개별 구분(`fs_div`: `CFS`·`OFS`), 보고서 유형(`reprt_code`: `11011` 사업보고서, `11012` 반기, `11013` 1분기, `11014` 3분기), 통화와 `version`·`valid_from`·`superseded_at`을 노출한다. 출처는 `DART`다.
- 정정 공시는 이전 버전을 보존한 새 버전으로 나타나고 이력 조회로 확인한다.
- 계정 라인은 재무제표 구분(`sj_div`: BS·IS·CIS·CF·SCE), IFRS 표준 `account_id`(미사용 계정 `null`), 원문 응답 순번(`line_seq`)과 표시 순서(`ord`), 당기·전기·전전기 명칭과 금액을 원문 그대로 노출한다. 금액은 정밀도를 보존하는 문자열로 직렬화된다.
- 파생·환산 값은 없다. 지표 계산은 이 사실을 입력으로 수식·기준일·출처와 함께 별도 정의한다.

## 공시 목록

[수급·공시 연결 데이터 계약](../data/investor-flow-disclosure-contract.md)을 따른다. 항목은
접수번호(`rcept_no`)·보고서명·제출인·접수일·유형(`A` 정기, `B` 주요사항, `D` 지분, `I`
거래소)을 포함하는 불변 사실이며, 정정 공시는 새 접수번호로 나타난다. 화면은 접수번호로
DART 원문 뷰어에 연결한다. 문서 원문은 저장하지 않는다.

## 수집 작업

```bash
cd backend
AUTO_STOCK_DART_API_KEY_FILE=../.secrets/dart-api-key \
  uv run python -m auto_stock_trading.worker.fundamentals
```

기본 대상은 삼성전자(`005930`, 고유번호 `00126380`)이며 승인 범위(최근 5개년 사업보고서 + 당해 분·반기 × 연결·개별)를 수집한다. `--collect-disclosures`를 주면 최근 1년의 공시 목록(정기·주요사항·지분·거래소)을 수집한다. 미제출 기간은 건너뛰고, 같은 접수번호 재수집은 버전을 늘리지 않는다. API 키는 문서·Git·로그에 기록하지 않는다.

## 현재 제한

- 수집 대상은 명시 매핑된 종목뿐이다. 전체 종목코드·고유번호 매핑은 종목 마스터 확장 시 다룬다.
- ETF는 재무제표 대상이 아니다.
