import {
  ACCOUNT,
  RECEIPT,
  activation,
  expect,
  installNoWallet,
  installWallet,
  mockActivations,
  signedMessages,
  test,
} from "../fixtures";

const PERSISTENT = activation({
  activation_id: "act_aaaaaaaaaaaaaaaaaaaaaaaa",
  kind: "persistent",
  state: "active",
  policy: {
    contract_allowlist: ["0x46A15B0b27311cedF172AB29E4f4766fbE7F4364"],
    token_allowlist: ["0x55d398326f99059fF775485246999027B3197955"],
    total_cap_atomic: {
      "0x55d398326f99059fF775485246999027B3197955": "10000000000000000000",
    },
    per_action_limit_atomic: {
      "0x55d398326f99059fF775485246999027B3197955": "1000000000000000000",
    },
    max_slippage_bps: 50,
    max_gas_price_wei: "5000000000",
    expires_at: "2026-10-03T00:00:00Z",
    emergency_pause: false,
  },
  session: {
    address: "0x9999999999999999999999999999999999999999",
    funded_atomic: {
      "0x55d398326f99059fF775485246999027B3197955": "10000000000000000000",
    },
    spent_atomic: {
      "0x55d398326f99059fF775485246999027B3197955": "2500000000000000000",
    },
  },
  receipts: [RECEIPT],
});

test("with no wallet the page says why it has nothing to show", async ({
  page,
}) => {
  await installNoWallet(page);
  await mockActivations(page);
  await page.goto("/my-agents");

  await expect(
    page.getByRole("heading", { name: "No wallet in this browser" }),
  ).toBeVisible();
  await expect(
    page.getByText("Docket holds no key of yours", { exact: false }),
  ).toBeVisible();
});

test("an address that owns nothing gets copy, not an empty table", async ({
  page,
}) => {
  await installWallet(page);
  await mockActivations(page, { listing: [] });
  await page.goto("/my-agents");

  await expect(
    page.getByRole("heading", {
      name: "Nothing activated from this address yet",
    }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Find an agent" })).toBeVisible();
  await expect(page.locator("table")).toHaveCount(0);
});

test("a state change is not presented as a run without a receipt", async ({
  page,
}) => {
  const receiptless = activation({
    state: "authorized",
    receipts: [],
    updated_at: "2000-01-01T00:00:00Z",
  });
  await installWallet(page);
  await mockActivations(page, { listing: [receiptless] });
  await page.goto("/my-agents");

  const row = page.locator(`[data-row="${receiptless.activation_id}"]`);
  await expect(row.locator("td").nth(2)).toHaveText("never");
});

test.describe("with one persistent session", () => {
  test.beforeEach(async ({ page }) => {
    await installWallet(page);
    await mockActivations(page, { listing: [PERSISTENT] });
    await page.goto("/my-agents");
    await expect(page.locator(".jobs-table")).toBeVisible();
  });

  test("the row states the state, the spend and the permission scope", async ({
    page,
  }) => {
    const row = page.locator(`[data-row="${PERSISTENT.activation_id}"]`);
    await expect(row.locator(".state-pill")).toHaveText("active");
    await expect(row).toContainText("2500000000000000000");
    await expect(row).toContainText("slippage 50 bps");
    await expect(row).toContainText("1 contract");
    await expect(row).toContainText("expires 2026-10-03T00:00:00Z");
    await expect(
      page.getByText(ACCOUNT, { exact: false }).first(),
    ).toBeVisible();
  });

  test("pausing signs the exact message the activation's nonce belongs to", async ({
    page,
  }) => {
    await page.getByRole("button", { name: "Pause" }).click();
    await expect(page.locator(".state-pill")).toHaveText("paused");

    expect(await signedMessages(page)).toEqual([
      `Docket activation ${PERSISTENT.activation_id} pause ${PERSISTENT.auth_nonce}`,
    ]);
  });

  test("revoking signs too, and a dismissed prompt changes nothing", async ({
    page,
  }) => {
    await page.evaluate(() => {
      (
        window as unknown as { __wallet: { rejectNext: string } }
      ).__wallet.rejectNext = "personal_sign";
    });
    await page.getByRole("button", { name: "Revoke" }).click();

    await expect(
      page.getByRole("heading", { name: "revoke did not go through" }),
    ).toBeVisible();
    await expect(page.getByText("user_rejected")).toBeVisible();
    await expect(page.locator(".state-pill")).toHaveText("active");

    await page.getByRole("button", { name: "Revoke" }).click();
    await expect(page.locator(".state-pill")).toHaveText("revoked");
    /* Two prompts, one message: the dismissed attempt asked for exactly what the
       accepted one did, and nothing else was ever put in front of the wallet. */
    const message = `Docket activation ${PERSISTENT.activation_id} revoke ${PERSISTENT.auth_nonce}`;
    expect(await signedMessages(page)).toEqual([message, message]);
  });

  test("no control posts without a signature", async ({ page }) => {
    const bodies: string[] = [];
    await page.route("**/api/activations/*/pause", async (route) => {
      bodies.push(route.request().postData() ?? "");
      await route.fallback();
    });
    await page.getByRole("button", { name: "Pause" }).click();
    await expect(page.locator(".state-pill")).toHaveText("paused");

    expect(bodies).toHaveLength(1);
    const body = JSON.parse(bodies[0]);
    expect(body.nonce).toBe(PERSISTENT.auth_nonce);
    expect(body.owner_signature).toMatch(/^0x[0-9a-f]{130}$/);
  });

  test("the receipt exports as JSON with a copy button and a download", async ({
    page,
  }) => {
    await page.getByRole("button", { name: "Export receipt" }).click();

    const block = page.locator("[data-receipt]");
    await expect(block.locator("pre")).toContainText("output_hash");
    await expect(
      block.getByRole("button", { name: "Copy receipt JSON" }),
    ).toBeVisible();
    const download = block.getByRole("link", { name: "Download receipt" });
    await expect(download).toHaveAttribute("download", /docket-receipt/);
    await expect(download).toHaveAttribute("href", /^blob:/);
  });
});
