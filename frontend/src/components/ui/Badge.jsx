// Dark variants use a translucent tint of the hue plus a light text step,
// rather than the light theme's -100/-700 pair: a solid -100 background is
// near-white and would glare on a dark surface.
const COLORS = {
  gray: "bg-gray-100 text-gray-700 dark:bg-gray-700/40 dark:text-gray-200",
  green: "bg-green-100 text-green-700 dark:bg-green-500/15 dark:text-green-300",
  red: "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300",
  amber: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300",
  indigo: "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300",
  sky: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300",
};

export function Badge({ color = "gray", className = "", children }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium
        ${COLORS[color]} ${className}`}
    >
      {children}
    </span>
  );
}
