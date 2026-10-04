import { describe, expect, it, vi } from "vitest";
import { interpretBrief, PlanRequestError, requestPlan, resolveDestination } from "./planClient";

const brief = {
  raw_prompt: "Dinner in Kyoto on 2026-10-05 at 7pm",
  destination_text: "Kyoto",
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
  confidence: "high" as const,
  resolution_source: "locations_api" as const,
  provenance: null,
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
    const resolved = await resolveDestination({ query: "Kyoto" }, { fetchImpl });
    expect(interpreted.brief.destination_text).toBe("Kyoto");
    expect(resolved.status).toBe("ambiguous");
    expect(resolved.choices).toHaveLength(2);
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
        prior_billed_requests: 0,
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
        prior_billed_requests: 0,
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
      resolveDestination({ query: "Kyoto" }, { signal: controller.signal, fetchImpl: vi.fn() }),
    ).rejects.toMatchObject({ name: "AbortError" });
  });
});
