import {
  POLICY_DEFAULTS,
  SERVICE,
  USDT,
  activation,
  expect,
  installWallet,
  mockActivations,
  mockHire,
  mockServices,
  test,
} from "../fixtures";

/* The guards between a reader and a signature they did not mean to give. Each one exists
   because the alternative is a wallet prompt over something other than what the page said,
   and by then the reader's only defence is reading hex in a dialog. */

test.beforeEach(async ({ page }) => {
  await installWallet(page);
  await mockServices(page);
  await mockHire(page);
});

test("a persistent session shows the allowlists it would run inside, unedited", async ({
  page,
}) => {
  const bodies: string[] = [];
  await mockActivations(page, {
    onCreate: activation({
      kind: "persistent",
      state: "awaiting_session",
      session: null,
      next_action: {
        kind: "wait",
        detail: { reason: "Docket is minting the session key.", poll_seconds: 3 },
      },
    }),
  });
  await page.route("**/api/activations", async (route) => {
    if (route.request().method() === "POST") {
      bodies.push(route.request().postData() ?? "");
    }
    await route.fallback();
  });

  await page.goto("/activate?service=range-doctor");
  await page.getByRole("radio", { name: /Continuously/ }).check();

  /* The lists come from the server and are shown, not typed. A reader agreeing to a
     "bounded" session should be able to see what the bound is. */
  await expect(page.getByText("What this session may touch")).toBeVisible();
  await expect(
    page.getByText(POLICY_DEFAULTS.policy.contract_allowlist[0]),
  ).toBeVisible();
  await expect(page.getByText("0x88316456", { exact: false })).toBeVisible();
  /* And they are not editable here: only the caps are the reader's. */
  await expect(page.locator('input[name="contract_allowlist"]')).toHaveCount(0);

  /* The caps arrive prefilled from what the server proposed. */
  await expect(page.locator("#limit-total")).toHaveValue("10");
  await expect(page.locator("#limit-action")).toHaveValue("1");
  await expect(page.locator("#limit-slippage")).toHaveValue("50");

  await page.locator("#limit-total").fill("25");
  await page.getByRole("button", { name: /Activate and pay/ }).click();
  await expect(page.locator('.step[data-status="current"]')).toHaveText(
    /awaiting session/,
  );

  expect(bodies).toHaveLength(1);
  const policy = JSON.parse(bodies[0]).policy;
  /* The allowlists travel back exactly as they arrived — a browser that sent an empty one
     would be asking for a session permitted to call nothing. */
  expect(policy.contract_allowlist).toEqual(
    POLICY_DEFAULTS.policy.contract_allowlist,
  );
  expect(policy.function_allowlist).toEqual(
    POLICY_DEFAULTS.policy.function_allowlist,
  );
  expect(policy.token_allowlist).toEqual(
    POLICY_DEFAULTS.policy.token_allowlist,
  );
  /* Only the cap the reader changed is theirs. */
  expect(policy.total_cap_atomic[USDT]).toBe("25000000000000000000");
  expect(policy.max_slippage_bps).toBe(50);
  expect(policy.expires_at).toMatch(/^\d{4}-\d{2}-\d{2}T/);
});

test("with no allowlists to show there is nothing to agree to, and nothing is created", async ({
  page,
}) => {
  const creates: string[] = [];
  await mockActivations(page, { policyDefaults: null });
  await page.route("**/api/activations", async (route) => {
    if (route.request().method() === "POST") creates.push("created");
    await route.fallback();
  });

  await page.goto("/activate?service=range-doctor");
  await page.getByRole("radio", { name: /Continuously/ }).check();

  await expect(
    page.getByRole("heading", {
      name: "The limits for this session could not be read",
    }),
  ).toBeVisible();
  await expect(page.getByText("Nothing was created.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  expect(creates).toHaveLength(0);
});

test("a challenge that asks a different price than the page quoted is refused", async ({
  page,
}) => {
  await mockActivations(page);
  await page.route("**/hire/range-doctor", async (route) => {
    const header = route.request().headers()["x-payment"];
    if (header !== "challenge-request") return route.fallback();
    return route.fulfill({
      status: 402,
      contentType: "application/json",
      headers: { date: new Date().toUTCString() },
      body: JSON.stringify({
        x402Version: 2,
        resource: {
          url: "http://x/hire/range-doctor",
          mimeType: "application/json",
        },
        accepts: [
          {
            scheme: "exact",
            network: "eip155:56",
            /* Ten times what the page printed. */
            amount: "5000000000000000000",
            asset: USDT,
            payTo: "0xe55816904796341bf8535e25f6c8b647927fc946",
            maxTimeoutSeconds: 300,
            extra: {
              name: "B402",
              version: "1",
              chainId: 56,
              verifyingContract: "0xE1Af7DaEa624bA3B5073f24A6Ea5531434D82d88",
              relayerContract: "0xE1Af7DaEa624bA3B5073f24A6Ea5531434D82d88",
            },
          },
        ],
        error: { code: "payment_invalid", message: "no payload" },
      }),
    });
  });

  await page.goto("/activate?service=range-doctor");
  await page.getByRole("button", { name: /Activate and pay/ }).click();

  await expect(page.getByText("quote_changed")).toBeVisible();
  await expect(
    page.getByText("Nothing was signed.", { exact: false }),
  ).toBeVisible();
  /* And the wallet was never asked to sign the substituted terms. */
  const signed = await page.evaluate(
    () =>
      (
        window as unknown as { __wallet: { calls: Array<{ method: string }> } }
      ).__wallet.calls.filter((call) => call.method === "eth_signTypedData_v4")
        .length,
  );
  expect(signed).toBe(0);
});

test("an approval that is mined without raising the allowance stops the flow", async ({
  page,
}) => {
  await mockActivations(page);
  await page.goto("/activate?service=range-doctor");
  /* A token whose approve mines and changes nothing: the receipt says success and the
     allowance is still short. Trusting the receipt would sign an authorization the
     relayer cannot pull. */
  await page.evaluate(() => {
    const control = (
      window as unknown as { __wallet: { allowance: string; frozen?: boolean } }
    ).__wallet;
    control.allowance = "0".repeat(64);
    Object.defineProperty(control, "allowance", {
      get: () => "0".repeat(64),
      set: () => {},
    });
  });

  await page.getByRole("button", { name: /Activate and pay/ }).click();

  await expect(page.getByText("allowance_not_applied")).toBeVisible();
  await expect(
    page.getByText("Nothing was signed.", { exact: false }),
  ).toBeVisible();
});

test("an activation's events are shown, and a note is not drawn as a transition", async ({
  page,
}) => {
  const withEvents = activation({
    state: "failed",
    events: [
      {
        at: "2026-09-03T10:00:00Z",
        from_state: "queued",
        to_state: "running",
        reason: "a runner picked it up",
        actor: "docket",
      },
      {
        at: "2026-09-03T10:00:30Z",
        from_state: "running",
        to_state: "running",
        reason: "the pool read was retried once",
        actor: "docket",
      },
      {
        at: "2026-09-03T10:01:00Z",
        from_state: "running",
        to_state: "failed",
        reason: "the pool read reverted",
        actor: "chain",
      },
    ],
  });
  await mockActivations(page, { afterApprove: withEvents, poll: [withEvents] });

  await page.goto("/activate?service=range-doctor");
  await page.getByRole("button", { name: /Activate and pay/ }).click();
  await expect(
    page.getByRole("heading", { name: "What happened" }),
  ).toBeVisible();

  /* The failure copy says the reason is recorded below. This is below. */
  await expect(page.getByText("the pool read reverted")).toBeVisible();
  const events = page.locator('[data-region="events"] li');
  await expect(events).toHaveCount(3);
  /* An event that moved nothing is a note, not an arrow. */
  await expect(
    events.filter({ hasText: "the pool read was retried once" }),
  ).toHaveAttribute("data-event", "note");
  await expect(
    events.filter({ hasText: "the pool read reverted" }),
  ).toHaveAttribute("data-event", "transition");
});

test("the failure that is the whole page carries the page's h1", async ({
  page,
}) => {
  await page.goto("/activate");
  await expect(
    page.getByRole("heading", { level: 1, name: "Nothing to activate" }),
  ).toBeVisible();
});

test("switching accounts mid-flow is said, and stops the next signature", async ({
  page,
}) => {
  await mockActivations(page, {
    afterApprove: activation({ state: "needs_approval" }),
  });
  await page.goto("/activate?service=range-doctor");
  await page.getByRole("button", { name: /Activate and pay/ }).click();
  await expect(page.getByRole("heading", { name: "Result" })).toBeVisible();

  await page.evaluate(() => {
    const provider = window.ethereum as unknown as {
      emit: (event: string, value: unknown) => void;
    };
    (window as unknown as { __wallet: { account: string } }).__wallet.account =
      "0x2222222222222222222222222222222222222222";
    provider.emit("accountsChanged", [
      "0x2222222222222222222222222222222222222222",
    ]);
  });

  const notice = page.locator('[data-region="account"]');
  await expect(notice).toBeVisible();
  await expect(notice).toContainText("switched accounts");
  await expect(notice).toContainText(
    "0x2222222222222222222222222222222222222222",
  );
});

test("the free sample is unaffected by any of this", async ({ page }) => {
  await mockActivations(page);
  await page.goto(`/activate?service=${SERVICE.service_id}&demo=1`);
  await expect(
    page.getByRole("heading", { name: "Free sample result" }),
  ).toBeVisible();
});
