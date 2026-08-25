import { useQuery } from "@tanstack/react-query";

import { fetchCostRules } from "../api/settings";
import { fetchAutomation, fetchRiskLimits } from "../api/trading";
import { AppShell } from "../components/app-shell";
import { CoordinateCell, KpiGrid } from "../components/coordinate-cell";
import { SafetyBanner } from "../components/safety-banner";
import { StatusBadge } from "../components/status-badge";
import { formatKstDateTime } from "../lib/format";
import { isResearchAssumption, ratePercent } from "../lib/settings";
import {
  type AutomationEvent,
  automationLabel,
  eventTypeLabel,
  isAlertEvent,
  limitLabel,
} from "../lib/trading";

const EVENT_ROWS = 20;

const transitionText = (event: AutomationEvent): string => {
  if (event.event_type !== "state_change") {
    return event.reason_code ?? event.detail ?? "—";
  }
  const from = event.previous_state === null ? "—" : automationLabel(event.previous_state);
  const to = event.state === null ? "—" : automationLabel(event.state);
  return `${from} → ${to}`;
};

export const SettingsAndAudit = () => {
  const automationQuery = useQuery({
    queryFn: fetchAutomation,
    queryKey: ["trading-automation"],
    refetchInterval: 60_000,
    retry: false,
  });
  const limitsQuery = useQuery({
    queryFn: fetchRiskLimits,
    queryKey: ["trading-risk-limits"],
    retry: false,
  });
  const costsQuery = useQuery({
    queryFn: fetchCostRules,
    queryKey: ["settings-cost-rules"],
    retry: false,
  });

  const automation = automationQuery.data;
  const limits = limitsQuery.data;
  const costs = costsQuery.data;
  const events = automation?.events.slice(0, EVENT_ROWS) ?? [];
  const currentCost = costs?.rules.find((rule) => rule.current);
  const alerts = events.filter((event) => isAlertEvent(event.event_type, event.reason_code));

  return (
    <AppShell
      active="settings"
      headerMeta={
        <>
          <StatusBadge kind="neutral" label="조회 전용" />
          <span>
            {automation === undefined
              ? "상태 확인 중"
              : `자동매매 ${automationLabel(automation.state)}`}
          </span>
          <span>
            {costs === undefined ? "비용 규칙 확인 중" : `비용 기준 ${costs.evaluated_on}`}
          </span>
        </>
      }
      title="설정과 감사"
    >
      <SafetyBanner
        description="이 화면에서 값을 바꿀 수 없습니다. 위험 한도와 거래비용은 코드 상수이며, 완화하려면 정책 문서를 먼저 고치고 사람의 승인을 받아야 합니다. 자동매매 상태 전이도 worker CLI에서만 수행합니다."
        level="info"
        title="조회 전용 · 값 변경 경로 없음"
      />

      <div className="work__body">
        <KpiGrid label="설정 요약 KPI">
          <CoordinateCell
            coord="A1"
            label="자동매매"
            sub={
              automation?.changed_at === undefined || automation.changed_at === null
                ? "기록 없음"
                : formatKstDateTime(automation.changed_at)
            }
            value={automation === undefined ? "—" : automationLabel(automation.state)}
          />
          <CoordinateCell
            coord="A2"
            label="상태 사유"
            sub={automation?.stale_reason_code ?? undefined}
            value={automation?.reason_code ?? "—"}
          />
          <CoordinateCell
            coord="A3"
            label="위험 한도"
            sub="정책 §3"
            value={limits === undefined ? "—" : `${String(limits.items.length)}종`}
          />
          <CoordinateCell
            coord="A4"
            label="비용 규칙"
            sub={currentCost === undefined ? undefined : `현행 ${currentCost.version}`}
            value={costs === undefined ? "—" : `${String(costs.rules.length)}세트`}
          />
          <CoordinateCell
            coord="A5"
            label="기록된 이벤트"
            sub={`최근 ${String(EVENT_ROWS)}건 표시`}
            value={automation === undefined ? "—" : `${String(automation.events.length)}건`}
          />
          <CoordinateCell
            coord="A6"
            label="주의 이벤트"
            sub={alerts.length === 0 ? "정상 흐름만" : "확인이 필요합니다"}
            value={automation === undefined ? "—" : `${String(alerts.length)}건`}
          />
        </KpiGrid>

        <div className="board">
          <div className="board__main">
            <section className={events.length === 0 ? "card card--empty" : "card"}>
              <div className="card__head">
                <h2>
                  <span className="card__coord">A</span> 상태 전이와 감사 기록
                </h2>
                {alerts.length > 0 && (
                  <StatusBadge kind="warn" label={`주의 ${String(alerts.length)}건`} />
                )}
              </div>
              <div className="card__body">
                {automationQuery.isError ? (
                  <p className="inline-error" role="alert">
                    감사 기록을 불러오지 못했습니다.
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
                ) : events.length === 0 ? (
                  "기록된 이벤트가 없습니다. 자동매매 상태를 전이하거나 주문을 실행하면 여기에 남습니다."
                ) : (
                  <table className="grid-table grid-table--stack">
                    <thead>
                      <tr>
                        <th scope="col">시각</th>
                        <th scope="col">유형</th>
                        <th scope="col">내용</th>
                        <th scope="col">사유</th>
                      </tr>
                    </thead>
                    <tbody>
                      {events.map((event) => (
                        <tr key={`${event.occurred_at}-${event.event_type}-${event.state ?? ""}`}>
                          <td className="is-name">{formatKstDateTime(event.occurred_at)}</td>
                          <td data-label="유형">
                            <StatusBadge
                              kind={
                                isAlertEvent(event.event_type, event.reason_code)
                                  ? "warn"
                                  : "neutral"
                              }
                              label={eventTypeLabel(event.event_type)}
                            />
                          </td>
                          <td data-label="내용">{transitionText(event)}</td>
                          <td data-label="사유">
                            {event.reason_code === null ? "—" : <code>{event.reason_code}</code>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <p className="card__note">
                화면과 감사 기록이 같은 사유 코드를 씁니다. 상태 전이는 worker CLI에서만 일어납니다.
              </p>
            </section>

            <section className={costs === undefined ? "card card--empty" : "card"}>
              <div className="card__head">
                <h2>
                  <span className="card__coord">C</span> 거래비용 규칙
                </h2>
                {currentCost !== undefined && (
                  <StatusBadge kind="neutral" label={`현행 ${currentCost.version}`} />
                )}
              </div>
              <div className="card__body">
                {costsQuery.isError ? (
                  <p className="inline-error" role="alert">
                    비용 규칙을 불러오지 못했습니다.
                    <button
                      className="retry-button"
                      onClick={() => {
                        void costsQuery.refetch();
                      }}
                      type="button"
                    >
                      다시 시도
                    </button>
                  </p>
                ) : costs === undefined ? (
                  "비용 규칙을 불러오는 중입니다."
                ) : (
                  <table className="grid-table grid-table--stack">
                    <thead>
                      <tr>
                        <th scope="col">규칙</th>
                        <th scope="col">적용 시작</th>
                        <th scope="col">수수료</th>
                        <th scope="col">슬리피지(주식/ETF)</th>
                        <th scope="col">매도세(KOSPI/KOSDAQ)</th>
                        <th scope="col">근거</th>
                      </tr>
                    </thead>
                    <tbody>
                      {costs.rules.map((rule) => (
                        <tr key={rule.version}>
                          <td className="is-name">
                            <code>{rule.version}</code>
                            {rule.current && (
                              <>
                                {" "}
                                <StatusBadge kind="ok" label="현행" />
                              </>
                            )}
                          </td>
                          <td data-label="적용 시작">{rule.effective_from}</td>
                          <td data-label="수수료">{ratePercent(rule.fee_rate)}</td>
                          <td data-label="슬리피지">
                            {ratePercent(rule.stock_slippage_rate)} /{" "}
                            {ratePercent(rule.etf_slippage_rate)}
                          </td>
                          <td data-label="매도세">
                            {ratePercent(rule.kospi_stock_sell_tax_rate)} /{" "}
                            {ratePercent(rule.kosdaq_stock_sell_tax_rate)}
                          </td>
                          <td data-label="근거">
                            <StatusBadge
                              kind={isResearchAssumption(rule.source) ? "warn" : "neutral"}
                              label={isResearchAssumption(rule.source) ? "연구 가정" : "공식 고시"}
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <p className="card__note">
                과거 백테스트에는 당시 유효했던 규칙을 적용하며 현재 규칙으로 소급하지 않습니다.
                ETF는 모든 세트에서 증권거래세가 면제됩니다.
              </p>
            </section>
          </div>

          <div className="board__side">
            <section className={limits === undefined ? "card card--empty" : "card"}>
              <div className="card__head">
                <h2>
                  <span className="card__coord">B</span> 위험 한도
                </h2>
                <StatusBadge kind="neutral" label="완화 불가" />
              </div>
              <div className="card__body">
                {limitsQuery.isError ? (
                  <p className="inline-error" role="alert">
                    한도를 불러오지 못했습니다.
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
                  "한도를 불러오는 중입니다."
                ) : (
                  <table className="grid-table grid-table--stack">
                    <thead>
                      <tr>
                        <th scope="col">항목</th>
                        <th scope="col">한도</th>
                      </tr>
                    </thead>
                    <tbody>
                      {limits.items.map((item) => (
                        <tr key={item.rule_code}>
                          <td className="is-name">{limitLabel(item.rule_code)}</td>
                          <td data-label="한도">{item.limit_value}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <p className="card__note">
                한도 완화, 허용 상품 확대, 시장가 주문 추가는 정책 변경입니다. 코드만 바꿀 수 없으며
                정책 문서와 테스트를 먼저 고치고 사람의 승인을 받아야 합니다.
              </p>
            </section>

            <section className="card">
              <div className="card__head">
                <h2>
                  <span className="card__coord">D</span> 변경 절차
                </h2>
              </div>
              <div className="card__body">
                <ul className="plain-list">
                  <li>정책 문서를 먼저 고칩니다(거래 안전 정책).</li>
                  <li>주문 실행·위험통제 경계는 ADR과 사람의 승인이 필요합니다.</li>
                  <li>구현이 정책을 통과하도록 정책을 고치지 않습니다.</li>
                  <li>상태 전이는 worker CLI에서만 수행합니다.</li>
                </ul>
              </div>
            </section>
          </div>
        </div>
      </div>
    </AppShell>
  );
};
