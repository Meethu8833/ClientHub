import { useQuery } from "@tanstack/react-query";

import { getClient } from "../../../api/endpoints/clients";

// Detail query, key ['clients', id] (ARCHITECTURE §10: keys mirror API paths).
export function useClient(id) {
  return useQuery({
    queryKey: ["clients", id],
    queryFn: () => getClient(id),
    // A missing client stays missing — retrying a 404 just delays the
    // "not found" screen. Retry only real (network/5xx) failures.
    retry: (failureCount, error) => error?.response?.status !== 404 && failureCount < 1,
  });
}
