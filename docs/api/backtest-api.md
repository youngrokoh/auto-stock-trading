# 백테스트 읽기 API

- 상태: 구현됨
- 구현일: 2026-08-18
- 기준 경로: `/api/backtests`
- 관련 계약: [백테스트·규칙형 전략 계약](../data/backtest-strategy-contract.md)

## 범위

저장된 백테스트 실행 기록을 읽기 전용으로 제공한다. 실행 자체는 worker CLI
(`uv run python -m auto_stock_trading.worker.backtests`)로 수행하며, HTTP로 실행을 트리거하는
엔드포인트는 제공하지 않는다. 주문·계좌·전략 활성화 기능은 포함하지 않는다(ADR-0004 경계).

| 메서드 | 경로 | 응답 |
|---|---|---|
| `GET` | `/api/backtests` | 실행 기록 목록 (생성 시각 내림차순, `limit` 기본 50 · 1~200) |
| `GET` | `/api/backtests/{run_id}` | 실행 상세와 성과 지표 |
| `GET` | `/api/backtests/{run_id}/trades` | 신호별 체결 기록 (순번 오름차순) |
| `GET` | `/api/backtests/{run_id}/equity` | 일별 현금·평가액·NAV 곡선 |

## 응답 계약

- 모든 실행은 전략 이름·버전, canonical JSON 파라미터, 창(`range_start`~`range_end`),
  초기 현금, 신호 가격 방식(`signal_method`), 엔진 알고리즘 버전, 비용 규칙 버전 목록과 입력
  데이터 계보(입력 일봉 버전 해시 `trading_date:version` sha256, 기업행사 버전 해시
  `ex_date:action_key:version` sha256, 신호·벤치마크 수정주가 데이터셋 ID)를 항상 포함한다.
- 실패한 실행도 `status="failed"`와 계약의 사유 코드(`missing_confirmed_bar`,
  `missing_adjusted_dataset`, `missing_calendar_coverage`, `uncovered_cost_date`,
  `lookahead_input`, `invalid_input`)로 조회된다. 실패 실행의 `metrics`는 `null`이고 체결·NAV는
  빈 목록이다.
- 성과 지표는 총수익률·비용 전 수익률·벤치마크 수익률·초과수익·MDD(음수 퍼센트)·샤프지수
  (표준편차 0이면 `null`)·연환산 회전율과 수수료·슬리피지·세금 합계, 체결 건수다. 금액과
  비율은 문자열 십진수로 직렬화된다.
- 체결 기록은 신호일·체결일·매수매도·사유(`golden_cross`·`dead_cross`·`rsi_overbought`)·수량·
  체결가(시가 원문)·수수료·슬리피지·세금을 포함하고, 체결하지 못한 신호는 `execution_date`가
  `null`이며 `skip_reason`(`window_end`·`already_positioned`·`no_position`·`insufficient_cash`)이
  남는다.
- 없는 `run_id`는 `404`, UUID가 아닌 `run_id`와 범위를 벗어난 `limit`은 `422`다.
