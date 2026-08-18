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
bun run e2e                                     # Playwright, needs :8000 + :5173 up. Default mode asserts structure + empty states — for a fresh/empty DB (CI parity); it fails against a populated DB
E2E_EXPECT_DATA=1 bun run e2e                   # data mode: asserts real collected data — use this against the local populated DB
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

- **The UI direction is approved and now implemented for the first screens.** On 2026-08-12 the user approved the Research Grid structure combined with Night Watch safety states in `docs/design/claude-design/`. On 2026-08-17 the approved tokens and primitives (coordinate cells, data tables, status badges, safety banners, responsive app shell) plus the 운영 개요 (`/`), 시장 데이터 (`/market`), and primitives gallery (`/showcase`) screens were built on them, with real-browser QA at 390/768/1360px; the tablet folding rule (keep the 52px rail, hide the nav panel, single column, KPI 3×2) was user-approved the same day. Build further screens from the same tokens and primitives; never hardcode the sample prices, positions, orders, or account values from the mockup — every displayed value comes from real APIs, and areas without a backend stay as explicit empty states.
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

Alembic revision `20260811_0001` creates PostgreSQL schemas (`reference`, `market`, `fundamental`, `strategy`, `trading`, `operations`). Revision `20260814_0002` adds the first market-data tables for instruments, quotes, daily bars, raw responses, and collection runs. Revision `20260816_0003` adds the versioned `reference.market_calendar` table. Revision `20260816_0004` adds persistent scheduled-job execution claims. Revision `20260816_0005` converts `market.market_bar` to versioned, unadjusted facts with explicit pending/confirmed finality and one current row per logical bar. Revision `20260816_0006` adds `market.corporate_action` as versioned corporate-action facts with one current row per `action_key` and source-event/version uniqueness. Revision `20260817_0007` adds the adjusted-price dataset tables (`market.adjustment_dataset`, `market.adjustment_dataset_action`, `market.adjusted_market_bar`) with a partial unique input-identity index over building/published rows. Revision `20260817_0008` adds versioned `market.minute_bar` facts keyed by `bar_started_at` with the same pending/confirmed finality pattern. Revision `20260817_0010` adds versioned `reference.listed_share_count` facts observed from KIS quote responses (same-value re-observation refreshes evidence only; changed counts supersede). Revision `20260817_0011` adds versioned `market.investor_flow` daily facts and immutable `fundamental.disclosure` list entries (unique per instrument+rcept_no, no versioning — corrections arrive as new receipt numbers). Revision `20260818_0012` adds versioned `reference.etf_profile` facts (from the unauthenticated official KIS master file, fixed-width cp949 records, group code EF) and the `market.etf_nav` latest-snapshot table (quote-style upsert; history reconstructable from append-only raws only). Revision `20260818_0013` adds the `strategy.backtest_run`/`backtest_trade`/`backtest_equity` tables for append-only backtest run records with full input lineage. The migration test renders offline SQL (`--sql`), while repository integration tests exercise the applied schema on PostgreSQL.

ADR-0005 is the binding KIS coordination decision. Workers sharing an environment and credential scope reuse a Valkey-cached access token and reserve KIS request slots through a distributed gate. Valkey failure is fail-closed: do not bypass coordination with a local token or independent requests. Keep the Compose Valkey host binding on `127.0.0.1`, and never expose the token cache or include token values in diagnostics.

ADR-0006 is the binding market-calendar scheduling decision. Run one Taskiq scheduler, but enforce duplicate prevention with PostgreSQL execution claims rather than process count alone. KRX collection precedes KIS same-day confirmation on Seoul time. Automatic KIS confirmation is enabled only through the user-approved `infra/compose.kis-live-calendar.yaml` override: the worker receives read-only live credentials, while the scheduler receives no secrets. Default Compose and paper environments keep it disabled; missing, stale, pending, or conflicting calendar state remains fail-closed.

Frontend: React 19 + TanStack Query + Tailwind 4, no router yet — `App.tsx` switches on `window.location.pathname` (`/` overview, `/market`, `/analysis`, `/etf`, `/strategy`, `/showcase`). The approved design lives in `src/styles.css` (semantic tokens, light default + `prefers-color-scheme: dark` per spec §8) and `src/components/` (app-shell, coordinate-cell, status-badge, safety-banner, chart-panes, figure-bars). Market-data and fundamentals responses are parsed with Zod `strictObject` in `src/lib/market-data.ts` / `src/lib/fundamentals.ts` (decimals arrive as strings, including pydantic's `"0E-8"` scientific form); price indicators (SMA/RSI/MACD/Bollinger) are computed client-side in `src/lib/indicators.ts` from confirmed bars only, while financial ratios are computed backend-side and only displayed (roadmap: same definition on screen and backend). Dev-only diagnostics load dynamically in `devtools.ts` behind `import.meta.env.DEV`.

## Conventions that bite

- **Exact pinned versions everywhere.** `pyproject.toml` and `package.json` use `==` / exact strings, lockfiles are committed, no prereleases. `docs/architecture/tech-stack.md` records the baseline; update it when bumping.
- Ruff runs `select = ["ALL"]` (line length 100) and basedpyright runs `typeCheckingMode = "all"` with `reportAny`/`reportExplicitAny` as errors — no untyped escapes, `@final` on concrete classes, `_ = ` for discarded returns.
- Python 3.14 syntax is in use (parenthesis-free multi-exception `except A, B:`, `type` statement). Do not "fix" these to older forms.
- TypeScript: `strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, `verbatimModuleSyntax`, `erasableSyntaxOnly`. Biome forbids `any` and unused variables.
- Money uses `Decimal`, never `float`; timestamps stored UTC with exchange timezone preserved (see tech-stack §3.1).
- `ListQueueBroker` must keep `socket_timeout=None` or an idle worker drops its blocking pop.
- Playwright runs three viewport projects (mobile/tablet/desktop); the dashboard spec also asserts zero console errors and no horizontal overflow. CI runs against a freshly migrated empty database, so data-dependent assertions are gated behind `E2E_EXPECT_DATA=1` — run the data mode against the populated local DB and the default mode against a fresh scratch DB when touching e2e, and keep backend integration tests self-contained (create their own instruments/rows; never assume collected data exists).
- Credentials for the broker (KIS) never enter documents, Git, the browser bundle, or logs; paper and live credentials stay fully separate.
- `kis_coordination.py` is already near the project's 250 pure-LOC review threshold. Split the Valkey implementation into a separate module before extending KIS coordination behavior.

## Next implementation work

Continue from `docs/plan/current-status.md`, not from a remembered chat plan. The KRX annual calendar, temporary-hours notices, Taskiq scheduler, PostgreSQL execution claims, approved live read-only KIS confirmation, versioned unadjusted daily-bar storage, the versioned `market.corporate_action` repository, and OpenDART cash-dividend collection (`adapters/disclosures/`, strict form parsing, correction linking by record date) are implemented. KODEX 200 ETF distributions are collected from the fund manager's official KODEX API (`kodex_distributions.py`, no credentials) through the same generalized `CorporateActionCollector`. Real-API collection was verified on 2026-08-17 for both sources: three 2026 Samsung dividends via the user's DART key (`.secrets/dart-api-key`) and eleven KODEX 200 distributions (2024-2026), each with idempotent re-collection and official-document cross-checks. Ex-dates are confirmed by the user-approved rule (previous trading day before the last trading day on or before the record date, verified XKRX calendar only, fail-closed on missing coverage) via `ExDateResolver`, producing `verified` fact versions. The adjustment calculator (`domain/market_data/adjustments.py`) and `PostgresAdjustmentStore` build split_adjusted/total_return datasets with pinned hash serialization, knowledge-cutoff version selection, and fail-closed publication. Daily bars are confirmed by `DailyBarConfirmer` (two matching observations after 15:40 KST on the trading date; intraday first observations don't count; mismatches become pending correction versions), and real datasets are published from confirmed bars — verified against the live paper API with the KODEX 2026-07-30 distribution factor. The corporate-action and adjusted-price read API is implemented per the contract's 필수 조회 계약: `api/market_data_adjusted.py` exposes current/history/point-in-time corporate actions, latest published datasets with per-bar factors and lineage (`source_bar_id`/`source_bar_version`, applied action versions), dataset-by-id, and action-impact lists; `create_app` injects `CorporateActionReader`/`AdjustedPriceReader` protocol implementations (read adapters are separate modules from the write stores). Responses never express raw-vs-adjusted as a single boolean. Verified against the real published datasets, including empty results for pre-collection knowledge cutoffs. Minute bars are implemented per the user-approved `docs/data/minute-bar-data-contract.md`: unadjusted 1-minute facts collected from the KIS same-day endpoint (latest session only — no historical backfill exists in the paper environment; uncollected days are permanent gaps), filtered to the verified calendar session window, versioned in `market.minute_bar`, confirmed by two matching post-interval observations (`MinuteBarCollector`), collected via `worker/market_data.py --collect-minute-bars`, and read via `GET .../minute-bars?trading_date=`. Known source quirks (recorded in the contract, do not "fix" the data): the 15:30 closing-auction row reports exactly double the executed volume, and per-minute volume sums do not match daily-bar volume (the minute feed's own cumulative volume does). Phase 4 fundamentals groundwork is implemented per the user-approved `docs/data/financial-statement-data-contract.md`: OpenDART full financial statements (`fnlttSinglAcntAll`, CFS+OFS, last 5 annual reports + current-year interim reports) are stored as receipt-number-evidenced report versions in `fundamental.financial_report`/`financial_statement_line` (revision `20260817_0009`; same-receipt refetch is idempotent, a new receipt supersedes while preserving history, older receipts are rejected, unfiled periods are skipped). Lines are keyed by `line_seq` (response order) because the source `ord` repeats in SCE statements, and `account_id` is up to 180 chars in practice — both user-approved contract corrections. Collect via `worker/fundamentals.py`; read via `/api/fundamentals/...` (reports list / lines by report_id / correction history). Verified against real DART data for Samsung (14 reports, totals matched). Financial indicators are implemented per the user-approved `docs/data/financial-indicator-contract.md`: nine growth/profitability/stability indicators computed at read time (never stored) from current-version annual CFS/OFS reports only, each response carrying formula, input accounts with amounts, and the evidencing `rcept_no`; missing/duplicated accounts, missing amounts, and zero denominators fail closed with reason codes (OFS ROE really returns `MISSING_ACCOUNT` — 지배주주 lines exist only in CFS). ROE uses 지배주주순이익 over average 지배기업 소유주지분; growth uses the same report's 당기/전기 amounts. Value indicators are implemented per the same contract's user-approved amendment: listed share counts (`lstn_stcn`) are observed during KIS quote collection into versioned `reference.listed_share_count` facts, and the indicators response carries a `valuation` block — EPS is the disclosed 기본주당이익 original fact (never derive 순이익÷주식수: preferred shares make it wrong — measured 7,570.79 vs disclosed 6,605), PER = price ÷ latest annual basic EPS, market cap = price × common share count — always exposing the three distinct bases (price as_of, share-count as_of/version, report rcept_no) separately, with `MISSING_QUOTE`/`MISSING_SHARE_COUNT` fail-closed reasons. BPS/PBR are deferred until a preferred-share-aware design is approved; never expose KIS's own per/pbr/eps/bps values as our indicators. The 기업 분석 screen (`/analysis`, mockup 2b) displays this API only — verified against hand-recomputed Samsung figures (PER 41.56, market cap 1,604.8조) and 12 e2e tests at 390/768/1360px plus dark mode. Phase 5 ETF exploration is implemented per the user-approved `docs/data/etf-exploration-data-contract.md`: the domestic ETF universe (1,163 KOSPI EF rows) comes from KIS's unauthenticated master file into versioned `reference.etf_profile` facts (raw kept as a base64 envelope); `market.etf_nav` holds latest snapshots from the paper-supported ETF price TR `FHPST02400000`, whose source fields already carry NAV, 괴리율(`dprt`), 추적오차, 추적배수, 운용사, 대표지수, and 순자산총액 in 억원 — never classify ETFs by name heuristics, use these fields. A full sweep takes ~21 minutes at the paper rate limit (`--collect-etf-nav`; per-symbol failures are recorded and the sweep continues; sync target symbol `ETF`). Distribution yield uses the roadmap formula (최근 12개월 분배금 합 ÷ 현재가 × 100) computed only for ETFs with stored distributions. Rankings are snapshot-based only (등락률/거래량/괴리율/추적오차/순자산 — the ETF price response has no 거래대금; period returns and per-investor rankings are follow-ups). Investor flows and disclosure linking are implemented per the user-approved `docs/data/investor-flow-disclosure-contract.md`: KIS `FHKST01010900` daily per-investor net buys (개인/외국인/기관) are stored as versioned facts excluding the current Seoul date (intraday rows are provisional); recorded source quirks — the three investor groups do not sum to zero (other entities are absent) and values are in millions of KRW stored as-is; the API returns only ~30 recent trading days, so history accumulates from first collection (`worker/market_data.py --collect-investor-flows`). DART disclosures are collected per type (`pblntf_ty` A/B/D/I) because the plain list response has no type field, stored as immutable receipt-unique rows (`worker/fundamentals.py --collect-disclosures`, initial window 1 year), and linked to the DART viewer by rcpNo on the analysis screen (D2/D3 cards). Phase 6 backtesting is implemented per the user-approved `docs/data/backtest-strategy-contract.md`: daily bars are backfilled from 2025-01-02 (KIS paper history works, max ~100 bars per call — collect+confirm in chunks; 394 confirmed days per instrument), Samsung 2025 dividends were back-collected and ex-date-verified, and full-window total_return datasets republished. The deterministic engine (`domain/strategies/backtest.py`) executes T-close signals at the next tradable open (calendar roll-forward), applies safety-policy §5 costs with dated statutory sell-tax rule sets (`research-krx-2025`: KOSPI 0.15%, `research-krx-2026`: 0.20%, ETF exempt; each cost item floored to won), credits dividends as cash on verified ex-dates from prior-day holdings, and rejects non-causal signal functions by recomputing every signal on the prefix series (`lookahead_input`). Indicators (SMA/EMA/RSI-Wilder/MACD/ATR/Bollinger) are pure Decimal functions in `domain/strategies/indicators.py`; the MA-RSI strategy (sell-priority: dead cross or RSI>=overbought; buy: golden cross with RSI filter) is the v1 baseline. Runs persist to the `strategy` schema with canonical-JSON parameters, bar/action version hashes, dataset IDs and cost-rule versions; read via `GET /api/backtests[...]` (failed runs stay queryable with failure codes); execute via `uv run python -m auto_stock_trading.worker.backtests`. Real-data verification: identical metrics on re-run, 107 signals matched an independent recomputation, weekend roll-forward and ETF tax exemption confirmed (`docs/qa/phase-6-backtest-verification.md`). Composite-rank and ETF-momentum strategies wait for a multi-instrument universe. The 전략 연구 screen (`/strategy`, mockup 2c) displays stored runs only: performance KPI 7, run selector with NAV/드로다운 curves (benchmark curve derived from the published total_return dataset via `GET .../adjusted-daily-bars`), cost card, signal/trade table on the D coordinate (user-approved stand-in until phase-7 target positions), walk-forward run comparison, and lineage card; the mobile tabbar is now 운영/시장/기업/ETF/전략. Next: phase 7 (paper auto-trading). The KIS adjusted-price cross-check still waits for an instrument with split history. Approved-design frontend implementation requires real browser QA at 390px, 768px, and 1360px.
