import { z } from "zod";

const clock = z.string().regex(/^\d{2}:\d{2}(:\d{2})?$/);
const day = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
const instant = z.string().min(1);
const intentKind = z.enum([
  "dinner",
  "drinks",
  "coffee",
  "dessert",
  "show",
  "walk",
  "live_music",
  "museum",
]);
const confidence = z.enum(["high", "medium", "low", "insufficient"]);

export const planIntentSchema = z.object({
  kind: intentKind,
  label: z.string().min(1),
  position: z.number().int().min(1).max(2),
});

export const planBriefSchema = z.object({
  raw_prompt: z.string().min(1),
  destination_text: z.string().nullable(),
  local_date: day.nullable(),
  pending_date: z
    .object({
      phrase: z.enum(["today", "tonight", "tomorrow", "weekday", "next_weekday", "weekend"]),
      weekday: z.number().int().min(0).max(6).nullable().optional(),
    })
    .nullable(),
  local_start: clock.nullable(),
  party_size: z.number().int().nullable(),
  budget: z
    .object({
      amount: z.string().nullable(),
      currency: z.string().nullable(),
      tier: z.enum(["low", "moderate", "high"]).nullable(),
      bound: z.enum(["exact", "at_most", "about"]).nullable(),
    })
    .nullable(),
  intents: z.array(planIntentSchema).max(2),
  preferences: z.array(z.string()),
  accessibility_needs: z.array(z.string()),
  missing_essentials: z.array(
    z.object({
      kind: z.literal("missing"),
      field: z.enum(["destination", "date", "time", "primary_intent"]),
      question: z.string().min(1),
    }),
  ),
  ambiguities: z.array(
    z.object({
      kind: z.literal("ambiguity"),
      field: z.string().min(1),
      message: z.string().min(1),
      candidates: z.array(z.string()),
      blocking: z.boolean(),
    }),
  ),
  confidence,
});

export const interpretedBriefSchema = z.object({
  outcome: z.enum(["needs_follow_up", "ready_for_retrieval"]),
  brief: planBriefSchema,
  destination: z.unknown().nullable(),
  stops: z.array(z.unknown()).max(2),
  follow_up: z.unknown().nullable(),
  warnings: z.array(z.string()),
});

export const resolvedDestinationSchema = z.object({
  label: z.string().min(1),
  source_text: z.string().min(1),
  locality: z.string().nullable(),
  region: z.string().nullable(),
  country_code: z.string().nullable(),
  timezone_name: z.string().nullable(),
  latitude: z.number().nullable(),
  longitude: z.number().nullable(),
  serpapi_location: z.string().nullable(),
  confidence: confidence.nullable(),
  resolution_source: z.enum(["locations_api", "maps_lookup"]).nullable(),
  provenance: z
    .object({
      provider: z.literal("serpapi"),
      source_url: z.string().min(1),
      retrieved_at: instant,
      label: z.string().min(1),
    })
    .nullable(),
});

export const destinationResolutionSchema = z.object({
  status: z.enum([
    "resolved",
    "ambiguous",
    "unsupported",
    "missing_coordinates",
    "unknown_timezone",
    "budget_exhausted",
  ]),
  destination: resolvedDestinationSchema.nullable(),
  choices: z.array(resolvedDestinationSchema).max(3),
  billed_requests: z.number().int().nonnegative(),
  local_time: z
    .object({
      date_status: z.enum(["resolved", "ambiguous", "missing"]),
      wall_status: z.enum(["unique", "gap", "ambiguous", "not_checked"]),
      local_date: day.nullable(),
      local_start: clock.nullable(),
      timezone_name: z.string().min(1),
      offsets: z.array(z.string()),
      date_candidates: z.array(z.string()),
    })
    .nullable(),
});

export const planEvidenceSchema = z.object({
  source: z.enum(["official", "maps", "community"]),
  text: z.string().min(1),
  url: z.string().nullable(),
  retrieved_at: instant,
});

export const planStopSchema = z.object({
  position: z.number().int().min(1).max(2),
  intent: intentKind,
  label: z.string().min(1),
  name: z.string().min(1),
  place_id: z.string().nullable(),
  data_id: z.string().nullable(),
  address: z.string().nullable(),
  latitude: z.number().nullable(),
  longitude: z.number().nullable(),
  maps_link: z.string().nullable(),
  website: z.string().nullable(),
  confidence: z.enum(["high", "medium", "low"]),
  hours_status: z.enum(["open", "unknown"]),
  explanation: z.string().min(1),
  evidence: z.array(planEvidenceSchema).max(8),
  unknown_fields: z.array(z.string()),
  warnings: z.array(z.string()),
});

export const planTransitionSchema = z.strictObject({
  from_stop: z.number().int().min(1).max(2),
  to_stop: z.number().int().min(1).max(2),
  status: z.literal("unverified"),
  directions_url: z.string().url(),
});

export const eveningPlanSchema = z.object({
  version: z.literal("2"),
  outcome: z.enum(["planned", "no_results", "insufficient_evidence"]),
  local_date: day,
  local_start: clock,
  stops: z.array(planStopSchema).max(2),
  transition: planTransitionSchema.nullable(),
  warnings: z.array(z.string()),
  retrieved_at: instant,
});

export const briefDiffSchema = z.object({
  added: z.array(z.string()),
  removed: z.array(z.string()),
  changed: z.array(
    z.object({
      field: z.string().min(1),
      before: z.string().nullable(),
      after: z.string().nullable(),
    }),
  ),
});

export const refinementProposalSchema = z.object({
  version: z.literal("2"),
  applied: z.literal(false),
  current: planBriefSchema,
  proposed: planBriefSchema,
  follow_up: z.unknown().nullable(),
  diff: briefDiffSchema,
  message: z.string().min(1),
});

export const planErrorSchema = z.object({
  request_id: z.string().min(1),
  contract_version: z.string().min(1),
  error: z.object({
    code: z.string().min(1),
    message: z.string().min(1),
    retryable: z.boolean(),
    next_action: z.string().min(1),
    fixture_available: z.boolean(),
    fields: z
      .array(
        z.object({
          field: z.string().min(1),
          message: z.string().min(1),
        }),
      )
      .optional(),
    retry_after_seconds: z.number().int().nonnegative().nullable().optional(),
  }),
});

export type EveningPlan = z.infer<typeof eveningPlanSchema>;
export type RefinementProposal = z.infer<typeof refinementProposalSchema>;
