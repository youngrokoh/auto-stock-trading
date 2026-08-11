import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowUpRight,
  ChartNoAxesCombined,
  Clock3,
  LockKeyhole,
  RefreshCw,
  ScrollText,
  ShieldCheck,
  Waypoints,
} from "lucide-react";

import { fetchReadiness } from "../api/health";
import { EmptyModule } from "../components/empty-module";
import { ServiceRow } from "../components/service-row";
import { StatusBadge } from "../components/status-badge";
import type { ComponentHealth } from "../lib/health";

const navigation = [
  { active: true, label: "운영 개요" },
  { active: false, label: "시장 데이터" },
  { active: false, label: "기업 분석" },
  { active: false, label: "ETF 탐색" },
  { active: false, label: "전략 연구" },
] as const;

const pendingComponents = [
  { name: "PostgreSQL", status: "loading" },
  { name: "Valkey", status: "loading" },
] as const;

const unavailableComponents = [
  { name: "PostgreSQL", status: "unavailable" },
  { name: "Valkey", status: "unavailable" },
] as const;

const updatedAtFormatter = new Intl.DateTimeFormat("ko-KR", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

const formatUpdatedAt = (updatedAt: number): string => {
  if (updatedAt === 0) {
    return "상태 확인 전";
  }
  return updatedAtFormatter.format(updatedAt);
};

export const Dashboard = () => {
  const readinessQuery = useQuery({
    queryFn: fetchReadiness,
    queryKey: ["readiness"],
    refetchInterval: 30_000,
    retry: false,
  });

  const components: readonly (ComponentHealth | (typeof pendingComponents)[number])[] =
    readinessQuery.data?.components ??
    (readinessQuery.isError ? unavailableComponents : pendingComponents);
  const apiState = readinessQuery.isError
    ? "unavailable"
    : readinessQuery.isPending
      ? "loading"
      : "ok";
  const environment = readinessQuery.data?.environment ?? "development";

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="주요 탐색">
        <a className="brand" href="/" aria-label="AutoStock 운영 개요">
          <span className="brand__mark" aria-hidden="true">
            AS
          </span>
          <span>
            <strong>AutoStock</strong>
            <small>OPERATIONS</small>
          </span>
        </a>

        <nav className="nav-list">
          <span className="nav-label">WORKSPACE</span>
          {navigation.map((item) => (
            <span
              className={`nav-item${item.active ? " nav-item--active" : ""}`}
              aria-current={item.active ? "page" : undefined}
              aria-disabled={!item.active}
              key={item.label}
            >
              <span className="nav-item__indicator" aria-hidden="true" />
              {item.label}
              {!item.active && <small>준비 중</small>}
            </span>
          ))}
        </nav>

        <div className="sidebar__footer">
          <span className="eyebrow">ENVIRONMENT</span>
          <div>
            <StatusBadge kind="ok" label={environment} />
            <span>v{readinessQuery.data?.version ?? "0.1.0"}</span>
          </div>
        </div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <span className="eyebrow">PHASE 01 · FOUNDATION</span>
            <h1>자동매매 운영 현황</h1>
            <p>안전한 자동매매를 위한 서비스 연결과 실행 경계를 확인합니다.</p>
          </div>
          <div className="topbar__meta">
            <span>
              <Clock3 aria-hidden="true" size={14} />
              {formatUpdatedAt(readinessQuery.dataUpdatedAt)}
            </span>
            <button
              className="icon-button"
              disabled={readinessQuery.isFetching}
              onClick={() => readinessQuery.refetch()}
              type="button"
            >
              <RefreshCw aria-hidden="true" size={16} />
              <span>상태 새로고침</span>
            </button>
          </div>
        </header>

        <div className="workspace__body">
          <section className="context-strip" aria-label="현재 실행 경계">
            <div>
              <span>구축 단계</span>
              <strong>프로젝트 기반</strong>
            </div>
            <div>
              <span>주문 환경</span>
              <strong>모의투자 준비</strong>
            </div>
            <div>
              <span>실전 주문</span>
              <strong className="warning-text">
                <LockKeyhole aria-hidden="true" size={15} />
                비활성
              </strong>
            </div>
          </section>

          <section className="overview-grid">
            <article className="panel service-panel" aria-live="polite">
              <div className="panel__header">
                <div>
                  <span className="eyebrow">SYSTEM READINESS</span>
                  <h2>서비스 상태</h2>
                </div>
                <StatusBadge
                  kind={readinessQuery.isError ? "unavailable" : apiState}
                  label={readinessQuery.isError ? "확인 필요" : "상태 확인"}
                />
              </div>
              <div className="service-list">
                <ServiceRow name="API" state={apiState} />
                {components.map((component) => (
                  <ServiceRow key={component.name} name={component.name} state={component.status} />
                ))}
              </div>
              {readinessQuery.isError && (
                <div className="inline-error" role="alert">
                  상태 API에 연결하지 못했습니다. 백엔드 실행 상태를 확인해 주세요.
                </div>
              )}
            </article>

            <article className="panel readiness-panel">
              <div className="panel__header">
                <div>
                  <span className="eyebrow">DELIVERY GATE</span>
                  <h2>1단계 준비 상태</h2>
                </div>
                <span className="phase-index">01</span>
              </div>
              <div className="readiness-list">
                <div>
                  <ShieldCheck aria-hidden="true" size={18} />
                  <span>
                    <strong>안전 정책</strong>
                    <small>승인된 정책을 구현 경계로 사용</small>
                  </span>
                  <StatusBadge kind="ok" label="확정" />
                </div>
                <div>
                  <Waypoints aria-hidden="true" size={18} />
                  <span>
                    <strong>API·작업자 분리</strong>
                    <small>독립 프로세스로 실행</small>
                  </span>
                  <StatusBadge kind="ok" label="구성" />
                </div>
                <div>
                  <Activity aria-hidden="true" size={18} />
                  <span>
                    <strong>운영 연결</strong>
                    <small>실행 환경에서 최종 확인</small>
                  </span>
                  <StatusBadge
                    kind={readinessQuery.data?.status === "ready" ? "ok" : "warning"}
                    label={readinessQuery.data?.status === "ready" ? "준비됨" : "확인 필요"}
                  />
                </div>
              </div>
            </article>

            <article className="panel safety-panel">
              <span className="safety-panel__icon">
                <LockKeyhole aria-hidden="true" size={21} />
              </span>
              <div>
                <span className="eyebrow">EXECUTION SAFETY</span>
                <h2>실전거래 비활성</h2>
                <p>
                  현재 단계에서는 주문 자격증명을 브라우저에 전달하지 않으며 주문을 실행하지
                  않습니다.
                </p>
              </div>
              <StatusBadge kind="disabled" label="잠금" />
            </article>

            <article className="panel next-panel">
              <span className="eyebrow">NEXT MILESTONE</span>
              <h2>신뢰할 수 있는 시장 데이터</h2>
              <p>KIS 토큰 경계와 종목 마스터 수집을 연결하는 2단계가 이어집니다.</p>
              <span className="next-panel__link">
                Phase 02
                <ArrowUpRight aria-hidden="true" size={15} />
              </span>
            </article>
          </section>

          <section className="modules-section" aria-labelledby="modules-title">
            <div className="section-heading">
              <div>
                <span className="eyebrow">MODULES</span>
                <h2 id="modules-title">운영 모듈</h2>
              </div>
              <p>가짜 시장 데이터 없이 기반 상태만 표시합니다.</p>
            </div>
            <div className="module-grid">
              <EmptyModule
                description="시장 데이터가 수집되면 검증된 전략 신호를 표시합니다."
                icon={ChartNoAxesCombined}
                phase="PHASE 06"
                title="전략"
              />
              <EmptyModule
                description="모의투자 게이트를 통과한 주문만 표시합니다."
                icon={ScrollText}
                phase="PHASE 07"
                title="주문"
              />
              <EmptyModule
                description="계좌 연결 전에는 포지션 수치나 손익을 생성하지 않습니다."
                icon={Waypoints}
                phase="PHASE 07"
                title="포지션"
              />
            </div>
          </section>
        </div>
      </main>
    </div>
  );
};
