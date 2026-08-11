import { Database, Layers3, RadioTower } from "lucide-react";
import type { ComponentType } from "react";

import type { ComponentHealth } from "../lib/health";
import { StatusBadge } from "./status-badge";

type ServiceName = ComponentHealth["name"] | "API";
type ServiceState = ComponentHealth["status"] | "loading";

type ServiceRowProps = Readonly<{
  name: ServiceName;
  state: ServiceState;
}>;

type IconProps = Readonly<{ "aria-hidden": true; size: number; strokeWidth: number }>;

const serviceMeta: Readonly<
  Record<ServiceName, Readonly<{ description: string; icon: ComponentType<IconProps> }>>
> = {
  API: { description: "FastAPI 상태 경계", icon: RadioTower },
  PostgreSQL: { description: "운영 데이터 원본", icon: Database },
  Valkey: { description: "작업 큐 브로커", icon: Layers3 },
};

export const ServiceRow = ({ name, state }: ServiceRowProps) => {
  const meta = serviceMeta[name];
  const Icon = meta.icon;
  const label = state === "ok" ? "정상" : state === "loading" ? "확인 중" : "연결 안 됨";

  return (
    <div className="service-row">
      <span className="service-row__icon">
        <Icon aria-hidden={true} size={17} strokeWidth={1.8} />
      </span>
      <span className="service-row__copy">
        <strong>{name}</strong>
        <span>{meta.description}</span>
      </span>
      <StatusBadge kind={state} label={label} />
    </div>
  );
};
