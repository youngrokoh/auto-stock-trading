# 프로젝트 실행 구조

- 상태: 구현됨
- 작성일: 2026-08-11
- 관련 결정: [ADR-0001](../decisions/0001-modular-monolith.md)
- 관련 기술: [상세 기술 스택](tech-stack.md)

## 실행 단위

하나의 Python 패키지를 공유하면서 API와 작업자를 독립 프로세스로 실행한다. 웹은 별도 정적 빌드이며 Caddy가 같은 출처에서 웹과 API를 제공한다.

```text
Caddy :8080
├─ /api/* -> FastAPI :8000
└─ /*     -> React 정적 파일

FastAPI API ─┬─ PostgreSQL
             └─ Valkey 상태 확인

Taskiq worker ─┬─ Valkey 작업 큐
               ├─ KIS 시장 데이터·당일 달력 확인 어댑터
               ├─ KRX 공식 휴장일·임시 거래시간 공지 어댑터
               └─ PostgreSQL

Taskiq scheduler ── Valkey 작업 큐
```

작업자에는 삼성전자와 KODEX 200의 종목정보·현재가·비수정 일봉을 수집하는 `collect_seed_market_data`와 시장 달력 예약 작업을 등록했다. `market_calendar.py`는 KRX 연간 휴장일·임시 거래시간 합성과 실전 KIS 당일 확인 조립을, `market_calendar_schedule.py`는 이를 PostgreSQL 실행 claim으로 감싼 예약·수동 공통 경계와 Taskiq scheduler를 제공한다. 모의환경은 지원되지 않는 종목 상세·휴장일 TR을 호출하지 않는다. 주문 작업은 아직 등록하지 않았으며 API 프로세스와 설정·도메인 패키지를 공유한다.

시장 달력은 `domain/market_data/calendar_models.py`의 불변 도메인 타입, `calendar_logic.py`의 스케줄 판정, `adapters/exchanges/krx_market_calendar.py`의 연간 일정, `krx_trading_hours_notices.py`와 `krx_trading_hours_contracts.py`의 보도자료·PDF 경계, `krx_composite_calendar.py`의 합성, `adapters/brokers/kis_market_calendar.py`의 당일 확인, `application/market_calendar.py`의 범위 수집·확인, `adapters/database/market_calendar_*`의 행·매핑·SQL·저장소로 분리했다. 기존 호출자는 `domain/market_data/calendar.py` 호환 모듈을 통해 같은 공개 타입을 사용한다.

## 저장소 구조

```text
backend/
├─ src/auto_stock_trading/
│  ├─ adapters/       KIS·PostgreSQL·Valkey 등 외부 경계
│  ├─ api/            FastAPI 앱, 상태·시장 데이터 엔드포인트
│  ├─ application/    상태 조합과 시장 데이터 수집 유스케이스
│  ├─ domain/         시장 데이터 도메인 타입
│  ├─ settings/       서버 전용 환경 설정
│  └─ worker/         Taskiq 브로커와 작업자 진입점
├─ migrations/        Alembic 마이그레이션
└─ tests/             API·마이그레이션 테스트

frontend/
├─ src/
│  ├─ api/            브라우저 API 경계
│  ├─ components/     재사용 UI 프리미티브
│  ├─ lib/            Zod 응답 계약
│  └─ pages/          대시보드·프리미티브 쇼케이스
└─ tests/             단위·브라우저 테스트

infra/
├─ compose.yaml       PostgreSQL, Valkey, migration, API, worker, 선택적 scheduler, web
├─ compose.kis-paper.yaml  모의환경 강제와 worker 전용 Docker secret
├─ compose.kis-live-calendar.yaml  실전 읽기 전용 달력 확인과 worker 전용 secret
└─ Caddyfile          같은 출처 라우팅과 보안 헤더
```

## 설정과 비밀정보 경계

백엔드는 `AUTO_STOCK_` 접두사의 환경변수만 읽는다. 데이터베이스와 Valkey URL은 Pydantic `SecretStr`로 보관하며 상태 응답이나 로그에 포함하지 않는다.

| 환경변수 | 용도 | 브라우저 노출 |
|---|---|---|
| `AUTO_STOCK_ENVIRONMENT` | `development`, `test`, `production` 구분 | 환경 이름만 상태 응답에 포함 |
| `AUTO_STOCK_DATABASE_URL` | PostgreSQL 연결 | 금지 |
| `AUTO_STOCK_VALKEY_URL` | Valkey 및 Taskiq 연결 | 금지 |
| `AUTO_STOCK_CORS_ORIGINS` | 직접 개발 서버 허용 출처 | 서버 설정 전용 |
| `AUTO_STOCK_KIS_ENVIRONMENT` | `paper` 또는 `live` KIS 호스트 선택 | 금지 |
| `AUTO_STOCK_KIS_APP_KEY` | KIS 서버 앱 키 | 금지 |
| `AUTO_STOCK_KIS_APP_SECRET` | KIS 서버 앱 시크릿 | 금지 |
| `AUTO_STOCK_KIS_APP_KEY_FILE` | Docker secret 앱 키 파일 경로 | 금지 |
| `AUTO_STOCK_KIS_APP_SECRET_FILE` | Docker secret 앱 시크릿 파일 경로 | 금지 |
| `AUTO_STOCK_KRX_BASE_URL` | KRX 공식 사이트 기준 URL | 서버 설정 전용 |
| `AUTO_STOCK_KRX_OPEN_BASE_URL` | KRX 보도자료 사이트 기준 URL | 서버 설정 전용 |
| `AUTO_STOCK_KRX_ATTACHMENT_BASE_URL` | KRX 공식 첨부파일 기준 URL | 서버 설정 전용 |
| `AUTO_STOCK_KRX_CALENDAR_SCHEDULE_ENABLED` | KRX 달력 예약 등록 | 금지 |
| `AUTO_STOCK_KIS_CALENDAR_SCHEDULE_ENABLED` | 실전 KIS 당일 확인 예약 등록 | 금지 |

프론트엔드는 빌드 시 비밀 환경변수를 사용하지 않는다. 개발 전용 React 진단 도구는 `import.meta.env.DEV`에서만 동적 로드하며 `VITE_DISABLE_REACT_DEVTOOLS=1`로 QA 캡처에서 비활성화한다.

기본 `infra/compose.yaml`에는 KIS 키를 전달하지 않는다. 실제 모의검증에서만 `infra/compose.kis-paper.yaml`을 함께 적용해 Git과 Docker 빌드 컨텍스트에서 제외된 `.secrets/` 파일을 worker의 `/run/secrets`에 마운트한다. 이 override는 실전 환경 값을 받을 수 없도록 `paper`를 고정한다.

사용자가 2026-08-16 승인한 `infra/compose.kis-live-calendar.yaml`은 실전 읽기 전용 시장 달력 확인에만 사용한다. 실전 키 파일은 worker에만 마운트하고 scheduler에는 `live` 환경과 KIS 예약 활성화 플래그만 전달한다. 두 프로세스는 `unless-stopped` 재시작 정책을 사용하며 기본 Compose와 모의 override는 계속 KIS 자동 확인이 꺼진 상태다.

프로세스 간 KIS 토큰과 REST 호출 간격은 승인된 [ADR-0005](../decisions/0005-kis-token-and-rate-coordination.md)에 따라 Valkey에서 조정한다. 모의·실전 환경과 자격증명 지문마다 키 공간을 나누고, 토큰이 필요할 때 한 worker만 분산 잠금을 획득한다. Valkey를 사용할 수 없으면 개별 worker가 토큰 발급이나 KIS 요청으로 우회하지 않는다. 로컬 Valkey 호스트 포트는 `127.0.0.1`에만 바인딩한다.

## 데이터베이스 초기 상태

첫 Alembic 리비전 `20260811_0001`은 다음 PostgreSQL 스키마를 만든다.

- `reference`
- `market`
- `fundamental`
- `strategy`
- `trading`
- `operations`

두 번째 리비전 `20260814_0002`는 `reference.instrument`, `operations.raw_api_response`, `operations.api_sync_status`, `market.quote`, `market.market_bar`를 추가한다. Alembic 버전 테이블은 기본 `public` 스키마에 둔다.

세 번째 리비전 `20260816_0003`은 `reference.market_calendar`를 추가한다. 논리 세션별 사실 버전과 현재 행 하나를 보장하고, 정상 거래일·휴장일·단축장의 시각 조합과 확인 상태를 DB 제약조건으로 검증한다.

네 번째 리비전 `20260816_0004`는 `operations.scheduled_job_run`을 추가한다. 작업 이름과 논리 실행 키의 유일성, 상태·lease·소유자 토큰·시도 횟수로 중복 메시지와 worker 종료 후 회수를 제어한다.

다섯 번째 리비전 `20260816_0005`는 `market.market_bar`를 비수정 사실 버전 저장소로 전환한다. 기존 행은 버전 1의 검증 대기 사실로 보존하고, 버전 유일키와 현재 행 부분 유일 인덱스, 비수정·확정·유효기간 제약조건을 추가한다.
