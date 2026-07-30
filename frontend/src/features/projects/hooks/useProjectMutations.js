import { useMutation, useQueryClient } from "@tanstack/react-query";

import { createProject, deleteProject, updateProject } from "../../../api/endpoints/projects";
import { useToast } from "../../../components/ui/useToast";

// All project writes in one hook — same rules as useClientMutations:
// - every success invalidates the ['projects'] prefix (lists AND details);
// - create/update PRIME the detail cache from the response, because the API
//   answers writes with the full detail shape;
// - toasts fire here so every caller gets feedback for free;
// - no onError toast on create/update: the form maps 400s onto its fields.
export function useProjectMutations() {
  const queryClient = useQueryClient();
  const toast = useToast();

  const create = useMutation({
    mutationFn: createProject,
    onSuccess: (project) => {
      queryClient.setQueryData(["projects", String(project.id)], project);
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      toast.success(`Project "${project.name}" created.`);
    },
  });

  const update = useMutation({
    mutationFn: ({ id, ...payload }) => updateProject(id, payload),
    onSuccess: (project) => {
      queryClient.setQueryData(["projects", String(project.id)], project);
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      toast.success("Project updated.");
    },
  });

  const remove = useMutation({
    mutationFn: deleteProject,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      // Tasks hang off projects: a deleted project's tasks vanish from every
      // cross-project list, so those caches are stale too.
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      toast.success("Project deleted.");
    },
    onError: () => toast.error("Could not delete the project. Please try again."),
  });

  return { create, update, remove };
}
