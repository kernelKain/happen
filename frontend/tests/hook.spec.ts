import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { SAMPLE_RESULT } from "../src/app/result/sample";

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

const unavailable = {
  request_id: "error-model",
  contract_version: "1.0.0",
  error: {
    code: "MODEL_UNAVAILABLE",
    message: "The evidence model is unavailable.",
    retryable: true,
    next_action: "Try again in a moment.",
    fixture_available: false,
  },
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/meta", async (route) => {
    await route.fulfill({ json: meta });
  });
  await page.route("**/api/v1/recommendations", async (route) => {
    throw new Error(`unexpected live recommendation ${route.request().url()}`);
  });
});

test("scores the preset from the keyboard and can start over", async ({ page }) => {
  let release = () => undefined;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let idempotencyKey = "";
  await page.route("**/api/v1/demo-recommendations", async (route) => {
    idempotencyKey = route.request().headers()["idempotency-key"] ?? "";
    await gate;
    await route.fulfill({ json: SAMPLE_RESULT });
  });

  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Find the moment" })).toBeEnabled();
  await page.getByRole("button", { name: "Find the moment" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("status")).toContainText("Gathering evidence.");
  await expect(page.getByRole("button", { name: "Find the moment" })).toBeDisabled();
  release();

  const recommended = page.getByRole("article", { name: "Recommended" });
  await expect(recommended).toContainText("Courtyard Lantern");
  await expect(recommended).toContainText("Fit Strong");
  await expect(recommended).toContainText("Confidence High");
  await expect(page.getByRole("article", { name: "Fallback" })).toContainText(
    "North Gallery Supper",
  );
  await expect(page.getByRole("article", { name: "Platform Seats" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Selected/ })).toHaveCount(1);
  await expect(page.getByText("Synthetic development ·")).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await expectNoSeriousViolations(page);

  await page.getByRole("button", { name: "Why this moment?" }).click();
  await expect(page.getByRole("region", { name: "Why this moment?" })).toContainText(
    "conversation was easy around 7 pm",
  );
  await page.getByRole("button", { name: "Close evidence" }).click();
  await expect(page.getByRole("button", { name: "Why this moment?" })).toBeFocused();
  await page.getByRole("button", { name: "Start over" }).click();
  await expect(page.getByText("Nothing has been recommended yet.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Courtyard Lantern" })).toHaveCount(0);
  expect(idempotencyKey).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);
});

test("shows three timelines and no winner when evidence is insufficient", async ({ page }) => {
  await page.route("**/api/v1/demo-recommendations", async (route) => {
    await route.fulfill({
      json: {
        ...SAMPLE_RESULT,
        outcome: "insufficient_evidence",
        recommendation: null,
        fallback: null,
        evidence: [],
      },
    });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Find the moment" }).click();
  await expect(page.getByRole("heading", { name: "No moment selected" })).toBeVisible();
  await expect(
    page.getByText("Fewer than two restaurants have enough comparable evidence."),
  ).toBeVisible();
  await expect(page.getByRole("article", { name: "Courtyard Lantern" })).toBeVisible();
  await expect(page.getByRole("article", { name: "North Gallery Supper" })).toBeVisible();
  await expect(page.getByRole("article", { name: "Platform Seats" })).toBeVisible();
  await expect(page.getByRole("article", { name: "Recommended" })).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
});

test("keeps the planner inputs when the fixture request fails and retry uses a new request", async ({
  page,
}) => {
  const keys: string[] = [];
  let attempts = 0;
  await page.route("**/api/v1/demo-recommendations", async (route) => {
    attempts += 1;
    keys.push(route.request().headers()["idempotency-key"] ?? "");
    if (attempts === 1) {
      await route.fulfill({ status: 503, json: unavailable });
      return;
    }
    await route.fulfill({ json: SAMPLE_RESULT });
  });
  await page.goto("/");
  await page.getByLabel("Arrival from").fill("19:00");
  await page.getByRole("button", { name: "Find the moment" }).click();
  const alert = page.getByRole("alert");
  await expect(alert).toContainText("The evidence model is unavailable.");
  await expect(alert).toContainText("Try again in a moment.");
  await expect(page.getByLabel("Arrival from")).toHaveValue("19:00");
  await expect(page.getByText("Nothing has been recommended yet.")).toBeVisible();
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByRole("article", { name: "Recommended" })).toContainText(
    "Courtyard Lantern",
  );
  await expect(page.getByLabel("Arrival from")).toHaveValue("19:00");
  expect(keys).toHaveLength(2);
  expect(keys[0]).not.toBe(keys[1]);
});

test("offers captured evidence only after the user chooses it", async ({ page }) => {
  await page.unroute("**/api/v1/recommendations");
  await page.route("**/api/v1/meta", async (route) => {
    await route.fulfill({
      json: { ...meta, fixture_available: true, live_available: true, model_status: "ready" },
    });
  });
  let demoCalls = 0;
  await page.route("**/api/v1/recommendations", async (route) => {
    await route.fulfill({
      status: 503,
      json: {
        ...unavailable,
        error: {
          ...unavailable.error,
          code: "SERPAPI_UNAVAILABLE",
          message: "Live place evidence is temporarily unavailable.",
          next_action: "Retry, or use the captured snapshot.",
          fixture_available: true,
        },
      },
    });
  });
  await page.route("**/api/v1/demo-recommendations", async (route) => {
    demoCalls += 1;
    await route.fulfill({
      json: {
        ...SAMPLE_RESULT,
        provenance: { ...SAMPLE_RESULT.provenance, data_label: "captured_fixture" },
      },
    });
  });
  await page.goto("/");
  await expect(page.getByText("Live evidence", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Find the moment" }).click();
  const alert = page.getByRole("alert");
  await expect(alert).toContainText("Live place evidence is temporarily unavailable.");
  expect(demoCalls).toBe(0);
  await page.getByRole("button", { name: "Use captured evidence" }).click();
  await expect(page.getByText("Captured fixture ·")).toBeVisible();
  expect(demoCalls).toBe(1);
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
