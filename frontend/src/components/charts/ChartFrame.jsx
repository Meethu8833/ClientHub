// Shared shell for every chart on the dashboard.
//
// Three jobs, all of them accessibility jobs:
//   1. gives the chart a title/subtitle that names what is plotted (so a
//      single-series chart needs no legend box — the title already says it);
//   2. renders the legend for >= 2 series, mirroring the mark (a rect for
//      bars/areas, a line for lines) so identity is never colour-alone;
//   3. carries the TABLE VIEW — the same numbers as real text. Tooltips
//      enhance, they never gate: everything hoverable is also readable here.
//      It is visually hidden but fully available to screen readers, and it is
//      what makes a colour-encoded chart WCAG-clean.

export function ChartFrame({
  title,
  subtitle,
  legend,
  tableCaption,
  tableHead,
  tableRows,
  children,
  className = "",
}) {
  return (
    <figure className={`flex h-full flex-col ${className}`}>
      <figcaption className="mb-4">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-50">{title}</h3>
        {subtitle && <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">{subtitle}</p>}
      </figcaption>

      {/* Legend sits above the plot: always present for two or more series. */}
      {legend?.length > 1 && (
        <ul className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1.5">
          {legend.map(({ label, color, shape = "rect" }) => (
            <li
              key={label}
              className="flex items-center gap-1.5 text-xs text-gray-600 dark:text-gray-300"
            >
              <span
                aria-hidden="true"
                className={shape === "line" ? "h-0.5 w-3.5 rounded-full" : "h-2.5 w-2.5 rounded-sm"}
                style={{ backgroundColor: color }}
              />
              {label}
            </li>
          ))}
        </ul>
      )}

      {/* w-full matters: as a flex child this box would otherwise shrink-wrap
          to the SVG's initial width, and the ResizeObserver would then just
          keep re-measuring that same width instead of the card's. */}
      <div className="min-h-0 w-full flex-1">{children}</div>

      {/* The WCAG-clean twin of the plot above. */}
      {tableRows?.length > 0 && (
        <table className="sr-only">
          <caption>{tableCaption ?? title}</caption>
          <thead>
            <tr>
              {tableHead.map((h) => (
                <th key={h} scope="col">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tableRows.map((row, i) => (
              <tr key={i}>
                {row.map((cell, j) =>
                  j === 0 ? (
                    <th key={j} scope="row">
                      {cell}
                    </th>
                  ) : (
                    <td key={j}>{cell}</td>
                  )
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </figure>
  );
}
