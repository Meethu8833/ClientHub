import { useState } from "react";

import { Avatar } from "../../../components/ui/Avatar";
import { Badge } from "../../../components/ui/Badge";
import { Button } from "../../../components/ui/Button";
import { ConfirmDialog } from "../../../components/ui/ConfirmDialog";
import { DropdownMenu } from "../../../components/ui/DropdownMenu";
import { EmptyState } from "../../../components/ui/EmptyState";
import { useContactMutations } from "../hooks/useContactMutations";
import { ContactForm } from "./ContactForm";

// Contacts tab (design doc §7.4): card per person, primary first (the API
// orders -is_primary, name). Owns its own modals — the detail page just
// renders <ContactList client={client} canWrite={...} />.
export function ContactList({ client, canWrite }) {
  const { remove } = useContactMutations(client.id);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingContact, setEditingContact] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);

  function openCreate() {
    setEditingContact(null);
    setIsFormOpen(true);
  }

  function openEdit(contact) {
    setEditingContact(contact);
    setIsFormOpen(true);
  }

  return (
    <div>
      {canWrite && (
        <div className="mb-4 flex justify-end">
          <Button variant="secondary" onClick={openCreate}>
            + Add contact
          </Button>
        </div>
      )}

      {client.contacts.length === 0 ? (
        <EmptyState
          icon="👤"
          title="No contacts yet"
          message="Add the people you talk to at this company."
          action={canWrite && <Button onClick={openCreate}>+ Add contact</Button>}
        />
      ) : (
        <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {client.contacts.map((contact) => (
            <li
              key={contact.id}
              className="flex items-start justify-between rounded-lg bg-white p-4 shadow-sm
                ring-1 ring-gray-200 dark:bg-gray-900 dark:ring-gray-800"
            >
              <div className="flex items-start gap-3">
                <Avatar name={contact.name} size="lg" />
                <div>
                  <p className="flex items-center gap-2 text-sm font-medium text-gray-900 dark:text-gray-50">
                    {contact.name}
                    {contact.is_primary && <Badge color="indigo">★ Primary</Badge>}
                  </p>
                  {contact.position && (
                    <p className="text-xs text-gray-500 dark:text-gray-400">{contact.position}</p>
                  )}
                  <p className="mt-1 space-x-3 text-sm">
                    {contact.email && (
                      <a
                        href={`mailto:${contact.email}`}
                        className="text-indigo-600 hover:underline dark:text-indigo-400"
                      >
                        {contact.email}
                      </a>
                    )}
                    {contact.phone && (
                      <a
                        href={`tel:${contact.phone}`}
                        className="text-indigo-600 hover:underline dark:text-indigo-400"
                      >
                        {contact.phone}
                      </a>
                    )}
                  </p>
                </div>
              </div>

              {canWrite && (
                <DropdownMenu
                  label={`Actions for ${contact.name}`}
                  items={[
                    { label: "Edit", onClick: () => openEdit(contact) },
                    { label: "Delete", tone: "danger", onClick: () => setDeleteTarget(contact) },
                  ]}
                />
              )}
            </li>
          ))}
        </ul>
      )}

      <ContactForm
        isOpen={isFormOpen}
        onClose={() => setIsFormOpen(false)}
        clientId={client.id}
        contact={editingContact}
      />

      <ConfirmDialog
        isOpen={deleteTarget != null}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => remove.mutate(deleteTarget.id, { onSuccess: () => setDeleteTarget(null) })}
        isPending={remove.isPending}
        title={`Remove ${deleteTarget?.name}?`}
        message="This permanently removes the contact from this client."
        confirmLabel="Remove"
      />
    </div>
  );
}
