import {
  activation,
  expect,
  installWallet,
  mockActivations,
  mockServices,
  SERVICE,
  signedMessages,
  test,
} from "../fixtures";

test.beforeEach(async ({ page }) => {
  await installWallet(page);
  await mockServices(page, {
    ...SERVICE,
    paid_stock: false,
    stock_status: "not_admitted",
  });
  await mockActivations(page);
});

test("free activation disclosures agree with the free action", async ({ page }) => {
  await page.goto("/activate?service=range-doctor");
  await expect(page.locator('[data-field="permissions"]')).toContainText(
    "No payment authorization",
  );
  await expect(page.locator('[data-field="custody"]')).toContainText(
    "No funds move",
  );
  await expect(page.getByRole("radio", { name: /Once/ })).not.toHaveAccessibleName(
    /one payment/,
  );
  await expect(page.locator('[data-field="activation-means"]')).toContainText(
    "It does not execute trades",
  );
  await page.getByRole("radio", { name: /Continuously/ }).check();
  await expect(page.locator('[data-field="permissions"]')).toContainText(
    "software",
  );
  await expect(page.locator('[data-field="price"]')).toContainText(
    "you supply session funds and gas",
  );
  await page.getByRole("radio", { name: /Once/ }).check();
  await expect(page.locator('[data-field="custody"]')).toContainText(
    "No funds move",
  );
});

for (const [field, value] of [
  ["#limit-expiry", "1.5"],
  ["#limit-expiry", "366"],
  ["#limit-slippage", "10001"],
  ["#limit-slippage", ""],
  ["#limit-gas", "0"],
]) {
  test(`invalid session limit ${field}=${value} is refused before wallet authorization`, async ({ page }) => {
    await page.goto("/activate?service=range-doctor");
    await page.getByRole("radio", { name: /Continuously/ }).check();
    await page.locator(field).fill(value);
    await page.getByRole("button", { name: /as a session/ }).click();
    await expect(page.locator('[data-region="outcome"]')).toContainText(
      "invalid_limits",
    );
    expect(await signedMessages(page)).toEqual([]);
    await expect(page.locator('[data-region="activation"]')).toBeHidden();
  });
}

test("a failed free run is reported as failed in the activity log", async ({ page }) => {
  await mockActivations(page, {
    onCreate: activation({ quote: { payment_scheme: "free_tier" } }),
    afterApprove: activation({ state: "failed" }),
  });
  await page.goto("/activate?service=range-doctor");
  await page.getByRole("button", { name: "Activate on the free tier" }).click();
  await expect(page.locator('.step[data-status="failed"]')).toContainText("failed");
  await expect(page.locator('[data-region="progress"] li').last()).toContainText(
    "failed",
  );
  await expect(page.getByRole("heading", { name: "Result", exact: true })).toHaveCount(0);
});

test("checking a timed-out activation reads its current state without authorizing again", async ({ page }) => {
  await page.clock.install();
  await mockActivations(page, {
    onCreate: activation({ quote: { payment_scheme: "free_tier" } }),
    afterApprove: activation({ state: "queued" }),
    poll: [activation({ state: "completed" })],
  });
  await page.goto("/activate?service=range-doctor");
  await page.getByRole("button", { name: "Activate on the free tier" }).click();
  await expect(page.locator('.step[data-status="current"]')).toContainText("queued");
  await page.clock.fastForward(601000);
  await expect(page.getByRole("button", { name: "Check it now" })).toBeVisible();
  const signatures = await signedMessages(page);
  await page.getByRole("button", { name: "Check it now" }).click();
  await expect(page.locator('.step[data-status="current"]')).toContainText("completed");
  await expect(page.getByRole("button", { name: "Check it now" })).toHaveCount(0);
  expect(await signedMessages(page)).toEqual(signatures);
});
