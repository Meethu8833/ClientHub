// Generic data table (design doc §4.1). Owns the four states every data view
// must handle (§11): loading (skeleton rows matching the final layout — no
// jumping), error (retry), empty (caller-provided EmptyState) and data.
//
// columns: [{ key, header, render?, sortable?, className? }]
//   render(row) overrides the default row[key] cell.
// sort: DRF ?ordering= string ("name" asc, "-name" desc) — the table only
//   *displays* it; the parent owns it because it lives in the URL.

function SortIcon({ direction }) {
  return (
    <span aria-hidden="true" className="ml-1 inline-block w-3 text-gray-400 dark:text-gray-500">
      {direction === "asc" ? "▲" : direction === "desc" ? "▼" : "⇅"}
    </span>
  );
}

function SkeletonRows({ columns, rows }) {
  return Array.from({ length: rows }, (_, r) => (
    <tr key={r}>
      {columns.map((col) => (
        <td key={col.key} className="px-4 py-3">
          <div className="h-4 animate-pulse rounded bg-gray-200 dark:bg-gray-700" />
        </td>
      ))}
    </tr>
  ));
}

export function Table({
  columns,
  rows,
  isLoading = false,
  skeletonRows = 5,
  emptyState = null,
  sort = "",
  onSortChange,
  onRowClick,
}) {
  const isEmpty = !isLoading && (!rows || rows.length === 0);

  function handleSort(col) {
    if (!col.sortable || !onSortChange) return;
    // Cycle: unsorted → asc → desc → asc (never back to unsorted; a list
    // page should always have SOME deterministic order the user picked).
    onSortChange(sort === col.key ? `-${col.key}` : col.key);
  }

  const sortDirection = (col) =>
    sort === col.key ? "asc" : sort === `-${col.key}` ? "desc" : null;

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-800">
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                scope="col"
                aria-sort={
                  sortDirection(col) === "asc"
                    ? "ascending"
                    : sortDirection(col) === "desc"
                      ? "descending"
                      : undefined
                }
                className={`px-4 py-3 text-left text-xs font-medium uppercase tracking-wide
                  text-gray-500 dark:text-gray-400 ${col.className ?? ""}`}
              >
                {col.sortable ? (
                  <button
                    type="button"
                    onClick={() => handleSort(col)}
                    className="inline-flex items-center rounded hover:text-gray-700 dark:hover:text-gray-200
                      focus-visible:outline-2 focus-visible:outline-offset-2
                      focus-visible:outline-indigo-600"
                  >
                    {col.header}
                    <SortIcon direction={sortDirection(col)} />
                  </button>
                ) : (
                  col.header
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
          {isLoading && <SkeletonRows columns={columns} rows={skeletonRows} />}

          {isEmpty && (
            <tr>
              <td colSpan={columns.length}>{emptyState}</td>
            </tr>
          )}

          {!isLoading &&
            rows?.map((row) => (
              <tr
                key={row.id}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={
                  onRowClick
                    ? "cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800/60"
                    : undefined
                }
              >
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className={`whitespace-nowrap px-4 py-3 text-sm text-gray-900
                      dark:text-gray-100 ${col.className ?? ""}`}
                  >
                    {col.render ? col.render(row) : row[col.key]}
                  </td>
                ))}
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}
