export type FigureYear = Readonly<{
  netIncome: number | null;
  operatingIncome: number | null;
  revenue: number | null;
  year: number;
}>;

type FigureBarsProps = Readonly<{
  years: readonly FigureYear[];
}>;

const GROUP = 30;
const BAR = 8;
const GAP = 1;
const HEIGHT = 150;

const SERIES = [
  { className: "figure-bar--revenue", key: "revenue", label: "매출액" },
  { className: "figure-bar--operating", key: "operatingIncome", label: "영업이익" },
  { className: "figure-bar--net", key: "netIncome", label: "당기순이익" },
] as const;

const toTrillion = (value: number): string =>
  `${String(Number((value / 1_000_000_000_000).toFixed(1)))}조`;

export const FigureBars = ({ years }: FigureBarsProps) => {
  const values = years.flatMap((year) =>
    [year.revenue, year.operatingIncome, year.netIncome].filter(
      (value): value is number => value !== null,
    ),
  );
  if (values.length === 0) {
    return <p className="card__note">표시할 실적 금액이 없습니다.</p>;
  }
  const max = Math.max(...values, 0);
  const min = Math.min(...values, 0);
  const span = max - min || 1;
  const scaleY = (value: number): number => HEIGHT - ((value - min) / span) * HEIGHT;
  const width = years.length * GROUP;

  return (
    <div>
      <div className="chart-legend">
        {SERIES.map((series) => (
          <span className={series.className} key={series.key}>
            <i /> {series.label}
          </span>
        ))}
      </div>
      <div className="chart-pane">
        <svg
          aria-label="연간 실적 막대 차트"
          height={HEIGHT}
          preserveAspectRatio="none"
          role="img"
          viewBox={`0 0 ${String(width)} ${String(HEIGHT)}`}
        >
          <line className="figure-bar__baseline" x1={0} x2={width} y1={scaleY(0)} y2={scaleY(0)} />
          {years.map((year, index) =>
            SERIES.map((series, seriesIndex) => {
              const value = year[series.key];
              if (value === null) {
                return null;
              }
              const x = index * GROUP + 2 + seriesIndex * (BAR + GAP);
              const top = Math.min(scaleY(value), scaleY(0));
              const barHeight = Math.max(Math.abs(scaleY(value) - scaleY(0)), 1);
              return (
                <rect
                  className={series.className}
                  height={barHeight.toFixed(2)}
                  key={`${String(year.year)}-${series.key}`}
                  width={BAR}
                  x={x}
                  y={top.toFixed(2)}
                />
              );
            }),
          )}
        </svg>
        <span className="chart-pane__scale chart-pane__scale--max">{toTrillion(max)}</span>
        {min < 0 && (
          <span className="chart-pane__scale chart-pane__scale--min">{toTrillion(min)}</span>
        )}
      </div>
      <div className="chart-axis">
        {years.map((year) => (
          <span key={year.year}>{year.year}</span>
        ))}
      </div>
    </div>
  );
};
