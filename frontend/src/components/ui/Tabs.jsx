// URL-driven tab strip (design doc §4.1): the parent reads ?tab= from the URL
// and passes it as `active` — so tabs are deep-linkable and survive refresh.
// role="tablist" + aria-selected announce the structure to screen readers.
export function Tabs({ tabs, active, onChange }) {
  return (
    <div
      role="tablist"
      className="flex gap-1 overflow-x-auto border-b border-gray-200 dark:border-gray-800"
    >
      {tabs.map((tab) => {
        const isActive = tab.key === active;
        return (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={isActive}
            disabled={tab.disabled}
            onClick={() => onChange(tab.key)}
            className={`-mb-px whitespace-nowrap border-b-2 px-4 py-2.5 text-sm font-medium
              transition-colors focus-visible:outline-2 focus-visible:outline-offset-2
              focus-visible:outline-indigo-600 disabled:cursor-not-allowed disabled:text-gray-300
              ${
                isActive
                  ? "border-indigo-600 text-indigo-600 dark:border-indigo-400 dark:text-indigo-300"
                  : "border-transparent text-gray-600 hover:border-gray-300 hover:text-gray-900 " +
                    "dark:text-gray-400 dark:hover:border-gray-600 dark:hover:text-gray-100"
              }`}
          >
            {tab.label}
            {tab.count != null && (
              <span
                className={`ml-2 rounded-full px-2 py-0.5 text-xs
                  ${
                    isActive
                      ? "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-200"
                      : "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300"
                  }`}
              >
                {tab.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
