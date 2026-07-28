const TONES = {
  default: "text-gray-900",
  danger: "text-red-600",
  success: "text-green-600",
};

export function KpiCard({ label, value, tone = "default" }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <p className="truncate text-sm text-gray-500">{label}</p>
      <p className={`mt-1 text-2xl font-semibold ${TONES[tone]}`}>{value}</p>
    </div>
  );
}

// Same footprint as KpiCard so the page doesn't jump when data arrives.
export function KpiCardSkeleton() {
  return (
    <div className="animate-pulse rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="h-4 w-24 rounded bg-gray-200" />
      <div className="mt-2 h-7 w-14 rounded bg-gray-200" />
    </div>
  );
}
