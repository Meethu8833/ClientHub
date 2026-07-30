import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";

import { Badge } from "../../../components/ui/Badge";
import { Button } from "../../../components/ui/Button";
import { ConfirmDialog } from "../../../components/ui/ConfirmDialog";
import { EmptyState } from "../../../components/ui/EmptyState";
import { Input } from "../../../components/ui/Input";
import { Modal } from "../../../components/ui/Modal";
import { Spinner } from "../../../components/ui/Spinner";
import { StatusBadge } from "../../../components/ui/StatusBadge";
import { SPRINT_STATUS } from "../../../lib/constants";
import { applyServerErrors } from "../../../lib/forms";
import { formatDate } from "../../../lib/formatters";
import { useSprintMutations } from "../hooks/useSprintMutations";
import { useSprints } from "../hooks/useSprints";

function SprintFormModal({ isOpen, onClose, projectId, sprint = null }) {
  const isEdit = sprint != null;
  const { create, update } = useSprintMutations(projectId);
  const mutation = isEdit ? update : create;

  const {
    register,
    handleSubmit,
    reset,
    setError,
    watch,
    formState: { errors },
  } = useForm({ mode: "onTouched" });

  useEffect(() => {
    if (!isOpen) return;
    reset({
      name: sprint?.name ?? "",
      goal: sprint?.goal ?? "",
      start_date: sprint?.start_date ?? "",
      end_date: sprint?.end_date ?? "",
    });
  }, [isOpen, sprint, reset]);

  const startDate = watch("start_date");

  function onSubmit(values) {
    mutation.mutate(isEdit ? { id: sprint.id, ...values } : values, {
      onSuccess: () => onClose(),
      onError: (error) =>
        applyServerErrors(error, setError, ["name", "goal", "start_date", "end_date"]),
    });
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={isEdit ? `Edit ${sprint.name}` : "New sprint"}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="sprint-form" isLoading={mutation.isPending}>
            {isEdit ? "Save changes" : "Create sprint"}
          </Button>
        </>
      }
    >
      <form id="sprint-form" onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
        {errors.root && (
          <p
            role="alert"
            className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700
              dark:bg-red-500/10 dark:text-red-300"
          >
            {errors.root.message}
          </p>
        )}
        <Input
          label="Name *"
          error={errors.name?.message}
          {...register("name", { required: "A sprint needs a name." })}
        />
        <Input label="Goal" error={errors.goal?.message} {...register("goal")} />
        <div className="grid grid-cols-2 gap-4">
          <Input
            label="Start date *"
            type="date"
            error={errors.start_date?.message}
            {...register("start_date", { required: "Required." })}
          />
          <Input
            label="End date *"
            type="date"
            error={errors.end_date?.message}
            {...register("end_date", {
              required: "Required.",
              validate: (v) =>
                !startDate || v >= startDate || "End date cannot be before the start date.",
            })}
          />
        </div>
        {/* Status is absent on purpose: it only moves through the start and
            complete ceremonies, which also freeze the velocity snapshot. */}
      </form>
    </Modal>
  );
}

// Sprints tab. The ceremonies (start / complete) are buttons rather than a
// status dropdown because they are not edits — completing a sprint freezes its
// velocity numbers and returns unfinished tasks to the backlog.
export function SprintList({ projectId, canWrite }) {
  const { data: sprints, isPending } = useSprints(projectId);
  const { start, complete, remove } = useSprintMutations(projectId);

  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [completeTarget, setCompleteTarget] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);

  if (isPending) {
    return (
      <div className="flex justify-center py-10">
        <Spinner />
      </div>
    );
  }

  function openCreate() {
    setEditing(null);
    setIsFormOpen(true);
  }

  return (
    <div>
      {canWrite && (
        <div className="mb-4 flex justify-end">
          <Button variant="secondary" onClick={openCreate}>
            + New sprint
          </Button>
        </div>
      )}

      {sprints?.length === 0 ? (
        <EmptyState
          icon="🏃"
          title="No sprints yet"
          message="Sprints are optional — tasks without one sit in the backlog."
          action={canWrite && <Button onClick={openCreate}>+ New sprint</Button>}
        />
      ) : (
        <ul className="space-y-3">
          {sprints.map((sprint) => (
            <li
              key={sprint.id}
              className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-gray-200
                dark:bg-gray-900 dark:ring-gray-800"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="flex items-center gap-2 text-sm font-medium text-gray-900 dark:text-gray-50">
                    {sprint.name}
                    <StatusBadge map={SPRINT_STATUS} value={sprint.status} />
                  </p>
                  {sprint.goal && (
                    <p className="mt-0.5 text-sm text-gray-600 dark:text-gray-400">{sprint.goal}</p>
                  )}
                  <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                    {formatDate(sprint.start_date)} → {formatDate(sprint.end_date)}
                  </p>
                  <p className="mt-2 flex flex-wrap gap-1.5">
                    <Badge>{sprint.task_count} tasks</Badge>
                    <Badge>{sprint.points_committed} pts in sprint</Badge>
                    {/* Snapshots exist only after completion; before that the
                        live numbers above are the whole story. */}
                    {sprint.status === "completed" && (
                      <Badge color="green">
                        {sprint.completed_points}/{sprint.total_points} pts delivered
                      </Badge>
                    )}
                  </p>
                </div>

                {canWrite && (
                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    {sprint.status === "planned" && (
                      <>
                        <Button onClick={() => start.mutate(sprint.id)} isLoading={start.isPending}>
                          Start
                        </Button>
                        <Button
                          variant="secondary"
                          onClick={() => {
                            setEditing(sprint);
                            setIsFormOpen(true);
                          }}
                        >
                          Edit
                        </Button>
                        <Button variant="ghost" onClick={() => setDeleteTarget(sprint)}>
                          Delete
                        </Button>
                      </>
                    )}
                    {sprint.status === "active" && (
                      <>
                        <Button onClick={() => setCompleteTarget(sprint)}>Complete</Button>
                        <Button
                          variant="secondary"
                          onClick={() => {
                            setEditing(sprint);
                            setIsFormOpen(true);
                          }}
                        >
                          Edit
                        </Button>
                      </>
                    )}
                    {/* A completed sprint offers nothing: it is history that
                        velocity reports read from. */}
                  </div>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      <SprintFormModal
        isOpen={isFormOpen}
        onClose={() => setIsFormOpen(false)}
        projectId={projectId}
        sprint={editing}
      />

      <ConfirmDialog
        isOpen={completeTarget != null}
        onClose={() => setCompleteTarget(null)}
        onConfirm={() =>
          complete.mutate(completeTarget.id, { onSuccess: () => setCompleteTarget(null) })
        }
        isPending={complete.isPending}
        title={`Complete ${completeTarget?.name}?`}
        message="Its points are frozen for the velocity report and any unfinished
          tasks go back to the backlog. A completed sprint cannot be edited or
          reopened."
      />

      <ConfirmDialog
        isOpen={deleteTarget != null}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => remove.mutate(deleteTarget.id, { onSuccess: () => setDeleteTarget(null) })}
        isPending={remove.isPending}
        title={`Delete ${deleteTarget?.name}?`}
        message="Any tasks already pulled into it fall back to the backlog."
      />
    </div>
  );
}
