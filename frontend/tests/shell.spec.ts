import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/meta", async (route) => {
    throw new Error(`unexpected metadata request ${route.request().url()}`);
  });
  await page.route("**/api/v1/recommendations", async (route) => {
    throw new Error(`unexpected recommendation request ${route.request().url()}`);
  });
  await page.route("**/api/v1/demo-recommendations", async (route) => {
    throw new Error(`unexpected fixture request ${route.request().url()}`);
  });
});

test("a layout query stays on the landing", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  for (const target of ["/?layout=sample", "/?layout=planner", "/"]) {
    await page.goto(target);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "One evening, held to two stops.",
    );
    await expect(page.getByRole("button", { name: "Plan this evening" })).toBeVisible();
    await expect(page.getByLabel("Neighbourhood")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Find the moment" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Use captured evidence" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Restore demo preset" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Project repository" })).toHaveCount(0);
    await expect(page.getByText("Courtyard Lantern")).toHaveCount(0);
    await expect(page.getByText("Synthetic fixture")).toHaveCount(0);
    await expect(page.getByText("Indiranagar")).toHaveCount(0);
    await expectNoHorizontalOverflow(page);
  }
  await expectNoSeriousViolations(page);
});

test("the landing stays usable at 390 pixels without a demo preset", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?layout=planner");
  await expect(page.getByRole("textbox", { name: "Describe the evening" })).toBeVisible();
  await page
    .getByRole("button", { name: "Dinner in Kyoto tomorrow at 7, then a short walk." })
    .click();
  await expect(page.getByRole("textbox", { name: "Describe the evening" })).toHaveValue(
    "Dinner in Kyoto tomorrow at 7, then a short walk.",
  );
  await expect(page.getByText("Indiranagar")).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
  await expectNoSeriousViolations(page);
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
