const ERROR_TITLES: Record<string, string> = {
  PROCESSING_TIMEOUT: "Request timed out",
  SERPAPI_QUOTA_EXHAUSTED: "Search allowance reached",
  SERPAPI_UNAVAILABLE: "Place evidence unavailable",
  SERPAPI_INVALID_RESPONSE: "Place evidence unavailable",
  LIVE_MODE_DISABLED: "Live evidence unavailable",
  MODEL_UNAVAILABLE: "Evidence model unavailable",
  FIXTURE_NOT_AVAILABLE: "Captured evidence unavailable",
  FIXTURE_CHECKSUM_INVALID: "Captured evidence unavailable",
  FIXTURE_SCHEMA_INVALID: "Captured evidence unavailable",
  INVALID_INPUT: "These inputs are not valid",
  RATE_LIMITED: "Happen is busy",
  IDEMPOTENCY_CONFLICT: "Submission already running",
  REQUEST_TOO_LARGE: "Request too large",
  INTERNAL_ERROR: "Happen could not finish",
};

const FIELD_LABELS: Record<string, string> = {
  neighborhood: "Neighbourhood",
  restaurant_category: "Category",
  arrival_start: "Arrival from",
  arrival_end: "Arrival until",
  desired_experience: "Desired experience",
  priorities: "Priority order",
  body: "Request",
};

/** Name a public error code so the page can show a specific state. */
export function errorTitle(code: string): string {
  return ERROR_TITLES[code] ?? "Happen could not finish";
}

/** Return the planner label for a public field error. */
export function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? field;
}
