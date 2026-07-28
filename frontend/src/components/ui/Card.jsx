// The white surface every list/table/panel sits on (design tokens §1.4:
// surface white, ring-gray-200, rounded-lg, shadow-sm — never deeper).
export function Card({ title, actions, children, padding = true, className = "" }) {
  return (
    <div className={`rounded-lg bg-white shadow-sm ring-1 ring-gray-200 ${className}`}>
      {(title || actions) && (
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          {title && <h2 className="text-base font-semibold text-gray-900">{title}</h2>}
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={padding ? "p-6" : ""}>{children}</div>
    </div>
  );
}
