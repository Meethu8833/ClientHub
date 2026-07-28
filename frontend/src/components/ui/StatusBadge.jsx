import { Badge } from "./Badge";

// Badge + a constants map in one line (design doc §4.1). `map` is a
// { value: {label, color} } object from lib/constants — the label always
// renders next to the color, so color is never the only signal (§1.1 rule).
export function StatusBadge({ map, value }) {
  const entry = map[value] ?? { label: value, color: "gray" };
  return <Badge color={entry.color}>{entry.label}</Badge>;
}
