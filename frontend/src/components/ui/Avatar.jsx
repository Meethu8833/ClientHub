const HUES = [
  "bg-indigo-500",
  "bg-sky-500",
  "bg-emerald-500",
  "bg-amber-500",
  "bg-rose-500",
  "bg-violet-500",
  "bg-teal-500",
];

const SIZES = {
  sm: "h-6 w-6 text-[10px]",
  md: "h-8 w-8 text-xs",
  lg: "h-10 w-10 text-sm",
};

// Initials on a colored disc (design doc §4.1). The hue is a hash of the
// name, so the same person is always the same color everywhere — recognition
// without uploading a photo.
function hueFor(name) {
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + ch.codePointAt(0)) % HUES.length;
  return HUES[hash];
}

function initialsOf(name) {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

export function Avatar({ name = "?", size = "md", className = "" }) {
  return (
    <span
      title={name}
      className={`inline-flex shrink-0 items-center justify-center rounded-full font-semibold
        text-white ${SIZES[size]} ${hueFor(name)} ${className}`}
    >
      {initialsOf(name)}
    </span>
  );
}
