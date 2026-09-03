import {
  expect,
  installWallet,
  mockAgents,
  mockProviders,
  mockServices,
  signedMessages,
  test,
} from "../fixtures";

/* A listing Docket has run and settled a payment with. `hireable` is the server's own
   decision and the page reads it rather than recomputing it from the level. */
const OFFERED = {
  agent_id: "56:0x8004A169FB4a3325136EB29fA0ceB6D2e539a432:311253",
  name: "Somebody's Range Agent",
  category: "rebalancing",
  capability_source: "provider_declared",
  capabilities:
    "Reads PancakeSwap v3 positions and says whether each is in range.",
  price: "0.50 USDT",
  payment_method: "x402",
  endpoints: [{ kind: "a2a", url: "https://example.invalid/a2a" }],
  verification: {
    level: "docket_verified",
    payment_tested: true,
    payment_tested_evidence: { level: "payment_tested", ok: true },
    evidence: [
      { level: "live", ok: true, at: "2026-09-03T09:00:00Z" },
      { level: "payment_tested", ok: true, at: "2026-09-03T09:01:00Z" },
    ],
    verified_at: "2026-09-03T10:00:00Z",
  },
  hireable: true,
};

/* The case the payment_tested boolean exists for: a listing that reached `docket_tested`
   without any payment challenge ever being exercised against it. */
const TESTED_UNPAID = {
  agent_id: "56:0x8004A169FB4a3325136EB29fA0ceB6D2e539a432:409",
  name: "Somebody Else's Agent",
  category: "grid_trading",
  capability_source: "docket_classified",
  capabilities: "Places grid orders.",
  price: null,
  endpoints: [{ kind: "web", url: "https://example.invalid/" }],
  verification: {
    level: "docket_tested",
    payment_tested: false,
    payment_tested_evidence: null,
    evidence: [
      { level: "live", ok: true, at: "2026-09-03T09:00:00Z" },
      { level: "payment_tested", ok: false, at: "2026-09-03T09:01:00Z" },
    ],
    verified_at: "2026-09-03T10:00:00Z",
  },
  hireable: false,
};

const UNSEEN = {
  agent_id: "56:0x8004A169FB4a3325136EB29fA0ceB6D2e539a432:777",
  name: "Never Reached",
  category: null,
  capability_source: "registration_metadata",
  capabilities: "",
  endpoints: [],
  verification: {
    level: null,
    payment_tested: false,
    payment_tested_evidence: null,
    evidence: [],
    verified_at: null,
  },
  hireable: false,
};

test.describe("search", () => {
  test.beforeEach(async ({ page }) => {
    await installWallet(page);
    await mockServices(page);
    await mockAgents(page, [OFFERED, TESTED_UNPAID, UNSEEN]);
  });

  test("the two layers are labelled and only Docket's own is activatable", async ({
    page,
  }) => {
    await page.goto("/search");
    await expect(
      page.getByRole("heading", { name: "Services Docket runs" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Third-party agents Docket observed" }),
    ).toBeVisible();

    /* Docket's own layer carries the only Activate control on the page. */
    const docket = page.locator('[data-service="range-doctor"]');
    await expect(
      docket.getByRole("link", { name: "Activate" }),
    ).toHaveAttribute("href", "/activate?service=range-doctor");
    /* Every Activate control on the page belongs to the Docket layer; the registry
       section carries none at all. */
    const registry = page.locator(
      'section[aria-labelledby="registry-layer-heading"]',
    );
    await expect(registry.getByRole("link", { name: "Activate" })).toHaveCount(0);

    /* Even the hireable third-party listing is read, not bought, from this site. */
    const offered = page.locator(`[data-agent="${OFFERED.agent_id}"]`);
    await expect(
      offered.getByRole("link", { name: "Read what Docket observed" }),
    ).toHaveAttribute(
      "href",
      `/agent?id=${encodeURIComponent(OFFERED.agent_id)}`,
    );
    await expect(offered.getByRole("link", { name: "Activate" })).toHaveCount(
      0,
    );
  });

  test("payment_tested is its own badge and a level never stands in for it", async ({
    page,
  }) => {
    await page.goto("/search");

    const unpaid = page.locator(`[data-agent="${TESTED_UNPAID.agent_id}"]`);
    await expect(unpaid.locator('[data-level="docket_tested"]')).toBeVisible();
    await expect(unpaid.locator('[data-payment-tested="no"]')).toHaveText(
      "payment untested",
    );

    const offered = page.locator(`[data-agent="${OFFERED.agent_id}"]`);
    await expect(
      offered.locator('[data-level="docket_verified"]'),
    ).toBeVisible();
    await expect(offered.locator('[data-payment-tested="yes"]')).toHaveText(
      "payment tested",
    );

    /* A listing nothing has been observed about carries no level rather than the weakest
       one, which would read as a finding. */
    const unseen = page.locator(`[data-agent="${UNSEEN.agent_id}"]`);
    await expect(unseen.locator('[data-level="no level"]')).toHaveText(
      "no level",
    );
  });

  test("a category says where it came from", async ({ page }) => {
    await page.goto("/search");

    await expect(
      page
        .locator(`[data-agent="${OFFERED.agent_id}"]`)
        .getByText("the owner declared this category"),
    ).toBeVisible();
    await expect(
      page
        .locator(`[data-agent="${TESTED_UNPAID.agent_id}"]`)
        .getByText(
          "Docket's printed rule table read this out of its capability text",
        ),
    ).toBeVisible();
  });

  test("the page says plainly which listings Docket does not offer", async ({
    page,
  }) => {
    await page.goto("/search");
    await expect(
      page.getByText("2 of these are not offered by Docket"),
    ).toBeVisible();
    await expect(
      page.getByText("Being in a registry is not an offer", { exact: false }),
    ).toBeVisible();
    await expect(
      page
        .locator(`[data-agent="${TESTED_UNPAID.agent_id}"]`)
        .getByText("not hireable from this site", { exact: false }),
    ).toBeVisible();
  });

  test("every level Docket attempted is shown, failures included", async ({
    page,
  }) => {
    await page.goto("/search");
    const unpaid = page.locator(`[data-agent="${TESTED_UNPAID.agent_id}"]`);
    await expect(
      unpaid.getByText("live", { exact: false }).first(),
    ).toBeVisible();
    await expect(
      unpaid.locator("li", { hasText: "did not pass" }),
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

  test("one layer failing leaves the other readable rather than blanking the page", async ({
    page,
  }) => {
    await page.route("**/api/agents*", (route) =>
      route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          error_code: "registry_unavailable",
          message: "The registry index did not answer.",
        }),
      }),
    );
    await page.goto("/search");

    await expect(
      page.getByText("The registry listings could not be read", {
        exact: false,
      }),
    ).toBeVisible();
    /* Docket's own services are still there and still activatable. */
    await expect(
      page
        .locator('[data-service="range-doctor"]')
        .getByRole("link", { name: "Activate" }),
    ).toBeVisible();
  });

  test("no match is stated as an answer, not left blank", async ({ page }) => {
    await mockAgents(page, []);
    await page.goto("/search?q=nothing-matches-this");

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

  test("a claim signs the sentence Docket printed, and publishing spends that nonce", async ({
    page,
  }) => {
    const bodies: string[] = [];
    await mockProviders(page, {
      level: "registered",
      evidence: [{ level: "registered", ok: true, at: "2026-09-03T10:00:00Z" }],
    });
    await page.route("**/api/providers/listings", async (route) => {
      bodies.push(route.request().postData() ?? "");
      await route.fallback();
    });
    await page.goto("/providers");

    await page.locator("#provider-agent").fill("311253");
    await page
      .getByRole("button", { name: "Connect wallet and claim" })
      .click();

    await expect(
      page.getByRole("heading", { name: "Ownership proved" }),
    ).toBeVisible();
    expect(await signedMessages(page)).toEqual([
      "Docket provider claim 311253 claim-nonce",
    ]);

    await page.locator("#listing-category").selectOption("rebalancing");
    await page.locator("#listing-capabilities").fill("Rebalances v3 ranges");
    await page.locator("#listing-price").fill("0.50 USDT");
    await page.locator("#listing-payment-method").selectOption("x402");
    await page.getByRole("button", { name: "Publish listing" }).click();

    await expect(
      page.getByRole("heading", { name: "Listing status" }),
    ).toBeVisible();
    expect(bodies).toHaveLength(1);
    const body = JSON.parse(bodies[0]);
    expect(body.agent_id).toBe("311253");
    expect(body.nonce).toBe("claim-nonce");
    expect(body.signature).toMatch(/^0x[0-9a-f]{130}$/);
    /* Capabilities travel as the provider's own text, not chopped into a list. */
    expect(body.capabilities).toBe("Rebalances v3 ranges");
    expect(body.price).toBe("0.50 USDT");
    expect(body.payment_method).toBe("x402");
  });

  test("a fresh listing is not offered, and the page says so rather than implying it is", async ({
    page,
  }) => {
    await mockProviders(page, {
      level: "registered",
      hireable: false,
      evidence: [
        { level: "endpoint_detected", ok: true, at: "2026-09-03T10:00:00Z" },
        { level: "live", ok: false, at: "2026-09-03T10:01:00Z" },
      ],
    });
    await page.goto("/providers?agent=311253");
    await expect(page.locator("#provider-agent")).toHaveValue("311253");

    await page
      .getByRole("button", { name: "Connect wallet and claim" })
      .click();
    await page.locator("#listing-capabilities").fill("Rebalances v3 ranges");
    await page.getByRole("button", { name: "Publish listing" }).click();

    await expect(page.getByText("1 level did not pass")).toBeVisible();
    await expect(page.locator('[data-payment-tested="no"]')).toBeVisible();
    await expect(page.getByText("Offered by Docket", { exact: true })).toBeVisible();
    await expect(
      page.getByText("nothing here is a permanent verdict", { exact: false }),
    ).toBeVisible();
    await expect(
      page.getByText("It becomes hireable only once a verification pass", {
        exact: false,
      }),
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

  test("a refused listing sends the reader back for a fresh claim, not a dead button", async ({
    page,
  }) => {
    await mockProviders(page, {
      listingError: {
        status: 409,
        error_code: "stale_nonce",
        message: "That claim nonce was already spent.",
      },
    });
    await page.goto("/providers");
    await page.locator("#provider-agent").fill("311253");
    await page
      .getByRole("button", { name: "Connect wallet and claim" })
      .click();
    await page.locator("#listing-capabilities").fill("Rebalances v3 ranges");
    await page.getByRole("button", { name: "Publish listing" }).click();

    await expect(
      page.getByRole("heading", { name: "The listing was not published" }),
    ).toBeVisible();
    await expect(page.getByText("stale_nonce")).toBeVisible();
    /* A claim nonce is single use, so the page says the claim has to be made again rather
       than leaving a publish button that can now only fail. */
    await expect(
      page.getByText("claim the identity again before publishing", {
        exact: false,
      }),
    ).toBeVisible();
    await expect(page.locator('.step[data-status="current"]')).toHaveText(
      /identity/,
    );
  });
});
