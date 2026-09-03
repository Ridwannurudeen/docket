import {
  expect,
  installWallet,
  mockAgents,
  mockProviders,
  signedMessages,
  test,
} from "../fixtures";

const VERIFIED = {
  agent_id: "56:0x8004A169FB4a3325136EB29fA0ceB6D2e539a432:311253",
  name: "Range Doctor",
  category: "rebalancing",
  service_id: "range-doctor",
  description:
    "Reads PancakeSwap v3 positions and says whether each is in range.",
  verification: {
    level: "docket_verified",
    evidence: [
      { url: "/advantage/v1/01-liquidity", label: "Advantage task 01" },
    ],
    verified_at: "2026-09-03T10:00:00Z",
  },
};

const UNTESTED = {
  agent_id: "56:0x8004A169FB4a3325136EB29fA0ceB6D2e539a432:409",
  name: "Somebody Else's Agent",
  category: null,
  service_id: null,
  endpoint: "https://example.invalid/a2a",
  verification: { level: "registered", evidence: [], verified_at: null },
};

test.describe("search", () => {
  test.beforeEach(async ({ page }) => {
    await installWallet(page);
    await mockAgents(page, [VERIFIED, UNTESTED]);
  });

  test("a verified listing is activated here and an untested one is not", async ({
    page,
  }) => {
    await page.goto("/search");
    await expect(page.locator(".result-row")).toHaveCount(2);

    const verified = page.locator(`[data-agent="${VERIFIED.agent_id}"]`);
    await expect(verified.locator(".verify-badge")).toHaveText(
      "docket verified",
    );
    await expect(
      verified.getByRole("link", { name: "Activate" }),
    ).toHaveAttribute("href", "/activate?service=range-doctor");

    const untested = page.locator(`[data-agent="${UNTESTED.agent_id}"]`);
    await expect(untested.locator(".verify-badge")).toHaveText("registered");
    await expect(
      untested.getByRole("link", { name: "Read what Docket observed" }),
    ).toHaveAttribute(
      "href",
      `/agent?id=${encodeURIComponent(UNTESTED.agent_id)}`,
    );
    await expect(untested.getByRole("link", { name: "Activate" })).toHaveCount(
      0,
    );
    await expect(
      untested.getByText(
        "Docket has not run this agent, so it cannot be activated here.",
      ),
    ).toBeVisible();
  });

  test("the page says plainly that an untested registry entry is not hireable", async ({
    page,
  }) => {
    await page.goto("/search");
    await expect(
      page.getByText("1 of these are registry entries Docket has not run"),
    ).toBeVisible();
    await expect(
      page.getByText("not hireable from this site", { exact: false }),
    ).toBeVisible();
  });

  test("filters travel in the address, so a narrowed view is a link", async ({
    page,
  }) => {
    const queries: string[] = [];
    await page.route("**/api/agents*", async (route) => {
      queries.push(new URL(route.request().url()).search);
      await route.fallback();
    });
    await page.goto("/search");

    await page.locator("#search-q").fill("range");
    await page.locator("#search-category").selectOption("rebalancing");
    await page.locator("#search-level").selectOption("docket_tested");
    await page.getByRole("button", { name: "Search", exact: true }).click();

    await expect(page).toHaveURL(
      /q=range&category=rebalancing&level=docket_tested/,
    );
    expect(queries.at(-1)).toBe(
      "?q=range&category=rebalancing&level=docket_tested",
    );
  });

  test("no match is stated as an answer, not left blank", async ({ page }) => {
    await mockAgents(page, []);
    await page.goto("/search?q=nothing");

    await expect(
      page.getByRole("heading", { name: "No agent matched" }),
    ).toBeVisible();
    await expect(
      page.getByText("A zero here is the answer, not a gap."),
    ).toBeVisible();
  });
});

test.describe("providers", () => {
  test.beforeEach(async ({ page }) => {
    await installWallet(page);
  });

  test("a claim signs the server's own message before anything is listed", async ({
    page,
  }) => {
    await mockProviders(page);
    await page.goto("/providers");

    await page.locator("#provider-agent").fill("311253");
    await page
      .getByRole("button", { name: "Connect wallet and claim" })
      .click();

    await expect(
      page.getByRole("heading", { name: "Ownership proved" }),
    ).toBeVisible();
    expect(await signedMessages(page)).toEqual([
      "Docket listing claim 311253 claim-nonce",
    ]);

    await page.locator("#listing-category").selectOption("rebalancing");
    await page
      .locator("#listing-capabilities")
      .fill("Rebalances v3 ranges\nReports fees");
    await page.locator("#listing-price").fill("500000000000000000");
    await page.getByRole("button", { name: "Publish listing" }).click();

    await expect(
      page.getByRole("heading", { name: "Listing status" }),
    ).toBeVisible();
    await expect(page.locator(".verify-badge")).toHaveText("docket tested");
    await expect(
      page.getByText("Every check Docket ran against this listing passed."),
    ).toBeVisible();
  });

  test("failed checks are published beside the listing rather than hidden", async ({
    page,
  }) => {
    await mockProviders(page, {
      level: "endpoint_detected",
      failedChecks: [
        {
          name: "live_probe",
          detail: "The declared endpoint did not answer within 8 seconds.",
        },
        {
          name: "payment_tested",
          detail: "No payment challenge was returned.",
        },
      ],
    });
    await page.goto("/providers?agent=311253");
    await expect(page.locator("#provider-agent")).toHaveValue("311253");

    await page
      .getByRole("button", { name: "Connect wallet and claim" })
      .click();
    await page.locator("#listing-capabilities").fill("Rebalances v3 ranges");
    await page.locator("#listing-price").fill("500000000000000000");
    await page.getByRole("button", { name: "Publish listing" }).click();

    await expect(page.getByText("2 checks did not pass")).toBeVisible();
    await expect(
      page.getByText("The declared endpoint did not answer within 8 seconds."),
    ).toBeVisible();
    await expect(page.locator(".verify-badge")).toHaveText("endpoint detected");
    await expect(
      page.getByText("nothing here is a permanent verdict", { exact: false }),
    ).toBeVisible();
  });

  test("a rejected claim leaves nothing listed and says so", async ({
    page,
  }) => {
    await mockProviders(page);
    await page.goto("/providers");
    await page.locator("#provider-agent").fill("311253");
    await page.evaluate(() => {
      (
        window as unknown as { __wallet: { rejectNext: string } }
      ).__wallet.rejectNext = "personal_sign";
    });
    await page
      .getByRole("button", { name: "Connect wallet and claim" })
      .click();

    await expect(
      page.getByRole("heading", { name: "That identity was not claimed" }),
    ).toBeVisible();
    await expect(page.getByText("Nothing was published.")).toBeVisible();
    await expect(page.locator("#listing-category")).toHaveCount(0);
  });
});
