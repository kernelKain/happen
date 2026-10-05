import { describe, expect, it } from "vitest";
import {
  destinationResolutionSchema,
  eveningPlanSchema,
  interpretedBriefSchema,
  planErrorSchema,
  refinementProposalSchema,
} from "./plan";

const brief = {
  raw_prompt: "Dinner in Kyoto on 2026-10-05 at 7pm",
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
};

describe("v2 planning contracts", () => {
  it("accepts an interpreted brief and ignores an extra field", () => {
    const parsed = interpretedBriefSchema.parse({
      outcome: "ready_for_retrieval",
      brief,
      destination: null,
      stops: [],
      follow_up: null,
      warnings: ["Live place retrieval has not run."],
      future_field: "ignored",
    });
    expect(parsed.brief.destination_text).toBe("Kyoto");
    expect(parsed).not.toHaveProperty("future_field");
  });

  it("accepts a resolved destination and an ambiguous choice list", () => {
    const destination = {
      label: "Tokyo, Tokyo, Japan",
      source_text: "Tokyo",
      locality: "Tokyo",
      region: "Tokyo",
      country_code: "JP",
      timezone_name: "Asia/Tokyo",
      latitude: 35.67,
      longitude: 139.65,
      serpapi_location: "Tokyo,Tokyo,Japan",
      confidence: "high",
      resolution_source: "locations_api",
      provenance: null,
    };
    const resolved = destinationResolutionSchema.parse({
      status: "resolved",
      destination,
      choices: [],
      billed_requests: 0,
      local_time: {
        date_status: "resolved",
        wall_status: "not_checked",
        local_date: "2026-10-05",
        local_start: null,
        timezone_name: "Asia/Tokyo",
        offsets: [],
        date_candidates: [],
      },
    });
    const ambiguous = destinationResolutionSchema.parse({
      status: "ambiguous",
      destination: null,
      choices: [destination, { ...destination, label: "Tokyo, other" }],
      billed_requests: 0,
      local_time: null,
    });
    expect(resolved.destination?.timezone_name).toBe("Asia/Tokyo");
    expect(ambiguous.choices).toHaveLength(2);
  });

  it("accepts one planned evening without a travel duration", () => {
    const plan = eveningPlanSchema.parse({
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
          latitude: 35,
          longitude: 135.7,
          maps_link: "https://maps.example/kura",
          website: "https://kura.example",
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
            {
              source: "official",
              text: "Official site listed for this place.",
              url: "https://kura.example",
              retrieved_at: "2026-10-04T12:00:00Z",
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
    expect(plan.stops[0].evidence.map((item) => item.source)).toEqual(["maps", "official"]);
    expect(plan.transition).toBeNull();
  });

  it("accepts an unapplied refinement and a safe error", () => {
    const proposal = refinementProposalSchema.parse({
      version: "2",
      applied: false,
      current: brief,
      proposed: { ...brief, destination_text: "Tokyo" },
      follow_up: null,
      diff: {
        added: [],
        removed: [],
        changed: [{ field: "destination", before: "Kyoto", after: "Tokyo" }],
      },
      message: "The current plan was not changed.",
    });
    const error = planErrorSchema.parse({
      request_id: "req",
      contract_version: "1.0.0",
      error: {
        code: "QUOTA_EXHAUSTED",
        message: "The search allowance for this plan has been reached.",
        retryable: false,
        next_action: "Try again later.",
        fixture_available: false,
      },
    });
    expect(proposal.applied).toBe(false);
    expect(error.error.code).toBe("QUOTA_EXHAUSTED");
  });

  it("rejects a transition that invents a duration", () => {
    expect(() =>
      eveningPlanSchema.parse({
        version: "2",
        outcome: "planned",
        local_date: "2026-10-05",
        local_start: "19:00:00",
        stops: [],
        transition: {
          from_stop: 1,
          to_stop: 2,
          status: "unverified",
          directions_url: "https://www.google.com/maps/dir/?api=1",
          duration: 15,
        },
        warnings: [],
        retrieved_at: "2026-10-04T12:00:00Z",
      }),
    ).toThrow();
  });
});
