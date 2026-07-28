// Every list's zero state (design doc §4.1): tell the user this is normal,
// and hand them the next step (a CTA) instead of a dead end.
export function EmptyState({ icon = "📋", title, message, action }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      <span aria-hidden="true" className="text-3xl">
        {icon}
      </span>
      <h3 className="mt-3 text-base font-semibold text-gray-900">{title}</h3>
      {message && <p className="mt-1 max-w-prose text-sm text-gray-600">{message}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
