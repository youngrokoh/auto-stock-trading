# 상세 기술 스택

- 상태: 승인
- 승인일: 2026-08-11
- 관련 계획: [구현 로드맵](../plan/implementation-roadmap.md)
- 관련 명세: [제품 범위 및 요구사항](../spec/product-scope.md)

## 1. 아키텍처 기준

이 프로젝트는 Python 기반 모듈형 모놀리스로 구현한다. 하나의 백엔드 패키지가 도메인과 애플리케이션 로직을 공유하고, API·작업자·스케줄러·실시간 스트림을 별도 프로세스로 실행한다.

```text
Caddy
├─ /api/* -> FastAPI API
└─ /*     -> React 정적 파일

Backend package
├─ API process
├─ Taskiq worker
├─ Taskiq scheduler
└─ WebSocket stream worker

Infrastructure
├─ PostgreSQL
└─ Valkey
```

초기에는 Kubernetes, Kafka, TimescaleDB, Elasticsearch와 마이크로서비스를 도입하지 않는다. 실제 병목이나 운영 요구가 측정된 경우에만 추가한다.

관련 결정: [ADR-0001](../decisions/0001-modular-monolith.md)

## 2. 버전 기준선

2026-08-11 기준 안정 버전을 기준선으로 사용한다. 프로젝트 생성 시 각 패치 버전을 정확히 고정하고 lockfile을 커밋한다. 프리릴리스 버전은 사용하지 않는다.

| 계층 | 선택 | 기준 버전 |
|---|---|---|
| 백엔드 언어 | Python | 3.14.6 |
| API | FastAPI | 0.141.1 |
| 데이터 검증 | Pydantic | 2.13.4 |
| ORM | SQLAlchemy | 2.0.51 |
| 운영 DB | PostgreSQL | 18.4 |
| 작업 브로커 | Valkey | 9.1.1 |
| 작업 실행 | Taskiq | 0.12.4 |
| 외부 HTTP | httpx2 | 2.10.0 |
| 프론트엔드 | React | 19.2.8 |
| 프론트엔드 빌드 | Vite | 8.1.5 |
| TypeScript 도구 | Bun | 1.3.14 |

공식 기준:

- [Python 3.14.6](https://www.python.org/downloads/release/python-3146/)
- [PostgreSQL 버전 지원 정책](https://www.postgresql.org/support/versioning/)
- [React 최신 버전](https://react.dev/versions)
- [Vite 지원 버전](https://vite.dev/releases)

## 3. 백엔드

### 3.1 런타임과 웹 API

| 역할 | 기술 |
|---|---|
| 패키지 관리 | uv |
| 웹 API | FastAPI |
| 경계 데이터 파싱 | Pydantic v2 |
| 환경 설정 | pydantic-settings |
| 비동기 런타임 | AnyIO |
| 외부 HTTP | httpx2 |
| WebSocket | websockets (pinned `17.0.1`) |
| 대칭키 복호화 | cryptography (pinned `50.0.0`) |
| JSON 응답 | Pydantic 직렬화, 필요 시 orjson |
| 구조화 로그 | structlog |

증권사·공시 API의 JSON은 어댑터에서 Pydantic 모델로 한 번만 파싱한 뒤 내부 도메인 타입으로 변환한다. 외부 원본 `dict`를 애플리케이션 내부로 전달하지 않는다.

FastAPI 라우터는 `create_app`이 주입하는 application 계층 Protocol(상태 probe, 시장 데이터 reader, 기업행사·수정주가 reader, 재무 보고서 reader)만 사용한다. 어댑터 구현은 기본 factory로 연결하고 테스트는 fake reader를 주입한다. 읽기 전용 조회 어댑터는 쓰기 저장소와 모듈을 분리한다. 분봉 읽기는 `MarketDataReader` Protocol의 `minute_bars`로 노출되며, 분봉 수집은 시장 달력·KIS 당일분봉·분봉 저장소 Protocol을 조합한 application 유스케이스가 담당한다.

KIS 어댑터의 `httpx2` 클라이언트는 HTTP/2, 연결 풀, Brotli·Zstandard 응답, 연결·읽기·쓰기·풀 타임아웃과 전송 재시도를 사용한다. 모의투자 인증과 시세 요청은 초당 1건 제한보다 안전한 최소 1.05초 간격으로 직렬화하고, 로그에는 HTTP 메서드·경로·상태·소요시간만 남겨 인증 헤더와 요청 본문을 제외한다.

증권사가 주문을 바꿀 때 새 식별자를 주면 내부 식별자를 갱신하고 이전 값을 이벤트에 남긴다. 정정은 같은 논리적 주문이므로 행을 새로 만들지 않는다. 같은 주문에 대한 여러 번의 위험판정은 회차로 구분해 모두 보존한다(정책 §7).

종목 유니버스와 업종 키는 KIS 공식 마스터 파일(비인증)에서 온다. ETF 마스터와 같은 파일을 읽어 그룹코드로 갈라 쓰고, 다운로드·원본 봉투 생성은 한 곳에서 공유한다. 종목 식별자는 정체성(국가·거래소·단축코드·상품유형·통화)에서 나오는 결정적 uuid5이므로 마스터 수집과 번들 수집이 같은 행을 가리킨다. 이 값을 무작위로 만들면 이후 시세·일봉이 존재하지 않는 종목을 참조한다.

상태 무효화 규칙은 순수 함수 하나에 모으고 읽는 경로마다 적용한다. 정책이 "항상"이라고 정한
복귀(거래일 변경 등)를 쓰기 경로에만 넣으면, 게이트와 조회가 만료된 상태를 유효한 것으로 믿는다.
조회는 저장 기록을 고쳐 쓰지 않고 지금 성립하는 값을 계산해 저장값과 함께 노출한다 — 읽기가 쓰기를
하지 않으면서도 화면이 거짓을 말하지 않게 하는 방법이다. 시각에 의존하는 판정은 시계를 주입해
테스트가 실행 날짜에 흔들리지 않게 한다.

분류 규칙은 조회 응답이 말한다. 화면이 식별자에서 성질을 추론하면(단축코드 6번째 자리로 우선주
판정 등) 데이터 규칙이 UI에 복제되고 원천이 바뀔 때 갈라진다. 사실을 가진 층이 필드로 내보내고
화면은 그 값만 본다. 사실이 없는 종목은 `null`로 "모른다"를 표현하며, 화면은 모르는 것을 특정
분류로 취급하지 않는다.

도메인 타입 간 import 순환은 최하위 모듈에 타입을 두어 끊는다. 종목 타입이 주식종류를 참조하면
`models` → `share_classes` → `stocks` → `models`가 되므로 enum을 `models`에 정의하고 규칙 모듈이
재노출한다.

조회 모델은 저장된 감사 문자열을 그대로 돌려준다. 전략·경로마다 사유 어휘가 다르므로 읽기 계층이 한 구현의 enum으로 되검증하면 다른 구현의 기록 조회가 500이 된다(2026-08-21 실측: 다종목 실행의 체결 목록이 `rebalance` 때문에 깨졌다). 엔진의 내부 타입과 조회용 기록을 분리한다. 같은 이유로 대표 식별자가 없는 기록은 outer join으로 읽는다 — inner join은 그 기록을 조용히 목록에서 없앤다.

append-only 시퀀스를 계산하는 경로는 부모 행을 먼저 잠근다. 상태를 바꾸는 전이는 `UPDATE`가 행을 잠가 우연히 직렬화되지만, 상태를 바꾸지 않는 기록(취소 요청·실패 등)은 잠금이 없어 동시 쓰기가 같은 `max(sequence)+1`을 잡고 유일 제약을 위반한다. 비상정지처럼 사람이 마지막으로 쓰는 통제 수단이 부분 실패로 끝나는 경로였다(2026-08-21 실측).

원천 사실과 우리가 파생한 사실이 한 테이블을 공유하면, "같은 사실인가" 비교에서 파생 필드를 빼야 한다. 원천이 주지 않는 값(예: 배당락일)이 비어 있는 관측은 "그 값에 대해 의견이 없다"로 읽고 기존 확정을 보존한다. 파생 필드를 비교에 넣으면 수집과 확정이 서로의 버전을 계속 supersede해 확정이 조용히 사라진다(2026-08-21 실측: 재수집 한 번에 422건이 7건).

전략 신호는 거래일 달력을 필수 입력으로 받는다. 지표 기준 시점을 시계열 길이에서 추정하는 폴백을 두면, 구간이 부족할 때 조용히 퇴화한 순위(전 종목 동일 값 → 동점 처리 순서)가 나와 전략이 아닌 결과를 전략처럼 저장한다(2026-08-20 실측). 기준 시점을 정할 수 없으면 그 회차를 만들지 않는다 — 빈 선정을 내보내면 포트폴리오 엔진이 보유 전량을 매도한다.

검증된 엔진에 새 규칙을 섞지 않는다. 다종목 포트폴리오 백테스트는 단일 종목 엔진과 별 모듈이며, 성과 지표 정의만 공용 모듈로 공유한다. 같은 이름의 지표를 두 엔진이 각자 계산하면 값이 갈라지고, 반대로 한 모듈에 두 규칙을 넣으면 이미 실데이터로 검증한 경로가 흔들린다.

종목 정체성은 저장 직전에 검사한다. 유일 제약이 상품유형을 포함하므로 같은 단축코드가 다른 상품유형으로 들어오면 DB는 막지 못하고 행을 하나 더 만들고, 그때부터 모든 조인이 둘로 쪼개진다. 마스터 수집과 번들 저장이 모두 기존 행의 상품유형을 확인해 충돌이면 아무것도 저장하지 않고 실패한다.

외부 원천의 식별자 체계가 우리 것과 다르면 매핑 자체를 사실로 저장한다. DART 배당 공시는 종목코드가 아니라 고유번호로만 조회되므로 `corpCode.xml` 전체 파일을 버전 사실로 적재하고, 매핑이 없는 종목은 추측하지 않고 대상에서 제외해 보고한다. 대용량 파일 원천은 점검 중 ZIP 대신 오류 XML을 돌려주므로 형식을 먼저 확인하고 부분·빈 매핑을 저장하지 않는다.

전 종목 스윕은 어댑터 타임아웃에 의존하지 않는다. 실측으로 KIS 요청이 TCP 연결을 유지한 채 응답 없이 매달려 HTTP 읽기 타임아웃이 걸리지 않는 경우가 있었으므로, 스윕 유스케이스가 `anyio.fail_after`로 대상마다 상한을 강제하고 초과분은 실패로 세고 넘어간다. 상한이 없으면 한 종목이 전체 수집을 멈춘다.

주문을 새로 내보내는 경로와 기존 주문의 체결 가능성을 바꾸는 경로는 같은 전제조건 집합을 쓴다. 제출·정정 CLI가 모두 체결통보 리스너 부착을 확인하고, 붙어 있지 않으면 증권사를 호출하지 않는다. 조건 집합이 갈라지면 한쪽 경로로 통보 없는 체결이 생긴다.

CLI 보고는 시도한 수가 아니라 남은 결과를 센다. 멱등 저장(`on_conflict_do_nothing`)으로 조용히 생략된 행이 있으면 "만든 수"와 "저장된 수"를 나눠 출력해, 운영자가 저장되지 않은 것을 저장된 것으로 오해하지 않게 한다.

예약 작업은 원천의 회수 창을 안전 여유로 쓴다. 수급은 최근 약 30거래일을 돌려주므로 며칠 놓쳐도
다음 실행이 그 구간을 메운다. 그래서 거래일 판정을 전제로 두지 않는다 — 휴장일 실행은 같은 구간을
다시 관측하는 멱등 동작이고, 달력을 필수로 걸면 달력 미커버가 축적 자체를 막는다. 반대로 부분
실패는 성공으로 기록하지 않는다. 수집된 종목은 이미 저장돼 있고, 실패로 남겨야 같은 날 다음 시도가
남은 종목을 채운다.

상시 프로세스의 시작은 상태 머신의 입력이다. 거래 관련 상시 프로세스가 시작하면 자동매매를 `DISABLED`로 되돌려(사유 `PROCESS_START`) 사람이 다시 켜야 주문이 나가게 한다(정책 §6). 세션 내부 재연결은 프로세스 시작이 아니므로 구분한다.

저장된 원본은 복구 경로의 근거다. 처리 버그로 반영되지 않은 외부 사실은 원본을 다시 해석해 적용하고(`--replay`), 재반영 여부를 별도 열로 표시해 중복 적용을 막는다. 사람의 진술로 상태를 바꾸는 경로(ADR-0010)와 구분해 사유 코드를 다르게 남긴다.

거래일은 거래소 시간대로 정한다. 시각은 UTC로 저장하지만 "오늘이 며칠인가"는 `Asia/Seoul` 기준이며, 자동매매 상태·신호일자·비상정지가 모두 같은 헬퍼(`seoul_trading_date()`)를 쓴다. UTC 날짜를 쓰면 09:00 KST 이전에 하루가 밀려 상태 머신이 거래일 변경으로 오판한다(2026-08-20 실측).

사람이 입력한 사실은 증권사 응답과 같은 자리에 섞지 않는다. 사람이 확인해 상태를 바꾸는 경로는 별도 이벤트 유형(`attestation`)과 사유 코드(`HUMAN_ATTESTED`)로 저장해 감사에서 출처를 구분하고, 실행자와 근거 문자열을 필수로 함께 남긴다(ADR-0010).

상시 실행 프로세스의 운영자 보고는 취소를 견뎌야 한다. 세션 안에서 센 값은 취소 시 유실되므로, 처리 건수·차단 여부 같은 집계는 세션 밖 객체에 모아 종료 요약이 사실과 어긋나지 않게 한다.

상시 실행 프로세스는 종료 신호를 코드로 다룬다. 체결통보 리스너는 `anyio.open_signal_receiver`로 SIGINT·SIGTERM을 같은 종료 경로로 모아 세션을 닫고(취소 중에도 기록이 남도록 `CancelScope(shield=True)`) 종료하며, 감사 로그의 종료 사유로 운영자 중단(`STOPPED`)과 연결 끊김(`CONNECTION_CLOSED`)을 구분한다. 컨테이너 정지가 기록 없이 프로세스를 죽이면 다음 기동이 남은 연결 세션을 만나기 때문이다. 수신 루프의 예외는 태스크 그룹이 예외 그룹으로 묶기 전에 해당 프레임에서 처리한다.

실시간 체결통보는 `websockets`로 연결하고 자동 ping을 끈 뒤 서버의 `PINGPONG` 프레임에 응답해 유지한다. 통보 본문은 항상 암호화되어 오므로 `cryptography`의 AES-256-CBC로 복호화한다(`adapters/brokers/kis_realtime.py`). 프레임 해석·복호화는 순수 함수로 분리해 소켓 없이 검증하며, 웹소켓 접속키는 REST 접근토큰과 별개 자격증명이라 별도 Valkey 캐시 키로 공유한다. Valkey 조정 모듈은 공용 타입·단일 프로세스 구현(`kis_coordination.py`)과 Valkey 구현(`kis_coordination_valkey.py`)으로 나뉘어 있다.

주요 의미 타입은 일반 문자열이나 숫자와 구분한다.

```text
InstrumentId
BrokerOrderId
ClientOrderId
AccountId
Money(amount, currency)
Quantity
ExchangeTimestamp
```

- 금액과 가격은 `float`가 아니라 `Decimal`을 사용한다.
- 수량은 정수 또는 상품에서 허용하는 명시적 단위를 사용한다.
- DB 시각은 UTC로 저장하고 거래소 시간대를 별도로 보존한다.
- 모의투자와 실전투자의 자격증명 및 환경 타입을 구분한다.

### 3.2 데이터베이스

| 역할 | 기술 |
|---|---|
| ORM | SQLAlchemy 2 async |
| PostgreSQL 드라이버 | asyncpg |
| 마이그레이션 | Alembic |
| 통합 테스트 | Testcontainers PostgreSQL |

PostgreSQL 18 컨테이너의 named volume은 메이저 버전별 하위 디렉터리 생성을 허용하도록 `/var/lib/postgresql`에 연결한다.

### 3.3 외부 API 어댑터

초기 어댑터는 다음 책임으로 나눈다.

```text
KisMarketDataAdapter
KisTradingAdapter
KisAccountAdapter
OpenDartAdapter
EtfReferenceDataAdapter
```

처음에는 한국투자증권만 구현한다. 다중 증권사를 예상한 거대한 공통 인터페이스를 만들지 않고 실제 사용 기능만 작은 포트로 정의한다.

2026-08-14 구현 범위의 `KisMarketDataAdapter`는 모의·실전 호스트를 설정으로 분리한다. 접근 토큰은 프로세스 메모리를 1차 캐시로 사용하고 Valkey에서 다른 worker와 공유한다. 현재가 `FHKST01010100`, 기간별 일봉 `FHKST03010100`을 지원하며 일봉은 비수정 원본 가격으로 요청한다. 실전 환경은 종목 상세 `CTPF1002R`도 호출하지만, 이 TR을 지원하지 않는 모의환경은 일봉 응답 요약에서 종목명과 최소 식별정보를 구성한다.

승인된 [ADR-0005](../decisions/0005-kis-token-and-rate-coordination.md)에 따라 `KIS 환경 + 자격증명 HMAC 지문`별로 토큰, 단일 발급 잠금과 REST 호출 게이트를 분리한다. 토큰 TTL은 KIS 만료시각보다 1분 짧고 모의 REST 호출은 모든 worker를 합쳐 최소 1.05초 간격이다. 유효한 메모리 토큰이 있어도 Valkey 호출 게이트를 사용할 수 없으면 외부 요청을 보내지 않고 실패한다.

`KrxMarketCalendarAdapter`는 KRX 공식 휴장일 화면의 OTP와 연간 JSON 응답을 같은 HTTP 세션에서 조회한다. 연도별 원본 1건을 범위 내 날짜들이 공유하고, 공식 휴장 목록과 KRX 주말 규칙을 정상장·휴장 세션으로 정규화한다. `KrxTradingHoursNoticeAdapter`는 KRX 보도자료 목록과 첨부 PDF에서 수능일·연초 개장일의 주식·ETF 정규장 변경을 추출하고 PDF 원문을 Base64 근거로 보존한다. `KrxCompositeCalendarSource`가 임시 변경을 연간 세션에 합성한 전체 범위만 저장해 후속 연간 재수집이 단축장을 정상장으로 되돌리지 못하게 한다. PDF 파싱에는 `pypdf`를 사용한다. `KisMarketCalendarVerifier`는 실전 전용 `CTCA0903R`의 요청일 `opnd_yn`만 사용해 저장된 KRX 사실을 당일 확인한다. 모의환경에서는 지원되지 않는 TR을 호출하지 않고 실패해 상태를 `pending`으로 유지한다.

2026-08-16 구현 범위의 `DartCorporateActionAdapter`는 OpenDART 공시검색 `list.json`으로 접수번호를 페이지 단위로 수집하고, 공시서류 원본 `document.xml`의 ZIP에서 거래소 서식 HTML을 추출해 EUC-KR로 복호화한다. `현금ㆍ현물배당결정` 서식만 엄격 파싱하며(허용 정정 접두어: 기재정정·첨부정정·첨부추가) 현물배당, 알 수 없는 접두어, 서식 불일치는 전체 수집을 실패시킨다. `crtfc_key`는 요청에만 사용하고 저장 지문·원본·로그에 포함하지 않는다. 원본은 목록 JSON과 문서 파일의 Base64 봉투로 append-only 보존한다.

배당·분배락일은 사용자가 승인한 규칙 기반 도출로 확정한다. `ExDateResolver`가 검증된 `XKRX` 달력에서 `기준일 이전 마지막 거래일의 직전 거래일`을 계산하고, 달력 미커버는 확정하지 않으며, 확정 결과는 원본 근거를 재사용하는 `verified` 새 사실 버전이다. 수정주가는 `domain/market_data/adjustments.py`의 순수 계산기가 `Decimal` 정밀도 34로 계수를 만들고 가격 8자리·계수 16자리 `ROUND_HALF_UP`으로 고정하며, `PostgresAdjustmentStore`가 knowledge cutoff 기준 point-in-time 기업행사 선택, 입력 해시 멱등성, 정정 시 새 데이터셋 생성과 실패 코드 기록을 담당한다.

2026-08-17 구현 범위의 `KodexDistributionAdapter`는 삼성자산운용 KODEX 공식 분배금 데이터에서 지급기준일·세전 주당분배금·실지급일 이력을 인증 없이 수집한다. 응답 항목은 엄격한 필드 계약으로 검증하고 지급기준일 중복이나 형식 불일치는 전체 수집을 실패시킨다. 한 응답을 공유하는 여러 분배 사실은 원본 한 건을 함께 참조한다. 두 어댑터는 공통 `CorporateActionCollector` 유스케이스와 기업행사 사실 버전 저장소를 공유한다. KRX 정보데이터시스템 `getJsonData`는 화면 종속 세션 게이트가 있어 자동 수집 출처로 사용하지 않는다.

### 3.4 작업 처리와 스케줄링

| 역할 | 기술 |
|---|---|
| 비동기 작업 | Taskiq |
| 작업 브로커 | Valkey의 Redis 호환 프로토콜 |
| 주기 작업 | Taskiq scheduler 단일 인스턴스 |
| 장기 WebSocket | 별도 stream worker |

- 주문과 데이터 수집 작업에는 중복 방지 키를 둔다.
- 작업 큐는 주문 상태의 원본이 아니다.
- PostgreSQL 주문 상태를 기준으로 재시작과 메시지 유실을 복구한다.
- 모델 학습처럼 CPU 사용량이 큰 작업은 별도 프로세스로 격리한다.
- ListQueueBroker의 블로킹 대기가 유휴 상태에서도 유지되도록 Valkey 연결의 `socket_timeout`을 `None`으로 지정한다.
- `confirm_seed_daily_bars`는 KIS 일봉을 재조회해 서울 기준 15:40 이후의 두 관측이 일치한 `pending` 일봉만 `confirmed`로 전환한다. 장중 첫 관측은 확정 근거가 아니고, 재조회 값이 다르면 확정하지 않고 새 `pending` 정정 버전을 남긴다.
- `collect_seed_market_data`는 삼성전자와 KODEX 200의 종목정보·현재가·비수정 일봉을 수집한다. `collect_krx_market_calendar`는 KRX 연간 휴장일과 임시 거래시간 공지를 합성해 적재하고 `confirm_today_market_calendar`는 실전 KIS로 오늘 거래 가능 상태를 1회 확인한다. `collect_dart_cash_dividends`와 `collect_kodex_distributions`는 각각 DART 현금배당 공시와 KODEX 분배금 이력을 기업행사 사실 버전으로 저장하며 아직 예약 없이 수동으로 실행한다.
- 시장 달력 저장소는 누락·미확인·충돌·오래된 확인을 fail-closed로 판정한다. 승인된 [ADR-0006](../decisions/0006-market-calendar-scheduling.md)에 따라 서울 기준 KRX 선행 수집, KIS 당일 보완 확인과 PostgreSQL 영속 실행 claim을 구현했다. 기본 Compose의 단일 scheduler 프로필은 KRX 예약만 켠다. 실전 `CTCA0903R` 읽기 전용 검증 후 사용자가 승인한 `compose.kis-live-calendar.yaml`을 함께 적용할 때만 KIS 자동 확인을 활성화한다.
- 유니버스 전 종목 수집 CLI(`worker/market_data.py --collect-universe-quotes`, `worker/fundamentals.py --universe-statements`)는 예약 없이 수동 실행한다. 종목 하나의 실패는 기록하고 계속하되, 출처의 일 요청 한도 초과는 남은 종목도 모두 실패하므로 즉시 중단하고 미처리 종목을 보고한다. 실측 소요는 시세 스윕 약 3.5분, 재무제표 스윕 약 9분(요청 3,200회)이다.
- 기본 Compose는 자격증명 없이 실행한다. 실제 모의검증은 `compose.kis-paper.yaml`에서 `.secrets/` 파일을 Docker secret으로 worker에만 마운트하며 환경을 `paper`로 강제한다.
- Valkey 호스트 포트는 로컬 루프백 `127.0.0.1`에만 바인딩한다. 운영 배포에서는 Valkey 포트를 공개하지 않는다.

## 4. 데이터 저장과 분석

### 4.1 운영 데이터

PostgreSQL을 주문, 계좌, 시장 데이터, 전략, 감사 기록의 단일 영속 원본으로 사용한다.

```text
reference
├─ instrument
├─ market_calendar
├─ corporate_action
└─ etf_profile

market
├─ quote
├─ market_bar
├─ investor_flow
├─ etf_nav
├─ etf_constituent
└─ etf_distribution

fundamental
├─ company
├─ financial_statement
├─ financial_metric
└─ disclosure_event

strategy
├─ strategy_version
├─ feature_set_version
├─ backtest_run
├─ signal
└─ prediction

trading
├─ account_snapshot
├─ order
├─ execution
├─ position
├─ risk_decision
└─ reconciliation_run

operations
├─ raw_api_response
├─ api_sync_status
├─ job_run
├─ alert
└─ audit_event
```

`market_bar`는 데이터 규모가 확인된 뒤 종목 또는 시간 기준 파티셔닝을 적용한다. 초기부터 TimescaleDB에 의존하지 않는다.

2단계 첫 리비전은 `instrument`, 최신 `quote`, 일봉 `market_bar`, append-only `raw_api_response`, 수집 상태 `api_sync_status`를 생성했다. 후속 리비전은 버전된 `market_calendar`를 생성하고 현재 세션·기간·다음·이전 거래일 조회와 출처 충돌 기록을 구현했다. 나머지 표의 엔터티는 해당 단계에서 추가한다.

### 4.2 분석 및 학습 데이터

| 역할 | 기술 |
|---|---|
| 컬럼형 데이터 처리 | Polars Lazy API |
| 수치 계산 | NumPy |
| 연구용 로컬 SQL | DuckDB |
| 학습 데이터 포맷 | 버전이 지정된 Parquet |

```text
PostgreSQL
    ↓ 데이터셋 버전 생성
Parquet snapshot
    ↓
Polars / DuckDB
    ↓
백테스트·ML 학습
```

분석·학습 작업이 운영 PostgreSQL을 반복적으로 대량 조회하지 않도록 데이터셋 스냅샷을 만든다. 데이터셋에는 생성시각, 조회 범위, 원본 버전, 기업행사 처리 방식과 특징 버전을 기록한다.

관련 결정: [ADR-0003](../decisions/0003-data-architecture.md)

## 5. 보조지표와 백테스트

### 5.1 특징 계산

보조지표는 순수 계산 모듈로 구현한다. 2026-08-23 현재 구현은 다음과 같다 — 계획 단계의 Polars 기반 모듈 목록을 실제 구조로 갱신했다.

```text
domain/strategies/indicators.py   # SMA·EMA·RSI(Wilder)·MACD·ATR·볼린저, 순수 Decimal
features/
├─ price_features.py       # 가격·거래량 파생 23종 (features-1)
├─ fundamental_features.py # 이익수익률·ROE (features-2 추가분)
├─ feature_set.py          # 특징 집합 버전과 이름 목록
├─ targets.py              # 초과수익과 횡단면 순위
└─ splits.py               # 워크포워드 분할·엠바고
```

- 외부 수치 라이브러리(Polars·numpy·scikit-learn)를 특징 계산에 쓰지 않는다. `typeCheckingMode = "all"` 게이트를 통과하지 못하는 것이 직접 이유이고(§6.1), 금액은 `Decimal`이어야 하므로 부동소수 프레임과 맞지 않는다.
- 상장 주식종류는 `domain/market_data/share_classes.py`의 순수 함수가 단축코드 앞 5자리로 묶고, 예외 군은 저장하지 않고 사유와 함께 돌려준다. 저장은 `adapters/database/market_data_share_class_store.py`이며 `market_data_stock_store`가 300줄을 넘어 별 모듈로 뒀다(리뷰 임계 규칙).
- 재무 특징은 정의를 새로 만들지 않고 [재무 지표 정의 계약](../data/financial-indicator-contract.md)의 도메인 함수를 호출한다. 화면·백테스트·ML이 같은 정의를 쓰지 않으면 결과를 비교할 수 없다.
- **특징 집합은 버전 문자열이다**(`features-1`, `features-2`). 모델마다 자기 집합을 저장하고 추론 경로가 그 버전을 따라간다. 이름을 하드코딩하면 집합이 다른 모델에서 열 개수가 어긋난다(2026-08-22 실측 결함).
- 동일한 특징 계산 코드를 웹 차트, 백테스트, 모의매매와 실전매매에서 공유한다. 라이브러리별 계산 차이로 결과가 달라지지 않도록 실제 사용하는 지표만 고정된 공식과 테스트 데이터로 검증한다.

### 5.2 백테스트 엔진

운영 전략과 동일한 체결·위험 규칙을 사용하기 위해 필요한 주문 유형만 지원하는 결정적 이벤트 시뮬레이터를 내부에 구현한다.

```text
시장 데이터
→ 특징 계산
→ 전략 신호
→ 목표 포지션
→ 위험검사
→ 다음 거래 가능 시점 주문
→ 수수료·세금·슬리피지
→ 포트폴리오 평가
```

Backtrader나 VectorBT는 연구 비교에 사용할 수 있지만 운영 핵심 의존성으로 사용하지 않는다.

2026-08-18에는 주문 실행 이전 계층을 추가했다. `domain/risk/`가 거래 안전 정책 §3·§4의 한도를 외부 호출 없는 순수 함수로 표현하고, `domain/orders/`가 주문·자동매매 상태 머신과 호가단위·지정가 규칙을 담는다. `application/trading/`이 시장 달력·계좌 조회·현재가 조회·저장소 Protocol을 조합해 계획을 만들고, `adapters/database/trading_*`가 `trading` 스키마(리비전 `20260818_0014`)에 계좌 스냅샷·자동매매 상태·주문·이벤트·위험판정을 저장한다. 읽기는 `/api/trading/*`, 실행은 `worker/execution/planning.py` CLI다. 증권사 주문 제출 어댑터는 아직 존재하지 않는다. 계좌번호·상품코드는 Docker secret 파일로만 주입하고 로드 시점에 자릿수 계약(8자리·2자리 숫자)을 검사해 잘못된 값이 증권사로 나가지 않게 한다. asyncpg가 `numeric(24,0)`의 trailing zero를 지수 표기 `Decimal`로 돌려주므로 원화 금액은 읽기 어댑터에서 정수 표기로 정규화한다.

2026-08-18 구현 상태: 보조지표(SMA·EMA·RSI·MACD·ATR·볼린저)는 `domain/strategies/indicators.py`의
순수 `Decimal` 함수로 구현했다. 2종목 유니버스에서는 Polars 도입 없이 금액 `Decimal` 규칙과
결정성을 우선했고, 다종목 유니버스로 확장할 때 Polars 벡터화를 재검토한다. 백테스트 엔진은
`domain/strategies/backtest.py`의 결정적 시뮬레이터로 위 흐름 중 위험검사 단계를 제외하고
구현했으며(위험검사는 7단계 모의 자동매매 범위), 실행 기록은 `strategy.backtest_run`·
`backtest_trade`·`backtest_equity`(리비전 `20260818_0013`)에 저장하고
`/api/backtests`로 조회한다. 실행은 `worker/backtests.py` CLI로 수행한다.

2026-08-21에 다종목 전략을 둘로 늘렸다. 횡단면 순위의 공용 타입·평균 순위 계산은
`domain/strategies/ranking.py`, 요인은 `momentum.py`(모멘텀)와 `composite_rank.py`(가치·수익성·
모멘텀 종합, 시점 정합 선택 포함)에 있다. 러너는 전략을 모르고
`application/backtests/portfolio_strategies.py`가 전략 신원·canonical 파라미터·회차 생성기를
묶어 주입한다. 재무 입력은 `adapters/database/strategy_fundamentals_reader.py`가 재무 지표 도메인
함수를 그대로 호출해 만들며, 전략이 지표를 다시 정의하지 않는다. 실행 기록에는
`input_report_version_hash`(리비전 `20260821_0024`)가 추가됐다. 같은 날 지표 읽기 경로에 업종 원천을 주입했다 — `create_app`이 `PostgresStockStore`를 `SectorSource`로 넘기고, 응용 계층이 금융업(KOSPI200 업종 코드 `6`)의 매출액·영업이익 기반 실패를 `SECTOR_ACCOUNT_BASIS`로 다시 표기한다. 도메인 순수 함수는 업종을 모르고 값도 만들지 않는다.

## 6. 머신러닝과 생성형 AI

### 6.1 머신러닝

| 단계 | 기술 |
|---|---|
| 기준 모델 | Ridge(정규방정식 닫힌 해, 표준 라이브러리만) |
| 주력 표 모델 | LightGBM 4.7.0 (경계 모듈 `ml/lightgbm_model.py`) |
| 후속 시계열 모델 | PyTorch 기반 1D CNN/TCN, LSTM |
| 평가 | 시간 순서 기반 워크포워드 검증 |

첫 모델 입력과 목표:

```text
입력 X
= 최근 60거래일
× OHLCV
× 이동평균·RSI·MACD·ATR
× 캔들 특징
× 거래량·수급

정답 y
= 향후 10~20거래일 시장 대비 초과수익 또는 순위
```

모델 파일은 임의 코드를 실행할 수 있는 Python pickle 대신 LightGBM 텍스트, XGBoost JSON처럼 해당 모델의 안전한 네이티브 포맷을 사용한다. 2026-08-22 정정: 기준 모델은 `scikit-learn` 대신 표준 라이브러리 닫힌 해로 구현했다. 특징이 23개라 정규방정식이 23x23이고, `scikit-learn`은 타입 스텁이 없어 `typeCheckingMode = "all"` 게이트를 통과하지 못하며 `numpy`도 부분적으로 `Any`를 노출한다. 새 런타임 의존성 없이 같은 모델을 얻으므로 이 선택을 택했다. 주력 모델(LightGBM)은 계획대로 경계 모듈 하나로 격리했고 타입 검사 예외를 그 파일에만 뒀다. 경계 밖으로는 `numpy.asarray`로 조밀 배열을 확정한 값만 내보내므로 나머지 코드는 완전한 타입 검사를 유지한다. **macOS는 OpenMP 런타임이 필요하다**(`brew install libomp`) — 없으면 `lib_lightgbm.dylib` 로드가 실패한다. 재현성을 위해 `num_threads=1`·`deterministic=True`를 고정한다. 모델 메타데이터와 평가 결과는 PostgreSQL에 저장한다.

학습 진입점은 `worker/ml.py`이며 예약하지 않는다. `application/ml/training.py`가 로드·구간 분할·구간별 학습·평가·저장을 잇고, `adapters/database/ml_dataset_reader.py`가 확정 일봉만 읽어 특징과 목표를 만든다. 모델·구간 지표·특징 중요도는 `ml` 스키마(리비전 `20260822_0025`)에 한 트랜잭션으로 저장하며, 모델 행에는 학습 시점 달력으로 계산한 표본 밖 시작일도 남긴다(리비전 `20260822_0026`) — 백테스트 창의 달력만으로는 학습 창과의 거래일 간격을 셀 수 없다. `ml-rank` 실행은 저장된 모델을 읽어 추론만 하며 `worker/backtests.py --ml-rank`가 진입점이다. 학습 CLI는 `--algorithm`(ridge·lightgbm)과 `--horizon-days`를 받고, 목표 창을 바꾸면 엠바고 하한이 함께 따라간다 — 상수에 고정하면 라벨이 검증 구간으로 새어 나간다.

초기에는 MLflow를 도입하지 않는다. 모델과 실험 수가 증가해 현재 저장 구조로 추적하기 어려워질 때 검토한다.

### 6.2 생성형 AI

| 역할 | 기술 |
|---|---|
| 구조화 출력 | Pydantic AI |
| 입력 | OpenDART 공시, 계산된 재무·전략 결과 |
| 출력 | 타입이 있는 이벤트·요약·근거 |

- 공시 접수번호, 발표일, 원문 근거를 필수로 저장한다.
- LLM 프로세스에 증권사 주문 자격증명을 제공하지 않는다.
- LLM 출력은 주문 API 입력으로 직접 연결하지 않는다.
- 모델 제공자는 설정으로 교체할 수 있도록 경계만 둔다.

관련 결정: [ADR-0004](../decisions/0004-ai-execution-separation.md)

## 7. 프론트엔드

### 7.1 기반 기술

| 역할 | 기술 |
|---|---|
| UI 런타임 | React 19.2 |
| 언어 | TypeScript strict |
| 빌드 | Vite 8.1 |
| 패키지 관리 | Bun |
| 라우팅 | TanStack Router 또는 구현 시점 검증 후 React Router |
| 서버 상태 | TanStack Query |
| 폼 | React Hook Form + Zod |
| 표 | TanStack Table |

서버 상태는 TanStack Query로 관리한다. Redux는 도입하지 않는다. 복잡한 클라이언트 전역 상태가 실제로 생긴 경우에만 Zustand를 검토한다.

### 7.2 UI와 차트

| 역할 | 기술 |
|---|---|
| 스타일 | Tailwind CSS 4 |
| 접근 가능한 primitive | Radix UI |
| 아이콘 | Lucide |
| 캔들·거래량 | Lightweight Charts |
| 재무·수급·순위·히트맵 | Apache ECharts |

UI 코드보다 `docs/` 아래 디자인 시스템 문서를 먼저 작성한다. 색상, 타이포그래피, 간격, 표, 차트, 상태와 반응형 규칙은 디자인 토큰으로 관리한다.

2026-08-17의 3단계 1차 구현은 승인 토큰을 `src/styles.css`의 semantic 변수(라이트 기본, `prefers-color-scheme: dark` 대응)로 관리하고, 캔들·거래량·RSI·MACD·볼린저는 외부 차트 라이브러리 없이 화면 디자인 사양 5.6 규칙의 자체 SVG 패널로 렌더링한다(가격축 텍스트는 SVG 밖 HTML). 십자선·확대 같은 상호작용 요구가 확정되면 Lightweight Charts 도입을 다시 검토한다. 라우팅은 pathname 분기를 유지하고 화면이 더 늘어나면 라우터를 도입한다(2026-08-18 전략 연구 `/strategy`와 모의매매 콘솔 `/trading` 추가로 실화면 6개 + 갤러리; 백테스트 조회는 `/api/backtests`, 주문 계획·한도 조회는 `/api/trading` 읽기 전용이며 화면에서 실행이나 상태 전이를 트리거하지 않는다 — 자동매매 상태 변경은 worker CLI 전용 경계라 HTTP 쓰기 경로를 만들지 않았다). TypeScript 프로젝트는 셋으로 나뉜다: 앱·vitest(`tsconfig.app.json`, DOM 환경), 빌드 도구·Playwright 스펙(`tsconfig.node.json`, node 타입 + `page.evaluate` 콜백용 DOM lib), 루트 참조(`tsconfig.json`). Playwright e2e는 Node 프로세스에서 실행되므로 node 프로젝트에 속하며, CI는 빈 데이터베이스로 돌기 때문에 실데이터 단언은 `E2E_EXPECT_DATA=1`로만 활성화된다.

같은 날 모의매매 콘솔은 정책 한도를 화면에 하드코딩하지 않도록 `GET /api/trading/risk-limits`를 추가했다. 한도값은 `domain/risk/limits.py`의 승인 상수를 그대로 내보내고, 소진율은 저장하지 않고 `domain/risk/utilization.py`의 순수 함수가 조회 시점에 계산한다(기준 스냅샷·장 시작 NAV·고점 NAV·주문 카운터·최근 API 실패 수). 주문 카운터 SQL은 쓰기 저장소와 읽기 어댑터가 `adapters/database/trading_queries.py`를 공유해 두 경로가 다른 정의로 갈라지지 않게 했다. 화면 주석에 들어가는 실행 명령은 `code` 요소와 보조 표면 배경으로 문장과 분리한다(운영자가 복사해야 하는 문자열이라 산문과 붙어 보이면 안 된다). 주문 제출은 `KisHttpClient.post`로 KIS 쓰기 TR을 호출하는 첫 경로이며, 제출·취소 응답은 거절도 예외가 아니라 `BrokerAcknowledgement` 사실로 돌려받아 상태 전이로 기록한다. 체결 동기화는 순수 함수(`domain/orders/fills.py`)가 증권사 행과 내부 주문을 맞춰 전이 목표와 불일치를 계산하고, 어댑터는 그 결과만 저장한다. 2026-08-19 실주문 검증에서 판정용 현금의 의미를 `AccountState.settled_cash`로 고정했다(가수도정산금액). 예수금 총액은 미결제 매수분을 차감하지 않아 NAV와 최소 현금 비중을 완화시키므로 판정에 쓰지 않는다. 예상 노출에는 그 거래일의 미체결·계획 주문 금액(`PendingExposure`)이 포함되며, 이 입력은 계획 시점에 저장소가 계산해 위험검사에 넘긴다.

같은 날 4단계 재무 지표는 백엔드가 조회 시점에 계산하는 방식을 채택했다. 파생 지표를 별도 테이블에 저장하지 않고 `domain/fundamentals/indicators.py`의 순수 함수가 현재 버전 보고서에서 결정적으로 계산해 수식·입력 계정·근거 접수번호를 응답에 포함하며, 화면은 응답을 표시만 한다(로드맵 4단계의 "동일 지표가 화면과 백엔드에서 같은 정의" 요구). 연간 실적 막대 차트도 동일한 자체 SVG 규칙을 따른다. 가치지표도 같은 조회 시점 계산을 따르되, 기준 시점이 서로 다른 세 입력(배치 시세·상장주식수 버전 사실·최근 연간 보고서)을 결합하므로 응답에 세 기준을 항상 분리해 노출하고, 출처가 불분명한 외부 계산값(KIS per/pbr)은 쓰지 않는다. 수급(투자자별 매매)과 DART 공시 목록도 동일한 원본 보존·버전 사실 패턴을 재사용한다. 수급은 서울 기준 당일 잠정치를 저장하지 않는 fail-closed 경계를 두고, 공시 목록은 접수번호 유일의 불변 사실이라 버전 없이 멱등 삽입만 한다. ETF 마스터는 KIS가 공식 배포하는 비인증 고정폭 마스터 파일을 원본(Base64 봉투)과 함께 버전 사실로 저장하고, NAV·괴리율 스냅샷은 시세(quote)와 같은 최신값 정규화 + append-only 원본 패턴을 쓴다(정규화 이력 테이블은 두지 않고 한계로 기록). 전량 sweep은 Valkey 호출 게이트를 공유하며 개별 종목 실패를 기록하고 계속한다.

초기 라우트:

```text
/dashboard
/markets/:market
/stocks/:symbol
/etfs
/etfs/:symbol
/strategies
/backtests/:id
/paper-trading
/models
/operations
/settings
```

## 8. 인증과 보안

- 단일 사용자를 위한 서버 세션과 `HttpOnly`, `Secure`, `SameSite` 쿠키를 사용한다.
- 인증 토큰을 브라우저 `localStorage`에 저장하지 않는다.
- 증권사 App Secret과 접근 토큰은 서버에서만 관리한다.
- 모의투자와 실전투자 키를 완전히 분리한다.
- Caddy로 HTTPS를 종료한다.
- 초기 운영 접근은 Tailscale 또는 IP 제한을 우선한다.
- 로그에서 토큰과 계좌번호를 마스킹한다.
- 실전 자동매매 활성 상태는 서버 재시작 시 자동 해제한다.
- 비상정지 상태와 주문 한도는 PostgreSQL에 영속화한다.

## 9. 테스트와 품질 게이트

### 9.1 백엔드

- pytest
- pytest-anyio
- Hypothesis
- Testcontainers PostgreSQL
- 외부 API의 HTTP wire 수준 fake
- 한국투자증권 모의투자 E2E

### 9.2 프론트엔드

- Vitest
- Testing Library
- Playwright
- 실제 브라우저 기반 반응형·접근성·상호작용 QA

### 9.3 필수 시나리오

- 미래정보 누출 방지
- 수정주가와 거래정지 처리
- 중복 주문 차단
- 부분체결 후 잔고 조정
- 서버 재시작 후 주문 복구
- 손실 한도 초과 주문 거절
- 오래된 시세를 사용한 주문 차단
- 모의·실전 자격증명 혼용 방지
- 비상정지 후 신규 주문 차단

## 10. 개발 도구와 CI

### Python

- uv
- Ruff `select = ["ALL"]`
- basedpyright `typeCheckingMode = "all"`
- pytest

### TypeScript

- Bun
- Biome
- `tsc --noEmit`
- `strict`
- `noUncheckedIndexedAccess`
- `exactOptionalPropertyTypes`
- `verbatimModuleSyntax`

### CI 게이트

```text
Backend
├─ ruff check
├─ ruff format --check
├─ basedpyright
└─ pytest

Frontend
├─ biome check
├─ tsc --noEmit
├─ vitest
└─ vite build

E2E
├─ Docker Compose
├─ PostgreSQL migration
└─ Playwright
```

## 11. 배포

| 역할 | 기술 |
|---|---|
| 컨테이너 | Docker, Docker Compose |
| 리버스 프록시·TLS | Caddy |
| 호스트 | 항상 실행되는 Linux 서버 |
| 프로세스 복구 | Docker restart policy 또는 systemd |
| CI/CD | GitHub Actions |
| DB 백업 | `pg_dump` 기반 암호화 백업, 후속 원격 복제 |

첫 배포는 단일 서버를 기준으로 한다. 고가용성보다 주문 안전, 데이터 복구, 운영 단순성을 우선한다.

## 12. 저장소 구조

```text
auto-stock-trading/
├─ backend/
│  ├─ pyproject.toml
│  ├─ src/auto_stock_trading/
│  │  ├─ domain/
│  │  ├─ application/
│  │  ├─ adapters/
│  │  ├─ api/
│  │  ├─ worker/
│  │  └─ settings/
│  └─ tests/
├─ frontend/
│  ├─ package.json
│  ├─ src/
│  │  ├─ app/
│  │  ├─ features/
│  │  ├─ pages/
│  │  ├─ components/
│  │  └─ api/
│  └─ tests/
├─ infra/
│  ├─ compose.yaml
│  └─ caddy/
├─ docs/
└─ .github/workflows/
```

## 13. 재검토 조건

다음 조건이 발생하면 기술 스택을 ADR로 재검토한다.

- PostgreSQL 파티셔닝만으로 시계열 조회 성능을 충족하지 못한다.
- 단일 서버가 데이터 수집 또는 모델 학습 부하를 감당하지 못한다.
- 다중 사용자나 타인 계좌 연결이 제품 범위에 포함된다.
- 두 번째 증권사 주문 연동이 확정된다.
- 전략 수와 모델 수 증가로 단순 모델 레지스트리가 운영 불가능해진다.
- 실시간 분봉 또는 틱 전략이 핵심 요구사항이 된다.
