import {
  test,
  expect,
  SERVICE,
  USDT,
  WBNB,
  ACCOUNT,
  activation,
  installWallet,
  mockServices,
  mockActivations,
  mockHire,
  signedMessages,
} from "../fixtures";

test.beforeEach(async ({ page }) => {
  await installWallet(page);
  await mockServices(page, {
    ...SERVICE,
    category: "grid_trading",
    input_schema: {
      wallet: SERVICE.input_schema.wallet,
      base: { type: "string", required: false, default: WBNB },
      quote: { type: "string", required: false, default: USDT },
      levels: { type: "integer", required: false, default: 4 },
      lower: { type: "integer", required: false },
      price_lower: { type: "integer", required: false },
    },
  } as typeof SERVICE);
  await mockActivations(page);
});

test("Grid worked example excludes hidden activation fields", async ({
  page,
}) => {
  await mockHire(page);
  await page.goto("/activate?service=range-doctor");
  const sent = page.waitForRequest(
    (r) =>
      r.method() === "POST" &&
      new URL(r.url()).pathname === "/hire/range-doctor",
  );
  await page.getByRole("button", { name: "Use the worked example" }).click();
  expect((await sent).postDataJSON()).not.toHaveProperty("price_lower");
  await expect(
    page.getByRole("heading", { name: "Free sample result" }),
  ).toBeVisible();
});

test("Grid persistent inputs are separate and incomplete fields never open the wallet", async ({
  page,
}) => {
  await page.goto("/activate?service=range-doctor");
  await expect(page.locator('[name="price_lower"]')).toHaveCount(0);
  await page.getByRole("radio", { name: /Continuously/ }).check();
  await expect(page.getByLabel("Lower price (USDT per WBNB)")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Try free sample", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: /as a session/ }).click();
  await expect(page.locator('[data-region="outcome"]')).toContainText(
    "Complete",
  );
  expect(await signedMessages(page)).toEqual([]);
});

test("Grid decimal amounts survive review and creation exactly", async ({
  page,
}) => {
  await page.goto("/activate?service=range-doctor");
  await page.getByRole("radio", { name: /Continuously/ }).check();
  await page
    .getByLabel("Lower price (USDT per WBNB)")
    .fill("721.754918290690227007");
  await page
    .getByLabel("Upper price (USDT per WBNB)")
    .fill("723.202771687461922547");
  await page.getByLabel("Amount per level (USDT)").fill("0.250000000000000001");
  await page.getByLabel("Grid total cap (USDT)").fill("0.5");
  await page.locator("#limit-total").fill("0.500000000000000001");
  await page.locator("#limit-action").fill("0.250000000000000001");
  await page.getByRole("button", { name: /as a session/ }).click();
  await expect(
    page.getByRole("heading", { name: "Review Grid session" }),
  ).toBeVisible();
  expect(await signedMessages(page)).toEqual([]);
  const sent = page.waitForRequest(
    (r) =>
      r.method() === "POST" && new URL(r.url()).pathname === "/api/activations",
  );
  await page.getByRole("button", { name: "Confirm and open wallet" }).click();
  const request = (await sent).postDataJSON();
  const inputs = request.inputs;
  expect(request.policy.total_cap_atomic[USDT]).toBe("500000000000000001");
  expect(request.policy.per_action_limit_atomic[USDT]).toBe(
    "250000000000000001",
  );
  expect(inputs.price_lower).toBe("721754918290690227007");
  expect(inputs.amount_per_level_atomic).toBe("250000000000000001");
  expect(inputs).not.toHaveProperty("reference");
  expect(inputs).not.toHaveProperty("lower");
  expect(inputs.wallet).toBe(ACCOUNT);
});

test("editing a reviewed policy invalidates its confirmation", async ({
  page,
}) => {
  await page.goto("/activate?service=range-doctor");
  await page.getByRole("radio", { name: /Continuously/ }).check();
  for (const [name, value] of [
    ["price_lower", "700"],
    ["price_upper", "710"],
    ["amount_per_level_atomic", "0.25"],
    ["total_cap_atomic", "0.5"],
  ])
    await page.locator(`[name="${name}"]`).fill(value);
  await page.getByRole("button", { name: /as a session/ }).click();
  await expect(page.locator("[data-confirm-grid]")).toBeVisible();
  await page.locator("#limit-total").fill("0.6");
  await expect(page.locator("[data-confirm-grid]")).toHaveCount(0);
  expect(await signedMessages(page)).toEqual([]);
});

for (const [field, value] of [
  ["price_upper", "699"],
  ["stop_price", "705"],
  ["amount_per_level_atomic", "0.0000000000000000001"],
  ["levels", "65"],
]) {
  test(`invalid Grid ${field} is refused before signing`, async ({ page }) => {
    await page.goto("/activate?service=range-doctor");
    await page.getByRole("radio", { name: /Continuously/ }).check();
    for (const [name, initial] of [
      ["price_lower", "700"],
      ["price_upper", "710"],
      ["amount_per_level_atomic", "0.25"],
      ["total_cap_atomic", "0.5"],
    ])
      await page.locator(`[name="${name}"]`).fill(initial);
    await page.locator(`[data-grid-form] [name="${field}"]`).fill(value);
    await page.getByRole("button", { name: /as a session/ }).click();
    await expect(
      page.locator('[data-region="outcome"] [role="alert"]'),
    ).toBeVisible();
    expect(await signedMessages(page)).toEqual([]);
  });
}

test("My agents explains funding rather than minting when the session exists", async ({
  page,
}) => {
  await mockActivations(page, {
    listing: [
      activation({
        kind: "persistent",
        state: "awaiting_session",
        session: { address: ACCOUNT, funded_atomic: {}, spent_atomic: {} },
      }),
    ],
  });
  await page.goto("/my-agents");
  await expect(page.locator('[data-region="jobs"]')).toContainText(
    "The session address exists",
  );
  await expect(page.locator('[data-region="jobs"]')).not.toContainText(
    "minting",
  );
});

test("setup cannot change while the reviewed creation is awaiting its nonce", async ({
  page,
}) => {
  let release = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/activations/nonce*", async (route) => {
    await held;
    await route.fallback();
  });
  await page.goto("/activate?service=range-doctor");
  await page.getByRole("radio", { name: /Continuously/ }).check();
  for (const [name, value] of [
    ["price_lower", "700"],
    ["price_upper", "710"],
    ["amount_per_level_atomic", "0.25"],
    ["total_cap_atomic", "0.5"],
  ])
    await page.locator(`[name="${name}"]`).fill(value);
  await page.getByRole("button", { name: /as a session/ }).click();
  const nonce = page.waitForRequest(
    (r) => new URL(r.url()).pathname === "/api/activations/nonce",
  );
  await page.getByRole("button", { name: "Confirm and open wallet" }).click();
  await nonce;
  await expect(page.locator('[data-region="controls"]')).toHaveAttribute(
    "inert",
    "",
  );
  expect(await signedMessages(page)).toEqual([]);
  release();
  await expect(page.locator('[data-region="activation"]')).toBeVisible();
});
