import { formatDecimal, formatSignedDecimal } from "../lib/format";

export type EquityChartPoint = Readonly<{
  benchmarkPct: number | null;
  date: string;
  drawdownPct: number;
  strategyPct: number;
}>;

type EquityPanesProps = Readonly<{
  points: readonly EquityChartPoint[];
}>;

const STEP = 3;
const CURVE_HEIGHT = 180;
const DRAWDOWN_HEIGHT = 64;

type Scale = (value: number) => number;

const makeScale = (min: number, max: number, height: number): Scale => {
  const span = max - min || 1;
  return (value) => height - ((value - min) / span) * height;
};

const linePath = (series: readonly (number | null)[], scale: Scale): string => {
  let path = "";
  let drawing = false;
  for (const [index, value] of series.entries()) {
    if (value === null) {
      drawing = false;
      continue;
    }
    const x = index * STEP + STEP / 2;
    path += `${drawing ? "L" : "M"}${x.toFixed(2)} ${scale(value).toFixed(2)} `;
    drawing = true;
  }
  return path.trim();
};

const extent = (values: readonly (number | null)[]): readonly [number, number] => {
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  for (const value of values) {
    if (value === null) {
      continue;
    }
    min = Math.min(min, value);
    max = Math.max(max, value);
  }
  if (!Number.isFinite(min)) {
    return [0, 1];
  }
  return [min, max];
};

const lastOf = (series: readonly (number | null)[]): string => {
  for (let index = series.length - 1; index >= 0; index -= 1) {
    const value = series[index];
    if (value !== null && value !== undefined) {
      return `${formatSignedDecimal(value.toFixed(2))}%`;
    }
  }
  return "—";
};

export const EquityPanes = ({ points }: EquityPanesProps) => {
  if (points.length === 0) {
    return <p className="card__note">표시할 NAV 곡선이 없습니다.</p>;
  }
  const width = points.length * STEP;
  const strategySeries = points.map((point) => point.strategyPct);
  const benchmarkSeries = points.map((point) => point.benchmarkPct);
  const drawdownSeries = points.map((point) => point.drawdownPct);

  const [curveMin, curveMax] = extent([...strategySeries, ...benchmarkSeries, 0]);
  const curveScale = makeScale(curveMin, curveMax, CURVE_HEIGHT);
  const [drawdownMin] = extent(drawdownSeries);
  const drawdownScale = makeScale(Math.min(drawdownMin, 0), 0, DRAWDOWN_HEIGHT);
  const firstPoint = points[0];
  const lastPoint = points[points.length - 1];

  return (
    <div>
      <div aria-hidden="true" className="chart-legend">
        <span style={{ color: "var(--color-ma20)" }}>
          <i /> 전략 {lastOf(strategySeries)}
        </span>
        <span style={{ color: "var(--color-ma60)" }}>
          <i /> 벤치마크 {lastOf(benchmarkSeries)}
        </span>
      </div>

      <div className="chart-pane">
        <span className="chart-pane__scale chart-pane__scale--max">
          {formatDecimal(curveMax.toFixed(0))}%
        </span>
        <span className="chart-pane__scale chart-pane__scale--min">
          {formatDecimal(curveMin.toFixed(0))}%
        </span>
        <svg
          aria-label="누적 수익 곡선 차트"
          height={CURVE_HEIGHT}
          preserveAspectRatio="none"
          role="img"
          viewBox={`0 0 ${String(width)} ${String(CURVE_HEIGHT)}`}
        >
          <line
            stroke="var(--color-chart-grid)"
            strokeDasharray="3 3"
            x1="0"
            x2={width}
            y1={curveScale(0)}
            y2={curveScale(0)}
          />
          <path
            d={linePath(benchmarkSeries, curveScale)}
            fill="none"
            stroke="var(--color-ma60)"
            strokeWidth="1.2"
          />
          <path
            d={linePath(strategySeries, curveScale)}
            fill="none"
            stroke="var(--color-ma20)"
            strokeWidth="1.4"
          />
        </svg>
      </div>

      <div className="chart-pane">
        <span className="chart-pane__label">드로다운</span>
        <span className="chart-pane__scale chart-pane__scale--min">
          {formatDecimal(Math.min(drawdownMin, 0).toFixed(1))}%
        </span>
        <svg
          aria-label="드로다운 차트"
          height={DRAWDOWN_HEIGHT}
          preserveAspectRatio="none"
          role="img"
          viewBox={`0 0 ${String(width)} ${String(DRAWDOWN_HEIGHT)}`}
        >
          <line
            stroke="var(--color-chart-grid)"
            x1="0"
            x2={width}
            y1={drawdownScale(0)}
            y2={drawdownScale(0)}
          />
          <path
            d={linePath(drawdownSeries, drawdownScale)}
            fill="none"
            stroke="var(--color-candle-down)"
            strokeWidth="1.2"
          />
        </svg>
      </div>

      <div aria-hidden="true" className="chart-axis">
        <span>{firstPoint?.date}</span>
        <span>{lastPoint?.date}</span>
      </div>
    </div>
  );
};
