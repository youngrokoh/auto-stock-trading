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
  columns?: 6 | 7;
  label: string;
}>;

export const KpiGrid = ({ children, columns = 6, label }: KpiGridProps) => (
  <section aria-label={label} className={columns === 7 ? "kpi-grid kpi-grid--seven" : "kpi-grid"}>
    {children}
  </section>
);
