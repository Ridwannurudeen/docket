import { expect, test } from "@playwright/test";

test.use({ javaScriptEnabled: false });

test("the directory and its terms are available without JavaScript", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Find BSC agents.Check the evidence.",
  );
  const cards = page.locator(".listing-card");
  await expect(cards).toHaveCount(6);
  for (const card of await cards.all()) {
    await expect(card.locator(".listing-evidence")).not.toHaveAttribute("open");
    await expect(card.locator(".listing-overview dt")).toHaveText([
      "Price",
      "Required permissions",
    ]);
    for (const value of await card.locator(".listing-overview dd").all()) {
      await expect(value).toBeVisible();
      await expect(value).not.toBeEmpty();
    }
  }
  await expect(page.locator(".preview-agent")).toHaveCount(4);
  for (const service of [
    "range-doctor",
    "grid-operator",
    "yield-router",
    "health-guard",
  ]) {
    await expect(
      page.locator(`.preview-agent[href="/service?id=${service}"]`),
    ).toBeVisible();
  }
});

for (const viewport of [
  { width: 1440, height: 1000 },
  { width: 375, height: 667 },
  { width: 412, height: 915 },
]) {
  test.describe(`${viewport.width}px homepage`, () => {
    test.use({ viewport });

    test("evidence opens and closes by keyboard without overflowing", async ({
      page,
    }) => {
      await page.goto("/");
      for (const control of await page
        .locator(".hero-actions a, .goal-card, .listing-evidence summary")
        .all()) {
        const box = await control.boundingBox();
        expect(box).not.toBeNull();
        expect(box!.height).toBeGreaterThanOrEqual(44);
        expect(box!.width).toBeGreaterThanOrEqual(44);
      }
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
      ).toBeLessThanOrEqual(viewport.width);

      for (const card of await page.locator(".listing-card").all()) {
        const details = card.locator(".listing-evidence");
        const summary = details.locator("summary");
        await summary.focus();
        await expect(summary).toBeFocused();
        await page.keyboard.press("Enter");
        await expect(details).toHaveAttribute("open", "");
        await expect(details.locator(".listing-facts")).toBeVisible();
        await expect(card.locator(".listing-overview")).toBeVisible();
        expect(
          await page.evaluate(() => document.documentElement.scrollWidth),
        ).toBeLessThanOrEqual(viewport.width);
        await page.keyboard.press("Space");
        await expect(details).not.toHaveAttribute("open");
        await expect(details.locator(".listing-facts")).toBeHidden();
        await expect(card.locator(".listing-overview")).toBeVisible();
      }
    });

    test("supporting records are collapsed and keyboard accessible", async ({
      page,
    }, info) => {
      await page.goto("/");
      const records = page.locator(".case-section > details");
      await expect(records).toHaveCount(3);
      await page.screenshot({
        path: info.outputPath("homepage-collapsed.png"),
        fullPage: true,
      });
      for (const [index, record] of (await records.all()).entries()) {
        await expect(record).not.toHaveAttribute("open");
        const summary = record.locator(":scope > summary");
        const body = record.locator(":scope > :not(summary)").first();
        await expect(body).toBeHidden();
        const box = await summary.boundingBox();
        expect(box).not.toBeNull();
        expect(box!.height).toBeGreaterThanOrEqual(44);
        expect(box!.width).toBeGreaterThanOrEqual(44);
        await record.screenshot({
          path: info.outputPath(`record-${index}-collapsed.png`),
        });
        await summary.focus();
        await expect(summary).toBeFocused();
        await page.keyboard.press("Enter");
        await expect(record).toHaveAttribute("open", "");
        await expect(body).toBeVisible();
        await record.screenshot({
          path: info.outputPath(`record-${index}-expanded.png`),
        });
        expect(
          await page.evaluate(() => document.documentElement.scrollWidth),
        ).toBeLessThanOrEqual(viewport.width);
        await page.keyboard.press("Space");
        await expect(record).not.toHaveAttribute("open");
        await expect(body).toBeHidden();
      }
      for (const summary of await records.locator(":scope > summary").all()) {
        await summary.focus();
        await page.keyboard.press("Enter");
      }
      await page.screenshot({
        path: info.outputPath("homepage-expanded.png"),
        fullPage: true,
      });
    });
  });
}

test("reduced motion removes entrance and disclosure animations", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await page.locator(".listing-evidence summary").first().click();
  const motion = await page
    .locator(
      ".market-preview, .preview-agent, .listing-card, .listing-facts, .listing-evidence summary",
    )
    .evaluateAll((nodes) =>
      nodes.map((node) => {
        const style = getComputedStyle(node);
        return {
          animation: style.animationName,
          transition: style.transitionDuration,
        };
      }),
    );
  for (const style of motion) {
    expect(style.animation).toBe("none");
    expect(
      style.transition
        .split(",")
        .every((duration) => parseFloat(duration) === 0),
    ).toBe(true);
  }
});
