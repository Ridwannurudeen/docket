import { expect, installWallet, mockAgents, mockProviders, mockServices, test } from "../fixtures";

test("verification eligibility does not advertise a registry listing for sale", async ({ page }) => {
  await installWallet(page);
  await mockProviders(page, { level: "docket_tested", hireable: true });
  await page.goto("/providers?agent=311253");
  await page.getByRole("button", { name: "Connect wallet and claim" }).click();
  await page.locator("#listing-capabilities").fill("Reads LP positions");
  await page.getByRole("button", { name: "Publish listing" }).click();
  const status = page.getByRole("region", { name: "Listing status" });
  await expect(status.getByText("Verification eligibility", { exact: true })).toBeVisible();
  await expect(status).toContainText("Research record only, not hireable from this site.");
  await expect(status).not.toContainText("Offered by Docket");
});

test("a voided provider claim removes the unusable publish form", async ({ page }) => {
  await installWallet(page);
  await mockProviders(page, {
    listingError: { status: 409, error_code: "stale_nonce", message: "Claim expired." },
  });
  await page.goto("/providers?agent=311253");
  await page.getByRole("button", { name: "Connect wallet and claim" }).click();
  await page.locator("#listing-capabilities").fill("Reads LP positions");
  await page.getByRole("button", { name: "Publish listing" }).click();
  await expect(page.getByText("stale_nonce")).toBeVisible();
  await expect(page.getByRole("button", { name: "Publish listing" })).toHaveCount(0);
  await expect(page.locator('[data-region="ownership"]')).toBeEmpty();
  await mockProviders(page);
  await page.getByRole("button", { name: "Connect wallet and claim" }).click();
  await page.locator("#listing-capabilities").fill("Reads LP positions");
  await page.getByRole("button", { name: "Publish listing" }).click();
  await expect(page.getByRole("region", { name: "Listing status" })).toBeVisible();
});

test("signing a claim does not announce verified ownership", async ({ page }) => {
  await installWallet(page);
  await mockProviders(page);
  await page.goto("/providers?agent=311253");
  await page.getByRole("button", { name: "Connect wallet and claim" }).click();
  await expect(page.getByRole("heading", { name: "Claim signed" })).toBeVisible();
  await expect(page.getByText("Ownership is checked when you publish the listing.")).toBeVisible();
});

test("an older search response cannot replace the latest query", async ({ page }) => {
  await mockServices(page);
  await mockAgents(page, []);
  let releaseOld: () => void = () => {};
  const oldReleased = new Promise<void>((resolve) => { releaseOld = resolve; });
  let markOldStarted: () => void = () => {};
  const oldStarted = new Promise<void>((resolve) => { markOldStarted = resolve; });
  await page.route("**/api/agents?**", async (route) => {
    if (new URL(route.request().url()).searchParams.get("q") !== "old") {
      await route.fallback();
      return;
    }
    markOldStarted();
    await oldReleased;
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [], total: 0 }) });
  });
  await page.goto("/search");
  await page.getByLabel("Search", { exact: true }).fill("old");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await oldStarted;
  await page.getByLabel("Search", { exact: true }).fill("Range");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.locator('[data-service="range-doctor"]')).toBeVisible();
  const response = page.waitForResponse((answer) => new URL(answer.url()).searchParams.get("q") === "old");
  releaseOld();
  await (await response).finished();
  await expect(page.locator('[data-service="range-doctor"]')).toBeVisible();
  await expect(page.locator('[data-field="result-count"]')).toContainText('"Range"');
});
