import { AppShell } from "../components/app-shell";
import { CoordinateCell, KpiGrid } from "../components/coordinate-cell";
import { SafetyBanner } from "../components/safety-banner";
import { StatusBadge } from "../components/status-badge";

export const Showcase = () => (
  <AppShell
    active="overview"
    headerMeta={<span>프리미티브 시각 계약</span>}
    title="구성요소 갤러리"
  >
    <SafetyBanner
      description="이 화면은 승인된 디자인 프리미티브의 상태 계약을 검증하기 위한 갤러리입니다. 값은 예시가 아니라 상태 표기입니다."
      level="info"
      title="구성요소 갤러리"
    />
    <div className="work__body">
      <div className="gallery">
        <section className="card">
          <div className="card__head">
            <h2>
              <span className="card__coord">G1</span> 좌표 셀
            </h2>
          </div>
          <div className="card__body">
            <KpiGrid label="좌표 셀 상태">
              <CoordinateCell coord="A1" label="기본" value="정상" />
              <CoordinateCell coord="A2" label="값 없음" sub="수집 전" value="—" />
              <CoordinateCell coord="A3" label="정상 상태" tone="ok" value="통과" />
              <CoordinateCell coord="A4" label="차단 상태" tone="warn" value="잠금" />
              <CoordinateCell coord="A5" label="위험 상태" tone="danger" value="실패" />
              <CoordinateCell
                coord="A6"
                label="오래된 값"
                sub="기준 시각 필수"
                tone="stale"
                value="지연"
              />
            </KpiGrid>
          </div>
        </section>

        <section className="card">
          <div className="card__head">
            <h2>
              <span className="card__coord">G2</span> 상태 배지
            </h2>
          </div>
          <div className="card__body" style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
            <StatusBadge kind="ok" label="정상" />
            <StatusBadge kind="neutral" label="확인 중" />
            <StatusBadge kind="warn" label="차단" />
            <StatusBadge kind="danger" label="실패" />
            <StatusBadge kind="up" label="상승" />
            <StatusBadge kind="down" label="하락" />
            <StatusBadge kind="accent" label="선택" />
          </div>
        </section>

        <section className="card">
          <div className="card__head">
            <h2>
              <span className="card__coord">G3</span> 경고 배너
            </h2>
          </div>
          <div className="card__body" style={{ display: "grid", gap: "8px" }}>
            <SafetyBanner
              description="영역 안에서만 쓰는 정보 배너입니다."
              level="info"
              title="정보"
            />
            <SafetyBanner
              code="ACCOUNT_NOT_RECONCILED"
              description="주의 배너는 작업면 헤더 아래 전체 폭에 배치하고 사유 코드를 함께 씁니다."
              level="warning"
              title="주의"
            />
            <SafetyBanner
              code="API_CONSECUTIVE_FAILURE"
              description="위험 배너는 자동으로 해제되지 않으며 사용자 확인이 필요합니다."
              level="danger"
              title="위험"
            />
          </div>
        </section>

        <section className="card card--empty">
          <div className="card__head">
            <h2>
              <span className="card__coord">G4</span> 단계 미도달 빈 상태
            </h2>
          </div>
          <div className="card__body">
            점선 경계와 보조 표면을 쓰고 행동 버튼을 두지 않습니다. 값과 건수를 만들어 채우지
            않습니다.
          </div>
        </section>
      </div>
    </div>
  </AppShell>
);
