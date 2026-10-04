import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    throw new Error(`the landing must not call ${route.request().url()}`);
  });
});

test("plans an evening from the keyboard at desktop width", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "One evening, held to two stops.",
  );
  await page.getByRole("link", { name: "Skip to the evening" }).focus();
  await page.keyboard.press("Enter");
  const field = page.getByRole("textbox", { name: "Describe the evening" });
  await expect(field).toBeFocused();
  await field.fill("Dinner in Kyoto tomorrow at 7, then a short walk.");
  await page.getByRole("button", { name: "Plan this evening" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("status")).toContainText("Dinner in Kyoto tomorrow at 7");
  await expect(page.getByText("Project repository")).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
  await expectNoSeriousViolations(page);
});

test("stays within a 390 pixel width and accepts an example", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: /Dinner in Kyoto/ }).click();
  await expect(page.getByRole("textbox", { name: "Describe the evening" })).toHaveValue(
    /Dinner in Kyoto/,
  );
  await expectNoHorizontalOverflow(page);
  await expectNoSeriousViolations(page);
});

test("drops the entrance motion when reduced motion is requested", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  const motion = await page.locator(".landing-hero").evaluate((element) => {
    return getComputedStyle(element).animationName;
  });
  expect(motion).toBe("none");
});

test("asks for an evening instead of inventing one", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Plan this evening" }).click();
  await expect(page.getByRole("alert")).toContainText("Describe the evening");
  await expect(page.getByRole("status")).toHaveCount(0);
});

/** Assert that an axe audit reports no serious or critical accessibility violations. */
async function expectNoSeriousViolations(page: import("@playwright/test").Page) {
  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  );
  expect(serious.map((violation) => violation.id)).toEqual([]);
}

/** Assert that document overflow stays within one pixel of the viewport width. */
async function expectNoHorizontalOverflow(page: import("@playwright/test").Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
}
