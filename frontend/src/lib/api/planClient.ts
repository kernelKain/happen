import { apiOrigin } from "./meta";
import {
  type DestinationResolution,
  destinationResolutionSchema,
  type EveningPlan,
  eveningPlanSchema,
  type InterpretedBrief,
  interpretedBriefSchema,
  type PlanningBrief,
  planErrorSchema,
  type RefinementProposal,
  type RefinementPurpose,
  type ResolvedDestination,
  refinementProposalSchema,
} from "./plan";

/** A user-safe planning failure. The message never includes the prompt. */
export class PlanRequestError extends Error {
  readonly code: string;
  readonly nextAction: string;
  readonly retryable: boolean;
  readonly status: number;

  constructor(input: {
    code: string;
    message: string;
    nextAction: string;
    retryable: boolean;
    status: number;
  }) {
    super(input.message);
    this.name = "PlanRequestError";
    this.code = input.code;
    this.nextAction = input.nextAction;
    this.retryable = input.retryable;
    this.status = input.status;
  }
}

export type PlanFetch = typeof fetch;

type CallOptions = {
  signal?: AbortSignal;
  fetchImpl?: PlanFetch;
};

export type ResolveQuery = {
  query: string;
  pending_date?: "today" | "tomorrow";
  local_date?: string | null;
  local_start?: string | null;
  plan_token: string;
};

export type PlanQuery = {
  destination: ResolvedDestination;
  intents: PlanningBrief["intents"];
  local_date: string;
  local_start: string;
  party_size: number | null;
  budget: PlanningBrief["budget"];
  preferences: string[];
  accessibility_needs: string[];
  plan_token: string;
};

function unreachable(status = 0): PlanRequestError {
  return new PlanRequestError({
    code: "UNAVAILABLE",
    message: "Happen could not be reached.",
    nextAction: "Try again.",
    retryable: true,
    status,
  });
}

function isAbort(error: unknown): boolean {
  return (
    error instanceof DOMException && (error.name === "AbortError" || error.name === "TimeoutError")
  );
}

async function postJson(
  path: string,
  body: unknown,
  options: CallOptions,
): Promise<{ status: number; payload: unknown }> {
  if (options.signal?.aborted) {
    throw options.signal.reason ?? new DOMException("The operation was aborted.", "AbortError");
  }
  const fetchImpl = options.fetchImpl ?? fetch;
  let response: Response;
  try {
    response = await fetchImpl(`${apiOrigin()}${path}`, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: options.signal,
    });
  } catch (error) {
    if (isAbort(error)) {
      throw error;
    }
    throw unreachable();
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch (error) {
    if (isAbort(error)) {
      throw error;
    }
    throw unreachable(response.status);
  }
  return { status: response.status, payload };
}

function errorFrom(status: number, payload: unknown): PlanRequestError {
  const parsed = planErrorSchema.safeParse(payload);
  if (!parsed.success) {
    return unreachable(status);
  }
  return new PlanRequestError({
    code: parsed.data.error.code,
    message: parsed.data.error.message,
    nextAction: parsed.data.error.next_action,
    retryable: parsed.data.error.retryable,
    status,
  });
}

/** Read one prompt. This call does not retrieve places. */
export async function interpretBrief(
  prompt: string,
  options: CallOptions = {},
): Promise<InterpretedBrief> {
  const { status, payload } = await postJson("/api/v2/briefs/interpret", { prompt }, options);
  if (status !== 200) {
    throw errorFrom(status, payload);
  }
  const parsed = interpretedBriefSchema.safeParse(payload);
  if (!parsed.success) {
    throw unreachable(status);
  }
  return parsed.data;
}

/**
 * Resolve one destination.
 * Several matches are a normal result, including the HTTP 409 choice response.
 */
export async function resolveDestination(
  query: ResolveQuery,
  options: CallOptions = {},
): Promise<DestinationResolution> {
  const body: Record<string, unknown> = {
    query: query.query,
    plan_token: query.plan_token,
  };
  if (query.pending_date) {
    body.pending_date = query.pending_date;
  }
  if (query.local_date) {
    body.local_date = query.local_date;
  }
  if (query.local_start) {
    body.local_start = query.local_start;
  }
  const { status, payload } = await postJson("/api/v2/destinations/resolve", body, options);
  if (status === 200 || status === 409) {
    const parsed = destinationResolutionSchema.safeParse(payload);
    if (!parsed.success) {
      throw unreachable(status);
    }
    return parsed.data;
  }
  throw errorFrom(status, payload);
}

/** Retrieve live places. Call this only after the user confirms Find the plan. */
export async function requestPlan(
  query: PlanQuery,
  options: CallOptions = {},
): Promise<EveningPlan> {
  const { status, payload } = await postJson(
    "/api/v2/plans",
    {
      destination: query.destination,
      intents: query.intents,
      local_date: query.local_date,
      local_start: query.local_start,
      party_size: query.party_size,
      budget: query.budget,
      preferences: query.preferences,
      accessibility_needs: query.accessibility_needs,
      plan_token: query.plan_token,
    },
    options,
  );
  if (status !== 200) {
    throw errorFrom(status, payload);
  }
  const parsed = eveningPlanSchema.safeParse(payload);
  if (!parsed.success) {
    throw unreachable(status);
  }
  return parsed.data;
}

/**
 * Validate a revision. The caller decides whether to keep the proposed brief.
 *
 * The purpose says which of the two actions this is. `follow_up` continues the
 * current plan, so the server keeps the current token and its remaining
 * allowance. `plan_refinement` is a newly submitted plan, so the server issues
 * a new token with a fresh allowance. The page never supplies a token here:
 * the server resolves the plan identity from the brief it already issued, so
 * nothing about the allowance is trusted from the browser.
 */
export async function refineBrief(
  current: PlanningBrief,
  revision: string,
  options: CallOptions & { purpose?: RefinementPurpose } = {},
): Promise<RefinementProposal> {
  const { status, payload } = await postJson(
    "/api/v2/plans/refine",
    { current, revision, purpose: options.purpose ?? "follow_up" },
    options,
  );
  if (status !== 200) {
    throw errorFrom(status, payload);
  }
  const parsed = refinementProposalSchema.safeParse(payload);
  if (!parsed.success) {
    throw unreachable(status);
  }
  return parsed.data;
}
