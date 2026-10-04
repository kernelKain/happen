import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, type Route, test } from "@playwright/test";

const original = "Dinner in Kyoto tomorrow at 7, then a short walk.";

const brief = {
  raw_prompt: original,
  destination_text: "Kyoto",
  local_date: "2026-10-05",
  pending_date: null,
  local_start: "19:00:00",
  party_size: null,
  budget: null,
  intents: [
    { kind: "dinner", label: "dinner", position: 1 },
    { kind: "walk", label: "walk", position: 2 },
  ],
  preferences: [],
  accessibility_needs: [],
  missing_essentials: [],
  ambiguities: [],
  confidence: "high",
};

const destination = {
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
};

const resolved = {
  status: "resolved",
  destination,
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
};

const eveningPlan = {
  version: "2",
  outcome: "planned",
  local_date: "2026-10-05",
  local_start: "19:00:00",
  stops: [
    {
      position: 1,
      intent: "dinner",
      label: "dinner",
      name: "Kura",
      place_id: "kura",
      data_id: null,
      address: "Kyoto",
      latitude: 35.01,
      longitude: 135.77,
      maps_link: "https://maps.example/kura",
      website: null,
      confidence: "high",
      hours_status: "open",
      explanation: "Maps hours cover 19:00 on 2026-10-05.",
      evidence: [
        {
          source: "maps",
          text: "monday: 17:00-22:00",
          url: "https://maps.example/kura",
          retrieved_at: "2026-10-04T12:00:00Z",
        },
      ],
      unknown_fields: [],
      warnings: [],
    },
  ],
  transition: null,
  warnings: [],
  retrieved_at: "2026-10-04T12:00:00Z",
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    throw new Error(`the landing must not call ${route.request().url()}`);
  });
});

test("plans an evening from the keyboard at desktop width", async ({ page }) => {
  const calls: string[] = [];
  await mockPlanning(page, calls);
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "One evening, held to two stops.",
  );
  await page.getByRole("link", { name: "Skip to the evening" }).focus();
  await page.keyboard.press("Enter");
  const field = page.getByRole("textbox", { name: "Describe the evening" });
  await expect(field).toBeFocused();
  await field.fill(original);
  await page.getByRole("button", { name: "Plan this evening" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText(`Your words: ${original}`)).toBeVisible();
  await expect(page.getByRole("button", { name: "Find the plan" })).toBeVisible();
  expect(calls.filter((url) => url.includes("/api/v2/plans"))).toHaveLength(0);
  await page.getByRole("button", { name: "Find the plan" }).click();
  await expect(page.getByRole("heading", { name: "This evening" })).toBeVisible();
  await expect(page.getByText("Kura")).toBeVisible();
  expect(calls.filter((url) => url.includes("/api/v2/plans"))).toHaveLength(1);
  await expect(page.getByText("Project repository")).toHaveCount(0);
  await expect(page.getByText(/fixture|captured evidence/i)).toHaveCount(0);
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
  await expect(page.getByRole("status")).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
  await expectNoSeriousViolations(page);
});

test("asks one follow-up on a phone without searching", async ({ page }) => {
  await page.route("**/api/v2/**", async (route) => {
    const url = route.request().url();
    if (url.includes("/api/v1/")) {
      throw new Error(url);
    }
    await fulfill(route, {
      outcome: "needs_follow_up",
      brief: { ...brief, destination_text: null, intents: [] },
      destination: null,
      stops: [],
      follow_up: {
        kind: "missing",
        field: "destination",
        question: "Which place should this evening be in?",
      },
      warnings: [],
    });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("textbox", { name: "Describe the evening" }).fill("Dinner tomorrow at 7.");
  await page.getByRole("button", { name: "Plan this evening" }).click();
  await expect(page.getByLabel("Which place should this evening be in?")).toBeVisible();
  await expect(page.getByRole("button", { name: "Find the plan" })).toHaveCount(0);
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

test("cancels a place search without starting another", async ({ page }) => {
  let plans = 0;
  let release: (() => void) | undefined;
  await page.route("**/api/v2/**", async (route) => {
    const url = route.request().url();
    if (url.includes("/briefs/interpret")) {
      await fulfill(route, {
        outcome: "ready_for_retrieval",
        brief,
        destination: null,
        stops: [],
        follow_up: null,
        warnings: [],
      });
      return;
    }
    if (url.includes("/destinations/resolve")) {
      await fulfill(route, resolved);
      return;
    }
    if (url.includes("/plans") && !url.includes("refine")) {
      plans += 1;
      await new Promise<void>((resolve) => {
        release = resolve;
      });
      try {
        await fulfill(route, eveningPlan);
      } catch {
        // The page cancelled this search.
      }
      return;
    }
    throw new Error(url);
  });
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await page.getByRole("textbox", { name: "Describe the evening" }).fill(original);
  await page.getByRole("button", { name: "Plan this evening" }).click();
  await page.getByRole("button", { name: "Find the plan" }).click();
  await expect(page.getByRole("status")).toContainText("Finding live places");
  await page.getByRole("button", { name: "Cancel" }).click();
  release?.();
  await expect(page.getByRole("heading", { name: "This evening" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Find the plan" })).toBeVisible();
  expect(plans).toBe(1);
});

test("shows a quota failure without a stand-in plan", async ({ page }) => {
  await page.route("**/api/v2/**", async (route) => {
    const url = route.request().url();
    if (url.includes("/briefs/interpret")) {
      await fulfill(route, {
        outcome: "ready_for_retrieval",
        brief,
        destination: null,
        stops: [],
        follow_up: null,
        warnings: [],
      });
      return;
    }
    if (url.includes("/destinations/resolve")) {
      await fulfill(route, resolved);
      return;
    }
    await fulfill(
      route,
      {
        request_id: "req-1",
        contract_version: "2",
        error: {
          code: "QUOTA_EXHAUSTED",
          message: "The search allowance for this plan has been reached.",
          retryable: false,
          next_action: "Try again later.",
          fixture_available: true,
        },
      },
      503,
    );
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("textbox", { name: "Describe the evening" }).fill(original);
  await page.getByRole("button", { name: "Plan this evening" }).click();
  await page.getByRole("button", { name: "Find the plan" }).click();
  await expect(page.getByRole("alert")).toContainText("search allowance");
  await expect(page.getByRole("button", { name: "Try again" })).toHaveCount(0);
  await expect(page.getByText(/fixture|captured evidence|sample plan/i)).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
});

/** Fulfill a mocked planning response. */
async function fulfill(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

/** Mock the ready Kyoto path and record the URLs the page calls. */
async function mockPlanning(page: Page, calls: string[]) {
  await page.route("**/api/v2/**", async (route) => {
    const url = route.request().url();
    calls.push(url);
    if (url.includes("/api/v1/")) {
      throw new Error(url);
    }
    if (url.includes("/briefs/interpret")) {
      await fulfill(route, {
        outcome: "ready_for_retrieval",
        brief,
        destination: null,
        stops: [],
        follow_up: null,
        warnings: [],
      });
      return;
    }
    if (url.includes("/destinations/resolve")) {
      await fulfill(route, resolved);
      return;
    }
    if (url.includes("/plans") && !url.includes("refine")) {
      await fulfill(route, eveningPlan);
      return;
    }
    throw new Error(url);
  });
}

/** Assert that an axe audit reports no serious or critical accessibility violations. */
async function expectNoSeriousViolations(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  );
  expect(serious.map((violation) => violation.id)).toEqual([]);
}

/** Assert that document overflow stays within one pixel of the viewport width. */
async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
}
