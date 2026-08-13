# 2단계 시장 데이터 수직 슬라이스 검증

- 상태: 자동·로컬 통합 검증 완료, KIS 모의환경 검증 대기
- 기준일: 2026-08-14
- 대상: KIS 인증·종목정보·현재가·비수정 일봉·PostgreSQL·읽기 API
- 관련 API: [시장 데이터 읽기 API](../api/market-data-api.md)

## 검증 범위

| 영역 | 검증 방법 | 판정 |
|---|---|---|
| KIS 토큰 캐시와 만료 후 갱신 | HTTP fake와 공식 형태 fixture | 통과 |
| 주식·ETF 응답 정규화 | 삼성전자·KODEX 200 fixture | 통과 |
| 비수정 일봉 요청 | `FID_ORG_ADJ_PRC=1` 요청 검사 | 통과 |
| 한국 시장 날짜 경계 | UTC 수신시각을 `Asia/Seoul` 날짜로 변환 | 통과 |
| 실패 기록과 재실행 | PostgreSQL 통합 테스트 | 통과 |
| 반복 수집 멱등성 | 정규화 행 수와 원본 append-only 행 수 검사 | 통과 |
| 읽기 전용 API | FastAPI 계약 테스트와 실제 HTTP 호출 | 통과 |
| 비밀정보 경계 | 오류 문자열과 로그 필드 검사 | 통과 |
| 실제 KIS 모의환경 | 서버 자격증명으로 수집 작업 실행 | 자격증명 필요 |

## 테스트 데이터 근거

fixture는 한국투자증권 공식 `open-trading-api` 저장소의 2026-08-14 기준 커밋 `b093e42ba32d1df5f5ddad7a71cb715cbc800832`에 있는 인증, 국내주식 종목정보, 현재가, 기간별 일봉 샘플의 필드와 TR ID를 기준으로 작성했다.

- 인증: `/oauth2/tokenP`
- 종목정보: `CTPF1002R`
- 현재가: `FHKST01010100`
- 기간별 일봉: `FHKST03010100`

fixture 값은 계약 테스트용 예시이며 실제 현재 시세로 해석하지 않는다.

## 자동 검증 명령

```bash
cd backend
uv run ruff check src tests migrations
uv run ruff format --check src tests migrations
uv run basedpyright
uv run pytest
uv run alembic upgrade head

cd ..
bash tests/infra-compose-test.sh
python3 scripts/docs_guard.py check
```

2026-08-14 실행 결과:

- Ruff 검사·포맷: 통과
- basedpyright: 오류 0건, 경고 0건
- pytest: 14건 통과
- Alembic `upgrade head`: 통과
- Compose 계약 검사: 통과
- Docker Compose 현재 이미지 빌드와 기동: PostgreSQL·Valkey·API·worker 정상, migration 종료 코드 0
- 문서 생성·링크·변경 매핑 검사: 통과

## 실제 HTTP 관찰

현재 코드로 빌드한 Compose API에서 `/api/health/ready`는 PostgreSQL·Valkey를 `ok`로 보고하며 `200`을 반환했다. 아직 실제 KIS 데이터가 없는 개발 DB의 `/api/market-data/instruments/005930`은 명시적인 `404 Instrument not found`를 반환했다.

같은 FastAPI 앱을 공식 형태 fixture reader로 실제 8010 포트에 실행해 `curl`로 세 엔드포인트를 확인했다.

- 종목정보: `200`, `product_type=stock`, `source=KIS`, `source_as_of=2026-08-14`
- 현재가: `200`, Decimal 문자열, UTC `as_of`·`received_at`
- 일봉: `200`, 날짜 범위 필터 적용, `adjusted=false`, `source=KIS`

이 관찰은 애플리케이션 라우팅과 직렬화에 대한 런타임 증거이며 실제 KIS 외부 전송 성공을 뜻하지 않는다.

## 남은 실환경 검증

현재 로컬 환경에는 KIS 앱 키와 앱 시크릿이 없어 외부 모의투자 호출은 수행할 수 없다. 자격증명이 서버 환경변수로 제공되면 다음을 확인한다.

1. `collect_seed_market_data`가 두 종목을 수집한다.
2. 같은 날짜 범위를 두 번 실행해 정규화 행 수가 증가하지 않는다.
3. 원본 응답은 실행마다 추가되고 인증정보를 포함하지 않는다.
4. API 값과 KIS 모의투자 화면의 출처·수신시각·거래일을 대조한다.
