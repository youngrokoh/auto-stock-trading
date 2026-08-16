# 2단계 시장 데이터 수직 슬라이스 검증

- 상태: 자동·로컬 통합·실제 KIS 모의환경·시장 달력 저장 검증 완료, 사용자 화면 대조 대기
- 기준일: 2026-08-16
- 대상: KIS 인증·종목정보·현재가·비수정 일봉·시장 달력·PostgreSQL·읽기 API
- 관련 API: [시장 데이터 읽기 API](../api/market-data-api.md)

## 검증 범위

| 영역 | 검증 방법 | 판정 |
|---|---|---|
| 프로세스 내부 KIS 토큰 캐시와 만료 후 갱신 | HTTP fake와 공식 형태 fixture | 통과 |
| 프로세스 간 토큰 단일 발급·만료 여유·잠금 복구 | 실제 Valkey와 두 독립 coordinator | 통과 |
| 프로세스 간 모의 REST 호출 간격 | 실제 Valkey 동시 예약 | 통과 |
| Valkey 장애 시 KIS 호출 차단 | 연결 실패와 issuer 미호출 검사 | 통과 |
| 주식·ETF 응답 정규화 | 삼성전자·KODEX 200 fixture | 통과 |
| 비수정 일봉 요청 | `FID_ORG_ADJ_PRC=1` 요청 검사 | 통과 |
| 한국 시장 날짜 경계 | UTC 수신시각을 `Asia/Seoul` 날짜로 변환 | 통과 |
| 실패 기록과 재실행 | PostgreSQL 통합 테스트 | 통과 |
| 반복 수집 멱등성 | 정규화 행 수와 원본 append-only 행 수 검사 | 통과 |
| 기존 실제 데이터와 테스트 격리 | 대상 fixture를 테스트 트랜잭션에서 초기화한 뒤 롤백 | 통과 |
| 읽기 전용 API | FastAPI 계약 테스트와 실제 HTTP 호출 | 통과 |
| 비밀정보 경계 | 오류 문자열과 로그 필드 검사 | 통과 |
| 모의전용 Docker secret 전달 | 파일 기반 키 로딩과 `paper` 강제 Compose override | 통과 |
| 모의투자 호출 제한 | 기본 요청 간격 1.05초 검사 | 통과 |
| 모의환경 미지원 종목 상세 TR 우회 | 일봉 요약으로 최소 종목정보 구성 | 통과 |
| 실제 KIS 모의환경 | 로컬 모의 키 반복 수집, 공유 토큰 재사용과 DB·API 확인 | 통과 |
| 시장 달력 스키마와 불변조건 | Alembic offline SQL과 PostgreSQL 적용 | 통과 |
| 정상·휴장·단축장과 fail-closed 판정 | 도메인 테스트 | 통과 |
| 동일 사실 재수신과 정정 버전 보존 | PostgreSQL 통합 테스트 | 통과 |
| KRX 우선순위와 KIS 충돌 차단·오류 기록 | PostgreSQL 통합 테스트 | 통과 |
| 현재 범위와 다음·이전 거래일 조회 | PostgreSQL 통합 테스트 | 통과 |
| KIS 앱 화면 값 대조 | 사용자의 모의투자 화면과 육안 비교 | 대기 |

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
- pytest: 24건 통과
- Alembic `upgrade head`: 통과
- Compose 계약 검사: 통과
- Docker Compose 현재 이미지 빌드와 기동: PostgreSQL·Valkey·API·worker 정상, migration 종료 코드 0
- 모의전용 worker 이미지 빌드와 Docker secret one-off 실행: 통과
- 문서 생성·링크·변경 매핑 검사: 통과

2026-08-16 시장 달력 저장 계층 실행 결과:

- Ruff 검사·포맷: 통과
- basedpyright: 오류 0건, 경고 0건
- pytest: 37건 통과
- Alembic `20260816_0003` PostgreSQL 적용: 통과
- 시장 달력 PostgreSQL 통합 시나리오: 3건 통과
- Python sdist·wheel 빌드: 통과
- Compose·문서 계약 검사: 통과

저장소 통합 테스트는 현재 로컬 Compose의 PostgreSQL 18에 실제 리비전을 적용한 뒤 테스트 트랜잭션을 롤백하는 기존 프로젝트 방식을 따른다. 기술 스택에 정의된 Testcontainers 기반 테스트별 격리는 아직 도입하지 않았다.

2026-08-14 모의검증 준비 런타임 관찰:

- 실제 키 대신 저장소의 가짜 fixture 파일 두 개를 Compose secret 원본으로 지정했다.
- `compose.kis-paper.yaml` one-off worker 안에서 환경이 `paper`로 고정됨을 확인했다.
- 직접 자격증명 환경변수는 `None`인 상태에서 `/run/secrets` 파일로 두 값을 읽었다.
- 키 내용은 명령행 인자, Compose 환경과 출력에 노출하지 않았다.
- 이 관찰은 비밀정보 전달 경로에 대한 증거이며 실제 KIS 외부 호출 성공을 뜻하지 않는다.

## 실제 KIS 모의환경 관찰

사용자는 2026-08-14에 모의투자와 실전투자 키 발급을 완료했고 모의 키만 로컬 `.secrets/`에 저장했다. 파일 존재·비어 있지 않음·권한 `0600`만 관찰했으며 애플리케이션이 값을 로드해 인증에 사용하되 키 자체는 출력하거나 기록하지 않았다. 실전 키는 검증 경로에 연결하지 않았다.

첫 실제 호출에서 인증은 성공했지만 종목 상세 `CTPF1002R`이 HTTP `500`, `EGW02006`, `모의투자 TR 이 아닙니다.`를 반환했다. 같은 토큰으로 현재가 `FHKST01010100`과 일봉 `FHKST03010100`은 모두 `200`, `MCA00000`이었다. 공식 샘플과 요청 계약을 대조한 결과 요청 오류가 아니라 모의환경 미지원 TR로 확정했고, 실패 테스트를 먼저 추가한 뒤 모의환경에서는 일봉 요약으로 최소 종목정보를 구성하도록 수정했다.

수정한 worker 이미지의 `2026-08-01`부터 `2026-08-14`까지 첫 수집 결과:

| 데이터 | 행 수 |
|---|---:|
| 종목 | 2 |
| 최신 현재가 | 2 |
| 비수정 일봉 | 20 |
| 원본 응답 | 4 |
| 성공 상태 | 2 |

삼성전자와 KODEX 200은 각각 10개 거래일, `2026-08-03`부터 `2026-08-14`까지 저장됐다. 같은 범위의 두 번째 성공 수집 후 종목 2, 최신 현재가 2, 일봉 20, 성공 상태 2는 유지됐고 원본 응답만 8로 증가했다.

독립 컨테이너를 즉시 재실행했을 때 새 프로세스의 토큰 발급이 HTTP `403`으로 한 번 거절됐다. 추가 호출을 반복하지 않고 보호 구간 이후 한 번 재실행해 성공했다. 이 관찰을 근거로 ADR-0005를 승인하고 Valkey 기반 프로세스 간 토큰 재사용과 호출 게이트를 구현했다.

구현 후 첫 독립 worker가 실제 KIS 수집을 완료하고 Valkey에 공유 토큰을 저장했다. 다음 독립 worker는 `KIS shared access token reused`를 기록했으며 `/oauth2/tokenP` 없이 현재가·일봉 GET 4건을 모두 `200`으로 완료했다. 두 번 추가 수집 후 종목 2, 최신 현재가 2, 일봉 20, 성공 상태 2는 유지됐고 누적 원본 응답은 16건이었다. 공유 토큰 항목은 1개, 원본 payload의 인증 필드는 0건, Valkey 호스트 포트는 `127.0.0.1:6379`였다.

실제 FastAPI `:8000` 관찰:

- 종목정보: `200`, `symbol=005930`, `name=삼성전자`, `product_type=stock`, `source=KIS`
- 현재가: `200`, KRW Decimal 문자열, UTC `as_of`·`received_at`, `source=KIS`
- 일봉: `200`, 10건, `2026-08-03`부터 `2026-08-14`, 모두 `adjusted=false`, `source=KIS`
- 원본 payload 최상위 인증 필드 `access_token`, `appkey`, `appsecret`: 0건

## 남은 사용자 확인

KIS 모의투자 앱 또는 웹 화면에서 삼성전자와 KODEX 200의 값과 마지막 거래일을 육안 대조한다. 기술 검증과 원본 보안 검증은 완료됐으며 화면 대조 결과에는 시세 전문이나 키를 기록하지 않는다.
