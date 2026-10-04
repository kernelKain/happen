// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PlanFetch } from "../../lib/api/planClient";
import { EXAMPLE_EVENINGS } from "./examples";
import { Landing } from "./Landing";

const original = "Dinner in Kyoto on 2026-10-05 at 7.";

const brief = {
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
  it("shows the promise, the composer, the steps, and the trust line", () => {
    render(<Landing />);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "One evening, held to two stops.",
    );
    expect(screen.getByRole("textbox", { name: "Describe the evening" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Plan this evening" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "How it works" })).toBeTruthy();
    expect(screen.getByText(/live SerpApi results/)).toBeTruthy();
    expect(screen.getByText(/Gemma runs locally/)).toBeTruthy();
    expect(document.querySelector(".mark")).toBeTruthy();
    expect(screen.getByText("Happen", { selector: ".wordmark" })).toBeTruthy();
  });

  it("keeps repository and implementation language off the page", () => {
    render(<Landing />);
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/repository|github|fixture|gguf|scoring|Indiranagar/i);
    expect(text).not.toMatch(/\bv1\b|\bv2\b/);
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

  it("reviews a change without replacing the plan until Apply, and skips a repeat search", async () => {
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
          proposed: { ...brief, raw_prompt: body.revision, preferences: ["quiet"] },
          follow_up: null,
          diff: {
            added: [],
            removed: [],
            changed: [{ field: "preferences", before: "quiet", after: "lively" }],
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
      target: { value: "Make it lively" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Review this change" }));
    expect(await screen.findByRole("heading", { name: "Review the change" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "1. Kura" })).toBeTruthy();
    expect(screen.getByText(/Preferences: quiet to lively/)).toBeTruthy();
    expect(planCalls).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("heading", { name: "Review the change" })).toBeNull();
    expect(screen.getByRole("heading", { name: "1. Kura" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Change this evening"), {
      target: { value: "Make it lively" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Review this change" }));
    await screen.findByRole("button", { name: "Apply" });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(screen.queryByRole("heading", { name: "Review the change" })).toBeNull();
    expect(screen.getByRole("heading", { name: "1. Kura" })).toBeTruthy();
    expect(planCalls).toBe(1);
  });
});
