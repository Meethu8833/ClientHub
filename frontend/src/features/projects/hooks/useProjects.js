import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { getProjects } from "../../../api/endpoints/projects";

// List query. The key embeds the filter params (['projects', {page, status…}])
// so every filter combination is its own cache entry — and invalidating the
// ['projects'] prefix wipes all of them at once.
export function useProjects(params) {
  return useQuery({
    queryKey: ["projects", params],
    queryFn: () => getProjects(params),
    // While page 2 loads, keep showing page 1 instead of flashing a skeleton.
    placeholderData: keepPreviousData,
  });
}
