import { useQuery } from "@tanstack/react-query";

import { getClients } from "../../../api/endpoints/clients";

// Option source for the project form's Client select. There is no dedicated
// "all clients" endpoint, so this borrows the paginated list at the API's
// maximum page size (100) sorted by name.
//
// The caller gets `count` back alongside the rows precisely so it can tell the
// user when the list is truncated — a picker that quietly omits clients would
// look like those clients had been deleted.
export function useClientOptions({ enabled = true } = {}) {
  return useQuery({
    queryKey: ["clients", "options"],
    queryFn: () => getClients({ page_size: 100, ordering: "name" }),
    enabled,
    staleTime: 5 * 60_000,
    select: (data) => ({ clients: data.results, total: data.count }),
  });
}
