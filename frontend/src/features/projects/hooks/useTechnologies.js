import { useQuery } from "@tanstack/react-query";

import { getTechnologies } from "../../../api/endpoints/projects";

// The tech-stack picker's option source. Tags change rarely (the API has no
// update/delete at all), so cache for 5 minutes rather than refetching every
// time the project form opens.
export function useTechnologies({ enabled = true } = {}) {
  return useQuery({
    queryKey: ["technologies"],
    // 100 is the API's max_page_size — asking for more is silently capped.
    queryFn: () => getTechnologies({ page_size: 100 }),
    enabled,
    staleTime: 5 * 60_000,
    // Unwrap the DRF envelope here so every caller gets a plain array.
    select: (data) => data.results ?? data,
  });
}
