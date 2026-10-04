const LABELS: Record<string, string> = {
  indiranagar: "Indiranagar",
  restaurants: "Restaurants",
  easier_conversation: "Easier conversation",
  conversation: "Easier conversation",
  short_wait: "Shorter waiting",
  seating: "Better seating",
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
