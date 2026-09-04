import {
  SERVICE,
  expect,
  installNoWallet,
  installWallet,
  mockActivations,
  mockHire,
  mockServices,
  test,
} from "../fixtures";

/* Every way the paid path can fail, and the way out of each. A status code with no next
   step is a dead end, and a dead end on the one page that takes money is the worst place
   in the product to have one. */

test.describe("failure recovery", () => {
  test.beforeEach(async ({ page }) => {
    await installWallet(page);
    await mockServices(page);
    await mockActivations(page);
  });

  test("a replayed authorization explains itself and does not offer a blind retry first", async ({
    page,
  }) => {
    const approves: string[] = [];
    await mockHire(page, { kind: "replay" });
    await page.route("**/api/activations/*/approve", async (route) => {
      approves.push(route.request().postData() ?? "");
      await route.fallback();
    });
    await page.goto("/activate?service=range-doctor");
    await page.getByRole("button", { name: /Activate and pay/ }).click();

    await expect(
      page.getByRole("heading", { name: "Your activation" }),
    ).toBeVisible();
    /* A replay proves the original authorization settled. The browser derives its payment
       id from the exact envelope and binds that settled payment; it never offers a second
       purchase. */
    await expect.poll(() => approves.length).toBe(1);
    const body = JSON.parse(approves[0]);
    expect(body.payment_id).toMatch(/^0x[0-9a-f]{64}$/);
    expect(body.payment_header).toBeUndefined();
    await expect(page.locator('[data-action="resend-payment"]')).toHaveCount(0);
  });

  test("a facilitator rejection says nothing was charged and offers the next step", async ({
    page,
  }) => {
    await mockHire(page, { kind: "facilitator_rejected" });
    await page.goto("/activate?service=range-doctor");
    await page.getByRole("button", { name: /Activate and pay/ }).click();

    await expect(
      page.getByRole("heading", {
        name: "The facilitator rejected the payment",
      }),
    ).toBeVisible();
    await expect(page.getByText("payment_not_verified")).toBeVisible();
    await expect(
      page.getByText(
        "The facilitator rejected the payment. No work ran and no charge was attempted.",
      ),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Check the allowance and sign again" }),
    ).toBeVisible();
  });

  test("a failed execution offers a rerun and says no settlement ran", async ({
    page,
  }) => {
    await mockHire(page, { kind: "service_failed" });
    await page.goto("/activate?service=range-doctor");
    await page.getByRole("button", { name: /Activate and pay/ }).click();

    await expect(
      page.getByRole("heading", {
        name: "The service could not complete the request",
      }),
    ).toBeVisible();
    await expect(page.getByText("service_failed")).toBeVisible();
    await expect(
      page.getByText("No settlement ran, so nothing was charged for it."),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Run it again" }),
    ).toBeVisible();
  });

  test("a dismissed wallet prompt is not reported as an error", async ({
    page,
  }) => {
    await mockHire(page);
    await page.goto("/activate?service=range-doctor");
    await page.evaluate(() => {
      (
        window as unknown as { __wallet: { rejectNext: string } }
      ).__wallet.rejectNext = "eth_signTypedData_v4";
    });
    await page.getByRole("button", { name: /Activate and pay/ }).click();

    await expect(
      page.getByRole("heading", { name: "You dismissed the wallet prompt" }),
    ).toBeVisible();
    await expect(page.getByText("user_rejected")).toBeVisible();
    await expect(
      page.getByText(
        "Nothing was signed, nothing was sent, and nothing was charged.",
      ),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Start the payment again" }),
    ).toBeVisible();
  });

  test("a connection that drops mid-payment refuses to guess whether it settled", async ({
    page,
  }) => {
    await mockHire(page);
    /* Registered after the mock so it runs first: Playwright dispatches route handlers
       last-registered first, and this one has to see the paid request before the mock
       fulfils it. */
    await page.route("**/hire/range-doctor", async (route) => {
      const header = route.request().headers()["x-payment"];
      if (header && header !== "challenge-request")
        return route.abort("connectionreset");
      return route.fallback();
    });
    await page.goto("/activate?service=range-doctor");
    await page.getByRole("button", { name: /Activate and pay/ }).click();

    await expect(
      page.getByRole("heading", { name: "The connection dropped mid-payment" }),
    ).toBeVisible();
    await expect(page.getByText("payment_outcome_unknown")).toBeVisible();
    /* No retry button at all: a second signature here would buy the same work twice. */
    await expect(
      page.locator(".panel-error").getByRole("button", { name: /Sign|again/ }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("link", { name: "Check My agents" }),
    ).toBeVisible();
  });

  test("a service outside paid stock offers the free tier instead of a payment", async ({
    page,
  }) => {
    await mockServices(page, {
      ...SERVICE,
      paid_stock: false,
      stock_status: "candidate",
    });
    await mockHire(page);
    await page.goto("/activate?service=range-doctor");

    await expect(
      page.getByRole("button", { name: /Activate and pay/ }),
    ).toHaveCount(0);
    await expect(
      page.getByText("not admitted to paid stock", { exact: false }),
    ).toBeVisible();
    /* The free sample still works, so the page is not a dead end. */
    await page.getByRole("button", { name: "Try free sample" }).click();
    await expect(
      page.getByRole("heading", { name: "Free sample result" }),
    ).toBeVisible();
  });

  test("with no wallet the page says so and keeps the free sample working", async ({
    page,
  }) => {
    await installNoWallet(page);
    await mockHire(page);
    await page.goto("/activate?service=range-doctor");

    await page.getByRole("button", { name: /Activate and pay/ }).click();
    await expect(
      page.getByRole("heading", { name: "No wallet is available" }),
    ).toBeVisible();
    await expect(page.getByText("no_wallet")).toBeVisible();

    await page
      .getByRole("button", { name: "Try the free sample instead" })
      .click();
    await expect(
      page.getByRole("heading", { name: "Free sample result" }),
    ).toBeVisible();
  });

  test("a missing required field is caught before any wallet prompt opens", async ({
    page,
  }) => {
    await mockHire(page);
    await page.goto("/activate?service=range-doctor");
    await page.locator("#field-wallet").fill("");
    await page.getByRole("button", { name: /Activate and pay/ }).click();

    await expect(page.getByText("missing_field")).toBeVisible();
    await expect(page.getByText("range-doctor needs wallet.")).toBeVisible();
    const calls = await page.evaluate(
      () =>
        (window as unknown as { __wallet: { calls: unknown[] } }).__wallet.calls
          .length,
    );
    expect(calls).toBe(0);
  });
});
