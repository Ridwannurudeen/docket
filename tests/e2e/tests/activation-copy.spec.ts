import {
  expect,
  installNoWallet,
  mockServices,
  SERVICE,
  test,
} from "../fixtures";

for (const width of [375, 1440]) {
  test(`activation disclosures preserve the long mock service record at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await installNoWallet(page);
    const description =
      "A detailed service explanation. ".repeat(150) +
      "<b>Literal provider text</b>";
    await mockServices(page, { ...SERVICE, what_you_get: description });
    const writes: string[] = [];
    page.on("request", (request) => {
      if (request.method() !== "GET") writes.push(request.url());
    });
    await page.goto("/activate?service=range-doctor");
    const listing = page.locator('[data-region="listing"]');
    await expect(
      listing.getByRole("heading", { name: SERVICE.name, exact: true }),
    ).toBeVisible();
    await expect(
      listing.getByText(SERVICE.category_job, { exact: true }),
    ).toHaveCount(1);
    await expect(listing.locator("dt", { hasText: /^Job$/ })).toHaveCount(0);
    await expect(
      listing.getByText(SERVICE.price_display, { exact: true }),
    ).toBeVisible();
    await expect(listing.locator('[data-field="permissions"]')).toBeVisible();
    await expect(listing.locator('[data-field="custody"]')).toBeVisible();
    await expect(listing.locator('[data-field="stock-badge"]')).toBeVisible();
    await expect(
      listing.getByText(SERVICE.limitations, { exact: true }),
    ).toBeVisible();
    const full = listing
      .locator("details")
      .filter({
        has: page.locator("summary", { hasText: "Full service description" }),
      });
    const technical = listing
      .locator("details")
      .filter({
        has: page.locator("summary", {
          hasText: "Identity and payment details",
        }),
      });
    await expect(full).not.toHaveAttribute("open", "");
    await expect(full.locator("p")).toBeHidden();
    await expect(technical).not.toHaveAttribute("open", "");
    await expect(
      listing.getByText(SERVICE.identity, { exact: true }),
    ).toBeHidden();
    await page.screenshot({
      path: testInfo.outputPath(`activation-long-mock-${width}-closed.png`),
    });
    for (const disclosure of [full, technical]) {
      const summary = disclosure.locator("summary");
      expect((await summary.boundingBox())!.height).toBeGreaterThanOrEqual(44);
      await summary.focus();
      await page.keyboard.press("Enter");
      await expect(disclosure).toHaveAttribute("open", "");
    }
    await expect(full.locator("p")).toHaveText(description);
    await expect(full.locator("b")).toHaveCount(0);
    await expect(
      listing.getByText(SERVICE.identity, { exact: true }),
    ).toBeVisible();
    await expect(
      technical.getByText(SERVICE.price_atomic, { exact: true }),
    ).toBeVisible();
    await expect(
      technical.getByText(SERVICE.asset, { exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath(`activation-long-mock-${width}-open.png`),
      fullPage: true,
    });
    expect(writes).toEqual([]);
  });
}
