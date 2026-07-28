import { useMutation, useQueryClient } from "@tanstack/react-query";

import { createClient, deleteClient, updateClient } from "../../../api/endpoints/clients";
import { useToast } from "../../../components/ui/useToast";

// All client writes in one hook. Shared rules:
// - every success invalidates the ['clients'] prefix (lists AND details) —
//   mutations invalidate their query keys, no hand-patching of stale rows;
// - update/create additionally PRIME the detail cache from the response
//   (the API answers writes with the full detail shape) so navigating to
//   the record right after saving needs no extra fetch;
// - toasts fire here, not in components — every caller gets feedback free.
export function useClientMutations() {
  const queryClient = useQueryClient();
  const toast = useToast();

  const create = useMutation({
    mutationFn: createClient,
    onSuccess: (client) => {
      queryClient.setQueryData(["clients", client.id], client);
      queryClient.invalidateQueries({ queryKey: ["clients"] });
      toast.success(`Client "${client.name}" created.`);
    },
    // No onError toast: the form maps 400s onto its fields — a toast on top
    // would double-report. Callers handle unexpected errors via .isError.
  });

  const update = useMutation({
    mutationFn: ({ id, ...payload }) => updateClient(id, payload),
    onSuccess: (client) => {
      queryClient.setQueryData(["clients", client.id], client);
      queryClient.invalidateQueries({ queryKey: ["clients"] });
      toast.success("Client updated.");
    },
  });

  const remove = useMutation({
    mutationFn: deleteClient,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["clients"] });
      toast.success("Client deleted.");
    },
    onError: () => toast.error("Could not delete the client. Please try again."),
  });

  return { create, update, remove };
}
