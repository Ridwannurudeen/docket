import {
  RECEIPT,
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

/* 390x844 is an iPhone 14. The one thing a phone reader cannot recover from is a page that
   scrolls sideways, because the content that ran off the edge is unreachable without
   knowing it is there. Every pivot surface is checked at that width, including the ones
   whose natural shape is a wide table. */

const MOBILE = { width: 390, height: 844 };

async function noHorizontalScroll(page: import("@playwright/test").Page) {
  return await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }));
}

test.use({ viewport: MOBILE });

test.beforeEach(async ({ page }) => {
  await installWallet(page);
  await mockServices(page);
  await mockHire(page);
});

test("the activate page fits the viewport", async ({ page }) => {
  await mockActivations(page);
  await page.goto("/activate?service=range-doctor");
  await expect(
    page.getByRole("heading", { name: "Range Doctor" }),
  ).toBeVisible();

  const { scroll, client } = await noHorizontalScroll(page);
  expect(scroll).toBeLessThanOrEqual(client);
});

test("the activate page still fits once a result and a receipt are on it", async ({
  page,
}) => {
  await mockActivations(page);
  await page.goto("/activate?service=range-doctor");
  await page.getByRole("button", { name: /Activate and pay/ }).click();
  await expect(page.getByRole("heading", { name: "Result" })).toBeVisible();

  const { scroll, client } = await noHorizontalScroll(page);
  expect(scroll).toBeLessThanOrEqual(client);
});

test("the activation table stacks rather than scrolling the page sideways", async ({
  page,
}) => {
  await mockActivations(page, {
    listing: [
      activation({
        kind: "persistent",
        state: "active",
        receipts: [RECEIPT],
        session: {
          address: "0x9999999999999999999999999999999999999999",
          funded_atomic: {},
          spent_atomic: {
            "0x55d398326f99059fF775485246999027B3197955": "2500000000000000000",
          },
        },
      }),
    ],
  });
  await page.goto("/my-agents");
  await expect(page.locator(".jobs-table")).toBeVisible();

  const { scroll, client } = await noHorizontalScroll(page);
  expect(scroll).toBeLessThanOrEqual(client);
});

test("search fits, filters and all", async ({ page }) => {
  await mockAgents(page, [
    {
      agent_id: "56:0x8004A169FB4a3325136EB29fA0ceB6D2e539a432:311253",
      name: "Range Doctor",
      category: "rebalancing",
      service_id: "range-doctor",
      verification: {
        level: "docket_verified",
        evidence: [
          { url: "/advantage/v1/01-liquidity", label: "Advantage task 01" },
        ],
        verified_at: "2026-09-03T10:00:00Z",
      },
    },
  ]);
  await page.goto("/search");
  await expect(page.locator(".result-row")).toBeVisible();

  const { scroll, client } = await noHorizontalScroll(page);
  expect(scroll).toBeLessThanOrEqual(client);
});

test("the provider flow fits", async ({ page }) => {
  await mockProviders(page);
  await page.goto("/providers");
  await expect(page.locator("#provider-agent")).toBeVisible();

  const { scroll, client } = await noHorizontalScroll(page);
  expect(scroll).toBeLessThanOrEqual(client);
});

test("the primary controls stay at a touchable size", async ({ page }) => {
  await mockActivations(page);
  await page.goto("/activate?service=range-doctor");

  const pay = page.getByRole("button", { name: /Activate and pay/ });
  const box = await pay.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.height).toBeGreaterThanOrEqual(44);
  expect(box!.width).toBeLessThanOrEqual(MOBILE.width);
});
