import { useQuery } from "@tanstack/react-query";

import { getAssignableUsers } from "../../../api/endpoints/users";

// Dropdown source for the account-manager select. Only managers/admins may
// call the endpoint (staff get 403), so the hook takes `enabled` and the
// form only turns it on when the current role can actually write.
// Users change rarely — cache for 5 minutes instead of refetching per open.
export function useAssignableUsers({ enabled = true } = {}) {
  return useQuery({
    queryKey: ["users", "assignable"],
    queryFn: getAssignableUsers,
    enabled,
    staleTime: 5 * 60_000,
  });
}
