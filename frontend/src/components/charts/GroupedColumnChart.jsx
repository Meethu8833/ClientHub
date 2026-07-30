import { useTheme } from "../../features/theme/useTheme";
import { chartPalette, niceMax } from "../../lib/viz";
import { ChartTooltip } from "./ChartTooltip";
import { useChartTooltip } from "./useChartTooltip";
import { useChartWidth } from "./useChartWidth";

// Grouped columns — two series compared per month (tickets opened vs
// resolved). Mark spec: columns capped at 24px thick (never filling the band —
// the leftover is air), 3px rounded cap at the data end, square at the
// baseline, with a 2px surface gap between the pair. Grid is a solid recessive
// hairline, never dashed.
//
// Drawn at the container's MEASURED width (see useChartWidth) so type stays a
// fixed size and only the plot stretches.

const H = 210;
const PAD = { top: 12, right: 12, bottom: 26, left: 40 };
const MAX_BAR = 24;
const GAP = 2; // the surface gap doing the separating

export function GroupedColumnChart({ data, series, valueFormat = (v) => v }) {
  const { tip, show, hide } = useChartTooltip();
  const [wrapRef, W] = useChartWidth();
  const { isDark } = useTheme();
  const { chrome: CHROME } = chartPalette(isDark);

  const plotW = Math.max(80, W - PAD.left - PAD.right);
  const plotH = H - PAD.top - PAD.bottom;
  const max = niceMax(Math.max(1, ...data.flatMap((d) => series.map((s) => d[s.key] ?? 0))));
  const band = plotW / Math.max(data.length, 1);
  const barW = Math.max(3, Math.min(MAX_BAR, (band * 0.62 - GAP) / series.length));
  const y = (v) => PAD.top + plotH - (v / max) * plotH;
  const ticks = [0, max / 2, max];

  const readout = (d, xPct) => ({
    xPct,
    yPct: 22,
    title: d.fullLabel ?? d.label,
    rows: series.map((s) => ({
      label: s.label,
      value: valueFormat(d[s.key] ?? 0),
      color: s.color,
    })),
  });

  return (
    <div className="relative w-full" ref={wrapRef}>
      <svg
        width={W}
        height={H}
        className="block max-w-full"
        role="img"
        aria-label={`Grouped column chart. ${series.map((s) => s.label).join(" and ")} per month. The same figures are in the table below.`}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(t)}
              y2={y(t)}
              stroke={t === 0 ? CHROME.axis : CHROME.grid}
              strokeWidth="1"
            />
            <text
              x={PAD.left - 8}
              y={y(t) + 4}
              textAnchor="end"
              fontSize="11"
              fill={CHROME.label}
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {Math.round(t)}
            </text>
          </g>
        ))}

        {data.map((d, i) => {
          const groupW = barW * series.length + GAP * (series.length - 1);
          const gx = PAD.left + band * i + (band - groupW) / 2;
          const xPct = ((gx + groupW / 2) / W) * 100;

          return (
            <g key={d.label}>
              {/* One hit target per month, taller and wider than the columns:
                  the reader aims at a month, never at a 6px bar. */}
              <rect
                x={PAD.left + band * i}
                y={PAD.top}
                width={band}
                height={plotH}
                fill="transparent"
                tabIndex={0}
                role="button"
                aria-label={`${d.fullLabel ?? d.label}: ${series
                  .map((s) => `${valueFormat(d[s.key] ?? 0)} ${s.label.toLowerCase()}`)
                  .join(", ")}`}
                className="cursor-default focus:outline-none focus-visible:ring-2
                  focus-visible:ring-indigo-600"
                onPointerEnter={() => show(readout(d, xPct))}
                onPointerLeave={hide}
                onFocus={() => show(readout(d, xPct))}
                onBlur={hide}
              />

              {series.map((s, si) => {
                const v = d[s.key] ?? 0;
                const h = Math.max(v > 0 ? 2 : 0, PAD.top + plotH - y(v));
                return (
                  <rect
                    key={s.key}
                    x={gx + si * (barW + GAP)}
                    y={PAD.top + plotH - h}
                    width={barW}
                    height={h}
                    rx="3"
                    fill={s.color}
                    className="pointer-events-none"
                  />
                );
              })}

              <text
                x={PAD.left + band * i + band / 2}
                y={H - 8}
                textAnchor="middle"
                fontSize="11"
                fill={CHROME.label}
                className="pointer-events-none"
              >
                {d.label}
              </text>
            </g>
          );
        })}
      </svg>
      <ChartTooltip tip={tip} />
    </div>
  );
}
