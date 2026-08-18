import { useQuery } from "@tanstack/react-query";

import { fetchInstruments } from "../api/market-data";
import {
  fetchAccountSnapshots,
  fetchAutomation,
  fetchRiskLimits,
  fetchTradingOrders,
} from "../api/trading";
import { AppShell } from "../components/app-shell";
import { CoordinateCell, KpiGrid } from "../components/coordinate-cell";
import { SafetyBanner } from "../components/safety-banner";
import { StatusBadge } from "../components/status-badge";
import { UsageBar } from "../components/usage-bar";
import { decimalToNumber, formatDecimal, formatKstDateTime } from "../lib/format";
import type { AutomationEvent, RiskLimitUsage } from "../lib/trading";
import {
  automationLabel,
  hasFillInformation,
  limitLabel,
  orderStateLabel,
  positionReturnPct,
  positionWeightPct,
  usageLevel,
  usagePercent,
} from "../lib/trading";

const ORDER_ROWS = 20;
const PERCENT = 100;

const automationTone = (state: string): "danger" | "neutral" | "ok" | "warn" => {
  if (state === "running") {
    return "ok";
  }
  if (state === "emergency_stop") {
    return "danger";
  }
  return state === "paused" || state === "armed" ? "warn" : "neutral";
};

const signedTone = (value: number): "down" | "neutral" | "up" => {
  if (value > 0) {
    return "up";
  }
  return value < 0 ? "down" : "neutral";
};

const percentText = (value: string): string =>
  `${formatDecimal((decimalToNumber(value) * PERCENT).toFixed(2))}%`;

const usageValueText = (item: RiskLimitUsage): string => {
  if (item.current_value === null) {
    return "—";
  }
  return item.basis === "count"
    ? `${formatDecimal(item.current_value)}건`
    : percentText(item.current_value);
};

const usageLimitText = (item: RiskLimitUsage): string =>
  item.basis === "count" ? `${formatDecimal(item.limit_value)}건` : percentText(item.limit_value);

const basisNote = (item: RiskLimitUsage): string | undefined => {
  if (item.reason !== null) {
    return item.reason;
  }
  if (item.basis === "session_open_nav_ratio") {
    return "장 시작 NAV 기준";
  }
  return item.basis === "peak_nav_ratio" ? "고점 NAV 기준" : undefined;
};

const eventMessage = (event: AutomationEvent): string => {
  if (event.event_type === "state_change") {
    const from = event.previous_state === null ? "—" : automationLabel(event.previous_state);
    const to = event.state === null ? "—" : automationLabel(event.state);
    return `${from} → ${to}${event.reason_code === null ? "" : ` · ${event.reason_code}`}`;
  }
  return event.detail ?? event.event_type;
};

const eventLabel = (event: AutomationEvent): string =>
  event.event_type === "api_failure" ? "API 실패" : "상태 전이";

const clockText = (value: string): string => value.slice(0, 5);

export const Trading = () => {
  const automationQuery = useQuery({
    queryFn: fetchAutomation,
    queryKey: ["trading-automation"],
    refetchInterval: 60_000,
    retry: false,
  });
  const snapshotsQuery = useQuery({
    queryFn: () => fetchAccountSnapshots(1),
    queryKey: ["trading-account-snapshots"],
    retry: false,
  });
  const ordersQuery = useQuery({
    queryFn: () => fetchTradingOrders(ORDER_ROWS),
    queryKey: ["trading-orders", ORDER_ROWS],
    retry: false,
  });
  const limitsQuery = useQuery({
    queryFn: fetchRiskLimits,
    queryKey: ["trading-risk-limits"],
    refetchInterval: 60_000,
    retry: false,
  });
  const instrumentsQuery = useQuery({
    queryFn: fetchInstruments,
    queryKey: ["instruments"],
    retry: false,
  });

  const automation = automationQuery.data;
  const snapshot = snapshotsQuery.data?.snapshots[0];
  const limits = limitsQuery.data;
  const orders = ordersQuery.data?.orders ?? [];
  const nameBySymbol = new Map(
    (instrumentsQuery.data?.instruments ?? []).map((instrument) => [
      instrument.symbol,
      instrument.name,
    ]),
  );
  const usageByRule = new Map((limits?.items ?? []).map((item) => [item.rule_code, item]));
  const positions = snapshot?.positions ?? [];

  const sessionOpenNav = limits?.session_open_nav ?? null;
  const dailyPnl =
    snapshot === undefined || sessionOpenNav === null
      ? null
      : decimalToNumber(snapshot.nav) - decimalToNumber(sessionOpenNav);
  const unrealized =
    snapshot === undefined
      ? null
      : positions.reduce((sum, position) => sum + decimalToNumber(position.profit_loss), 0);
  const totalExposure = usageByRule.get("RISK_TOTAL_EXPOSURE");
  const openOrders = usageByRule.get("RISK_OPEN_ORDERS");
  const dailyLoss = usageByRule.get("RISK_DAILY_LOSS");
  const blockedState =
    automation !== undefined &&
    (automation.state === "paused" || automation.state === "emergency_stop");
  const blockReason = blockedState ? automation.reason_code : null;

  return (
    <AppShell
      active="trading"
      headerMeta={
        <>
          <StatusBadge
            kind={automation === undefined ? "neutral" : automationTone(automation.state)}
            label={`자동매매 ${automation === undefined ? "확인 중" : automationLabel(automation.state)}`}
          />
          <span>
            {limits === undefined
              ? "주문 허용시간 확인 중"
              : `주문 허용 ${clockText(limits.conditions.order_window_start)}~${clockText(limits.conditions.order_window_end)} KST`}
          </span>
          <span>
            {automation?.changed_at === undefined || automation.changed_at === null
              ? "상태 기록 없음"
              : `상태 변경 ${formatKstDateTime(automation.changed_at)}`}
          </span>
        </>
      }
      title="모의매매 콘솔"
    >
      <SafetyBanner
        description="이 화면의 주문은 모의계좌 계획 단계이며 증권사에 제출되지 않습니다. 활성화·일시정지·비상정지는 HTTP로 제공하지 않고 worker CLI에서만 수행합니다."
        level="warning"
        title="모의투자 전용 · 주문 제출 없음"
      />
      {automation !== undefined && blockReason !== null && (
        <SafetyBanner
          code={blockReason}
          description="신규 주문 생성이 차단된 상태입니다. 조회는 계속 가능하며 원인을 확인한 뒤 worker CLI로 상태를 되돌립니다. 보유 종목은 자동으로 청산하지 않습니다."
          level={automation.state === "emergency_stop" ? "danger" : "warning"}
          title={`자동매매 ${automationLabel(automation.state)}`}
        />
      )}

      <div className="work__body">
        <KpiGrid columns={7} label="계좌 상태 KPI">
          <CoordinateCell
            coord="A1"
            label="기준 NAV"
            sub={snapshot === undefined ? "계좌 조회 기록 없음" : formatKstDateTime(snapshot.as_of)}
            value={snapshot === undefined ? "—" : formatDecimal(snapshot.nav)}
          />
          <CoordinateCell
            coord="A2"
            label="장 시작 NAV"
            sub={limits?.basis_date ?? undefined}
            value={sessionOpenNav === null ? "—" : formatDecimal(sessionOpenNav)}
          />
          <CoordinateCell
            coord="A3"
            label="일일 손익"
            sub={
              dailyLoss?.current_value === undefined || dailyLoss.current_value === null
                ? undefined
                : percentText(dailyLoss.current_value)
            }
            tone={dailyPnl === null ? "neutral" : signedTone(dailyPnl)}
            value={dailyPnl === null ? "—" : formatDecimal(String(dailyPnl))}
          />
          <CoordinateCell
            coord="A4"
            label="평가손익"
            sub={snapshot === undefined ? undefined : `보유 ${String(positions.length)}종목`}
            tone={unrealized === null ? "neutral" : signedTone(unrealized)}
            value={unrealized === null ? "—" : formatDecimal(String(unrealized))}
          />
          <CoordinateCell
            coord="A5"
            label="현금"
            sub={
              snapshot === undefined
                ? undefined
                : `주문가능 ${formatDecimal(snapshot.orderable_cash)}`
            }
            value={snapshot === undefined ? "—" : formatDecimal(snapshot.cash_balance)}
          />
          <CoordinateCell
            coord="A6"
            label="투자 비중"
            sub={
              totalExposure === undefined
                ? undefined
                : `한도 ${percentText(totalExposure.limit_value)}`
            }
            value={
              totalExposure?.current_value === undefined || totalExposure.current_value === null
                ? "—"
                : percentText(totalExposure.current_value)
            }
          />
          <CoordinateCell
            coord="A7"
            label="미체결"
            sub={
              openOrders === undefined
                ? undefined
                : `한도 ${formatDecimal(openOrders.limit_value)}건`
            }
            value={
              openOrders?.current_value === undefined || openOrders.current_value === null
                ? "—"
                : `${formatDecimal(openOrders.current_value)}건`
            }
          />
        </KpiGrid>

        <div className="board">
          <div className="board__main">
            <section className={orders.length === 0 ? "card card--empty" : "card"}>
              <div className="card__head">
                <h2>
                  <span className="card__coord">B</span> 주문 내역
                </h2>
                {orders.length > 0 && (
                  <StatusBadge
                    kind="neutral"
                    label={`전체 ${String(orders.length)}건 · 거절 ${String(orders.filter((order) => order.state === "rejected").length)}건`}
                  />
                )}
              </div>
              <div className="card__body">
                {ordersQuery.isError ? (
                  <p className="inline-error" role="alert">
                    주문 목록을 불러오지 못했습니다.
                    <button
                      className="retry-button"
                      onClick={() => {
                        void ordersQuery.refetch();
                      }}
                      type="button"
                    >
                      다시 시도
                    </button>
                  </p>
                ) : orders.length === 0 ? (
                  "저장된 주문이 없습니다. 주문 허용시간 안에 worker CLI로 계획을 실행하면 계획된 주문과 거절 사유가 여기에 남습니다."
                ) : (
                  <table className="grid-table grid-table--stack">
                    <thead>
                      <tr>
                        <th scope="col">시각</th>
                        <th scope="col">주문 ID</th>
                        <th scope="col">종목</th>
                        <th scope="col">구분</th>
                        <th scope="col">수량</th>
                        <th scope="col">체결</th>
                        <th scope="col">지정가</th>
                        <th scope="col">상태</th>
                      </tr>
                    </thead>
                    <tbody>
                      {orders.map((order) => (
                        <tr key={order.client_order_id}>
                          <td className="is-name">{formatKstDateTime(order.created_at)}</td>
                          <td data-label="주문 ID">
                            <code>{order.client_order_id.slice(0, 12)}…</code>
                          </td>
                          <td data-label="종목">
                            {nameBySymbol.get(order.symbol) ?? order.symbol} {order.symbol}
                          </td>
                          <td
                            className={order.side === "buy" ? "is-up" : "is-down"}
                            data-label="구분"
                          >
                            {order.side === "buy" ? "매수" : "매도"}
                          </td>
                          <td data-label="수량">{formatDecimal(String(order.quantity))}</td>
                          <td data-label="체결">
                            {hasFillInformation(order.state)
                              ? formatDecimal(String(order.filled_quantity))
                              : "—"}
                          </td>
                          <td data-label="지정가">
                            {order.limit_price === null ? "—" : formatDecimal(order.limit_price)}
                          </td>
                          <td data-label="상태">
                            <StatusBadge
                              kind={
                                order.state === "rejected"
                                  ? "danger"
                                  : order.state === "filled"
                                    ? "ok"
                                    : "accent"
                              }
                              label={
                                order.reject_code === null
                                  ? orderStateLabel(order.state)
                                  : `${orderStateLabel(order.state)} · ${order.reject_code}`
                              }
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <div className="card__note">
                주문마다 결정적 식별자로 중복 제출을 막습니다 · 상태 흐름은 계획 → 제출 → 부분체결 →
                체결이며 거절·취소로 종료될 수 있습니다 · 주문 제출 단계가 아직 없어 체결 열은 값을
                만들지 않고 줄표로 둡니다
              </div>
            </section>

            <section className={positions.length === 0 ? "card card--empty" : "card"}>
              <div className="card__head">
                <h2>
                  <span className="card__coord">C</span> 보유 포지션
                </h2>
                {snapshot !== undefined && (
                  <StatusBadge
                    kind="neutral"
                    label={`계좌 ${snapshot.account_reference} · 기준 ${formatKstDateTime(snapshot.as_of)}`}
                  />
                )}
              </div>
              <div className="card__body">
                {snapshot === undefined ? (
                  "계좌 스냅샷이 없습니다. worker CLI의 계좌 조회를 실행하면 잔고와 보유 종목이 표시됩니다."
                ) : positions.length === 0 ? (
                  "이 스냅샷에 보유 종목이 없습니다. 평가금액 0원은 조회된 사실이며 추정하지 않습니다."
                ) : (
                  <table className="grid-table grid-table--stack">
                    <thead>
                      <tr>
                        <th scope="col">종목</th>
                        <th scope="col">수량</th>
                        <th scope="col">평균단가</th>
                        <th scope="col">현재가</th>
                        <th scope="col">평가금액</th>
                        <th scope="col">평가손익</th>
                        <th scope="col">수익률</th>
                        <th scope="col">비중</th>
                      </tr>
                    </thead>
                    <tbody>
                      {positions.map((position) => {
                        const returnPct = positionReturnPct(position);
                        const weightPct = positionWeightPct(
                          position.evaluation_amount,
                          snapshot.nav,
                        );
                        return (
                          <tr key={position.symbol}>
                            <td className="is-name">
                              {nameBySymbol.get(position.symbol) ?? position.symbol}{" "}
                              {position.symbol}
                            </td>
                            <td data-label="수량">{formatDecimal(String(position.quantity))}</td>
                            <td data-label="평균단가">{formatDecimal(position.average_price)}</td>
                            <td data-label="현재가">{formatDecimal(position.current_price)}</td>
                            <td data-label="평가금액">
                              {formatDecimal(position.evaluation_amount)}
                            </td>
                            <td
                              className={
                                decimalToNumber(position.profit_loss) >= 0 ? "is-up" : "is-down"
                              }
                              data-label="평가손익"
                            >
                              {formatDecimal(position.profit_loss)}
                            </td>
                            <td data-label="수익률">
                              {returnPct === null ? "—" : `${formatDecimal(String(returnPct))}%`}
                            </td>
                            <td data-label="비중">
                              {weightPct === null ? "—" : `${formatDecimal(String(weightPct))}%`}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </div>
              <div className="card__note">
                보유 수량·평균단가·평가금액은 증권사 잔고 응답 값이며 계좌번호는 해시 참조로만
                표시합니다 · 수익률은 평균단가×수량 기준입니다
              </div>
            </section>
          </div>

          <div className="board__aside">
            <section className={limits === undefined ? "card card--empty" : "card"}>
              <div className="card__head">
                <h2>
                  <span className="card__coord">D</span> 위험 한도 소진율
                </h2>
                {limits !== undefined && (
                  <StatusBadge kind="neutral" label={`${String(limits.items.length)}항목`} />
                )}
              </div>
              <div className="card__body">
                {limitsQuery.isError ? (
                  <p className="inline-error" role="alert">
                    위험 한도를 불러오지 못했습니다.
                    <button
                      className="retry-button"
                      onClick={() => {
                        void limitsQuery.refetch();
                      }}
                      type="button"
                    >
                      다시 시도
                    </button>
                  </p>
                ) : limits === undefined ? (
                  "한도 소진율을 불러오는 중입니다."
                ) : (
                  <>
                    <div className="usage-list">
                      {limits.items.map((item) => (
                        <UsageBar
                          current={usageValueText(item)}
                          key={item.rule_code}
                          label={limitLabel(item.rule_code)}
                          level={usageLevel(item.usage_ratio)}
                          limit={usageLimitText(item)}
                          note={basisNote(item)}
                          percent={usagePercent(item.usage_ratio)}
                        />
                      ))}
                    </div>
                    <dl className="fact-list">
                      <div>
                        <dt>주문 허용시간</dt>
                        <dd>
                          {clockText(limits.conditions.order_window_start)}~
                          {clockText(limits.conditions.order_window_end)} KST
                        </dd>
                      </div>
                      <div>
                        <dt>기준가 최대 지연</dt>
                        <dd>{String(limits.conditions.quote_max_age_seconds)}초</dd>
                      </div>
                      <div>
                        <dt>지정가 허용 범위</dt>
                        <dd>기준가 ±{percentText(limits.conditions.price_band)}</dd>
                      </div>
                      <div>
                        <dt>API 실패 집계 창</dt>
                        <dd>{String(limits.conditions.api_failure_window_seconds)}초</dd>
                      </div>
                      <div>
                        <dt>소진율 기준 시각</dt>
                        <dd>{formatKstDateTime(limits.evaluated_at)}</dd>
                      </div>
                    </dl>
                  </>
                )}
              </div>
              <div className="card__note">
                한도는 거래 안전 정책 §3·§4가 원본이며 화면은 서버가 준 값만 표시합니다 · 체결 후
                예상 상태로 검사하고 여러 한도가 겹치면 가장 엄격한 결과를 적용합니다 · 업종 분류
                원천이 없어 모든 종목이 미분류로 판정됩니다
              </div>
            </section>

            <section
              className={
                automation === undefined || automation.events.length === 0
                  ? "card card--empty"
                  : "card"
              }
            >
              <div className="card__head">
                <h2>
                  <span className="card__coord">E</span> 주문·위험 이벤트
                </h2>
                {automation !== undefined && (
                  <StatusBadge
                    kind={automationTone(automation.state)}
                    label={automationLabel(automation.state)}
                  />
                )}
              </div>
              <div className="card__body">
                {automationQuery.isError ? (
                  <p className="inline-error" role="alert">
                    자동매매 상태를 불러오지 못했습니다.
                    <button
                      className="retry-button"
                      onClick={() => {
                        void automationQuery.refetch();
                      }}
                      type="button"
                    >
                      다시 시도
                    </button>
                  </p>
                ) : automation === undefined || automation.events.length === 0 ? (
                  "기록된 상태 전이와 외부 API 실패가 없습니다."
                ) : (
                  <ul className="event-list">
                    {automation.events.map((event) => (
                      <li key={`${event.event_type}-${event.occurred_at}-${event.detail ?? ""}`}>
                        <span className="event-list__time">
                          {formatKstDateTime(event.occurred_at)}
                        </span>
                        <span
                          className={
                            event.event_type === "api_failure"
                              ? "event-list__level event-list__level--danger"
                              : "event-list__level"
                          }
                        >
                          {eventLabel(event)}
                        </span>
                        <span className="event-list__message">{eventMessage(event)}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="card__note">
                상태 전이는 읽기 API가 아니라 worker CLI에서만 수행합니다{" "}
                <code>
                  uv run python -m auto_stock_trading.worker.execution.planning --automation paused
                </code>
              </div>
            </section>
          </div>
        </div>
      </div>
    </AppShell>
  );
};
