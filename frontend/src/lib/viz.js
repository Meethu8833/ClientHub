// Data-visualisation palette + helpers.
//
// These hex values are NOT eyeballed: every set below was run through the
// dataviz colour validator against this app's real chart surface (white
// cards, `#ffffff`) and only orderings that PASS every check are kept.
// Re-run the validator before changing any value here — the checks are
// lightness band, chroma floor, colour-blind (CVD) separation, normal-vision
// separation and contrast-vs-surface.
//
// Two results worth remembering, because both were caught by the validator
// and are invisible to the naked eye:
//
//   * green ↔ red are ADJACENT-UNSAFE (deutan ΔE 5.0 — the classic red/green
//     confusion). PROJECT_STATUS_SERIES is therefore ordered so those two are
//     never neighbours, which lifts the worst adjacent pair to ΔE 19.2.
//   * the invoice-aging ramp cannot hold FIVE distinct indigo steps: the 5th
//     is either too pale against white (< 2:1) or too close to its neighbour
//     (ΔL < 0.06). Hence four ramp steps for the four *overdue* buckets, with
//     "current" carried by a neutral grey — which is also the more honest
//     encoding, since not-yet-due is a different kind of thing from late.

// Two-series categorical. Semantic on purpose: resolved/collected is a good
// outcome, so it wears green. Worst adjacent CVD ΔE 31.7 — very safe.
export const SERIES_INDIGO = "#4f46e5"; // indigo-600
export const SERIES_GREEN = "#16a34a"; // green-600

// Project-status categorical, in validated ORDER (the order is the safety
// mechanism, not cosmetic). Keys mirror Project.Status on the backend.
//
// The dark column is NOT an automatic flip of the light one: it was re-stepped
// for the dark surface (#0f172a) and validated as its own set. Two results
// forced its shape — amber had to move from amber-500 to amber-600 (500 sits
// outside the dark lightness band), and green must not neighbour red, so the
// dark ORDER is green → amber → indigo → red. That order is the only one
// clearing the hard normal-vision floor; its worst adjacent CVD pair lands in
// the 6–8 warn band, which is legal here because the stacked bar carries
// secondary encoding (2px surface gaps + a fully labelled breakdown list).
export const PROJECT_STATUS_SERIES = {
  completed: { label: "Completed", color: "#16a34a", dark: "#16a34a" }, // green-600
  on_hold: { label: "On hold", color: "#f59e0b", dark: "#d97706" }, // amber-500 / -600
  in_progress: { label: "In progress", color: "#4f46e5", dark: "#6366f1" }, // indigo-600 / -500
  cancelled: { label: "Cancelled", color: "#dc2626", dark: "#ef4444" }, // red-600 / -500
  planned: { label: "Planned", color: "#64748b", dark: "#94a3b8" }, // slate (neutral)
};

// Invoice aging. `current` is neutral (not late); the four overdue buckets
// ride a validated single-hue ordinal ramp, darker = later.
//
// On dark the ramp is RE-STEPPED, not inverted: it still runs light→dark in
// the validator's sense, but starts lighter (indigo-300) so the pale end
// clears the dark surface instead of disappearing into it.
export const AGING_BUCKETS = [
  { key: "current", label: "Current", color: "#64748b", dark: "#94a3b8", overdue: false },
  { key: "days_1_30", label: "1–30 days", color: "#818cf8", dark: "#a5b4fc", overdue: true },
  { key: "days_31_60", label: "31–60 days", color: "#6366f1", dark: "#818cf8", overdue: true },
  { key: "days_61_90", label: "61–90 days", color: "#4338ca", dark: "#6366f1", overdue: true },
  { key: "days_over_90", label: "90+ days", color: "#312e81", dark: "#4f46e5", overdue: true },
];

// Chart chrome. Recessive by design — the data is the only loud thing.
export const CHROME_LIGHT = {
  grid: "#e5e7eb", // gray-200 hairline, solid (never dashed)
  axis: "#d1d5db", // gray-300 baseline
  label: "#6b7280", // gray-500 axis text
  surface: "#ffffff", // the gap/ring colour that separates touching marks
};

export const CHROME_DARK = {
  grid: "#1f2937", // gray-800
  axis: "#374151", // gray-700
  label: "#9ca3af", // gray-400 — still >= 4.5:1 on the dark surface
  surface: "#111827", // gray-900: matches the card the chart sits on, so the
  // 2px gaps and rings read as gaps, not as grey strokes
};

// Pick a palette for the active theme. Charts call this rather than importing
// a fixed CHROME, because their colours are SVG attributes — a `dark:` class
// can't reach them.
export function chartPalette(isDark) {
  return {
    chrome: isDark ? CHROME_DARK : CHROME_LIGHT,
    seriesIndigo: isDark ? "#6366f1" : SERIES_INDIGO,
    seriesGreen: isDark ? "#16a34a" : SERIES_GREEN,
    color: (entry) => (isDark ? (entry.dark ?? entry.color) : entry.color),
  };
}

// "2026-07" → "Jul". Charts label months, not ISO strings.
export function monthLabel(iso) {
  const [y, m] = iso.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-IN", { month: "short" });
}

// "2026-07" → "July 2026", for tooltips and the table view where there is room.
export function monthLabelLong(iso) {
  const [y, m] = iso.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-IN", { month: "long", year: "numeric" });
}

// Compact money for axis ticks: 1250000 → "₹12.5L". Indian units, because the
// app formats currency as INR everywhere else.
export function compactCurrency(n) {
  const v = Number(n) || 0;
  const abs = Math.abs(v);
  if (abs >= 1e7) return `₹${(v / 1e7).toFixed(abs >= 1e8 ? 0 : 1)}Cr`;
  if (abs >= 1e5) return `₹${(v / 1e5).toFixed(abs >= 1e6 ? 0 : 1)}L`;
  if (abs >= 1e3) return `₹${(v / 1e3).toFixed(0)}K`;
  return `₹${v}`;
}

// A "nice" axis maximum at/above the data max, so ticks land on round numbers
// (0 / 10 / 20) instead of 0 / 8.33 / 16.67.
export function niceMax(max) {
  if (!max || max <= 0) return 1;
  const pow = 10 ** Math.floor(Math.log10(max));
  const scaled = max / pow;
  const step = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 5 ? 5 : 10;
  return step * pow;
}
