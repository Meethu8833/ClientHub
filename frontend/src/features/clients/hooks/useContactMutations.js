import { useMutation, useQueryClient } from "@tanstack/react-query";

import { createContact, deleteContact, updateContact } from "../../../api/endpoints/clients";
import { useToast } from "../../../components/ui/useToast";

// Contact writes always happen on a client's detail page, and the detail
// response embeds the contacts — so invalidating ['clients', clientId]
// refreshes the visible list. The plain ['clients'] prefix also catches the
// list page's contact_count column.
export function useContactMutations(clientId) {
  const queryClient = useQueryClient();
  const toast = useToast();

  function refresh() {
    queryClient.invalidateQueries({ queryKey: ["clients"] });
  }

  const create = useMutation({
    mutationFn: (payload) => createContact(clientId, payload),
    onSuccess: (contact) => {
      refresh();
      toast.success(`Contact "${contact.name}" added.`);
    },
  });

  const update = useMutation({
    mutationFn: ({ id, ...payload }) => updateContact(id, payload),
    onSuccess: () => {
      refresh();
      toast.success("Contact updated.");
    },
  });

  const remove = useMutation({
    mutationFn: deleteContact,
    onSuccess: () => {
      refresh();
      toast.success("Contact removed.");
    },
    onError: () => toast.error("Could not remove the contact. Please try again."),
  });

  return { create, update, remove };
}
