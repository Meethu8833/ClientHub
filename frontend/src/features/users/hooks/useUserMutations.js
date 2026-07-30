import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  activateUser,
  assignUserRole,
  createUser,
  deactivateUser,
  updateUser,
} from "../../../api/endpoints/users";
import { useToast } from "../../../components/ui/useToast";
import { ROLE_LABELS } from "../../../lib/constants";

// Every admin write against /users/ in one hook, mirroring useClientMutations:
// - success invalidates the ['users'] prefix, which covers both the admin list
//   and the ['users','assignable'] picker list (a new teammate must show up in
//   the account-manager dropdown without a reload);
// - toasts fire here so no caller has to remember them;
// - create/update deliberately have NO error toast — the form maps 400s onto
//   its fields, and a toast on top would report the same thing twice.
export function useUserMutations() {
  const queryClient = useQueryClient();
  const toast = useToast();

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["users"] });

  const create = useMutation({
    mutationFn: createUser,
    onSuccess: (user, variables) => {
      invalidate();
      const who = user.first_name ? `${user.first_name} (${user.email})` : user.email;
      // The message has to tell the admin what happens NEXT, and that differs:
      // with no password the server emailed an invite, otherwise they must
      // hand the credentials over themselves.
      toast.success(
        variables.password
          ? `${ROLE_LABELS[user.role] ?? user.role} account created for ${who}.`
          : `Invite sent to ${user.email} — they'll set their own password.`
      );
    },
  });

  const update = useMutation({
    mutationFn: ({ id, ...payload }) => updateUser(id, payload),
    onSuccess: () => {
      invalidate();
      toast.success("User updated.");
    },
  });

  // The three lifecycle actions DO toast their errors: they fire straight from
  // a menu item with no form to land a message in, and they carry real server
  // guards (last admin, self-action) whose messages the admin must see.
  const changeRole = useMutation({
    mutationFn: ({ id, role }) => assignUserRole(id, role),
    onSuccess: (user) => {
      invalidate();
      toast.success(`${user.email} is now ${ROLE_LABELS[user.role] ?? user.role}.`);
    },
    onError: (error) => toast.error(serverMessage(error, "Could not change the role.")),
  });

  const deactivate = useMutation({
    mutationFn: deactivateUser,
    onSuccess: (user) => {
      invalidate();
      toast.success(`${user.email} can no longer sign in.`);
    },
    onError: (error) => toast.error(serverMessage(error, "Could not deactivate the user.")),
  });

  const activate = useMutation({
    mutationFn: activateUser,
    onSuccess: (user) => {
      invalidate();
      toast.success(`${user.email} can sign in again.`);
    },
    onError: (error) => toast.error(serverMessage(error, "Could not reactivate the user.")),
  });

  return { create, update, changeRole, deactivate, activate };
}

// The guards answer with DRF's two error shapes — {"detail": "..."} (403
// PermissionDenied) and {"detail": ["..."]} (400 ValidationError). Both say
// something specific ("Cannot delete the last active admin"), so show it
// instead of a generic failure message.
function serverMessage(error, fallback) {
  const detail = error?.response?.data?.detail;
  if (!detail) return fallback;
  return Array.isArray(detail) ? detail[0] : String(detail);
}
