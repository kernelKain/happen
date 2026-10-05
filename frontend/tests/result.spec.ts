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
  await page.route("**/api/v1/meta", async (route) => {
    await route.fulfill({ json: meta });
  });
});

test("a sample query stays on the landing", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?layout=sample");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Your evening, checked.");
  await expect(page.getByText("Courtyard Lantern")).toHaveCount(0);
  await expect(page.getByText("Layout sample")).toHaveCount(0);
  await expect(page.getByText("Recommended")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Use captured evidence" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Project repository" })).toHaveCount(0);
  await expect(page.getByText("Indiranagar")).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
});

test("the landing does not show the layout sample", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Your evening, checked.");
  await expect(page.getByRole("heading", { name: "Courtyard Lantern" })).toHaveCount(0);
});

/** Assert that document overflow stays within one pixel of the viewport width. */
async function expectNoHorizontalOverflow(page: import("@playwright/test").Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
}
