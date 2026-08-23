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

macOS에서는 LightGBM이 OpenMP 런타임을 요구한다. 없으면 `lib_lightgbm.dylib` 로드가 실패해 ML 학습 경로만 죽는다(나머지 경로는 영향 없다).

```bash
brew install libomp
```

작업자는 별도 터미널에서 실행한다.

```bash
cd backend
uv run taskiq worker auto_stock_trading.worker.market_data:broker
```

예약 작업 메시지도 처리하려면 worker에 예약 모듈을 함께 불러온다.

```bash
cd backend
uv run taskiq worker \
  auto_stock_trading.worker.market_data:broker \
  auto_stock_trading.worker.market_calendar_schedule
```

기본 Compose는 scheduler를 시작하지 않는다. KRX 자동 수집을 명시적으로 활성화할 때만 다음 프로필을 사용한다.

```bash
docker compose -f infra/compose.yaml \
  --profile calendar-scheduler up --build -d --wait --wait-timeout 300
```

이 KRX 전용 실행의 단일 scheduler는 `Asia/Seoul` 기준 KRX 예약만 발행하고 KIS 자격증명을 받지 않는다. 중복 메시지는 worker의 PostgreSQL claim이 차단한다. 아래 실전 달력 전용 override를 함께 적용하지 않으면 KIS 예약은 등록되지 않으며 기본 Compose 파일에는 실전 비밀정보를 연결하지 않는다.

실전 읽기 전용 KIS 당일 확인을 함께 자동 실행하려면 사용자가 승인한 전용 override를 추가한다.

```bash
docker compose \
  -f infra/compose.yaml \
  -f infra/compose.kis-live-calendar.yaml \
  --profile calendar-scheduler \
  up --build -d --wait --wait-timeout 300 worker calendar-scheduler
```

`compose.kis-live-calendar.yaml`은 `.secrets/kis-live-app-key`와 `.secrets/kis-live-app-secret`을 worker에만 Docker secret으로 마운트한다. scheduler에는 자격증명을 전달하지 않고 `live` 환경과 KRX·KIS 예약 플래그만 설정한다. 두 프로세스는 명시적으로 중지하기 전까지 Docker 재시작 후 복구되도록 `restart: unless-stopped`를 사용한다. 이 override는 주문 작업을 등록하거나 활성화하지 않는다. 자동 확인을 중지하려면 같은 두 Compose 파일과 프로필로 `stop calendar-scheduler worker`를 실행한다.

대표 주식·ETF 시장 데이터는 CLI로 한 번 수집할 수 있다.

```bash
cd backend
uv run python -m auto_stock_trading.worker.market_data \
  --start-date 2026-08-01 \
  --end-date 2026-08-14
```

현재 대상은 삼성전자 `005930`과 KODEX 200 `069500`이다. 자격증명이 없으면 비밀 값을 출력하지 않고 명시적인 설정 오류로 종료한다.

수집된 일봉은 정규장 종료 후 재조회로 확정한다.

```bash
cd backend
uv run python -m auto_stock_trading.worker.market_data \
  --confirm-daily-bars \
  --start-date 2026-07-01 \
  --end-date 2026-08-14
```

서울 기준 해당 거래일 15:40 이후에 저장된 관측과 재조회 응답이 정확히 일치한 일봉만 `confirmed`가 된다. 장중에 처음 수집된 일봉은 이 명령을 한 번 더 실행해야 확정되고, 재조회 값이 다르면 확정 대신 새 `pending` 정정 버전이 남는다. 수정주가 데이터셋 생성(`--build-adjusted`)은 범위의 모든 일봉이 확정된 뒤에만 발행되며, 재현 가능한 발행이 필요하면 `--knowledge-cutoff`로 지식 기준시각을 고정한다.

KRX 공식 연간 일정은 자격증명 없이 수집한다.

```bash
cd backend
uv run python -m auto_stock_trading.worker.market_data --calendar-year 2026
```

이 명령은 KRX 공식 연간 휴장일 원본과 조회 기간에 영향을 주는 보도자료의 임시 거래시간 PDF를 수집한다. 수능일·연초 개장일 공지가 있으면 주식·ETF 정규장 변경을 연간 일정에 합성한 뒤 해당 연도의 모든 날짜를 한 트랜잭션에서 적재한다. PDF 원문은 공지 번호·첨부 메타데이터와 함께 원본 근거로 저장하고, 알 수 없는 임시 공지 형식이나 기준시간 불일치는 추정하지 않고 전체 수집을 실패시킨다. 세션은 KIS 당일 확인 전까지 `pending`이다.

```bash
cd backend
AUTO_STOCK_KIS_ENVIRONMENT=live \
AUTO_STOCK_KIS_APP_KEY_FILE=../.secrets/kis-live-app-key \
AUTO_STOCK_KIS_APP_SECRET_FILE=../.secrets/kis-live-app-secret \
uv run python -m auto_stock_trading.worker.market_data --confirm-calendar-today
```

KIS 국내휴장일조회 `CTCA0903R`은 실전 전용이며 공식 예제가 1일 1회 호출을 권고한다. 위 두 파일은 `.secrets/` 아래에서 각각 권한 `0600`으로 보관하고 기존 모의 키와 분리한다. 모의환경에서는 외부 호출 없이 설정 오류로 끝나며 시장 달력은 `pending`을 유지한다. 실전 키를 채팅, 명령행 직접 값, Git 또는 문서에 기록하지 않는다. 2026-08-16 수동 검증은 주문·계좌 API를 사용하지 않고 이 읽기 전용 TR만 호출했다.

OpenDART 현금배당 공시는 사용자가 [OpenDART](https://opendart.fss.or.kr)에서 발급한 API 키로 수집한다.

```bash
cd backend
AUTO_STOCK_DART_API_KEY_FILE=../.secrets/dart-api-key \
uv run python -m auto_stock_trading.worker.corporate_actions \
  --symbol 005930 \
  --corp-code 00126380 \
  --start-date 2026-01-01 \
  --end-date 2026-08-16
```

키 파일은 `.secrets/` 아래 권한 `0600`으로 두고 Git·문서·명령행 직접 값으로 기록하지 않는다. 이 명령은 공시검색 목록과 `현금ㆍ현물배당결정` 원본 문서를 append-only로 보존한 뒤 배당 사실 버전을 저장한다. 같은 범위를 반복 실행해도 새 사실 버전이 생기지 않으며, 지원하지 않는 서식·접두어·배당종류를 만나면 추정 없이 전체 수집이 실패한다. 키가 없으면 비밀 값 노출 없이 설정 오류로 종료한다.

KODEX 200 ETF 분배금은 운용사 공식 데이터에서 인증 없이 수집한다.

```bash
cd backend
uv run python -m auto_stock_trading.worker.corporate_actions \
  --etf-distributions \
  --start-date 2024-01-01 \
  --end-date 2026-08-17
```

기본 대상은 KODEX 200 `069500`(펀드 `2ETF01`)이며 `--symbol`과 `--fund-id`로 바꿀 수 있다. 응답 원본은 append-only로 보존되고, 지급기준일·세전 주당분배금·실지급일이 지급 완료(`confirmed`) 사실 버전으로 저장된다. 같은 범위를 반복 실행해도 새 사실 버전이 생기지 않는다.

수집된 배당·분배금의 배당락일은 검증된 시장 달력으로 확정하고, 수정주가 데이터셋은 확정된 일봉에서 생성한다.

```bash
cd backend
uv run python -m auto_stock_trading.worker.corporate_actions --confirm-ex-dates
uv run python -m auto_stock_trading.worker.corporate_actions \
  --build-adjusted total_return \
  --symbol 069500 \
  --start-date 2026-08-03 \
  --end-date 2026-08-14
```

락일 확정은 달력이 없는 기간을 건너뛰고 `pending`으로 남긴다. 데이터셋 생성은 범위의 모든 거래일 일봉이 `confirmed`여야 하며, 조건을 만족하지 못하면 `market.adjustment_dataset`에 `failed`와 오류 코드만 남기고 발행하지 않는다.

발행된 데이터셋과 기업행사는 API 서버에서 읽기 전용으로 조회한다.

```bash
curl "http://localhost:8000/api/market-data/instruments/069500/corporate-actions?include_history=true"
curl "http://localhost:8000/api/market-data/instruments/069500/adjusted-daily-bars?method=total_return"
curl "http://localhost:8000/api/market-data/adjusted-datasets/{dataset_id}"
curl "http://localhost:8000/api/market-data/corporate-actions/{action_key}/adjusted-datasets"
```

기업행사 조회는 `knowledge_cutoff_at`(시간대 오프셋 필수)으로 당시 알 수 있었던 버전을 선택하는 point-in-time 조회를 지원한다. 자세한 응답 계약은 [시장 데이터 읽기 API](../api/market-data-api.md)를 따른다.

## 재무제표 수집

승인된 [재무제표 데이터 계약](../data/financial-statement-data-contract.md)에 따라 OpenDART 전체 재무제표(최근 5개년 사업보고서 + 당해 분·반기 × 연결·개별)를 수집한다.

```bash
cd backend
AUTO_STOCK_DART_API_KEY_FILE=../.secrets/dart-api-key \
  uv run python -m auto_stock_trading.worker.fundamentals
curl "http://localhost:8000/api/fundamentals/instruments/005930/financial-reports"
```

미제출 기간은 건너뛰고, 같은 접수번호 재수집은 버전을 늘리지 않으며 정정 공시는 이전 버전을 보존한 새 버전이 된다.

## 분봉 수집

검증된 시장 달력이 결정한 최신 거래 세션의 1분봉을 수집한다. 정규장 종료 후 같은 명령을 두 번 실행하면 두 관측이 일치한 분봉이 `confirmed`가 된다.

```bash
cd backend
uv run python -m auto_stock_trading.worker.market_data --collect-minute-bars
uv run python -m auto_stock_trading.worker.market_data --collect-minute-bars   # 재수집으로 확정
```

ETF 마스터(비인증 KIS 공식 파일)와 전량 NAV 스냅샷은 아래로 수집한다. NAV 전량 수집은
모의환경 호출 간격 때문에 약 21분이 걸리고 개별 종목 실패는 기록 후 계속된다.

```bash
cd backend
uv run python -m auto_stock_trading.worker.market_data --collect-etf-master
uv run python -m auto_stock_trading.worker.market_data --collect-etf-nav   # KIS 모의 키 필요
```

투자자별 수급(개인·외국인·기관 순매수)은 같은 자격증명으로 수집한다. 서울 기준 당일 행은
저장하지 않고, KIS가 최근 약 30거래일만 반환하므로 거래일마다 수집해 축적한다.

```bash
cd backend
uv run python -m auto_stock_trading.worker.market_data --collect-investor-flows
# 유니버스 200종목 스윕(종목당 요청 1회, 약 3.5분). 개별 실패는 종목코드와 함께 보고된다
uv run python -m auto_stock_trading.worker.market_data --collect-universe-investor-flows
curl "http://localhost:8000/api/market-data/instruments/069500/minute-bars?trading_date=2026-08-14"
```

수급 축적을 자동화하려면 예약 override를 겹친다. 기본 Compose는 꺼져 있다.

```bash
docker compose -f infra/compose.yaml \
  -f infra/compose.investor-flow-schedule.yaml \
  --profile investor-flow-scheduler up -d
```

worker에만 모의 자격증명을 Docker secret으로 준다. 스케줄러는 자격증명을 받지 않고 시각만 안다.
예약은 07:10·08:10·09:10 KST에 시도하고 성공하면 PostgreSQL 실행 claim이 나머지를 건너뛴다.
휴장일 실행은 같은 30거래일을 다시 관측하는 멱등 동작이라 놓친 날이 자동으로 복구된다. 중지는 같은
두 Compose 파일과 프로필로 `stop investor-flow-scheduler worker`다. 이 override는 읽기 전용
조회만 켜며 주문 작업을 등록하거나 활성화하지 않는다.

모의환경 당일분봉 API는 날짜 지정이 불가능해 최신 세션만 수집할 수 있다. 수집하지 않은 과거 거래일은 영구 결손으로 남으므로 거래일마다 실행한다. 달력이 없거나 충돌 상태면 수집은 실패 상태만 남기고 아무것도 저장하지 않는다.

KIS 모의투자 REST API는 초당 1건 제한을 적용하므로 Valkey 호출 게이트가 같은 환경과 자격증명을 사용하는 모든 worker의 인증·시세 요청을 최소 1.05초 간격으로 예약한다. 접근 토큰은 만료 1분 전까지 Valkey에서 재사용하며 동시에 토큰이 필요해도 분산 잠금을 획득한 worker 하나만 발급한다. Valkey를 사용할 수 없으면 호출 제한 위반을 막기 위해 새 KIS 요청을 보내지 않고 수집을 실패 처리한다. 자세한 반복 실행은 [모의환경 검증 런북](kis-paper-verification.md)을 따른다.

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
bun run e2e                      # 빈 DB 전용: 구조·빈 상태 검증 (CI와 동일)
E2E_EXPECT_DATA=1 bun run e2e     # 실수집 데이터가 있는 로컬 DB에서는 이 모드를 사용
```

브라우저 테스트 전에 API와 Vite 개발 서버가 각각 8000, 5173 포트에서 실행되어 있어야 한다.

Compose로 실행한 배포용 웹과 Caddy 프록시를 검증하려면 다음 명령을 사용한다.

```bash
cd frontend
PLAYWRIGHT_BASE_URL=http://127.0.0.1:8080 bun run e2e --headed
```
