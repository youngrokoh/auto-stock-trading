# 문서 인벤토리

> 이 파일은 `python3 scripts/docs_guard.py generate`로 생성됩니다. 직접 수정하지 마세요.

| 문서 | 경로 | 상태 |
|---|---|---|
| [Auto Stock Trading](../README.md) | `docs/README.md` | 미지정 |
| [백테스트 읽기 API](../api/backtest-api.md) | `docs/api/backtest-api.md` | 구현됨 |
| [기업 재무 읽기 API](../api/fundamentals-api.md) | `docs/api/fundamentals-api.md` | 구현됨 |
| [내부 상태 확인 API](../api/health-api.md) | `docs/api/health-api.md` | 구현됨 |
| [시장 데이터 읽기 API](../api/market-data-api.md) | `docs/api/market-data-api.md` | 구현됨 |
| [모의투자 주문 계획 읽기 API](../api/trading-api.md) | `docs/api/trading-api.md` | 구현됨 |
| [프로젝트 실행 구조](../architecture/project-structure.md) | `docs/architecture/project-structure.md` | 구현됨 |
| [상세 기술 스택](../architecture/tech-stack.md) | `docs/architecture/tech-stack.md` | 승인 |
| [백테스트·규칙형 전략 계약](../data/backtest-strategy-contract.md) | `docs/data/backtest-strategy-contract.md` | 구현 기준 |
| [기업행사·수정주가 데이터 계약](../data/corporate-action-adjusted-price-data-contract.md) | `docs/data/corporate-action-adjusted-price-data-contract.md` | 승인 |
| [ETF 탐색 데이터 계약](../data/etf-exploration-data-contract.md) | `docs/data/etf-exploration-data-contract.md` | 구현 기준 |
| [주문·위험 이벤트 외부 알림 계약](../data/event-notification-contract.md) | `docs/data/event-notification-contract.md` | 승인 |
| [재무 지표 정의 계약](../data/financial-indicator-contract.md) | `docs/data/financial-indicator-contract.md` | 구현 기준 |
| [재무제표 데이터 계약](../data/financial-statement-data-contract.md) | `docs/data/financial-statement-data-contract.md` | 구현 기준 |
| [수급·공시 연결 데이터 계약](../data/investor-flow-disclosure-contract.md) | `docs/data/investor-flow-disclosure-contract.md` | 구현 기준 |
| [국내 시장 달력 데이터 계약](../data/market-calendar-data-contract.md) | `docs/data/market-calendar-data-contract.md` | 구현 기준 |
| [국내 분봉 데이터 계약](../data/minute-bar-data-contract.md) | `docs/data/minute-bar-data-contract.md` | 구현 기준 |
| [ML 신호 데이터·모델 계약](../data/ml-signal-contract.md) | `docs/data/ml-signal-contract.md` | 구현 기준 |
| [주문 계획·위험검사 데이터 계약](../data/order-planning-risk-contract.md) | `docs/data/order-planning-risk-contract.md` | 구현 기준 |
| [주문 제출·체결 동기화 계약](../data/order-submission-contract.md) | `docs/data/order-submission-contract.md` | 구현 기준 |
| [실시간 체결통보 계약](../data/realtime-fill-notification-contract.md) | `docs/data/realtime-fill-notification-contract.md` | 구현 기준 |
| [종목 유니버스·업종 분류 데이터 계약](../data/stock-universe-data-contract.md) | `docs/data/stock-universe-data-contract.md` | 구현 기준 |
| [ADR-0001: 모듈형 모놀리스 채택](../decisions/0001-modular-monolith.md) | `docs/decisions/0001-modular-monolith.md` | 승인 |
| [ADR-0002: Python·React 기술 기준선 채택](../decisions/0002-technology-baseline.md) | `docs/decisions/0002-technology-baseline.md` | 승인 |
| [ADR-0003: PostgreSQL 중심 데이터 아키텍처 채택](../decisions/0003-data-architecture.md) | `docs/decisions/0003-data-architecture.md` | 승인 |
| [ADR-0004: AI 신호와 주문 실행 분리](../decisions/0004-ai-execution-separation.md) | `docs/decisions/0004-ai-execution-separation.md` | 승인 |
| [ADR-0005: Valkey 기반 KIS 토큰·호출 조정](../decisions/0005-kis-token-and-rate-coordination.md) | `docs/decisions/0005-kis-token-and-rate-coordination.md` | 승인 |
| [ADR-0006: 시장 달력 스케줄 실행과 중복 방지](../decisions/0006-market-calendar-scheduling.md) | `docs/decisions/0006-market-calendar-scheduling.md` | 승인 |
| [ADR-0007: 모의투자 주문 계획과 위험검사 경계](../decisions/0007-paper-order-planning-and-risk.md) | `docs/decisions/0007-paper-order-planning-and-risk.md` | 승인 |
| [ADR-0008: 모의투자 주문 제출·체결 동기화 경계](../decisions/0008-paper-order-submission.md) | `docs/decisions/0008-paper-order-submission.md` | 승인 |
| [ADR-0009: 실시간 체결통보 수신 경계](../decisions/0009-realtime-fill-notification.md) | `docs/decisions/0009-realtime-fill-notification.md` | 승인 |
| [ADR-0010: 사람이 확인한 주문 대조 종결](../decisions/0010-human-attested-order-reconciliation.md) | `docs/decisions/0010-human-attested-order-reconciliation.md` | 승인 |
| [ADR-0011: 모의투자 주문 정정 경계](../decisions/0011-paper-order-revision.md) | `docs/decisions/0011-paper-order-revision.md` | 승인 |
| [ADR-0012: ML 신호의 전략 경계](../decisions/0012-ml-signal-boundary.md) | `docs/decisions/0012-ml-signal-boundary.md` | 승인 |
| [ADR-0013: 미체결 수량 축소 경계 (부분 취소)](../decisions/0013-paper-partial-cancel.md) | `docs/decisions/0013-paper-partial-cancel.md` | 승인 |
| [ADR-0014: 주문·위험 이벤트 외부 알림 경계](../decisions/0014-outbound-event-notification.md) | `docs/decisions/0014-outbound-event-notification.md` | 승인 |
| [ADR-0015: 자동 스케줄 주문 제출 경계](../decisions/0015-scheduled-order-submission.md) | `docs/decisions/0015-scheduled-order-submission.md` | 승인 (2026-08-25 구현) |
| [ADR-0016: 실주문 신호 원천 경계](../decisions/0016-live-signal-source.md) | `docs/decisions/0016-live-signal-source.md` | 승인 |
| [ADR-0017: 마감 후 재대조와 세션 종료 주문 처리 경계](../decisions/0017-post-close-reconciliation-and-session-end.md) | `docs/decisions/0017-post-close-reconciliation-and-session-end.md` | 승인 (2026-08-25 구현) |
| [ADR-0018: 사람이 확인한 재조정 문제 해소 경계](../decisions/0018-human-resolved-reconciliation-records.md) | `docs/decisions/0018-human-resolved-reconciliation-records.md` | 초안 |
| [화면 구현 요청 안내](../design/claude-design/README.md) | `docs/design/claude-design/README.md` | 승인된 디자인 구현 안내 |
| [화면 디자인 사양](../design/claude-design/screen-design-spec.md) | `docs/design/claude-design/screen-design-spec.md` | 승인 |
| [자동매매 웹 디자인 방향 제안](../design/design-direction-proposals.md) | `docs/design/design-direction-proposals.md` | 승인 |
| [자동매매 운영 UI 디자인 시스템](../design/design-system.md) | `docs/design/design-system.md` | 승인 |
| [디자인 시안 생성 프롬프트](../design/proposal-generation-prompts.md) | `docs/design/proposal-generation-prompts.md` | 기록 |
| [문서 동기화 정책](../governance/documentation-policy.md) | `docs/governance/documentation-policy.md` | 승인 |
| [KIS 모의환경 검증 런북](../operations/kis-paper-verification.md) | `docs/operations/kis-paper-verification.md` | 실제 모의 API 반복 수집·프로세스 간 토큰 재사용 검증 완료 |
| [로컬 개발과 실행](../operations/local-development.md) | `docs/operations/local-development.md` | 구현됨 |
| [현재 프로젝트 상태와 다음 세션 인계](../plan/current-status.md) | `docs/plan/current-status.md` | 진행 중 |
| [자동매매 웹 프로그램 구현 로드맵](../plan/implementation-roadmap.md) | `docs/plan/implementation-roadmap.md` | 승인 |
| [디자인 방향 시안 시각 QA](../qa/evidence/design-direction-proposals/visual-qa.md) | `docs/qa/evidence/design-direction-proposals/visual-qa.md` | 통과 · 방향 승인 완료 |
| [Phase 1 Clone / Design-System Fidelity Gate](../qa/evidence/phase-1/design-system-fidelity-gate.md) | `docs/qa/evidence/phase-1/design-system-fidelity-gate.md` | 미지정 |
| [1단계 검증 기록](../qa/phase-1-verification.md) | `docs/qa/phase-1-verification.md` | 기술 검증 통과 · 시각 디자인 사용자 미승인 |
| [1단계 시각 QA 감사 기록](../qa/phase-1-visual-review.md) | `docs/qa/phase-1-visual-review.md` | 프로토타입 품질 통과 · 시각 디자인 사용자 미승인 |
| [2단계 시장 데이터 수직 슬라이스 검증](../qa/phase-2-market-data-verification.md) | `docs/qa/phase-2-market-data-verification.md` | 자동·로컬 통합·실제 KIS 모의환경·실전 달력 읽기·실제 KRX 일정·scheduler·실제 DART 배당·KODEX 분배금 수집·락일 확정·일봉 재조회 확정·실제 수정주가 발행 검증 완료, 사용자 화면 대조 대기 |
| [3단계 시장 대시보드 검증](../qa/phase-3-market-dashboard-verification.md) | `docs/qa/phase-3-market-dashboard-verification.md` | 검증 완료 (1차 구현 범위) |
| [4단계 기업 재무 데이터 검증](../qa/phase-4-fundamentals-verification.md) | `docs/qa/phase-4-fundamentals-verification.md` | 검증 완료 (수집·저장·읽기 API·지표 계산·가치지표·수급·공시 연결·기업 분석 화면 범위) |
| [5단계 ETF 탐색 검증](../qa/phase-5-etf-verification.md) | `docs/qa/phase-5-etf-verification.md` | 검증 완료 (마스터·NAV 스냅샷·순위·상세 범위) |
| [6단계 백테스트 엔진 검증](../qa/phase-6-backtest-verification.md) | `docs/qa/phase-6-backtest-verification.md` | 검증 완료 (엔진·기술 전략 1종·읽기 API·전략 연구 화면 범위) |
| [7단계 주문 계획·위험검사 검증](../qa/phase-7-order-planning-verification.md) | `docs/qa/phase-7-order-planning-verification.md` | 검증 완료 (계획·제출·체결·취소를 실제 모의계좌에서 확인) · 장중 주문별 체결 조회 한계는 후속 결정 대기 |
| [8단계 ML 신호 검증](../qa/phase-8-ml-verification.md) | `docs/qa/phase-8-ml-verification.md` | 1차 검증 완료 (다섯 시도 모두 완료 기준 미달, 재무 특징에서 첫 개선 확인) |
| [시장 데이터 및 시점 정책](../spec/market-data-policy.md) | `docs/spec/market-data-policy.md` | 승인 |
| [모의투자·실전투자 전환 게이트](../spec/paper-to-live-gate.md) | `docs/spec/paper-to-live-gate.md` | 승인 |
| [제품 범위 및 요구사항](../spec/product-scope.md) | `docs/spec/product-scope.md` | 승인 |
| [거래 안전 정책](../spec/trading-safety-policy.md) | `docs/spec/trading-safety-policy.md` | 승인 |
