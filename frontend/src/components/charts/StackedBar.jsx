import { useTheme } from "../../features/theme/useTheme";
import { chartPalette } from "../../lib/viz";
import { ChartTooltip } from "./ChartTooltip";
import { useChartTooltip } from "./useChartTooltip";

// Part-to-whole as a single horizontal stacked bar, plus a labelled breakdown
// list beneath it.
//
// Horizontal because the category names are long ("31–60 days", "In
// progress") and would collide as column ticks. The bar carries proportion at
// a glance; the list under it carries the actual numbers as ordinary text —
// which is why no value is ever labelled *inside* a segment (a narrow segment
// would clip it, and clipping is worse than no label).
//
// Segments are separated by a 2px surface gap, never a stroke.

const GAP = 2;

export function StackedBar({
  segments,
  total,
  valueFormat,
  emptyMessage = "Nothing to show yet.",
}) {
  const { tip, show, hide } = useChartTooltip();
  const { isDark } = useTheme();
  const { chrome: CHROME } = chartPalette(isDark);

  if (!total) {
    return (
      <p className="py-8 text-center text-sm text-gray-500 dark:text-gray-400">{emptyMessage}</p>
    );
  }

  const visible = segments.filter((s) => s.value > 0);
  let offset = 0;

  return (
    <div className="relative">
      <div
        className="flex h-7 w-full overflow-hidden rounded-md"
        style={{ gap: `${GAP}px` }}
        role="img"
        aria-label={`Stacked bar: ${visible
          .map((s) => `${s.label} ${valueFormat(s.value)}`)
          .join(", ")}. The same figures are listed below.`}
      >
        {visible.map((s) => {
          const pct = (s.value / total) * 100;
          const mid = offset + pct / 2;
          offset += pct;
          const readout = {
            xPct: mid,
            yPct: 50,
            title: s.label,
            rows: [
              {
                label: `${Math.round((s.value / total) * 100)}% of total`,
                value: valueFormat(s.value),
                color: s.color,
              },
            ],
          };
          return (
            <button
              key={s.key}
              type="button"
              // flex-basis carries the proportion; min-width keeps a tiny
              // slice from vanishing entirely.
              style={{ flexBasis: `${pct}%`, backgroundColor: s.color, minWidth: 4 }}
              className="h-full shrink-0 transition-opacity hover:opacity-80 focus:outline-none
                focus-visible:ring-2 focus-visible:ring-indigo-600 focus-visible:ring-offset-1
                focus-visible:ring-offset-white dark:focus-visible:ring-offset-gray-900"
              aria-label={`${s.label}: ${valueFormat(s.value)}`}
              onPointerEnter={() => show(readout)}
              onPointerLeave={hide}
              onFocus={() => show(readout)}
              onBlur={hide}
            />
          );
        })}
      </div>

      {/* The breakdown: identity comes from the swatch beside the text, never
          from colouring the text itself. */}
      <ul className="mt-4 space-y-2">
        {segments.map((s) => (
          <li key={s.key} className="flex items-center gap-2 text-sm">
            {/* A short bar rather than a 10px dot: on an ordinal ramp the
                steps differ by lightness, and adjacent steps are genuinely
                hard to tell apart at dot size even though the ramp itself
                passes its contrast checks. More painted area makes the
                gradation readable. */}
            <span
              aria-hidden="true"
              className="h-3 w-4 shrink-0 rounded-sm"
              style={{ backgroundColor: s.color }}
            />
            <span className="min-w-0 flex-1 truncate text-gray-600 dark:text-gray-300">
              {s.label}
            </span>
            <span
              className="font-medium text-gray-900 dark:text-gray-100"
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {valueFormat(s.value)}
            </span>
          </li>
        ))}
      </ul>

      <div
        className="mt-3 flex items-center justify-between border-t pt-3 text-sm"
        style={{ borderColor: CHROME.grid }}
      >
        <span className="font-medium text-gray-600 dark:text-gray-400">Total</span>
        <span
          className="font-semibold text-gray-900 dark:text-gray-100"
          style={{ fontVariantNumeric: "tabular-nums" }}
        >
          {valueFormat(total)}
        </span>
      </div>

      <ChartTooltip tip={tip} />
    </div>
  );
}
