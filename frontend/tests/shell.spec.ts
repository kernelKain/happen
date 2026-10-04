import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const meta = {
  contract_version: "1.0.0",
  service_version: "0.1.0",
  supported_neighborhoods: ["indiranagar"],
  supported_categories: ["restaurants"],
  supported_experiences: ["easier_conversation"],
  priority_dimensions: ["conversation", "short_wait", "seating"],
  canonical_preset: {
    neighborhood: "indiranagar",
    restaurant_category: "restaurants",
    arrival_start: "18:00",
    arrival_end: "21:00",
    desired_experience: "easier_conversation",
    priorities: ["conversation", "short_wait", "seating"],
  },
  fixture_available: false,
  live_available: false,
  model_status: "not_loaded",
  scoring_policy_version: "v1",
  timezone: "Asia/Kolkata",
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/recommendations", async (route) => {
    throw new Error(`unexpected recommendation request ${route.request().url()}`);
  });
});

test("shows the planner after metadata loads", async ({ page }) => {
  let release = () => undefined;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/v1/meta", async (route) => {
    await gate;
    await route.fulfill({ json: meta });
  });

  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto("/");
  await expect(page.getByRole("status")).toContainText("Checking the Happen service");
  release();
  await expect(page.getByRole("heading", { name: "Happen" })).toBeVisible();
  await expect(page.getByLabel("Neighbourhood")).toHaveValue("indiranagar");
  await expect(page.getByRole("button", { name: "Find the moment" })).toBeDisabled();
  await expect(page.getByText("The evidence model is not ready")).toBeVisible();
  await expect(page.getByText("Planning evidence—not live occupancy.")).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test("keeps the planner usable at 390 pixels", async ({ page }) => {
  await page.route("**/api/v1/meta", async (route) => {
    await route.fulfill({ json: meta });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Restore demo preset" })).toBeVisible();
  await page.getByLabel("Arrival from").fill("19:00");
  await page.getByRole("button", { name: "Restore demo preset" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("Arrival from")).toHaveValue("18:00");
  await page.getByRole("button", { name: "Move Shorter waiting earlier" }).click();
  await expect(page.getByRole("listitem").nth(0)).toContainText("Shorter waiting");
  await expectNoHorizontalOverflow(page);
});

test("shows a service error with retry and no invented result", async ({ page }) => {
  let available = false;
  await page.route("**/api/v1/meta", async (route) => {
    if (!available) {
      await route.abort();
      return;
    }
    await route.fulfill({ json: meta });
  });
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("The Happen service is unavailable");
  await expect(page.getByRole("heading", { name: "Happen" })).toBeVisible();
  await expect(page.getByText("Nothing has been recommended yet.")).toBeVisible();
  available = true;
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByLabel("Neighbourhood")).toHaveValue("indiranagar");
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("disables submission when the contract major version differs", async ({ page }) => {
  await page.route("**/api/v1/meta", async (route) => {
    await route.fulfill({ json: { ...meta, contract_version: "2.0.0", model_status: "ready" } });
  });
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("A new version is available");
  await expect(page.getByRole("button", { name: "Find the moment" })).toBeDisabled();
  await expect(page.getByLabel("Neighbourhood")).toBeDisabled();
});

test("initial and error states have no serious accessibility violations", async ({ page }) => {
  await page.route("**/api/v1/meta", async (route) => {
    await route.fulfill({ json: meta });
  });
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto("/");
  await expect(page.getByLabel("Neighbourhood")).toHaveValue("indiranagar");
  await expectNoSeriousViolations(page);

  await page.unroute("**/api/v1/meta");
  await page.route("**/api/v1/meta", async (route) => {
    await route.abort();
  });
  await page.reload();
  await expect(page.getByRole("alert")).toBeVisible();
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
