/** Return an http(s) source URL, or null when the address is not safe to open. */
export function safeSourceUrl(value: string): string | null {
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return null;
    }
    if (url.username !== "" || url.password !== "") {
      return null;
    }
    return url.toString();
  } catch {
    return null;
  }
}

/** Report a priority whose accepted quotes both support and conflict. */
export function hasConflict(polarities: readonly string[]): boolean {
  const seen = new Set(polarities);
  const supports = seen.has("positive");
  const conflicts = seen.has("negative") || seen.has("mixed");
  return supports && conflicts;
}
