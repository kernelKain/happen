import { z } from "zod";

export const SUPPORTED_CONTRACT_MAJOR = 1;

export const canonicalPresetSchema = z.object({
  neighborhood: z.string().min(1),
  restaurant_category: z.string().min(1),
  arrival_start: z.string().regex(/^\d{2}:\d{2}$/),
  arrival_end: z.string().regex(/^\d{2}:\d{2}$/),
  desired_experience: z.string().min(1),
  priorities: z.array(z.string().min(1)).length(3),
});

export const metaSchema = z.object({
  contract_version: z.string().min(1),
  service_version: z.string().min(1),
  supported_neighborhoods: z.array(z.string().min(1)).min(1),
  supported_categories: z.array(z.string().min(1)).min(1),
  supported_experiences: z.array(z.string().min(1)).min(1),
  priority_dimensions: z.array(z.string().min(1)).length(3),
  canonical_preset: canonicalPresetSchema,
  fixture_available: z.boolean(),
  live_available: z.boolean(),
  model_status: z.enum(["not_loaded", "loading", "ready", "unavailable"]),
  scoring_policy_version: z.string().min(1),
  timezone: z.string().min(1),
});

export type CanonicalPreset = z.infer<typeof canonicalPresetSchema>;
export type ServiceMeta = z.infer<typeof metaSchema>;

export const LOCAL_PRESET: CanonicalPreset = {
  neighborhood: "indiranagar",
  restaurant_category: "restaurants",
  arrival_start: "18:00",
  arrival_end: "21:00",
  desired_experience: "easier_conversation",
  priorities: ["conversation", "short_wait", "seating"],
};

/** Return the numeric first version component, or null when it contains nondigits. */
export function contractMajor(version: string): number | null {
  const major = version.split(".")[0] ?? "";
  if (!/^\d+$/.test(major)) {
    return null;
  }
  return Number(major);
}

/** Return the configured HTTP(S) origin or an empty same-origin prefix; reject invalid URLs. */
export function apiOrigin(configured = import.meta.env.VITE_API_BASE_URL): string {
  const value = configured?.trim() ?? "";
  if (!value) {
    return "";
  }
  const url = new URL(value);
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("API base URL must use http or https");
  }
  return url.origin;
}

/** Build the metadata endpoint URL from the supplied or configured API origin. */
export function metaUrl(origin = apiOrigin()): string {
  return `${origin}/api/v1/meta`;
}

type Sleep = (milliseconds: number) => Promise<void>;

/** Resolve after the requested delay without blocking the event loop. */
const defaultSleep: Sleep = (milliseconds) =>
  new Promise((resolve) => {
    setTimeout(resolve, milliseconds);
  });

/** Fetch and validate metadata with a three-second timeout per attempt and one delayed retry. */
export async function loadMetadata(
  fetchImpl: typeof fetch = fetch,
  options: { origin?: string; retryDelayMs?: number; sleep?: Sleep } = {},
): Promise<ServiceMeta> {
  const url = metaUrl(options.origin ?? apiOrigin());
  const sleep = options.sleep ?? defaultSleep;
  const retryDelayMs = options.retryDelayMs ?? 1000;
  let lastError: unknown;

  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const response = await fetchImpl(url, {
        headers: { Accept: "application/json" },
        signal: AbortSignal.timeout(3000),
      });
      if (!response.ok) {
        throw new Error(`metadata status ${response.status}`);
      }
      return metaSchema.parse(await response.json());
    } catch (error) {
      lastError = error;
      if (attempt === 0) {
        await sleep(retryDelayMs);
      }
    }
  }

  throw lastError instanceof Error ? lastError : new Error("metadata unavailable");
}
