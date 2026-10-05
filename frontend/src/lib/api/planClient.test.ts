import { describe, expect, it, vi } from "vitest";
import {
  interpretBrief,
  PlanRequestError,
  refineBrief,
  requestPlan,
  resolveDestination,
} from "./planClient";

const brief = {
  raw_prompt: "Dinner in Kyoto on 2026-10-05 at 7pm",
  destination_text: "Kyoto",
  plan_token: null as string | null,
  local_date: "2026-10-05",
  pending_date: null,
  local_start: "19:00:00",
  party_size: null,
  budget: null,
  intents: [{ kind: "dinner" as const, label: "dinner", position: 1 }],
  preferences: [],
  accessibility_needs: [],
  missing_essentials: [],
  ambiguities: [],
  confidence: "high" as const,
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
  confidence: "high" as const,
  resolution_source: "locations_api" as const,
  provenance: null,
};

const eveningPlanResponse = {
  version: "2" as const,
  outcome: "no_results" as const,
  local_date: "2026-10-05",
  local_start: "19:00:00",
  party_size: null,
  stops: [],
  transition: null,
  warnings: [],
  retrieved_at: "2026-10-04T12:00:00Z",
  billed_requests: 2,
  remaining_requests: 6,
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("plan client", () => {
  it("reads a brief and does not treat an ambiguous destination as a transport error", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v2/briefs/interpret")) {
        return json({
          outcome: "ready_for_retrieval",
          brief,
          destination: null,
          stops: [],
          follow_up: null,
          warnings: ["Live place retrieval has not run."],
        });
      }
      return json(
        {
          status: "ambiguous",
          destination: null,
          choices: [destination, { ...destination, label: "Kyoto, other" }],
          billed_requests: 0,
          local_time: null,
        },
        409,
      );
    });
    const interpreted = await interpretBrief("Dinner in Kyoto on 2026-10-05 at 7pm", { fetchImpl });
    const resolved = await resolveDestination(
      { query: "Kyoto", plan_token: "test-plan-token-0001" },
      { fetchImpl },
    );
    expect(interpreted.brief.destination_text).toBe("Kyoto");
    expect(resolved.status).toBe("ambiguous");
    expect(resolved.choices).toHaveLength(2);
  });

  it("sends the plan token and never a caller-supplied request count", async () => {
    const bodies: Record<string, unknown>[] = [];
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      bodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      if (String(_input).endsWith("/api/v2/destinations/resolve")) {
        return json({
          status: "resolved",
          destination,
          choices: [],
          billed_requests: 2,
          remaining_requests: 6,
          local_time: null,
        });
      }
      return json(eveningPlanResponse);
    });
    await resolveDestination({ query: "Kyoto", plan_token: "test-plan-token-0001" }, { fetchImpl });
    await requestPlan(
      {
        destination,
        intents: [{ kind: "dinner", label: "dinner", position: 1 }],
        local_date: "2026-10-05",
        local_start: "19:00:00",
        party_size: 2,
        budget: null,
        preferences: [],
        accessibility_needs: [],
        plan_token: "test-plan-token-0001",
      },
      { fetchImpl },
    );
    for (const body of bodies) {
      expect(body.plan_token).toBe("test-plan-token-0001");
      expect("prior_billed_requests" in body).toBe(false);
    }
  });

  it("reports the server's own counts rather than a local tally", async () => {
    const fetchImpl = vi.fn(async () => json({ ...eveningPlanResponse, billed_requests: 5 }));
    const plan = await requestPlan(
      {
        destination,
        intents: [{ kind: "dinner", label: "dinner", position: 1 }],
        local_date: "2026-10-05",
        local_start: "19:00:00",
        party_size: 2,
        budget: null,
        preferences: [],
        accessibility_needs: [],
        plan_token: "test-plan-token-0001",
      },
      { fetchImpl },
    );
    expect(plan.billed_requests).toBe(5);
    expect(plan.remaining_requests).toBe(eveningPlanResponse.remaining_requests);
  });

  it("keeps quota and timeout failures user-safe", async () => {
    const fetchImpl = vi.fn(async () =>
      json(
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
      ),
    );
    const error = await requestPlan(
      {
        destination,
        intents: brief.intents,
        local_date: "2026-10-05",
        local_start: "19:00:00",
        party_size: 4,
        budget: { amount: "40", currency: "USD", tier: null, bound: "at_most" },
        preferences: ["quiet"],
        accessibility_needs: ["wheelchair access"],
        plan_token: "test-plan-token-0001",
      },
      { fetchImpl },
    ).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(PlanRequestError);
    if (!(error instanceof PlanRequestError)) {
      return;
    }
    expect(error.retryable).toBe(false);
    expect(error.message).not.toMatch(/fixture|prompt|traceback/i);
    expect(error.nextAction).toBe("Try again later.");
  });

  it("sends party size, budget, preferences, and accessibility needs", async () => {
    let sent: Record<string, unknown> = {};
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      sent = JSON.parse(String(init?.body)) as Record<string, unknown>;
      return json({
        version: "2",
        outcome: "planned",
        local_date: "2026-10-05",
        local_start: "19:00:00",
        party_size: 4,
        stops: [
          {
            position: 1,
            intent: "dinner",
            label: "dinner",
            name: "Kura",
            place_id: "kura",
            data_id: null,
            address: "Kyoto",
            latitude: 35,
            longitude: 135.7,
            maps_link: null,
            website: null,
            confidence: "low",
            hours_status: "unknown",
            explanation: "Opening hours were not listed, so this stop is less certain.",
            evidence: [],
            constraints: [
              { constraint: "quiet", status: "unknown", evidence: [] },
              { constraint: "wheelchair access", status: "unknown", evidence: [] },
              { constraint: "budget", status: "unknown", evidence: [] },
              { constraint: "party size", status: "unknown", evidence: [] },
            ],
            components: [
              {
                name: "hours",
                result: "unknown",
                detail: "Hours: opening hours were not listed.",
              },
            ],
            unknown_fields: ["price", "popular_times"],
            warnings: [],
          },
        ],
        transition: null,
        warnings: [],
        retrieved_at: "2026-10-04T12:00:00Z",
      });
    });
    const plan = await requestPlan(
      {
        destination,
        intents: brief.intents,
        local_date: "2026-10-05",
        local_start: "19:00:00",
        party_size: 4,
        budget: { amount: "40", currency: "USD", tier: "low", bound: "at_most" },
        preferences: ["quiet"],
        accessibility_needs: ["wheelchair access"],
        plan_token: "test-plan-token-0001",
      },
      { fetchImpl },
    );
    expect(sent.party_size).toBe(4);
    expect(sent.preferences).toEqual(["quiet"]);
    expect(sent.accessibility_needs).toEqual(["wheelchair access"]);
    expect(sent.budget).toMatchObject({ amount: "40", currency: "USD", tier: "low" });
    expect(plan.party_size).toBe(4);
    expect(plan.stops[0].constraints.map((item) => item.status)).toEqual([
      "unknown",
      "unknown",
      "unknown",
      "unknown",
    ]);
    expect(JSON.stringify(plan)).not.toMatch(/"score"|"weight"/);
  });

  it("reports an unreachable backend without reading a prompt back", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError("network down");
    });
    const error = await interpretBrief("Dinner in a private place", { fetchImpl }).catch(
      (caught: unknown) => caught,
    );
    expect(error).toBeInstanceOf(PlanRequestError);
    if (!(error instanceof PlanRequestError)) {
      return;
    }
    expect(error.message).toBe("Happen could not be reached.");
    expect(error.message).not.toMatch(/private place/);
  });

  it("lets the caller abort before another search starts", async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(
      resolveDestination(
        { query: "Kyoto", plan_token: "test-plan-token-0001" },
        { signal: controller.signal, fetchImpl: vi.fn() },
      ),
    ).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("refinement purposes", () => {
  const proposal = (purpose: "follow_up" | "plan_refinement", token: string | null) => ({
    version: "2" as const,
    applied: false as const,
    purpose,
    current: { ...brief, plan_token: "test-plan-token-0001" },
    proposed: { ...brief, plan_token: token },
    follow_up: null,
    diff: { added: ["preferences"], removed: [], changed: [] },
    message: "The current plan was not changed.",
  });

  it("sends follow_up as the default so an answer keeps the current plan", async () => {
    let body: Record<string, unknown> = {};
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      return json(proposal("follow_up", "test-plan-token-0001"));
    });
    const result = await refineBrief({ ...brief, plan_token: "test-plan-token-0001" }, "Kyoto", {
      fetchImpl,
    });
    expect(body.purpose).toBe("follow_up");
    expect(result.purpose).toBe("follow_up");
    // The same plan identity survives, so the answer stays usable.
    expect(result.proposed.plan_token).toBe("test-plan-token-0001");
  });

  it("sends plan_refinement for a change reviewed after a result", async () => {
    let body: Record<string, unknown> = {};
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      return json(proposal("plan_refinement", "fresh-plan-token-0002"));
    });
    const result = await refineBrief(
      { ...brief, plan_token: "test-plan-token-0001" },
      "Make it romantic",
      {
        fetchImpl,
        purpose: "plan_refinement",
      },
    );
    expect(body.purpose).toBe("plan_refinement");
    expect(result.purpose).toBe("plan_refinement");
    // An accepted refinement is a newly submitted plan with its own identity.
    expect(result.proposed.plan_token).toBe("fresh-plan-token-0002");
  });

  it("never sends a token or an allowance count the browser chose", async () => {
    const bodies: Record<string, unknown>[] = [];
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      bodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      return json(proposal("plan_refinement", "fresh-plan-token-0002"));
    });
    await refineBrief({ ...brief, plan_token: "test-plan-token-0001" }, "Make it romantic", {
      fetchImpl,
      purpose: "plan_refinement",
    });
    const sent = bodies[0];
    // Only the brief, the revision, and the purpose cross this boundary.
    expect(Object.keys(sent).sort()).toEqual(["current", "purpose", "revision"]);
    expect(sent).not.toHaveProperty("plan_token");
    expect(sent).not.toHaveProperty("remaining_requests");
    expect(sent).not.toHaveProperty("billed_requests");
  });

  it("rejects a proposal whose purpose is not one of the two actions", async () => {
    const fetchImpl = vi.fn(async () =>
      json({ ...proposal("follow_up", null), purpose: "make_it_better" }),
    );
    await expect(
      refineBrief({ ...brief, plan_token: "test-plan-token-0001" }, "Kyoto", { fetchImpl }),
    ).rejects.toBeInstanceOf(PlanRequestError);
  });
});
