# 5단계 ETF 탐색 검증

- 상태: 검증 완료 (마스터·NAV 스냅샷·순위·상세 범위)
- 검증일: 2026-08-18
- 관련 계약: [ETF 탐색 데이터 계약](../data/etf-exploration-data-contract.md)
- 관련 API: [시장 데이터 읽기 API](../api/market-data-api.md)

## 실제 수집 검증 (2026-08-18)

| 항목 | 값 |
|---|---|
| 마스터 수집 | KIS 공식 마스터 파일에서 KOSPI ETF 1,163종목 적재(현재 버전 1,163행), 원본은 Base64 봉투로 보존 |
| 마스터 멱등 | 재수집 후에도 1,163행·전부 `version=1` 유지. 통합 테스트에서 이름 변경이 이전 버전 보존 새 버전이 됨을 검증 |
| NAV 전량 수집 | 1차 sweep 23분에 1,125/1,163 수집, 일시 오류 38건은 계약대로 `partial_failure`로 기록 후 계속. 같은 코드 경로 재수집으로 38건 전부 채워 전량 1,163 스냅샷 확보 |
| KODEX 200 대조 | NAV·괴리율·추적오차·운용사(삼성자산운용)·대표지수(KOSPI200)가 KIS 원본 응답과 일치, 분배율은 저장된 분배금 4회 합 ÷ 현재가 수동 계산과 일치 |
| 읽기 API | 목록 1,163건(스냅샷 없는 종목 `null`), 상세·분배율 fail-closed(`MISSING_DISTRIBUTIONS` 등), 미등록 404 확인 |

## 실측 결과 (2026-08-18)

- 1차 전량 sweep: 소요 약 23분(00:03~00:26 UTC), 1,125건 수집·38건 일시 실패(재조회 시 정상 응답 — 호출 한도성 오류로 판단). 실패는 `operations.api_sync_status`에 `partial_failure`(38 of 1163)로 기록됐고 성공분은 보존됐다.
- 누락 38건은 동일 어댑터·저장소 경로 재수집으로 채워 전량 1,163 스냅샷을 확보했다.
- HTTP 대조: 목록 1,163건(전부 스냅샷 보유), 순자산 상위 KODEX 200 260,643억원 · TIGER 미국S&P500 209,545억원 · TIGER 미국나스닥100 117,922억원. KODEX 200 상세 NAV 113,074.10 · 괴리율 -0.18% · 운용사 삼성자산운용 — KIS 원본 응답과 일치.
- 분배율: KODEX 200 최근 12개월 분배금 4회 합 849원 ÷ 현재가 112,875원 × 100 = 0.75% — 수동 계산과 일치. 분배금 이력이 없는 ETF는 `MISSING_DISTRIBUTIONS`로 빈 값.

## 화면 검증

- ETF 탐색(`/etf`, 승인 시안 3a): A 요약 KPI 6(종목 수·스냅샷 보유·상승·하락·최대 괴리율·데이터 상태), B 순위표(등락률·거래량·괴리율·추적오차·순자산 정렬, 괴리율·추적오차는 절대값 기준), C 투자자별 순매수(수집된 ETF만, 나머지 빈 상태), D 선택 ETF 상세(NAV·괴리율·추적오차·배수·운용사·지수·상장일·순자산·분배율).
- e2e 15건(운영 개요·시장 데이터·기업 분석·ETF 탐색·갤러리 × 3폭)과 390·768·1360px·다크 스크린샷 육안 QA를 통과했다. 수급 미수집 ETF에서는 수급 API를 호출하지 않아 콘솔 오류가 없다.

## 자동 검증 명령

```bash
cd backend
uv run pytest tests/brokers/test_kis_master_files.py tests/brokers/test_kis_etf_nav.py \
  tests/market_data/test_etf_application.py tests/market_data/test_etf_store_integration.py \
  tests/api/test_market_data_etf_api.py
cd frontend
bun run test tests/etf.test.ts
bun run e2e
```

## 남은 범위

- 거래대금·기간 수익률 순위(ETF 일봉 확장), 투자자별 순매수 순위(전량 수급 sweep)
- NAV·구성종목 이력 정규화, 상장폐지 처리, 미국 ETF
- 연환산 분배율(지급 예상 횟수 근거 확보 시)
