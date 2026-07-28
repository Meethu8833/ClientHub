import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { getClients } from "../../../api/endpoints/clients";

// List query. The key embeds the filter params (['clients', {page, search…}])
// so every distinct filter combination is its own cache entry — and
// invalidating the ['clients'] prefix wipes all of them at once.
export function useClients(params) {
  return useQuery({
    queryKey: ["clients", params],
    queryFn: () => getClients(params),
    // While page 2 loads, keep showing page 1 instead of flashing a skeleton —
    // paging feels instant and the layout never jumps.
    placeholderData: keepPreviousData,
  });
}
