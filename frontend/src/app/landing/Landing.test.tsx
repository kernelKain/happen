// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PlanFetch } from "../../lib/api/planClient";
import { EXAMPLE_EVENINGS } from "./examples";
import { Landing } from "./Landing";

const original = "Dinner in Kyoto on 2026-10-05 at 7.";

const brief = {
  plan_token: "test-plan-token-0001",
  raw_prompt: original,
  destination_text: "Kyoto",
  local_date: "2026-10-05",
  pending_date: null,
  local_start: "19:00:00",
  party_size: 2,
  budget: null,
  intents: [
    { kind: "dinner", label: "dinner", position: 1 },
    { kind: "walk", label: "walk", position: 2 },
  ],
  preferences: ["quiet"],
  accessibility_needs: [],
  missing_essentials: [],
  ambiguities: [],
  confidence: "high",
};

const destination = {
  label: "Kyoto, Kyoto, Japan",
  source_text: "Kyoto",
  locality: "Kyoto",
  region: "Kyoto",
  country_code: "JP",
  timezone_name: "Asia/Tokyo",
  latitude: 35.01,
  longitude: 135.77,
  serpapi_location: "Kyoto,Kyoto,Japan",
  confidence: "high",
  resolution_source: "locations_api",
  provenance: null,
};

const resolved = {
  status: "resolved",
  destination,
  choices: [],
  billed_requests: 0,
  local_time: {
    date_status: "resolved",
    wall_status: "unique",
    local_date: "2026-10-05",
    local_start: "19:00:00",
    timezone_name: "Asia/Tokyo",
    offsets: ["+09:00"],
    date_candidates: [],
  },
};

const eveningPlan = {
  version: "2",
  outcome: "planned",
  local_date: "2026-10-05",
  local_start: "19:00:00",
  stops: [
    {
      position: 1,
      intent: "dinner",
      label: "dinner",
      name: "Kura",
      place_id: "kura",
      data_id: null,
      address: "Kyoto",
      latitude: 35.01,
      longitude: 135.77,
      maps_link: "https://maps.example/kura",
      website: null,
      confidence: "high",
      hours_status: "open",
      explanation: "Maps hours cover 19:00 on 2026-10-05.",
      evidence: [
        {
          source: "maps",
          text: "monday: 17:00-22:00",
          url: "https://maps.example/kura",
          retrieved_at: "2026-10-04T12:00:00Z",
        },
      ],
      unknown_fields: ["price"],
      warnings: [],
    },
  ],
  transition: null,
  warnings: [],
  retrieved_at: "2026-10-04T12:00:00Z",
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function interpreted(body: Record<string, unknown> = brief, followUp: unknown = null) {
  return {
    outcome: followUp ? "needs_follow_up" : "ready_for_retrieval",
    brief: body,
    destination: null,
    stops: [],
    follow_up: followUp,
    warnings: ["Live place retrieval has not run."],
  };
}

afterEach(() => {
  cleanup();
});

describe("landing", () => {
  it("leads with the promise, the composer, the chips, and the trust strip", () => {
    render(<Landing />);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Your evening, checked.");
    expect(screen.getByRole("textbox", { name: "Describe the evening" })).toHaveProperty(
      "maxLength",
      2000,
    );
    expect(screen.getByRole("button", { name: "Plan this evening" })).toBeTruthy();
    expect(screen.getByRole("list", { name: "Example evenings" })).toBeTruthy();
    // Three promises, stated in the reader's terms rather than in internals.
    expect(screen.getByText("Live places")).toBeTruthy();
    expect(screen.getByText("Checked timing")).toBeTruthy();
    expect(screen.getByText("Source-backed")).toBeTruthy();
    expect(document.querySelector(".mark")).toBeTruthy();
    expect(screen.getByText("Happen", { selector: ".wordmark" })).toBeTruthy();
  });

  it("keeps implementation detail out of the primary journey", () => {
    render(<Landing />);
    // Above the fold, nothing explains the implementation.
    const hero = document.querySelector(".landing-hero")?.textContent ?? "";
    expect(hero).not.toMatch(/SerpApi|Gemma|Python|model|fixture|repository|Indiranagar/i);
    // The headline carries no product-identity claim beyond the decision itself.
    expect(hero).not.toMatch(/itinerary|chatbot|assistant/i);
  });

  it("puts methodology behind an optional disclosure", () => {
    render(<Landing />);
    const toggle = screen.getByRole("button", { name: "How Happen decides" });
    expect(toggle).toHaveProperty("ariaExpanded", "false");
    // Nothing is shown until it is asked for.
    expect(screen.queryByText(/local deterministic parsing/)).toBeNull();
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Hide how Happen decides" })).toHaveProperty(
      "ariaExpanded",
      "true",
    );
    expect(screen.getByText(/local deterministic parsing/)).toBeTruthy();
    expect(screen.getByText(/Python checks feasibility and picks the stops/)).toBeTruthy();
    expect(screen.getByText(/missed its quality gates, so it stays switched off/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Hide how Happen decides" }));
    expect(screen.queryByText(/local deterministic parsing/)).toBeNull();
  });

  it("never tells a visitor that a model reads the request", () => {
    render(<Landing />);
    fireEvent.click(screen.getByRole("button", { name: "How Happen decides" }));
    const method = document.querySelector(".methodology")?.textContent ?? "";
    // The false sentence must not come back.
    expect(method).not.toMatch(/Gemma runs locally/);
    expect(method).not.toMatch(/Gemma reads/);
    expect(method).not.toMatch(/model reads the request/);
    // Nor may unused weights be implied to help the plan.
    expect(method).not.toMatch(/improves|stronger|better because/i);
  });

  it("keeps repository and implementation language off the visible page", () => {
    render(<Landing />);
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/repository|github|fixture|gguf|scoring|Indiranagar/i);
    expect(text).not.toMatch(/\bv1\b|\bv2\b/);
  });

  it("keeps the support sentence short", () => {
    render(<Landing />);
    const sentence = document.querySelector(".promise p")?.textContent ?? "";
    // One short sentence. A paragraph here would read as documentation.
    expect(sentence.length).toBeLessThanOrEqual(140);
    expect(sentence).not.toMatch(/\.\s+\S/);
  });

  it("offers exactly three concise example chips", () => {
    render(<Landing />);
    const chips = screen.getByRole("list", { name: "Example evenings" });
    const buttons = within(chips).getAllByRole("button");
    expect(buttons).toHaveLength(3);
    for (const button of buttons) {
      expect(button.textContent?.length ?? 0).toBeLessThanOrEqual(70);
    }
  });

  it("fills the composer from a chip without sending it", () => {
    const fetchImpl = vi.fn();
    render(<Landing fetchImpl={fetchImpl as PlanFetch} />);
    fireEvent.click(screen.getByRole("button", { name: EXAMPLE_EVENINGS[0] }));
    const field = screen.getByRole("textbox", { name: "Describe the evening" });
    expect(field).toHaveProperty("value", EXAMPLE_EVENINGS[0]);
    expect(screen.queryByRole("status")).toBeNull();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("reaches a chip, the composer, and the disclosure by keyboard alone", () => {
    render(<Landing />);
    // Every control in the primary journey is a real focusable element.
    for (const role of ["button", "textbox"] as const) {
      expect(screen.getAllByRole(role).length).toBeGreaterThan(0);
    }
    // A chip takes focus, fills the composer, and hands focus to the composer so
    // a keyboard user can start editing immediately.
    const chip = screen.getByRole("button", { name: EXAMPLE_EVENINGS[0] });
    chip.focus();
    expect(document.activeElement).toBe(chip);
    fireEvent.click(chip);
    expect(screen.getByRole("textbox", { name: "Describe the evening" })).toHaveProperty(
      "value",
      EXAMPLE_EVENINGS[0],
    );
    expect(document.activeElement).toBe(
      screen.getByRole("textbox", { name: "Describe the evening" }),
    );
    // The disclosure is reachable and reports its state to assistive tech.
    const toggle = screen.getByRole("button", { name: "How Happen decides" });
    toggle.focus();
    expect(document.activeElement).toBe(toggle);
    expect(toggle).toHaveProperty("ariaExpanded", "false");
  });

  it("fills the composer from an example without sending it", () => {
    const fetchImpl = vi.fn();
    render(<Landing fetchImpl={fetchImpl as PlanFetch} />);
    fireEvent.click(screen.getByRole("button", { name: EXAMPLE_EVENINGS[0] }));
    const field = screen.getByRole("textbox", { name: "Describe the evening" });
    expect(field).toHaveProperty("value", EXAMPLE_EVENINGS[0]);
    expect(screen.queryByRole("status")).toBeNull();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("asks for an evening before calling the backend", () => {
    const fetchImpl = vi.fn();
    render(<Landing fetchImpl={fetchImpl as PlanFetch} />);
    fireEvent.click(screen.getByRole("button", { name: "Plan this evening" }));
    expect(screen.getByRole("alert").textContent).toMatch(/Describe the evening/);
    expect(screen.queryByRole("status")).toBeNull();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("shows an editable brief and waits for Find the plan before searching", async () => {
    const calls: string[] = [];
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      calls.push(url);
      if (url.endsWith("/api/v2/briefs/interpret")) {
        return json(interpreted());
      }
      if (url.endsWith("/api/v2/destinations/resolve")) {
        return json(resolved);
      }
      if (url.endsWith("/api/v2/plans")) {
        return json(eveningPlan);
      }
      throw new Error(url);
    });
    render(<Landing initialEvening={original} fetchImpl={fetchImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Plan this evening" }));
    expect(await screen.findByRole("button", { name: "Find the plan" })).toBeTruthy();
    expect(screen.getByText(`Your words: ${original}`)).toBeTruthy();
    expect(screen.getByLabelText("Destination")).toHaveProperty("value", "Kyoto");
    expect(screen.getByLabelText("Local date")).toHaveProperty("value", "2026-10-05");
    expect(screen.getByLabelText("Local time")).toHaveProperty("value", "19:00");
    expect(screen.getByLabelText("Party size")).toHaveProperty("value", "2");
    expect(calls.some((url) => url.endsWith("/api/v2/plans"))).toBe(false);
    fireEvent.change(screen.getByLabelText("Party size"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("Destination"), { target: { value: "Osaka" } });
    expect(screen.queryByRole("button", { name: "Find the plan" })).toBeNull();
    expect(screen.getByRole("button", { name: "Check this place" })).toBeTruthy();
    expect(screen.getByText(`Your words: ${original}`)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Destination"), { target: { value: "Kyoto" } });
    fireEvent.click(screen.getByRole("button", { name: "Check this place" }));
    fireEvent.click(await screen.findByRole("button", { name: "Find the plan" }));
    expect(await screen.findByRole("heading", { name: "This evening" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "1. Kura" })).toBeTruthy();
    expect(calls.filter((url) => url.endsWith("/api/v2/plans"))).toHaveLength(1);
  });

  it("asks one follow-up and keeps the original prompt", async () => {
    const unnamed = {
      ...brief,
      destination_text: null,
      local_date: null,
      pending_date: { phrase: "tomorrow" },
      intents: [],
      preferences: [],
      party_size: null,
    };
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/v2/briefs/interpret")) {
        return json(
          interpreted(unnamed, {
            kind: "missing",
            field: "destination",
            question: "Which place should this evening be in?",
          }),
        );
      }
      if (url.endsWith("/api/v2/plans/refine")) {
        const body = JSON.parse(String(init?.body)) as { current: { raw_prompt: string } };
        expect(body.current.raw_prompt).toBe(original);
        return json({
          version: "2",
          applied: false,
          current: unnamed,
          proposed: { ...brief, raw_prompt: "Kyoto" },
          follow_up: null,
          diff: { added: ["destination"], removed: [], changed: [] },
          message: "The current plan was not changed.",
        });
      }
      if (url.endsWith("/api/v2/destinations/resolve")) {
        return json(resolved);
      }
      throw new Error(url);
    });
    render(<Landing initialEvening={original} fetchImpl={fetchImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Plan this evening" }));
    const question = await screen.findByLabelText("Which place should this evening be in?");
    expect(screen.queryByLabelText("What time should the evening start?")).toBeNull();
    fireEvent.change(question, { target: { value: "Kyoto" } });
    fireEvent.click(screen.getByRole("button", { name: "Answer" }));
    expect(await screen.findByText(`Your words: ${original}`)).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Find the plan" })).toBeTruthy();
    expect(fetchImpl.mock.calls.some((call) => String(call[0]).endsWith("/api/v2/plans"))).toBe(
      false,
    );
  });

  it("lets the user choose an ambiguous destination before searching", async () => {
    const calls: string[] = [];
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      calls.push(url);
      if (url.endsWith("/api/v2/briefs/interpret")) {
        return json(interpreted({ ...brief, destination_text: "London" }));
      }
      if (url.endsWith("/api/v2/destinations/resolve")) {
        return json(
          {
            status: "ambiguous",
            destination: null,
            choices: [
              { ...destination, label: "London, United Kingdom", timezone_name: "Europe/London" },
              {
                ...destination,
                label: "London, Ontario, Canada",
                timezone_name: "America/Toronto",
              },
            ],
            billed_requests: 0,
            local_time: null,
          },
          409,
        );
      }
      throw new Error(url);
    });
    render(<Landing initialEvening={original} fetchImpl={fetchImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Plan this evening" }));
    expect(await screen.findByRole("group", { name: "Which place did you mean?" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Find the plan" })).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: "London, United Kingdom" }));
    fireEvent.click(screen.getByRole("button", { name: "Use this place" }));
    expect(await screen.findByRole("button", { name: "Find the plan" })).toBeTruthy();
    expect(calls.some((url) => url.endsWith("/api/v2/plans"))).toBe(false);
  });

  it("does not start a second place search while one is running or after cancel", async () => {
    let planCalls = 0;
    let rejectPlan: (error: unknown) => void = () => {};
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/v2/briefs/interpret")) {
        return json(interpreted());
      }
      if (url.endsWith("/api/v2/destinations/resolve")) {
        return json(resolved);
      }
      planCalls += 1;
      return await new Promise<Response>((_resolve, reject) => {
        rejectPlan = reject;
        init?.signal?.addEventListener("abort", () => {
          reject(new DOMException("The operation was aborted.", "AbortError"));
        });
      });
    });
    render(<Landing initialEvening={original} fetchImpl={fetchImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Plan this evening" }));
    const find = await screen.findByRole("button", { name: "Find the plan" });
    fireEvent.click(find);
    fireEvent.click(find);
    expect(await screen.findByRole("status")).toHaveProperty("textContent", "Finding live places.");
    expect(planCalls).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    rejectPlan(new DOMException("The operation was aborted.", "AbortError"));
    expect(screen.queryByRole("heading", { name: "This evening" })).toBeNull();
    expect(planCalls).toBe(1);
    expect(screen.getByRole("button", { name: "Find the plan" })).toBeTruthy();
  });

  it("shows quota, timeout, unreachable, and no-result states without a stand-in plan", async () => {
    const quota = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v2/briefs/interpret")) {
        return json(interpreted());
      }
      if (url.endsWith("/api/v2/destinations/resolve")) {
        return json(resolved);
      }
      return json(
        {
          request_id: "req-1",
          contract_version: "2",
          error: {
            code: "QUOTA_EXHAUSTED",
            message: "The search allowance for this plan has been reached.",
            retryable: false,
            next_action: "Try again later.",
            fixture_available: true,
          },
        },
        503,
      );
    });
    const { unmount } = render(<Landing initialEvening={original} fetchImpl={quota} />);
    fireEvent.click(screen.getByRole("button", { name: "Plan this evening" }));
    fireEvent.click(await screen.findByRole("button", { name: "Find the plan" }));
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      expect.stringMatching(/search allowance/),
    );
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
    expect(document.body.textContent).not.toMatch(/fixture|captured evidence|sample plan/i);
    unmount();

    let planCalls = 0;
    const timeout = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v2/briefs/interpret")) {
        return json(interpreted());
      }
      if (url.endsWith("/api/v2/destinations/resolve")) {
        return json(resolved);
      }
      planCalls += 1;
      return json(
        {
          request_id: "req-2",
          contract_version: "2",
          error: {
            code: "TIMEOUT",
            message: "Live place evidence did not respond in time.",
            retryable: true,
            next_action: "Try again.",
            fixture_available: false,
          },
        },
        504,
      );
    });
    const second = render(<Landing initialEvening={original} fetchImpl={timeout} />);
    fireEvent.click(screen.getByRole("button", { name: "Plan this evening" }));
    fireEvent.click(await screen.findByRole("button", { name: "Find the plan" }));
    expect(await screen.findByText("Live place evidence did not respond in time.")).toBeTruthy();
    expect(planCalls).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(planCalls).toBe(2));
    second.unmount();

    const offline = vi.fn(async () => {
      throw new TypeError("offline");
    });
    render(<Landing initialEvening={original} fetchImpl={offline} />);
    fireEvent.click(screen.getByRole("button", { name: "Plan this evening" }));
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      expect.stringMatching(/could not be reached/),
    );
    expect(screen.queryByRole("heading", { name: "This evening" })).toBeNull();
    cleanup();

    const empty = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v2/briefs/interpret")) {
        return json(interpreted());
      }
      if (url.endsWith("/api/v2/destinations/resolve")) {
        return json(resolved);
      }
      return json({ ...eveningPlan, outcome: "no_results", stops: [], warnings: [] });
    });
    render(<Landing initialEvening={original} fetchImpl={empty} />);
    fireEvent.click(screen.getByRole("button", { name: "Plan this evening" }));
    fireEvent.click(await screen.findByRole("button", { name: "Find the plan" }));
    expect(await screen.findByText("No live places matched this evening.")).toBeTruthy();
    expect(screen.getByText(`Your words: ${original}`)).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "1. Kura" })).toBeNull();
  });

  it("reviews a change without replacing the plan until Apply", async () => {
    let planCalls = 0;
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/v2/briefs/interpret")) {
        return json(interpreted());
      }
      if (url.endsWith("/api/v2/destinations/resolve")) {
        return json(resolved);
      }
      if (url.endsWith("/api/v2/plans/refine")) {
        const body = JSON.parse(String(init?.body)) as { revision: string };
        return json({
          version: "2",
          applied: false,
          current: brief,
          proposed: { ...brief, raw_prompt: body.revision, preferences: ["quiet", "lively"] },
          follow_up: null,
          diff: {
            added: [],
            removed: [],
            changed: [{ field: "preferences", before: "quiet", after: "quiet, lively" }],
          },
          message: "The current plan was not changed.",
        });
      }
      planCalls += 1;
      return json(eveningPlan);
    });
    render(<Landing initialEvening={original} fetchImpl={fetchImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Plan this evening" }));
    fireEvent.click(await screen.findByRole("button", { name: "Find the plan" }));
    expect(await screen.findByRole("heading", { name: "1. Kura" })).toBeTruthy();
    expect(planCalls).toBe(1);
    fireEvent.change(screen.getByLabelText("Change this evening"), {
      target: { value: "Make it livelier" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Review this change" }));
    expect(await screen.findByRole("heading", { name: "Review the change" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "1. Kura" })).toBeTruthy();
    expect(screen.getByText(/Preferences: quiet to quiet, lively/)).toBeTruthy();
    // Reviewing alone must not recompute.
    expect(planCalls).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("heading", { name: "Review the change" })).toBeNull();
    expect(screen.getByRole("heading", { name: "1. Kura" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Change this evening"), {
      target: { value: "Make it livelier" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Review this change" }));
    await screen.findByRole("button", { name: "Apply" });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(await screen.findByRole("heading", { name: "This evening" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Review the change" })).toBeNull();
    // Apply recomputes from the server, so the plan request happens again.
    expect(planCalls).toBe(2);
  });

  it("sends the complete proposed brief to the server on Apply", async () => {
    const sent: Record<string, unknown>[] = [];
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/v2/briefs/interpret")) {
        return json(interpreted());
      }
      if (url.endsWith("/api/v2/destinations/resolve")) {
        return json(resolved);
      }
      if (url.endsWith("/api/v2/plans/refine")) {
        return json({
          version: "2",
          applied: false,
          current: brief,
          proposed: {
            ...brief,
            raw_prompt: "Make it quieter",
            preferences: ["quiet", "romantic"],
            party_size: 4,
          },
          follow_up: null,
          diff: {
            added: [],
            removed: [],
            changed: [{ field: "preferences", before: "quiet", after: "quiet, romantic" }],
          },
          message: "The current plan was not changed.",
        });
      }
      sent.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      return json(eveningPlan);
    });
    render(<Landing initialEvening={original} fetchImpl={fetchImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Plan this evening" }));
    fireEvent.click(await screen.findByRole("button", { name: "Find the plan" }));
    await screen.findByRole("heading", { name: "1. Kura" });
    fireEvent.change(screen.getByLabelText("Change this evening"), {
      target: { value: "Make it quieter" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Review this change" }));
    await screen.findByRole("button", { name: "Apply" });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(sent).toHaveLength(2));
    const recomputed = sent[1];
    expect(recomputed.preferences).toEqual(["quiet", "romantic"]);
    expect(recomputed.party_size).toBe(4);
    expect(recomputed.local_date).toBe("2026-10-05");
    expect(recomputed.local_start).toBe("19:00:00");
    expect(recomputed.intents).toHaveLength(2);
    expect(recomputed.accessibility_needs).toEqual([]);
  });

  it("keeps the previous plan when the recomputation fails", async () => {
    let planCalls = 0;
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v2/briefs/interpret")) {
        return json(interpreted());
      }
      if (url.endsWith("/api/v2/destinations/resolve")) {
        return json(resolved);
      }
      if (url.endsWith("/api/v2/plans/refine")) {
        return json({
          version: "2",
          applied: false,
          current: brief,
          proposed: { ...brief, raw_prompt: "Make it quieter", preferences: ["quiet", "spicy"] },
          follow_up: null,
          diff: { added: [], removed: [], changed: [] },
          message: "The current plan was not changed.",
        });
      }
      planCalls += 1;
      if (planCalls === 1) {
        return json(eveningPlan);
      }
      return json(
        {
          error: {
            code: "PLANNING_FAILED",
            message: "The plan could not be recomputed.",
            retryable: true,
            next_action: "Try again.",
          },
        },
        503,
      );
    });
    render(<Landing initialEvening={original} fetchImpl={fetchImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Plan this evening" }));
    fireEvent.click(await screen.findByRole("button", { name: "Find the plan" }));
    await screen.findByRole("heading", { name: "1. Kura" });
    fireEvent.change(screen.getByLabelText("Change this evening"), {
      target: { value: "Make it quieter" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Review this change" }));
    await screen.findByRole("button", { name: "Apply" });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    // The old plan is still on the page, and the brief was not advanced.
    expect(screen.getByRole("heading", { name: "1. Kura" })).toBeTruthy();
    expect(screen.getByLabelText("Preferences")).toHaveProperty("value", "quiet");
  });

  it("shows an honest result when a new preference cannot be verified", async () => {
    const unverified = {
      ...eveningPlan,
      outcome: "insufficient_evidence",
      stops: [
        {
          ...eveningPlan.stops[0],
          confidence: "low",
          constraints: [{ constraint: "romantic", status: "unknown", evidence: [] }],
        },
      ],
    };
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v2/briefs/interpret")) {
        return json(interpreted());
      }
      if (url.endsWith("/api/v2/destinations/resolve")) {
        return json(resolved);
      }
      if (url.endsWith("/api/v2/plans/refine")) {
        return json({
          version: "2",
          applied: false,
          current: brief,
          proposed: { ...brief, raw_prompt: "Make it romantic", preferences: ["romantic"] },
          follow_up: null,
          diff: { added: [], removed: [], changed: [] },
          message: "The current plan was not changed.",
        });
      }
      return json(unverified);
    });
    render(<Landing initialEvening={original} fetchImpl={fetchImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Plan this evening" }));
    fireEvent.click(await screen.findByRole("button", { name: "Find the plan" }));
    await screen.findByRole("heading", { name: "1. Kura" });
    fireEvent.change(screen.getByLabelText("Change this evening"), {
      target: { value: "Make it romantic" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Review this change" }));
    await screen.findByRole("button", { name: "Apply" });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(await screen.findByText(/romantic: unknown/)).toBeTruthy();
    expect(screen.getByLabelText("Preferences")).toHaveProperty("value", "romantic");
  });

  it("resolves the destination again when the change names another place", async () => {
    const osaka = {
      ...destination,
      label: "Osaka, Osaka, Japan",
      source_text: "Osaka",
      locality: "Osaka",
      serpapi_location: "Osaka,Osaka,Japan",
    };
    let resolveCalls = 0;
    let planCalls = 0;
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v2/briefs/interpret")) {
        return json(interpreted());
      }
      if (url.endsWith("/api/v2/destinations/resolve")) {
        resolveCalls += 1;
        return json(resolveCalls === 1 ? resolved : { ...resolved, destination: osaka });
      }
      if (url.endsWith("/api/v2/plans/refine")) {
        return json({
          version: "2",
          applied: false,
          current: brief,
          proposed: { ...brief, raw_prompt: "Move this to Osaka", destination_text: "Osaka" },
          follow_up: null,
          diff: { added: [], removed: [], changed: [] },
          message: "The current plan was not changed.",
        });
      }
      planCalls += 1;
      return json(eveningPlan);
    });
    render(<Landing initialEvening={original} fetchImpl={fetchImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Plan this evening" }));
    fireEvent.click(await screen.findByRole("button", { name: "Find the plan" }));
    await screen.findByRole("heading", { name: "1. Kura" });
    expect(resolveCalls).toBe(1);
    fireEvent.change(screen.getByLabelText("Change this evening"), {
      target: { value: "Move this to Osaka" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Review this change" }));
    await screen.findByRole("button", { name: "Apply" });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(planCalls).toBe(2));
    // The new place needs its own resolution before the plan can be requested.
    expect(resolveCalls).toBe(2);
    expect(screen.getByLabelText("Destination")).toHaveProperty("value", "Osaka");
  });
});

describe("refinement purposes on the page", () => {
  it("asks as a follow_up and as a plan_refinement, and applies with the new token", async () => {
    const refinements: Record<string, unknown>[] = [];
    const plans: Record<string, unknown>[] = [];
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
      if (url.endsWith("/api/v2/briefs/interpret")) {
        return json(interpreted());
      }
      if (url.endsWith("/api/v2/destinations/resolve")) {
        return json(resolved);
      }
      if (url.endsWith("/api/v2/plans/refine")) {
        refinements.push(body);
        const purpose = body.purpose as "follow_up" | "plan_refinement";
        return json({
          version: "2",
          applied: false,
          purpose,
          current: brief,
          proposed: {
            ...brief,
            raw_prompt: "Dinner in Kyoto on 2026-10-05 at 7pm",
            preferences: ["quiet"],
            // A follow-up keeps the plan it continues. An applied refinement is
            // a newly submitted plan, so the server issues it a new identity.
            plan_token: purpose === "follow_up" ? "test-plan-token-0001" : "replan-token-0002",
          },
          follow_up: null,
          diff: { added: ["preferences"], removed: [], changed: [] },
          message: "The current plan was not changed.",
        });
      }
      if (url.endsWith("/api/v2/plans")) {
        plans.push(body);
        return json(eveningPlan);
      }
      throw new Error(url);
    });

    const unnamed = {
      ...brief,
      destination_text: null,
      local_date: null,
      intents: [],
      missing_essentials: [
        { kind: "missing" as const, field: "destination" as const, question: "Which place?" },
      ],
    };
    const ask = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/v2/briefs/interpret")) {
        return json(
          interpreted(unnamed, {
            kind: "missing",
            field: "destination",
            question: "Which place should this evening be in?",
          }),
        );
      }
      return fetchImpl(input, init);
    });

    const { unmount } = render(<Landing initialEvening={original} fetchImpl={ask} />);
    fireEvent.click(screen.getByRole("button", { name: "Plan this evening" }));
    const question = await screen.findByLabelText("Which place should this evening be in?");
    fireEvent.change(question, { target: { value: "Kyoto" } });
    fireEvent.click(screen.getByRole("button", { name: "Answer" }));
    await waitFor(() => expect(refinements).toHaveLength(1));
    // Answering a question continues the current plan.
    expect(refinements[0].purpose).toBe("follow_up");
    unmount();

    render(<Landing initialEvening={original} fetchImpl={fetchImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Plan this evening" }));
    fireEvent.click(await screen.findByRole("button", { name: "Find the plan" }));
    await screen.findByRole("heading", { name: "1. Kura" });
    fireEvent.change(screen.getByLabelText("Change this evening"), {
      target: { value: "Make it quiet" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Review this change" }));
    await screen.findByRole("button", { name: "Apply" });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(plans).toHaveLength(2));
    // Reviewing a change after a result is a plan refinement, not a question.
    expect(refinements[1].purpose).toBe("plan_refinement");
    // And the retrieval runs on the plan the server issued for it.
    expect(plans[1].plan_token).toBe("replan-token-0002");
  });
});
