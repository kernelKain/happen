const LABELS: Record<string, string> = {
  indiranagar: "Indiranagar",
  restaurants: "Restaurants",
  easier_conversation: "Easier conversation",
  conversation: "Easier conversation",
  short_wait: "Shorter waiting",
  seating: "Better seating",
  strong: "Strong",
  possible: "Possible",
  weak: "Weak",
  unknown: "Unknown",
  high: "High",
  medium: "Medium",
  low: "Low",
  insufficient: "Insufficient",
  positive: "Supports",
  negative: "Conflicts",
  mixed: "Mixed",
  synthetic_development: "Synthetic development",
  captured_fixture: "Captured fixture",
  mid_evening: "Mid evening",
};

/** Return a display label for a known identifier, preserving unknown identifiers. */
export function labelFor(value: string): string {
  return LABELS[value] ?? value;
}

/** Copy and move an item one position; return the original array if the move is invalid. */
export function moveItem(values: string[], index: number, direction: -1 | 1): string[] {
  const target = index + direction;
  if (target < 0 || target >= values.length) {
    return values;
  }
  const next = [...values];
  const [item] = next.splice(index, 1);
  if (!item) {
    return values;
  }
  next.splice(target, 0, item);
  return next;
}

/** Format an HH:mm time using AM or PM, preserving inputs with noninteger parts. */
export function formatClock(value: string): string {
  const [hourText, minuteText] = value.split(":");
  const hour = Number(hourText);
  const minute = Number(minuteText);
  if (!Number.isInteger(hour) || !Number.isInteger(minute)) {
    return value;
  }
  const suffix = hour >= 12 ? "PM" : "AM";
  const hour12 = hour % 12 || 12;
  return `${hour12}:${minuteText} ${suffix}`;
}
