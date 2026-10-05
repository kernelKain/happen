import { describe, expect, it } from "vitest";
import type { PlanningBrief, RefinementProposal } from "../../lib/api/plan";
import {
  briefSummary,
  constraintLabel,
  diffRows,
  formatClock,
  formatDay,
  hoursView,
  unknownFieldLabel,
} from "./present";

const brief: PlanningBrief = {
  raw_prompt: "Coffee then a museum",
  destination_text: "Mexico City",
  plan_token: null,
  local_date: "2026-10-14",
  pending_date: null,
  local_start: "18:00:00",
  party_size: 2,
  budget: { amount: "50000", currency: "USD", tier: null, bound: "exact" },
  intents: [
    { kind: "coffee", label: "coffee", position: 1 },
    { kind: "museum", label: "museum", position: 2 },
  ],
  preferences: [],
  accessibility_needs: [],
  missing_essentials: [],
  ambiguities: [],
  confidence: "high",
};

describe("presentation", () => {
  it("formats destination-local times and dates without ISO strings", () => {
    expect(formatClock("18:00:00")).toBe("6:00 PM");
    expect(formatClock("00:30")).toBe("12:30 AM");
    expect(formatDay("2026-10-14")).toBe("Wed, Oct 14");
  });

  it("summarizes the brief compactly", () => {
    const summary = briefSummary(brief, null);
    expect(summary.where).toBe("Mexico City");
    expect(summary.when).toEqual(["Wed, Oct 14", "6:00 PM"]);
    expect(summary.details.join(" · ")).toBe("Coffee → Museum · 2 people · USD 50,000");
  });

  it("maps internal names to reader language", () => {
    expect(unknownFieldLabel("popular_times")).toBe("current crowd level");
    expect(constraintLabel("party size", { partySize: 2, currency: null })).toBe("seating for two");
    expect(constraintLabel("party size", { partySize: null, currency: null })).toBe(
      "space for your group",
    );
    expect(constraintLabel("budget", { partySize: null, currency: "usd" })).toBe("USD budget fit");
  });

  it("puts the planned weekday first and keeps the week behind it", () => {
    const view = hoursView(
      {
        evidence: [],
        weekly_hours: ["Thursday: 9 AM–5 PM", "Friday: 9 AM–5 PM", "Wednesday: 8 AM–9 PM"],
      } as never,
      "2026-10-14",
    );
    expect(view.today).toBe("Wednesday: 8 AM–9 PM");
    expect(view.week).toHaveLength(3);
  });

  it("describes a refinement with friendly labels and readable values", () => {
    const proposal = {
      current: brief,
      proposed: { ...brief, party_size: 4, local_start: "19:30:00", preferences: ["quiet"] },
      diff: {
        added: ["preferences"],
        removed: [],
        changed: [
          { field: "party size", before: "2", after: "4" },
          { field: "time", before: "18:00", after: "19:30" },
        ],
      },
    } as unknown as RefinementProposal;
    const text = diffRows(proposal).map((row) => `${row.kind} ${row.text}`);
    expect(text).toEqual([
      "Added Preferences: quiet",
      "Changed Party size: 2 people → 4 people",
      "Changed Start time: 6:00 PM → 7:30 PM",
    ]);
  });
});
