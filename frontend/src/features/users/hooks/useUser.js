import { useQuery } from "@tanstack/react-query";

import { getUser } from "../../../api/endpoints/users";

// Single user detail. The list rows carry UserListSerializer's slim shape
// (no first/last name, no weekly_capacity_hours), so the edit form must load
// the full record before it can PATCH — seeding a missing field from a
// default would silently overwrite the stored value.
export function useUser(id, { enabled = true } = {}) {
  return useQuery({
    queryKey: ["users", "detail", id],
    queryFn: () => getUser(id),
    enabled: enabled && id != null,
  });
}
