import { useQuery } from "@tanstack/react-query";

import { fetchGateReadiness } from "../api/gate";
import { AppShell } from "../components/app-shell";
import { CoordinateCell, KpiGrid } from "../components/coordinate-cell";
import { SafetyBanner } from "../components/safety-banner";
import { StatusBadge } from "../components/status-badge";
import { formatKstDateTime } from "../lib/format";
import { conditionLabel, conditionTone, type GateCondition } from "../lib/gate";

const sectionLabel = (section: string): string =>
  section === "backtest" ? "백테스트 게이트" : "모의운영 게이트";

/** 판정 불가 사유를 사람이 읽는 말로. 코드는 그대로 함께 보여 감사와 화면이 같은 값을 쓴다. */
const reasonText = (code: string): string => {
  if (code === "NO_UPTIME_SOURCE") {
    return "가용성을 기록하는 원천이 없습니다";
  }
  if (code === "HUMAN_REPORT_REQUIRED") {
    return "사람이 작성한 보고서로 확인합니다";
  }
  if (code === "HUMAN_VERIFICATION_REQUIRED") {
    return "사람이 시나리오를 수행해 확인합니다";
  }
  if (code === "NO_OUT_OF_SAMPLE_TAG") {
    return "표본 밖 구간을 표시한 실행 기록이 없습니다";
  }
  return code;
};

const badgeKind = (state: GateCondition["state"]): "danger" | "neutral" | "ok" => {
  const tone = conditionTone(state);
  if (tone === "normal") {
    return "ok";
  }
  return tone === "danger" ? "danger" : "neutral";
};

/** 조건의 측정값. 없으면 판정할 원천이 없다는 뜻이므로 줄표로 둔다. */
const measuredOf = (conditions: readonly GateCondition[], code: string): string =>
  conditions.find((item) => item.code === code)?.measured ?? "—";

export const Gate = () => {
  const gateQuery = useQuery({
    queryFn: fetchGateReadiness,
    queryKey: ["gate-readiness"],
    refetchInterval: 300_000,
    retry: false,
  });

  const gate = gateQuery.data;
  const conditions = gate?.conditions ?? [];
  const met = conditions.filter((item) => item.state === "met");
  const unmet = conditions.filter((item) => item.state === "not_met");
  const unmeasurable = conditions.filter((item) => item.state === "not_measurable");

  return (
    <AppShell
      active="gate"
      headerMeta={
        <>
          <StatusBadge
            kind={gate === undefined ? "neutral" : gate.live_enabled ? "danger" : "ok"}
            label={gate?.live_enabled === true ? "실전 활성" : "실전 비활성"}
          />
          <span>
            {gate === undefined ? "판정 확인 중" : `판정 ${formatKstDateTime(gate.evaluated_at)}`}
          </span>
        </>
      }
      title="실전 전환 게이트"
    >
      <SafetyBanner
        description="이 화면은 전환 게이트 문서의 조건을 저장된 사실로 판정한 결과입니다. 판정할 원천이 없는 조건은 통과로 표시하지 않고 '판정 불가'와 사유 코드로 남깁니다. 게이트 통과 여부와 무관하게 실전 전환은 사람의 승인이 필요합니다."
        level="info"
        title="판정 불가는 통과가 아닙니다"
      />

      <div className="work__body">
        <KpiGrid label="게이트 요약 KPI">
          <CoordinateCell
            coord="A1"
            label="게이트"
            sub={gate === undefined ? undefined : `막는 조건 ${gate.blocking_codes.length}개`}
            value={gate === undefined ? "—" : gate.passed ? "통과" : "미통과"}
          />
          <CoordinateCell
            coord="A2"
            label="충족"
            sub={conditions.length === 0 ? undefined : `전체 ${String(conditions.length)}개`}
            value={conditions.length === 0 ? "—" : `${String(met.length)}개`}
          />
          <CoordinateCell
            coord="A3"
            label="미충족"
            sub={unmet.length === 0 ? undefined : "데이터가 쌓이면 바뀝니다"}
            value={conditions.length === 0 ? "—" : `${String(unmet.length)}개`}
          />
          <CoordinateCell
            coord="A4"
            label="판정 불가"
            sub={unmeasurable.length === 0 ? undefined : "사람이 확인해야 합니다"}
            value={conditions.length === 0 ? "—" : `${String(unmeasurable.length)}개`}
          />
          <CoordinateCell
            coord="A5"
            label="모의 운영일"
            sub="기준 60거래일"
            value={measuredOf(conditions, "PAPER_TRADING_DAYS")}
          />
          <CoordinateCell
            coord="A6"
            label="체결 주문"
            sub="기준 20건"
            value={measuredOf(conditions, "FILLED_ORDERS")}
          />
        </KpiGrid>

        <div className="board">
          <div className="board__main">
            <section className={conditions.length === 0 ? "card card--empty" : "card"}>
              <div className="card__head">
                <h2>
                  <span className="card__coord">A</span> 전환 조건
                </h2>
                {gate !== undefined && (
                  <StatusBadge
                    kind={gate.passed ? "ok" : "warn"}
                    label={
                      gate.passed ? "모든 조건 충족" : `미해소 ${gate.blocking_codes.length}개`
                    }
                  />
                )}
              </div>
              <div className="card__body">
                {gateQuery.isError ? (
                  <p className="inline-error" role="alert">
                    게이트 판정을 불러오지 못했습니다.
                    <button
                      className="retry-button"
                      onClick={() => {
                        void gateQuery.refetch();
                      }}
                      type="button"
                    >
                      다시 시도
                    </button>
                  </p>
                ) : conditions.length === 0 ? (
                  "판정 결과가 없습니다."
                ) : (
                  <table className="grid-table grid-table--stack">
                    <thead>
                      <tr>
                        <th scope="col">절</th>
                        <th scope="col">조건</th>
                        <th scope="col">기준</th>
                        <th scope="col">현재</th>
                        <th scope="col">상태</th>
                        <th scope="col">해소 방법</th>
                      </tr>
                    </thead>
                    <tbody>
                      {conditions.map((condition) => (
                        <tr key={condition.code}>
                          <td className="is-name">{sectionLabel(condition.section)}</td>
                          <td data-label="조건">
                            {condition.requirement}
                            <br />
                            <code>{condition.code}</code>
                          </td>
                          <td data-label="기준">{condition.threshold ?? "—"}</td>
                          <td data-label="현재">{condition.measured ?? "—"}</td>
                          <td data-label="상태">
                            <StatusBadge
                              kind={badgeKind(condition.state)}
                              label={conditionLabel(condition.state)}
                            />
                          </td>
                          <td data-label="해소 방법">
                            {condition.reason_code === null
                              ? "운영을 이어가면 값이 쌓입니다"
                              : reasonText(condition.reason_code)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <p className="card__note">
                판정은 저장된 사실만 셉니다. 중복 주문은 세는 값이 아니라 주문 식별자 UNIQUE 제약의
                결과입니다.
              </p>
            </section>

            <section className="card">
              <div className="card__head">
                <h2>
                  <span className="card__coord">D</span> 이중 확인
                </h2>
                <StatusBadge kind="neutral" label="사람 승인 필요" />
              </div>
              <div className="card__body">
                <ul className="plain-list">
                  <li>모든 조건이 충족돼도 자동으로 실전이 켜지지 않습니다.</li>
                  <li>
                    실전 전환은 승인 자료와 함께 사람이 결정하며, 결정과 근거는 ADR로 남깁니다.
                  </li>
                  <li>서버 재시작과 거래일 변경 시 실전 활성 상태는 해제됩니다.</li>
                </ul>
              </div>
            </section>
          </div>

          <div className="board__side">
            <section className="card">
              <div className="card__head">
                <h2>
                  <span className="card__coord">B</span> 최초 실전 한도
                </h2>
                <StatusBadge kind="neutral" label="완화 불가" />
              </div>
              <div className="card__body">
                {gate === undefined ? (
                  "한도를 불러오는 중입니다."
                ) : (
                  <table className="grid-table grid-table--stack">
                    <thead>
                      <tr>
                        <th scope="col">항목</th>
                        <th scope="col">상한</th>
                      </tr>
                    </thead>
                    <tbody>
                      {gate.initial_limits.map((limit) => (
                        <tr key={limit.code}>
                          <td className="is-name">{limit.item}</td>
                          <td data-label="상한">{limit.value}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <p className="card__note">
                최초 승인 시 이 값보다 완화할 수 없습니다. 확대는 관찰 기간을 채운 뒤 별도 승인
                사항입니다.
              </p>
            </section>

            <section className="card">
              <div className="card__head">
                <h2>
                  <span className="card__coord">C</span> 막고 있는 조건
                </h2>
              </div>
              <div className="card__body">
                {gate === undefined || gate.blocking_codes.length === 0 ? (
                  "막고 있는 조건이 없습니다."
                ) : (
                  <ul className="plain-list">
                    {gate.blocking_codes.map((code) => (
                      <li key={code}>
                        <code>{code}</code>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <p className="card__note">화면과 감사 기록이 같은 사유 코드를 씁니다.</p>
            </section>
          </div>
        </div>
      </div>
    </AppShell>
  );
};
