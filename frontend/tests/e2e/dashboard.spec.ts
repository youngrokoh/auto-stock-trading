import { expect, type Page, test } from "@playwright/test";

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
  await expect(page.getByText("삼성전자 005930")).toBeVisible();

  await expectNoSecretsAndNoOverflow(page);
  expect(consoleErrors).toEqual([]);
});

test("시장 데이터 화면이 실데이터 시세·차트·표를 제공한다", async ({ page }) => {
  const consoleErrors = collectConsoleErrors(page);

  await page.goto("/market");

  await expect(page.getByRole("heading", { name: "시장 데이터" })).toBeVisible();
  await expect(page.getByText("A1 · 현재가 (원)")).toBeVisible();
  await expect(page.getByRole("img", { name: "일봉 캔들 차트" })).toBeVisible();
  await expect(page.getByRole("img", { name: "RSI 차트" })).toBeVisible();
  await expect(page.getByRole("img", { name: "MACD 차트" })).toBeVisible();
  await expect(page.getByText("지연 데이터")).toBeVisible();

  const select = page.getByLabel("종목 선택");
  await select.selectOption("069500");
  await expect(page.getByText("D1")).toBeVisible();
  await expect(page.getByText("069500", { exact: true })).toBeVisible();
  await expect(page.getByText("ETF 분배금").first()).toBeVisible();

  await page.getByRole("button", { name: "1개월" }).click();
  await expect(page.getByRole("button", { name: "1개월" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("img", { name: "일봉 캔들 차트" })).toBeVisible();

  await expectNoSecretsAndNoOverflow(page);
  expect(consoleErrors).toEqual([]);
});

test("기업 분석 화면이 수식·출처와 함께 재무 지표를 제공한다", async ({ page }) => {
  const consoleErrors = collectConsoleErrors(page);

  await page.goto("/analysis");

  await expect(page.getByRole("heading", { name: "기업 분석" })).toBeVisible();
  await expect(page.getByText("A1 · 매출액 (원)")).toBeVisible();
  await expect(page.getByText("A5 · ROE (지배주주)")).toBeVisible();
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
  await expect(page.getByText("D3")).toBeVisible();
  await expect(page.getByText("공시 연결")).toBeVisible();

  await page.getByRole("button", { name: "개별" }).click();
  await expect(page.getByText("지배주주 계정 없음")).toBeVisible();

  await expectNoSecretsAndNoOverflow(page);
  expect(consoleErrors).toEqual([]);
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
