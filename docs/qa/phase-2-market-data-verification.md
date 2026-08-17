# 2단계 시장 데이터 수직 슬라이스 검증

- 상태: 자동·로컬 통합·실제 KIS 모의환경·실전 달력 읽기·실제 KRX 일정·scheduler·실제 DART 배당·KODEX 분배금 수집·락일 확정·일봉 재조회 확정·실제 수정주가 발행 검증 완료, 사용자 화면 대조 대기
- 기준일: 2026-08-17
- 대상: KIS 인증·종목정보·현재가·비수정 일봉·시장 달력·DART 기업행사·PostgreSQL·읽기 API
- 관련 API: [시장 데이터 읽기 API](../api/market-data-api.md)

## 검증 범위

| 영역 | 검증 방법 | 판정 |
|---|---|---|
| 프로세스 내부 KIS 토큰 캐시와 만료 후 갱신 | HTTP fake와 공식 형태 fixture | 통과 |
| 프로세스 간 토큰 단일 발급·만료 여유·잠금 복구 | 실제 Valkey와 두 독립 coordinator | 통과 |
| 프로세스 간 모의 REST 호출 간격 | 실제 Valkey 동시 예약 | 통과 |
| Valkey 장애 시 KIS 호출 차단 | 연결 실패와 issuer 미호출 검사 | 통과 |
| 주식·ETF 응답 정규화 | 삼성전자·KODEX 200 fixture | 통과 |
| 비수정 일봉 요청 | `FID_ORG_ADJ_PRC=1` 요청 검사 | 통과 |
| 한국 시장 날짜 경계 | UTC 수신시각을 `Asia/Seoul` 날짜로 변환 | 통과 |
| 실패 기록과 재실행 | PostgreSQL 통합 테스트 | 통과 |
| 반복 수집 멱등성 | 정규화 행 수와 원본 append-only 행 수 검사 | 통과 |
| 기존 실제 데이터와 테스트 격리 | 대상 fixture를 테스트 트랜잭션에서 초기화한 뒤 롤백 | 통과 |
| 읽기 전용 API | FastAPI 계약 테스트와 실제 HTTP 호출 | 통과 |
| 비밀정보 경계 | 오류 문자열과 로그 필드 검사 | 통과 |
| 모의전용 Docker secret 전달 | 파일 기반 키 로딩과 `paper` 강제 Compose override | 통과 |
| 모의투자 호출 제한 | 기본 요청 간격 1.05초 검사 | 통과 |
| 모의환경 미지원 종목 상세 TR 우회 | 일봉 요약으로 최소 종목정보 구성 | 통과 |
| 실제 KIS 모의환경 | 로컬 모의 키 반복 수집, 공유 토큰 재사용과 DB·API 확인 | 통과 |
| 시장 달력 스키마와 불변조건 | Alembic offline SQL과 PostgreSQL 적용 | 통과 |
| 정상·휴장·단축장과 fail-closed 판정 | 도메인 테스트 | 통과 |
| 동일 사실 재수신과 정정 버전 보존 | PostgreSQL 통합 테스트 | 통과 |
| KRX 우선순위와 KIS 충돌 차단·오류 기록 | PostgreSQL 통합 테스트 | 통과 |
| 현재 범위와 다음·이전 거래일 조회 | PostgreSQL 통합 테스트 | 통과 |
| KRX OTP·연간 휴장일 응답 계약 | 공식 응답 형태 fixture와 HTTP fake | 통과 |
| KRX 전체 날짜 정규화·범위 원자 저장 | fixture와 PostgreSQL 배치 통합 테스트 | 통과 |
| 실제 KRX 2026 연간 일정 | 공식 `[01023]` 외부 응답·PostgreSQL 직접 조회 | 통과 |
| KRX 임시 거래시간 공지·PDF 계약 | 수능일·연초 개장일 fixture, HTTP fake와 미지원 형식 실패 | 통과 |
| 실제 KRX 임시 거래시간 공지 | 2025 수능일·2026 연초 개장일 공식 PDF 직접 호출 | 통과 |
| KIS `CTCA0903R` 당일 `opnd_yn` 확인 | 공식 응답 형태 fixture와 HTTP fake | 통과 |
| KIS 달력 확인의 모의환경 차단 | worker 설정 경계 테스트 | 통과 |
| 서울 기준 Taskiq 예약과 기본 비활성 | 예약 라벨·설정 경계 테스트 | 통과 |
| scheduler 중복 실행·실패 회수 | PostgreSQL claim 통합 테스트 | 통과 |
| 단일 scheduler와 KRX 전용 활성화 | Compose 프로필·비밀정보 계약과 실제 컨테이너 기동 | 통과 |
| 실제 KIS 실전 달력 확인 | 분리된 실전 키로 읽기 전용 1회 호출과 DB 상태 확인 | 통과 |
| KIS 자동 확인 활성화 경계 | 전용 Compose override의 worker secret·scheduler 플래그 분리 | 통과 |
| 비수정 일봉 버전 마이그레이션 | 기존 행의 버전 1·검증 대기 상태·유효시각 이관 직접 조회 | 통과 |
| 동일 일봉 재수신·확정·정정 | PostgreSQL 트랜잭션 통합 시나리오와 현재 버전 조회 | 통과 |
| 일봉 버전·확정 상태 API | FastAPI 응답 계약 테스트 | 통과 |
| KIS 앱 화면 값 대조 | 사용자의 모의투자 화면과 육안 비교 | 대기 |

## 테스트 데이터 근거

fixture는 한국투자증권 공식 `open-trading-api` 저장소의 2026-08-14 기준 커밋 `b093e42ba32d1df5f5ddad7a71cb715cbc800832`에 있는 인증, 국내주식 종목정보, 현재가, 기간별 일봉 샘플의 필드와 TR ID를 기준으로 작성했다.

- 인증: `/oauth2/tokenP`
- 종목정보: `CTPF1002R`
- 현재가: `FHKST01010100`
- 기간별 일봉: `FHKST03010100`
- 국내휴장일조회: `CTCA0903R`, `/uapi/domestic-stock/v1/quotations/chk-holiday`

fixture 값은 계약 테스트용 예시이며 실제 현재 시세로 해석하지 않는다.

KRX 연간 fixture는 [KRX 공식 휴장일 화면](https://global.krx.co.kr/contents/GLB/05/0501/0501110000/GLB0501110000.jsp)의 2026년 응답 필드 `block1`, `calnd_dd`, `calnd_dd_dy`, `dy_tp_cd`, `kr_dy_tp`, `holdy_eng_nm`을 기준으로 했다. 임시 거래시간 fixture는 [KRX 보도자료](https://open.krx.co.kr/contents/OPN/05/05000000/OPN05000000.jsp)의 2025년 수능일과 2026년 연초 개장일 공식 PDF에서 주식·ETF 정규장 대상일과 변경 전·후 시간 부분을 축약해 작성했다.

## 자동 검증 명령

```bash
cd backend
uv run ruff check src tests migrations
uv run ruff format --check src tests migrations
uv run basedpyright
uv run pytest
uv run alembic upgrade head

cd ..
bash tests/infra-compose-test.sh
python3 scripts/docs_guard.py check
```

2026-08-14 실행 결과:

- Ruff 검사·포맷: 통과
- basedpyright: 오류 0건, 경고 0건
- pytest: 24건 통과
- Alembic `upgrade head`: 통과
- Compose 계약 검사: 통과
- Docker Compose 현재 이미지 빌드와 기동: PostgreSQL·Valkey·API·worker 정상, migration 종료 코드 0
- 모의전용 worker 이미지 빌드와 Docker secret one-off 실행: 통과
- 문서 생성·링크·변경 매핑 검사: 통과

2026-08-16 시장 달력 저장 계층 실행 결과:

- Ruff 검사·포맷: 통과
- basedpyright: 오류 0건, 경고 0건
- pytest: 37건 통과
- Alembic `20260816_0003` PostgreSQL 적용: 통과
- 시장 달력 PostgreSQL 통합 시나리오: 3건 통과
- Python sdist·wheel 빌드: 통과
- Compose·문서 계약 검사: 통과

2026-08-16 KRX·KIS 시장 달력 어댑터 실행 결과:

- Ruff 검사·포맷: 통과
- basedpyright: 오류 0건, 경고 0건
- pytest: 44건 통과
- 시장 달력 PostgreSQL 통합 시나리오: 5건 통과
- Python sdist·wheel과 프론트엔드 프로덕션 빌드: 통과
- KRX 수동 수집과 KIS 실전 전용 확인 함수 조립·모의환경 차단: 통과
- 실제 KRX 2026 일정: 현재 세션 365건, 휴장 121건, 공유 원본 1건
- 실제 KRX 동기화 상태: `success`, 오류 코드 없음, 마지막 성공시각 기록
- `2026-08-14` 정상장, `08-15~16` 주말 휴장, `08-17` 대체휴일, `08-18` 정상장 직접 조회: 통과
- KIS 실전 달력 호출: 실전 자격증명을 검증 경로에 연결하지 않아 미실행

2026-08-16 KRX 임시 거래시간 공지 실행 결과:

- Ruff 검사·포맷과 basedpyright: 통과, 오류·경고 0건
- pytest: 52건 통과
- Python sdist·wheel, Compose·문서 계약 검사: 통과
- 실제 KRX 보도자료 목록·첨부 PDF 호출: 통과

2026-08-16 비수정 일봉 버전 저장 실행 결과:

- Ruff 검사·포맷과 basedpyright: 통과, 오류·경고 0건
- pytest: 69건 통과
- Python sdist·wheel 빌드: 통과
- Alembic `20260816_0005` PostgreSQL 적용: 통과
- 기존 비수정 일봉 20건: 모두 `version=1`, `finality=pending`, `valid_from=received_at`
- 논리 일봉별 현재 행 중복: 0건
- 동일 사실 근거 갱신, 정확히 일치하는 사실 확정, 확정 후 정정 이력 보존과 오래된 정정 차단 통합 시나리오: 4건 통과
- `2025-11-13` 수능일 정규장 `10:00~16:30` 추출: 통과
- `2025-01-02` 과거 연초 PDF의 벡터 범위 글자 누락과 증권상품 구조 보완 판정: 통과
- `2026-01-02` 연초 개장일 정규장 `10:00~15:30` 추출: 통과
- PDF 원문 Base64, 공지 번호와 첨부 메타데이터 원본 계약: 통과
- 미지원 임시 주식시장 공지와 주식·ETF 범위 누락의 fail-closed 처리: 통과
- 실제 2025·2026 worker 적재 후 세 날짜의 `shortened` 상태·서울 시각·공지 출처 DB 조회: 통과

2026-08-16 시장 달력 scheduler 실행 결과:

- Alembic `20260816_0004` PostgreSQL 적용: 통과
- PostgreSQL claim의 유효 lease 중복 차단, 실패 재시도, 만료 lease 회수, 소유권 상실과 성공 종결 시나리오: 통과
- Taskiq KRX 예약 2개가 `Asia/Seoul`과 고정 schedule ID로 등록되고 KIS 예약은 기본 비활성: 통과
- Compose `calendar-scheduler` 프로필 빌드·기동 후 단일 scheduler 프로세스 확인: 통과
- 수동 KRX CLI 첫 실행에서 시장 달력 원본 2건 추가, claim `succeeded`·시도 1회 기록: 통과
- 같은 날짜·연도의 두 번째 CLI에서 원본 건수와 시도 횟수가 유지되어 외부 호출 건너뛰기 확인: 통과
- Ruff 검사·포맷, basedpyright, pytest 65건, Python sdist·wheel, Compose·문서 계약 검사: 통과
- KIS 자동 확인은 사용자 활성화 전까지 비활성: 대기

2026-08-16 KIS 실전 읽기 전용 달력 확인 결과:

- 실전 App Key·Secret은 모의 키와 다른 `.secrets/` 파일에 저장하고 두 파일 모두 권한 `0600` 확인
- 주문·계좌 API 없이 `CTCA0903R` `/uapi/domestic-stock/v1/quotations/chk-holiday`만 1회 호출: 통과
- 응답 `rt_cd=0`, 요청일 `20260816`, `opnd_yn=N`, `bzdy_yn=N`, `tr_day_yn=Y`: 계약 통과
- KRX `closed|pending|v1`과 일치해 `closed|confirmed|v1`로 전환: 통과
- `operations.api_sync_status`는 `success`, 오류 코드 없음: 통과
- 영속 claim은 `succeeded`, 시도 1회, 논리 키 `kis-calendar:XKRX:2026-08-16:v1`: 통과
- 저장 원본의 `access_token`, `appkey`, `appsecret` 최상위 필드: 0건
- 같은 CLI 재실행 후 KIS 원본 1건과 claim 시도 1회가 유지되어 외부 중복 호출 차단: 통과

2026-08-16 KIS 자동 확인 활성화 결과:

- 사용자가 실전 읽기 전용 검증 결과를 확인한 뒤 자동 확인 플래그 활성화를 명시적으로 승인
- `compose.kis-live-calendar.yaml` 병합 시 worker 환경은 `live`, KIS 예약 활성화, 실전 secret 파일 경로 사용: 통과
- worker에 마운트되는 secret은 `kis_live_app_key`, `kis_live_app_secret` 두 개뿐임: 통과
- scheduler는 KRX·KIS 예약 활성화와 `live` 환경을 받고 secret 마운트는 0개: 통과
- worker와 scheduler의 `restart: unless-stopped` 복구 정책: 통과
- 기본 Compose와 모의 override는 KIS 자동 확인 비활성 상태 유지: 통과
- 전용 override로 worker·scheduler 이미지를 실제 빌드·기동하고 두 컨테이너 `running` 확인: 통과
- worker 내부 실전 secret 두 파일의 권한 `0600`, scheduler 내부 실전 secret 파일 0개: 통과
- 실제 scheduler 모듈에서 서울 기준 KIS 예약 3개와 KRX 예약 2개 등록 확인: 통과
- 두 컨테이너의 Docker 재시작 정책 `unless-stopped` 적용 확인: 통과

저장소 통합 테스트는 현재 로컬 Compose의 PostgreSQL 18에 실제 리비전을 적용한 뒤 테스트 트랜잭션을 롤백하는 기존 프로젝트 방식을 따른다. 기술 스택에 정의된 Testcontainers 기반 테스트별 격리는 아직 도입하지 않았다.

2026-08-14 모의검증 준비 런타임 관찰:

- 실제 키 대신 저장소의 가짜 fixture 파일 두 개를 Compose secret 원본으로 지정했다.
- `compose.kis-paper.yaml` one-off worker 안에서 환경이 `paper`로 고정됨을 확인했다.
- 직접 자격증명 환경변수는 `None`인 상태에서 `/run/secrets` 파일로 두 값을 읽었다.
- 키 내용은 명령행 인자, Compose 환경과 출력에 노출하지 않았다.
- 이 관찰은 비밀정보 전달 경로에 대한 증거이며 실제 KIS 외부 호출 성공을 뜻하지 않는다.

## 실제 KIS 모의환경 관찰

사용자는 2026-08-14에 모의투자와 실전투자 키 발급을 완료했고 모의 키만 로컬 `.secrets/`에 저장했다. 파일 존재·비어 있지 않음·권한 `0600`만 관찰했으며 애플리케이션이 값을 로드해 인증에 사용하되 키 자체는 출력하거나 기록하지 않았다. 실전 키는 검증 경로에 연결하지 않았다.

첫 실제 호출에서 인증은 성공했지만 종목 상세 `CTPF1002R`이 HTTP `500`, `EGW02006`, `모의투자 TR 이 아닙니다.`를 반환했다. 같은 토큰으로 현재가 `FHKST01010100`과 일봉 `FHKST03010100`은 모두 `200`, `MCA00000`이었다. 공식 샘플과 요청 계약을 대조한 결과 요청 오류가 아니라 모의환경 미지원 TR로 확정했고, 실패 테스트를 먼저 추가한 뒤 모의환경에서는 일봉 요약으로 최소 종목정보를 구성하도록 수정했다.

수정한 worker 이미지의 `2026-08-01`부터 `2026-08-14`까지 첫 수집 결과:

| 데이터 | 행 수 |
|---|---:|
| 종목 | 2 |
| 최신 현재가 | 2 |
| 비수정 일봉 | 20 |
| 원본 응답 | 4 |
| 성공 상태 | 2 |

삼성전자와 KODEX 200은 각각 10개 거래일, `2026-08-03`부터 `2026-08-14`까지 저장됐다. 같은 범위의 두 번째 성공 수집 후 종목 2, 최신 현재가 2, 일봉 20, 성공 상태 2는 유지됐고 원본 응답만 8로 증가했다.

독립 컨테이너를 즉시 재실행했을 때 새 프로세스의 토큰 발급이 HTTP `403`으로 한 번 거절됐다. 추가 호출을 반복하지 않고 보호 구간 이후 한 번 재실행해 성공했다. 이 관찰을 근거로 ADR-0005를 승인하고 Valkey 기반 프로세스 간 토큰 재사용과 호출 게이트를 구현했다.

구현 후 첫 독립 worker가 실제 KIS 수집을 완료하고 Valkey에 공유 토큰을 저장했다. 다음 독립 worker는 `KIS shared access token reused`를 기록했으며 `/oauth2/tokenP` 없이 현재가·일봉 GET 4건을 모두 `200`으로 완료했다. 두 번 추가 수집 후 종목 2, 최신 현재가 2, 일봉 20, 성공 상태 2는 유지됐고 누적 원본 응답은 16건이었다. 공유 토큰 항목은 1개, 원본 payload의 인증 필드는 0건, Valkey 호스트 포트는 `127.0.0.1:6379`였다.

실제 FastAPI `:8000` 관찰:

- 종목정보: `200`, `symbol=005930`, `name=삼성전자`, `product_type=stock`, `source=KIS`
- 현재가: `200`, KRW Decimal 문자열, UTC `as_of`·`received_at`, `source=KIS`
- 일봉: `200`, 10건, `2026-08-03`부터 `2026-08-14`, 모두 `adjusted=false`, `source=KIS`
- 원본 payload 최상위 인증 필드 `access_token`, `appkey`, `appsecret`: 0건

## 실제 OpenDART 배당 수집 검증 (2026-08-17)

사용자가 발급한 OpenDART 인증키를 `.secrets/dart-api-key`(권한 `0600`, Git 제외)에 저장하고 실제 API로 삼성전자 `005930`의 `2026-01-01`부터 `2026-08-17`까지 현금배당 공시를 수집했다. 키 값은 요청에만 사용했고 채팅 밖의 문서·Git·로그에 기록하지 않는다.

첫 수집 결과:

| 항목 | 값 |
|---|---|
| 수집된 기업행사 | 현금배당 3건, 모두 `version=1`, `announced`, `pending` |
| 결산배당 | 접수 `2026-01-29`, 기준일 `2025-12-31`, 주당 566원, 지급일 미정(`-`→NULL) |
| 1분기 배당 | 접수 `2026-04-30`, 기준일 `2026-03-31`, 주당 372원, 지급일 `2026-05-29` |
| 2분기 배당 | 접수 `2026-07-30`, 기준일 `2026-06-30`, 주당 374원, 지급일 `2026-08-28` |
| 원본 응답 | 공시검색 목록 28페이지 + 원본 문서 3건 = 31건 append-only |
| 동기화 상태 | `DART`/`corporate_actions`/`005930` `success`, 오류 코드 없음 |
| 원본·지문 내 인증키 | 0건 |

같은 범위를 즉시 재수집한 결과 사실 행은 3건·버전 1로 유지됐고 원본 응답만 62건으로 늘었다. 2분기 공시 `20260730800137`은 공개 DART 뷰어 원문과 분기배당·현금배당·주당 374원·기준일 `2026-06-30`·지급 예정일 `2026-08-28`이 일치함을 확인했다. 이 검증은 배당락일을 저장하지 않으므로 세 사실 모두 계산 조건 미충족 `pending`이며, 배당락일 확정은 후속 단계다.

## 실제 KODEX 분배금 수집 검증 (2026-08-17)

삼성자산운용 KODEX 공식 분배금 데이터에서 KODEX 200 `069500`의 `2024-01-01`부터 `2026-08-17`까지 분배금을 인증 없이 수집했다.

| 항목 | 값 |
|---|---|
| 수집된 기업행사 | `etf_distribution` 11건, 모두 `version=1`, `confirmed`, `pending` |
| 기간 | 지급기준일 `2024-01-31`부터 `2026-07-31`까지 분기별 |
| 최근 사실 | 기준일 `2026-07-31`, 세전 주당 183원, 실지급일 `2026-08-04` |
| 원본 응답 | 분배 이력 JSON 1건, 11개 사실이 같은 원본을 공유 |
| 동기화 상태 | `KODEX`/`corporate_actions`/`069500` `success`, 오류 코드 없음 |

같은 범위를 즉시 재수집한 결과 사실 행은 11건·버전 1로 유지됐고 원본 응답만 2건으로 늘었다. 기준일 `2026-07-31`의 주당 183원은 운용사 공식 '26.7월 월말배당 공지문(공지 78273, `069500 | KODEX 200 | 0.19% | 183`)과 일치함을 확인했다. 분배락일은 저장하지 않으므로 계산 조건은 미충족 상태다. KRX 정보데이터시스템 `getJsonData`는 TLS 위장·세션·Referer를 갖춰도 `LOGOUT`을 반환하는 화면 종속 게이트가 있어 자동 수집 출처에서 제외했다.

## 실제 배당락일 확정과 수정주가 생성 경계 검증 (2026-08-17)

사용자가 승인한 규칙 기반 도출(`배당락일 = 기준일 이전 마지막 거래일의 직전 거래일`, 검증된 `XKRX` 달력만 사용)을 실제 DB에 적용했다.

| 대상 | 결과 |
|---|---|
| 삼성전자 결산배당 (기준일 `2025-12-31`, 연말휴장) | 락일 `2025-12-29`, `verified` v2 |
| 삼성전자 1·2분기 배당 | 락일 `2026-03-30`, `2026-06-29`, `verified` v2 |
| KODEX 200 분배금 2025년 1월 (설연휴 `01-27`~`01-30`) | 락일 `2025-01-24`, `verified` v2 |
| KODEX 200 분배금 2025~2026년 나머지 6건 | 기준일 직전 거래일로 확정, `verified` v2 |
| 2024년 분배금 4건 | 달력 미수집으로 확정하지 않고 `pending` 유지 (fail-closed) |

연말휴장과 설연휴를 달력 기반으로 정확히 건너뛰었고, 확정 재실행은 새 버전을 만들지 않았다.

수정주가 데이터셋 실데이터 생성은 KODEX 200 `2026-08-03`~`2026-08-14` `total_return` 요청이 미확정 일봉 때문에 `failed`(`unconfirmed_bar_in_range`)로 차단됨을 확인했다. 계약의 "미확정 일봉 발행 금지"가 실데이터에서 동작하며, 이 실패 기록은 이후 발행 뒤에도 보존된다. 계산·해시·point-in-time·정정 시나리오는 고정 fixture와 PostgreSQL 통합 테스트로 검증했다.

## 실제 일봉 재조회 확정과 수정주가 발행 검증 (2026-08-17)

실제 KIS 모의환경에서 `2026-07-01`~`2026-08-14` 일봉을 수집한 뒤 `--confirm-daily-bars`로 재조회했다.

| 항목 | 값 |
|---|---|
| 확정된 일봉 | 삼성전자 32개, KODEX 200 32개 — 전량 `confirmed` |
| 확정 근거 | 서울 15:40 이후의 저장 관측과 재조회 응답 일치 (두 관측 모두 종가 확정 이후) |
| 발행된 데이터셋 | KODEX `total_return`(분배락 반영)·`split_adjusted`, 삼성전자 `total_return` — `published`, 각 32개 수정 일봉 |
| 분배락 반영 | 사건일 `2026-07-30`, 가격계수 `0.9979577032531667` = (89605−183)/89605 |
| 수정 종가 대조 | 락일 직전 `2026-07-29` 수정 종가 `89422` = 원주가 89605 − 분배금 183, 락일 이후 계수 1 |
| 계보 | 데이터셋 → 비수정 일봉 버전(`source_bar_id`)과 기업행사 버전(`adjustment_dataset_action`) 연결 확인 |

`knowledge_cutoff_at`이 다른 반복 발행은 계약대로 별도 point-in-time 데이터셋을 만든다. 재현 가능한 발행이 필요하면 worker의 `--knowledge-cutoff`로 지식 기준시각을 고정한다. KIS 수정주가와의 대조(계약 검증 시나리오 9)는 현재 종목의 사건이 현금 분배뿐이라 KIS 수정주가와 원주가의 차이가 없을 것으로 예상되므로, 액면분할 이력이 있는 종목을 수집 대상에 추가할 때 수행한다.

## 실제 수정주가 읽기 API 검증 (2026-08-17)

로컬 API 서버를 실제 PostgreSQL에 연결하고 새 읽기 엔드포인트를 실데이터로 확인했다.

| 항목 | 값 |
|---|---|
| 최신 발행 조회 | `GET /instruments/069500/adjusted-daily-bars?method=total_return` → `published` 데이터셋, 32개 수정 일봉 |
| 계약 필수 필드 | `method`, `range_start`, `price_cutoff_date`, `knowledge_cutoff_at`, `algorithm_version=krx-t2-adjust-v1`, 두 입력 해시, 데이터셋 ID 모두 응답에 포함 |
| 계수·종가 대조 | `2026-07-29` 수정 종가 `89422`, 가격계수 `0.9979577032531667` — 발행 검증 값과 일치 |
| 계보·출처 | 일봉마다 `source=KIS`, `source_bar_id`, `source_bar_version=1`, 반영 기업행사 `action_version=2`·`source=KODEX` 노출 |
| 기업행사 조회 | 현재(069500 분배금 1건 `verified`, 005930 2026년 배당 2건 `verified`), `include_history`로 `pending`→`verified` 두 버전 확인 |
| point-in-time | 수집 시각(02:26 UTC) 이전 `knowledge_cutoff_at`은 빈 결과 — 미래정보 누출 없음 |
| 데이터셋 ID·영향 조회 | ID 조회와 `corporate-actions/{action_key}/adjusted-datasets`가 동일 사실 버전을 반영한 발행 이력 반환 |
| 오류 처리 | 미등록 종목·미지 데이터셋 `404`, 잘못된 `method`·시간대 없는 cutoff·`include_history`+cutoff 조합 `422` |

락일 확정 전 버전은 `ex_date`가 없어 기간 필터에 나타나지 않으므로 이력 검증은 기간 없는 조회로 수행했다. 응답에는 자격증명이나 연결 URL이 없다.

## 남은 사용자 확인

KIS 모의투자 앱 또는 웹 화면에서 삼성전자와 KODEX 200의 값과 마지막 거래일을 육안 대조한다. 기술 검증과 원본 보안 검증은 완료됐으며 화면 대조 결과에는 시세 전문이나 키를 기록하지 않는다.
