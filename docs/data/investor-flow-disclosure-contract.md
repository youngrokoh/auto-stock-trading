# 수급·공시 연결 데이터 계약

- 상태: 구현 기준
- 작성일: 2026-08-17
- 승인: 사용자가 2026-08-17에 당일 제외 버전 사실 수급 저장, DART 주요 유형별(정기·주요사항·지분·거래소) 공시 목록 수집, 최초 1년 범위와 이 계약을 구현 기준으로 승인
- 관련 정책: [시장 데이터 및 시점 정책](../spec/market-data-policy.md)
- 관련 계약: [재무 지표 정의 계약](financial-indicator-contract.md)
- 관련 로드맵: [구현 로드맵](../plan/implementation-roadmap.md) 4단계

## 목적

기업 분석 화면의 수급(투자자별 매매)과 공시 연결에 필요한 사실을 원본 근거와 함께 저장하고,
읽기 API가 출처·기준시각을 항상 노출하는 기반을 제공한다.

## 수급: KIS 투자자별 매매동향

### 출처와 실측 확인 (2026-08-17)

- 출처는 KIS `FHKST01010900`(`/uapi/domestic-stock/v1/quotations/inquire-investor`)이며 모의환경에서 응답을 확인했다.
- 일자별로 개인(`prsn_*`)·외국인(`frgn_*`)·기관(`orgn_*`)의 순매수 수량(`*_ntby_qty`)과
  순매수 대금(`*_ntby_tr_pbmn`), 매수·매도 총량, 종가를 반환한다.
- 실측 한계 (원본 보정 금지, 그대로 기록):
  1. 대금 단위는 백만원이다(수량 × 종가 대조로 확인). 원 단위로 환산하지 않고 그대로 저장한다.
  2. 세 주체 순매수 합계는 0이 아니다. 기타법인 등 다른 주체가 응답에 없다.
  3. 최근 약 30거래일만 반환한다. 과거 백필은 불가능하며 수집 시점부터 축적한다.
     최초 수집 이전 이력의 공백은 영구적이다.

### 저장 규칙

- `market.investor_flow`에 종목·거래일 단위 버전 사실로 저장한다.
  논리 키 = `instrument_id + trading_date + source`.
- 서울 기준 당일 행은 장중 잠정치일 수 있으므로 저장하지 않는다(당일 제외).
- 같은 값 재관측은 버전을 늘리지 않고 최신 관측 근거(`received_at`, 원본 참조)만 갱신한다.
  값이 바뀌면 이전 버전에 `superseded_at`을 기록하고 새 버전을 만든다. 과거 버전은 삭제하지
  않는다.
- 행은 개인·외국인·기관의 순매수 수량(주)과 순매수 대금(백만원), 출처, 수신 시각, 버전
  필드, 원본 응답 참조를 포함한다.
- 외부 응답은 인증정보 없이 `operations.raw_api_response`에 append-only 저장하고, 수집
  상태는 `operations.api_sync_status`에 기록한다(fail-closed).

### 필수 조회 계약

- `GET /api/market-data/instruments/{symbol}/investor-flows`: 현재 버전 행을 거래일
  내림차순으로 반환한다. 응답은 출처, 대금 단위(`million_krw`), 행별 `received_at`·`version`
  과 세 주체 합계가 0이 아닌 한계를 포함한 계약임을 전제한다. 미등록 종목은 404다.

## 공시 연결: DART 공시 목록

### 출처와 실측 확인 (2026-08-17)

- 출처는 OpenDART `GET /api/list.json`이며 항목은 `rcept_no`(접수번호), `report_nm`,
  `flr_nm`(제출인), `rcept_dt`(접수일), `rm`(비고)을 포함한다.
- 목록 응답에는 공시 유형 필드가 없으므로 유형별 파라미터(`pblntf_ty`)로 나눠 조회해 유형을
  태그한다. 수집 유형은 정기공시(`A`), 주요사항보고(`B`), 지분공시(`D`), 거래소공시(`I`)다.
- 목록 항목은 불변 사실이다. 정정 공시는 새 접수번호의 새 항목으로 나타나며 기존 항목은
  변하지 않는다.

### 저장 규칙

- `fundamental.disclosure`에 접수번호 단위 불변 사실로 저장한다.
  유일 키 = `instrument_id + rcept_no`. 버전 관리는 없다(항목 불변).
- 같은 접수번호 재수집은 아무것도 바꾸지 않는다(멱등). 문서 원문은 내려받지 않는다.
- 최초 수집 범위는 최근 1년이며, 이후 수집은 마지막 수집 구간과 겹치게 반복해도 멱등이다.
- 원본 목록 페이지는 인증정보(`crtfc_key`) 없이 append-only 저장한다.

### 필수 조회 계약

- `GET /api/fundamentals/instruments/{symbol}/disclosures?limit=`: 접수일 내림차순(같은 날은
  접수번호 내림차순)으로 반환한다. 항목은 `rcept_no`, `report_nm`, `flr_nm`, `rcept_dt`,
  유형(`A`·`B`·`D`·`I`), 출처(`DART`)를 포함한다. 화면은 접수번호로 DART 원문 뷰어
  (`https://dart.fss.or.kr/dsaf001/main.do?rcptNo=...`)에 연결한다. 미등록 종목은 404다.

## 화면 반영

- 기업 분석 D2(수급): 최근 거래일별 외국인·기관·개인 순매수를 단위와 기준시각, 한계와 함께
  표시한다. 값을 만들지 않으며 수집 전이면 빈 상태다.
- 기업 분석 D3(공시 연결): 최근 공시 목록을 유형·제출인·접수일과 DART 원문 링크로 표시한다.

## 검증 시나리오

1. 같은 수급 응답 재수집은 버전과 행 수를 늘리지 않고, 값 변경 관측은 이전 버전을 보존한
   새 버전이 된다.
2. 서울 기준 당일 행은 저장되지 않는다.
3. 같은 공시 목록 재수집은 행을 늘리지 않고, 새 접수번호만 추가된다.
4. 실제 KIS 모의환경·DART 키로 수집해 수급 수치와 공시 목록을 원문 화면과 대조한다.
5. 읽기 API의 정렬·단위·출처 노출과 미등록 종목 404를 검증한다.

## 구현 결과 (2026-08-17)

- Alembic `20260817_0011`이 두 테이블을 계약의 유일키·제약조건으로 생성한다.
- 수급: `KisInvestorFlowAdapter`가 서울 기준 당일 행을 제외하고 정규화하며,
  `PostgresInvestorFlowStore`가 버전 규칙(같은 값 멱등, 값 변경은 이력 보존 새 버전)으로
  저장한다. `python -m auto_stock_trading.worker.market_data --collect-investor-flows`로
  수집한다. 실수집으로 삼성전자·KODEX 200 각 30거래일(2026-07-03~08-14)을 적재했고 재수집은
  버전을 늘리지 않았으며, 값이 KIS 원본 응답과 일치했다(8/14 외국인 +4,913,433주·1,336,152
  백만원).
- 공시: `DartDisclosureAdapter`가 유형별(pblntf_ty A·B·D·I) 페이지를 수집하고
  `PostgresDisclosureStore`가 접수번호 유일 사실로 저장한다.
  `python -m auto_stock_trading.worker.fundamentals --collect-disclosures`로 최근 1년을
  수집한다. 실수집으로 삼성전자 2,837건(정기 4·주요사항 9·지분 2,758·거래소 66)을 적재했고
  재수집은 행을 늘리지 않았다.
- 읽기 API 두 개가 계약대로 제공되고, 기업 분석 D2(최근 8거래일 순매수 표)·D3(최근 공시
  목록과 DART 원문 링크) 카드가 실제 값으로 구현됐다.
  검증 기록은 [4단계 검증](../qa/phase-4-fundamentals-verification.md)에 있다.

## 구현 순서

1. 완료: `market.investor_flow`·`fundamental.disclosure` Alembic 마이그레이션
2. 완료: KIS 투자자별 매매 어댑터·수집 유스케이스·버전 저장소
3. 완료: DART 공시 목록 어댑터·수집 유스케이스·저장소
4. 완료: 읽기 API와 기업 분석 D2·D3 카드
5. 완료: fixture·PostgreSQL 통합 테스트와 실데이터 대조, 영향 문서 갱신
