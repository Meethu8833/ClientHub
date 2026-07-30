import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { getUsers } from "../../../api/endpoints/users";

// List query for the admin users screen. The key embeds the filter params
// (['users', 'list', {page, search, role…}]) so every filter combination is
// its own cache entry, and invalidating the ['users'] prefix wipes them all
// — including ['users','assignable'], which must also refresh when a new
// teammate is created.
export function useUsers(params) {
  return useQuery({
    queryKey: ["users", "list", params],
    queryFn: () => getUsers(params),
    // Keep the current page on screen while the next one loads.
    placeholderData: keepPreviousData,
  });
}
