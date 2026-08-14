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
               ├─ KIS 시장 데이터 어댑터
               └─ PostgreSQL
```

작업자에는 삼성전자와 KODEX 200의 종목정보·현재가·비수정 일봉을 수집하는 `collect_seed_market_data` 작업을 등록했다. 모의환경은 지원되지 않는 종목 상세 TR을 호출하지 않고 일봉 요약에서 최소 종목정보를 구성한다. 주문 작업은 아직 등록하지 않았으며 API 프로세스와 설정·도메인 패키지를 공유한다.

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
├─ compose.yaml       PostgreSQL, Valkey, migration, API, worker, web
├─ compose.kis-paper.yaml  모의환경 강제와 worker 전용 Docker secret
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

프론트엔드는 빌드 시 비밀 환경변수를 사용하지 않는다. 개발 전용 React 진단 도구는 `import.meta.env.DEV`에서만 동적 로드하며 `VITE_DISABLE_REACT_DEVTOOLS=1`로 QA 캡처에서 비활성화한다.

기본 `infra/compose.yaml`에는 KIS 키를 전달하지 않는다. 실제 모의검증에서만 `infra/compose.kis-paper.yaml`을 함께 적용해 Git과 Docker 빌드 컨텍스트에서 제외된 `.secrets/` 파일을 worker의 `/run/secrets`에 마운트한다. 이 override는 실전 환경 값을 받을 수 없도록 `paper`를 고정한다.

## 데이터베이스 초기 상태

첫 Alembic 리비전 `20260811_0001`은 다음 PostgreSQL 스키마를 만든다.

- `reference`
- `market`
- `fundamental`
- `strategy`
- `trading`
- `operations`

두 번째 리비전 `20260814_0002`는 `reference.instrument`, `operations.raw_api_response`, `operations.api_sync_status`, `market.quote`, `market.market_bar`를 추가한다. Alembic 버전 테이블은 기본 `public` 스키마에 둔다.
