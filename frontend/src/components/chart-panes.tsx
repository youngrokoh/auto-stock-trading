import { formatDecimal } from "../lib/format";
import { bollinger, macd, rsi, sma } from "../lib/indicators";

export type ChartBar = Readonly<{
  close: number;
  confirmed: boolean;
  date: string;
  high: number;
  low: number;
  open: number;
  volume: number;
}>;

type ChartPanesProps = Readonly<{
  bars: readonly ChartBar[];
}>;

const STEP = 7;
const BODY = 4.4;
const PRICE_HEIGHT = 200;
const SUB_HEIGHT = 56;

type Scale = (value: number) => number;

const makeScale = (min: number, max: number, height: number): Scale => {
  const span = max - min || 1;
  return (value) => height - ((value - min) / span) * height;
};

const maskPending = (
  series: readonly (number | null)[],
  cutoff: number,
): readonly (number | null)[] => series.map((value, index) => (index < cutoff ? value : null));

const linePath = (series: readonly (number | null)[], scale: Scale): string => {
  let path = "";
  let drawing = false;
  for (const [index, value] of series.entries()) {
    if (value === null) {
      drawing = false;
      continue;
    }
    const x = index * STEP + STEP / 2;
    const y = scale(value);
    path += `${drawing ? "L" : "M"}${x.toFixed(2)} ${y.toFixed(2)} `;
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

export const ChartPanes = ({ bars }: ChartPanesProps) => {
  if (bars.length === 0) {
    return <p className="card__note">표시할 확정 일봉이 없습니다.</p>;
  }
  const width = bars.length * STEP;
  const closes = bars.map((bar) => bar.close);
  const firstPending = bars.findIndex((bar) => !bar.confirmed);
  const cutoff = firstPending === -1 ? bars.length : firstPending;
  const ma5 = maskPending(sma(closes, 5), cutoff);
  const ma20 = maskPending(sma(closes, 20), cutoff);
  const ma60 = maskPending(sma(closes, 60), cutoff);
  const bands = bollinger(closes, 20, 2);
  const upperBand = maskPending(bands.upper, cutoff);
  const lowerBand = maskPending(bands.lower, cutoff);
  const rsiSeries = maskPending(rsi(closes, 14), cutoff);
  const macdResult = macd(closes, 12, 26, 9);
  const macdLine = maskPending(macdResult.macd, cutoff);
  const signalLine = maskPending(macdResult.signal, cutoff);
  const histogram = maskPending(macdResult.histogram, cutoff);

  const priceValues: (number | null)[] = [
    ...bars.map((bar) => bar.high),
    ...bars.map((bar) => bar.low),
    ...upperBand,
    ...lowerBand,
  ];
  const [priceMin, priceMax] = extent(priceValues);
  const priceScale = makeScale(priceMin, priceMax, PRICE_HEIGHT);
  const [, volumeMax] = extent(bars.map((bar) => bar.volume));
  const volumeScale = makeScale(0, volumeMax, SUB_HEIGHT);
  const rsiScale = makeScale(0, 100, SUB_HEIGHT);
  const [macdMin, macdMax] = extent([...macdLine, ...signalLine, ...histogram, 0]);
  const macdScale = makeScale(macdMin, macdMax, SUB_HEIGHT);

  const lastOf = (series: readonly (number | null)[]): string => {
    for (let index = series.length - 1; index >= 0; index -= 1) {
      const value = series[index];
      if (value !== null && value !== undefined) {
        return formatDecimal(value.toFixed(0));
      }
    }
    return "—";
  };
  const firstBar = bars[0];
  const lastBar = bars[bars.length - 1];

  return (
    <div>
      <div aria-hidden="true" className="chart-legend">
        <span style={{ color: "var(--color-ma5)" }}>
          <i /> MA5 {lastOf(ma5)}
        </span>
        <span style={{ color: "var(--color-ma20)" }}>
          <i /> MA20 {lastOf(ma20)}
        </span>
        <span style={{ color: "var(--color-ma60)" }}>
          <i /> MA60 {lastOf(ma60)}
        </span>
        <span style={{ color: "var(--color-text-faint)" }}>
          <i /> BB(20, 2σ)
        </span>
      </div>

      <div className="chart-pane">
        <span className="chart-pane__scale chart-pane__scale--max">
          {formatDecimal(priceMax.toFixed(0))}
        </span>
        <span className="chart-pane__scale chart-pane__scale--min">
          {formatDecimal(priceMin.toFixed(0))}
        </span>
        <svg
          aria-label="일봉 캔들 차트"
          height={PRICE_HEIGHT}
          preserveAspectRatio="none"
          role="img"
          viewBox={`0 0 ${String(width)} ${String(PRICE_HEIGHT)}`}
        >
          <line
            stroke="var(--color-chart-grid)"
            x1="0"
            x2={width}
            y1={PRICE_HEIGHT / 2}
            y2={PRICE_HEIGHT / 2}
          />
          <path d={linePath(upperBand, priceScale)} fill="none" stroke="var(--color-line)" />
          <path d={linePath(lowerBand, priceScale)} fill="none" stroke="var(--color-line)" />
          {bars.map((bar, index) => {
            const x = index * STEP + STEP / 2;
            const color =
              bar.close >= bar.open ? "var(--color-candle-up)" : "var(--color-candle-down)";
            const bodyTop = priceScale(Math.max(bar.open, bar.close));
            const bodyBottom = priceScale(Math.min(bar.open, bar.close));
            return (
              <g key={bar.date} opacity={bar.confirmed ? 1 : 0.45}>
                <line
                  stroke={color}
                  strokeWidth="1"
                  x1={x}
                  x2={x}
                  y1={priceScale(bar.high)}
                  y2={priceScale(bar.low)}
                />
                <rect
                  fill={color}
                  height={Math.max(bodyBottom - bodyTop, 1)}
                  width={BODY}
                  x={x - BODY / 2}
                  y={bodyTop}
                />
              </g>
            );
          })}
          <path
            d={linePath(ma5, priceScale)}
            fill="none"
            stroke="var(--color-ma5)"
            strokeWidth="1.2"
          />
          <path
            d={linePath(ma20, priceScale)}
            fill="none"
            stroke="var(--color-ma20)"
            strokeWidth="1.2"
          />
          <path
            d={linePath(ma60, priceScale)}
            fill="none"
            stroke="var(--color-ma60)"
            strokeWidth="1.2"
          />
        </svg>
      </div>

      <div className="chart-pane">
        <span className="chart-pane__label">거래량</span>
        <svg
          aria-label="거래량 차트"
          height={SUB_HEIGHT}
          preserveAspectRatio="none"
          role="img"
          viewBox={`0 0 ${String(width)} ${String(SUB_HEIGHT)}`}
        >
          {bars.map((bar, index) => {
            const x = index * STEP + (STEP - BODY) / 2;
            const y = volumeScale(bar.volume);
            const fill =
              bar.close >= bar.open ? "var(--color-volume-up)" : "var(--color-volume-down)";
            return (
              <rect
                fill={fill}
                height={Math.max(SUB_HEIGHT - y, 0.5)}
                key={bar.date}
                width={BODY}
                x={x}
                y={y}
              />
            );
          })}
        </svg>
      </div>

      <div className="chart-pane">
        <span className="chart-pane__label">RSI 14</span>
        <span className="chart-pane__scale chart-pane__scale--max">70</span>
        <span className="chart-pane__scale chart-pane__scale--min">30</span>
        <svg
          aria-label="RSI 차트"
          height={SUB_HEIGHT}
          preserveAspectRatio="none"
          role="img"
          viewBox={`0 0 ${String(width)} ${String(SUB_HEIGHT)}`}
        >
          <line
            stroke="var(--color-chart-grid)"
            strokeDasharray="3 3"
            x1="0"
            x2={width}
            y1={rsiScale(70)}
            y2={rsiScale(70)}
          />
          <line
            stroke="var(--color-chart-grid)"
            strokeDasharray="3 3"
            x1="0"
            x2={width}
            y1={rsiScale(30)}
            y2={rsiScale(30)}
          />
          <path
            d={linePath(rsiSeries, rsiScale)}
            fill="none"
            stroke="var(--color-ma20)"
            strokeWidth="1.2"
          />
        </svg>
      </div>

      <div className="chart-pane">
        <span className="chart-pane__label">MACD 12·26·9</span>
        <svg
          aria-label="MACD 차트"
          height={SUB_HEIGHT}
          preserveAspectRatio="none"
          role="img"
          viewBox={`0 0 ${String(width)} ${String(SUB_HEIGHT)}`}
        >
          <line
            stroke="var(--color-chart-grid)"
            x1="0"
            x2={width}
            y1={macdScale(0)}
            y2={macdScale(0)}
          />
          {histogram.map((value, index) => {
            if (value === null) {
              return null;
            }
            const bar = bars[index];
            if (bar === undefined) {
              return null;
            }
            const zero = macdScale(0);
            const y = macdScale(value);
            return (
              <rect
                fill={value >= 0 ? "var(--color-volume-up)" : "var(--color-volume-down)"}
                height={Math.max(Math.abs(zero - y), 0.5)}
                key={bar.date}
                width={BODY}
                x={index * STEP + (STEP - BODY) / 2}
                y={Math.min(zero, y)}
              />
            );
          })}
          <path
            d={linePath(macdLine, macdScale)}
            fill="none"
            stroke="var(--color-ma5)"
            strokeWidth="1.2"
          />
          <path
            d={linePath(signalLine, macdScale)}
            fill="none"
            stroke="var(--color-ma60)"
            strokeWidth="1.2"
          />
        </svg>
      </div>

      <div aria-hidden="true" className="chart-axis">
        <span>{firstBar?.date}</span>
        <span>{lastBar?.date}</span>
      </div>
    </div>
  );
};
