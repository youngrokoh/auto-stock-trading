# Auto Stock Trading

국내 주식·ETF 데이터 수집, 기업 분석, 퀀트 전략 연구와 안전한 자동매매 실행을 단계적으로 구축하는 웹 프로젝트다. 현재 KIS 시세·비수정 일봉·분봉·상장주식수·투자자별 수급·ETF 마스터·NAV, `XKRX` 시장 달력, 기업행사·수정주가 데이터셋, OpenDART 재무제표·재무 지표·공시 목록의 수집·버전 저장·읽기 API, 그리고 승인 디자인(Research Grid + Night Watch)으로 구현한 운영 개요·시장 데이터·기업 분석·ETF 탐색 화면을 제공한다.

> 웹 화면은 승인된 [클로드 화면 디자인 사양](design/claude-design/screen-design-spec.md)의 토큰·프리미티브로 구현되어 있다. 다음 작업과 구현 상태는 [현재 프로젝트 상태와 다음 세션 인계](plan/current-status.md)를 기준으로 한다.

## 현재 구현 범위

- FastAPI 생존·준비 상태 API
- PostgreSQL 18 마이그레이션과 Valkey 작업 큐
- Valkey 공유 KIS 토큰·호출 게이트와 대표 주식·ETF 시장 데이터 수집 Taskiq worker
- 원본 응답과 정규화 데이터를 분리한 PostgreSQL 저장소
- 종목정보·최신 현재가·버전·확정 상태가 포함된 비수정 일봉 읽기 API
- 동일 사실 재수집과 정정 이력을 구분해 보존하는 비수정 일봉 저장소
- KRX 공식 일정과 KIS 당일 확인을 결합한 버전형 `XKRX` 시장 달력과 Taskiq scheduler
- 검증된 세션 창 기반 비수정 1분봉 수집·재관측 확정
- DART·KODEX 공식 자료 기반 기업행사 사실 버전과 수정주가 파생 데이터셋
- OpenDART 재무제표(연결·개별) 사실 버전 수집과 읽기 API
- 수식·기준·접수번호 출처를 명시한 재무·가치 지표와 상장주식수 버전 사실
- KIS 투자자별 수급(당일 제외 버전 사실)과 DART 공시 목록 수집·읽기 API
- KIS 공식 마스터 파일 기반 국내 ETF 전체 목록과 NAV·괴리율 스냅샷·분배율
- 승인 디자인으로 구현한 운영 개요·시장 데이터·기업 분석·ETF 탐색 화면(캔들·보조지표·실적 차트, 좌표 셀, 안전 배너)
- 결정적 백테스트 엔진과 전략 연구 화면
- 승인된 안전 정책 한도를 코드로 표현한 결정적 위험검사와 모의투자 주문 계획(주문 제출 없음)
- 모바일·태블릿·데스크톱(390/768/1360px) Playwright 검증
- 코드와 문서 변경을 함께 검사하는 문서 동기화 게이트

계좌 조회·목표 포지션·위험검사·주문 계획까지 구현했고 증권사 주문 제출과 AI 모델은 아직 구현하지 않았다. 실전거래는 승인된 [전환 게이트](spec/paper-to-live-gate.md)를 통과하기 전까지 비활성 상태를 유지한다.

## 실행

Docker와 Colima가 준비된 macOS 환경에서는 저장소 루트에서 실행한다.

```bash
docker compose -f infra/compose.yaml up --build -d --wait --wait-timeout 300
```

- 웹: `http://localhost:8080`
- API 준비 상태: `http://localhost:8000/api/health/ready`

도구 설치, 개별 프로세스 실행과 품질 검사 명령은 [로컬 개발과 실행](operations/local-development.md)을 따른다. 전체 구조와 기술 선택은 [프로젝트 실행 구조](architecture/project-structure.md)와 [상세 기술 스택](architecture/tech-stack.md)에 기록한다.

## 구조

```text
Caddy + React
      │ /api
   FastAPI ── PostgreSQL
      │
Taskiq worker ── Valkey
```

## 문서 관리

이 디렉터리는 `auto-stock-trading` 프로젝트에서 생성하는 모든 문서의 단일 저장 위치다.

### 문서 관리 원칙

- 프로젝트 문서는 반드시 `docs/` 또는 그 하위 디렉터리에 저장한다.
- 프로젝트 루트나 소스 디렉터리에 별도의 기획·설계 문서를 만들지 않는다.
- 문서는 내용의 성격에 맞는 카테고리 디렉터리에 저장한다.
- 파일 이름은 소문자 kebab-case를 사용한다.
- 새 문서를 추가하거나 이동하면 이 색인의 링크도 함께 갱신한다.
- 계획이나 명세가 변경되면 새 문서를 중복 생성하기보다 기존 문서의 변경 이력을 남기고 갱신한다.
- API 키, 계좌번호, 토큰, 개인정보는 문서에 기록하지 않는다.

### 카테고리

| 디렉터리 | 용도 |
|---|---|
| `plan/` | 구현 순서, 마일스톤, 작업 계획 |
| `spec/` | 제품 요구사항, 기능 범위, 완료 조건 |
| `architecture/` | 시스템·배포·보안 아키텍처 |
| `design/` | UI 디자인 토큰, 컴포넌트 및 상호작용 규칙 |
| `api/` | 내부 API 및 외부 증권사 API 연동 명세 |
| `data/` | 데이터 모델, 지표 정의, 데이터 품질 규칙 |
| `ai/` | 학습 데이터, 모델, 평가 및 운영 명세 |
| `operations/` | 배포, 모니터링, 장애 대응, 백업 |
| `qa/` | 테스트 전략, 검증 시나리오, QA 증거 |
| `decisions/` | 주요 기술·제품 결정 기록(ADR) |
| `governance/` | 문서 정책, 변경 매핑, 승인 절차 |
| `generated/` | 코드와 문서 메타데이터에서 자동 생성된 문서 |

현재는 실제 문서가 있는 카테고리만 생성한다. 새 카테고리는 해당 문서를 처음 추가할 때 만든다.

### 문서 색인

#### Plan

- [현재 프로젝트 상태와 다음 세션 인계](plan/current-status.md)
- [구현 로드맵](plan/implementation-roadmap.md)

#### Spec

- [제품 범위 및 요구사항](spec/product-scope.md)
- [거래 안전 정책](spec/trading-safety-policy.md)
- [시장 데이터 및 시점 정책](spec/market-data-policy.md)
- [모의투자·실전투자 전환 게이트](spec/paper-to-live-gate.md)

#### Architecture

- [상세 기술 스택](architecture/tech-stack.md)
- [프로젝트 실행 구조](architecture/project-structure.md)

#### Design

- [자동매매 운영 UI 디자인 시스템](design/design-system.md)
- [자동매매 웹 디자인 방향 제안](design/design-direction-proposals.md)
- [디자인 시안 생성 프롬프트](design/proposal-generation-prompts.md)
- [화면 디자인 사양](design/claude-design/screen-design-spec.md)
- [화면 구현 요청 안내](design/claude-design/README.md)

#### API

- [내부 상태 확인 API](api/health-api.md)
- [시장 데이터 읽기 API](api/market-data-api.md)
- [기업 재무 읽기 API](api/fundamentals-api.md)
- [백테스트 읽기 API](api/backtest-api.md)
- [모의투자 주문 계획 읽기 API](api/trading-api.md)

#### Data

- [국내 시장 달력 데이터 계약](data/market-calendar-data-contract.md)
- [기업행사·수정주가 데이터 계약](data/corporate-action-adjusted-price-data-contract.md)
- [국내 분봉 데이터 계약](data/minute-bar-data-contract.md)
- [재무제표 데이터 계약](data/financial-statement-data-contract.md)
- [재무 지표 정의 계약](data/financial-indicator-contract.md)
- [수급·공시 연결 데이터 계약](data/investor-flow-disclosure-contract.md)
- [ETF 탐색 데이터 계약](data/etf-exploration-data-contract.md)
- [종목 유니버스·업종 분류 데이터 계약](data/stock-universe-data-contract.md)
- [백테스트·규칙형 전략 계약](data/backtest-strategy-contract.md)
- [주문 계획·위험검사 데이터 계약](data/order-planning-risk-contract.md)
- [주문·위험 이벤트 외부 알림 계약](data/event-notification-contract.md)
- [주문 제출·체결 동기화 계약](data/order-submission-contract.md)
- [실시간 체결통보 계약](data/realtime-fill-notification-contract.md)
- [ML 신호 데이터·모델 계약](data/ml-signal-contract.md)

#### Operations

- [로컬 개발과 실행](operations/local-development.md)
- [KIS 모의환경 검증 런북](operations/kis-paper-verification.md)

#### QA

- [1단계 검증 기록](qa/phase-1-verification.md)
- [1단계 시각 QA 감사 기록](qa/phase-1-visual-review.md)
- [2단계 시장 데이터 수직 슬라이스 검증](qa/phase-2-market-data-verification.md)
- [3단계 시장 대시보드 검증](qa/phase-3-market-dashboard-verification.md)
- [4단계 기업 재무 데이터 검증](qa/phase-4-fundamentals-verification.md)
- [5단계 ETF 탐색 검증](qa/phase-5-etf-verification.md)
- [6단계 백테스트 엔진 검증](qa/phase-6-backtest-verification.md)
- [7단계 주문 계획·위험검사 검증](qa/phase-7-order-planning-verification.md)
- [8단계 ML 신호 검증](qa/phase-8-ml-verification.md)
- [디자인 방향 시안 시각 QA](qa/evidence/design-direction-proposals/visual-qa.md)

#### Decisions

- [ADR-0001: 모듈형 모놀리스 채택](decisions/0001-modular-monolith.md)
- [ADR-0002: Python·React 기술 기준선 채택](decisions/0002-technology-baseline.md)
- [ADR-0003: PostgreSQL 중심 데이터 아키텍처 채택](decisions/0003-data-architecture.md)
- [ADR-0004: AI 신호와 주문 실행 분리](decisions/0004-ai-execution-separation.md)
- [ADR-0005: Valkey 기반 KIS 토큰·호출 조정](decisions/0005-kis-token-and-rate-coordination.md)
- [ADR-0006: 시장 달력 스케줄 실행과 중복 방지](decisions/0006-market-calendar-scheduling.md)
- [ADR-0007: 모의투자 주문 계획과 위험검사 경계](decisions/0007-paper-order-planning-and-risk.md)
- [ADR-0008: 모의투자 주문 제출·체결 동기화 경계](decisions/0008-paper-order-submission.md)
- [ADR-0009: 실시간 체결통보 수신 경계](decisions/0009-realtime-fill-notification.md)
- [ADR-0010: 사람이 확인한 주문 대조 종결](decisions/0010-human-attested-order-reconciliation.md)
- [ADR-0011: 모의투자 주문 정정 경계](decisions/0011-paper-order-revision.md)
- [ADR-0012: ML 신호의 전략 경계](decisions/0012-ml-signal-boundary.md)
- [ADR-0013: 미체결 수량 축소 경계 (부분 취소)](decisions/0013-paper-partial-cancel.md) (승인)
- [ADR-0014: 주문·위험 이벤트 외부 알림 경계](decisions/0014-outbound-event-notification.md) (승인)
- [ADR-0015: 자동 스케줄 주문 제출 경계](decisions/0015-scheduled-order-submission.md) (승인, 구현)
- [ADR-0016: 실주문 신호 원천 경계](decisions/0016-live-signal-source.md) (승인)
- [ADR-0017: 마감 후 재대조와 세션 종료 주문 처리 경계](decisions/0017-post-close-reconciliation-and-session-end.md) (승인)
- [ADR-0018: 사람이 확인한 재조정 문제 해소 경계](decisions/0018-human-resolved-reconciliation-records.md) (승인)

#### Governance

- [문서 동기화 정책](governance/documentation-policy.md)
- [코드-문서 변경 매핑](governance/change-map.yaml)

#### Generated

- [문서 인벤토리](generated/document-inventory.md)
