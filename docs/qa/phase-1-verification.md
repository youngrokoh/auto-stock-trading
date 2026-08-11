# 1단계 검증 기록

- 상태: 기술 검증 통과 · 시각 디자인 사용자 미승인
- 검증일: 2026-08-11
- 대상: 프로젝트 기반, 상태 API, 빈 운영 대시보드

이 문서의 브라우저 및 시각 검증 통과는 프로토타입의 구현 품질을 의미한다. 현재 색상, 레이아웃과 화면 방향에 대한 사용자 승인을 의미하지 않는다.

## 자동 검사 결과

| 범위 | 검사 | 결과 |
|---|---|---|
| 백엔드 | Ruff lint·format | 통과 |
| 백엔드 | basedpyright strict | 오류 0 |
| 백엔드 | pytest | 6개 통과 |
| 마이그레이션 | Alembic 오프라인 PostgreSQL SQL 생성 | 통과 |
| 프론트엔드 | Biome | 통과 |
| 프론트엔드 | TypeScript project build | 통과 |
| 프론트엔드 | Vitest | 3개 통과 |
| 프론트엔드 | Vite production build | 통과 |
| 프론트엔드 | React Doctor | 100/100 |
| 브라우저 | Playwright 2개 시나리오 × 3개 뷰포트 | 6개 통과 |
| 인프라 | Compose 구성·PostgreSQL 18 볼륨·Caddy CSP 계약 | 통과 |
| 통합 | PostgreSQL·Valkey·migration·API·worker·Caddy web | 전체 기동 통과 |
| 영속성 | Compose `down` 후 PostgreSQL·Valkey 표식 복구 | 통과 |
| 문서 | docs guard와 링크 검사 | 통과 |

백엔드는 Python 3.14.6, 프론트엔드는 Bun 1.3.14와 Vite 8.1.5에서 검증했다.

## 수동 API 확인

- `GET /api/health/live`: `200`, `status=ok`
- `GET /api/health/ready`: `200`, PostgreSQL·Valkey 모두 `ok`
- `GET /api/health/status`: `200`, `status=ready`
- Caddy 경유 `GET http://localhost:8080/api/health/ready`: `200`
- Alembic 버전 `20260811_0001`, migration 컨테이너 종료 코드 `0`
- Valkey `PING`: `PONG`

Colima의 Docker Engine에서 전체 Compose 환경을 실제로 기동했다. PostgreSQL 18은 버전별 데이터 디렉터리 구조를 사용하므로 named volume을 `/var/lib/postgresql`에 연결한다. `down` 후 같은 볼륨으로 재기동하여 PostgreSQL과 AOF가 활성화된 Valkey의 임시 검증 표식이 모두 유지됨을 확인했으며, 확인 후 표식은 제거했다.

Taskiq worker는 redis-py의 기본 읽기 타임아웃이 블로킹 `BRPOP`을 끊지 않도록 `socket_timeout=None`으로 구성했다. 수정 전에는 유휴 worker가 약 5초마다 종료·재생성됐고, 수정 후 두 worker 프로세스가 같은 임계 시간을 넘겨 오류와 재시작 없이 유지됐다.

## 브라우저 확인

검증 뷰포트는 375×812, 768×1024, 1280×900이다. Compose의 `http://127.0.0.1:8080`을 실제 Chromium headed 모드로 열어 각 뷰포트에서 대시보드와 `/showcase`를 모두 확인했다.

- 실전거래 비활성 상태가 첫 화면과 안전 패널에 표시된다.
- API, PostgreSQL, Valkey 상태가 실제 상태 응답에 따라 표시된다.
- 페이지 가로 오버플로가 없다.
- 브라우저 본문에 `postgresql://`, `redis://` 연결 문자열이 없다.
- 브라우저 콘솔 오류가 없다.
- Caddy CSP가 `script-src`와 `style-src`를 포함해 브라우저 fallback 경고를 발생시키지 않는다.
- 가짜 가격, 수익률, 차트, 주문·포지션 건수를 표시하지 않는다.
- 한국어 문장 분리, 잘림, 대체 글리프가 없다.

독립 시각 QA 두 건은 동일한 캡처 세트를 기준으로 수행하며, 판정과 캡처 해시는 [시각 QA 감사 기록](phase-1-visual-review.md)에 남긴다.

## 화면 증거

### Dashboard

- [모바일](evidence/phase-1/dashboard-mobile.png)
- [태블릿](evidence/phase-1/dashboard-tablet.png)
- [데스크톱](evidence/phase-1/dashboard-desktop.png)

### Primitive showcase

- [모바일](evidence/phase-1/showcase-mobile.png)
- [태블릿](evidence/phase-1/showcase-tablet.png)
- [데스크톱](evidence/phase-1/showcase-desktop.png)
