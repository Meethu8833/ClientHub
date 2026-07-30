import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";

import { Avatar } from "../../../components/ui/Avatar";
import { Button } from "../../../components/ui/Button";
import { ConfirmDialog } from "../../../components/ui/ConfirmDialog";
import { EmptyState } from "../../../components/ui/EmptyState";
import { Modal } from "../../../components/ui/Modal";
import { Select } from "../../../components/ui/Select";
import { StatusBadge } from "../../../components/ui/StatusBadge";
import { MEMBER_ROLE, MEMBER_ROLE_OPTIONS } from "../../../lib/constants";
import { applyServerErrors } from "../../../lib/forms";
import { formatDate } from "../../../lib/formatters";
// Shared user picker source (/users/assignable/) — it lives in the clients
// feature because that is where the first picker appeared; users.js always
// intended it to serve task assignees too.
import { useAssignableUsers } from "../../clients/hooks/useAssignableUsers";
import { useMemberMutations } from "../hooks/useMemberMutations";

function AddMemberModal({ isOpen, onClose, project }) {
  const { add } = useMemberMutations(project.id);
  const { data: users } = useAssignableUsers({ enabled: isOpen });

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors },
  } = useForm({ defaultValues: { user_id: "", role: "developer" } });

  useEffect(() => {
    if (isOpen) reset({ user_id: "", role: "developer" });
  }, [isOpen, reset]);

  // Offering someone already on the team would only earn a 400 — filter them
  // out so the picker can't produce an invalid choice.
  const options = useMemo(() => {
    const taken = new Set(project.members?.map((m) => m.user.id));
    return (users ?? [])
      .filter((u) => !taken.has(u.id))
      .map((u) => ({ value: u.id, label: `${u.name} (${u.email})` }));
  }, [users, project.members]);

  function onSubmit(values) {
    add.mutate(
      { user_id: Number(values.user_id), role: values.role },
      {
        onSuccess: () => onClose(),
        onError: (error) => applyServerErrors(error, setError, ["user_id", "role"]),
      }
    );
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Add team member"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={add.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="add-member-form" isLoading={add.isPending}>
            Add to team
          </Button>
        </>
      }
    >
      <form id="add-member-form" onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
        {errors.root && (
          <p
            role="alert"
            className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700
              dark:bg-red-500/10 dark:text-red-300"
          >
            {errors.root.message}
          </p>
        )}
        <Select
          label="User *"
          placeholder="— Select a user —"
          options={options}
          hint={options.length === 0 ? "Everyone assignable is already on this team." : undefined}
          error={errors.user_id?.message}
          {...register("user_id", { required: "Pick someone to add." })}
        />
        <Select
          label="Project role"
          options={MEMBER_ROLE_OPTIONS}
          hint="This role applies to this project only — it is not their account role."
          error={errors.role?.message}
          {...register("role")}
        />
      </form>
    </Modal>
  );
}

// Team tab. Membership is what makes a project visible to STAFF at all
// (§8 scoping) and what makes someone assignable — so this tab is closer to
// access control than to a contact list, and the copy says so.
export function TeamList({ project, canWrite }) {
  const { changeRole, remove } = useMemberMutations(project.id);
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [removeTarget, setRemoveTarget] = useState(null);

  const members = project.members ?? [];

  return (
    <div>
      {canWrite && (
        <div className="mb-4 flex justify-end">
          <Button variant="secondary" onClick={() => setIsAddOpen(true)}>
            + Add member
          </Button>
        </div>
      )}

      {members.length === 0 ? (
        <EmptyState
          icon="👥"
          title="Nobody on this project yet"
          message="Add people to make the project visible to them and to be able to
            assign them tasks."
          action={canWrite && <Button onClick={() => setIsAddOpen(true)}>+ Add member</Button>}
        />
      ) : (
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {members.map((member) => (
            <li
              key={member.id}
              className="flex items-start justify-between gap-3 rounded-lg bg-white p-4
                shadow-sm ring-1 ring-gray-200 dark:bg-gray-900 dark:ring-gray-800"
            >
              <div className="flex items-start gap-3">
                <Avatar name={member.user.name} size="lg" />
                <div>
                  <p className="flex items-center gap-2 text-sm font-medium text-gray-900 dark:text-gray-50">
                    {member.user.name}
                    <StatusBadge map={MEMBER_ROLE} value={member.role} />
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">{member.user.email}</p>
                  <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                    Joined {formatDate(member.created_at)}
                  </p>
                </div>
              </div>

              {canWrite && (
                <div className="flex shrink-0 flex-col items-end gap-2">
                  <Select
                    label=""
                    aria-label={`Project role for ${member.user.name}`}
                    options={MEMBER_ROLE_OPTIONS}
                    value={member.role}
                    disabled={changeRole.isPending}
                    onChange={(e) => changeRole.mutate({ id: member.id, role: e.target.value })}
                    className="w-32"
                  />
                  <Button variant="ghost" onClick={() => setRemoveTarget(member)}>
                    Remove
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      <AddMemberModal isOpen={isAddOpen} onClose={() => setIsAddOpen(false)} project={project} />

      <ConfirmDialog
        isOpen={removeTarget != null}
        onClose={() => setRemoveTarget(null)}
        onConfirm={() => remove.mutate(removeTarget.id, { onSuccess: () => setRemoveTarget(null) })}
        isPending={remove.isPending}
        title={`Remove ${removeTarget?.user.name}?`}
        message="They lose access to this project and stop being assignable. Tasks
          already assigned to them stay assigned — reassign those first if the
          work needs an owner."
      />
    </div>
  );
}
