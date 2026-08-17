export type IndicatorSeries = readonly (number | null)[];

export type MacdResult = Readonly<{
  macd: IndicatorSeries;
  signal: IndicatorSeries;
  histogram: IndicatorSeries;
}>;

export type BollingerResult = Readonly<{
  upper: IndicatorSeries;
  middle: IndicatorSeries;
  lower: IndicatorSeries;
}>;

export const sma = (values: readonly number[], period: number): (number | null)[] => {
  const result: (number | null)[] = new Array<number | null>(values.length).fill(null);
  let windowSum = 0;
  for (const [index, value] of values.entries()) {
    windowSum += value;
    const dropped = values[index - period];
    if (dropped !== undefined) {
      windowSum -= dropped;
    }
    if (index >= period - 1) {
      result[index] = windowSum / period;
    }
  }
  return result;
};

export const rsi = (values: readonly number[], period: number): (number | null)[] => {
  const result: (number | null)[] = new Array<number | null>(values.length).fill(null);
  if (values.length <= period) {
    return result;
  }
  let averageGain = 0;
  let averageLoss = 0;
  for (let index = 1; index < values.length; index += 1) {
    const previous = values[index - 1];
    const current = values[index];
    if (previous === undefined || current === undefined) {
      continue;
    }
    const change = current - previous;
    const gain = Math.max(change, 0);
    const loss = Math.max(-change, 0);
    if (index <= period) {
      averageGain += gain / period;
      averageLoss += loss / period;
      if (index < period) {
        continue;
      }
    } else {
      averageGain = (averageGain * (period - 1) + gain) / period;
      averageLoss = (averageLoss * (period - 1) + loss) / period;
    }
    if (averageLoss === 0) {
      result[index] = averageGain === 0 ? 50 : 100;
    } else {
      result[index] = 100 - 100 / (1 + averageGain / averageLoss);
    }
  }
  return result;
};

const ema = (values: readonly (number | null)[], period: number): (number | null)[] => {
  const result: (number | null)[] = new Array<number | null>(values.length).fill(null);
  const smoothing = 2 / (period + 1);
  let previous: number | null = null;
  let seedSum = 0;
  let seedCount = 0;
  for (const [index, value] of values.entries()) {
    if (value === null || value === undefined) {
      continue;
    }
    if (previous === null) {
      seedSum += value;
      seedCount += 1;
      if (seedCount === period) {
        previous = seedSum / period;
        result[index] = previous;
      }
      continue;
    }
    previous = previous + smoothing * (value - previous);
    result[index] = previous;
  }
  return result;
};

export const macd = (
  values: readonly number[],
  fastPeriod: number,
  slowPeriod: number,
  signalPeriod: number,
): MacdResult => {
  const fast = ema(values, fastPeriod);
  const slow = ema(values, slowPeriod);
  const line = values.map((_, index) => {
    const fastValue = fast[index];
    const slowValue = slow[index];
    return fastValue !== null &&
      fastValue !== undefined &&
      slowValue !== null &&
      slowValue !== undefined
      ? fastValue - slowValue
      : null;
  });
  const signal = ema(line, signalPeriod);
  const histogram = line.map((value, index) => {
    const signalValue = signal[index];
    return value !== null && signalValue !== null && signalValue !== undefined
      ? value - signalValue
      : null;
  });
  return { histogram, macd: line, signal };
};

export const bollinger = (
  values: readonly number[],
  period: number,
  multiplier: number,
): BollingerResult => {
  const middle = sma(values, period);
  const upper: (number | null)[] = new Array<number | null>(values.length).fill(null);
  const lower: (number | null)[] = new Array<number | null>(values.length).fill(null);
  for (const [index, mean] of middle.entries()) {
    if (mean === null || mean === undefined) {
      continue;
    }
    const window = values.slice(index - period + 1, index + 1);
    const variance = window.reduce((total, value) => total + (value - mean) ** 2, 0) / period;
    const deviation = Math.sqrt(variance);
    upper[index] = mean + multiplier * deviation;
    lower[index] = mean - multiplier * deviation;
  }
  return { lower, middle, upper };
};
