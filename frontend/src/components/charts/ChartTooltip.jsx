// The hover/focus readout shared by every chart.
//
// Values lead and labels follow (the legend's hierarchy inverted): the reader
// already knows which series they are pointing at — they came for the number.
//
// Positioned in PERCENT of the plot box, so it follows the mark when the SVG
// scales responsively (viewBox units are not CSS pixels once the chart is
// fluid). `pointer-events-none` keeps it from stealing the hover it describes.
export function ChartTooltip({ tip }) {
  if (!tip) return null;

  // Flip to the left of the cursor near the right edge so the card never
  // overflows its container.
  const flip = tip.xPct > 62;

  return (
    <div
      role="presentation"
      // In dark mode the surface lifts to gray-800 and gains a hairline ring:
      // plain gray-900 would be the same colour as the card behind it and the
      // tooltip would read as floating text with no edge.
      className="pointer-events-none absolute z-10 min-w-[9rem] rounded-md bg-gray-900 px-2.5
        py-2 shadow-md dark:bg-gray-800 dark:ring-1 dark:ring-gray-700"
      style={{
        left: `${tip.xPct}%`,
        top: `${tip.yPct}%`,
        transform: `translate(${flip ? "calc(-100% - 10px)" : "10px"}, -50%)`,
      }}
    >
      <p className="mb-1 text-[11px] font-medium text-gray-300">{tip.title}</p>
      <ul className="space-y-0.5">
        {tip.rows.map(({ label, value, color }) => (
          <li key={label} className="flex items-baseline gap-1.5 whitespace-nowrap">
            {/* A short line-key, not a filled box: at tooltip density a box is
                data-weight ink doing a label's job. */}
            <span
              aria-hidden="true"
              className="h-0.5 w-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: color }}
            />
            <span className="text-xs font-semibold text-white">{value}</span>
            <span className="text-[11px] text-gray-400">{label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
