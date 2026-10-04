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

test("shows three timelines, one moment, and a different fallback", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto("/?layout=sample");
  await expect(page.getByRole("note")).toContainText("Layout sample");
  await expect(page.getByRole("article", { name: "Courtyard Lantern" })).toBeVisible();
  await expect(page.getByRole("article", { name: "North Gallery Supper" })).toBeVisible();
  await expect(page.getByRole("article", { name: "Platform Seats" })).toBeVisible();
  const recommended = page.getByRole("article", { name: "Recommended" });
  await expect(recommended).toContainText("Courtyard Lantern");
  await expect(recommended).toContainText("Fit Strong");
  await expect(recommended).toContainText("Confidence High");
  const fallback = page.getByRole("article", { name: "Fallback" });
  await expect(fallback).toContainText("North Gallery Supper");
  await expect(fallback).toContainText("Fit Possible");
  await expect(fallback).toContainText("Confidence Medium");
  await expect(page.getByText("Synthetic development ·")).toBeVisible();
  await expect(page.getByText("Scoring policy v1")).toBeVisible();
  await expect(
    page.getByText("Synthetic development evidence. Planning evidence—not live occupancy."),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /Selected/ })).toHaveCount(1);
  await expectNoHorizontalOverflow(page);

  await page.getByRole("button", { name: "Why this moment?" }).click();
  const evidence = page.getByRole("region", { name: "Why this moment?" });
  await expect(evidence).toContainText("the wait was shorter before 8 pm");
  await expect(
    evidence.locator('a[href="https://example.com/happen/synthetic/courtyard-lantern"]'),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close evidence" }).click();
  await expect(page.getByRole("button", { name: "Why this moment?" })).toBeFocused();
});

test("stacks the result without horizontal overflow on a narrow screen", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?layout=sample");
  await expect(page.getByRole("article", { name: "Recommended" })).toBeVisible();
  await expect(page.getByRole("article", { name: "Fallback" })).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test("the planner stays empty until the layout sample is requested", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Nothing has been recommended yet.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Courtyard Lantern" })).toHaveCount(0);
});

/** Assert that document overflow stays within one pixel of the viewport width. */
async function expectNoHorizontalOverflow(page: import("@playwright/test").Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
}
