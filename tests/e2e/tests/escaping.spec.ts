import {
  SERVICE,
  activation,
  expect,
  installWallet,
  mockActivations,
  mockAgents,
  mockHire,
  mockProviders,
  mockServices,
  test,
} from "../fixtures";

/* Every string these pages render was written by somebody other than Docket: a service
   name and its limitations come from the catalogue, an agent name and description come off
   chain, an error message comes from a server, a receipt field comes from a payment record,
   a failed check comes from a verification run. Each of those is a channel, and each one is
   pushed markup here.

   The assertion is deliberately behavioural rather than a check on the source: the question
   is not whether a template looks escaped, it is whether the browser ends up with an
   element. `PAYLOAD` uses an `img` with an `onerror` because that fires without any user
   action, so a page that failed to escape it would also record the breach. */

const PAYLOAD = '<img src=x onerror="window.__pwned=true">';
const MARKER = "onerror=";

async function assertRenderedAsText(page: import("@playwright/test").Page) {
  /* No element was created from the payload, and nothing it carried ever ran. */
  expect(await page.locator("img[onerror]").count()).toBe(0);
  expect(
    await page.evaluate(() => (window as { __pwned?: boolean }).__pwned),
  ).toBeUndefined();
  /* And the text is still on the page, verbatim, rather than silently dropped: a page that
     swallowed the value would pass the first two checks and tell the reader nothing. */
  expect(await page.locator("body").innerText()).toContain(MARKER);
}

test.beforeEach(async ({ page }) => {
  await installWallet(page);
});

test("a service name and its limitations reach the page as text", async ({
  page,
}) => {
  await mockServices(page, {
    ...SERVICE,
    name: `Range Doctor ${PAYLOAD}`,
    limitations: `It reads only. ${PAYLOAD}`,
    identity: `Registered as 311253. ${PAYLOAD}`,
  });
  await mockHire(page);
  await mockActivations(page);
  await page.goto("/activate?service=range-doctor");

  await expect(page.locator('[data-region="listing"] h1')).toContainText(
    MARKER,
  );
  await assertRenderedAsText(page);
});

test("an evidence link's label and url reach the page as text", async ({
  page,
}) => {
  await mockServices(page, {
    ...SERVICE,
    evidence: [
      {
        kind: "run",
        url: `/advantage/v1/01-liquidity" onmouseover="window.__pwned=true`,
        label: `Advantage task 01 ${PAYLOAD}`,
      },
    ],
  });
  await mockHire(page);
  await mockActivations(page);
  await page.goto("/activate?service=range-doctor");

  await assertRenderedAsText(page);
  expect(await page.locator("[onmouseover]").count()).toBe(0);
});

test("an error message from the server reaches the page as text", async ({
  page,
}) => {
  await mockServices(page);
  await mockActivations(page);
  await page.route("**/hire/range-doctor", (route) =>
    route.fulfill({
      status: 502,
      contentType: "application/json",
      body: JSON.stringify({
        error: {
          code: `service_failed ${PAYLOAD}`,
          message: `It broke. ${PAYLOAD}`,
        },
      }),
    }),
  );
  await page.goto("/activate?service=range-doctor");
  await page.getByRole("button", { name: "Try free sample" }).click();
  await expect(page.locator(".panel-error")).toBeVisible();

  await assertRenderedAsText(page);
});

test("a receipt field reaches the page as text", async ({ page }) => {
  await mockServices(page);
  await mockActivations(page);
  await page.route("**/hire/range-doctor", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        result: { summary: `all fine ${PAYLOAD}` },
        receipt: {
          service: `range-doctor ${PAYLOAD}`,
          delivered_at: "2026-09-03T10:00:00Z",
          input_hash: `0x${"a".repeat(64)} ${PAYLOAD}`,
          output_hash: `0x${"b".repeat(64)}`,
          payment: { status: "free_tier" },
        },
      }),
    }),
  );
  await page.goto("/activate?service=range-doctor");
  await page.getByRole("button", { name: "Try free sample" }).click();
  await expect(
    page.getByRole("heading", { name: "The receipt" }),
  ).toBeVisible();

  await assertRenderedAsText(page);
});

test("an agent name and description in search reach the page as text", async ({
  page,
}) => {
  await mockAgents(page, [
    {
      agent_id: `56:0x8004:409 ${PAYLOAD}`,
      name: `Somebody Else's Agent ${PAYLOAD}`,
      description: `Does things. ${PAYLOAD}`,
      category: `rebalancing ${PAYLOAD}`,
      service_id: null,
      verification: { level: "registered", evidence: [], verified_at: null },
    },
  ]);
  await page.goto("/search");
  await expect(page.locator(".result-row")).toBeVisible();

  await assertRenderedAsText(page);
});

test("a verification level Docket does not recognise cannot smuggle an attribute", async ({
  page,
}) => {
  await mockAgents(page, [
    {
      agent_id: "56:0x8004:409",
      name: "Somebody Else's Agent",
      service_id: null,
      verification: {
        level: `registered" onload="window.__pwned=true`,
        evidence: [],
        verified_at: null,
      },
    },
  ]);
  await page.goto("/search");
  await expect(page.locator(".verify-badge")).toBeVisible();

  expect(await page.locator("[onload]").count()).toBe(0);
  expect(
    await page.evaluate(() => (window as { __pwned?: boolean }).__pwned),
  ).toBeUndefined();
});

test("a failed check's detail reaches the provider page as text", async ({
  page,
}) => {
  await mockProviders(page, {
    level: "endpoint_detected",
    failedChecks: [
      { name: `live_probe ${PAYLOAD}`, detail: `No answer. ${PAYLOAD}` },
    ],
  });
  await page.goto("/providers");
  await page.locator("#provider-agent").fill("311253");
  await page.getByRole("button", { name: "Connect wallet and claim" }).click();
  await page.locator("#listing-capabilities").fill("Rebalances ranges");
  await page.locator("#listing-price").fill("500000000000000000");
  await page.getByRole("button", { name: "Publish listing" }).click();
  await expect(
    page.getByRole("heading", { name: "Listing status" }),
  ).toBeVisible();

  await assertRenderedAsText(page);
});

test("an activation's own fields reach my agents as text", async ({ page }) => {
  await mockActivations(page, {
    listing: [
      activation({
        service_id: `range-doctor ${PAYLOAD}`,
        state: `active ${PAYLOAD}`,
        kind: "persistent",
        session: {
          address: "0x9999999999999999999999999999999999999999",
          funded_atomic: {},
          spent_atomic: { [`0xtoken ${PAYLOAD}`]: `1 ${PAYLOAD}` },
        },
        policy: {
          contract_allowlist: [],
          total_cap_atomic: {},
          max_slippage_bps: 50,
          expires_at: `2026-10-03 ${PAYLOAD}`,
        },
      }),
    ],
  });
  await page.goto("/my-agents");
  await expect(page.locator(".jobs-table")).toBeVisible();

  await assertRenderedAsText(page);
});
