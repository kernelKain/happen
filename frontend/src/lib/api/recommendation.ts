import { z } from "zod";
import { apiOrigin, type CanonicalPreset } from "./meta";

const clock = z.string().regex(/^\d{2}:\d{2}$/);
const fitLabel = z.enum(["strong", "possible", "weak", "unknown"]);
const confidenceLabel = z.enum(["high", "medium", "low", "insufficient"]);
const extractionConfidence = z.enum(["high", "medium", "low"]);

export const arrivalWindowSchema = z.object({
  window_id: z.string().min(1),
  arrival_start: clock,
  arrival_end: clock,
  feasibility: z.literal("verified_open"),
  status: fitLabel,
  fit_label: fitLabel,
  confidence_label: confidenceLabel,
  evidence_references: z.array(z.string()),
  reason_codes: z.array(z.string()),
});

export const candidateSchema = z.object({
  candidate_id: z.string().min(1),
  name: z.string().min(1),
  source_url: z.string().url(),
  hours_summary: z.string(),
  evidence_summary: z.string(),
  windows: z.array(arrivalWindowSchema).min(1),
  missing_dimensions: z.array(z.string()),
  warnings: z.array(z.string()),
});

export const selectedMomentSchema = z.object({
  candidate_id: z.string().min(1),
  window_id: z.string().min(1),
  restaurant_name: z.string().min(1),
  arrival_start: clock,
  arrival_end: clock,
  fit_label: fitLabel,
  confidence_label: confidenceLabel,
  explanation: z.string().min(1),
  evidence_references: z.array(z.string()),
});

export const evidenceSchema = z.object({
  evidence_id: z.string().min(1),
  dimension: z.enum(["conversation", "short_wait", "seating"]),
  polarity: z.enum(["positive", "negative", "mixed"]),
  temporal_hint: z.string().min(1),
  quoted_span: z.string().min(1),
  source_url: z.string().url(),
  captured_at: z.string().min(1),
  extraction_confidence: extractionConfidence,
  validation_status: z.enum(["accepted", "partially_accepted"]),
  candidate_id: z.string().min(1),
  window_ids: z.array(z.string()),
});

export const recommendationSchema = z.object({
  request_id: z.string().min(1),
  contract_version: z.string().min(1),
  outcome: z.enum(["recommendation", "partial_evidence", "insufficient_evidence"]),
  provenance: z.object({
    mode: z.literal("captured_fixture"),
    captured_at: z.string().min(1),
    generated_at: z.string().min(1),
    timezone: z.string().min(1),
    model_id: z.string().min(1),
    adapter_id: z.string().min(1),
    extraction_schema_version: z.string().min(1),
    scoring_policy_version: z.string().min(1),
    fixture_version: z.string().min(1),
    contract_version: z.string().min(1),
    stale: z.boolean(),
    data_label: z.literal("synthetic_development"),
  }),
  candidates: z.array(candidateSchema).length(3),
  recommendation: selectedMomentSchema.nullable(),
  fallback: selectedMomentSchema.nullable(),
  warnings: z.array(z.object({ code: z.string().min(1), message: z.string().min(1) })),
  rejected_evidence_count: z.number().int().nonnegative(),
  evidence: z.array(evidenceSchema),
});

export type RecommendationResult = z.infer<typeof recommendationSchema>;
export type SelectedMoment = z.infer<typeof selectedMomentSchema>;

const errorSchema = z.object({
  error: z.object({
    code: z.string().min(1),
    message: z.string().min(1),
    next_action: z.string().min(1),
  }),
});

export class RecommendationRequestError extends Error {
  readonly code: string;
  readonly nextAction: string;

  constructor(code: string, message: string, nextAction: string) {
    super(message);
    this.name = "RecommendationRequestError";
    this.code = code;
    this.nextAction = nextAction;
  }
}

/** Ask the fixture endpoint to score the planner request. Each call uses a new idempotency key. */
export async function requestDemoRecommendation(
  body: CanonicalPreset,
  fetchImpl: typeof fetch = fetch,
  options: { origin?: string; timeoutMs?: number; idempotencyKey?: string } = {},
): Promise<RecommendationResult> {
  const origin = options.origin ?? apiOrigin();
  const response = await fetchImpl(`${origin}/api/v1/demo-recommendations`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "Idempotency-Key": options.idempotencyKey ?? crypto.randomUUID(),
    },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(options.timeoutMs ?? 30_000),
  });
  const payload: unknown = await response.json();
  if (!response.ok) {
    const parsed = errorSchema.safeParse(payload);
    if (parsed.success) {
      throw new RecommendationRequestError(
        parsed.data.error.code,
        parsed.data.error.message,
        parsed.data.error.next_action,
      );
    }
    throw new RecommendationRequestError(
      "INTERNAL_ERROR",
      "Happen could not complete that request.",
      "Try again in a moment.",
    );
  }
  return recommendationSchema.parse(payload);
}
