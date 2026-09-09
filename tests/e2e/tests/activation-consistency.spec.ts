import {
  activation,
  expect,
  installWallet,
  mockActivations,
  mockServices,
  SERVICE,
  USDT,
  WBNB,
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

test("free activation disclosures agree with the free action", async ({
  page,
}) => {
  await page.goto("/activate?service=range-doctor");
  await expect(page.locator('[data-field="permissions"]')).toContainText(
    "No payment authorization",
  );
  await expect(page.locator('[data-field="custody"]')).toContainText(
    "No funds move",
  );
  await expect(
    page.getByRole("radio", { name: /Once/ }),
  ).not.toHaveAccessibleName(/one payment/);
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
  ["#limit-gas-total", "0"],
  ["#limit-gas-action", ""],
  ["#limit-gas-action", "0.2"],
  ["#limit-token-action-0", "200000000000000001"],
  ["#limit-token-total-0", "0"],
  ["#limit-token-total-0", "1.5"],
  ["#limit-token-action-0", "-1"],
]) {
  test(`invalid session limit ${field}=${value} is refused before wallet authorization`, async ({
    page,
  }) => {
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

test("session budgets reflect the owner choices without hidden token funding", async ({
  page,
}) => {
  await page.goto("/activate?service=range-doctor");
  await page.getByRole("radio", { name: /Continuously/ }).check();
  await page.locator("#limit-total").fill("0.5");
  await page.locator("#limit-action").fill("0.5");
  await page.locator("#limit-gas-total").fill("0.0005");
  await page.locator("#limit-gas-action").fill("0.0001");
  await page
    .locator("[data-token-budget]")
    .filter({ hasText: WBNB })
    .getByRole("checkbox")
    .uncheck();
  const created = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      new URL(request.url()).pathname === "/api/activations",
  );
  await page.getByRole("button", { name: /as a session/ }).click();
  const policy = (await created).postDataJSON().policy;
  expect(policy.total_cap_atomic).toEqual({
    [USDT]: "500000000000000000",
    BNB: "500000000000000",
  });
  expect(policy.per_action_limit_atomic).toEqual({
    [USDT]: "500000000000000000",
    BNB: "100000000000000",
  });
  expect(policy.token_allowlist).toContain(WBNB);
  await expect(page.locator("[data-limits-form]")).toContainText(
    "Owner wallet funding fees are separate",
  );
});

test("enabled secondary token budgets retain exact atomic amounts", async ({
  page,
}) => {
  await page.goto("/activate?service=range-doctor");
  await page.getByRole("radio", { name: /Continuously/ }).check();
  await page.locator("#limit-token-total-0").fill("100000000000000001");
  await page.locator("#limit-token-action-0").fill("100000000000000001");
  await page.locator("#limit-gas-total").fill("0.000000000000000001");
  await page.locator("#limit-gas-action").fill("0.000000000000000001");
  const created = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      new URL(request.url()).pathname === "/api/activations",
  );
  await page.getByRole("button", { name: /as a session/ }).click();
  const policy = (await created).postDataJSON().policy;
  expect(policy.total_cap_atomic[WBNB]).toBe("100000000000000001");
  expect(policy.per_action_limit_atomic[WBNB]).toBe("100000000000000001");
  expect(policy.total_cap_atomic.BNB).toBe("1");
  expect(policy.per_action_limit_atomic.BNB).toBe("1");
});

test("a failed free run is reported as failed in the activity log", async ({
  page,
}) => {
  await mockActivations(page, {
    onCreate: activation({ quote: { payment_scheme: "free_tier" } }),
    afterApprove: activation({ state: "failed" }),
  });
  await page.goto("/activate?service=range-doctor");
  await page.getByRole("button", { name: "Activate on the free tier" }).click();
  await expect(page.locator('.step[data-status="failed"]')).toContainText(
    "failed",
  );
  await expect(
    page.locator('[data-region="progress"] li').last(),
  ).toContainText("failed");
  await expect(
    page.getByRole("heading", { name: "Result", exact: true }),
  ).toHaveCount(0);
});

test("checking a timed-out activation reads its current state without authorizing again", async ({
  page,
}) => {
  await page.clock.install();
  await mockActivations(page, {
    onCreate: activation({ quote: { payment_scheme: "free_tier" } }),
    afterApprove: activation({ state: "queued" }),
    poll: [activation({ state: "completed" })],
  });
  await page.goto("/activate?service=range-doctor");
  await page.getByRole("button", { name: "Activate on the free tier" }).click();
  await expect(page.locator('.step[data-status="current"]')).toContainText(
    "queued",
  );
  await page.clock.fastForward(601000);
  await expect(
    page.getByRole("button", { name: "Check it now" }),
  ).toBeVisible();
  const signatures = await signedMessages(page);
  await page.getByRole("button", { name: "Check it now" }).click();
  await expect(page.locator('.step[data-status="current"]')).toContainText(
    "completed",
  );
  await expect(page.getByRole("button", { name: "Check it now" })).toHaveCount(
    0,
  );
  expect(await signedMessages(page)).toEqual(signatures);
});
