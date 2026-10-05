import type {
  EveningPlan,
  PlanningBrief,
  PlanStop,
  RefinementProposal,
  ResolvedDestination,
} from "../../lib/api/plan";
import { safeSourceUrl } from "../../lib/evidenceView";

type Evidence = PlanStop["evidence"][number];

const INTENT_LABEL: Record<string, string> = {
  dinner: "Dinner",
  drinks: "Drinks",
  coffee: "Coffee",
  dessert: "Dessert",
  show: "Show",
  walk: "Walk",
  live_music: "Live music",
  museum: "Museum",
};

const NUMBER_WORD = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight"];

/** "18:00:00" → "6:00 PM". Unreadable input stays as written, never as an ISO value. */
export function formatClock(value: string | null | undefined): string {
  const match = value ? /^(\d{2}):(\d{2})/.exec(value) : null;
  if (!match) {
    return value ?? "";
  }
  const hours = Number(match[1]);
  const suffix = hours >= 12 ? "PM" : "AM";
  const twelve = hours % 12 === 0 ? 12 : hours % 12;
  return `${twelve}:${match[2]} ${suffix}`;
}

function calendar(value: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) {
    return null;
  }
  return new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]), 12));
}

/** A destination-local calendar date, "Wed, Oct 14". The date is already local. */
export function formatDay(value: string | null | undefined): string {
  const day = value ? calendar(value) : null;
  if (!day) {
    return value ?? "";
  }
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(day);
}

export function weekdayName(value: string): string {
  const day = calendar(value);
  if (!day) {
    return "";
  }
  return new Intl.DateTimeFormat("en-US", { weekday: "long", timeZone: "UTC" }).format(day);
}

/** An instant shown on the destination clock, or in UTC when the zone is unknown. */
export function formatInstant(value: string, timezone: string | null): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "an unrecorded time";
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: timezone ?? "UTC",
    timeZoneName: "short",
  }).format(parsed);
}

export function activityLabel(intent: string, label?: string): string {
  if (INTENT_LABEL[intent]) {
    return INTENT_LABEL[intent];
  }
  const text = (label ?? intent).replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function placeName(destination: ResolvedDestination | null, brief: PlanningBrief): string {
  return destination?.locality ?? destination?.label ?? brief.destination_text ?? "";
}

export function budgetText(budget: PlanningBrief["budget"]): string | null {
  if (!budget) {
    return null;
  }
  if (budget.amount && budget.currency) {
    const amount = Number(budget.amount);
    const shown = Number.isFinite(amount)
      ? new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(amount)
      : budget.amount;
    const bound = budget.bound === "at_most" ? "Up to " : budget.bound === "about" ? "About " : "";
    return `${bound}${budget.currency.toUpperCase()} ${shown}`;
  }
  if (budget.tier) {
    return `${budget.tier.charAt(0).toUpperCase()}${budget.tier.slice(1)} price range`;
  }
  return null;
}

export function partyText(size: number | null): string | null {
  if (!size) {
    return null;
  }
  return size === 1 ? "1 person" : `${size} people`;
}

/** The compact brief: place, day, and start; then the order, group, and budget. */
export function briefSummary(brief: PlanningBrief, destination: ResolvedDestination | null) {
  const where = destination?.label ?? brief.destination_text ?? "Destination needed";
  const when = [
    brief.local_date ? formatDay(brief.local_date) : "Date needed",
    brief.local_start ? formatClock(brief.local_start) : "Time needed",
  ];
  const details = [
    brief.intents.length > 0
      ? brief.intents.map((item) => activityLabel(item.kind, item.label)).join(" → ")
      : "No stop listed yet",
    partyText(brief.party_size),
    budgetText(brief.budget),
  ].filter((item): item is string => Boolean(item));
  const extras = [
    brief.accessibility_needs.length > 0
      ? `Accessibility: ${brief.accessibility_needs.join(", ")}`
      : null,
    brief.preferences.length > 0 ? `Preferences: ${brief.preferences.join(", ")}` : null,
  ].filter((item): item is string => Boolean(item));
  const zone = destination?.timezone_name
    ? `Times shown in ${destination.locality ?? destination.label} local time.`
    : null;
  return { where, when, details, extras, zone };
}

function joinOr(items: string[]): string {
  return new Intl.ListFormat("en", { type: "disjunction" }).format(items);
}

function joinAnd(items: string[]): string {
  return new Intl.ListFormat("en", { type: "conjunction" }).format(items);
}

function quoted(value: string): string {
  return `“${value}”`;
}

/** What one constraint means to a reader, never its internal name. */
export function constraintLabel(
  name: string,
  context: { partySize: number | null; currency: string | null },
): string {
  const key = name.toLowerCase().replaceAll("_", " ");
  if (key === "party size") {
    const size = context.partySize;
    return size ? `seating for ${NUMBER_WORD[size] ?? size}` : "space for your group";
  }
  if (key === "budget") {
    return context.currency ? `${context.currency.toUpperCase()} budget fit` : "budget fit";
  }
  return quoted(name);
}

const UNKNOWN_FIELD: Record<string, string> = {
  popular_times: "current crowd level",
  price: "price",
  rating: "rating",
  hours: "opening hours",
  party_size: "space for your group",
  website: "official website",
};

export function unknownFieldLabel(field: string): string {
  return UNKNOWN_FIELD[field] ?? field.replaceAll("_", " ");
}

const HOURS_REASON: Record<string, string> = {
  hours_covers_arrival: "Open at your planned arrival",
  hours_missing: "Opening hours not listed",
  hours_day_not_listed: "Hours for this day not listed",
  hours_unparseable: "Listed hours could not be read",
  hours_day_value_unrecognized: "Listed hours could not be read",
  hours_day_label_unrecognized: "Listed hours could not be read",
  hours_shape_unrecognized: "Listed hours could not be read",
  hours_contradictory: "Sources disagree on the hours",
};

export type Timing = { text: string; tone: "ok" | "caution" };

/** One clear timing status. A second stop never claims a calculated arrival. */
export function timingStatus(stop: PlanStop, plan: EveningPlan): Timing {
  const planned = stop.arrival_planned ?? stop.position === 1;
  if (stop.hours_status === "open") {
    if (planned) {
      return { text: "Open at your planned arrival", tone: "ok" };
    }
    if (stop.closes_at) {
      return { text: `Listed open until ${formatClock(stop.closes_at)}`, tone: "ok" };
    }
    return {
      text: `Listed open at ${formatClock(plan.local_start)} on ${weekdayName(plan.local_date)}`,
      tone: "ok",
    };
  }
  const reason = stop.hours_reason ? HOURS_REASON[stop.hours_reason] : undefined;
  return { text: reason ?? "Opening hours not confirmed", tone: "caution" };
}

function isPriceLevel(price: string): boolean {
  return /^[$€£¥₹₩]{1,4}$/.test(price.trim());
}

export type StopView = {
  when: { label: string; datetime: string | null };
  activity: string;
  timing: Timing;
  reasons: string[];
  facts: string[];
  unconfirmed: string[];
  contradicted: string[];
};

/** The decision-ready reading of one stop, built from typed fields only. */
export function stopView(stop: PlanStop, plan: EveningPlan, brief: PlanningBrief | null): StopView {
  const planned = stop.arrival_planned ?? stop.position === 1;
  const context = {
    partySize: plan.party_size ?? brief?.party_size ?? null,
    currency: brief?.budget?.currency ?? null,
  };
  const reasons: string[] = [];
  if (stop.hours_status === "open") {
    reasons.push(
      planned
        ? `Opening hours cover ${formatClock(plan.local_start)}.`
        : `Listed hours include ${formatClock(plan.local_start)} on ${weekdayName(plan.local_date)}.`,
    );
  }
  const constraints = stop.constraints ?? [];
  for (const item of constraints) {
    if (item.status === "met") {
      reasons.push(`Retrieved text supports ${constraintLabel(item.constraint, context)}.`);
    }
  }
  if (stop.website) {
    reasons.push("An official website was found.");
  }
  if (typeof stop.rating === "number" && !stop.unknown_fields.includes("rating")) {
    reasons.push(`Google Maps lists a ${stop.rating} rating.`);
  }

  const facts: string[] = [];
  const shown = reasons.slice(0, 3);
  if (
    typeof stop.rating === "number" &&
    reasons.length > 3 &&
    !shown.some((r) => r.includes("rating"))
  ) {
    facts.push(`Maps rating ${stop.rating}`);
  }
  if (stop.price && !stop.unknown_fields.includes("price")) {
    if (isPriceLevel(stop.price)) {
      facts.push(`Price level ${stop.price}`);
    } else {
      facts.push(stop.price);
      if (!/\b[A-Z]{3}\b/.test(stop.price)) {
        facts.push("Currency not stated");
      }
    }
  }
  if (stop.busyness === "listed" && !stop.unknown_fields.includes("popular_times")) {
    facts.push("Typical busy times listed");
  }

  const unconfirmed: string[] = [];
  for (const field of stop.unknown_fields) {
    if (field === "rating" || field === "hours") {
      continue;
    }
    unconfirmed.push(unknownFieldLabel(field));
  }
  const contradicted: string[] = [];
  for (const item of constraints) {
    if (item.status === "unknown") {
      unconfirmed.push(constraintLabel(item.constraint, context));
    }
    if (item.status === "unmet") {
      contradicted.push(constraintLabel(item.constraint, context));
    }
  }

  return {
    when: planned
      ? { label: formatClock(plan.local_start), datetime: plan.local_start.slice(0, 5) }
      : { label: "Then", datetime: null },
    activity: activityLabel(stop.intent, stop.label),
    timing: timingStatus(stop, plan),
    reasons: shown,
    facts,
    unconfirmed: [...new Set(unconfirmed)],
    contradicted: [...new Set(contradicted)],
  };
}

export function couldNotConfirm(items: string[]): string {
  return `${joinOr(items)}.`;
}

export function listAnd(items: string[]): string {
  return joinAnd(items);
}

export type PlanState = "planned" | "partial" | "insufficient" | "none";

const OUTCOME_COPY: Record<Exclude<PlanState, "planned">, string> = {
  partial: "We found a usable plan, but some requested details could not be confirmed.",
  insufficient: "We couldn't verify enough information to recommend a stop for this evening.",
  none: "No live places matched this evening.",
};

export function planState(plan: EveningPlan, intentCount: number): PlanState {
  if (plan.outcome === "no_results") {
    return "none";
  }
  if (plan.outcome === "insufficient_evidence") {
    return plan.stops.length > 0 ? "partial" : "insufficient";
  }
  const thin =
    plan.stops.length < intentCount ||
    plan.stops.some((stop) => stop.hours_status === "unknown") ||
    plan.stops.some((stop) =>
      (stop.constraints ?? []).some((item) => item.status === "unknown" || item.status === "unmet"),
    );
  return thin ? "partial" : "planned";
}

export function outcomeCopy(state: PlanState): string | null {
  return state === "planned" ? null : OUTCOME_COPY[state];
}

/** Plan notes a reader can act on. Internal or duplicated lines are dropped. */
export function planNotes(plan: EveningPlan): string[] {
  return [...new Set(plan.warnings)].filter(
    (note) =>
      !/fixture|captured evidence|retrieval has not run|sample/i.test(note) &&
      !/_[a-z]/.test(note) &&
      note !== "No open place had enough evidence for this evening.",
  );
}

export function planHeading(
  plan: EveningPlan,
  destination: ResolvedDestination | null,
  brief: PlanningBrief | null,
): string {
  const day = weekdayName(plan.local_date);
  const where = brief ? placeName(destination, brief) : (destination?.locality ?? "");
  const evening = day ? `Your ${day} evening` : "Your evening";
  return where ? `${evening} in ${where}` : evening;
}

export function planSubline(plan: EveningPlan): string {
  const count = plan.stops.length === 2 ? "Two stops" : plan.stops.length === 1 ? "One stop" : "";
  return [
    count,
    `Starts at ${formatClock(plan.local_start)}`,
    "Live listings checked through SerpApi",
  ]
    .filter(Boolean)
    .join(" · ");
}

export const SOURCE_KIND: Record<
  Evidence["source"],
  { title: string; note: string; link: string }
> = {
  maps: {
    title: "Google Maps listing",
    link: "Open the Maps listing",
    note: "The place's public listing, retrieved through SerpApi.",
  },
  official: {
    title: "Official website",
    link: "Open the official website",
    note: "The place's own site, found through SerpApi.",
  },
  community: {
    title: "Community text",
    link: "Open the community source",
    note: "Unverified context from reviews or the web. Not treated as fact.",
  },
};

export const SUPPORTS_LABEL: Record<string, string> = {
  hours: "Opening hours",
  place_identity: "Place identity",
  constraint: "Requested detail",
  contact: "Contact detail",
  description: "Description",
  provenance: "Source link",
};

export const MATCH_LABEL: Record<string, string> = {
  provider_id: "Matched by listing ID",
  official_domain: "Matched on the official domain",
  name_and_location: "Matched by name and location",
  place_record: "From the place listing",
  review_text: "From review text",
  none_found: "Not tied to this place",
};

export const VERIFICATION_LABEL: Record<Evidence["verification"], string> = {
  verified: "Confirmed by the listing",
  unverified: "Not verified",
  conflicting: "Conflicts with another source",
};

export type SourceGroup = {
  kind: Evidence["source"];
  title: string;
  note: string;
  link: string;
  items: { text: string; verification: Evidence["verification"] }[];
  links: string[];
};

/** Default source view: grouped by kind, with repeated text and links removed. */
export function sourceGroups(stop: PlanStop, skipHours: boolean): SourceGroup[] {
  const order: Evidence["source"][] = ["maps", "official", "community"];
  const groups: SourceGroup[] = [];
  const seenLinks = new Set<string>();
  for (const kind of order) {
    const items: SourceGroup["items"] = [];
    const seenText = new Set<string>();
    const links: string[] = [];
    for (const item of stop.evidence) {
      if (item.source !== kind || (skipHours && item.field === "hours")) {
        continue;
      }
      const key = item.text.trim().toLowerCase();
      if (!seenText.has(key)) {
        seenText.add(key);
        items.push({ text: item.text, verification: item.verification });
      }
      const url = item.url ? safeSourceUrl(item.url) : null;
      if (url && !seenLinks.has(url)) {
        seenLinks.add(url);
        links.push(url);
      }
    }
    if (kind === "maps" && stop.maps_link) {
      const url = safeSourceUrl(stop.maps_link);
      if (url && !seenLinks.has(url)) {
        seenLinks.add(url);
        links.push(url);
      }
    }
    if (kind === "official" && stop.website && items.length === 0) {
      const url = safeSourceUrl(stop.website);
      if (url && !seenLinks.has(url)) {
        seenLinks.add(url);
        links.push(url);
      }
    }
    if (items.length > 0 || links.length > 0) {
      groups.push({ kind, ...SOURCE_KIND[kind], items, links });
    }
  }
  return groups;
}

function namesDay(line: string, day: string): boolean {
  const label = line.split(":", 1)[0]?.trim().toLowerCase().replace(/\.$/, "") ?? "";
  return label.length >= 3 && day.toLowerCase().startsWith(label);
}

/** The planned weekday's hours first; the full week sits behind a disclosure. */
export function hoursView(stop: PlanStop, localDate: string) {
  const day = weekdayName(localDate);
  const week = stop.weekly_hours?.length
    ? stop.weekly_hours
    : stop.evidence.filter((item) => item.field === "hours").map((item) => item.text);
  const today = stop.hours_for_day ?? week.find((line) => namesDay(line, day)) ?? null;
  return { day, today, week: week.length > 1 ? week : [] };
}

/** What Python checked, in reader terms. Component details carry internal codes. */
export function checksView(stop: PlanStop, plan: EveningPlan, brief: PlanningBrief | null) {
  const context = {
    partySize: plan.party_size ?? brief?.party_size ?? null,
    currency: brief?.budget?.currency ?? null,
  };
  const rows: { label: string; result: string }[] = [
    { label: "Opening hours", result: timingStatus(stop, plan).text },
  ];
  for (const item of stop.constraints ?? []) {
    const result =
      item.status === "met"
        ? "Supported by retrieved text"
        : item.status === "unmet"
          ? "Retrieved text suggests otherwise"
          : item.status === "unknown"
            ? "Not confirmed by the retrieved listings"
            : "Does not apply to this stop";
    const label = constraintLabel(item.constraint, context).replaceAll("“", "").replaceAll("”", "");
    rows.push({ label: label.charAt(0).toUpperCase() + label.slice(1), result });
  }
  rows.push({
    label: "Official website",
    result: stop.website ? "Found" : "Not found in the listings",
  });
  return rows;
}

const FIELD_LABEL: Record<string, string> = {
  destination: "Destination",
  date: "Date",
  time: "Start time",
  intent: "Stops",
  preferences: "Preferences",
  "party size": "Party size",
  budget: "Budget",
  accessibility: "Accessibility",
};

export function fieldLabel(field: string): string {
  return FIELD_LABEL[field] ?? activityLabel(field);
}

function briefValue(brief: PlanningBrief, field: string): string | null {
  switch (field) {
    case "destination":
      return brief.destination_text;
    case "date":
      return brief.local_date
        ? formatDay(brief.local_date)
        : (brief.pending_date?.phrase.replaceAll("_", " ") ?? null);
    case "time":
      return brief.local_start ? formatClock(brief.local_start) : null;
    case "party size":
      return partyText(brief.party_size);
    case "budget":
      return budgetText(brief.budget);
    case "intent":
      return brief.intents.map((item) => activityLabel(item.kind, item.label)).join(" → ") || null;
    case "preferences":
      return brief.preferences.join(", ") || null;
    case "accessibility":
      return brief.accessibility_needs.join(", ") || null;
    default:
      return null;
  }
}

/** Readable added, removed, and changed rows for a refinement proposal. */
export function diffRows(proposal: RefinementProposal) {
  const rows: { kind: "Added" | "Removed" | "Changed"; text: string }[] = [];
  for (const field of proposal.diff.added) {
    const value = briefValue(proposal.proposed, field);
    rows.push({
      kind: "Added",
      text: value ? `${fieldLabel(field)}: ${value}` : fieldLabel(field),
    });
  }
  for (const field of proposal.diff.removed) {
    const value = briefValue(proposal.current, field);
    rows.push({
      kind: "Removed",
      text: value ? `${fieldLabel(field)} (was ${value})` : fieldLabel(field),
    });
  }
  for (const change of proposal.diff.changed) {
    const before = briefValue(proposal.current, change.field) ?? change.before ?? "none";
    const after = briefValue(proposal.proposed, change.field) ?? change.after ?? "none";
    rows.push({ kind: "Changed", text: `${fieldLabel(change.field)}: ${before} → ${after}` });
  }
  return rows;
}
