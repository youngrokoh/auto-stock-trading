import { expect, type Page, test } from "@playwright/test";

// CI는 마이그레이션만 적용된 빈 데이터베이스로 실행되므로 기본은 구조·빈 상태 검증이다.
// 실수집 데이터가 있는 로컬 환경에서는 E2E_EXPECT_DATA=1로 실데이터 검증까지 수행한다.
const expectData = process.env.E2E_EXPECT_DATA === "1";

const collectConsoleErrors = (page: Page): string[] => {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text());
    }
  });
  return errors;
};

const expectNoSecretsAndNoOverflow = async (page: Page): Promise<void> => {
  const bodyText = await page.locator("body").innerText();
  expect(bodyText).not.toContain("postgresql://");
  expect(bodyText).not.toContain("redis://");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
};

test("운영 개요가 실제 상태와 안전 경계를 표시한다", async ({ page }) => {
  const consoleErrors = collectConsoleErrors(page);

  await page.goto("/");

  await expect(page.getByRole("heading", { name: "운영 개요" })).toBeVisible();
  await expect(page.getByText("실전거래 비활성")).toBeVisible();
  await expect(page.getByText("A2 · PostgreSQL")).toBeVisible();
  await expect(page.getByText("A3 · Valkey")).toBeVisible();
  await expect(page.getByText("수집 파이프라인")).toBeVisible();
  if (expectData) {
    // 개요 표는 종목코드 오름차순 상위 10개만 보여준다(유니버스 201종목).
    await expect(page.getByText("전체 201종목은 시장 데이터 화면")).toBeVisible();
    await expect(page.getByText("SK하이닉스 000660")).toBeVisible();
  }

  await expectNoSecretsAndNoOverflow(page);
  expect(consoleErrors).toEqual([]);
});

test("시장 데이터 화면이 실데이터 시세·차트·표를 제공한다", async ({ page }) => {
  const consoleErrors = collectConsoleErrors(page);

  await page.goto("/market");

  await expect(page.getByRole("heading", { name: "시장 데이터" })).toBeVisible();
  await expect(page.getByText("A1 · 현재가 (원)")).toBeVisible();
  await expect(page.getByText("지연 데이터")).toBeVisible();
  if (expectData) {
    // 유니버스가 201종목이라 기본 선택 종목에는 일봉이 없다. 일봉을 가진 종목을 명시한다.
    const select = page.getByLabel("종목 선택");
    await select.selectOption("005930");
    await expect(page.getByRole("img", { name: "일봉 캔들 차트" })).toBeVisible();
    await expect(page.getByRole("img", { name: "RSI 차트" })).toBeVisible();
    await expect(page.getByRole("img", { name: "MACD 차트" })).toBeVisible();

    await select.selectOption("069500");
    await expect(page.getByText("D1")).toBeVisible();
    await expect(page.getByText("069500", { exact: true })).toBeVisible();
    await expect(page.getByText("ETF 분배금").first()).toBeVisible();

    await page.getByRole("button", { name: "1개월" }).click();
    await expect(page.getByRole("button", { name: "1개월" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(page.getByRole("img", { name: "일봉 캔들 차트" })).toBeVisible();
  } else {
    await expect(page.getByText("시세 확인 전")).toBeVisible();
  }

  await expectNoSecretsAndNoOverflow(page);
  expect(consoleErrors).toEqual([]);
});

test("기업 분석 화면이 수식·출처와 함께 재무 지표를 제공한다", async ({ page }) => {
  const consoleErrors = collectConsoleErrors(page);

  await page.goto("/analysis");

  await expect(page.getByRole("heading", { name: "기업 분석" })).toBeVisible();
  await expect(page.getByText("A1 · 매출액 (원)")).toBeVisible();
  await expect(page.getByText("A5 · ROE (지배주주)")).toBeVisible();
  await expect(page.getByText("공시 연결")).toBeVisible();
  if (expectData) {
    // 유니버스가 201종목이라 기본 선택 종목에는 재무 사실이 없다. 수집된 종목을 명시한다.
    await page.getByLabel("종목 선택").selectOption("005930");
    await expect(page.getByText("사업보고서 · 접수번호").first()).toBeVisible();
    await expect(page.getByRole("img", { name: "연간 실적 막대 차트" })).toBeVisible();
    await expect(page.getByText("연도별 지표")).toBeVisible();
    await expect(page.getByText("매출액증가율").first()).toBeVisible();
    await expect(page.getByText("PER", { exact: true })).toBeVisible();
    await expect(page.getByText("시가총액(보통주)")).toBeVisible();
    await expect(page.getByText("가격 기준")).toBeVisible();
    await expect(page.getByText("상장주식수", { exact: true })).toBeVisible();
    await expect(page.getByText("재무 기준")).toBeVisible();

    await page.getByRole("button", { name: "손익계산서" }).click();
    await expect(page.getByRole("button", { name: "손익계산서" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(page.getByText("매출액", { exact: true }).first()).toBeVisible();

    await expect(page.getByText("D2")).toBeVisible();
    await expect(page.getByText("순매수 수량(주)", { exact: false })).toBeVisible();

    await page.getByRole("button", { name: "개별" }).click();
    await expect(page.getByText("지배주주 계정 없음")).toBeVisible();
  } else {
    await expect(page.getByText("연간 보고서 확인 전")).toBeVisible();
    await expect(page.getByText("수집된 연간 사업보고서가 없습니다.")).toBeVisible();
  }

  await expectNoSecretsAndNoOverflow(page);
  expect(consoleErrors).toEqual([]);
});

test("ETF 탐색 화면이 순위와 상세를 기준시각과 함께 제공한다", async ({ page }) => {
  const consoleErrors = collectConsoleErrors(page);

  await page.goto("/etf");

  await expect(page.getByRole("heading", { name: "ETF 탐색" })).toBeVisible();
  await expect(page.getByText("A1 · ETF 종목 수")).toBeVisible();
  await expect(page.getByRole("heading", { name: "B 순위표" })).toBeVisible();
  await expect(page.getByRole("button", { name: "괴리율" })).toBeVisible();

  await page.getByRole("button", { name: "괴리율" }).click();
  await expect(page.getByRole("button", { name: "괴리율" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  if (expectData) {
    await expect(page.getByText("1,163").first()).toBeVisible();
    await expect(page.getByText("선택 ETF 상세")).toBeVisible();
    await expect(page.getByText("최근 12개월 분배율")).toBeVisible();
  } else {
    await expect(page.getByText("스냅샷 수집 전")).toBeVisible();
    await expect(page.getByText("수집된 스냅샷이 없습니다.")).toBeVisible();
  }

  await expectNoSecretsAndNoOverflow(page);
  expect(consoleErrors).toEqual([]);
});

test("전략 연구 화면이 저장된 백테스트 실행을 계보와 함께 제공한다", async ({ page }) => {
  const consoleErrors = collectConsoleErrors(page);

  await page.goto("/strategy");

  await expect(page.getByRole("heading", { name: "전략 연구" })).toBeVisible();
  await expect(page.getByText("A1 · 총수익률 (비용 후)")).toBeVisible();
  await expect(page.getByText("실전 반영 불가")).toBeVisible();
  await expect(page.getByText("누적 수익 곡선 · 드로다운")).toBeVisible();
  await expect(page.getByText("워크포워드 구간")).toBeVisible();
  await expect(page.getByText("검증·입력 계보")).toBeVisible();
  if (expectData) {
    await expect(page.getByRole("img", { name: "누적 수익 곡선 차트" })).toBeVisible();
    await expect(page.getByRole("img", { name: "드로다운 차트" })).toBeVisible();
    await expect(page.getByText("미래정보 누출 검사 통과")).toBeVisible();
    await expect(page.getByText("신호·체결 기록")).toBeVisible();
    await expect(page.getByText("비용 전 수익률")).toBeVisible();
    await expect(page.getByText("일봉 버전 해시")).toBeVisible();

    const select = page.getByLabel("실행 선택");
    const options = select.locator("option");
    expect(await options.count()).toBeGreaterThan(0);
    const lastValue = await options.last().getAttribute("value");
    await select.selectOption(lastValue ?? "");
    await expect(page.getByRole("img", { name: "누적 수익 곡선 차트" })).toBeVisible();
  } else {
    await expect(page.getByText("백테스트 실행 전")).toBeVisible();
    await expect(page.getByText("저장된 백테스트 실행이 없습니다.")).toBeVisible();
  }

  await expectNoSecretsAndNoOverflow(page);
  expect(consoleErrors).toEqual([]);
});

test("모의매매 콘솔이 자동매매 상태와 정책 한도를 표시한다", async ({ page }) => {
  const consoleErrors = collectConsoleErrors(page);

  await page.goto("/trading");

  await expect(page.getByRole("heading", { name: "모의매매 콘솔" })).toBeVisible();
  await expect(page.getByText("모의투자 전용 · 주문 제출 없음")).toBeVisible();
  await expect(page.getByText("A1 · 기준 NAV")).toBeVisible();
  await expect(page.getByText("A7 · 미체결")).toBeVisible();
  await expect(page.getByRole("heading", { name: "B 주문 내역" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "D 위험 한도 소진율" })).toBeVisible();
  await expect(page.getByText("총 투자 비중")).toBeVisible();
  await expect(page.getByText("분류되지 않은 종목 합계")).toBeVisible();
  await expect(page.getByText("업종별 비중")).toBeVisible();
  await expect(page.getByText("주문 허용시간", { exact: true })).toBeVisible();
  await expect(page.getByText("09:05~15:15 KST").first()).toBeVisible();
  if (expectData) {
    await expect(page.getByText("자동매매 비활성")).toBeVisible();
    await expect(page.getByRole("heading", { name: "E 주문·위험 이벤트" })).toBeVisible();
    await expect(page.getByText("상태 전이").first()).toBeVisible();
  } else {
    // 빈 DB에는 업종 사실이 없어 업종 한도가 사유 코드로 남는다.
    await expect(page.getByText("MISSING_SECTOR_DATA")).toBeVisible();
  }

  await expectNoSecretsAndNoOverflow(page);
  expect(consoleErrors).toEqual([]);
});

test("모의매매 콘솔이 계좌번호 원문을 노출하지 않는다", async ({ page }) => {
  await page.goto("/trading");

  await expect(page.getByRole("heading", { name: "C 보유 포지션" })).toBeVisible();
  const bodyText = await page.locator("body").innerText();
  expect(bodyText).not.toMatch(/계좌 \d{8}/);
  expect(bodyText).not.toContain("50123456");
});

test("구성요소 갤러리가 승인된 프리미티브 상태를 표시한다", async ({ page }) => {
  const consoleErrors = collectConsoleErrors(page);

  await page.goto("/showcase");

  await expect(page.getByRole("heading", { name: "구성요소 갤러리" })).toBeVisible();
  await expect(page.getByText("좌표 셀")).toBeVisible();
  await expect(page.getByText("ACCOUNT_NOT_RECONCILED")).toBeVisible();
  await expect(page.getByText("단계 미도달 빈 상태")).toBeVisible();

  await expectNoSecretsAndNoOverflow(page);
  expect(consoleErrors).toEqual([]);
});
