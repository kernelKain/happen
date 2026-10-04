import { describe, expect, it } from "vitest";
import { SAMPLE_RESULT } from "../../app/result/sample";
import { LOCAL_PRESET } from "./meta";
import { recommendationSchema, requestDemoRecommendation } from "./recommendation";

describe("recommendation result", () => {
  it("renders the canonical sample as three rows, one primary, and a different fallback", () => {
    const result = recommendationSchema.parse(SAMPLE_RESULT);
    expect(result.candidates).toHaveLength(3);
    expect(result.candidates.every((candidate) => candidate.windows)).toBe(true);
    expect(result.recommendation?.candidate_id).toBe("courtyard-lantern");
    expect(result.fallback?.candidate_id).toBe("north-gallery");
    expect(result.recommendation?.fit_label).toBe("strong");
    expect(result.recommendation?.confidence_label).toBe("high");
    expect(result.provenance.data_label).toBe("synthetic_development");
    expect(result.provenance.scoring_policy_version).toBe("v1");
    expect(result.evidence.every((item) => item.quoted_span.length > 0)).toBe(true);
  });

  it("posts the planner draft to the fixture endpoint with the supplied idempotency key", async () => {
    const calls: { url: string; key: string | null; body: string }[] = [];
    const result = await requestDemoRecommendation(
      LOCAL_PRESET,
      async (input, init) => {
        calls.push({
          url: String(input),
          key: new Headers(init?.headers).get("Idempotency-Key"),
          body: String(init?.body),
        });
        return new Response(JSON.stringify(SAMPLE_RESULT), { status: 200 });
      },
      {
        origin: "http://example.test",
        idempotencyKey: "11111111-1111-4111-8111-111111111111",
      },
    );
    expect(result.recommendation?.candidate_id).toBe("courtyard-lantern");
    expect(calls).toEqual([
      {
        url: "http://example.test/api/v1/demo-recommendations",
        key: "11111111-1111-4111-8111-111111111111",
        body: JSON.stringify(LOCAL_PRESET),
      },
    ]);
  });

  it("raises the public error message when the fixture endpoint rejects the request", async () => {
    await expect(
      requestDemoRecommendation(
        LOCAL_PRESET,
        async () =>
          new Response(
            JSON.stringify({
              error: {
                code: "MODEL_UNAVAILABLE",
                message: "The evidence model is unavailable.",
                next_action: "Try again in a moment.",
              },
            }),
            { status: 503 },
          ),
        { origin: "http://example.test" },
      ),
    ).rejects.toMatchObject({
      name: "RecommendationRequestError",
      code: "MODEL_UNAVAILABLE",
      message: "The evidence model is unavailable.",
      nextAction: "Try again in a moment.",
    });
  });
});
