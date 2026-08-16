# 시장 데이터 읽기 API

- 상태: 구현됨
- 구현일: 2026-08-14
- 기준 경로: `/api/market-data/instruments`
- 관련 정책: [시장 데이터 및 시점 정책](../spec/market-data-policy.md)

## 범위

2단계 첫 수직 슬라이스는 KIS 국내주식 시세 응답을 정규화해 종목정보, 최신 현재가, 비수정 일봉을 읽기 전용으로 제공한다. 시장 달력은 worker와 내부 저장소까지 구현했으며 아직 HTTP 읽기 API로 노출하지 않는다. 주문·계좌·실시간 스트림·분봉 API는 포함하지 않는다.

| 메서드 | 경로 | 응답 |
|---|---|---|
| `GET` | `/api/market-data/instruments/{symbol}` | 종목 기본정보와 상품 유형 |
| `GET` | `/api/market-data/instruments/{symbol}/quote` | 저장된 최신 현재가 |
| `GET` | `/api/market-data/instruments/{symbol}/daily-bars` | 거래일 오름차순 비수정 일봉 |

일봉 조회는 선택적인 `start_date`, `end_date` 쿼리를 `YYYY-MM-DD` 형식으로 받는다. 시작일이 종료일보다 늦으면 `422`, 종목이 없으면 `404`를 반환한다. 등록된 종목에 조회 구간 데이터가 없으면 빈 `bars`를 반환한다.

## 출처와 시각

- 모든 응답은 `source` 또는 개별 bar의 `source`로 `KIS`를 노출한다.
- 종목정보의 `source_as_of`는 종목 식별정보의 근거 응답을 수신한 한국 거래일이다. 실전환경은 종목 상세 응답, 모의환경은 일봉 요약 응답을 사용한다.
- 현재가 REST 응답에는 거래소 체결시각이 없으므로 `as_of`와 `received_at`은 서버가 응답을 수신한 UTC 시각이다.
- 일봉의 `trading_date`는 거래일, `received_at`은 서버 수신 UTC 시각이다.
- `adjusted=false`는 KIS 요청의 `FID_ORG_ADJ_PRC=1`, 즉 비수정 원본 가격임을 뜻한다.

가격과 금액은 내부에서 `Decimal`로 처리하며 JSON에서는 정밀도를 보존하는 문자열로 직렬화된다. 시각은 UTC ISO 8601 형식이다.

## 내부 저장 계약

외부 응답은 `operations.raw_api_response`에 append-only로 저장하고 정규화 데이터는 다음 고유키로 upsert한다.

- 종목: 국가·거래소·종목코드·상품유형·통화
- 최신 현재가: 종목·출처
- 일봉: 종목·주기·거래일·수정 여부·출처
- 수집 상태: 출처·작업·종목코드

현재가와 일봉은 원본 응답 식별자를 참조한다. 원본 응답에는 인증 헤더, 앱 키, 앱 시크릿과 계좌번호를 저장하지 않는다.

## 수집 작업

삼성전자 `005930`과 KODEX 200 `069500`을 기본 대상으로 수집한다.

```bash
cd backend
uv run python -m auto_stock_trading.worker.market_data \
  --start-date 2026-08-01 \
  --end-date 2026-08-14
```

Taskiq 등록 이름은 `collect_seed_market_data`다. 실행 서버에는 `AUTO_STOCK_KIS_APP_KEY`·`AUTO_STOCK_KIS_APP_SECRET` 직접 값 또는 대응하는 `_FILE` 경로가 필요하며 기본 환경은 모의투자다. 값은 문서·Git·브라우저 번들·로그에 기록하지 않는다. Docker 실행은 [KIS 모의환경 검증 런북](../operations/kis-paper-verification.md)을 따른다.

시장 달력 Taskiq 등록 이름은 `collect_krx_market_calendar`와 `confirm_today_market_calendar`다. 전자는 KIS 자격증명 없이 실행할 수 있고, 후자는 공식 KIS 국내휴장일조회가 실전 전용이므로 `AUTO_STOCK_KIS_ENVIRONMENT=live`와 분리된 실전 자격증명이 필요하다. KRX 원본 범위가 일부라도 빠지면 정규화 행을 저장하지 않고 실패 상태를 남긴다.

## 현재 제한

- KIS 모의환경은 종목 상세 `CTPF1002R`을 지원하지 않아 종목명·상품유형만 구성한다. 상장·상장폐지일과 영문명은 후속 종목 마스터 수집 전까지 제공하지 않는다.
- 모의투자 REST 요청은 현재 초당 1건 제한에 맞춰 최소 1.05초 간격으로 실행한다.
- 접근 토큰과 호출 간격은 Valkey에서 같은 자격증명의 worker가 공유한다.
- 현재가 `as_of`는 체결시각이 아니라 수신시각이다. 향후 실시간 스트림에서는 거래소 시각을 별도 저장한다.
- 수정주가, 분봉, 기업행사, 시장 달력 HTTP API와 자동 수집 스케줄러는 아직 구현하지 않았다. KRX 휴장일 화면은 단축장 시각을 주지 않으므로 임시 거래시간 공지 수집도 후속 범위다.
