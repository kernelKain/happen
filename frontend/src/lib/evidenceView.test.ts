import { describe, expect, it } from "vitest";
import { hasConflict, safeSourceUrl } from "./evidenceView";

describe("evidence view", () => {
  it("keeps ordinary web links and drops other addresses", () => {
    expect(safeSourceUrl("https://example.com/happen/source")).toBe(
      "https://example.com/happen/source",
    );
    expect(safeSourceUrl("javascript:alert(1)")).toBeNull();
    expect(safeSourceUrl("https://user:secret@example.com/place")).toBeNull();
    expect(safeSourceUrl("not a url")).toBeNull();
  });

  it("treats support beside a conflict as conflicting evidence", () => {
    expect(hasConflict(["positive"])).toBe(false);
    expect(hasConflict(["positive", "negative"])).toBe(true);
    expect(hasConflict(["positive", "mixed"])).toBe(true);
    expect(hasConflict(["negative"])).toBe(false);
  });
});
