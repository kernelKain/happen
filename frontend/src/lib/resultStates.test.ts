import { describe, expect, it } from "vitest";
import { errorTitle, fieldLabel } from "./resultStates";

describe("result state copy", () => {
  it("names timeout, quota, model, fixture, and input failures", () => {
    expect(errorTitle("PROCESSING_TIMEOUT")).toBe("Request timed out");
    expect(errorTitle("SERPAPI_QUOTA_EXHAUSTED")).toBe("Search allowance reached");
    expect(errorTitle("MODEL_UNAVAILABLE")).toBe("Evidence model unavailable");
    expect(errorTitle("FIXTURE_NOT_AVAILABLE")).toBe("Captured evidence unavailable");
    expect(errorTitle("INVALID_INPUT")).toBe("These inputs are not valid");
    expect(errorTitle("UNMAPPED")).toBe("Happen could not finish");
  });

  it("labels planner fields and keeps unknown field names", () => {
    expect(fieldLabel("arrival_start")).toBe("Arrival from");
    expect(fieldLabel("priorities")).toBe("Priority order");
    expect(fieldLabel("visit_date")).toBe("visit_date");
  });
});
