// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { EveningPlan } from "../../lib/api/plan";
import { EveningTimeline } from "./timeline";

const retrieved = "2026-10-04T12:00:00Z";

function plan(overrides: Partial<EveningPlan> = {}): EveningPlan {
  return {
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
        evidence: [
          {
            source: "official",
            text: "The dining room is open this evening.",
            url: "https://kura.example",
            retrieved_at: retrieved,
          },
          {
            source: "maps",
            text: "monday: 17:00-22:00",
            url: "https://maps.example/kura",
            retrieved_at: retrieved,
          },
          {
            source: "community",
            text: "Neighbors mention a quiet room.",
            url: null,
            retrieved_at: retrieved,
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

afterEach(() => {
  cleanup();
});

describe("evening timeline", () => {
  it("shows two stops, known listings, and keeps evidence closed", () => {
    render(<EveningTimeline plan={plan()} timezone="Asia/Tokyo" intentCount={2} />);
    expect(screen.getByRole("heading", { name: "1. Kura" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "2. River Path" })).toBeTruthy();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText(/Planned arrival 19:00 \(Asia\/Tokyo\)/)).toBeTruthy();
    expect(screen.getByText(/Price listed: \$\$/)).toBeTruthy();
    expect(screen.getByText(/not a live crowd count/)).toBeTruthy();
    expect(screen.getByText(/rating of 4.6/)).toBeTruthy();
    expect(screen.getByText("Price was not listed.")).toBeTruthy();
    expect(screen.getByText("Busyness was not listed.")).toBeTruthy();
    expect(screen.getByText("A rating was not listed.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Official site" })).toHaveProperty(
      "href",
      "https://kura.example/",
    );
    expect(screen.getByRole("link", { name: "Directions" })).toBeTruthy();
    expect(screen.getByText(/Travel time is not verified/)).toBeTruthy();
    expect(screen.queryByText("Neighbors mention a quiet room.")).toBeNull();
    fireEvent.click(screen.getAllByRole("button", { name: "Show evidence" })[0]);
    expect(screen.getByRole("heading", { name: "Official site" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Maps" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Community" })).toBeTruthy();
    expect(screen.getByText("Community statements are not live facts.")).toBeTruthy();
    expect(screen.getByText("Neighbors mention a quiet room.")).toBeTruthy();
  });

  it("marks incomplete, empty, and insufficient evenings without inventing a stop", () => {
    const partial = plan({
      stops: [plan().stops[1]],
      transition: null,
      warnings: ["No open place matched dinner."],
    });
    const { unmount } = render(
      <EveningTimeline plan={partial} timezone="Asia/Tokyo" intentCount={2} />,
    );
    expect(screen.getByText("The evidence for this evening is incomplete.")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "1. Kura" })).toBeNull();
    unmount();

    render(
      <EveningTimeline
        plan={plan({ outcome: "no_results", stops: [], transition: null })}
        timezone={null}
        intentCount={1}
      />,
    );
    expect(screen.getByText("No live places matched this evening.")).toBeTruthy();
    expect(screen.queryByRole("listitem")).toBeNull();
    cleanup();

    render(
      <EveningTimeline
        plan={plan({
          outcome: "insufficient_evidence",
          stops: [],
          transition: null,
          warnings: ["No open place had enough evidence for this evening."],
        })}
        timezone={null}
        intentCount={1}
      />,
    );
    expect(screen.getByText("The live evidence was not enough to choose a stop.")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: /Kura|River/ })).toBeNull();
  });
});
