# ADR-0002: Python·React 기술 기준선 채택

- 상태: 승인
- 결정일: 2026-08-11

## 배경

프로젝트는 증권사 API 연동과 주문 안정성뿐 아니라 재무·시계열 분석, 머신러닝, 웹 대시보드를 함께 구현해야 한다. 분석 생태계와 타입 안전성, 개발 속도, 운영 단순성을 모두 고려해야 한다.

## 결정

- 백엔드는 Python 3.14, FastAPI, Pydantic v2, SQLAlchemy 2 async를 사용한다.
- 데이터 처리는 Polars와 DuckDB를 사용한다.
- 프론트엔드는 React 19.2, TypeScript, Vite 8.1을 사용한다.
- Python 패키지는 uv, TypeScript 패키지는 Bun으로 관리한다.
- Python은 Ruff와 basedpyright, TypeScript는 Biome와 엄격한 `tsc`를 품질 게이트로 사용한다.
- API 계약은 FastAPI OpenAPI에서 TypeScript 클라이언트 타입을 생성한다.

## 대안

### 전체 TypeScript

웹 개발은 단순하지만 시계열 분석과 머신러닝 생태계가 Python보다 불리하므로 채택하지 않는다.

### Python 템플릿 기반 단일 웹

대규모 대시보드 상호작용과 차트 상태 관리에 제약이 있어 채택하지 않는다.

### Next.js 풀스택

공개 콘텐츠의 SEO나 서버 렌더링 필요성이 없고 Python 분석 계층이 별도로 필요하므로 초기 복잡도만 증가한다.

## 결과

- 금융 분석과 ML 라이브러리를 직접 사용할 수 있다.
- 프론트엔드와 백엔드의 런타임 경계가 명확하다.
- OpenAPI 타입 생성으로 계약 중복을 줄일 수 있다.
- 두 언어의 도구 체인을 CI에서 각각 관리해야 한다.

## 재검토 조건

- 프론트엔드에 SSR 또는 SEO 요구가 생긴다.
- Python 런타임이 실시간 처리 성능의 측정된 병목이 된다.
- 분석 기능이 독립 서비스로 분리된다.
