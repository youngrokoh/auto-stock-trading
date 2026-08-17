import { useQueries, useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";

import { fetchReadiness } from "../api/health";
import { fetchInstruments, fetchQuote } from "../api/market-data";
import { AppShell } from "../components/app-shell";
import { CoordinateCell, KpiGrid } from "../components/coordinate-cell";
import { SafetyBanner } from "../components/safety-banner";
import { StatusBadge } from "../components/status-badge";
import { formatDecimal, formatKstDateTime } from "../lib/format";

const serviceLabel = (status: "loading" | "ok" | "unavailable"): string =>
  status === "ok" ? "정상" : status === "loading" ? "확인 중" : "연결 안 됨";

const serviceKind = (status: "loading" | "ok" | "unavailable") =>
  status === "ok"
    ? ("ok" as const)
    : status === "loading"
      ? ("neutral" as const)
      : ("danger" as const);

export const Overview = () => {
  const readinessQuery = useQuery({
    queryFn: fetchReadiness,
    queryKey: ["readiness"],
    refetchInterval: 30_000,
    retry: false,
  });
  const instrumentsQuery = useQuery({
    queryFn: fetchInstruments,
    queryKey: ["instruments"],
    retry: false,
  });
  const instruments = instrumentsQuery.data?.instruments ?? [];
  const quoteQueries = useQueries({
    queries: instruments.map((instrument) => ({
      queryFn: () => fetchQuote(instrument.symbol),
      queryKey: ["quote", instrument.symbol],
      retry: false,
    })),
  });

  const apiStatus = readinessQuery.isError
    ? ("unavailable" as const)
    : readinessQuery.isPending
      ? ("loading" as const)
      : ("ok" as const);
  const componentStatus = (name: "PostgreSQL" | "Valkey"): "loading" | "ok" | "unavailable" => {
    if (readinessQuery.isPending) {
      return "loading";
    }
    const found = readinessQuery.data?.components.find(
      (component) => component.name === name,
    )?.status;
    return found ?? "unavailable";
  };
  const postgres = componentStatus("PostgreSQL");
  const valkey = componentStatus("Valkey");
  const checkedAt =
    readinessQuery.dataUpdatedAt === 0
      ? "확인 전"
      : formatKstDateTime(new Date(readinessQuery.dataUpdatedAt).toISOString());

  return (
    <AppShell
      active="overview"
      headerMeta={
        <>
          <span>상태 확인 {checkedAt}</span>
          <button
            aria-label="상태 새로고침"
            className="retry-button"
            disabled={readinessQuery.isFetching}
            onClick={() => {
              void readinessQuery.refetch();
            }}
            type="button"
          >
            <RefreshCw aria-hidden="true" size={13} strokeWidth={1.8} />
          </button>
        </>
      }
      title="운영 개요"
    >
      <SafetyBanner
        description="주문 자격증명은 브라우저에 전달되지 않으며 주문 기능이 구현되지 않았습니다. 해제는 실전 전환 게이트 승인 절차를 따릅니다."
        level="warning"
        title="실전거래 비활성"
      />

      <div className="work__body">
        <KpiGrid label="운영 상태 KPI">
          <CoordinateCell
            coord="A1"
            label="API"
            tone={apiStatus === "ok" ? "ok" : apiStatus === "loading" ? "neutral" : "danger"}
            value={serviceLabel(apiStatus)}
          />
          <CoordinateCell
            coord="A2"
            label="PostgreSQL"
            tone={postgres === "ok" ? "ok" : postgres === "loading" ? "neutral" : "danger"}
            value={serviceLabel(postgres)}
          />
          <CoordinateCell
            coord="A3"
            label="Valkey"
            tone={valkey === "ok" ? "ok" : valkey === "loading" ? "neutral" : "danger"}
            value={serviceLabel(valkey)}
          />
          <CoordinateCell
            coord="A4"
            label="실행 환경"
            value={readinessQuery.data?.environment ?? "—"}
          />
          <CoordinateCell
            coord="A5"
            label="수집 종목"
            sub={instrumentsQuery.isError ? "목록 조회 실패" : undefined}
            value={instrumentsQuery.data === undefined ? "—" : String(instruments.length)}
          />
          <CoordinateCell coord="A6" label="실전 주문" tone="warn" value="잠금" />
        </KpiGrid>

        <div className="board">
          <div className="board__main">
            <section aria-live="polite" className="card">
              <div className="card__head">
                <h2>
                  <span className="card__coord">B</span> 서비스 상태
                </h2>
                <StatusBadge
                  kind={apiStatus === "ok" ? "ok" : apiStatus === "loading" ? "neutral" : "danger"}
                  label={apiStatus === "unavailable" ? "확인 필요" : "상태 확인"}
                />
              </div>
              <div className="card__body">
                <dl className="fact-list">
                  {(
                    [
                      ["API", "FastAPI 상태 경계", apiStatus],
                      ["PostgreSQL", "운영 데이터 원본", postgres],
                      ["Valkey", "작업 큐·KIS 호출 게이트", valkey],
                    ] as const
                  ).map(([name, role, status]) => (
                    <div key={name}>
                      <dt>
                        {name} · {role}
                      </dt>
                      <dd>
                        <StatusBadge kind={serviceKind(status)} label={serviceLabel(status)} />
                      </dd>
                    </div>
                  ))}
                </dl>
                {readinessQuery.isError && (
                  <p className="inline-error" role="alert">
                    상태 API에 연결하지 못했습니다. 백엔드 실행 상태를 확인해 주세요.
                  </p>
                )}
              </div>
              <div className="card__note">출처 /api/health/status · 30초 간격 자동 확인</div>
            </section>

            <section className="card">
              <div className="card__head">
                <h2>
                  <span className="card__coord">E</span> 수집 파이프라인
                </h2>
              </div>
              <div className="card__body">
                {instruments.length === 0 ? (
                  <p className="card__note">
                    {instrumentsQuery.isError
                      ? "종목 목록을 불러오지 못했습니다."
                      : "수집된 종목이 없습니다."}
                  </p>
                ) : (
                  <table className="grid-table">
                    <thead>
                      <tr>
                        <th scope="col">종목</th>
                        <th scope="col">최근 시세 (원)</th>
                        <th scope="col">기준시각 (KST)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {instruments.map((instrument, index) => {
                        const quote = quoteQueries[index];
                        return (
                          <tr key={instrument.symbol}>
                            <td className="is-name">
                              {instrument.name} {instrument.symbol}
                            </td>
                            <td className="is-key">
                              {quote?.data === undefined ? "—" : formatDecimal(quote.data.price)}
                            </td>
                            <td>
                              {quote?.data === undefined
                                ? quote?.isError === true
                                  ? "조회 실패"
                                  : "—"
                                : formatKstDateTime(quote.data.received_at)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </div>
              <div className="card__note">
                출처 KIS 모의환경 배치 수집 · 실시간 시세가 아니며 수집 시점 값입니다
              </div>
            </section>
          </div>

          <div className="board__aside">
            <section className="card">
              <div className="card__head">
                <h2>
                  <span className="card__coord">C</span> 실전 전환 게이트
                </h2>
                <StatusBadge kind="warn" label="미통과" />
              </div>
              <div className="card__body">
                <dl className="fact-list">
                  <div>
                    <dt>모의 검증 실적</dt>
                    <dd>수집 중</dd>
                  </div>
                  <div>
                    <dt>주문·위험 한도</dt>
                    <dd>미구현</dd>
                  </div>
                  <div>
                    <dt>사용자 승인</dt>
                    <dd>대기</dd>
                  </div>
                </dl>
              </div>
              <div className="card__note">
                게이트 조건과 해제 절차는 paper-to-live-gate 정책 문서를 따릅니다
              </div>
            </section>

            <section className="card">
              <div className="card__head">
                <h2>
                  <span className="card__coord">D</span> 안전 경계
                </h2>
                <StatusBadge kind="ok" label="적용 중" />
              </div>
              <div className="card__body">
                <dl className="fact-list">
                  <div>
                    <dt>주문 자격증명</dt>
                    <dd>서버 전용</dd>
                  </div>
                  <div>
                    <dt>실전 자격증명</dt>
                    <dd>달력 확인 전용</dd>
                  </div>
                  <div>
                    <dt>미확정 데이터</dt>
                    <dd>전략 입력 금지</dd>
                  </div>
                </dl>
              </div>
            </section>

            <section className="card card--empty">
              <div className="card__head">
                <h2>
                  <span className="card__coord">F</span> 이벤트
                </h2>
              </div>
              <div className="card__body">
                운영 이벤트 스트림은 아직 만들지 않았습니다. 주문·위험 단계에서 감사 로그와 함께
                제공됩니다.
              </div>
            </section>
          </div>
        </div>
      </div>
    </AppShell>
  );
};
