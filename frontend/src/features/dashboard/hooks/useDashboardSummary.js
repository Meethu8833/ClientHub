import { useQuery } from "@tanstack/react-query";

import { getSummary } from "../../../api/endpoints/dashboard";

// All data fetching lives in feature hooks (ARCHITECTURE §3) — pages just
// consume { data, isPending, isError }. The query key mirrors the API path,
// so future invalidation stays predictable.
export function useDashboardSummary() {
  return useQuery({
    queryKey: ["dashboard", "summary"],
    queryFn: getSummary,
    // The backend caches this payload for 120 s anyway — refetching more
    // often would only re-download the same cached numbers.
    staleTime: 60_000,
  });
}
