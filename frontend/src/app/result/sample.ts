import { type RecommendationResult, recommendationSchema } from "../../lib/api/recommendation";

const BANDS = ["18:00", "18:30", "19:00", "19:30", "20:00", "20:30"] as const;
const DISCLAIMER = "Synthetic development evidence. Planning evidence—not live occupancy.";

type Mark = {
  fit: "strong" | "possible" | "weak" | "unknown";
  confidence: "high" | "medium" | "low" | "insufficient";
};

/** A labeled layout of the synthetic Indiranagar result. It is not a live score. */
export const SAMPLE_RESULT: RecommendationResult = recommendationSchema.parse({
  request_id: "layout-sample",
  contract_version: "1.0.0",
  outcome: "recommendation",
  provenance: {
    mode: "captured_fixture",
    captured_at: "2026-10-03T12:00:00+05:30",
    generated_at: "2026-10-03T12:00:00+05:30",
    timezone: "Asia/Kolkata",
    model_id: "bartowski/google_gemma-3-270m-it-GGUF",
    adapter_id: "none",
    extraction_schema_version: "1",
    scoring_policy_version: "v1",
    fixture_version: "1.0.0",
    contract_version: "1.0.0",
    stale: false,
    data_label: "synthetic_development",
  },
  candidates: [
    candidate(
      "courtyard-lantern",
      "Courtyard Lantern",
      "https://example.com/happen/synthetic/courtyard-lantern",
      { "19:00": { fit: "strong", confidence: "high" } },
    ),
    candidate(
      "north-gallery",
      "North Gallery Supper",
      "https://example.com/happen/synthetic/north-gallery",
      { "19:00": { fit: "possible", confidence: "medium" } },
    ),
    candidate(
      "platform-seats",
      "Platform Seats",
      "https://example.com/happen/synthetic/platform-seats",
      { "19:00": { fit: "unknown", confidence: "insufficient" } },
    ),
  ],
  recommendation: moment(
    "courtyard-lantern",
    "Courtyard Lantern",
    "strong",
    "high",
    "Courtyard Lantern from 7:00 PM to 7:30 PM. Fit is strong and confidence is high.",
  ),
  fallback: moment(
    "north-gallery",
    "North Gallery Supper",
    "possible",
    "medium",
    "North Gallery Supper from 7:00 PM to 7:30 PM. Fit is possible and confidence is medium.",
  ),
  warnings: [{ code: "synthetic_development", message: DISCLAIMER }],
  rejected_evidence_count: 0,
  evidence: [
    signal(
      "courtyard-lantern-1:1",
      "short_wait",
      "the wait was shorter before 8 pm",
      "https://example.com/happen/synthetic/courtyard-lantern",
      "courtyard-lantern",
    ),
    signal(
      "north-gallery-1:1",
      "conversation",
      "conversation was easy around 7 pm",
      "https://example.com/happen/synthetic/north-gallery",
      "north-gallery",
    ),
    signal(
      "platform-seats-1:1",
      "seating",
      "the side seating stayed comfortable",
      "https://example.com/happen/synthetic/platform-seats",
      "platform-seats",
    ),
  ],
});

function candidate(id: string, name: string, source: string, marks: Record<string, Mark>) {
  return {
    candidate_id: id,
    name,
    source_url: source,
    hours_summary: "18:00–23:00",
    evidence_summary: "Layout sample",
    windows: BANDS.map((start) => {
      const mark = marks[start] ?? { fit: "unknown" as const, confidence: "insufficient" as const };
      return {
        window_id: `${id}:2026-10-03T${start}`,
        arrival_start: start,
        arrival_end: endOf(start),
        feasibility: "verified_open" as const,
        status: mark.fit,
        fit_label: mark.fit,
        confidence_label: mark.confidence,
        evidence_references: [] as string[],
        reason_codes: [] as string[],
      };
    }),
    missing_dimensions: [],
    warnings: ["synthetic_development"],
  };
}

function moment(
  id: string,
  name: string,
  fit: Mark["fit"],
  confidence: Mark["confidence"],
  explanation: string,
) {
  return {
    candidate_id: id,
    window_id: `${id}:2026-10-03T19:00`,
    restaurant_name: name,
    arrival_start: "19:00",
    arrival_end: "19:30",
    fit_label: fit,
    confidence_label: confidence,
    explanation,
    evidence_references: [] as string[],
  };
}

function signal(
  id: string,
  dimension: "conversation" | "short_wait" | "seating",
  quote: string,
  source: string,
  candidateId: string,
) {
  return {
    evidence_id: id,
    dimension,
    polarity: "positive" as const,
    temporal_hint: "mid_evening",
    quoted_span: quote,
    source_url: source,
    captured_at: "2026-10-03T12:00:00+05:30",
    extraction_confidence: "high" as const,
    validation_status: "accepted" as const,
    candidate_id: candidateId,
    window_ids: [`${candidateId}:2026-10-03T19:00`],
  };
}

function endOf(start: string): string {
  const [hourText, minuteText] = start.split(":");
  const total = Number(hourText) * 60 + Number(minuteText) + 30;
  const hour = Math.floor(total / 60);
  const minute = total % 60;
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}
