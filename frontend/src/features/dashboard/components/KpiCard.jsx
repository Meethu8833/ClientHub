import { Link } from "react-router-dom";

// Two tile sizes, one contract.
//
//   <KpiCard>   the hero row — big number, icon, optional caption
//   <StatTile>  the compact secondary tiles inside a group card
//
// `tone` is state, not decoration: it only fires when a number actually
// demands attention (overdue > 0), and it is never colour-alone — a toned
// tile also carries a caption in words, so the meaning survives for a
// colour-blind reader and in greyscale print.

const TONE = {
  default: {
    value: "text-gray-900 dark:text-gray-50",
    icon: "bg-indigo-50 text-indigo-600 dark:bg-indigo-500/15 dark:text-indigo-300",
    caption: "text-gray-500 dark:text-gray-400",
  },
  success: {
    value: "text-gray-900 dark:text-gray-50",
    icon: "bg-green-50 text-green-700 dark:bg-green-500/15 dark:text-green-300",
    caption: "text-green-700 dark:text-green-400",
  },
  danger: {
    value: "text-red-700 dark:text-red-300",
    icon: "bg-red-50 text-red-600 dark:bg-red-500/15 dark:text-red-400",
    caption: "text-red-700 dark:text-red-400",
  },
};

// Wraps the tile in a Link only when a destination is given, so a tile is
// never a fake button. Same visual box either way.
function TileShell({ to, className = "", children }) {
  const shared = `block rounded-lg bg-white p-4 shadow-sm ring-1 ring-gray-200 transition-shadow
    dark:bg-gray-900 dark:ring-gray-800
    ${to ? "hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-600" : ""}
    ${className}`;

  return to ? (
    <Link to={to} className={shared}>
      {children}
    </Link>
  ) : (
    <div className={shared}>{children}</div>
  );
}

export function KpiCard({ label, value, caption, tone = "default", icon, to }) {
  const t = TONE[tone] ?? TONE.default;

  return (
    <TileShell to={to}>
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-gray-600 dark:text-gray-300">{label}</p>
        {icon && (
          <span
            aria-hidden="true"
            className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${t.icon}`}
          >
            {icon}
          </span>
        )}
      </div>
      {/* Proportional figures, not tabular: at 3xl, tabular digits make a
          number like 121 look loose. */}
      <p className={`mt-2 text-3xl font-semibold tracking-tight ${t.value}`}>{value}</p>
      {caption && <p className={`mt-1 text-xs ${t.caption}`}>{caption}</p>}
    </TileShell>
  );
}

// Compact tile for the grouped secondary stats — flat, so it reads as a
// child of its group card rather than competing with the hero row.
export function StatTile({ label, value, tone = "default", to }) {
  const t = TONE[tone] ?? TONE.default;
  const inner = (
    <>
      <p className="truncate text-xs text-gray-600 dark:text-gray-400">{label}</p>
      <p className={`mt-1 text-xl font-semibold ${t.value}`}>{value}</p>
    </>
  );
  const base = "block rounded-md bg-gray-50 p-3 transition-colors dark:bg-gray-800/60";

  return to ? (
    <Link
      to={to}
      className={`${base} hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-2
        focus-visible:ring-indigo-600 dark:hover:bg-gray-800`}
    >
      {inner}
    </Link>
  ) : (
    <div className={base}>{inner}</div>
  );
}

// Same footprint as KpiCard so the page never jumps when data arrives.
export function KpiCardSkeleton() {
  return (
    <div className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-gray-200 dark:bg-gray-900 dark:ring-gray-800">
      <div className="flex items-start justify-between gap-3">
        <div className="h-4 w-24 animate-pulse rounded bg-gray-200 dark:bg-gray-700" />
        <div className="h-8 w-8 shrink-0 animate-pulse rounded-md bg-gray-100 dark:bg-gray-800" />
      </div>
      <div className="mt-3 h-8 w-16 animate-pulse rounded bg-gray-200 dark:bg-gray-700" />
    </div>
  );
}

export function ChartSkeleton() {
  return (
    <div className="rounded-lg bg-white p-6 shadow-sm ring-1 ring-gray-200 dark:bg-gray-900 dark:ring-gray-800">
      <div className="h-4 w-40 animate-pulse rounded bg-gray-200 dark:bg-gray-700" />
      <div className="mt-2 h-3 w-24 animate-pulse rounded bg-gray-100 dark:bg-gray-800" />
      <div className="mt-6 h-40 animate-pulse rounded bg-gray-100 dark:bg-gray-800" />
    </div>
  );
}
