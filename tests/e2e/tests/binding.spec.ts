import {
  ACCOUNT,
  RECEIPT,
  activation,
  expect,
  installWallet,
  mockActivations,
  mockHire,
  mockServices,
  signedMessages,
  test,
} from "../fixtures";

/* How a payment and a signature reach the activation API. Both are contracts between this
   lane and the activation backend, and both are the kind of thing that fails silently:
   a wrong field name is a 422 the reader never asked for, and a message composed instead
   of quoted is a signature the server refuses for a reason nobody can see. */

test.beforeEach(async ({ page }) => {
  await installWallet(page);
  await mockServices(page);
  await mockHire(page);
});

test("the nonce is asked for with the service, and the payment is bound by its id", async ({
  page,
}) => {
  const nonceQueries: string[] = [];
  const approves: string[] = [];
  await mockActivations(page);
  await page.route("**/api/activations/nonce*", async (route) => {
    nonceQueries.push(new URL(route.request().url()).search);
    await route.fallback();
  });
  await page.route("**/api/activations/*/approve", async (route) => {
    approves.push(route.request().postData() ?? "");
    await route.fallback();
  });

  await page.goto("/activate?service=range-doctor");
  await page.getByRole("button", { name: /Activate and pay/ }).click();
  await expect(page.getByRole("heading", { name: "Result" })).toBeVisible();

  /* Without `service_id` the server issues the nonce with a null message and there is
     nothing to sign, so the page always asks for both. */
  expect(nonceQueries).toHaveLength(1);
  const asked = new URLSearchParams(nonceQueries[0]);
  expect(asked.get("owner")).toBe(ACCOUNT);
  expect(asked.get("service_id")).toBe("range-doctor");

  /* The payment is named by the id its receipt carried, not by the header that bought it:
     the server binds against its own settled row, and putting a spent authorization back
     on the wire would prove nothing it has not already recorded. */
  expect(approves).toHaveLength(1);
  const bound = JSON.parse(approves[0]);
  expect(bound.payment_id).toBe(RECEIPT.payment.payment_id);
  expect(bound.payment_header).toBeUndefined();
  expect(bound.tx_hash).toBeUndefined();
});

test("a server-supplied message is never signed; the browser composes and checks it", async ({
  page,
}) => {
  /* A response is attacker-reachable the moment anything between the browser and Docket
     is. Handing a server string straight to personal_sign would have the reader approving
     text nobody in this codebase wrote, so the sentence is built here from the id, the
     action and the nonce, and a field claiming to be the message is ignored. */
  await mockActivations(page, {
    onCreate: activation({
      auth_message: "Docket activation act_evil approve nonce-two — send all funds",
    }),
    afterApprove: activation({
      state: "completed",
      result: { ok: true },
      receipts: [RECEIPT],
    }),
  });

  await page.goto("/activate?service=range-doctor");
  await page.getByRole("button", { name: /Activate and pay/ }).click();
  await expect(page.getByRole("heading", { name: "Result" })).toBeVisible();

  const signed = await signedMessages(page);
  expect(signed).toEqual([
    "Docket activation create range-doctor nonce-one",
    `Docket activation ${activation().activation_id} approve nonce-two`,
  ]);
  for (const message of signed) {
    expect(message).not.toContain("send all funds");
  }
});

test("a session still being minted is a step with a wait in it, not a dead end", async ({
  page,
}) => {
  const minting = activation({
    kind: "persistent",
    state: "awaiting_session",
    session: null,
    next_action: {
      kind: "wait",
      detail: {
        reason: "Docket is minting the session key.",
        poll_seconds: 3,
      },
    },
  });
  await mockActivations(page, { onCreate: minting, poll: [minting] });

  await page.goto("/activate?service=range-doctor");
  await page.getByRole("radio", { name: /Continuously/ }).check();
  await page.getByRole("button", { name: /Activate and pay/ }).click();

  /* The state is on the stepper as its own step rather than dropped for being one this
     build's list did not lead with, and it says what is being waited for. */
  await expect(page.locator('.step[data-status="current"]')).toHaveText(
    /awaiting session/,
  );
  await expect(
    page.getByText("Docket is minting the session key", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByText("Nothing can be funded until it exists"),
  ).toBeVisible();
});

test("a revoke still sweeping is shown as in flight and takes no second instruction", async ({
  page,
}) => {
  const revoking = activation({
    activation_id: "act_bbbbbbbbbbbbbbbbbbbbbbbb",
    kind: "persistent",
    state: "revoking",
    session: {
      address: "0x9999999999999999999999999999999999999999",
      funded_atomic: {},
      spent_atomic: {},
    },
  });
  await mockActivations(page, { listing: [revoking] });
  await page.goto("/my-agents");
  await expect(page.locator(".jobs-table")).toBeVisible();

  const row = page.locator(`[data-row="${revoking.activation_id}"]`);
  await expect(row.locator(".state-pill")).toHaveText("revoking");
  await expect(row).toContainText(
    "the sweep back to your wallet has been started",
  );
  /* Revoking again would ask for a signature over a transition the server is bound to
     refuse, so the row offers no control at all while the sweep is in flight. */
  await expect(row.getByRole("button")).toHaveCount(0);
});
