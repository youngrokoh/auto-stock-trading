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
uv run taskiq worker auto_stock_trading.worker.broker:broker
```

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
