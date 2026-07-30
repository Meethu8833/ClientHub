import { useEffect, useMemo } from "react";
import { useForm } from "react-hook-form";

import { Button } from "../../../components/ui/Button";
import { Checkbox } from "../../../components/ui/Checkbox";
import { Input } from "../../../components/ui/Input";
import { Modal } from "../../../components/ui/Modal";
import { Select } from "../../../components/ui/Select";
import { PRIORITY_OPTIONS, TASK_STATUS_OPTIONS } from "../../../lib/constants";
import { applyServerErrors, toIdArray } from "../../../lib/forms";
import { useSprints } from "../hooks/useSprints";
import { useTaskMutations } from "../hooks/useTaskMutations";
import { useTasks } from "../hooks/useTasks";

const FIELD_NAMES = [
  "title",
  "description",
  "status",
  "priority",
  "due_date",
  "story_points",
  "estimated_hours",
  "milestone_id",
  "sprint_id",
  "assignee_id",
  "blocked_by_ids",
];

function toFormValues(task) {
  return {
    title: task?.title ?? "",
    description: task?.description ?? "",
    status: task?.status ?? "todo",
    priority: task?.priority ?? "medium",
    due_date: task?.due_date ?? "",
    story_points: task?.story_points ?? "",
    estimated_hours: task?.estimated_hours ?? "",
    milestone_id: task?.milestone?.id ?? "",
    sprint_id: task?.sprint?.id ?? "",
    assignee_id: task?.assignee?.id ?? "",
    blocked_by_ids: task?.blocked_by?.map((t) => String(t.id)) ?? [],
  };
}

// Create + edit for tasks. `project` is the PROJECT DETAIL object — the form
// needs its members and milestones to build the pickers, and the API validates
// against exactly those relationships (an assignee must be a member, a
// milestone must belong to this project).
export function TaskForm({ isOpen, onClose, project, task = null }) {
  const isEdit = task != null;
  const { create, update } = useTaskMutations(project.id);
  const mutation = isEdit ? update : create;

  const { data: sprints } = useSprints(project.id, { enabled: isOpen });
  // Dependency candidates: this project's tasks. One page is plenty for a
  // picker; the count below says so when it isn't.
  const { data: taskPage } = useTasks(
    { project: project.id, page_size: 100, ordering: "title" },
    { enabled: isOpen }
  );

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors },
  } = useForm({ defaultValues: toFormValues(task), mode: "onTouched" });

  useEffect(() => {
    if (isOpen) reset(toFormValues(task));
  }, [isOpen, task, reset]);

  const assigneeOptions = useMemo(
    () =>
      project.members?.map((m) => ({
        value: m.user.id,
        label: `${m.user.name} (${m.role})`,
      })) ?? [],
    [project.members]
  );

  const milestoneOptions = useMemo(
    () => project.milestones?.map((m) => ({ value: m.id, label: m.title })) ?? [],
    [project.milestones]
  );

  // A completed sprint is frozen history — the API refuses new tasks in it, so
  // it must not appear in the picker at all.
  const sprintOptions = useMemo(
    () =>
      sprints
        ?.filter((s) => s.status !== "completed")
        .map((s) => ({ value: s.id, label: `${s.name} (${s.status})` })) ?? [],
    [sprints]
  );

  // Never offer a task as its own blocker — the API rejects it, and the
  // option is meaningless.
  const blockerCandidates = (taskPage?.results ?? []).filter((t) => t.id !== task?.id);

  function onSubmit(values) {
    const payload = {
      title: values.title.trim(),
      description: values.description.trim(),
      status: values.status,
      priority: values.priority,
      due_date: values.due_date || null,
      // "" from a number input means "not estimated", which is null, not 0.
      story_points: values.story_points === "" ? null : Number(values.story_points),
      estimated_hours: values.estimated_hours === "" ? null : values.estimated_hours,
      milestone_id: values.milestone_id === "" ? null : Number(values.milestone_id),
      sprint_id: values.sprint_id === "" ? null : Number(values.sprint_id),
      assignee_id: values.assignee_id === "" ? null : Number(values.assignee_id),
      blocked_by_ids: toIdArray(values.blocked_by_ids),
    };

    mutation.mutate(isEdit ? { id: task.id, ...payload } : payload, {
      onSuccess: () => onClose(),
      onError: (error) => applyServerErrors(error, setError, FIELD_NAMES),
    });
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={isEdit ? `Edit task` : `New task in ${project.name}`}
      size="lg"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="task-form" isLoading={mutation.isPending}>
            {isEdit ? "Save changes" : "Create task"}
          </Button>
        </>
      }
    >
      <form id="task-form" onSubmit={handleSubmit(onSubmit)} noValidate>
        {errors.root && (
          <p
            role="alert"
            className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700
              dark:bg-red-500/10 dark:text-red-300"
          >
            {errors.root.message}
          </p>
        )}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Input
            label="Title *"
            className="sm:col-span-2"
            error={errors.title?.message}
            {...register("title", { required: "A task needs a title." })}
          />

          <Select
            label="Status"
            options={TASK_STATUS_OPTIONS}
            hint="A task with unfinished blockers can only be To do."
            error={errors.status?.message}
            {...register("status")}
          />
          <Select
            label="Priority"
            options={PRIORITY_OPTIONS}
            error={errors.priority?.message}
            {...register("priority")}
          />

          <Select
            label="Assignee"
            placeholder="— Unassigned —"
            options={assigneeOptions}
            hint={
              assigneeOptions.length === 0
                ? "Nobody is on this project's team yet."
                : "Only project members can be assigned."
            }
            error={errors.assignee_id?.message}
            {...register("assignee_id")}
          />
          <Input
            label="Due date"
            type="date"
            error={errors.due_date?.message}
            {...register("due_date")}
          />

          <Select
            label="Milestone"
            placeholder="— None —"
            options={milestoneOptions}
            error={errors.milestone_id?.message}
            {...register("milestone_id")}
          />
          <Select
            label="Sprint"
            placeholder="— Backlog —"
            options={sprintOptions}
            error={errors.sprint_id?.message}
            {...register("sprint_id")}
          />

          <Input
            label="Story points"
            type="number"
            min="0"
            step="1"
            error={errors.story_points?.message}
            {...register("story_points")}
          />
          <Input
            label="Estimated hours"
            type="number"
            min="0"
            step="0.25"
            error={errors.estimated_hours?.message}
            {...register("estimated_hours")}
          />

          <div className="sm:col-span-2">
            <label
              htmlFor="task-description"
              className="block text-sm font-medium text-gray-700 dark:text-gray-200"
            >
              Description
            </label>
            <textarea
              id="task-description"
              rows={3}
              className="mt-1 block w-full rounded-md border-0 px-3 py-2 text-gray-900 shadow-sm
                ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2
                focus:ring-inset focus:ring-indigo-600 sm:text-sm dark:bg-gray-800
                dark:text-gray-100 dark:ring-gray-600 dark:focus:ring-indigo-400"
              {...register("description")}
            />
          </div>

          <fieldset className="sm:col-span-2">
            <legend className="text-sm font-medium text-gray-700 dark:text-gray-200">
              Blocked by
            </legend>
            <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
              This task stays in To do until every task ticked here is done.
            </p>
            {errors.blocked_by_ids && (
              <p role="alert" className="mt-1 text-xs text-red-600 dark:text-red-400">
                {errors.blocked_by_ids.message}
              </p>
            )}
            {blockerCandidates.length > 0 ? (
              <div className="mt-2 max-h-40 space-y-1 overflow-y-auto rounded-md p-2 ring-1 ring-gray-200 dark:ring-gray-700">
                {blockerCandidates.map((candidate) => (
                  <Checkbox
                    key={candidate.id}
                    label={`${candidate.title} (${candidate.status})`}
                    value={String(candidate.id)}
                    {...register("blocked_by_ids")}
                  />
                ))}
              </div>
            ) : (
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                No other tasks in this project yet.
              </p>
            )}
          </fieldset>
        </div>
      </form>
    </Modal>
  );
}
