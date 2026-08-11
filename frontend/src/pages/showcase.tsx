import { Database, Layers3, RadioTower } from "lucide-react";

import { EmptyModule } from "../components/empty-module";
import { ServiceRow } from "../components/service-row";
import { StatusBadge } from "../components/status-badge";

export const Showcase = () => (
  <main className="showcase">
    <header>
      <span className="eyebrow">PRIMITIVE SHOWCASE</span>
      <h1>운영 UI 구성요소</h1>
      <p>제품 화면에 사용되는 상태·서비스·빈 모듈의 시각 계약입니다.</p>
    </header>
    <section className="showcase__section">
      <h2>상태 배지</h2>
      <div className="showcase__row">
        <StatusBadge kind="ok" label="정상" />
        <StatusBadge kind="loading" label="확인 중" />
        <StatusBadge kind="warning" label="확인 필요" />
        <StatusBadge kind="unavailable" label="연결 안 됨" />
        <StatusBadge kind="disabled" label="잠금" />
      </div>
    </section>
    <section className="showcase__section">
      <h2>서비스 행</h2>
      <div className="service-list showcase__services">
        <ServiceRow name="API" state="ok" />
        <ServiceRow name="PostgreSQL" state="loading" />
        <ServiceRow name="Valkey" state="unavailable" />
      </div>
    </section>
    <section className="showcase__section">
      <h2>빈 모듈</h2>
      <div className="module-grid">
        <EmptyModule
          description="실제 데이터 연결 전 상태입니다."
          icon={RadioTower}
          phase="API"
          title="신호"
        />
        <EmptyModule
          description="실제 데이터 연결 전 상태입니다."
          icon={Database}
          phase="DATA"
          title="기록"
        />
        <EmptyModule
          description="실제 데이터 연결 전 상태입니다."
          icon={Layers3}
          phase="QUEUE"
          title="작업"
        />
      </div>
    </section>
  </main>
);
