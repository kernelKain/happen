import type { FollowUp, PlanningBrief } from "../../lib/api/plan";

const DESTINATION_QUESTION = "Which place should this evening be in?";

/** Matches the planning prompt limit. Longer text is refused before a request. */
export const EVENING_TEXT_LIMIT = 2000;

/** Keep the visitor's original wording when a revision replaces the stored prompt. */
export function restorePrompt(brief: PlanningBrief, original: string): PlanningBrief {
  return { ...brief, raw_prompt: original };
}

/** Resolve only after the brief names a place and the destination question is not open. */
export function shouldResolve(brief: PlanningBrief, followUp: FollowUp | null): boolean {
  if (!brief.destination_text?.trim()) {
    return false;
  }
  if (followUp?.kind === "missing" && followUp.field === "destination") {
    return false;
  }
  if (followUp?.kind === "ambiguity" && followUp.field === "destination") {
    return false;
  }
  return true;
}

/** One question. Destination choices replace the parser question while they are open. */
export function activeFollowUp(
  brief: PlanningBrief,
  followUp: FollowUp | null,
  choosing: boolean,
): FollowUp | null {
  if (choosing) {
    return null;
  }
  if (!brief.destination_text?.trim()) {
    return { kind: "missing", field: "destination", question: DESTINATION_QUESTION };
  }
  return followUp;
}

/** Fill a missing calendar date from a resolved zone without overwriting an entered date. */
export function applyLocalTime(
  brief: PlanningBrief,
  local: { local_date: string | null; local_start: string | null } | null,
): PlanningBrief {
  if (!local) {
    return brief;
  }
  const localDate = brief.local_date ?? local.local_date;
  return {
    ...brief,
    local_date: localDate,
    local_start: brief.local_start ?? local.local_start,
    pending_date: brief.local_date || !local.local_date ? brief.pending_date : null,
  };
}

export function canFindPlan(input: {
  destination: { timezone_name: string | null } | null;
  brief: PlanningBrief | null;
  followUp: FollowUp | null;
  choosing: boolean;
  busy: boolean;
}): boolean {
  const { brief } = input;
  if (!brief || input.busy || input.choosing || input.followUp) {
    return false;
  }
  if (!brief.destination_text?.trim() || !brief.local_date || !brief.local_start) {
    return false;
  }
  if (brief.intents.length < 1) {
    return false;
  }
  return Boolean(input.destination?.timezone_name);
}

/** Clock values for a time input. Seconds from the API stay off the control. */
export function clockForInput(value: string | null): string {
  if (!value) {
    return "";
  }
  return value.slice(0, 5);
}

export function moveIntent(
  intents: PlanningBrief["intents"],
  index: number,
  direction: -1 | 1,
): PlanningBrief["intents"] {
  const next = index + direction;
  if (next < 0 || next >= intents.length) {
    return intents;
  }
  const copy = [...intents];
  const [item] = copy.splice(index, 1);
  if (!item) {
    return intents;
  }
  copy.splice(next, 0, item);
  return copy.map((intent, position) => ({ ...intent, position: position + 1 }));
}

export function partySizeIssue(value: string): string | null {
  if (!value.trim()) {
    return null;
  }
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 20) {
    return "Party size is from 1 to 20.";
  }
  return null;
}

export function budgetIssue(amount: string, currency: string): string | null {
  const trimmedAmount = amount.trim();
  const trimmedCurrency = currency.trim();
  if (!trimmedAmount && !trimmedCurrency) {
    return null;
  }
  if (!trimmedAmount || !trimmedCurrency) {
    return "Amount and currency go together.";
  }
  if (!/^\d+(\.\d{1,2})?$/.test(trimmedAmount) || !/^[A-Za-z]{3}$/.test(trimmedCurrency)) {
    return "Use an amount and a three-letter currency.";
  }
  return null;
}

export function preferenceIssue(value: string): string | null {
  const parts = value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  if (parts.length > 8 || parts.some((item) => item.length > 40)) {
    return "Keep each item short, and use at most eight.";
  }
  return null;
}

export function preferenceList(value: string): string[] {
  if (preferenceIssue(value)) {
    return [];
  }
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

/** Hide notes that would offer a stand-in plan or describe an internal step. */
export function visibleWarning(text: string): boolean {
  return !/fixture|captured evidence|retrieval has not run/i.test(text);
}

export function outcomeLead(
  outcome: "planned" | "no_results" | "insufficient_evidence",
  stopCount = 0,
): string | null {
  if (outcome === "no_results") {
    return "No live places matched this evening.";
  }
  if (outcome === "insufficient_evidence") {
    if (stopCount > 0) {
      return "A listed stop is missing verified evidence for a requested constraint.";
    }
    return "The live evidence was not enough to choose a stop.";
  }
  return null;
}

export function constraintCopy(item: {
  constraint: string;
  status: "met" | "unmet" | "unknown" | "not_applicable";
}): string | null {
  if (item.status === "met") {
    return `${item.constraint}: verified from the retrieved evidence.`;
  }
  if (item.status === "unmet") {
    return `${item.constraint}: the retrieved evidence does not support this.`;
  }
  if (item.status === "unknown") {
    return `${item.constraint}: unknown. The retrieval did not show this.`;
  }
  return null;
}

/** Another place search is needed only when the destination, date, time, or intents change. */
export function needsAnotherSearch(current: PlanningBrief, proposed: PlanningBrief): boolean {
  return searchKey(current) !== searchKey(proposed);
}

/** Python scores again when party size, budget, preferences, or access needs change. */
export function needsRescore(current: PlanningBrief, proposed: PlanningBrief): boolean {
  return (
    needsAnotherSearch(current, proposed) || constraintKey(current) !== constraintKey(proposed)
  );
}

function constraintKey(brief: PlanningBrief): string {
  const budget = brief.budget
    ? [
        brief.budget.amount ?? "",
        brief.budget.currency ?? "",
        brief.budget.tier ?? "",
        brief.budget.bound ?? "",
      ].join(":")
    : "";
  return [
    brief.party_size ?? "",
    budget,
    brief.preferences.join(","),
    brief.accessibility_needs.join(","),
  ].join("|");
}

function searchKey(brief: PlanningBrief): string {
  const intents = brief.intents.map((item) => `${item.position}:${item.kind}`).join(",");
  return [
    brief.destination_text?.trim() ?? "",
    brief.local_date ?? "",
    clockForInput(brief.local_start),
    intents,
  ].join("|");
}

type StatusStop = {
  position?: number;
  price?: string | null;
  busyness?: "listed" | "unknown";
  rating?: number | null;
  unknown_fields: string[];
  hours_status: "open" | "unknown";
};

/** A listed price stays tied to the retrieval. A missing price is not a recommendation. */
export function priceStatus(stop: StatusStop): string {
  if (stop.price && !stop.unknown_fields.includes("price")) {
    return `Price listed: ${stop.price}. That listing is from the retrieval, not a live quote.`;
  }
  return "Price was not listed.";
}

/** Popular times are a listing, never a live crowd count. */
export function busynessStatus(stop: StatusStop): string {
  if (stop.busyness === "listed" && !stop.unknown_fields.includes("popular_times")) {
    return "Busyness was listed. It is not a live crowd count.";
  }
  return "Busyness was not listed.";
}

/** A rating is shown only when the retrieval included one. */
export function ratingStatus(stop: StatusStop): string {
  if (typeof stop.rating === "number" && !stop.unknown_fields.includes("rating")) {
    return `A rating of ${stop.rating} was listed. It is not a live measure.`;
  }
  return "A rating was not listed.";
}

export function hoursCopy(stop: StatusStop): string {
  if (stop.hours_status === "open") {
    if ((stop.position ?? 1) > 1) {
      return "Opening hours are listed. A separate arrival was not planned for this stop.";
    }
    return "Opening hours cover this arrival.";
  }
  return "Opening hours were not listed.";
}

export function confidenceCopy(value: "high" | "medium" | "low"): string {
  if (value === "high") {
    return "Confidence is high.";
  }
  if (value === "medium") {
    return "Confidence is medium.";
  }
  return "Confidence is low.";
}

export function arrivalCopy(position: number, localStart: string, timezone: string | null): string {
  const clock = clockForInput(localStart);
  const zone = timezone ? ` (${timezone})` : "";
  if (position === 1) {
    return `Planned arrival ${clock}${zone}.`;
  }
  return `A separate arrival was not planned. The evening starts at ${clock}${zone}.`;
}

export function retrievalCopy(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return `Retrieved ${value}.`;
  }
  const stamp = parsed
    .toISOString()
    .replace("T", " ")
    .replace(".000Z", " UTC")
    .replace("Z", " UTC");
  return `Retrieved ${stamp}.`;
}

export function evidenceShape(
  plan: {
    outcome: "planned" | "no_results" | "insufficient_evidence";
    stops: {
      hours_status: "open" | "unknown";
      constraints?: { status: string }[];
    }[];
    warnings: string[];
  },
  intentCount: number,
): "planned" | "partial" | "insufficient" | "none" {
  if (plan.outcome === "no_results") {
    return "none";
  }
  if (plan.outcome === "insufficient_evidence") {
    return "insufficient";
  }
  const thin =
    plan.stops.length < intentCount ||
    plan.stops.some((stop) => stop.hours_status === "unknown") ||
    plan.stops.some((stop) =>
      stop.constraints?.some((item) => item.status === "unknown" || item.status === "unmet"),
    ) ||
    plan.warnings.some((note) => /did not respond|allowance stopped|No open place/i.test(note));
  return thin ? "partial" : "planned";
}
