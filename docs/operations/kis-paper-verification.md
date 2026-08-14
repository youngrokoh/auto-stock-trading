# KIS 모의환경 검증 런북

- 상태: 실제 모의 API 반복 수집·프로세스 간 토큰 재사용 검증 완료
- 기준일: 2026-08-14
- 대상: 삼성전자 `005930`, KODEX 200 `069500`
- 관련 QA: [2단계 시장 데이터 수직 슬라이스 검증](../qa/phase-2-market-data-verification.md)

## 1. 안전 경계

- 이 검증에는 모의투자 App Key와 App Secret만 사용한다.
- 실전투자 키는 별도 비밀번호 관리자에 보관하고 파일, 환경변수와 Compose에 연결하지 않는다.
- 키 값은 채팅, 문서, Git, 명령행 인자, 브라우저 번들과 로그에 입력하지 않는다.
- `.secrets/`는 Git과 Docker 빌드 컨텍스트에서 제외되며 파일 권한은 소유자 읽기·쓰기만 허용한다.
- `infra/compose.kis-paper.yaml`은 `AUTO_STOCK_KIS_ENVIRONMENT=paper`를 강제한다.

[KIS API 호출 유량 안내](https://apiportal.koreainvestment.com/community/10000000-0000-0011-0000-000000000001/post/d0d1a83f-6f8d-4437-9700-6d26702fd989)에 따른 모의투자 REST 호출 제한은 초당 1건이다. 클라이언트의 모든 인증·시세 요청은 1.05초 이상의 간격으로 직렬화한다. 실전 환경의 호출량을 늘리는 최적화는 이 검증 범위에 포함하지 않는다.

## 2. 모의 키를 로컬 secret 파일에 입력

저장소 안의 어느 하위 디렉터리에서도 실행할 수 있다. zsh에서 아래 코드 블록을 한 번에 하나씩 실행한다. `read -rs`를 사용하므로 키 값은 셸 이력과 화면에 표시되지 않는다.

```zsh
KIS_SECRET_DIR="$(git rev-parse --show-toplevel)/.secrets"
mkdir -p "$KIS_SECRET_DIR"
chmod 700 "$KIS_SECRET_DIR"
```

App Key를 입력하고 바로 저장한다.

```zsh
read -rs "KIS_PAPER_APP_KEY?KIS 모의투자 App Key를 붙여 넣고 Enter: "; echo; if [[ -n "$KIS_PAPER_APP_KEY" ]]; then (umask 077; printf '%s' "$KIS_PAPER_APP_KEY" > "$KIS_SECRET_DIR/kis-paper-app-key"); chmod 600 "$KIS_SECRET_DIR/kis-paper-app-key"; echo "App Key 저장 성공"; else echo "App Key가 비어 있어 저장 실패"; fi; unset KIS_PAPER_APP_KEY
```

App Secret도 같은 방식으로 저장한다.

```zsh
read -rs "KIS_PAPER_APP_SECRET?KIS 모의투자 App Secret을 붙여 넣고 Enter: "; echo; if [[ -n "$KIS_PAPER_APP_SECRET" ]]; then (umask 077; printf '%s' "$KIS_PAPER_APP_SECRET" > "$KIS_SECRET_DIR/kis-paper-app-secret"); chmod 600 "$KIS_SECRET_DIR/kis-paper-app-secret"; echo "App Secret 저장 성공"; else echo "App Secret이 비어 있어 저장 실패"; fi; unset KIS_PAPER_APP_SECRET
```

내용은 출력하지 않고 존재·크기·권한만 확인한다.

```zsh
test -s "$KIS_SECRET_DIR/kis-paper-app-key"
test -s "$KIS_SECRET_DIR/kis-paper-app-secret"
stat -f '권한=%Sp 크기=%z 파일=%N' "$KIS_SECRET_DIR"/kis-paper-app-*
unset KIS_SECRET_DIR
```

출력에서 두 파일 모두 권한이 `-rw-------`이고 크기가 0보다 큰지 확인한다. 키 내용은 출력하지 않는다.

## 3. 기반 서비스 실행

```bash
docker compose -f infra/compose.yaml up --build -d --wait --wait-timeout 300
docker compose -f infra/compose.yaml ps -a
```

PostgreSQL, Valkey와 API가 healthy이고 worker가 실행 중이며 migration이 종료 코드 0인지 확인한다. 기본 Compose는 키를 마운트하지 않으며 평상시 실행과 상태 확인에 사용한다.

## 4. 첫 번째 수집

모의전용 override를 사용해 일회성 worker 컨테이너에서 실행한다.

```bash
docker compose \
  -f infra/compose.yaml \
  -f infra/compose.kis-paper.yaml \
  run --rm --no-deps worker \
  python -m auto_stock_trading.worker.market_data \
  --start-date 2026-08-01 \
  --end-date 2026-08-14
```

인증·현재가·일봉 요청이 성공하고 두 종목코드가 처리되어야 한다. KIS 모의환경은 종목 상세 `CTPF1002R`을 지원하지 않으므로 이를 호출하지 않고 일봉 요약에서 종목명을 구성한다. 로그에는 HTTP 메서드, 경로, 상태와 소요시간만 표시되어야 한다.

## 5. 첫 수집 기준값 기록

```bash
docker compose -f infra/compose.yaml exec -T postgres \
  psql -U auto_stock -d auto_stock_trading -P pager=off -c "
SELECT 'instrument' AS entity, count(*) AS rows
FROM reference.instrument WHERE symbol IN ('005930', '069500')
UNION ALL
SELECT 'quote', count(*) FROM market.quote q
JOIN reference.instrument i ON i.id = q.instrument_id
WHERE i.symbol IN ('005930', '069500')
UNION ALL
SELECT 'daily_bar', count(*) FROM market.market_bar b
JOIN reference.instrument i ON i.id = b.instrument_id
WHERE i.symbol IN ('005930', '069500')
UNION ALL
SELECT 'raw_response', count(*) FROM operations.raw_api_response
WHERE request_fingerprint LIKE ANY (ARRAY['%:005930%', '%:069500%'])
UNION ALL
SELECT 'successful_sync', count(*) FROM operations.api_sync_status
WHERE symbol IN ('005930', '069500') AND state = 'success';"
```

2026-08-14 실제 검증 기준값은 종목 2개, 최신 현재가 2개, 일봉 20개, 성공 상태 2개다. 원본 응답은 모의환경에서 종목당 현재가·일봉 2개이므로 기존 데이터가 전혀 없다면 4개다.

## 6. 동일 범위 재수집과 멱등성 확인

4단계 명령을 같은 날짜로 한 번 더 실행하고 5단계 SQL을 다시 실행한다.

첫 worker는 Valkey에 유효한 공유 토큰이 없을 때만 `/oauth2/tokenP`를 호출한다. 같은 환경과 자격증명을 사용하는 두 번째 독립 컨테이너는 Valkey 토큰을 재사용해야 하며 로그에 `/oauth2/tokenP`가 다시 나타나면 실패다. 인증과 시세 요청은 모든 프로세스를 합쳐 1.05초 간격을 공유한다. Valkey를 사용할 수 없으면 개별 토큰 발급으로 우회하지 않고 수집이 실패해야 한다.

- `instrument`, `quote`, `daily_bar`, `successful_sync` 행 수는 첫 실행과 같아야 한다.
- `raw_response`만 정확히 4개 증가해야 한다.
- 수집 상태는 두 종목 모두 `success`여야 한다.

2026-08-14 ADR-0005 구현 검증에서는 첫 독립 worker가 공유 토큰을 저장한 뒤 다음 독립 worker가 `KIS shared access token reused`를 기록했다. 두 번째 worker 로그에는 `/oauth2/tokenP`가 없었고 현재가·일봉 GET 4건이 모두 `200`이었다. 두 번 추가 수집 후 정규화 행 수는 종목 2, 현재가 2, 일봉 20, 성공 상태 2로 유지됐고 누적 원본 응답은 기존 8건에서 16건으로 증가했다.

## 7. 읽기 API와 원본 보안 확인

```bash
curl --fail --silent http://127.0.0.1:8000/api/market-data/instruments/005930 \
  | python3 -m json.tool
curl --fail --silent http://127.0.0.1:8000/api/market-data/instruments/005930/quote \
  | python3 -m json.tool
curl --fail --silent \
  'http://127.0.0.1:8000/api/market-data/instruments/005930/daily-bars?start_date=2026-08-01&end_date=2026-08-14' \
  | python3 -m json.tool

docker compose -f infra/compose.yaml exec -T postgres \
  psql -U auto_stock -d auto_stock_trading -P pager=off -c "
SELECT count(*) AS credential_fields_in_raw_payload
FROM operations.raw_api_response
WHERE payload_json::jsonb ?| ARRAY['access_token', 'appkey', 'appsecret'];"
```

- API의 `source`는 `KIS`여야 한다.
- `received_at`과 현재가 `as_of`는 UTC 수신시각이다.
- 일봉은 `adjusted=false`이고 거래일 범위가 요청과 일치해야 한다.
- 원본 payload의 인증 필드 수는 0이어야 한다.
- 값과 거래일은 KIS 모의투자 화면과 대조한다.

## 8. 결과 기록과 키 보관

검증 결과, 실행시각, 행 수와 차이만 QA 문서에 기록한다. 시세 응답 전문, 계좌번호와 키는 기록하지 않는다.

반복 수집에 계속 사용할 경우 `.secrets/` 권한을 유지한다. 검증 후 로컬 보관이 필요 없다면 다음 두 파일만 명시적으로 삭제한다.

```bash
rm .secrets/kis-paper-app-key .secrets/kis-paper-app-secret
rmdir .secrets
```

데이터 볼륨을 보존하면서 서비스를 종료하려면 `docker compose -f infra/compose.yaml down`을 사용한다. `down -v`는 사용하지 않는다.
