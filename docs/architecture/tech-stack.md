# 상세 기술 스택

- 상태: 승인
- 승인일: 2026-08-11
- 관련 계획: [구현 로드맵](../plan/implementation-roadmap.md)
- 관련 명세: [제품 범위 및 요구사항](../spec/product-scope.md)

## 1. 아키텍처 기준

이 프로젝트는 Python 기반 모듈형 모놀리스로 구현한다. 하나의 백엔드 패키지가 도메인과 애플리케이션 로직을 공유하고, API·작업자·스케줄러·실시간 스트림을 별도 프로세스로 실행한다.

```text
Caddy
├─ /api/* -> FastAPI API
└─ /*     -> React 정적 파일

Backend package
├─ API process
├─ Taskiq worker
├─ Taskiq scheduler
└─ WebSocket stream worker

Infrastructure
├─ PostgreSQL
└─ Valkey
```

초기에는 Kubernetes, Kafka, TimescaleDB, Elasticsearch와 마이크로서비스를 도입하지 않는다. 실제 병목이나 운영 요구가 측정된 경우에만 추가한다.

관련 결정: [ADR-0001](../decisions/0001-modular-monolith.md)

## 2. 버전 기준선

2026-08-11 기준 안정 버전을 기준선으로 사용한다. 프로젝트 생성 시 각 패치 버전을 정확히 고정하고 lockfile을 커밋한다. 프리릴리스 버전은 사용하지 않는다.

| 계층 | 선택 | 기준 버전 |
|---|---|---|
| 백엔드 언어 | Python | 3.14.6 |
| API | FastAPI | 0.141.1 |
| 데이터 검증 | Pydantic | 2.13.4 |
| ORM | SQLAlchemy | 2.0.51 |
| 운영 DB | PostgreSQL | 18.4 |
| 작업 브로커 | Valkey | 9.1.1 |
| 작업 실행 | Taskiq | 0.12.4 |
| 외부 HTTP | httpx2 | 2.10.0 |
| 프론트엔드 | React | 19.2.8 |
| 프론트엔드 빌드 | Vite | 8.1.5 |
| TypeScript 도구 | Bun | 1.3.14 |

공식 기준:

- [Python 3.14.6](https://www.python.org/downloads/release/python-3146/)
- [PostgreSQL 버전 지원 정책](https://www.postgresql.org/support/versioning/)
- [React 최신 버전](https://react.dev/versions)
- [Vite 지원 버전](https://vite.dev/releases)

## 3. 백엔드

### 3.1 런타임과 웹 API

| 역할 | 기술 |
|---|---|
| 패키지 관리 | uv |
| 웹 API | FastAPI |
| 경계 데이터 파싱 | Pydantic v2 |
| 환경 설정 | pydantic-settings |
| 비동기 런타임 | AnyIO |
| 외부 HTTP | httpx2 |
| WebSocket | websockets |
| JSON 응답 | Pydantic 직렬화, 필요 시 orjson |
| 구조화 로그 | structlog |

증권사·공시 API의 JSON은 어댑터에서 Pydantic 모델로 한 번만 파싱한 뒤 내부 도메인 타입으로 변환한다. 외부 원본 `dict`를 애플리케이션 내부로 전달하지 않는다.

KIS 어댑터의 `httpx2` 클라이언트는 HTTP/2, 연결 풀, Brotli·Zstandard 응답, 연결·읽기·쓰기·풀 타임아웃과 전송 재시도를 사용한다. 모의투자 인증과 시세 요청은 초당 1건 제한보다 안전한 최소 1.05초 간격으로 직렬화하고, 로그에는 HTTP 메서드·경로·상태·소요시간만 남겨 인증 헤더와 요청 본문을 제외한다.

주요 의미 타입은 일반 문자열이나 숫자와 구분한다.

```text
InstrumentId
BrokerOrderId
ClientOrderId
AccountId
Money(amount, currency)
Quantity
ExchangeTimestamp
```

- 금액과 가격은 `float`가 아니라 `Decimal`을 사용한다.
- 수량은 정수 또는 상품에서 허용하는 명시적 단위를 사용한다.
- DB 시각은 UTC로 저장하고 거래소 시간대를 별도로 보존한다.
- 모의투자와 실전투자의 자격증명 및 환경 타입을 구분한다.

### 3.2 데이터베이스

| 역할 | 기술 |
|---|---|
| ORM | SQLAlchemy 2 async |
| PostgreSQL 드라이버 | asyncpg |
| 마이그레이션 | Alembic |
| 통합 테스트 | Testcontainers PostgreSQL |

PostgreSQL 18 컨테이너의 named volume은 메이저 버전별 하위 디렉터리 생성을 허용하도록 `/var/lib/postgresql`에 연결한다.

### 3.3 외부 API 어댑터

초기 어댑터는 다음 책임으로 나눈다.

```text
KisMarketDataAdapter
KisTradingAdapter
KisAccountAdapter
OpenDartAdapter
EtfReferenceDataAdapter
```

처음에는 한국투자증권만 구현한다. 다중 증권사를 예상한 거대한 공통 인터페이스를 만들지 않고 실제 사용 기능만 작은 포트로 정의한다.

2026-08-14 구현 범위의 `KisMarketDataAdapter`는 모의·실전 호스트를 설정으로 분리하고 접근 토큰을 프로세스 안에서 만료 전까지 메모리에 캐시한다. 현재가 `FHKST01010100`, 기간별 일봉 `FHKST03010100`을 지원하며 일봉은 비수정 원본 가격으로 요청한다. 실전 환경은 종목 상세 `CTPF1002R`도 호출하지만, 이 TR을 지원하지 않는 모의환경은 일봉 응답 요약에서 종목명과 최소 식별정보를 구성한다. 주기 수집 전에는 프로세스 간 24시간 토큰 재사용 저장소를 추가한다.

### 3.4 작업 처리와 스케줄링

| 역할 | 기술 |
|---|---|
| 비동기 작업 | Taskiq |
| 작업 브로커 | Valkey의 Redis 호환 프로토콜 |
| 주기 작업 | Taskiq scheduler 단일 인스턴스 |
| 장기 WebSocket | 별도 stream worker |

- 주문과 데이터 수집 작업에는 중복 방지 키를 둔다.
- 작업 큐는 주문 상태의 원본이 아니다.
- PostgreSQL 주문 상태를 기준으로 재시작과 메시지 유실을 복구한다.
- 모델 학습처럼 CPU 사용량이 큰 작업은 별도 프로세스로 격리한다.
- ListQueueBroker의 블로킹 대기가 유휴 상태에서도 유지되도록 Valkey 연결의 `socket_timeout`을 `None`으로 지정한다.
- 첫 등록 작업 `collect_seed_market_data`는 삼성전자와 KODEX 200의 종목정보·현재가·비수정 일봉을 수집한다. 스케줄러 자동 등록은 시장 달력 구현 후 추가한다.
- 기본 Compose는 자격증명 없이 실행한다. 실제 모의검증은 `compose.kis-paper.yaml`에서 `.secrets/` 파일을 Docker secret으로 worker에만 마운트하며 환경을 `paper`로 강제한다.

## 4. 데이터 저장과 분석

### 4.1 운영 데이터

PostgreSQL을 주문, 계좌, 시장 데이터, 전략, 감사 기록의 단일 영속 원본으로 사용한다.

```text
reference
├─ instrument
├─ market_calendar
├─ corporate_action
└─ etf_profile

market
├─ quote
├─ market_bar
├─ investor_flow
├─ etf_nav
├─ etf_constituent
└─ etf_distribution

fundamental
├─ company
├─ financial_statement
├─ financial_metric
└─ disclosure_event

strategy
├─ strategy_version
├─ feature_set_version
├─ backtest_run
├─ signal
└─ prediction

trading
├─ account_snapshot
├─ order
├─ execution
├─ position
├─ risk_decision
└─ reconciliation_run

operations
├─ raw_api_response
├─ api_sync_status
├─ job_run
├─ alert
└─ audit_event
```

`market_bar`는 데이터 규모가 확인된 뒤 종목 또는 시간 기준 파티셔닝을 적용한다. 초기부터 TimescaleDB에 의존하지 않는다.

2단계 첫 리비전은 `instrument`, 최신 `quote`, 일봉 `market_bar`, append-only `raw_api_response`, 수집 상태 `api_sync_status`를 생성했다. 나머지 표의 엔터티는 해당 단계에서 추가한다.

### 4.2 분석 및 학습 데이터

| 역할 | 기술 |
|---|---|
| 컬럼형 데이터 처리 | Polars Lazy API |
| 수치 계산 | NumPy |
| 연구용 로컬 SQL | DuckDB |
| 학습 데이터 포맷 | 버전이 지정된 Parquet |

```text
PostgreSQL
    ↓ 데이터셋 버전 생성
Parquet snapshot
    ↓
Polars / DuckDB
    ↓
백테스트·ML 학습
```

분석·학습 작업이 운영 PostgreSQL을 반복적으로 대량 조회하지 않도록 데이터셋 스냅샷을 만든다. 데이터셋에는 생성시각, 조회 범위, 원본 버전, 기업행사 처리 방식과 특징 버전을 기록한다.

관련 결정: [ADR-0003](../decisions/0003-data-architecture.md)

## 5. 보조지표와 백테스트

### 5.1 특징 계산

보조지표는 Polars 기반의 순수 계산 모듈로 구현한다.

```text
features/
├─ returns
├─ volatility
├─ moving_average
├─ rsi
├─ macd
├─ atr
├─ bollinger
├─ candlestick
├─ volume
└─ investor_flow
```

동일한 특징 계산 코드를 웹 차트, 백테스트, 모의매매와 실전매매에서 공유한다. 라이브러리별 계산 차이로 결과가 달라지지 않도록 실제 사용하는 지표만 고정된 공식과 테스트 데이터로 검증한다.

### 5.2 백테스트 엔진

운영 전략과 동일한 체결·위험 규칙을 사용하기 위해 필요한 주문 유형만 지원하는 결정적 이벤트 시뮬레이터를 내부에 구현한다.

```text
시장 데이터
→ 특징 계산
→ 전략 신호
→ 목표 포지션
→ 위험검사
→ 다음 거래 가능 시점 주문
→ 수수료·세금·슬리피지
→ 포트폴리오 평가
```

Backtrader나 VectorBT는 연구 비교에 사용할 수 있지만 운영 핵심 의존성으로 사용하지 않는다.

## 6. 머신러닝과 생성형 AI

### 6.1 머신러닝

| 단계 | 기술 |
|---|---|
| 기준 모델 | scikit-learn의 Logistic Regression, Ridge |
| 주력 표 모델 | LightGBM, XGBoost |
| 후속 시계열 모델 | PyTorch 기반 1D CNN/TCN, LSTM |
| 평가 | 시간 순서 기반 워크포워드 검증 |

첫 모델 입력과 목표:

```text
입력 X
= 최근 60거래일
× OHLCV
× 이동평균·RSI·MACD·ATR
× 캔들 특징
× 거래량·수급

정답 y
= 향후 10~20거래일 시장 대비 초과수익 또는 순위
```

모델 파일은 임의 코드를 실행할 수 있는 Python pickle 대신 LightGBM 텍스트, XGBoost JSON처럼 해당 모델의 안전한 네이티브 포맷을 사용한다. 모델 메타데이터와 평가 결과는 PostgreSQL에 저장한다.

초기에는 MLflow를 도입하지 않는다. 모델과 실험 수가 증가해 현재 저장 구조로 추적하기 어려워질 때 검토한다.

### 6.2 생성형 AI

| 역할 | 기술 |
|---|---|
| 구조화 출력 | Pydantic AI |
| 입력 | OpenDART 공시, 계산된 재무·전략 결과 |
| 출력 | 타입이 있는 이벤트·요약·근거 |

- 공시 접수번호, 발표일, 원문 근거를 필수로 저장한다.
- LLM 프로세스에 증권사 주문 자격증명을 제공하지 않는다.
- LLM 출력은 주문 API 입력으로 직접 연결하지 않는다.
- 모델 제공자는 설정으로 교체할 수 있도록 경계만 둔다.

관련 결정: [ADR-0004](../decisions/0004-ai-execution-separation.md)

## 7. 프론트엔드

### 7.1 기반 기술

| 역할 | 기술 |
|---|---|
| UI 런타임 | React 19.2 |
| 언어 | TypeScript strict |
| 빌드 | Vite 8.1 |
| 패키지 관리 | Bun |
| 라우팅 | TanStack Router 또는 구현 시점 검증 후 React Router |
| 서버 상태 | TanStack Query |
| 폼 | React Hook Form + Zod |
| 표 | TanStack Table |

서버 상태는 TanStack Query로 관리한다. Redux는 도입하지 않는다. 복잡한 클라이언트 전역 상태가 실제로 생긴 경우에만 Zustand를 검토한다.

### 7.2 UI와 차트

| 역할 | 기술 |
|---|---|
| 스타일 | Tailwind CSS 4 |
| 접근 가능한 primitive | Radix UI |
| 아이콘 | Lucide |
| 캔들·거래량 | Lightweight Charts |
| 재무·수급·순위·히트맵 | Apache ECharts |

UI 코드보다 `docs/` 아래 디자인 시스템 문서를 먼저 작성한다. 색상, 타이포그래피, 간격, 표, 차트, 상태와 반응형 규칙은 디자인 토큰으로 관리한다.

초기 라우트:

```text
/dashboard
/markets/:market
/stocks/:symbol
/etfs
/etfs/:symbol
/strategies
/backtests/:id
/paper-trading
/models
/operations
/settings
```

## 8. 인증과 보안

- 단일 사용자를 위한 서버 세션과 `HttpOnly`, `Secure`, `SameSite` 쿠키를 사용한다.
- 인증 토큰을 브라우저 `localStorage`에 저장하지 않는다.
- 증권사 App Secret과 접근 토큰은 서버에서만 관리한다.
- 모의투자와 실전투자 키를 완전히 분리한다.
- Caddy로 HTTPS를 종료한다.
- 초기 운영 접근은 Tailscale 또는 IP 제한을 우선한다.
- 로그에서 토큰과 계좌번호를 마스킹한다.
- 실전 자동매매 활성 상태는 서버 재시작 시 자동 해제한다.
- 비상정지 상태와 주문 한도는 PostgreSQL에 영속화한다.

## 9. 테스트와 품질 게이트

### 9.1 백엔드

- pytest
- pytest-anyio
- Hypothesis
- Testcontainers PostgreSQL
- 외부 API의 HTTP wire 수준 fake
- 한국투자증권 모의투자 E2E

### 9.2 프론트엔드

- Vitest
- Testing Library
- Playwright
- 실제 브라우저 기반 반응형·접근성·상호작용 QA

### 9.3 필수 시나리오

- 미래정보 누출 방지
- 수정주가와 거래정지 처리
- 중복 주문 차단
- 부분체결 후 잔고 조정
- 서버 재시작 후 주문 복구
- 손실 한도 초과 주문 거절
- 오래된 시세를 사용한 주문 차단
- 모의·실전 자격증명 혼용 방지
- 비상정지 후 신규 주문 차단

## 10. 개발 도구와 CI

### Python

- uv
- Ruff `select = ["ALL"]`
- basedpyright `typeCheckingMode = "all"`
- pytest

### TypeScript

- Bun
- Biome
- `tsc --noEmit`
- `strict`
- `noUncheckedIndexedAccess`
- `exactOptionalPropertyTypes`
- `verbatimModuleSyntax`

### CI 게이트

```text
Backend
├─ ruff check
├─ ruff format --check
├─ basedpyright
└─ pytest

Frontend
├─ biome check
├─ tsc --noEmit
├─ vitest
└─ vite build

E2E
├─ Docker Compose
├─ PostgreSQL migration
└─ Playwright
```

## 11. 배포

| 역할 | 기술 |
|---|---|
| 컨테이너 | Docker, Docker Compose |
| 리버스 프록시·TLS | Caddy |
| 호스트 | 항상 실행되는 Linux 서버 |
| 프로세스 복구 | Docker restart policy 또는 systemd |
| CI/CD | GitHub Actions |
| DB 백업 | `pg_dump` 기반 암호화 백업, 후속 원격 복제 |

첫 배포는 단일 서버를 기준으로 한다. 고가용성보다 주문 안전, 데이터 복구, 운영 단순성을 우선한다.

## 12. 저장소 구조

```text
auto-stock-trading/
├─ backend/
│  ├─ pyproject.toml
│  ├─ src/auto_stock_trading/
│  │  ├─ domain/
│  │  ├─ application/
│  │  ├─ adapters/
│  │  ├─ api/
│  │  ├─ worker/
│  │  └─ settings/
│  └─ tests/
├─ frontend/
│  ├─ package.json
│  ├─ src/
│  │  ├─ app/
│  │  ├─ features/
│  │  ├─ pages/
│  │  ├─ components/
│  │  └─ api/
│  └─ tests/
├─ infra/
│  ├─ compose.yaml
│  └─ caddy/
├─ docs/
└─ .github/workflows/
```

## 13. 재검토 조건

다음 조건이 발생하면 기술 스택을 ADR로 재검토한다.

- PostgreSQL 파티셔닝만으로 시계열 조회 성능을 충족하지 못한다.
- 단일 서버가 데이터 수집 또는 모델 학습 부하를 감당하지 못한다.
- 다중 사용자나 타인 계좌 연결이 제품 범위에 포함된다.
- 두 번째 증권사 주문 연동이 확정된다.
- 전략 수와 모델 수 증가로 단순 모델 레지스트리가 운영 불가능해진다.
- 실시간 분봉 또는 틱 전략이 핵심 요구사항이 된다.
