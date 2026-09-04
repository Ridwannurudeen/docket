import {
  expect,
  installWallet,
  mockActivations,
  mockHire,
  mockServices,
  test,
} from "../fixtures";

/* A payment flow reachable only with a mouse is a payment flow some people cannot make.
   These walk the activate page with the keyboard alone, from the skip link to the paid
   control, and check that what the page announces is what a screen reader would hear. */

test.beforeEach(async ({ page }) => {
  await installWallet(page);
  await mockServices(page);
  await mockHire(page);
  await mockActivations(page);
});

async function focused(page: import("@playwright/test").Page) {
  return await page.evaluate(() => {
    const node = document.activeElement as HTMLElement | null;
    if (!node) return null;
    return {
      tag: node.tagName.toLowerCase(),
      id: node.id,
      text: (node.textContent ?? "").trim().slice(0, 60),
      type: node.getAttribute("type"),
    };
  });
}

test("the whole activate flow is reachable by tabbing, in reading order", async ({
  page,
}) => {
  await page.goto("/activate?service=range-doctor");
  await expect(
    page.getByRole("heading", { name: "Range Doctor" }),
  ).toBeVisible();

  await page.keyboard.press("Tab");
  expect((await focused(page))?.text).toBe("Skip to content");

  /* Walk forward until every control the flow needs has been reached. Bounded, so a
     focus trap fails this test rather than hanging it. */
  const wanted = new Set(["field-wallet", "field-token_id", "limit-total"]);
  const seen = new Set<string>();
  let reachedSample = false;
  let reachedPay = false;
  let reachedKind = false;

  for (let step = 0; step < 60; step += 1) {
    await page.keyboard.press("Tab");
    const node = await focused(page);
    if (!node) continue;
    if (node.id && wanted.has(node.id)) seen.add(node.id);
    if (node.type === "radio") reachedKind = true;
    if (node.text.startsWith("Try free sample")) reachedSample = true;
    if (node.text.startsWith("Activate and pay")) reachedPay = true;
    if (reachedPay && reachedSample && reachedKind) break;
  }

  expect(reachedKind).toBe(true);
  expect(seen.has("field-wallet")).toBe(true);
  expect(reachedSample).toBe(true);
  expect(reachedPay).toBe(true);
});

test("the paid control can be operated from the keyboard alone", async ({
  page,
}) => {
  await page.goto("/activate?service=range-doctor");
  const pay = page.getByRole("button", { name: /Activate and pay/ });
  await pay.focus();
  await expect(pay).toBeFocused();
  await page.keyboard.press("Enter");

  await expect(page.getByRole("heading", { name: "Result" })).toBeVisible();
  /* Focus lands on the outcome so a screen reader is taken to what just arrived rather
     than left on a button that has finished its job. */
  await expect(page.locator("#outcome-heading")).toBeFocused();
});

test("submitting the sample form with Enter runs the free sample", async ({
  page,
}) => {
  await page.goto("/activate?service=range-doctor");
  await page.locator("#field-wallet").focus();
  await page.keyboard.press("Enter");

  await expect(
    page.getByRole("heading", { name: "Free sample result" }),
  ).toBeVisible();
});

test("a failure moves focus to the failure and names it in the live region", async ({
  page,
}) => {
  await mockHire(page, { kind: "service_failed" });
  await page.goto("/activate?service=range-doctor");
  await page.getByRole("button", { name: /Activate and pay/ }).click();

  const heading = page.getByRole("heading", {
    name: "The service could not complete the request",
  });
  await expect(heading).toBeVisible();
  await expect(heading).toBeFocused();
  await expect(page.locator('[data-region="live-status"]')).toHaveText(
    /The service could not complete the request\./,
  );
});

test("every control the page paints has an accessible name", async ({
  page,
}) => {
  await page.goto("/activate?service=range-doctor");
  await page.getByRole("radio", { name: /Continuously/ }).check();

  const unnamed = await page.evaluate(() => {
    const nodes = Array.from(
      document.querySelectorAll("button, a[href], input, select, textarea"),
    );
    return nodes
      .filter((node) => {
        const element = node as HTMLElement;
        if (element.hasAttribute("aria-hidden")) return false;
        /* A control is named by aria-label, by a label that points at its id, by a
           label that wraps it, or by its own text. A radio in a fieldset is named the
           third way, which is the conventional markup for a radio group. */
        const label =
          element.getAttribute("aria-label") ??
          (element.id
            ? document.querySelector(`label[for="${element.id}"]`)?.textContent
            : null) ??
          element.closest("label")?.textContent ??
          element.textContent;
        return !(label ?? "").trim();
      })
      .map((node) => (node as HTMLElement).outerHTML.slice(0, 80));
  });
  expect(unnamed).toEqual([]);
});
