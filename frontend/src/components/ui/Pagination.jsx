import { Button } from "./Button";

// "Showing X–Y of Z" + prev/next (design doc §4.1). Matches DRF's
// PageNumberPagination: the API says {count, next, previous}; we only need
// count + the current page to render everything.
export function Pagination({ page, pageSize = 20, count, onPageChange }) {
  const totalPages = Math.max(1, Math.ceil(count / pageSize));
  if (count === 0) return null; // the empty state already says there's nothing

  const from = (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, count);

  return (
    <nav
      aria-label="Pagination"
      className="flex items-center justify-between border-t border-gray-200 px-4 py-3"
    >
      <p className="text-sm text-gray-600">
        Showing <span className="font-medium">{from}</span>–
        <span className="font-medium">{to}</span> of <span className="font-medium">{count}</span>
      </p>
      <div className="flex items-center gap-2">
        <Button variant="secondary" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
          Previous
        </Button>
        <span className="text-sm text-gray-600">
          Page {page} of {totalPages}
        </span>
        <Button
          variant="secondary"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
        >
          Next
        </Button>
      </div>
    </nav>
  );
}
