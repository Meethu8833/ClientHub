import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  addProjectMember,
  removeProjectMember,
  updateProjectMember,
} from "../../../api/endpoints/projects";
import { useToast } from "../../../components/ui/useToast";

// Team writes. Membership rows are embedded in the project detail, so every
// success invalidates ['projects'] rather than patching rows by hand.
//
// Removing (or demoting) the LAST manager is refused by the API with a 400
// carrying a human-readable message — surface that text rather than a generic
// "something went wrong", because the user can act on it.
function serverMessage(error, fallback) {
  const data = error?.response?.data;
  const detail = data?.detail ?? data?.role;
  if (!detail) return fallback;
  return Array.isArray(detail) ? detail[0] : String(detail);
}

export function useMemberMutations(projectId) {
  const queryClient = useQueryClient();
  const toast = useToast();

  function refresh() {
    queryClient.invalidateQueries({ queryKey: ["projects"] });
    // Assignee pickers are filtered to project members — a new member becomes
    // assignable, a removed one must stop appearing on task forms.
    queryClient.invalidateQueries({ queryKey: ["tasks"] });
  }

  const add = useMutation({
    mutationFn: (payload) => addProjectMember(projectId, payload),
    onSuccess: (membership) => {
      refresh();
      toast.success(`${membership.user.name} added to the team.`);
    },
    // No error toast: the add-member form maps 400s ("already a member")
    // onto its own field.
  });

  const changeRole = useMutation({
    mutationFn: ({ id, role }) => updateProjectMember(id, { role }),
    onSuccess: () => {
      refresh();
      toast.success("Role updated.");
    },
    onError: (error) =>
      toast.error(serverMessage(error, "Could not change the role. Please try again.")),
  });

  const remove = useMutation({
    mutationFn: removeProjectMember,
    onSuccess: () => {
      refresh();
      toast.success("Member removed from the project.");
    },
    onError: (error) =>
      toast.error(serverMessage(error, "Could not remove the member. Please try again.")),
  });

  return { add, changeRole, remove };
}
