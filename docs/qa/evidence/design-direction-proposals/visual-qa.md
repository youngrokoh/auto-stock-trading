# 디자인 방향 시안 시각 QA

- 상태: 통과 · 사용자 선택 대기
- 검증일: 2026-08-11
- 범위: 이미지 전용 디자인 시안과 비교 문서
- 주의: 이 검증은 정적 시안의 품질만 확인하며 이후 실제 UI 구현의 브라우저 QA를 대체하지 않는다.

**Goal:** Independently review the three image-only UI direction boards for a Korean automated stock / ETF / company-analysis / quant-research product.

**Scope:** Static proposal artifacts only. No implementation, DOM, CSS, component tree, or runnable desktop/mobile surface was supplied or expected. Consequently, “live reused primitives” and “token-driven implementation” are not applicable at this proposal stage; this review does not certify a future implementation.

**Recommendation:** **APPROVE**

**Verdict:** **PASS** — the directions are genuinely distinct, coherent, suited to the stated product, and each visibly reflows from desktop to a safety-first, single-column mobile composition. No blocking issue was found in the reviewed scope.

## Evidence inspected

- [디자인 방향 제안](../../../design/design-direction-proposals.md), UTF-8 문서. 범위, 안전·데이터 제약, 비교 기준과 구현 게이트를 확인했다.
- [Night Watch 시안](../../../design/proposals/01-night-watch.png), RGB PNG, 1568 × 1003, SHA-256 `4fdf74a28191507a355451d2f45aa779a764edeffed74519d2d1e6e353d97b4c`.
- [Calm Ledger 시안](../../../design/proposals/02-calm-ledger.png), RGB PNG, 1536 × 1024, SHA-256 `3493c762e718cb0988de11ccfdf8acbd08fc281edde8376c4273d12de9b0f002`.
- [Research Grid 시안](../../../design/proposals/03-research-grid.png), RGB PNG, 1536 × 1024, SHA-256 `d2a845b879df245adc66b4ac043ac06d3d5ae62305e5e3010bc66bf1199dcde0`.

## Findings

### CRITICAL

None. These are clearly composition boards, not a screenshot masquerading as a live product implementation. There is no code claim to audit here.

### HIGH

None. The images do not substitute fake market metrics, charts, returns, or positions for the presently unavailable data. Each prioritizes the locked-trading state, then shows API, PostgreSQL, and Valkey as ready, consistent with the fixed constraints in the [proposal document](../../../design/design-direction-proposals.md).

### MEDIUM

None blocking.

- **Night Watch:** A dark graphite, cyan-ready, amber-lock operational shell; dense horizontal status rows, left tool rail, and top section navigation establish the operator-console direction. Its mobile companion preserves the lock banner and follows the status timeline vertically before order/position empties.
- **Calm Ledger:** Warm paper ground, editorial serif display face, hairline ledger rules, generous whitespace, and restrained red lock outline are materially different from Night Watch. The mobile version removes the side ledger rail and serializes service, milestone, and empty-state entries.
- **Research Grid:** Navy shell with a bright coordinate-labelled workplane, bolder outlined module cells, and blue/teal/red status accents reads as an extensible research workspace rather than either an operations console or a document ledger. Desktop uses distinct safety, service, and milestone cells; mobile promotes the lock first and stacks those cells in priority order.

### LOW

None blocking.

- The boards intentionally use short English labels. This is disclosed in the [proposal document](../../../design/design-direction-proposals.md); the Korean documentation itself is readable. Actual Korean font selection, text expansion, and accessibility contrast remain implementation-stage validation items.

## Independent visual gate

두 번째 독립 검수에서도 `PASS` 판정을 받았다.

- 모든 이미지에서 데스크톱과 모바일 외곽이 잘리지 않고 완전히 보인다.
- `LIVE TRADING LOCKED`가 위치, 크기, 경계와 경고색을 통해 가장 우선적으로 보인다.
- API, PostgreSQL, Valkey가 데스크톱·모바일 모두 `READY`로 표시된다.
- 가격, 잔고, 보유 수량, 손익, 수익률, 캔들 또는 성과 차트가 없다.
- 텍스트, 아이콘, 경계의 겹침이나 잘림이 없고 의도된 줄바꿈은 읽을 수 있다.
- 비교 문서에 기술한 색상, 밀도, 정보 구조와 각 이미지가 일치한다.

비차단 참고 사항으로 Night Watch의 데스크톱 `POSITION` 옆에 `NO LIVE ORDERS`가 사용되어 의미가 완전히 정확하지는 않다. 방향 선택용 시안의 판독에는 영향을 주지 않으며, 선택 후 한국어 실제 문구를 적용할 때 `보유 포지션 없음`처럼 문맥에 맞게 수정한다.

## Comparative assessment

| Direction | Distinct visual system | Product fit | Desktop/mobile consistency | Assessment |
|---|---|---|---|---|
| Night Watch | Dark operations console; compact row/timeline grammar; cyan/amber states | Excellent for system operation and incident awareness | Strong: same lock → readiness → milestones sequence becomes one column | Strong runner-up; borrow its high-salience lock treatment. |
| Calm Ledger | Paper/serif editorial ledger; low-to-medium density; red/green restraint | Good for investor reading and narrative company analysis | Strong: ledger rows become a reading sequence | Weakest *for the full stated product*, not visually weak: it leaves least room for dense research and operational comparison. |
| Research Grid | Navy shell + bright coordinate workplane; modular cell grammar; medium-high density | Best balanced fit for ETF screens, company analysis, strategy research, and safe operation | Strong: independent cells collapse into an ordered single column | Strongest concept and the appropriate base direction. |

## Required follow-through before implementation approval

No proposal-stage blocker. After the user selects a direction, the next change must turn its palette ramps, typography, spacing, grid rules, status states, responsive priorities, and reusable primitives into the documented design-system contract before UI code. A subsequent fidelity review must verify live DOM/primitives, token use, and real rendered breakpoints; this static-board approval does not replace that gate.
