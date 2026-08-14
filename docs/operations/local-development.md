# 로컬 개발과 실행

- 상태: 구현됨
- 작성일: 2026-08-11
- 관련 구조: [프로젝트 실행 구조](../architecture/project-structure.md)

## 필요 도구

- Python 3.14.6
- uv 0.12.3
- Bun 1.3.14
- Docker CLI와 Docker Compose
- macOS에서는 Colima 0.10.3

Python과 JavaScript 패키지는 lockfile로 고정한다. API 키나 계좌번호를 `.env.example`에 기록하지 않는다.

KIS 시장 데이터 수집은 서버 프로세스에서 직접 환경변수를 사용하거나 Docker secret 파일 경로를 사용한다. 값을 셸 이력, 문서, Git, 프론트엔드 환경변수와 로그에 남기지 않는다.

```text
AUTO_STOCK_KIS_ENVIRONMENT=paper
AUTO_STOCK_KIS_APP_KEY=<server-only>
AUTO_STOCK_KIS_APP_SECRET=<server-only>
AUTO_STOCK_KIS_APP_KEY_FILE=/run/secrets/kis_app_key
AUTO_STOCK_KIS_APP_SECRET_FILE=/run/secrets/kis_app_secret
```

직접 값과 파일 경로 중 하나만 사용한다. 직접 값이 있으면 파일보다 우선한다. `AUTO_STOCK_KIS_ENVIRONMENT`의 기본값은 `paper`이며 실제 주문 기능과는 연결되지 않는다.

실제 모의투자 키로 반복 수집을 검증할 때는 [KIS 모의환경 검증 런북](kis-paper-verification.md)을 따른다. `infra/compose.kis-paper.yaml`은 모의 환경을 강제하고 `.secrets/`의 키를 Docker secret으로 worker에만 마운트한다.

macOS에서는 Homebrew로 컨테이너와 개발 도구를 준비한다.

```bash
brew install colima docker docker-compose docker-buildx uv basedpyright
colima start --cpu 4 --memory 6 --disk 40 --vm-type vz --mount-type virtiofs
docker compose version
docker buildx version
```

Homebrew의 Docker 플러그인이 검색되지 않으면 `~/.docker/config.json`의 `cliPluginsExtraDirs`에 `/opt/homebrew/lib/docker/cli-plugins`를 추가한다. 기존 Docker 설정은 유지한다.

## 전체 구성 실행

저장소 루트에서 실행한다.

```bash
docker compose -f infra/compose.yaml up --build -d --wait --wait-timeout 300
docker compose -f infra/compose.yaml ps -a
```

서비스가 준비되면 다음 주소를 사용한다.

- 웹: `http://localhost:8080`
- API 생존 확인: `http://localhost:8000/api/health/live`
- API 준비성 확인: `http://localhost:8000/api/health/ready`

종료할 때 데이터 볼륨을 보존하려면 다음 명령만 사용한다.

```bash
docker compose -f infra/compose.yaml down
```

`down -v`는 PostgreSQL과 Valkey의 로컬 데이터를 삭제하므로 초기화가 목적일 때만 사용한다. Colima 자체를 종료하려면 모든 Compose 서비스를 내린 뒤 `colima stop`을 실행한다.

## 백엔드만 실행

```bash
cd backend
uv sync --frozen --all-groups
uv run alembic upgrade head
uv run uvicorn auto_stock_trading.api.app:app --reload
```

PostgreSQL이나 Valkey를 실행하지 않은 경우 `/live`는 `200`, `/ready`는 `503`과 `degraded`를 반환한다. 이는 의도된 장애 표시다.

작업자는 별도 터미널에서 실행한다.

```bash
cd backend
uv run taskiq worker auto_stock_trading.worker.market_data:broker
```

대표 주식·ETF 시장 데이터는 CLI로 한 번 수집할 수 있다.

```bash
cd backend
uv run python -m auto_stock_trading.worker.market_data \
  --start-date 2026-08-01 \
  --end-date 2026-08-14
```

현재 대상은 삼성전자 `005930`과 KODEX 200 `069500`이다. 자격증명이 없으면 비밀 값을 출력하지 않고 명시적인 설정 오류로 종료한다.

KIS 모의투자 REST API는 초당 1건 제한을 적용하므로 기본 클라이언트는 인증과 시세 요청 사이에 최소 1.05초 간격을 둔다. 토큰은 프로세스 안에서 재사용하지만 일회성 컨테이너를 다시 실행하면 새 프로세스가 토큰 발급을 시도한다. 즉시 재실행이 `/oauth2/tokenP` HTTP `403`으로 거절되면 반복 호출하지 않고 [모의환경 검증 런북](kis-paper-verification.md)의 재실행 절차를 따른다.

## 프론트엔드만 실행

```bash
cd frontend
bun install --frozen-lockfile
bun run dev
```

Vite는 `/api`를 `http://localhost:8000`으로 프록시한다. 개발 전용 컴포넌트 진단 UI 없이 제품 화면을 캡처하려면 다음과 같이 실행한다.

```bash
VITE_DISABLE_REACT_DEVTOOLS=1 bun run dev
```

## 품질 검사

```bash
cd backend
uv run ruff check src tests migrations
uv run ruff format --check src tests migrations
uv run basedpyright
uv run pytest
uv run alembic upgrade head

cd ../frontend
bun run lint
bun run typecheck
bun run test
bun run build
bun run e2e
```

브라우저 테스트 전에 API와 Vite 개발 서버가 각각 8000, 5173 포트에서 실행되어 있어야 한다.

Compose로 실행한 배포용 웹과 Caddy 프록시를 검증하려면 다음 명령을 사용한다.

```bash
cd frontend
PLAYWRIGHT_BASE_URL=http://127.0.0.1:8080 bun run e2e --headed
```
