import type { Page, TestInfo } from "@playwright/test";
import {
  POLICY_SKELETON,
  RECEIPT,
  USDT,
  activation,
  expect,
  installNoWallet,
  installWallet,
  mockActivations,
  mockAgents,
  mockHire,
  mockServices,
  signedMessages,
  test,
} from "../fixtures";

const OBSERVED_FIXTURE = {
  agent_id: "56:0x8004A169FB4a3325136EB29fA0ceB6D2e539a432:409",
  name: "Registry observation fixture",
  category: "rebalancing",
  capability_source: "provider_declared",
  capabilities: "Reads liquidity positions; this is a browser-test fixture.",
  endpoints: [{ kind: "a2a", url: "https://example.invalid/a2a" }],
  verification: {
    level: "docket_tested",
    payment_tested: false,
    payment_tested_evidence: null,
    evidence: [{ level: "live", ok: true, at: "2026-09-03T09:00:00Z" }],
    verified_at: "2026-09-03T10:00:00Z",
  },
  hireable: false,
};

const SESSION_FIXTURE = activation({
  kind: "persistent",
  state: "active",
  policy: { ...POLICY_SKELETON, expires_at: "2026-10-03T00:00:00Z" },
  session: {
    address: "0x9999999999999999999999999999999999999999",
    funded_atomic: { [USDT]: "10000000000000000000" },
    spent_atomic: { [USDT]: "2500000000000000000" },
  },
  receipts: [RECEIPT],
});

async function checkLayout(page: Page, info: TestInfo, name: string) {
  await expect(page.locator("body")).toHaveClass(/workspace-page/);
  const layout = await page.evaluate(() => {
    const controls = Array.from(
      document.querySelectorAll<HTMLElement>(
        ".site-nav a, .btn, input:not([type=radio]):not([type=hidden]), select",
      ),
    ).filter((node) => node.getClientRects().length > 0);
    return {
      reduced: matchMedia("(prefers-reduced-motion: reduce)").matches,
      scroll: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
      shortControls: controls
        .filter((node) => node.getBoundingClientRect().height < 44)
        .map((node) => node.outerHTML.slice(0, 160)),
      motion: controls
        .filter((node) => {
          const style = getComputedStyle(node);
          return [style.animationDuration, style.transitionDuration].some(
            (value) =>
              value.split(",").some((duration) => parseFloat(duration) !== 0),
          );
        })
        .map((node) => ({
          node: node.outerHTML.slice(0, 160),
          animation: getComputedStyle(node).animationDuration,
          transition: getComputedStyle(node).transitionDuration,
        })),
    };
  });
  expect(layout.reduced).toBe(true);
  expect(layout.scroll).toBeLessThanOrEqual(layout.client);
  expect(layout.shortControls).toEqual([]);
  expect(layout.motion).toEqual([]);
  await page.screenshot({
    path: info.outputPath(`${name}-viewport-fixture.png`),
  });
  await page.screenshot({
    path: info.outputPath(`${name}-fixture.png`),
    fullPage: true,
  });
}

for (const viewport of [
  { width: 375, height: 667 },
  { width: 412, height: 915 },
  { width: 1024, height: 768 },
  { width: 1440, height: 1000 },
]) {
  test.describe(`workspace ${viewport.width}x${viewport.height}`, () => {
    test.use({ viewport });

    test.beforeEach(async ({ page }) => {
      expect(page.viewportSize()).toEqual(viewport);
      await page.emulateMedia({ reducedMotion: "reduce" });
    });

    test("search keeps its evidence layers and keyboard filters", async ({
      page,
    }, info) => {
      await mockServices(page);
      await mockAgents(page, [OBSERVED_FIXTURE]);
      await page.goto("/search");
      await expect(page.locator(".result-row").first()).toBeVisible();
      await expect(page.locator('[data-payment-tested="no"]')).toHaveText(
        "payment untested",
      );
      await checkLayout(page, info, "search-populated");

      const query = page.locator("#search-q");
      await query.focus();
      await page.keyboard.type("range");
      await page.keyboard.press("Tab");
      await expect(page.locator("#search-category")).toBeFocused();
      await page.keyboard.press("ArrowDown");
      await page.keyboard.press("Tab");
      await expect(page.locator("#search-level")).toBeFocused();
      await page.keyboard.press("ArrowDown");
      await page.keyboard.press("Tab");
      await expect(
        page.getByRole("button", { name: "Search", exact: true }),
      ).toBeFocused();
      await page.keyboard.press("Enter");
      await expect(page).toHaveURL(
        /q=range&category=rebalancing&level=registered/,
      );
      await expect(page.locator('[data-region="live-status"]')).toHaveText(
        "Search finished.",
      );
    });

    test("empty search is a readable result", async ({ page }, info) => {
      await mockServices(page);
      await mockAgents(page, []);
      await page.goto("/search?q=no-fixture-can-match-this");
      await expect(
        page.getByRole("heading", { name: "No agent matched" }),
      ).toBeVisible();
      await checkLayout(page, info, "search-empty");
    });

    test("activation form and mocked settled receipt remain usable", async ({
      page,
    }, info) => {
      await installWallet(page);
      await mockServices(page);
      await mockHire(page);
      await mockActivations(page);
      await page.goto("/activate?service=range-doctor");
      await expect(
        page.getByRole("heading", { name: "Range Doctor" }),
      ).toBeVisible();
      if (viewport.width >= 1100) {
        const walletField = await page.locator("#field-wallet").boundingBox();
        expect(walletField).not.toBeNull();
        expect(walletField!.y).toBeLessThan(600);
        expect(walletField!.y + walletField!.height).toBeLessThan(
          viewport.height,
        );
      }
      await checkLayout(page, info, "activation-form");
      await page.getByRole("button", { name: /Activate and pay/ }).focus();
      await page.keyboard.press("Enter");
      await expect(page.getByRole("heading", { name: "Result" })).toBeVisible();
      await expect(page.locator("#outcome-heading")).toBeFocused();
      await expect(page.locator("[data-receipt-json]")).toContainText(
        "output_hash",
      );
      await checkLayout(page, info, "activation-mocked-result");
    });

    test("session fixture and expanded receipt fit without hiding controls", async ({
      page,
    }, info) => {
      await installWallet(page);
      await mockActivations(page, { listing: [SESSION_FIXTURE] });
      await page.goto("/my-agents");
      await expect(page.locator(".jobs-table")).toBeVisible();
      await expect(page.getByRole("columnheader")).toHaveCount(7);
      await expect(page.locator("[data-detail]")).toBeHidden();
      if (viewport.width >= 1024) {
        const amountLines = await page
          .locator("[data-row] td")
          .nth(4)
          .evaluate((cell) => {
            const text = cell.firstChild!;
            const range = document.createRange();
            range.setStart(text, 0);
            range.setEnd(text, "2500000000000000000".length);
            return range.getClientRects().length;
          });
        expect(amountLines).toBe(1);
      }
      await expect(
        page.getByRole("button", { name: "Pause", exact: true }),
      ).toBeVisible();
      await expect(
        page.getByRole("button", { name: "Revoke", exact: true }),
      ).toBeVisible();
      await checkLayout(page, info, "my-agents-populated");
      await page.getByRole("button", { name: "Export receipt" }).focus();
      await page.keyboard.press("Enter");
      await expect(page.locator("[data-receipt] pre")).toContainText(
        "output_hash",
      );
      await checkLayout(page, info, "my-agents-receipt");
      expect(await signedMessages(page)).toEqual([]);
    });

    test("connected wallet with no activations stays explicit", async ({
      page,
    }, info) => {
      await installWallet(page);
      await mockActivations(page, { listing: [] });
      await page.goto("/my-agents");
      await expect(
        page.getByRole("heading", {
          name: "Nothing activated from this address yet",
        }),
      ).toBeVisible();
      await checkLayout(page, info, "my-agents-empty");
      expect(await signedMessages(page)).toEqual([]);
    });

    test("disconnected wallet gets a deliberate connection control", async ({
      page,
    }, info) => {
      await installWallet(page, { account: "" });
      await mockActivations(page);
      await page.goto("/my-agents");
      await expect(
        page.getByRole("heading", {
          name: "Connect the wallet that owns your activations",
        }),
      ).toBeVisible();
      await expect(
        page.getByRole("button", { name: "Connect wallet", exact: true }),
      ).toBeVisible();
      await checkLayout(page, info, "my-agents-disconnected");
      expect(await signedMessages(page)).toEqual([]);
    });

    test("missing wallet is explained without a broken form", async ({
      page,
    }, info) => {
      await installNoWallet(page);
      await mockActivations(page);
      await page.goto("/my-agents");
      await expect(
        page.getByRole("heading", { name: "No wallet in this browser" }),
      ).toBeVisible();
      await checkLayout(page, info, "my-agents-no-wallet");
    });
  });
}
