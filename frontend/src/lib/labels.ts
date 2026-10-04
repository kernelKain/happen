const LABELS: Record<string, string> = {
  indiranagar: "Indiranagar",
  restaurants: "Restaurants",
  easier_conversation: "Easier conversation",
  conversation: "Easier conversation",
  short_wait: "Shorter waiting",
  seating: "Better seating",
};

export function labelFor(value: string): string {
  return LABELS[value] ?? value;
}

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
