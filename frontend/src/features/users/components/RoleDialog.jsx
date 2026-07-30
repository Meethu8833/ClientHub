import { useEffect, useState } from "react";

import { Button } from "../../../components/ui/Button";
import { Modal } from "../../../components/ui/Modal";
import { Select } from "../../../components/ui/Select";
import { ROLE_OPTIONS, ROLES } from "../../../lib/constants";
import { useUserMutations } from "../hooks/useUserMutations";

// What each role actually unlocks (ARCHITECTURE §8 permission matrix), shown
// under the picker: "manager" means nothing on its own — the consequence does.
const ROLE_DESCRIPTIONS = {
  [ROLES.STAFF]: "Reads the records they are assigned to. Cannot create or delete clients.",
  [ROLES.MANAGER]: "Full access to clients, projects and billing. Cannot manage user accounts.",
  [ROLES.ADMIN]: "Everything a manager can do, plus creating and managing user accounts.",
};

// Role changes get their own dialog rather than a field in the edit form,
// because the API models them as a separate, guarded action: the server
// refuses to demote the last active admin or to change your own role.
export function RoleDialog({ isOpen, onClose, user }) {
  const { changeRole } = useUserMutations();
  const [role, setRole] = useState(ROLES.STAFF);

  // Start from the user's current role each time the dialog opens.
  useEffect(() => {
    if (isOpen && user) setRole(user.role);
  }, [isOpen, user]);

  function submit() {
    changeRole.mutate({ id: user.id, role }, { onSuccess: () => onClose() });
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={`Change role — ${user?.full_name || user?.email || ""}`}
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={changeRole.isPending}>
            Cancel
          </Button>
          <Button onClick={submit} isLoading={changeRole.isPending} disabled={role === user?.role}>
            Change role
          </Button>
        </>
      }
    >
      <Select
        label="Role"
        options={ROLE_OPTIONS}
        value={role}
        onChange={(e) => setRole(e.target.value)}
        hint={ROLE_DESCRIPTIONS[role]}
      />
      <p className="mt-4 text-sm text-gray-600 dark:text-gray-300">
        The new permissions apply the next time {user?.email} loads a page.
      </p>
    </Modal>
  );
}
