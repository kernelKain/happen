import { describe, expect, it, vi } from "vitest";
import {
  contractMajor,
  LOCAL_PRESET,
  loadMetadata,
  metaSchema,
  SUPPORTED_CONTRACT_MAJOR,
} from "./meta";

const meta = {
  contract_version: "1.0.0",
  service_version: "0.1.0",
  supported_neighborhoods: ["indiranagar"],
  supported_categories: ["restaurants"],
  supported_experiences: ["easier_conversation"],
  priority_dimensions: ["conversation", "short_wait", "seating"],
  canonical_preset: LOCAL_PRESET,
  fixture_available: false,
  live_available: false,
  model_status: "not_loaded",
  planning_reader: "deterministic_parser",
  planner_model_in_request_path: false,
  scoring_policy_version: "v1",
  timezone: "Asia/Kolkata",
};

describe("metadata contract", () => {
  it("accepts the locked metadata shape and ignores additive fields", () => {
    const parsed = metaSchema.parse({ ...meta, future_field: "ignored" });
    expect(parsed.canonical_preset).toEqual(LOCAL_PRESET);
    expect(contractMajor(parsed.contract_version)).toBe(SUPPORTED_CONTRACT_MAJOR);
  });

  it("rejects a metadata document that omits the preset", () => {
    const { canonical_preset: _preset, ...incomplete } = meta;
    expect(() => metaSchema.parse(incomplete)).toThrow();
  });

  it("retries once and then fails without returning a partial document", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () => {
      throw new Error("offline");
    });
    const sleep = vi.fn(async () => undefined);
    await expect(
      loadMetadata(fetchImpl, { origin: "http://127.0.0.1:8000", retryDelayMs: 1000, sleep }),
    ).rejects.toThrow("offline");
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(sleep).toHaveBeenCalledWith(1000);
  });
});
