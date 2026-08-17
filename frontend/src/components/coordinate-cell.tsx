import type { ReactNode } from "react";

type CellTone = "danger" | "down" | "neutral" | "ok" | "stale" | "up" | "warn";

type CoordinateCellProps = Readonly<{
  coord: string;
  label: string;
  sub?: string | undefined;
  tone?: CellTone;
  value: ReactNode;
}>;

export const CoordinateCell = ({
  coord,
  label,
  sub,
  tone = "neutral",
  value,
}: CoordinateCellProps) => (
  <div className={tone === "neutral" ? "cell" : `cell cell--${tone}`}>
    <span className="cell__coord">
      {coord} · {label}
    </span>
    <span className="cell__value">{value}</span>
    {sub !== undefined && <span className="cell__sub">{sub}</span>}
  </div>
);

type KpiGridProps = Readonly<{
  children: ReactNode;
  label: string;
}>;

export const KpiGrid = ({ children, label }: KpiGridProps) => (
  <section aria-label={label} className="kpi-grid">
    {children}
  </section>
);
