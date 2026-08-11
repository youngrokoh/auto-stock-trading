# 내부 상태 확인 API

- 상태: 구현됨
- 작성일: 2026-08-11
- 기본 경로: `/api/health`

## 엔드포인트

| 메서드 | 경로 | 성공 의미 | 장애 시 HTTP 상태 | 사용처 |
|---|---|---|---|---|
| GET | `/live` | API 프로세스가 요청을 처리함 | 프로세스가 없으면 연결 실패 | 프로세스 생존 확인 |
| GET | `/ready` | PostgreSQL과 Valkey가 모두 연결됨 | `503` | Caddy·컨테이너 준비성 검사 |
| GET | `/status` | 현재 구성요소 상태를 응답함 | API 자체 오류가 아니면 `200` | 브라우저 대시보드 |

`/ready`와 `/status`의 본문 계약은 같다. 브라우저는 정상적으로 처리된 `degraded` 상태를 콘솔 네트워크 오류로 기록하지 않도록 `/status`를 사용한다.

## 응답 예시

```json
{
  "components": [
    { "name": "PostgreSQL", "status": "ok" },
    { "name": "Valkey", "status": "unavailable" }
  ],
  "environment": "development",
  "service": "api",
  "status": "degraded",
  "version": "0.1.0"
}
```

허용된 구성요소 상태는 `ok`, `unavailable`이다. 전체 상태는 `ready`, `degraded`다. 연결 URL, 사용자명, 암호, 계좌정보, 원본 예외는 응답에 포함하지 않는다.

프론트엔드는 응답을 Zod strict object로 파싱한다. 계약에 없는 필드가 있으면 상태 데이터를 화면에 사용하지 않는다.
