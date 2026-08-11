# 디자인 시안 생성 프롬프트

- 상태: 기록
- 작성일: 2026-08-11
- 생성 방식: Codex 내장 이미지 생성 도구, `ui-mockup` 유형
- 결과물: [디자인 방향 제안](design-direction-proposals.md)

## 공통 구성

- 동일한 자동매매 운영 대시보드를 데스크톱과 모바일로 함께 표현한다.
- 데스크톱은 왼쪽 약 76%, 모바일은 오른쪽 약 20%를 사용한 정면 컨셉 보드다.
- 공통 표기는 `LIVE TRADING LOCKED`, `API`, `PostgreSQL`, `Valkey`, `PHASE 01`, `NEXT: RELIABLE MARKET DATA`, `PHASE 02`, `ORDER`, `POSITION`, `NO LIVE ORDERS`로 제한한다.
- 서비스는 모두 준비 상태로 표현한다.
- 금액, 수익률, 보유 수량, 주가, 캔들 또는 성과 차트는 생성하지 않는다.
- 모바일은 데스크톱을 축소하지 않고 안전 상태부터 읽히도록 재배치한다.
- 로고, 워터마크, 원근감 있는 기기 목업과 의미 없는 장식은 제외한다.

## 1안 Night Watch

```text
Production-grade Figma-like automated stock trading operations dashboard named NIGHT WATCH. Use a deep graphite canvas, cool slate panels, hairline borders, off-white text, mint-teal only for healthy services and amber only for the trading lock. Create a compact fixed left rail, slim command header, dominant locked-live-trading banner, three service rows, readiness checklist, next-milestone panel and empty order/position modules. Use severe 6px geometry, geometric sans and small monospaced metadata. Add a thin vertical status trace with three restrained mint pulses and one amber lock marker. Avoid neon cyberpunk, glassmorphism, card spam, rounded pill overload, glow, fake metrics and fake charts.
```

## 2안 Calm Ledger

```text
Production-grade Figma-like automated stock trading dashboard named CALM LEDGER. Use warm paper, white content, ink text, soft ledger rules, forest green only for healthy services and restrained vermilion only for the trading lock. Create a slim text navigation, spacious title band, broad safety notice, ledger-like service table, understated readiness row, next-milestone strip and simple empty modules. Use an elegant serif for major titles and a legible humanist sans for UI, generous whitespace, 2px corners and no shadows. Add quiet horizontal rules with section indices 01, 02, 03 and one full-width safety rule. Avoid generic banking imagery, card grids, pill overload, gradients, decorative charts and excessive rounded corners.
```

## 3안 Research Grid

```text
Production-grade Figma-like institutional research workstation named RESEARCH GRID. Use an institutional navy shell, porcelain work surface, graphite text, cobalt for active structure, teal only for healthy services and coral only for the trading lock. Create a narrow utility rail, indexed top navigation, strict 12-column workspace, high-priority safety cell, three-column service matrix, adjacent readiness and next-milestone cells and empty module rows. Use modern Swiss sans, compact monospaced labels, thin grid rules, squared corners and no shadows. Add coordinate labels A1 through D4 and a thin cobalt crosshair around the next milestone. Avoid sci-fi HUD styling, neon, card spam, glassmorphism, fake charts and decorative maps.
```

## 검수 기준

- 각 결과에서 데스크톱과 모바일이 모두 잘리지 않고 보여야 한다.
- 지정한 짧은 영문 라벨에 식별을 방해하는 오탈자나 무의미한 문자가 없어야 한다.
- 실전거래 잠금 상태가 다른 정보보다 먼저 보여야 한다.
- 세 서비스의 준비 상태가 색상과 텍스트로 함께 표현되어야 한다.
- 세 방향의 밝기, 정보 밀도, 타이포그래피와 레이아웃이 서로 명확히 달라야 한다.
