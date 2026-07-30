import { useQuery } from "@tanstack/react-query";

import { getCharts } from "../../../api/endpoints/dashboard";

// Companion to useDashboardSummary. Kept as a SEPARATE query on purpose: the
// charts endpoint is the heavier of the two, so a slow chart query never
// holds up the KPI tiles — each block renders as soon as its own data lands.
export function useDashboardCharts() {
  return useQuery({
    queryKey: ["dashboard", "charts"],
    queryFn: getCharts,
    // Matches the backend's 120 s cache: asking more often just re-downloads
    // the same cached aggregates.
    staleTime: 60_000,
  });
}
