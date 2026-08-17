# 기업행사·수정주가 데이터 계약

- 상태: 승인
- 작성일: 2026-08-16
- 승인일: 2026-08-16
- 초기 범위: 국내주식·국내 ETF의 일봉 기업행사와 수정주가
- 관련 정책: [시장 데이터 및 시점 정책](../spec/market-data-policy.md)
- 관련 결정: [ADR-0003](../decisions/0003-data-architecture.md)
- 선행 계약: [국내 시장 달력 데이터 계약](market-calendar-data-contract.md)

## 목적

이 계약은 기업행사 사실과 비수정 일봉을 이용해 재현 가능한 수정주가 데이터셋을 만드는 기준이다. 액면분할·병합이나 배당으로 생긴 가격 단절을 실제 손익과 혼동하지 않고, 백테스트가 당시 공개되지 않은 정보나 사후 정정을 미리 사용하지 못하게 한다.

승인된 시장 데이터 정책을 구현 가능한 필드, 계산식과 불변조건으로 구체화한다. 원본 응답, 정규화 사실과 파생 데이터를 분리하는 [ADR-0003](../decisions/0003-data-architecture.md)의 경계 안에서 구현하므로 새 저장 기술은 도입하지 않는다. 이 계약과 승인 정책이 충돌하면 승인 정책을 우선하고 구현을 중단한다.

## 승인된 핵심 결정

사용자는 2026-08-16에 아래 테이블, 계산 방식과 조회 계약을 구현 기준으로 승인했다.

승인된 핵심 결정은 다음과 같다.

1. 비수정 일봉은 사실 데이터로 유지하고 수정주가는 별도 파생 데이터셋으로 저장한다.
2. 차트·기술지표 기본값은 `split_adjusted`, 총수익 비교용은 `total_return`으로 구분한다.
3. 주문 체결과 포트폴리오 손익에는 수정주가를 사용하지 않고 비수정 가격과 별도 현금흐름을 사용한다.
4. 기업행사와 비수정 일봉의 과거 버전을 보존한 뒤 수정주가 구현을 시작한다.

## 범위

초기 구현은 다음을 포함한다.

- 국가 `KR`, 거래소 MIC `XKRX`
- 국내 상장 보통주와 국내 상장 ETF
- 확정된 일봉 `1d`
- 액면분할, 액면병합과 주식배당에 따른 주식 수 변화
- 현금배당과 ETF 분배금
- 유상증자·권리락, 감자, 합병, 분할, 거래정지와 상장폐지의 사실 보존
- 수정 방식, 지식 기준시각과 입력 버전이 고정된 파생 데이터셋
- 차트·보조지표·백테스트가 사용할 조회와 계보 정보

분봉 조정, 미국 기업행사, 세금 원천징수, 외화 환산, 종목 간 합병 교환비율을 이용한 연속 수익률, 파생상품과 실시간 예상 권리락 가격은 초기 범위에 포함하지 않는다. 지원하지 않는 기업행사가 조회 범위의 가격 연속성에 영향을 줄 수 있으면 추정하지 않고 해당 수정주가 데이터셋 생성을 차단한다.

## 용어와 계층

```text
외부 원본 응답
    ↓
비수정 일봉 버전 + 기업행사 사실 버전
    ↓
수정주가 데이터셋 메타데이터
    ↓
데이터셋에 종속된 수정 일봉
```

- **비수정 일봉**: 해당 거래일에 실제 체결된 가격과 수량을 원천 의미 그대로 정규화한 사실이다.
- **기업행사**: 발행 주식 수, 현금흐름, 종목 상태 또는 종목 정체성에 영향을 주는 공식 사건이다.
- **수정주가**: 비교 가능한 과거 가격 계열을 만들기 위해 비수정 일봉에 계산계수를 적용한 파생 데이터다.
- **정보 가용시각**: 해당 기업행사 버전이 공식 출처를 통해 시장 참가자에게 공개된 시각이다.
- **가격 기준일**: 수정계수에 포함할 기업행사가 실제로 발생한 마지막 거래일이다.
- **입력 버전**: 수정주가 생성에 사용한 비수정 일봉과 기업행사 버전의 고정된 집합이다.

## KIS 가격 구분 경계

KIS의 `FID_ORG_ADJ_PRC` 의미는 TR별 공식 설명을 확인한 뒤 매핑한다. 현재 사용하는 국내주식기간별시세 `inquire-daily-itemchartprice`는 KIS 공식 샘플에서 `0=수정주가`, `1=원주가`로 설명하므로 `FID_ORG_ADJ_PRC=1` 응답을 `adjusted=false`로 저장한다.

이 값을 이름만 보고 다른 TR에 일반화하지 않는다. KIS 공식 구성에는 국내주식 일자별 `inquire-daily-price`처럼 같은 필드의 설명이 다른 TR도 있으므로 새 TR을 연결할 때는 해당 TR의 요청값 두 가지를 기업행사 전후 종목으로 대조하는 계약 테스트가 필수다. KIS 제공 수정주가는 내부 계산의 검증 자료로만 사용하고 기업행사 사실이나 내부 수정계수를 대신하지 않는다.

공식 참고: [KIS Open Trading API 국내주식 구성](https://github.com/koreainvestment/open-trading-api/blob/main/MCP/Kis%20Trading%20MCP/configs/domestic_stock.json)

## 기업행사 유형 계약

| `action_type` | 핵심 조건 | `split_adjusted` | `total_return` | 보유 현금·수량 반영 |
|---|---|---|---|---|
| `stock_split` | `share_multiplier > 1` | 반영 | 반영 | 수량 증가 |
| `reverse_split` | `0 < share_multiplier < 1` | 반영 | 반영 | 수량 감소 |
| `stock_dividend` | `share_multiplier > 1` | 반영 | 반영 | 수량 증가 |
| `cash_dividend` | `cash_amount > 0` | 제외 | 반영 | 현금 유입 |
| `etf_distribution` | `cash_amount > 0` | 제외 | 반영 | 현금 유입 |
| `rights_issue` | 권리락일·배정비율·발행가 | 초기 자동계산 제외 | 초기 자동계산 제외 | 후속 구현 |
| `capital_reduction` | 감자 효력일·비율 | 초기 자동계산 제외 | 초기 자동계산 제외 | 후속 구현 |
| `merger` | 소멸·존속 종목과 교환비율 | 초기 자동계산 제외 | 초기 자동계산 제외 | 후속 구현 |
| `spin_off` | 신설·존속 종목과 배정비율 | 초기 자동계산 제외 | 초기 자동계산 제외 | 후속 구현 |
| `trading_suspension` | 시작일·해제일 | 가격조정 없음 | 가격조정 없음 | 거래 가능 상태 차단 |
| `delisting` | 상장폐지일 | 가격조정 없음 | 가격조정 없음 | 거래 가능 상태 종료 |

`rights_issue`, `capital_reduction`, `merger`와 `spin_off`는 사실을 저장하되 계산기가 명시적으로 지원하기 전까지 이를 포함하는 기간의 수정주가를 `published`로 만들지 않는다. 거래정지와 상장폐지는 수정계수가 아니라 거래 가능 상태와 결측 해석의 근거다.

## 기업행사 사실 계약

정규화 테이블 이름은 `market.corporate_action`으로 한다. 한 논리 기업행사는 애플리케이션이 발급한 `action_key`로 식별하고, 같은 사건의 발표·확정·정정·취소는 버전을 증가시켜 보존한다.

### `market.corporate_action` 필드

| 필드 | DB 타입 | 필수 | 의미 |
|---|---|---|---|
| `id` | `UUID` | 예 | 행 식별자 |
| `action_key` | `UUID` | 예 | 기업행사 논리 식별자 |
| `instrument_id` | `UUID` | 예 | `reference.instrument.id` |
| `action_type` | `VARCHAR(32)` | 예 | 기업행사 유형 |
| `lifecycle_status` | `VARCHAR(16)` | 예 | `announced`, `confirmed`, `cancelled` |
| `quality_state` | `VARCHAR(16)` | 예 | `pending`, `verified`, `conflict`, `unsupported` |
| `announced_at` | `TIMESTAMPTZ` | 아니요 | 최초 발표시각. 날짜만 제공되면 서울 기준 장 시작시각을 임의 생성하지 않고 별도 정밀도 값과 함께 저장 |
| `announcement_date` | `DATE` | 예 | 공식 발표일 |
| `time_precision` | `VARCHAR(8)` | 예 | `date`, `minute`, `second` |
| `ex_date` | `DATE` | 조건부 | 권리·배당락이 가격에 반영되는 거래일 |
| `effective_date` | `DATE` | 조건부 | 주식 수나 종목 상태가 법적으로 효력을 갖는 날짜 |
| `record_date` | `DATE` | 아니요 | 권리 확정 기준일 |
| `payment_date` | `DATE` | 아니요 | 현금 또는 주식 지급일 |
| `share_multiplier` | `NUMERIC(24,12)` | 조건부 | 행사 후 주식 수 / 행사 전 주식 수 |
| `cash_amount` | `NUMERIC(24,8)` | 조건부 | 세전 주당 현금배당·분배금 |
| `currency` | `VARCHAR(3)` | 조건부 | 현금 금액의 통화, 초기값 `KRW` |
| `subscription_price` | `NUMERIC(24,8)` | 아니요 | 유상증자 발행가 |
| `related_instrument_id` | `UUID` | 아니요 | 합병·분할 등 연관 종목 |
| `source` | `VARCHAR(32)` | 예 | 현재 버전의 채택 출처 |
| `source_event_id` | `VARCHAR(120)` | 예 | 공시 접수번호나 출처 내 사건 식별자 |
| `source_reference` | `VARCHAR(240)` | 예 | 인증정보 없는 공식 원문 경로 |
| `available_at` | `TIMESTAMPTZ` | 예 | 이 버전의 조건이 공식적으로 공개된 시각 |
| `received_at` | `TIMESTAMPTZ` | 예 | 시스템이 원본을 받은 UTC 시각 |
| `version` | `INTEGER` | 예 | `action_key`별 1부터 증가하는 사실 버전 |
| `valid_from` | `TIMESTAMPTZ` | 예 | 이 버전을 현재 사실로 채택한 UTC 시각 |
| `superseded_at` | `TIMESTAMPTZ` | 아니요 | 후속 버전으로 대체된 UTC 시각 |
| `raw_response_id` | `UUID` | 예 | `operations.raw_api_response.id` |
| `created_at` | `TIMESTAMPTZ` | 예 | 행 생성 UTC 시각 |

공식 원문에 발표시각이 없으면 `announced_at=NULL`, `time_precision=date`로 저장한다. `available_at`은 출처가 제공하는 게시시각을 사용하고 게시시각도 없으면 `received_at`을 사용해 보수적으로 처리한다. 날짜만 있는 발표를 장 시작 전 공개로 추정하지 않는다.

### 기업행사 키와 버전 제약

- 버전 유일성: `(action_key, version)`
- 출처 사건 유일성: `(source, source_event_id, version)`
- 현재 버전 유일성: `action_key`에서 `superseded_at IS NULL`인 행은 최대 1개
- 조회 인덱스: `(instrument_id, ex_date)`, `(instrument_id, effective_date)`, `(instrument_id, available_at)`
- `version >= 1`
- `available_at <= received_at`을 강제하지 않는다. 공식 과거 게시물을 나중에 수집할 수 있기 때문이다.
- `superseded_at IS NULL OR superseded_at > valid_from`
- `cash_amount`, `subscription_price`는 음수가 아니어야 한다.
- `share_multiplier`가 있으면 0보다 커야 한다.
- `cancelled` 버전은 계산 입력에서 제외하지만 삭제하지 않는다.
- 같은 출처 사건을 반복 처리해도 새 버전이 생기지 않아야 한다.

### 필수 조건

- `stock_split`, `reverse_split`, `stock_dividend`: `ex_date` 또는 `effective_date`와 `share_multiplier`가 필수다.
- `cash_dividend`, `etf_distribution`: `ex_date`, `cash_amount`, `currency`가 필수다. `payment_date`가 없으면 현금흐름 확정 전 상태를 유지한다.
- `rights_issue`: `ex_date`, 배정비율에 해당하는 `share_multiplier`, `subscription_price`가 모두 확인되어야 계산 지원 후보가 된다.
- `trading_suspension`: `effective_date`를 시작일로 사용하고 해제는 새 버전이나 별도 논리 사건으로 기록한다.
- `delisting`: `effective_date`가 필수다.

조건이 부족한 사건은 `pending`, 공식 출처가 충돌하면 `conflict`, 계산 미지원 유형은 `unsupported`로 둔다. 이 세 상태는 수정주가 발행 전에 명시적으로 판정한다.

### 구현 결과

- Alembic `20260816_0006`이 `market.corporate_action`을 계약의 필드, `(action_key, version)`·`(source, source_event_id, version)` 유일키, `superseded_at IS NULL` 부분 유일 인덱스와 유형·생애주기·품질 상태·시간 정밀도·금액·유효기간 제약조건으로 생성한다.
- 도메인 타입은 기업행사 유형·생애주기·품질 상태·시간 정밀도 열거형과 양수 배수, 음수 금액 금지, `announced_at`·`time_precision` 일관성 불변조건 검증을 제공한다.
- 같은 출처 사건의 반복 처리는 현재 버전을 재사용하고 더 새로운 수신 근거만 갱신한다. 날짜·비율·금액·상태가 바뀌면 이전 버전을 보존한 채 새 버전을 만들고, 취소 버전도 삭제하지 않는다. 최신 수신 근거보다 오래된 정정은 거부한다.
- 저장소 조회는 현재 사실, 전체 정정·취소 이력과 `available_at <= knowledge_cutoff_at`에서 당시 알 수 있었던 최신 버전 선택을 제공한다. `available_at`은 원본 사실이 아니라 지식 시점 메타데이터이므로 동일 사실 재수신 시 최초 인지 시각을 보존한다.
- OpenDART 수집은 공시검색 목록과 원본 문서를 append-only 보존한 뒤 `현금ㆍ현물배당결정` 서식을 엄격 파싱해 저장한다. 접수번호가 다른 기재정정은 같은 종목·`cash_dividend`·배당기준일이 모두 일치할 때만 같은 `action_key`로 연결하고, 그 외에는 자동 병합하지 않는다.
- 배당 공시는 배당기준일만 제공하므로 `ex_date`는 저장하지 않고 계산 조건 미충족(`pending`) 상태로 둔다. 배당락일 확정은 공식 출처 확인이 있는 후속 단계에서 처리한다.
- ETF 분배금은 운용사(삼성자산운용) 공식 KODEX 분배금 데이터에서 지급기준일·세전 주당분배금·실지급일을 수집하고, 출처 내 사건 식별자는 `펀드ID:지급기준일`로 고정한다. 지급 완료 이력이므로 `confirmed`로 저장하되 품질은 `pending`을 유지한다. 발표시각이 없는 출처의 발표일·`available_at`은 최초 수신 시점으로 보수 처리하고 재수신 시 최초 인지 값을 보존한다.
- 액면분할·감자 등 나머지 유형 수집, 배당·분배락일 확정, 출처 충돌 판정과 수정주가 계산기는 아직 구현 전이다.

## 출처와 충돌 규칙

기업행사는 한 출처가 모든 시점과 조건의 우선권을 갖는다고 가정하지 않는다.

| 사실 | 1차 근거 | 보완·대조 |
|---|---|---|
| 발표시점·이사회 결정·지급 조건 | OpenDART 원문 공시, ETF 운용사 공식 공지 | KIND 공시 연결 |
| 거래소 권리락·효력일·거래정지·상장폐지 | KRX/KIND 공식 시장 공지 | OpenDART 원문 |
| 일봉의 권리 발생 표시·비율 | 위 공식 기업행사와 KIS 비수정 일봉 응답 | KIS 수정주가 응답 |
| 배당·분배금 지급 결과 | OpenDART, KIND 또는 ETF 운용사 공식 지급 공지 | KIS 제공 범위 |

OpenDART는 배당 및 증자·감자 정보를 제공하지만 거래소 운영일의 대체물이 아니다. 자세한 제공 범위는 [OpenDART 개발가이드](https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS002)를 따른다.

같은 논리 사건의 날짜, 비율 또는 금액이 출처 사이에서 다르면 한쪽으로 자동 덮어쓰지 않는다. `quality_state=conflict`로 기록하고 충돌한 원본을 모두 보존하며, 해소 전에는 영향을 받는 데이터셋을 발행하지 않는다. 사건 연결이 확실하지 않으면 두 사건을 자동 병합하지 않는다.

## 비수정 일봉 버전 선행조건

`market.market_bar`는 처음에 `(instrument_id, interval, trading_date, adjusted, source)`를 유일키로 사용하고 재수집 값을 현재 행에 덮어썼다. 과거 입력값을 재현할 수 있도록 2026-08-16에 다음 선행조건을 구현했다.

- `market.market_bar`는 비수정 사실만 저장하고 `adjusted=false`를 유지한다.
- 논리 일봉별 `version`, `valid_from`, `superseded_at`과 최종 확정 상태를 추가한다.
- 동일 값 재수신은 현재 버전의 수신 근거만 갱신하고, OHLCV·거래대금·정정 코드가 바뀌면 새 버전을 만든다.
- 현재 버전은 논리 일봉별 하나만 허용하고 이전 버전과 원본 응답을 삭제하지 않는다.
- 수정 일봉을 `market.market_bar`의 `adjusted=true` 행으로 혼합하지 않는다.
- 전환 마이그레이션은 기존 행을 `version=1` 비수정 사실로 보존해야 한다.

`DailyBar.adjusted`와 DB의 `adjusted` 열은 현재 KIS 원주가 매핑을 검증하는 과도기 필드다. 수정주가 데이터셋이 구현되면 읽기 모델에서 원본과 파생 타입을 분리하고, 이 불리언의 제거 여부는 마이그레이션 영향 검토 후 결정한다.

### 구현 결과

- Alembic `20260816_0005`가 기존 비수정 일봉을 `version=1`, `finality=pending`, `valid_from=received_at`으로 보존한다.
- 버전 유일키와 `superseded_at IS NULL` 부분 유일 인덱스로 전체 이력과 현재 사실 하나를 함께 보장한다.
- 같은 사실의 재수신은 최신 원본 근거와 `received_at`만 갱신하며 확정 상태를 낮추지 않는다. 최신 수신 근거보다 오래된 정정 응답은 새 버전으로 채택하지 않는다.
- 현재 사실과 정확히 일치하는 재확인만 `confirmed`로 전환한다. 정정은 이전 버전을 보존하고 새 `pending` 버전을 만든다.
- 읽기 API는 현재 버전만 반환하면서 `version`, `valid_from`, `finality`, `confirmed_at`을 노출한다.

## 수정주가 데이터셋 계약

수정주가는 생성 실행 단위의 메타데이터와 개별 일봉을 분리한다.

### `market.adjustment_dataset`

| 필드 | DB 타입 | 필수 | 의미 |
|---|---|---|---|
| `id` | `UUID` | 예 | 데이터셋 식별자 |
| `instrument_id` | `UUID` | 예 | 대상 종목 |
| `interval` | `VARCHAR(8)` | 예 | 초기값 `1d` |
| `method` | `VARCHAR(24)` | 예 | `split_adjusted`, `total_return` |
| `range_start` | `DATE` | 예 | 첫 거래일 |
| `price_cutoff_date` | `DATE` | 예 | 포함한 가격·기업행사의 마지막 거래일 |
| `knowledge_cutoff_at` | `TIMESTAMPTZ` | 예 | 사용할 수 있는 기업행사 버전의 정보 가용 상한 |
| `algorithm_version` | `VARCHAR(40)` | 예 | 계산식 구현 버전 |
| `input_bar_version_hash` | `VARCHAR(64)` | 예 | 정렬된 비수정 일봉 ID·버전 집합의 SHA-256 |
| `action_version_hash` | `VARCHAR(64)` | 예 | 정렬된 기업행사 ID·버전 집합의 SHA-256 |
| `status` | `VARCHAR(16)` | 예 | `building`, `published`, `superseded`, `failed` |
| `generated_at` | `TIMESTAMPTZ` | 예 | 생성 완료 UTC 시각 |
| `superseded_at` | `TIMESTAMPTZ` | 아니요 | 후속 데이터셋으로 대체된 UTC 시각 |
| `failure_code` | `VARCHAR(80)` | 아니요 | 비밀정보 없는 실패 코드 |

입력 해시는 JSON 직렬화에 의존하지 않고 계약에서 정한 UTF-8 행 형식을 거래일순으로 연결해 계산한다. 정확한 직렬화 형식은 구현 전에 테스트 벡터로 고정한다.

발행 데이터셋 유일성은 `(instrument_id, interval, method, range_start, price_cutoff_date, knowledge_cutoff_at, algorithm_version, input_bar_version_hash, action_version_hash)`다. 같은 입력을 반복 계산하면 기존 `published` 데이터셋을 반환하고 새 행을 만들지 않는다.

### `market.adjustment_dataset_action`

입력 해시만으로 기업행사 계보를 복원하지 않는다. 데이터셋에 포함된 각 기업행사 버전과 그 사건의 계산 결과를 명시적으로 연결한다.

| 필드 | DB 타입 | 필수 | 의미 |
|---|---|---|---|
| `dataset_id` | `UUID` | 예 | `market.adjustment_dataset.id` |
| `corporate_action_id` | `UUID` | 예 | 사용한 `market.corporate_action` 버전 행 |
| `action_key` | `UUID` | 예 | 논리 기업행사 식별자 |
| `action_version` | `INTEGER` | 예 | 사용한 사실 버전 |
| `event_date` | `DATE` | 예 | 계수를 적용한 배당락일 또는 효력일 |
| `event_price_factor` | `NUMERIC(32,16)` | 예 | 해당 사건의 가격계수. 가격조정 없는 사건은 `1` |
| `event_volume_factor` | `NUMERIC(32,16)` | 예 | 해당 사건의 거래량계수. 거래량조정 없는 사건은 `1` |
| `created_at` | `TIMESTAMPTZ` | 예 | 행 생성 UTC 시각 |

- 기본키: `(dataset_id, corporate_action_id)`
- `(action_key, action_version)`은 참조한 기업행사 행과 일치해야 한다.
- `action_version_hash`는 이 테이블에 연결된 기업행사 ID·버전을 `event_date`, `action_key` 순으로 직렬화한 결과와 일치해야 한다.
- 가격계수와 거래량계수는 0보다 커야 한다.

### `market.adjusted_market_bar`

| 필드 | DB 타입 | 필수 | 의미 |
|---|---|---|---|
| `id` | `UUID` | 예 | 행 식별자 |
| `dataset_id` | `UUID` | 예 | `market.adjustment_dataset.id` |
| `source_bar_id` | `UUID` | 예 | 사용한 비수정 일봉 버전 행 |
| `trading_date` | `DATE` | 예 | 거래일 |
| `open_price` | `NUMERIC(24,8)` | 예 | 수정 시가 |
| `high_price` | `NUMERIC(24,8)` | 예 | 수정 고가 |
| `low_price` | `NUMERIC(24,8)` | 예 | 수정 저가 |
| `close_price` | `NUMERIC(24,8)` | 예 | 수정 종가 |
| `volume` | `BIGINT` | 예 | 주식 수 변화가 반영된 수정 거래량 |
| `trading_value` | `NUMERIC(32,8)` | 예 | 원본 거래대금. 수정계수를 적용하지 않음 |
| `price_factor` | `NUMERIC(32,16)` | 예 | 비수정 가격에 곱한 누적계수 |
| `volume_factor` | `NUMERIC(32,16)` | 예 | 비수정 거래량에 곱한 누적계수 |
| `created_at` | `TIMESTAMPTZ` | 예 | 행 생성 UTC 시각 |

- 유일성: `(dataset_id, trading_date)`
- `source_bar_id`는 해당 데이터셋 입력 해시에 포함된 확정 비수정 일봉이어야 한다.
- 요청 범위에 존재하는 확정 비수정 일봉은 수정 일봉과 1:1로 대응해야 한다. 시장 거래일에 일봉이 없는 경우 상장 전·상장폐지 후이거나 공식 `trading_suspension`으로 설명되어야 하며, 그 날짜는 명시적인 gap으로 노출하고 합성 일봉을 만들지 않는다. 설명되지 않는 누락은 발행을 차단한다.
- 파생 일봉은 원본 응답을 직접 참조하지 않고 데이터셋과 비수정 일봉을 통해 계보를 추적한다.
- 반영 기업행사는 `market.adjustment_dataset_action`을 통해 조회한다.
- `published` 이후 데이터셋과 파생 일봉은 수정하지 않는다.

### 저장 규모 경계

초기 운영 조회와 검증용 데이터셋은 PostgreSQL에 저장한다. 6단계의 장기간·다종목 백테스트가 동일 종목에 많은 `knowledge_cutoff_at` 데이터셋을 요구하면 일자별 PostgreSQL 복제 행을 무제한 생성하지 않는다. [ADR-0003](../decisions/0003-data-architecture.md)에 따라 버전된 Parquet point-in-time 스냅샷을 생성하고 PostgreSQL에는 스냅샷 메타데이터, 입력 해시와 결과 위치만 보존한다. Parquet 전환 형식은 실제 규모가 확인될 때 별도 계약으로 정의한다.

## 계산 방식

### 공통 규칙

한 거래일 `d`의 수정계수에는 `d`보다 뒤에 있고 `price_cutoff_date` 이하에서 발생한 지원 기업행사를 포함한다. 같은 효력일에는 주식 수 변화 계수를 먼저 확정하고 현금 계수를 그다음 계산한다. 같은 종류의 복수 사건은 `action_key` 오름차순으로 처리해 결정적인 결과를 만든다.

```text
adjusted_price(d) = raw_price(d) × cumulative_price_factor(d)
adjusted_volume(d) = round_half_up(raw_volume(d) × cumulative_volume_factor(d))
adjusted_trading_value(d) = raw_trading_value(d)
```

계산 중간값은 `Decimal`로 처리하고 DB 저장 직전에 가격은 소수점 8자리, 계수는 소수점 16자리로 `ROUND_HALF_UP`한다. 수정가격을 당시 호가단위로 다시 반올림하지 않는다.

### 주식 수 변화 계수

`share_multiplier = 행사 후 주식 수 / 행사 전 주식 수`로 정의한다.

```text
event_price_factor = 1 / share_multiplier
event_volume_factor = share_multiplier
```

예를 들어 1주가 5주가 되는 액면분할은 `share_multiplier=5`, 과거 가격계수는 `0.2`, 거래량계수는 `5`다. 병합은 0과 1 사이의 배수를 사용한다. 비율의 방향을 출처 필드명으로 추정하지 않고 행사 전·후 주식 수 테스트 벡터로 확인한다.

### 현금배당·ETF 분배금 계수

`split_adjusted`에는 현금배당과 ETF 분배금을 포함하지 않는다. `total_return`은 배당락일 직전 확정 거래일 종가를 같은 날의 주식 수 변화까지 반영한 기준으로 환산한 `P`와 행사 후 1주 기준 세전 현금 `D`로 다음 계수를 계산한다.

```text
event_price_factor = (P - D) / P
event_volume_factor = 1
```

`P <= 0`, `D < 0` 또는 `P - D <= 0`이면 계산을 실패시킨다. 현금배당·분배금은 가격계수와 별개로 보유 현금흐름에 한 번만 반영한다.

같은 효력일에 액면분할과 현금배당이 함께 있으면 먼저 직전 종가를 행사 후 주식 단위로 환산하고, 공식 공시의 주당 현금 기준이 행사 전·후 중 어느 쪽인지 확인해 행사 후 1주 기준으로 정규화한다. 기준을 확인할 수 없으면 데이터셋 생성을 실패시킨다.

### 사용 경계

| 사용처 | 허용 데이터 | 금지 사항 |
|---|---|---|
| 주문 가격·체결 | 비수정 가격 | 수정주가로 주문가나 체결가 생성 금지 |
| 포트폴리오 수량·현금·손익 | 비수정 가격 + 기업행사 현금·수량 변동 | `total_return` 가격과 현금배당 동시 반영 금지 |
| 차트·기술지표 | 기본 `split_adjusted`, 명시 선택 시 `total_return` | 방식 표시 없는 혼합 금지 |
| 팩터·모멘텀 신호 | 데이터셋 ID가 고정된 수정주가 | 실행 시점 이후 정보가 포함된 데이터셋 금지 |
| 벤치마크 총수익 비교 | `total_return` | 실제 체결 가격 대체 금지 |

ETF 분배율 화면은 실제 분배금 현금흐름을 사용한다. `total_return` 수정가격에서 역산한 값을 분배금으로 저장하지 않는다.

## 시점과 미래정보 차단

데이터셋 생성기는 두 상한을 모두 적용한다.

1. `available_at <= knowledge_cutoff_at`인 기업행사 버전만 조회한다.
2. 해당 시점에 알 수 있었던 최신 버전을 선택한다.
3. `ex_date` 또는 계산에 사용하는 효력일이 `price_cutoff_date` 이하인 사건만 계수에 반영한다.
4. 이후 발표된 정정·취소는 기존 데이터셋을 수정하지 않고 새 입력 버전의 데이터셋을 만든다.
5. 백테스트 실행은 데이터셋 ID와 두 상한을 결과에 저장한다.

과거 공시를 오늘 처음 수집해도 공식 게시시각이 확인되면 `available_at`은 과거 게시시각이고 `received_at`은 오늘 수신시각이다. 공식 게시시각을 확인할 수 없으면 `available_at=received_at`으로 두어 과거에 알았다고 가정하지 않는다.

발표일만 있고 시각이 없는 사건은 그 발표일 정규장 종료 전 신호에서 사용하지 않는다. 초기 구현은 서울 기준 다음 거래일부터 사용 가능하게 처리하거나 더 보수적인 기준을 적용하되, 선택 규칙을 테스트와 `algorithm_version`에 고정한다.

## 생성과 버전 규칙

1. 외부 응답을 인증정보 없이 `operations.raw_api_response`에 먼저 append-only로 저장한다.
2. 기업행사 원본을 파싱하고 같은 사실이면 현재 버전을 재사용한다.
3. 날짜·비율·금액·상태가 바뀌면 이전 행을 대체 표시하고 새 버전을 만든다.
4. 계산 범위에 존재하는 모든 비수정 일봉이 확정됐는지 확인하고, 일봉이 없는 시장 거래일은 상장 기간 또는 공식 거래정지로 설명되는지 검사한다.
5. 당시 알 수 있었던 기업행사 버전을 선택하고 충돌·미지원·필수 조건 누락을 검사한다.
6. 입력 해시와 유일키로 기존 발행 데이터셋을 조회한다.
7. 새 데이터셋이면 `building`, 기업행사 매핑과 파생 일봉 전체를 원자적으로 생성한 뒤 `published`로 전환한다.
8. 한 행이라도 실패하면 파생 일봉을 부분 발행하지 않고 `failed`와 오류 코드를 남긴다.
9. 입력 사실이 정정되면 기존 발행본을 보존하고 새 데이터셋을 생성한다.

## 필수 조회 계약

저장소와 읽기 API는 다음 유스케이스를 지원해야 한다.

- 종목·기간·`knowledge_cutoff_at`으로 당시 유효한 기업행사 목록 조회
- 종목·기간의 최신 기업행사와 정정·취소 이력 조회
- 종목·방식·가격 기준일로 최신 `published` 데이터셋 조회
- 데이터셋 ID로 수정 일봉과 개별 가격·거래량 계수 조회
- 수정 일봉에서 비수정 일봉 버전과 반영 기업행사 버전까지 계보 조회
- 특정 기업행사 정정이 영향을 주는 데이터셋 목록 조회

응답에는 `method`, `price_cutoff_date`, `knowledge_cutoff_at`, `algorithm_version`, 두 입력 해시, 데이터셋 ID와 출처를 포함해야 한다. 원본·수정 여부를 불리언 하나만으로 표현하지 않는다.

## 데이터 품질과 실패 처리

- 기업행사 기간과 일봉 기간은 `XKRX` 시장 달력의 거래일로 검증한다.
- 배당락일·효력일이 휴장일이면 공식 출처 확인 없이 다음 거래일로 이동하지 않는다.
- 가격은 `low <= open, close <= high`, 거래량·거래대금은 음수가 아님을 원본과 파생 양쪽에서 검사한다.
- 가격계수와 거래량계수는 0보다 커야 한다.
- 기업행사 전후 급격한 가격 변화가 공식 조건과 설명되지 않으면 `conflict`로 처리한다.
- 누락된 일봉을 직전 값으로 채우지 않는다.
- 한 범위에서 현재 기업행사 버전이 둘 이상이면 무결성 오류다.
- 비수정 일봉이 미확정이거나 정정 진행 중이면 데이터셋을 발행하지 않는다.
- 출처 충돌, 계산 미지원, 입력 누락과 해시 불일치는 비밀정보 없는 오류 코드로 `operations.api_sync_status`에 기록한다.

## 검증 시나리오

구현은 최소 다음 시나리오를 자동화된 fixture와 PostgreSQL 통합 테스트로 검증해야 한다.

1. 1주가 5주가 되는 액면분할 전 가격은 0.2배, 거래량은 5배가 된다.
2. 액면병합은 반대 방향 계수를 적용하고 소수 거래량 반올림이 결정적이다.
3. 주식배당은 주식 수 변화로, 현금배당은 `total_return` 가격계수와 별도 현금흐름으로 처리된다.
4. ETF 분배금은 포트폴리오 현금과 총수익 가격에 동시에 중복 반영되지 않는다.
5. 발표 후 정정과 취소는 `knowledge_cutoff_at` 전후 데이터셋에서 서로 다른 버전을 선택한다.
6. 같은 원본 재처리는 기업행사 버전과 데이터셋 수를 늘리지 않는다.
7. 비수정 일봉 정정은 이전 데이터셋을 보존하고 새 입력 해시의 데이터셋을 만든다.
8. 권리락 조건 누락, 출처 충돌과 미지원 합병이 범위에 있으면 전체 발행이 차단된다.
9. KIS 제공 수정주가와 내부 `split_adjusted` 계열을 기업행사 전후 종목으로 대조하되 차이는 원본과 함께 기록한다.
10. 수정주가를 체결가로 전달하거나 미래 `available_at` 버전을 사용하려는 요청은 거부된다.

실제 환경 검증은 기업행사 이력이 분명한 국내주식 한 종목과 분배금 이력이 있는 국내 ETF 한 종목을 선택해 공식 공시, KIS 원주가, KIS 수정주가와 내부 계산을 날짜별로 대조한다. 실제 종목과 검증 기간은 구현 시점의 공식 자료 가용성을 확인한 뒤 QA 문서에 고정한다.

## 구현 완료 조건

- 기업행사 원본, 정규화 사실 버전과 수정주가 파생 데이터셋이 분리되어 있다.
- 비수정 일봉 정정과 기업행사 정정·취소가 과거 버전을 삭제하지 않는다.
- 같은 입력으로 동일한 데이터셋 ID 또는 동일한 입력 해시와 값을 재현한다.
- `split_adjusted`와 `total_return`의 용도와 계산식이 API에서 명시된다.
- 미래정보 누출과 ETF 분배금 중복 반영 테스트가 통과한다.
- 출처 충돌, 미지원 사건, 누락 일봉과 미확정 일봉은 부분 결과 없이 발행을 차단한다.
- 삼성전자 또는 검증용 국내주식과 국내 ETF의 공식 기업행사 전후 값을 육안 대조한다.

## 구현 순서

1. 완료: 비수정 `market_bar` 버전과 확정 상태 마이그레이션
2. 완료: 기업행사 도메인 타입, `market.corporate_action`와 버전 저장소
3. 완료(초기 종목 범위): DART 현금배당과 KODEX 분배금 수집. 액면분할·감자 등 나머지 유형은 해당 사건을 다루는 시점에 출처를 확장
4. 다음: 배당·분배락일 확정 경계와 수정계수 계산기·데이터셋·수정 일봉 저장소
5. point-in-time 조회와 읽기 API
6. fixture·PostgreSQL 통합 테스트와 실제 공식 자료 대조
7. 영향받는 API·운영·QA 문서 갱신
