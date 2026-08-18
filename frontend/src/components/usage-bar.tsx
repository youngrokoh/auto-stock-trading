import type { UsageLevel } from "../lib/trading";

const FULL_PERCENT = 100;

type UsageBarProps = Readonly<{
  label: string;
  level: UsageLevel;
  limit: string;
  current: string;
  percent: number | null;
  note?: string | undefined;
}>;

/** 화면 디자인 사양 5.5절 진행·소진율 막대. 현재값과 한도를 라벨 줄에 함께 쓴다. */
export const UsageBar = ({ label, level, limit, current, percent, note }: UsageBarProps) => (
  <div className="usage">
    <div className="usage__head">
      <span className="usage__label">{label}</span>
      <span className="usage__value">{current}</span>
      <span className="usage__limit">/ {limit}</span>
    </div>
    <div className="usage__track">
      <div
        aria-hidden="true"
        className={`usage__fill usage__fill--${level}`}
        style={{
          width:
            level === "unknown"
              ? `${String(FULL_PERCENT)}%`
              : `${String(Math.min(percent ?? 0, FULL_PERCENT))}%`,
        }}
      />
    </div>
    {note !== undefined && <span className="usage__note">{note}</span>}
  </div>
);
