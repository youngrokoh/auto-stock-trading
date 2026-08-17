# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Language

Project documentation, UI copy, and test assertion strings are Korean. Keep them Korean. Code identifiers, `AGENTS.md`, and this file are English.

## Commands

Backend commands run from `backend/`, frontend from `frontend/`, docs guard and compose from the repo root.

```bash
# Backend (uv, Python 3.14.6)
uv sync --frozen --all-groups
uv run alembic upgrade head
uv run uvicorn auto_stock_trading.api.app:app --reload
uv run taskiq worker auto_stock_trading.worker.market_data:broker
uv run ruff check src tests migrations && uv run ruff format --check src tests migrations
uv run basedpyright
uv run pytest
uv run pytest tests/api/test_health_api.py::test_liveness_reports_environment   # single test

# Frontend (bun 1.3.14)
bun install --frozen-lockfile
bun run dev                     # Vite :5173, proxies /api -> :8000
bun run lint                    # biome check
bun run typecheck               # tsc -b
bun run test                    # vitest run
bun run test tests/health.test.ts               # single unit test file
bun run e2e                                     # Playwright, needs :8000 + :5173 up
bun run e2e --project=desktop -g "dashboard"    # single e2e project/test
PLAYWRIGHT_BASE_URL=http://127.0.0.1:8080 bun run e2e   # against the Compose/Caddy build

# Full stack
docker compose -f infra/compose.yaml up --build -d --wait --wait-timeout 300
docker compose -f infra/compose.yaml down       # never `down -v` unless wiping data on purpose

# Documentation gate (repo root, system python3 is enough)
python3 scripts/docs_guard.py generate   # after adding/moving/renaming docs
python3 scripts/docs_guard.py check      # before handing work back
python3 scripts/docs_guard.py drift --base-ref <commit>
bash tests/docs-guard-test.sh
bash tests/infra-compose-test.sh
```

E2E requires the API on `:8000` and Vite on `:5173`. Use `VITE_DISABLE_REACT_DEVTOOLS=1` when capturing QA screenshots so react-scan/react-grab overlays stay out of the image.

## Documentation gate — read before touching code

`AGENTS.md` is binding and CI enforces it. Before changing implementation or tests, read `docs/governance/change-map.yaml`: it maps code glob patterns to documents that must change in the same commit. Touching `frontend/src/**` without touching one of `docs/design/design-system.md`, `docs/qa/phase-1-verification.md`, or `docs/api/health-api.md` fails the Documentation workflow. Same for backend API/worker/settings/infra paths → architecture + ADR docs.

Escape hatch: a `docs-not-required: <reason ≥10 chars>` line in the PR body (see `.github/pull_request_template.md`). Use it only for genuinely behavior-neutral internal changes.

Also required:
- All project documentation lives under `docs/`, lowercase kebab-case filenames, and must be linked from `docs/README.md`. `docs_guard check` fails on broken relative Markdown links and on a stale `docs/generated/document-inventory.md`.
- Every doc carries a `- 상태: <status>` line; the inventory generator reads it.
- Order execution, risk controls, permissions, and AI/execution boundary changes need a new or updated ADR in `docs/decisions/` **plus explicit human approval**.
- Never edit an approved policy document to make an implementation pass. Report the conflict and fix the implementation, or ask for a decision.

## Approval state (as of 2026-08-16)

`docs/plan/current-status.md` is the handoff document — read it at session start. Three standing constraints:

- **The UI direction is approved.** On 2026-08-12 the user approved the Research Grid structure combined with Night Watch safety states in `docs/design/claude-design/`. The current React dashboard still predates that approved design, so its QA `PASS` is not evidence that the approved design is implemented. Build future screens from the approved tokens, primitives, and responsive specifications; never hardcode the sample prices, positions, orders, or account values from the mockup.
- **Live trading is off.** KIS paper-environment authentication and read-only market-data collection are implemented and externally validated for Samsung Electronics and KODEX 200. The separate live KIS credentials are used only by the approved read-only market-calendar confirmation path. Account access, orders, positions, strategies, and live execution are not implemented. Live trading stays disabled until the approved gate in `docs/spec/paper-to-live-gate.md` is passed. Never use live credentials in a paper verification path or fabricate market data in the UI.
- **The corporate-action and adjusted-price contract is approved.** `docs/data/corporate-action-adjusted-price-data-contract.md` is binding. Unadjusted daily bars now preserve versions and finality; adjusted prices must remain a separate derived dataset. Do not mix adjusted rows into `market.market_bar`, erase superseded facts, or publish derived data from pending inputs.

## Architecture

Modular monolith: one Python package, several processes (ADR-0001).

```
Caddy :8080  ── /api/* → FastAPI :8000 ── PostgreSQL 18
             └─ /*     → React static     └─ Valkey ← Taskiq worker
                                               ↓
                         KIS paper market data, KRX official calendar,
                         and live KIS read-only calendar confirmation
```

Backend layering, strictly one-directional (`backend/src/auto_stock_trading/`):

- `api/` — FastAPI routers + Pydantic **response** models only (`api/models.py`)
- `application/` — use cases and domain types; defines `Protocol`s (e.g. `HealthProbe`) that adapters satisfy structurally
- `adapters/` — external boundaries (SQLAlchemy, KIS HTTP, Valkey/Redis coordination; the health probe uses a minimal RESP socket)
- `settings/` — `pydantic-settings`, env prefix `AUTO_STOCK_`, secrets as `SecretStr`
- `worker/` — Taskiq broker entry point

`create_app()` in `api/app.py` takes optional probe factories — that is the seam tests use to avoid real infrastructure. Follow the same pattern for new subsystems: application layer defines the Protocol, `create_app` injects the adapter, tests pass a fake.

The health endpoints are the reference vertical slice for everything added later: `adapters` → `application/health.py` (`HealthService`, frozen slotted dataclasses, `StrEnum` states) → `api/health.py` → `api/models.py` → `frontend/src/lib/health.ts` (Zod `strictObject`) → `frontend/src/api/health.ts`. The Zod schema is `strictObject`, so **adding a field to a response model breaks the frontend parse** — change both sides together, and update `docs/api/health-api.md`.

`/api/health/ready` returns 503 when degraded (for probes); `/api/health/status` returns the same body always 200 (for the browser, so TanStack Query does not treat degradation as a fetch error). Never leak connection URLs into responses or logs — the e2e test asserts `postgresql://` and `redis://` are absent from the rendered page.

Alembic revision `20260811_0001` creates PostgreSQL schemas (`reference`, `market`, `fundamental`, `strategy`, `trading`, `operations`). Revision `20260814_0002` adds the first market-data tables for instruments, quotes, daily bars, raw responses, and collection runs. Revision `20260816_0003` adds the versioned `reference.market_calendar` table. Revision `20260816_0004` adds persistent scheduled-job execution claims. Revision `20260816_0005` converts `market.market_bar` to versioned, unadjusted facts with explicit pending/confirmed finality and one current row per logical bar. Revision `20260816_0006` adds `market.corporate_action` as versioned corporate-action facts with one current row per `action_key` and source-event/version uniqueness. The migration test renders offline SQL (`--sql`), while repository integration tests exercise the applied schema on PostgreSQL.

ADR-0005 is the binding KIS coordination decision. Workers sharing an environment and credential scope reuse a Valkey-cached access token and reserve KIS request slots through a distributed gate. Valkey failure is fail-closed: do not bypass coordination with a local token or independent requests. Keep the Compose Valkey host binding on `127.0.0.1`, and never expose the token cache or include token values in diagnostics.

ADR-0006 is the binding market-calendar scheduling decision. Run one Taskiq scheduler, but enforce duplicate prevention with PostgreSQL execution claims rather than process count alone. KRX collection precedes KIS same-day confirmation on Seoul time. Automatic KIS confirmation is enabled only through the user-approved `infra/compose.kis-live-calendar.yaml` override: the worker receives read-only live credentials, while the scheduler receives no secrets. Default Compose and paper environments keep it disabled; missing, stale, pending, or conflicting calendar state remains fail-closed.

Frontend: React 19 + TanStack Query + Tailwind 4, no router yet — `App.tsx` switches on `window.location.pathname` (`/showcase` vs dashboard). Dev-only diagnostics load dynamically in `devtools.ts` behind `import.meta.env.DEV`.

## Conventions that bite

- **Exact pinned versions everywhere.** `pyproject.toml` and `package.json` use `==` / exact strings, lockfiles are committed, no prereleases. `docs/architecture/tech-stack.md` records the baseline; update it when bumping.
- Ruff runs `select = ["ALL"]` (line length 100) and basedpyright runs `typeCheckingMode = "all"` with `reportAny`/`reportExplicitAny` as errors — no untyped escapes, `@final` on concrete classes, `_ = ` for discarded returns.
- Python 3.14 syntax is in use (parenthesis-free multi-exception `except A, B:`, `type` statement). Do not "fix" these to older forms.
- TypeScript: `strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, `verbatimModuleSyntax`, `erasableSyntaxOnly`. Biome forbids `any` and unused variables.
- Money uses `Decimal`, never `float`; timestamps stored UTC with exchange timezone preserved (see tech-stack §3.1).
- `ListQueueBroker` must keep `socket_timeout=None` or an idle worker drops its blocking pop.
- Playwright runs three viewport projects (mobile/tablet/desktop); the dashboard spec also asserts zero console errors and no horizontal overflow.
- Credentials for the broker (KIS) never enter documents, Git, the browser bundle, or logs; paper and live credentials stay fully separate.
- `kis_coordination.py` is already near the project's 250 pure-LOC review threshold. Split the Valkey implementation into a separate module before extending KIS coordination behavior.

## Next implementation work

Continue from `docs/plan/current-status.md`, not from a remembered chat plan. The KRX annual calendar, temporary-hours notices, Taskiq scheduler, PostgreSQL execution claims, approved live read-only KIS confirmation, versioned unadjusted daily-bar storage, the versioned `market.corporate_action` repository, and OpenDART cash-dividend collection (`adapters/disclosures/`, strict form parsing, correction linking by record date) are implemented. KODEX 200 ETF distributions are collected from the fund manager's official KODEX API (`kodex_distributions.py`, no credentials) through the same generalized `CorporateActionCollector`. Real-API collection was verified on 2026-08-17 for both sources: three 2026 Samsung dividends via the user's DART key (`.secrets/dart-api-key`) and eleven KODEX 200 distributions (2024-2026), each with idempotent re-collection and official-document cross-checks. All corporate-action facts still lack ex-dates. Next, settle the ex-date confirmation boundary and build the adjustment-factor calculator with the separate adjusted-price dataset; minute bars follow. Approved-design frontend implementation is a separate track and requires real browser QA at 390px, 768px, and 1360px.
