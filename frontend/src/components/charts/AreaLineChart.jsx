import { useTheme } from "../../features/theme/useTheme";
import { chartPalette, niceMax } from "../../lib/viz";
import { ChartTooltip } from "./ChartTooltip";
import { useChartTooltip } from "./useChartTooltip";
import { useChartWidth } from "./useChartWidth";

// Single-series trend over time (net revenue per month).
//
// One series, so: no legend box (the title names what is plotted), the fill
// is a ~10% wash rather than a saturated block, the line is 2px with round
// joins, and only the LAST point is marked — a number on every point is chaos
// and goes unread. A crosshair snaps to the nearest month so the reader aims
// at a date, not at a 2px line.
//
// Drawn at the container's MEASURED width (see useChartWidth) rather than a
// scaled viewBox: type stays a fixed size at any card width, and only the
// plot stretches.

const H = 210;
const PAD = { top: 16, right: 16, bottom: 26, left: 52 };

export function AreaLineChart({ data, color, tickFormat, valueFormat }) {
  const { tip, show, hide } = useChartTooltip();
  const [wrapRef, W] = useChartWidth();
  const { isDark } = useTheme();
  // SVG fills/strokes are attributes, so `dark:` classes cannot reach them —
  // the palette has to be chosen in JS.
  const { chrome: CHROME } = chartPalette(isDark);

  const plotW = Math.max(80, W - PAD.left - PAD.right);
  const plotH = H - PAD.top - PAD.bottom;
  const max = niceMax(Math.max(1, ...data.map((d) => d.value)));
  const stepX = data.length > 1 ? plotW / (data.length - 1) : 0;
  const x = (i) => PAD.left + i * stepX;
  const y = (v) => PAD.top + plotH - (Math.max(v, 0) / max) * plotH;
  const ticks = [0, max / 2, max];

  const line = data.map((d, i) => `${i ? "L" : "M"}${x(i)},${y(d.value)}`).join(" ");
  const area = `${line} L${x(data.length - 1)},${PAD.top + plotH} L${x(0)},${PAD.top + plotH} Z`;

  const focusPoint = (i) => {
    const d = data[i];
    show({
      xPct: (x(i) / W) * 100,
      yPct: (y(d.value) / H) * 100,
      title: d.fullLabel ?? d.label,
      rows: [{ label: d.seriesLabel, value: valueFormat(d.value), color }],
    });
  };

  // Snap to the nearest month from the pointer's x — the reader never has to
  // land on the line itself.
  const onMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const rel = e.clientX - rect.left;
    const i = Math.max(0, Math.min(data.length - 1, Math.round((rel - PAD.left) / (stepX || 1))));
    focusPoint(i);
  };

  const last = data[data.length - 1];
  // Thin out month labels when the axis gets crowded (12 months on a phone).
  const labelEvery = Math.ceil((data.length * 34) / Math.max(plotW, 1));

  return (
    <div className="relative w-full" ref={wrapRef}>
      <svg
        width={W}
        height={H}
        className="block max-w-full"
        role="img"
        aria-label={`Line chart of ${last?.seriesLabel ?? "value"} per month. The same figures are in the table below.`}
        onPointerMove={onMove}
        onPointerLeave={hide}
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
              {tickFormat(t)}
            </text>
          </g>
        ))}

        <path d={area} fill={color} opacity="0.1" />
        <path
          d={line}
          fill="none"
          stroke={color}
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {/* Crosshair for the hovered month. */}
        {tip && (
          <line
            x1={(tip.xPct / 100) * W}
            x2={(tip.xPct / 100) * W}
            y1={PAD.top}
            y2={PAD.top + plotH}
            stroke={CHROME.axis}
            strokeWidth="1"
            className="pointer-events-none"
          />
        )}

        {/* End marker: >= 8px across, with a 2px surface ring so it stays
            legible where it crosses the line. */}
        {last && (
          <circle
            cx={x(data.length - 1)}
            cy={y(last.value)}
            r="4"
            fill={color}
            stroke={CHROME.surface}
            strokeWidth="2"
            className="pointer-events-none"
          />
        )}

        {/* Keyboard parity: one focusable stop per month, same readout. */}
        {data.map((d, i) => (
          <rect
            key={d.label}
            x={x(i) - (stepX || plotW) / 2}
            y={PAD.top}
            width={stepX || plotW}
            height={plotH}
            fill="transparent"
            tabIndex={0}
            role="button"
            aria-label={`${d.fullLabel ?? d.label}: ${valueFormat(d.value)}`}
            className="focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-600"
            onFocus={() => focusPoint(i)}
            onBlur={hide}
          />
        ))}

        {data.map((d, i) =>
          i % labelEvery === 0 ? (
            <text
              key={d.label}
              x={x(i)}
              y={H - 8}
              textAnchor="middle"
              fontSize="11"
              fill={CHROME.label}
              className="pointer-events-none"
            >
              {d.label}
            </text>
          ) : null
        )}
      </svg>
      <ChartTooltip tip={tip} />
    </div>
  );
}
