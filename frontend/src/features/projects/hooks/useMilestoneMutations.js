import { useMutation, useQueryClient } from "@tanstack/react-query";

import { createMilestone, deleteMilestone, updateMilestone } from "../../../api/endpoints/projects";
import { useToast } from "../../../components/ui/useToast";

// Milestone writes always happen on a project's detail page, and the detail
// response embeds the milestones — so invalidating ['projects'] refreshes the
// visible list. It also refreshes the list page's `progress` column, which is
// computed from completed/total milestones.
export function useMilestoneMutations(projectId) {
  const queryClient = useQueryClient();
  const toast = useToast();

  function refresh() {
    queryClient.invalidateQueries({ queryKey: ["projects"] });
  }

  const create = useMutation({
    mutationFn: (payload) => createMilestone(projectId, payload),
    onSuccess: (milestone) => {
      refresh();
      toast.success(`Milestone "${milestone.title}" added.`);
    },
  });

  const update = useMutation({
    mutationFn: ({ id, ...payload }) => updateMilestone(id, payload),
    onSuccess: () => {
      refresh();
      toast.success("Milestone updated.");
    },
  });

  // Toggling the done checkbox is an update like any other, but it deserves
  // its own message — "Milestone updated" reads as a no-op next to a tick.
  const toggle = useMutation({
    mutationFn: ({ id, is_completed }) => updateMilestone(id, { is_completed }),
    onSuccess: (milestone) => {
      refresh();
      toast.success(
        milestone.is_completed
          ? `"${milestone.title}" marked complete.`
          : `"${milestone.title}" reopened.`
      );
    },
    onError: () => toast.error("Could not update the milestone. Please try again."),
  });

  const remove = useMutation({
    mutationFn: deleteMilestone,
    onSuccess: () => {
      refresh();
      // Tasks can point at a milestone — their chip is now stale.
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      toast.success("Milestone deleted.");
    },
    onError: () => toast.error("Could not delete the milestone. Please try again."),
  });

  return { create, update, toggle, remove };
}
