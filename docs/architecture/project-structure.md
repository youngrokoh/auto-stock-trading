# 프로젝트 실행 구조

- 상태: 구현됨
- 작성일: 2026-08-11
- 관련 결정: [ADR-0001](../decisions/0001-modular-monolith.md)
- 관련 기술: [상세 기술 스택](tech-stack.md)

## 실행 단위

1단계 구현은 하나의 Python 패키지를 공유하면서 API와 작업자를 독립 프로세스로 실행한다. 웹은 별도 정적 빌드이며 Caddy가 같은 출처에서 웹과 API를 제공한다.

```text
Caddy :8080
├─ /api/* -> FastAPI :8000
└─ /*     -> React 정적 파일

FastAPI API ─┬─ PostgreSQL
             └─ Valkey 상태 확인

Taskiq worker ── Valkey 작업 큐
```

현재 작업자에는 시장 수집이나 주문 작업을 등록하지 않았다. 2단계부터 실제 작업을 추가하되 API 프로세스와 같은 설정·도메인 패키지를 공유한다.

## 저장소 구조

```text
backend/
├─ src/auto_stock_trading/
│  ├─ adapters/       PostgreSQL·Valkey 등 외부 경계
│  ├─ api/            FastAPI 앱, 상태 엔드포인트, 응답 모델
│  ├─ application/    유스케이스와 상태 조합
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

프론트엔드는 빌드 시 비밀 환경변수를 사용하지 않는다. 개발 전용 React 진단 도구는 `import.meta.env.DEV`에서만 동적 로드하며 `VITE_DISABLE_REACT_DEVTOOLS=1`로 QA 캡처에서 비활성화한다.

## 데이터베이스 초기 상태

첫 Alembic 리비전 `20260811_0001`은 다음 PostgreSQL 스키마를 만든다.

- `reference`
- `market`
- `fundamental`
- `strategy`
- `trading`
- `operations`

업무 테이블은 해당 데이터 계약을 구현하는 단계에서 별도 마이그레이션으로 추가한다. Alembic 버전 테이블은 기본 `public` 스키마에 둔다.
