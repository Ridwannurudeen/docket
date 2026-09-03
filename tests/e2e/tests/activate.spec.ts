import {
  ACCOUNT,
  PAY_TO,
  PRICE_ATOMIC,
  RELAYER,
  USDT,
  activation,
  expect,
  installWallet,
  mockActivations,
  mockHire,
  mockServices,
  signedMessages,
  test,
} from "../fixtures";

/* The walk the pivot exists to make possible: land, pick a job, open the agent, see what it
   costs and what it may do, send it something, pay for it, get an answer and a receipt. */

test.beforeEach(async ({ page }) => {
  await installWallet(page);
  await mockServices(page);
  await mockHire(page);
  await mockActivations(page);
});

test("a reader walks from the home page to a paid result and its receipt", async ({
  page,
}) => {
  await page.goto("/");

  /* The home leads with the four jobs. Following the rebalancing one reaches the agent
     that stands in it. */
  await page.getByRole("link", { name: "Run Range Doctor" }).click();
  await expect(page).toHaveURL(/\/service\?id=range-doctor/);

  /* The activation step the site did not have before this lane. */
  await page.getByRole("link", { name: "Activate", exact: true }).click();
  await expect(page).toHaveURL(/\/activate\?service=range-doctor/);

  await expect(
    page.getByRole("heading", { name: "Range Doctor" }),
  ).toBeVisible();
  /* Price, permissions and custody are stated before anything can be signed. */
  await expect(
    page.getByText("0.50 USDT", { exact: false }).first(),
  ).toBeVisible();
  await expect(
    page.getByText("Two wallet actions and no standing permission"),
  ).toBeVisible();
  await expect(page.getByText("No custody.", { exact: false })).toBeVisible();

  /* The sample form arrives prefilled from the service's own worked example. */
  const wallet = page.locator("#field-wallet");
  await expect(wallet).toHaveValue(PAY_TO);
  await wallet.fill("0x2222222222222222222222222222222222222222");

  await page
    .getByRole("button", { name: /Activate and pay 0\.50 USDT/ })
    .click();

  await expect(page.getByRole("heading", { name: "Result" })).toBeVisible();
  await expect(page.getByText("positions_examined")).toBeVisible();

  /* The receipt, with both hashes and the settlement it records. */
  await expect(
    page.getByRole("heading", { name: "The receipt" }),
  ).toBeVisible();
  await expect(
    page.getByText("settled", { exact: false }).first(),
  ).toBeVisible();
  await expect(page.locator("[data-receipt-json]")).toContainText(
    "output_hash",
  );
  await expect(
    page.getByRole("button", { name: "Copy receipt JSON" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Download receipt" }),
  ).toHaveAttribute("download", /docket-receipt/);

  /* The stepper reflects the activation, and the activation is bound to the payment. */
  await expect(page.locator('.step[data-status="current"]')).toHaveText(
    /completed/,
  );
});

test("the paid leg sends the exact x402 shapes the server verifies", async ({
  page,
}) => {
  const paid: Array<{ header: string; body: string }> = [];
  await page.route("**/hire/range-doctor", async (route) => {
    const header = route.request().headers()["x-payment"];
    if (header && header !== "challenge-request") {
      paid.push({ header, body: route.request().postData() ?? "" });
    }
    await route.fallback();
  });

  await page.goto("/activate?service=range-doctor");
  await page.getByRole("button", { name: /Activate and pay/ }).click();
  await expect(page.getByRole("heading", { name: "Result" })).toBeVisible();

  expect(paid).toHaveLength(1);
  const envelope = JSON.parse(
    Buffer.from(paid[0].header, "base64").toString("utf-8"),
  );
  expect(envelope.x402Version).toBe(2);
  expect(envelope.accepted.amount).toBe(PRICE_ATOMIC);
  expect(envelope.accepted.payTo).toBe(PAY_TO);
  expect(envelope.resource.url).toContain("/hire/range-doctor");

  const authorization = envelope.payload.authorization;
  expect(Object.keys(authorization).sort()).toEqual(
    [
      "from",
      "nonce",
      "to",
      "token",
      "validAfter",
      "validBefore",
      "value",
    ].sort(),
  );
  expect(authorization.token).toBe(USDT);
  expect(authorization.from).toBe(ACCOUNT);
  expect(authorization.to).toBe(PAY_TO);
  expect(authorization.value).toBe(PRICE_ATOMIC);
  expect(authorization.nonce).toMatch(/^0x[0-9a-f]{64}$/);
  /* The window opens before now and closes no later than the advertised timeout, which is
     what the server checks both ends of. */
  expect(
    authorization.validBefore - authorization.validAfter,
  ).toBeLessThanOrEqual(360);
  expect(envelope.payload.signature).toMatch(/^0x[0-9a-f]{130}$/);

  /* Canonical JSON: the header the browser encodes is byte-identical to the one Python
     produces from the same envelope. */
  expect(paid[0].header).toBe(
    Buffer.from(canonical(envelope), "utf-8").toString("base64"),
  );
});

function canonical(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${canonical(record[key])}`)
    .join(",")}}`;
}

test("a short allowance is approved for the exact price and never more", async ({
  page,
}) => {
  await page.addInitScript(() => {
    /* The relayer may pull nothing yet, so the page has to approve before it can pay. */
    const control = (window as unknown as { __wallet: { allowance: string } })
      .__wallet;
    if (control) control.allowance = "0".repeat(64);
  });
  await page.goto("/activate?service=range-doctor");
  await page.evaluate(() => {
    (
      window as unknown as { __wallet: { allowance: string } }
    ).__wallet.allowance = "0".repeat(64);
  });

  await page.getByRole("button", { name: /Activate and pay/ }).click();
  await expect(page.getByRole("heading", { name: "Result" })).toBeVisible();

  const sent = await page.evaluate(() =>
    (
      window as unknown as {
        __wallet: { calls: Array<{ method: string; params: unknown }> };
      }
    ).__wallet.calls
      .filter((call) => call.method === "eth_sendTransaction")
      .map((call) => (call.params as Array<{ to: string; data: string }>)[0]),
  );
  expect(sent).toHaveLength(1);
  expect(sent[0].to).toBe(USDT);
  /* approve(relayer, 500000000000000000) and nothing wider. */
  expect(sent[0].data).toBe(
    "0x095ea7b3" +
      RELAYER.slice(2).toLowerCase().padStart(64, "0") +
      500000000000000000n.toString(16).padStart(64, "0"),
  );
  await expect(
    page.getByText(/Approved exactly 500000000000000000/),
  ).toBeVisible();
});

test("the free sample runs with no wallet, no charge and no activation", async ({
  page,
}) => {
  await page.goto("/activate?service=range-doctor&demo=1");

  await expect(
    page.getByRole("heading", { name: "Free sample result" }),
  ).toBeVisible();
  await expect(
    page.getByText("Nothing was charged, no wallet was used", { exact: false }),
  ).toBeVisible();
  expect(await signedMessages(page)).toHaveLength(0);
  await expect(page.locator('[data-region="activation"]')).toBeHidden();
});

test("choosing a continuous session reveals its limits and states the custody", async ({
  page,
}) => {
  await page.goto("/activate?service=range-doctor");
  await expect(page.locator('[data-region="limits"]')).toBeHidden();

  await page.getByRole("radio", { name: /Continuously/ }).check();

  await expect(page.locator('[data-region="limits"]')).toBeVisible();
  await expect(page.locator("#limit-total")).toBeVisible();
  await expect(
    page.getByText("Revoking sweeps every allowlisted token"),
  ).toBeVisible();
});

test("a category with no service says so instead of showing an empty page", async ({
  page,
}) => {
  await page.route("**/services?category=*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        services: [],
        total: 0,
        category: "grid_trading",
      }),
    }),
  );
  await page.goto("/activate?category=grid_trading");

  await expect(
    page.getByRole("heading", { name: "Nothing to activate" }),
  ).toBeVisible();
  await expect(page.getByText("category_empty")).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Pick a service" }),
  ).toBeVisible();
});

test("the activation is bound with a signature over the message the plan specifies", async ({
  page,
}) => {
  await page.goto("/activate?service=range-doctor");
  await page.getByRole("button", { name: /Activate and pay/ }).click();
  await expect(page.getByRole("heading", { name: "Result" })).toBeVisible();

  const signed = await signedMessages(page);
  expect(signed).toEqual([
    "Docket activation create range-doctor nonce-one",
    `Docket activation ${activation().activation_id} approve nonce-two`,
  ]);
});

test("leaving BNB Smart Chain mid-flow is said at the moment it happens", async ({
  page,
}) => {
  await page.goto("/activate?service=range-doctor");
  await expect(page.locator('[data-region="chain"]')).toBeHidden();

  await page.evaluate(() => {
    const provider = window.ethereum as unknown as {
      emit: (event: string, value: unknown) => void;
    };
    provider.emit("chainChanged", "0x1");
  });

  const notice = page.locator('[data-region="chain"]');
  await expect(notice).toBeVisible();
  await expect(notice).toContainText("no longer on BNB Smart Chain");
  await expect(notice).toContainText("0x1");
  await expect(notice).toContainText("Nothing already signed is affected.");

  /* And it clears itself when the wallet comes back, rather than standing as a warning
     about a state the reader has already fixed. */
  await page.evaluate(() => {
    const provider = window.ethereum as unknown as {
      emit: (event: string, value: unknown) => void;
    };
    provider.emit("chainChanged", "0x38");
  });
  await expect(notice).toBeHidden();
});
