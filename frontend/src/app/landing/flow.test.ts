import { describe, expect, it } from "vitest";
import type { PlanningBrief } from "../../lib/api/plan";
import {
  activeFollowUp,
  applyLocalTime,
  budgetIssue,
  busynessStatus,
  canFindPlan,
  constraintCopy,
  hoursCopy,
  moveIntent,
  needsAnotherSearch,
  needsRescore,
  partySizeIssue,
  preferenceIssue,
  priceStatus,
  ratingStatus,
  restorePrompt,
  shouldResolve,
  visibleWarning,
} from "./flow";

const brief: PlanningBrief = {
  raw_prompt: "Dinner in Kyoto tomorrow at 7",
  destination_text: "Kyoto",
  local_date: null,
  pending_date: { phrase: "tomorrow" },
  local_start: "19:00:00",
  party_size: null,
  budget: null,
  intents: [
    { kind: "dinner", label: "dinner", position: 1 },
    { kind: "walk", label: "walk", position: 2 },
  ],
  preferences: [],
  accessibility_needs: [],
  missing_essentials: [],
  ambiguities: [],
  confidence: "high",
};

describe("planning flow", () => {
  it("keeps the original prompt when a revision replaces it", () => {
    const restored = restorePrompt({ ...brief, raw_prompt: "Kyoto" }, brief.raw_prompt);
    expect(restored.raw_prompt).toBe("Dinner in Kyoto tomorrow at 7");
    expect(restored.destination_text).toBe("Kyoto");
  });

  it("asks one destination question and does not resolve an unnamed place", () => {
    const unnamed = { ...brief, destination_text: null };
    const followUp = activeFollowUp(unnamed, null, false);
    expect(followUp?.kind).toBe("missing");
    if (followUp?.kind === "missing") {
      expect(followUp.question).toBe("Which place should this evening be in?");
    }
    expect(shouldResolve(unnamed, null)).toBe(false);
    expect(activeFollowUp(brief, null, true)).toBeNull();
  });

  it("fills a missing local date without replacing an entered date", () => {
    const dated = applyLocalTime(brief, { local_date: "2026-10-05", local_start: "19:00:00" });
    expect(dated.local_date).toBe("2026-10-05");
    expect(dated.pending_date).toBeNull();
    const kept = applyLocalTime(
      { ...brief, local_date: "2026-11-01" },
      { local_date: "2026-10-05", local_start: "18:00:00" },
    );
    expect(kept.local_date).toBe("2026-11-01");
    expect(kept.local_start).toBe("19:00:00");
  });

  it("allows a place search only when the evening is ready and idle", () => {
    const destination = { timezone_name: "Asia/Tokyo" };
    expect(
      canFindPlan({
        destination,
        brief: { ...brief, local_date: "2026-10-05" },
        followUp: null,
        choosing: false,
        busy: false,
      }),
    ).toBe(true);
    expect(
      canFindPlan({
        destination,
        brief,
        followUp: {
          kind: "missing",
          field: "date",
          question: "Which date should this evening be?",
        },
        choosing: false,
        busy: false,
      }),
    ).toBe(false);
    expect(
      canFindPlan({
        destination: null,
        brief: { ...brief, local_date: "2026-10-05" },
        followUp: null,
        choosing: false,
        busy: false,
      }),
    ).toBe(false);
  });

  it("reorders intents and rejects an incomplete budget or party size", () => {
    const moved = moveIntent(brief.intents, 1, -1);
    expect(moved.map((item) => item.label)).toEqual(["walk", "dinner"]);
    expect(moved.map((item) => item.position)).toEqual([1, 2]);
    expect(partySizeIssue("0")).toMatch(/1 to 20/);
    expect(partySizeIssue("2")).toBeNull();
    expect(budgetIssue("40", "")).toMatch(/together/);
    expect(budgetIssue("40", "USD")).toBeNull();
    expect(preferenceIssue("quiet")).toBeNull();
  });

  it("rescores when a constraint changes and searches again when the evening changes", () => {
    const proposed = { ...brief, preferences: ["quiet"], local_date: "2026-10-05" as const };
    const current = { ...brief, local_date: "2026-10-05" as const };
    expect(needsAnotherSearch(current, proposed)).toBe(false);
    expect(needsRescore(current, proposed)).toBe(true);
    expect(needsRescore(current, { ...current, party_size: 4 })).toBe(true);
    expect(needsRescore(current, { ...current, accessibility_needs: ["step-free"] })).toBe(true);
    expect(
      needsRescore(current, {
        ...current,
        budget: { amount: "40", currency: "USD", tier: null, bound: "about" },
      }),
    ).toBe(true);
    expect(needsRescore(current, current)).toBe(false);
    expect(needsAnotherSearch(current, { ...current, local_start: "20:00:00" })).toBe(true);
    expect(needsAnotherSearch(current, { ...current, destination_text: "Osaka" })).toBe(true);
    expect(constraintCopy({ constraint: "quiet", status: "unknown" })).toMatch(/unknown/);
    expect(constraintCopy({ constraint: "quiet", status: "met" })).toMatch(/verified/);
    expect(constraintCopy({ constraint: "quiet", status: "not_applicable" })).toBeNull();
  });

  it("does not treat a missing price, rating, or crowd listing as a live fact", () => {
    const missing = {
      price: null,
      busyness: "unknown" as const,
      rating: null,
      unknown_fields: ["price", "popular_times"],
      hours_status: "unknown" as const,
    };
    expect(priceStatus(missing)).toBe("Price was not listed.");
    expect(busynessStatus(missing)).toBe("Busyness was not listed.");
    expect(ratingStatus(missing)).toBe("A rating was not listed.");
    expect(priceStatus({ ...missing, price: "$$", unknown_fields: ["popular_times"] })).toMatch(
      /not a live quote/,
    );
    expect(busynessStatus({ ...missing, busyness: "listed", unknown_fields: ["price"] })).toMatch(
      /not a live crowd/,
    );
  });

  it("does not claim a verified arrival for the second stop", () => {
    const open = {
      position: 1,
      price: null,
      busyness: "unknown" as const,
      rating: null,
      unknown_fields: [] as string[],
      hours_status: "open" as const,
    };
    expect(hoursCopy(open)).toBe("Opening hours cover this arrival.");
    expect(hoursCopy({ ...open, position: 2 })).toMatch(/separate arrival was not planned/);
    expect(hoursCopy({ ...open, position: 2 })).not.toMatch(/cover this arrival/);
    expect(hoursCopy({ ...open, hours_status: "unknown" })).toBe("Opening hours were not listed.");
  });

  it("hides stand-in plan notes", () => {
    expect(visibleWarning("Use captured evidence.")).toBe(false);
    expect(visibleWarning("Live place retrieval has not run.")).toBe(false);
    expect(visibleWarning("No live places matched this evening.")).toBe(true);
  });
});
