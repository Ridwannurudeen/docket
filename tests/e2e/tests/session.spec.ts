import {
  PAY_TO,
  RECEIPT,
  RESULT,
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

/* The two paths that are not the one-shot payment: a persistent session the reader funds
   from their own wallet, and an activation the server moves while the page watches it.
   Both are driven by `next_action` and by polling rather than by a button press, so they
   can only be exercised by a server that changes its answer. */

const SESSION = "0x9999999999999999999999999999999999999999";
const FUND_ME = activation({
  kind: "persistent",
  state: "authorized",
  session: { address: SESSION, funded_atomic: {}, spent_atomic: {} },
  next_action: {
    kind: "fund_session",
    detail: {
      address: SESSION,
      required_atomic: { [USDT]: "10000000000000000000" },
      gas_allowance_wei: "5000000000000000",
    },
  },
});

test.beforeEach(async ({ page }) => {
  await installWallet(page);
  await mockServices(page);
  await mockHire(page);
});

test("a continuous session asks to be funded and binds the transaction the reader sends", async ({
  page,
}) => {
  const funded = activation({
    kind: "persistent",
    state: "funded",
    session: {
      address: SESSION,
      funded_atomic: { [USDT]: "10000000000000000000" },
      spent_atomic: {},
    },
    next_action: { kind: "wait", detail: {} },
  });
  const approves: string[] = [];
  await mockActivations(page, {
    onCreate: FUND_ME,
    afterApprove: funded,
    poll: [funded],
  });
  await page.route("**/api/activations/*/approve", async (route) => {
    approves.push(route.request().postData() ?? "");
    await route.fallback();
  });

  await page.goto("/activate?service=range-doctor");
  await page.getByRole("radio", { name: /Continuously/ }).check();
  await page.getByRole("button", { name: /Activate and pay/ }).click();

  /* No payment is signed for a persistent session: it is funded, not bought. */
  await expect(
    page.getByRole("heading", { name: "Fund the session" }),
  ).toBeVisible();
  const fund = page.locator('[data-region="next-action"]');
  await expect(fund.getByText(SESSION)).toBeVisible();
  await expect(fund.getByText("10000000000000000000")).toBeVisible();
  await expect(fund.getByText("5000000000000000", { exact: true })).toBeVisible();
  await expect(
    page.locator('[data-region="progress"] li', {
      hasText: "Send the session its funding to start it.",
    }),
  ).toBeVisible();

  /* A hash that is not 32 bytes is refused here rather than at the server. */
  await page.locator("#fund-hash").fill("0xnope");
  await page.getByRole("button", { name: "Fund session" }).click();
  await expect(page.getByText("invalid_tx_hash")).toBeVisible();
  expect(approves).toHaveLength(0);

  const hash = "0x" + "1".repeat(64);
  await page.locator("#fund-hash").fill(hash);
  await page.getByRole("button", { name: "Fund session" }).click();

  await expect(page.locator('.step[data-status="current"]')).toHaveText(
    /funded/,
  );
  expect(approves).toHaveLength(1);
  const body = JSON.parse(approves[0]);
  expect(body.tx_hash).toBe(hash);
  expect(body.nonce).toBe(FUND_ME.auth_nonce);
  expect(body.owner_signature).toMatch(/^0x[0-9a-f]{130}$/);

  expect(await signedMessages(page)).toEqual([
    "Docket activation create range-doctor nonce-one",
    `Docket activation ${FUND_ME.activation_id} approve ${FUND_ME.auth_nonce}`,
  ]);
});

test("the page follows an activation the server moves, without a reload", async ({
  page,
}) => {
  const queued = activation({ state: "queued" });
  const running = activation({ state: "running" });
  const completed = activation({
    state: "completed",
    result: RESULT,
    receipts: [RECEIPT],
  });
  await mockActivations(page, {
    afterApprove: queued,
    poll: [running, completed],
  });

  await page.goto("/activate?service=range-doctor");
  await page.getByRole("button", { name: /Activate and pay/ }).click();

  await expect(page.locator('.step[data-status="current"]')).toHaveText(
    /queued/,
  );
  /* Polling is three seconds apart, so this waits rather than asserting immediately. */
  await expect(page.locator('.step[data-status="current"]')).toHaveText(
    /running/,
    {
      timeout: 15_000,
    },
  );
  await expect(page.locator('.step[data-status="current"]')).toHaveText(
    /completed/,
    {
      timeout: 15_000,
    },
  );
  await expect(
    page.getByText("Finished, with a result and a receipt."),
  ).toBeVisible();
  /* And the result the poll carried is painted without the reader touching anything. */
  await expect(page.getByRole("heading", { name: "Result" })).toBeVisible();
});

test("an execution that fails after the payment shows where it stopped and why", async ({
  page,
}) => {
  const failed = activation({
    state: "failed",
    events: [
      {
        at: "2026-09-03T10:01:00Z",
        from_state: "running",
        to_state: "failed",
        reason: "the pool read reverted",
        actor: "docket",
      },
    ],
  });
  await mockActivations(page, {
    afterApprove: activation({ state: "running" }),
    poll: [failed],
  });

  await page.goto("/activate?service=range-doctor");
  await page.getByRole("button", { name: /Activate and pay/ }).click();

  /* The failed state is shown where it happened, so the step it stopped on stays visible
     rather than the stepper jumping to its end. */
  await expect(page.locator('.step[data-status="failed"]')).toHaveText(
    /failed/,
    {
      timeout: 15_000,
    },
  );
  await expect(
    page
      .getByText("It stopped without a result. The reason is recorded below.")
      .first(),
  ).toBeVisible();
});

test("a run that needs a signature shows the prepared call before asking for one", async ({
  page,
}) => {
  const needs = activation({
    state: "needs_approval",
    next_action: {
      kind: "sign_transaction",
      detail: { purpose: "Recenter the position around the current tick" },
    },
  });
  await mockActivations(page, { afterApprove: needs, poll: [needs] });
  await page.route("**/api/activations/*/prepared", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        calls: [
          {
            to: "0x46A15B0b27311cedF172AB29E4f4766fbE7F4364",
            data: "0x12345678",
            value_atomic: "0",
            chain_id: 56,
            gas_ceiling: "500000",
            deadline: "2026-09-03T10:10:00Z",
            purpose: "Recenter the position",
            simulation: {
              ok: true,
              gas_estimate: "412903",
              revert_reason: null,
              observed_at: "2026-09-03T10:00:00Z",
              block: 45000000,
            },
          },
        ],
      }),
    }),
  );

  await page.goto("/activate?service=range-doctor");
  await page.getByRole("button", { name: /Activate and pay/ }).click();
  await expect(
    page.getByRole("heading", { name: "This run needs your signature" }),
  ).toBeVisible();
  await expect(
    page.getByText("Recenter the position around the current tick"),
  ).toBeVisible();

  /* The wallet dismisses the send, which stops the flow with the review panel still on
     screen. That is the state the assertion is about: what a reader is shown before they
     decide, rather than what is left behind once the decision is made. */
  await page.evaluate(() => {
    (
      window as unknown as { __wallet: { rejectNext: string } }
    ).__wallet.rejectNext = "eth_sendTransaction";
  });
  await page.getByRole("button", { name: "Review and sign" }).click();

  /* The call, its gas ceiling and its simulation are on screen before the wallet opens. */
  await expect(
    page.getByText("0x46A15B0b27311cedF172AB29E4f4766fbE7F4364"),
  ).toBeVisible();
  await expect(page.getByText("412903")).toBeVisible();
  await expect(page.getByText("45000000")).toBeVisible();

  await expect(page.getByText("user_rejected")).toBeVisible();

  /* The transaction the page offered is the one the server prepared, byte for byte: the
     browser never rewrites calldata it did not build. */
  const sent = await page.evaluate(() =>
    (
      window as unknown as {
        __wallet: { calls: Array<{ method: string; params: unknown }> };
      }
    ).__wallet.calls
      .filter((call) => call.method === "eth_sendTransaction")
      .map((call) => (call.params as Array<{ to: string; data: string }>)[0]),
  );
  expect(sent.at(-1)).toMatchObject({
    to: "0x46A15B0b27311cedF172AB29E4f4766fbE7F4364",
    data: "0x12345678",
  });
});

test("signing a prepared call binds it to the activation with the owner's signature", async ({
  page,
}) => {
  const needs = activation({
    state: "needs_approval",
    next_action: { kind: "sign_transaction", detail: { purpose: "Recenter" } },
  });
  const approves: string[] = [];
  await mockActivations(page, {
    afterApprove: needs,
    poll: [activation({ state: "running" })],
  });
  await page.route("**/api/activations/*/prepared", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        calls: [
          {
            to: "0x46A15B0b27311cedF172AB29E4f4766fbE7F4364",
            data: "0x12345678",
            value_atomic: "0",
            chain_id: 56,
            gas_ceiling: "500000",
            deadline: "2026-09-03T10:10:00Z",
            purpose: "Recenter",
            simulation: {
              ok: true,
              gas_estimate: "412903",
              revert_reason: null,
              observed_at: "2026-09-03T10:00:00Z",
              block: 45000000,
            },
          },
        ],
      }),
    }),
  );
  /* The approve that binds the payment comes first; the one this test is about is the
     second, and it carries the transaction hash rather than a payment header. */
  await page.route("**/api/activations/*/approve", async (route) => {
    approves.push(route.request().postData() ?? "");
    await route.fallback();
  });

  await page.goto("/activate?service=range-doctor");
  await page.getByRole("button", { name: /Activate and pay/ }).click();
  await page.getByRole("button", { name: "Review and sign" }).click();

  await expect(page.locator('.step[data-status="current"]')).toHaveText(
    /running/,
    { timeout: 15_000 },
  );
  expect(approves).toHaveLength(2);
  const bound = JSON.parse(approves[1]);
  expect(bound.tx_hash).toMatch(/^0x[0-9a-f]{64}$/);
  expect(bound.payment_header).toBeUndefined();
  expect(bound.nonce).toBe(needs.auth_nonce);
  expect(bound.owner_signature).toMatch(/^0x[0-9a-f]{130}$/);
});

test("a prepared call that reverted in simulation is shown, not offered for signing", async ({
  page,
}) => {
  const needs = activation({
    state: "needs_approval",
    next_action: { kind: "sign_transaction", detail: { purpose: "Recenter" } },
  });
  await mockActivations(page, { afterApprove: needs, poll: [needs] });
  await page.route("**/api/activations/*/prepared", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        calls: [
          {
            to: PAY_TO,
            data: "0xdeadbeef",
            value_atomic: "0",
            chain_id: 56,
            gas_ceiling: "500000",
            deadline: "2026-09-03T10:10:00Z",
            purpose: "Recenter",
            simulation: {
              ok: false,
              gas_estimate: null,
              revert_reason: "STF",
              observed_at: "2026-09-03T10:00:00Z",
              block: 45000000,
            },
          },
        ],
      }),
    }),
  );

  await page.goto("/activate?service=range-doctor");
  await page.getByRole("button", { name: /Activate and pay/ }).click();
  await page.getByRole("button", { name: "Review and sign" }).click();

  await expect(page.getByText("simulation_failed")).toBeVisible();
  await expect(page.getByText("STF", { exact: false }).first()).toBeVisible();
  const sent = await page.evaluate(
    () =>
      (
        window as unknown as {
          __wallet: { calls: Array<{ method: string }> };
        }
      ).__wallet.calls.filter((call) => call.method === "eth_sendTransaction")
        .length,
  );
  /* One approve for the payment leg, and nothing for the reverting call. */
  expect(sent).toBe(0);
});
