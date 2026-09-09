import { expect, test } from "@playwright/test";

for (const width of [1440, 768, 375]) {
  test(`comparison facts remain readable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/compare");
    await expect(page.getByRole("heading", { name: "Compare services" })).toBeVisible();
    await expect(page.locator("article")).toHaveCount(6);
    const measurements = await page.locator("article dd, article p").evaluateAll(
      (elements) => elements.map((element) => element.getBoundingClientRect().width),
    );
    expect(Math.min(...measurements)).toBeGreaterThan(180);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}
