import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { SAMPLE_RESULT } from "../src/app/result/sample";

test("a fixture response is not requested or shown", async ({ page }) => {
  let fixtureCalls = 0;
  await page.route("**/api/v1/demo-recommendations", async (route) => {
    fixtureCalls += 1;
    await route.fulfill({ json: SAMPLE_RESULT });
  });
  await page.route("**/api/v1/recommendations", async (route) => {
    fixtureCalls += 1;
    await route.fulfill({ json: SAMPLE_RESULT });
  });
  await page.route("**/api/v1/meta", async (route) => {
    fixtureCalls += 1;
    await route.fulfill({
      json: {
        fixture_available: true,
        live_available: true,
        timezone: "Asia/Kolkata",
        canonical_preset: { neighborhood: "indiranagar" },
      },
    });
  });

  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/?layout=sample");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Turn your evening into a checked plan.",
  );
  await expect(page.getByText("Courtyard Lantern")).toHaveCount(0);
  await expect(page.getByText("Captured fixture")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Use captured evidence" })).toHaveCount(0);
  await expect(page.getByText(/fixture|captured evidence|Project repository/i)).toHaveCount(0);
  expect(fixtureCalls).toBe(0);

  await page.getByRole("button", { name: "Build my evening" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Describe the evening before Happen can plan it.",
  );
  expect(fixtureCalls).toBe(0);
  await expectNoSeriousViolations(page);
});

test("an exhausted search stays a failure without a fixture", async ({ page }) => {
  let planCalls = 0;
  const prompt = "Dinner in Kyoto tomorrow at 7.";
  await page.route("**/api/v2/briefs/interpret", async (route) => {
    await route.fulfill({
      json: {
        outcome: "ready_for_retrieval",
        brief: {
          raw_prompt: prompt,
          plan_token: "test-plan-token-0001",
          destination_text: "Kyoto",
          local_date: "2026-10-05",
          pending_date: null,
          local_start: "19:00:00",
          party_size: null,
          budget: null,
          intents: [{ kind: "dinner", label: "dinner", position: 1 }],
          preferences: [],
          accessibility_needs: [],
          missing_essentials: [],
          ambiguities: [],
          confidence: "high",
        },
        destination: null,
        stops: [],
        follow_up: null,
        warnings: [],
      },
    });
  });
  await page.route("**/api/v2/destinations/resolve", async (route) => {
    await route.fulfill({
      json: {
        status: "resolved",
        destination: {
          label: "Kyoto, Kyoto, Japan",
          source_text: "Kyoto",
          locality: "Kyoto",
          region: "Kyoto",
          country_code: "JP",
          timezone_name: "Asia/Tokyo",
          latitude: 35.01,
          longitude: 135.77,
          serpapi_location: "Kyoto,Kyoto,Japan",
          confidence: "high",
          resolution_source: "locations_api",
          provenance: null,
        },
        choices: [],
        billed_requests: 0,
        local_time: {
          date_status: "resolved",
          wall_status: "unique",
          local_date: "2026-10-05",
          local_start: "19:00:00",
          timezone_name: "Asia/Tokyo",
          offsets: ["+09:00"],
          date_candidates: [],
        },
      },
    });
  });
  await page.route("**/api/v2/plans", async (route) => {
    planCalls += 1;
    await route.fulfill({
      status: 503,
      json: {
        request_id: "quota",
        contract_version: "2",
        error: {
          code: "QUOTA_EXHAUSTED",
          message: "The search allowance for this plan has been reached.",
          retryable: false,
          next_action: "Try again later.",
          fixture_available: true,
        },
      },
    });
  });

  await page.goto("/");
  await page
    .getByRole("textbox", { name: "What would you like to do?" })
    .fill("Dinner in Kyoto tomorrow at 7.");
  await page.getByRole("button", { name: "Build my evening" }).click();
  await page.getByRole("button", { name: "Check live places" }).click();
  const alert = page.getByRole("alert");
  await expect(alert).toContainText("The search allowance for this plan has been reached.");
  await expect(alert).toContainText("Try again later.");
  await expect(alert.getByRole("button", { name: "Try again" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Use captured evidence" })).toHaveCount(0);
  await expect(page.getByText("Courtyard Lantern")).toHaveCount(0);
  await expect(page.getByText(/fixture|captured evidence/i)).toHaveCount(0);
  expect(planCalls).toBe(1);
});

/** Assert that an axe audit reports no serious or critical accessibility violations. */
async function expectNoSeriousViolations(page: import("@playwright/test").Page) {
  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  );
  expect(serious.map((violation) => violation.id)).toEqual([]);
}
