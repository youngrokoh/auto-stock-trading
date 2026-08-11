import { expect, test } from "@playwright/test";

test("dashboard exposes safety and infrastructure state without browser secrets", async ({
  page,
}) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push(message.text());
    }
  });

  await page.goto("/");

  await expect(page.getByRole("heading", { name: "자동매매 운영 현황" })).toBeVisible();
  await expect(page.getByText("실전거래 비활성")).toBeVisible();
  await expect(page.getByText("PostgreSQL")).toBeVisible();
  await expect(page.getByText("Valkey")).toBeVisible();
  await expect(page.getByText("가짜 시장 데이터 없이 기반 상태만 표시합니다.")).toBeVisible();

  const bodyText = await page.locator("body").innerText();
  expect(bodyText).not.toContain("postgresql://");
  expect(bodyText).not.toContain("redis://");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  expect(consoleErrors).toEqual([]);
});

test("primitive showcase renders the approved component states", async ({ page }) => {
  await page.goto("/showcase");

  await expect(page.getByRole("heading", { name: "운영 UI 구성요소" })).toBeVisible();
  await expect(page.getByText("정상", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("확인 중", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("연결 안 됨", { exact: true }).first()).toBeVisible();
});
