// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import type { EveningPlan, PlanningBrief, ResolvedDestination } from "../../lib/api/plan";
import { EveningTimeline, SourcesPanel } from "./timeline";

const retrieved = "2026-10-04T12:00:00Z";

function plan(overrides: Partial<EveningPlan> = {}): EveningPlan {
  return {
    version: "2",
    outcome: "planned",
    local_date: "2026-10-05",
    local_start: "19:00:00",
    party_size: 2,
    billed_requests: 3,
    remaining_requests: 5,
    stops: [
      {
        position: 1,
        intent: "dinner",
        label: "dinner",
        name: "Kura",
        place_id: "kura",
        data_id: null,
        address: "Kyoto",
        latitude: 35,
        longitude: 135.7,
        maps_link: "https://maps.example/kura",
        website: "https://kura.example",
        confidence: "high",
        hours_status: "open",
        price: "$$",
        busyness: "listed",
        rating: 4.6,
        explanation: "Maps hours cover 19:00 on 2026-10-05.",
        constraints: [
          {
            constraint: "quiet",
            status: "met" as const,
            evidence: [
              {
                source: "community" as const,
                text: "Neighbors mention a quiet room.",
                url: null,
                retrieved_at: retrieved,
                field: "constraint" as const,
                matched_by: "name_and_location" as const,
                verification: "unverified" as const,
              },
            ],
          },
          { constraint: "wheelchair access", status: "unknown" as const, evidence: [] },
        ],
        components: [
          {
            name: "hours",
            result: "supports" as const,
            detail: "Hours: opening hours cover this arrival.",
          },
        ],
        evidence: [
          {
            source: "official",
            text: "The dining room is open this evening.",
            url: "https://kura.example",
            retrieved_at: retrieved,
            field: "description" as const,
            matched_by: "official_domain" as const,
            verification: "verified" as const,
          },
          {
            source: "maps",
            text: "monday: 17:00-22:00",
            url: "https://maps.example/kura",
            retrieved_at: retrieved,
            field: "hours" as const,
            matched_by: "place_record" as const,
            verification: "verified" as const,
          },
          {
            source: "community",
            text: "Neighbors mention a quiet room.",
            url: null,
            retrieved_at: retrieved,
            field: "description" as const,
            matched_by: "name_and_location" as const,
            verification: "unverified" as const,
          },
        ],
        unknown_fields: [],
        warnings: [],
      },
      {
        position: 2,
        intent: "walk",
        label: "walk",
        name: "River Path",
        place_id: "path",
        data_id: null,
        address: null,
        latitude: 35.1,
        longitude: 135.8,
        maps_link: null,
        website: null,
        confidence: "low",
        hours_status: "unknown",
        price: null,
        busyness: "unknown",
        rating: null,
        explanation: "Opening hours were not listed, so this stop is less certain.",
        constraints: [],
        components: [],
        evidence: [],
        unknown_fields: ["price", "popular_times"],
        warnings: [],
      },
    ],
    transition: {
      from_stop: 1,
      to_stop: 2,
      status: "unverified",
      directions_url: "https://www.google.com/maps/dir/?api=1&origin=Kura&destination=River",
    },
    warnings: [],
    retrieved_at: retrieved,
    ...overrides,
  };
}

const destination: ResolvedDestination = {
  label: "Kyoto, Kyoto, Japan",
  source_text: "Kyoto",
  locality: "Kyoto",
  region: "Kyoto",
  country_code: "JP",
  timezone_name: "Asia/Tokyo",
  latitude: 35,
  longitude: 135.7,
  serpapi_location: "Kyoto,Kyoto,Japan",
  confidence: "high",
  resolution_source: "locations_api",
  provenance: null,
};

const brief: PlanningBrief = {
  raw_prompt: "Dinner in Kyoto",
  destination_text: "Kyoto",
  plan_token: null,
  local_date: "2026-10-05",
  pending_date: null,
  local_start: "19:00:00",
  party_size: 2,
  budget: { amount: "50000", currency: "USD", tier: null, bound: "about" },
  intents: [
    { kind: "dinner", label: "dinner", position: 1 },
    { kind: "walk", label: "walk", position: 2 },
  ],
  preferences: ["quiet"],
  accessibility_needs: ["wheelchair access"],
  missing_essentials: [],
  ambiguities: [],
  confidence: "high",
};

function Harness({ value }: { value: EveningPlan }) {
  const [selected, setSelected] = useState<number | null>(null);
  const stop = value.stops.find((item) => item.position === selected) ?? null;
  return (
    <>
      <EveningTimeline
        plan={value}
        brief={brief}
        destination={destination}
        intentCount={2}
        sourcesId="sources"
        selectedStop={selected}
        onViewSources={setSelected}
      />
      {stop ? (
        <SourcesPanel
          id="sources"
          stop={stop}
          plan={value}
          brief={brief}
          timezone="Asia/Tokyo"
          onClose={() => setSelected(null)}
        />
      ) : null}
    </>
  );
}

const RAW = /\b[a-z]+_[a-z_]+\b|not_applicable|\d{4}-\d{2}-\d{2}T/;

afterEach(() => {
  cleanup();
});

describe("evening timeline", () => {
  it("reads as an itinerary with a timed first stop and an honest second stop", () => {
    render(<Harness value={plan()} />);
    expect(screen.getByRole("heading", { name: "Your Monday evening in Kyoto" })).toBeTruthy();
    expect(
      screen.getByText("Two stops · Starts at 7:00 PM · Live listings checked through SerpApi"),
    ).toBeTruthy();
    const items = screen.getAllByRole("listitem").filter((item) => item.classList.contains("stop"));
    expect(items).toHaveLength(2);
    const first = within(items[0] as HTMLElement);
    expect(first.getByRole("heading", { name: "Kura" })).toBeTruthy();
    expect(first.getByText("7:00 PM").getAttribute("datetime")).toBe("19:00");
    expect(first.getByText("Open at your planned arrival")).toBeTruthy();
    expect(first.getByText("Opening hours cover 7:00 PM.")).toBeTruthy();
    expect(first.getByText("An official website was found.")).toBeTruthy();
    expect(first.getByText("Retrieved text supports “quiet”.")).toBeTruthy();
    expect(first.getByText(/Maps rating 4.6/)).toBeTruthy();
    expect(first.getByText(/Price level \$\$/)).toBeTruthy();
    expect(first.getByText(/“wheelchair access”/)).toBeTruthy();
    const second = within(items[1] as HTMLElement);
    expect(second.getByRole("heading", { name: "River Path" })).toBeTruthy();
    expect(second.getByText("Then")).toBeTruthy();
    expect(second.queryByText("Open at your planned arrival")).toBeNull();
    expect(
      second.getByText(/Exact arrival is not calculated because travel time is unavailable/),
    ).toBeTruthy();
    expect(second.getByRole("link", { name: "Open directions between stops" })).toBeTruthy();
    expect(second.getByText(/price or current crowd level\./)).toBeTruthy();
    expect(screen.getAllByText("Couldn't confirm:")).toHaveLength(2);
    // Evidence stays out of the primary path until it is asked for.
    expect(screen.queryByText("Neighbors mention a quiet room.")).toBeNull();
    expect(document.body.textContent).not.toMatch(RAW);
    expect(document.body.textContent).not.toMatch(/Unknown:|popular times|hours_/);
  });

  it("never claims a calculated arrival for a second stop that is open", () => {
    const base = plan();
    const [first, second] = base.stops;
    const value = plan({
      stops: [
        first as EveningPlan["stops"][number],
        {
          ...(second as EveningPlan["stops"][number]),
          hours_status: "open",
          arrival_planned: false,
          closes_at: "19:30:00",
          hours_reason: "hours_covers_arrival",
        },
      ],
    });
    render(<Harness value={value} />);
    expect(screen.getAllByText("Open at your planned arrival")).toHaveLength(1);
    expect(screen.getByText("Listed open until 7:30 PM")).toBeTruthy();
    expect(screen.getByText("Listed hours include 7:00 PM on Monday.")).toBeTruthy();
  });

  it("opens sources with the planned day first, deduplicated links, and labelled community text", () => {
    const base = plan();
    const kura = base.stops[0] as EveningPlan["stops"][number];
    const value = plan({
      stops: [
        {
          ...kura,
          hours_for_day: "Monday: 6:00 PM–11:00 PM",
          weekly_hours: [
            "Thursday: 9:00 AM–5:00 PM",
            "Friday: 9:00 AM–5:00 PM",
            "Saturday: 9:00 AM–5:00 PM",
            "Monday: 6:00 PM–11:00 PM",
          ],
          evidence: [
            ...kura.evidence,
            {
              source: "maps",
              text: "Listed on Maps.",
              url: "https://maps.example/kura",
              retrieved_at: retrieved,
              field: "place_identity",
              matched_by: "provider_id",
              verification: "verified",
            },
          ],
        },
      ],
    });
    render(<Harness value={value} />);
    const toggle = screen.getByRole("button", { name: /View sources/ });
    expect(toggle).toHaveProperty("ariaExpanded", "false");
    expect(toggle.getAttribute("aria-controls")).toBe("sources");
    fireEvent.click(toggle);
    expect(toggle).toHaveProperty("ariaExpanded", "true");
    const panel = screen.getByRole("complementary", { name: "Sources for Kura" });
    expect(document.activeElement).toBe(within(panel).getByRole("heading", { level: 2 }));
    for (const name of ["What was checked", "Sources", "What remains unknown", "Opening hours"]) {
      expect(within(panel).getByRole("heading", { name })).toBeTruthy();
    }
    expect(
      within(panel).getByText(/^Place information was retrieved through SerpApi/),
    ).toBeTruthy();
    const today = panel.querySelector(".hours-today")?.textContent ?? "";
    expect(today).toBe("Monday, your planned day: 6:00 PM–11:00 PM");
    expect(within(panel).getByText("Full weekly hours")).toBeTruthy();
    // The Maps link appears once in the default view even though two claims cite it.
    expect(within(panel).getAllByRole("link", { name: "Open the Maps listing" })).toHaveLength(1);
    expect(within(panel).getByRole("heading", { name: "Community text" })).toBeTruthy();
    expect(within(panel).getByText(/Unverified context/)).toBeTruthy();
    expect(within(panel).getAllByText("Neighbors mention a quiet room.").length).toBeGreaterThan(0);
    // The plan-level retrieval time is shown once; claim times live in the audit.
    expect(document.querySelectorAll(".plan-meta time")).toHaveLength(1);
    expect(panel.querySelectorAll(".audit time").length).toBeGreaterThan(0);
    expect(document.body.textContent).not.toMatch(RAW);
    fireEvent.click(within(panel).getByRole("button", { name: "Close sources" }));
    expect(screen.queryByRole("complementary", { name: "Sources for Kura" })).toBeNull();
  });

  it("states partial, empty, and insufficient evenings without inventing a stop", () => {
    const partial = plan();
    const { unmount } = render(<Harness value={partial} />);
    expect(
      screen.getByText(
        "We found a usable plan, but some requested details could not be confirmed.",
      ),
    ).toBeTruthy();
    unmount();
    const empty = render(
      <Harness value={plan({ outcome: "no_results", stops: [], transition: null })} />,
    );
    expect(screen.getByText("No live places matched this evening.")).toBeTruthy();
    expect(screen.queryAllByRole("heading", { level: 3 })).toHaveLength(0);
    empty.unmount();
    render(
      <Harness
        value={plan({
          outcome: "insufficient_evidence",
          stops: [],
          transition: null,
          warnings: ["No open place had enough evidence for this evening."],
        })}
      />,
    );
    expect(
      screen.getByText(
        "We couldn't verify enough information to recommend a stop for this evening.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText("No open place had enough evidence for this evening.")).toBeNull();
  });
});
