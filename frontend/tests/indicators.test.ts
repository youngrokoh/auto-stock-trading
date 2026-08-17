import { describe, expect, it } from "vitest";

import { bollinger, macd, rsi, sma } from "../src/lib/indicators";

describe("sma", () => {
  it("기간을 채우기 전에는 null을 반환하고 이후에는 단순 평균을 낸다", () => {
    expect(sma([1, 2, 3, 4, 5], 3)).toEqual([null, null, 2, 3, 4]);
  });

  it("기간보다 짧은 입력은 전부 null이다", () => {
    expect(sma([1, 2], 3)).toEqual([null, null]);
  });
});

describe("rsi", () => {
  it("Wilder 평활로 상승·하락 압력을 계산한다", () => {
    const values = rsi([1, 2, 3, 2, 3], 2);
    expect(values[0]).toBeNull();
    expect(values[1]).toBeNull();
    expect(values[2]).toBeCloseTo(100, 8);
    expect(values[3]).toBeCloseTo(50, 8);
    expect(values[4]).toBeCloseTo(75, 8);
  });

  it("하락만 있는 구간은 0이다", () => {
    const values = rsi([5, 4, 3], 2);
    expect(values[2]).toBeCloseTo(0, 8);
  });
});

describe("macd", () => {
  it("빠른 EMA와 느린 EMA의 차이와 신호선을 계산한다", () => {
    const result = macd([1, 2, 3, 4, 5], 2, 3, 2);
    expect(result.macd).toEqual([null, null, 0.5, 0.5, 0.5]);
    expect(result.signal).toEqual([null, null, null, 0.5, 0.5]);
    expect(result.histogram).toEqual([null, null, null, 0, 0]);
  });
});

describe("bollinger", () => {
  it("이동평균과 표준편차 밴드를 계산한다", () => {
    const result = bollinger([1, 2, 3, 4, 5], 3, 2);
    expect(result.middle).toEqual([null, null, 2, 3, 4]);
    expect(result.upper[2]).toBeCloseTo(2 + 2 * Math.sqrt(2 / 3), 8);
    expect(result.lower[2]).toBeCloseTo(2 - 2 * Math.sqrt(2 / 3), 8);
  });
});
