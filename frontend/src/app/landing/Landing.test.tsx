// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { EXAMPLE_EVENINGS } from "./examples";
import { Landing } from "./Landing";

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

  it("fills the composer from an example without inventing a place", () => {
    render(<Landing />);
    fireEvent.click(screen.getByRole("button", { name: EXAMPLE_EVENINGS[0] }));
    const field = screen.getByRole("textbox", { name: "Describe the evening" });
    expect(field).toHaveProperty("value", EXAMPLE_EVENINGS[0]);
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("asks for an evening before holding one", () => {
    render(<Landing />);
    fireEvent.click(screen.getByRole("button", { name: "Plan this evening" }));
    expect(screen.getByRole("alert").textContent).toMatch(/Describe the evening/);
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("holds the written evening and does not retrieve a plan", () => {
    render(<Landing initialEvening="Dinner in Kyoto tomorrow at 7." />);
    fireEvent.click(screen.getByRole("button", { name: "Plan this evening" }));
    expect(screen.getByRole("status").textContent).toMatch(/Dinner in Kyoto tomorrow at 7/);
    expect(screen.queryByRole("article")).toBeNull();
  });
});
