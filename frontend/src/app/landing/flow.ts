import type { FollowUp, PlanningBrief } from "../../lib/api/plan";

const DESTINATION_QUESTION = "Which place should this evening be in?";

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
    return "Keep each preference short, and use at most eight.";
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
): string | null {
  if (outcome === "no_results") {
    return "No live places matched this evening.";
  }
  if (outcome === "insufficient_evidence") {
    return "The live evidence was not enough to choose a stop.";
  }
  return null;
}
